# Work Orders

Work orders are the input contract for the Go CLI. They are JSON or JSONC
objects with `schema_version: 1`, exactly two providers, one judge, budgets, a
scope policy, and a workflow type.

The fastest way to start is the examples directory:

- [examples/gather.work-order.json](../examples/gather.work-order.json)
- [examples/compare.work-order.json](../examples/compare.work-order.json)
- [examples/analyze.work-order.json](../examples/analyze.work-order.json)
- [examples/review.work-order.json](../examples/review.work-order.json)
- [examples/build.work-order.json](../examples/build.work-order.json)

## Runtime Types

| Type | Purpose |
| --- | --- |
| `gather` | Evidence collection, inventories, source-backed findings. |
| `compare` | Choosing between options or approaches. |
| `analyze` | Root cause, explanation, architecture analysis, synthesis. |
| `build` | Competitive implementation candidates in isolated worktrees. |

`review` is an init recipe only. It writes a `gather` work order with
`facet.id: "code-review"`.

## Common Fields

| Field | Notes |
| --- | --- |
| `schema_version` | Must be `1`. |
| `id` | Non-empty slug. Must not start with the init placeholder `TODO-`. |
| `type` | One of `gather`, `compare`, `analyze`, or `build`. |
| `goal` | Non-empty user-facing goal. |
| `background` | String or array of strings. |
| `providers` | Exactly two provider participants. |
| `judge` | Judge participant; backend/model pair must differ from each provider. |
| `budgets` | Wall-clock, output, heartbeat, and output-cap settings. |
| `scope_policy` | `advisory`, `best_effort`, or `required`. Defaults to `best_effort` when omitted. |
| `facet` | Optional task filter, commonly used for code review. |
| `build` | Required only when `type: "build"`. |

Provider participants require `id`, `backend`, and `model`; provider `scope`
defaults to `mixed` when omitted. Valid backends are `claude` and `codex`.
Valid scopes are `codebase`, `web`, and `mixed`. Build providers cannot use
`web` scope.

## Facets

A facet is a task filter, not a persona. It tells both providers and the judge
what evidence to prioritize.

| Field | Required | Notes |
| --- | --- | --- |
| `id` | yes | Stable slug. Must not duplicate provider ids or reserved ids. |
| `kind` | no | V1 only allows `generic`; omitted defaults to `generic`. |
| `focus` | yes | One-sentence focus. |
| `include` | yes | One to eight strings. |
| `exclude` | no | Zero to eight strings. |
| `notes` | no | Optional project constraints. |

The `code-review` facet is the standard review shape:

```json
{
  "facet": {
    "id": "code-review",
    "kind": "generic",
    "focus": "Find actionable defects introduced or exposed by the change.",
    "include": [
      "correctness bugs and edge cases",
      "security issues with concrete data-flow or control-flow evidence",
      "user-visible regressions",
      "missing or misleading tests for changed behavior"
    ],
    "exclude": [
      "style-only preferences without project convention evidence",
      "large rewrites unrelated to the changed behavior",
      "speculation without file:line evidence"
    ]
  }
}
```

## Budgets

Budgets control runner limits:

| Field | Meaning |
| --- | --- |
| `wall_clock_seconds` | Maximum wall-clock time for provider or verifier execution. |
| `max_output_bytes` | Retained output cap. |
| `heartbeat_seconds` | Heartbeat cadence. Defaults to `60` if omitted. |
| `output_cap_grace_seconds` | Grace period after cap. Defaults to `10` if omitted. |
| `max_output_overrun_bytes` | Extra observed bytes before hard stop. Defaults to `max_output_bytes` if omitted. |

Plugin drafts currently use 900-second research budgets and 1200-second build
budgets.

## Build Spec

Build work orders require a `build` object.

| Field | Notes |
| --- | --- |
| `base_ref` | Base commit-ish for detached worktrees. Defaults to `HEAD`. |
| `comparison_goal` | Optional selector guidance for comparing patches. |
| `patch_max_bytes` | Positive max captured patch size. Defaults to `100000`; max is `5000000`. |
| `verify` | Non-empty verifier list with at least one gate verifier. |

Verifier fields:

| Field | Notes |
| --- | --- |
| `id` | Non-empty slug. |
| `kind` | `gate` or `metric`; defaults to `gate`. |
| `argv` | Non-empty string array. First element must be a command path without whitespace. |
| `wall_clock_seconds` | Required positive integer. |
| `max_output_bytes` | Required positive integer. |
| `metric` | Required only for metric verifiers. |

Metric verifier specs require `name`, `direction` (`lower` or `higher`), and
`min_delta_percent`; `noise_floor_percent` is optional. Metric commands should
print a JSON object as the last non-empty stdout line with the metric name as a
finite numeric field.

Verifier commands are the shared measuring stick. Bakeoff runs the same
predeclared verifier specs against the baseline and each provider candidate, so
the work order should define the official gates and metrics before providers
start editing. Provider-authored tests, probes, or benchmarks can be useful
patch evidence, but they are not decisive unless a human promotes them into the
shared verifier list for a later run.

For performance metrics, prefer a verifier that already handles noise and emits
one final JSON line. In Go projects, that often means repeated benchmark runs
and a statistical comparison such as
[`benchstat`](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat), then a JSON
summary with the configured metric name.

Minimal build shape:

```json
{
  "schema_version": 1,
  "id": "example-build",
  "type": "build",
  "goal": "Implement the requested change.",
  "background": "Acceptance criteria and constraints go here.",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "scope_policy": { "enforcement": "best_effort" },
  "judge": { "backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh" },
  "build": {
    "base_ref": "HEAD",
    "verify": [
      {
        "id": "tests",
        "kind": "gate",
        "argv": ["go", "test", "./..."],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  },
  "budgets": {
    "wall_clock_seconds": 1200,
    "max_output_bytes": 80000
  }
}
```

## Drafting From The Plugin

`/bakeoff:run` drafts clean JSON from natural language. It does not call
`bakeoff init` for generated drafts and does not inherit TODO placeholders.

The plugin must show the full JSON and ask:

```text
Write and run this work order? Reply `yes` to continue, or tell me what to change.
```

Only explicit approval lets the plugin write `./<id>.work-order.json` and run
`bakeoff validate`.
