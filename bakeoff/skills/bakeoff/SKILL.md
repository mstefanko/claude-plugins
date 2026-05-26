---
name: bakeoff
description: "USE THIS SKILL when the user says bakeoff, /bakeoff, run a bakeoff, compare providers, inspect a bakeoff run, code-review bakeoff, or competitive build bakeoff."
version: "0.0.0"
allowed-tools: "Read,Write,Edit,Glob,Grep,Bash"
author: mstefanko
---

# Bakeoff

Bakeoff is the source of truth. Do not reimplement CLI behavior in prompt
instructions, and do not place secrets in work orders, background text,
generated context, prompts, summaries, or plugin-written files.

Claude's plugin-side role is narrow: draft work orders, invoke `bakeoff`,
inspect durable artifacts, and summarize results. The Go CLI owns validation,
provider execution, judging, patch capture, reports, ledgers, triage, and exit
codes.

## Routing

- `/bakeoff:run` must use the `bakeoff-run` skill. If that skill is missing,
  stop and report an incomplete plugin install or routing failure.
- `/bakeoff:inspect` inspects existing run artifacts through the command doc;
  it never applies, edits, combines, commits, branches, or publishes patches.
- `/bakeoff:escalate` invokes one explicit non-build post-run escalation. It
  must preview with `--dry-run` unless the user already approved a specific
  mode.
- `/bakeoff:history`, `/bakeoff:doctor`, `/bakeoff:setup`, and `/bakeoff:uninstall`
  follow their command docs and the global rules here.
- For any Bakeoff command, do not call provider CLIs directly for the user task;
  only the Bakeoff CLI may launch providers.

## Work-Order Classification

Infer the most likely type from the user's request unless ambiguity changes
safety or cost:

- candidate implementations, patches, code edits, failing-test fixes, or "pick
  a winning patch" -> `type: "build"`;
- review, audit, check a PR, branch, diff, or local changes -> `type: "gather"`
  with `facet.id: "code-review"`;
- compare options, vendors, APIs, designs, or approaches -> `type: "compare"`;
- root cause, explanation, design analysis, or synthesis -> `type: "analyze"`;
- fact-finding, inventory, source gathering, or research -> `type: "gather"`.

`review` is not a work-order type. It is `type: "gather"` plus a
`code-review` facet. "Build a comparison/report/matrix" is research unless the
user asks providers to edit code or produce candidate patches. If build mode
would launch code-editing providers and the prompt does not clearly authorize
implementation, ask one clarification question.

## Permission Semantics

Command `allowed-tools` frontmatter is packaged convenience: it pre-approves
listed tools and does not deny all other tools by itself.

`Write` and `Edit` in `/bakeoff:run` are only for drafting work-order files and
plugin-created multi-lens summary files. They are never permission to apply,
rewrite, combine, or publish provider patches after a build.

Do not pre-approve or run `git apply`, `git am`, `git commit`, `git switch`,
`git checkout`, `gh pr create`, provider CLIs directly, or broad mutation
commands for `/bakeoff:run`.

Bakeoff build mode creates isolated worktrees. The plugin does not create
branches, manage worktrees, or retain implementation sandboxes. Pass
`--keep-worktrees` only when the user asks for it.

For competitive build handoff, report the Bakeoff decision plus the selected
provider patch artifact only when `decision.json.canonical_winner` is non-null:
`<out>/<run-id>/providers/<winner>/build/diff.patch`. Do not apply, merge,
cherry-pick, synthesize, commit, branch, push, open a PR, or edit source files
from provider output without a separate explicit user request and fresh
verification.

Escalation never applies to build runs and never creates a third patch. Witness
and dispute escalation are advisory; independent compare/analyze escalation
uses one synthesis judge and must not be described as position-swapped.

## Environment And Auth

- `CLAUDE_PLUGIN_ROOT`: canonical Claude command-time plugin root.
- `BAKEOFF_GO_BINARY`: optional path to a compatible executable Bakeoff binary.
- `BAKEOFF_PLUGIN_ROOT`: developer/test override for the shared launcher.
- `CODEX_PLUGIN_ROOT`: Codex-side launcher override, not a Claude user knob.
- `NO_COLOR`: standard CLI color suppression.

Provider auth belongs to provider CLIs. Do not add plugin auth claims and do not
write API keys or session tokens into work orders, context, prompts, summaries,
or plugin-managed files.
