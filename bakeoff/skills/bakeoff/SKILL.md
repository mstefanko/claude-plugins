---
name: bakeoff
description: "USE THIS SKILL when the user says bakeoff, /bakeoff, run a bakeoff, compare providers, inspect a bakeoff run, code-review bakeoff, or competitive build bakeoff."
version: "0.0.0"
allowed-tools: "Read,Write,Edit,Glob,Grep,Bash"
author: mstefanko
---

# Bakeoff

Use Bakeoff as the source of truth. Do not reimplement Bakeoff behavior in
Claude instructions. Do not place secrets in work orders, background text,
generated context, prompts, summaries, or plugin-written files.

Bakeoff is a thin CLI wrapper surface. Claude may draft work orders, inspect
artifacts, invoke `bakeoff`, and summarize results. The Go CLI owns validation,
provider execution, judging, patch capture, reports, ledgers, triage, and exit
codes.

## Work-Order Classification

Infer the most likely type from the user's request unless ambiguity changes
safety or cost:

- candidate implementations, patches, code edits, failing-test fixes, or
  "pick a winning patch" -> `type: "build"`;
- review, audit, check a PR, branch, diff, or local changes -> `type:
  "gather"` with `facet.id: "code-review"`;
- compare options, vendors, APIs, designs, or approaches -> `type: "compare"`;
- root cause, explanation, design analysis, or synthesis -> `type: "analyze"`;
- fact-finding, inventory, source gathering, or research -> `type: "gather"`.

"Build a comparison/report/matrix" is research unless the user asks providers
to edit code or produce candidate patches. If build mode would launch
code-editing providers and the prompt does not clearly authorize implementation,
ask one clarification question.

`review` is not a work-order type. It is `type: "gather"` plus a
`code-review` facet.

## Task Fit And Clean Splits

Apply these advisory checks only when drafting from natural language. Existing
work-order paths bypass both checks and keep the normal validate-and-run path.

Run the task-fit check after parsing flags and path detection, but before type
inference, JSON drafting, or filename decisions. If the request is a weak fit,
stop and ask for confirmation instead of silently drafting. This is advisory,
not a hard block: a clear same-turn phrase such as `draft anyway` or "run
Bakeoff anyway" satisfies the warning for that turn. Do not add a flag,
persistent preference, or "never warn me again" state.

Use this wording shape:

```text
This may not need Bakeoff because <reason>. Bakeoff usually pays off when two
independent providers can produce meaningfully different evidence or patches,
and when there is a verifier, scope, or citation standard. Reply `draft anyway`
to continue with Bakeoff, or tell me how to narrow it.
```

Weak-fit cases:

- mechanical edits or formatter-only work;
- build requests with no meaningful verifier or acceptance criterion;
- vague requests such as "make it better" without a target, scope, or evidence
  standard;
- review requests without a bounded branch, PR, diff, file set, or local-change
  scope;
- RCA or analyze requests without a concrete symptom, log, reproduction,
  trace, file set, incident, or command to inspect;
- highly sequential planning where each answer depends on the prior result.

Do not warn solely because a request is small or straightforward. Warn only
when Bakeoff is likely to add cost, ambiguity, or risk without better evidence.
If the user narrows the request, re-run the task-fit check on the revised
prompt.

After task fit passes or is explicitly confirmed, run the clean-split check.
Do not propose a split in the same response as a task-fit warning.

Suggest 2-3 separate work orders only when the split is obvious and all of
these are true:

- each subtask has its own goal;
- each subtask has its own evidence surface or verifier;
- no subtask depends on another Bakeoff result;
- shared context fits in 1-2 sentences and can be repeated safely in each work
  order;
- each subtask maps to a normal work-order type: `gather`, `compare`,
  `analyze`, review as `gather` plus `code-review`, or `build`.

Do not suggest a split when there are more than three parts, the parts are
sequential, any part would be under-scoped, the split would require shared
state or cross-run synthesis, or the user supplied a work-order file.

Use this split-proposal wording shape:

```text
This looks like it cleanly splits into <N> independent Bakeoff work orders:

1. <part one goal>
2. <part two goal>
3. <part three goal>

Each can run separately with the same shared context, and none depends on
another result. Reply `split` to draft separate work orders, or tell me to keep
it as one.
```

