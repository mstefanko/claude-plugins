# Bakeoff

Run the same research, review, analysis, or implementation challenge through
Claude and Codex, then let the Bakeoff CLI judge the artifacts and write a
replayable ledger.

Bakeoff is CLI-first. The Claude Code plugin is intentionally thin: it drafts or
inspects work orders, invokes `bakeoff`, and summarizes the resulting artifacts.
Validation, provider execution, judging, patch capture, reports, triage, and
exit codes belong to the Go CLI.

## What This Does

- Runs two-provider research bakeoffs for gathering, comparing, analyzing, and
  code-review facets.
- Runs competitive build bakeoffs in isolated provider worktrees, gates them
  with verifiers, captures candidate patches, and selects a winner when gates,
  metrics, or swapped judging agree.
- Writes auditable run ledgers under `runs/<run-id>/`.
- Keeps build output as handoff material: the report plus the selected provider
  patch artifact. It does not apply, merge, rewrite, commit, or publish patches.

## Prerequisites

- Claude Code with this plugin installed and reloaded.
- Source installs need Go on `PATH` unless `dist/bakeoff` already exists or
  `BAKEOFF_GO_BINARY` points at a compatible executable Bakeoff binary.
- Provider runs require authenticated `claude` and `codex` CLIs through their
  normal login/session flows.
- `git` is required for code-review context and competitive build worktrees.

Provider auth belongs to provider CLIs. Do not place API keys, tokens, or other
secrets in work orders, background text, generated context, prompts, summaries,
or plugin-written files.

## Install

If the marketplace is not already registered, add it from this checkout:

```text
/plugin marketplace add mstefanko-plugins /Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins
```

Install or refresh the plugin:

```text
/plugin marketplace update mstefanko-plugins
/plugin install bakeoff@mstefanko-plugins
/reload-plugins
```

Then run the first-readiness check:

```text
/bakeoff:quickstart
```

## Quick Start

```text
/bakeoff:quickstart
/bakeoff:run review this diff against main
/bakeoff:run compare these two approaches
/bakeoff:run build competing fixes for this failing test
```

`/bakeoff:run` accepts either a work-order path or natural language. When it
drafts JSON from a request, it shows the full work order and waits for an
explicit approval before writing or running it.

## Commands

| Command | Purpose |
| --- | --- |
| `/bakeoff:quickstart` | Build or find the CLI and run a readiness check without provider auth probes. |
| `/bakeoff:run <path | request>` | Validate and run an existing work order, or draft one from natural language. |
| `/bakeoff:inspect [latest|run-id]` | Inspect existing ledgers, reports, decisions, triage, and build handoff artifacts. |
| `/bakeoff:doctor [--skip-auth-probe] [--build] [--quiet]` | Check provider and host readiness. `--build` runs live edit probes. |
| `/bakeoff:uninstall` | Remove Bakeoff-owned plugin state, then instruct you to run the manual plugin uninstall command. |

The underlying CLI is still available:

```bash
bin/bakeoff --help
bin/bakeoff doctor --skip-auth-probe
```

## Work-Order UX

`/bakeoff:run` infers the work-order type:

- implementation candidates or competing patches -> `type: "build"`;
- review/audit/check a PR, branch, diff, or local changes -> `type: "gather"`
  with `facet.id: "code-review"`;
- compare options, vendors, APIs, designs, or approaches -> `type: "compare"`;
- root cause, explanation, design analysis, or synthesis -> `type: "analyze"`;
- fact-finding, inventory, source gathering, or research -> `type: "gather"`.

Code review is not a separate work-order type. It is a gather work order with a
`code-review` facet. Review runs can ask the CLI to capture read-only git
context with flags such as `--base main --diff`.

Generated plugin drafts use clean JSON with explicit providers, judge, budgets,
and `scope_policy.enforcement: "best_effort"`. They do not call `bakeoff init`
or inherit TODO placeholders. The CLI validates every work order before a run.

If `runs/<id>` or `./<id>.work-order.json` already exists, `/bakeoff:run`
chooses a non-conflicting id or filename. It never overwrites a work-order file
unless you explicitly ask.

## Competitive Build Handoff

