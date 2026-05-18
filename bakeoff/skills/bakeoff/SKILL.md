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