If the user accepts the split, draft each work order as a separate normal JSON
object. Show a one-line summary above each JSON block, then list the filenames
and commands before asking for one explicit approval:

```text
Files to write:
- ./<base-id>.part-1.work-order.json
- ./<base-id>.part-2.work-order.json

Commands to run:
- bakeoff <research|build> ./<base-id>.part-1.work-order.json ...
- bakeoff <research|build> ./<base-id>.part-2.work-order.json ...

Write these files and run them one after another? Reply `write and run` to
continue, or tell me what to change.
```

Derive one base slug from the original request. Append `.part-N` to each
work-order `id`, filename, and supplied `--run-id` value. If the user did not
pass `--run-id`, let the CLI use the work-order id. Apply the existing run-id
and filename collision policy after appending `.part-N`; do not overwrite exact
files unless the user explicitly asks.

After split approval, write all part files, validate all of them before running
any part, and run them sequentially with the existing CLI commands. Route each
part by its own `type`: `build` uses `bakeoff build`; `gather`, `compare`, and
`analyze` use `bakeoff research`. Apply mode-specific flags to each part.

If any split validation fails, stop before execution, surface the validation
error verbatim, repair the affected JSON, and show the full final set again
before asking for approval. `bakeoff validate` warnings are advisory and do not
stop the split sequence when validation exits successfully. During execution,
continue after exit `0` or `3`; exit `3` is a completed Bakeoff handoff with
unresolved disagreement. Stop the sequence on exit `1`, `2`, `130`,
interruption, or command failure. Summarize completed parts and the failed part
before asking whether to continue.

Do not run a decomposition agent, add a DAG runner, create a batch
work-order-list schema, coordinate shared state across parts, or synthesize an
overall winner, merged patch, or merged answer from split runs. Cross-run
synthesis is a separate user request.

## Drafting Rules

Write clean JSON for plugin drafts. Do not call `bakeoff init` for generated
work orders and do not inherit TODO placeholders.

Every draft should include explicit:

- `schema_version: 1`;
- `id`, as a kebab slug of the user goal;
- `type`, `goal`, and `background`;
- exactly two `providers`;
- `judge`;
- `budgets`;
- `scope_policy.enforcement: "best_effort"`.

Default providers:

- research: Claude Sonnet high and Codex GPT-5.5 high, with scope selected by
  task shape;
- build: both providers use `scope: "codebase"`;
- judge: Claude Opus xhigh.

Research budgets:

```json
{
  "wall_clock_seconds": 900,
  "max_output_bytes": 60000,
  "heartbeat_seconds": 60,
  "output_cap_grace_seconds": 10,
  "max_output_overrun_bytes": 60000
}
```

Build drafts must include:

- `build.base_ref`, defaulting to `HEAD`;
- non-empty `build.verify`;
- at least one verifier with `kind: "gate"`;
- `build.patch_max_bytes: 100000`;
- provider `scope: "codebase"` only.

For metric verifiers, treat `build.verify` as the official verifier suite. If a
metric harness, fixture, golden file, or expected-output file lives in the repo,
list those paths under `build.protected_paths` so provider patches cannot edit
the measuring stick for the current run. Provider-created tests and benchmarks
are useful advisory evidence, but they are not official metrics unless a human
adds them to a later work order.

Build budgets:

```json
{
  "wall_clock_seconds": 1200,
  "max_output_bytes": 80000,
  "heartbeat_seconds": 60,
  "output_cap_grace_seconds": 10,
  "max_output_overrun_bytes": 80000
}
```

Suggested verifier defaults are `wall_clock_seconds: 300` and
`max_output_bytes: 60000` unless the user supplies stricter limits.
For repeated metrics, prefer verifier commands that emit one final aggregate
JSON object with the configured metric value plus `unit`, `n`, `statistic`, and
`method`; set `metric.min_runs` when one-sample decisions should be treated as
inconclusive.

For code-review requests, use read-only git context when useful: `git status`,
`git diff --stat`, `git rev-parse`, and user-specified base refs. Recommend
`bakeoff research <path> --base <ref> --diff` when generated local diff context
is useful. Let the CLI auto-triage code-review reports unless the user passes
`--no-triage`.