Build mode creates isolated worktrees from `build.base_ref`, verifies the
baseline, launches codebase-scoped providers, captures eligible patches, runs
verifiers, and selects a winner when the decision rules are conclusive.

For competitive build runs, the desired output is:

- the Bakeoff report;
- the selected provider patch artifact when there is a canonical winner:
  `runs/<run-id>/providers/<winner>/build/diff.patch`.

The plugin stops there. It does not run `git apply`, `git am`, `patch`,
`git checkout`, `git switch`, `git commit`, `gh pr create`, or any equivalent
apply or publish step. It also does not merge, cherry-pick, rewrite, combine, or
synthesize a third patch from provider outputs. Any follow-up implementation is
a separate explicit request and needs fresh verification before being treated as
ready.

## Config And Environment

- `CLAUDE_PLUGIN_ROOT`: set by Claude Code, used by commands and scripts.
- `BAKEOFF_GO_BINARY`: optional user-facing override to a compatible Bakeoff
  binary.
- `BAKEOFF_PLUGIN_ROOT`: developer/test override for the shared launcher.
- `CODEX_PLUGIN_ROOT`: Codex-side launcher override, not a Claude user knob.
- `NO_COLOR`: standard CLI color suppression.

`bin/bakeoff` resolves the plugin root, then runs `BAKEOFF_GO_BINARY`,
`dist/bakeoff`, or `go run ./cmd/bakeoff` from a checkout. The
`scripts/bakeoff-ensure-cli` helper makes that source-install contract explicit
and builds `dist/bakeoff` when Go is available.

## State And Artifacts

Common state:

- `runs/<run-id>/`: work-order, providers, judge, decision, report, meta, and
  manifest artifacts.
- `*.work-order.json`: generated work-order drafts in the current directory.
- `review-context.md` and `review-context.json`: generated code-review context
  when requested.
- `runs/<run-id>/providers/<winner>/build/diff.patch`: selected build patch
  artifact when there is a canonical winner.
- Retained build worktrees only when `--keep-worktrees` is used, under the
  `build-context.json.worktree_parent_path` value, usually
  `runs/<run-id>/worktrees/<provider-id>`.
- `dist/bakeoff`: local CLI binary built by quickstart or ensure.
- `~/.claude/plugins/cache/mstefanko-plugins/bakeoff`: Claude plugin cache.

Repo-root `./bakeoff` and `./bakeoff-go` are development artifacts. They are not
plugin state and are not removed by `/bakeoff:uninstall`.

## Troubleshooting

Run:

```text
/bakeoff:doctor --skip-auth-probe
```

Use this when you only want local readiness: CLI, `git`, provider binaries,
cwd writability, default models, and scope controls.

Run:

```text
/bakeoff:doctor --build
```

Use this before competitive builds. It runs live provider edit probes in
temporary workspaces and reports launch, auth/session, sandbox, network, or
filesystem readiness failures.

If quickstart cannot find a CLI, install Go, install a plugin package that
contains `dist/bakeoff`, or set `BAKEOFF_GO_BINARY` to a compatible executable.

If a provider run fails auth, log in with the provider CLI directly. Bakeoff
does not own or store provider credentials.

Exit code `3` means the run completed but the judge decision was unresolved. It
is a completed Bakeoff handoff, not a launcher failure.

## Uninstall

Run:

```text
/bakeoff:uninstall
```

The command removes Bakeoff-owned state and cache, then tells you to finish with:

```text
/plugin uninstall bakeoff@mstefanko-plugins
```

The uninstall script does not remove provider CLIs, provider auth/session files,
git branches, user commits, non-Bakeoff `runs/` content, or development binaries
such as `./bakeoff` and `./bakeoff-go`.

## Development

```bash
go run ./cmd/bakeoff --help
go test ./...
go test -race ./...
python3 scripts/parity-go.py
```

Build a local release binary:

```bash
mkdir -p dist
go build -o dist/bakeoff ./cmd/bakeoff
```

Smoke the plugin helpers:

```bash
scripts/bakeoff-ensure-cli --check
scripts/bakeoff-ensure-cli
bin/bakeoff doctor --skip-auth-probe --json
```

The legacy Python CLI has been removed. Remaining Python files under `scripts/`
and `tests/parity/fakes/` are test harness utilities.