## Approval And Filename Collisions

Before writing a natural-language draft, show the full JSON in a fenced code
block and ask:

```text
Write and run this work order? Reply `yes` to continue, or tell me what to change.
```

Only explicit affirmative replies such as `yes`, `y`, `approve`, `run it`, or
`write and run` count. If the user edits, asks a question, or replies
ambiguously, revise or clarify and show the JSON again before writing.

If `runs/<id>` already exists, append `-YYYYMMDD` or the smallest numeric suffix
needed to make the run id unique before showing JSON for approval.

Write only `./<id>.work-order.json`. If that filename exists, do not overwrite
it. Use `./<id>-2.work-order.json`, `./<id>-3.work-order.json`, and so on,
unless the user explicitly asks to replace a file.

## Validation Before Run

Run `bakeoff validate <path>` before `bakeoff research` or `bakeoff build`.

Surface validation errors verbatim. Repair JSON, show the updated JSON to the
user, and revalidate only after approval.

Route existing work-order paths by `type`:

- `type: "build"` -> `bakeoff build <path>`;
- `type: "gather"`, `type: "compare"`, or `type: "analyze"` ->
  `bakeoff research <path>`.

Do not reinterpret missing path-like input as natural language.

## Competitive Build Handoff

For competitive build runs, the desired output is the Bakeoff report plus the
selected provider patch artifact. Stop after reporting the run id, decision,
selection basis, winner, report path, and patch artifact path.

When `decision.json.canonical_winner` is non-null, the selected patch artifact
is `runs/<run-id>/providers/<winner>/build/diff.patch`, or
`<out>/<run-id>/providers/<winner>/build/diff.patch` when `--out` is supplied.
If no canonical winner exists, say there is no selected patch artifact.

Do NOT run `git apply`, `git am`, `patch`, `git checkout`, `git switch`,
`git commit`, `gh pr create`, or any equivalent command to apply or publish the
selected patch.

Do NOT edit, merge, cherry-pick, rewrite, or synthesize a third patch from
provider outputs. Do NOT ask a subagent to combine candidates. Post-run edits,
synthesis, or reimplementation are outside the Bakeoff decision and require a
separate explicit user request plus fresh verification before being treated as
ready.

## Artifact Summary Contract

For every completed run, summarize:

- run id;
- command and exit-code meaning;
- decision kind;
- report path;
- `decision.json` highlights;
- `bakeoff show <run-id>` next command.

For code-review research runs, include relevant triage state and triage artifact
paths. For build runs, include `diagnostics.json` when present and the selected
patch artifact path only when there is a canonical winner.

Exit code `3` means a completed run with unresolved disagreement. Treat it as a
completed Bakeoff handoff, not as a launcher failure.

## Permission Semantics

Command `allowed-tools` frontmatter is a packaged convenience: it pre-approves
listed tools and does not deny all other tools by itself.

`Write` and `Edit` in `/bakeoff:run` are only for drafting work-order files.
They are never permission to apply, rewrite, combine, or publish provider
patches after a build.

Do not pre-approve or run `git apply`, `git am`, `git commit`, `git switch`,
`git checkout`, `gh pr create`, provider CLIs directly, or broad mutation
commands for `/bakeoff:run`.

Bakeoff build mode creates its own isolated worktrees. The plugin does not
create branches, manage worktrees, or retain implementation sandboxes.
`--keep-worktrees` is passed only when the user asks for it.

## Environment Variables

- `CLAUDE_PLUGIN_ROOT`: canonical Claude command-time plugin root.
- `BAKEOFF_GO_BINARY`: optional path to a compatible executable Bakeoff binary.
- `BAKEOFF_PLUGIN_ROOT`: developer/test override for the shared launcher.
- `CODEX_PLUGIN_ROOT`: Codex-side launcher override, not a Claude user knob.
- `NO_COLOR`: standard CLI color suppression.

Provider auth belongs to provider CLIs. Do not add plugin auth claims and do not
write API keys or session tokens into work orders, context, prompts, summaries,
or plugin-managed files.
