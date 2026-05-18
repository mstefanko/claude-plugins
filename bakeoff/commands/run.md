---
description: Draft, validate, and run a Bakeoff work order
argument-hint: "<work-order-path | request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff validate:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff research:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff build:*), Bash(bakeoff validate:*), Bash(bakeoff research:*), Bash(bakeoff build:*), Bash(git status:*), Bash(git diff:*), Bash(git rev-parse:*)
---

# /bakeoff:run

Draft, validate, and run one Bakeoff work order from a path or natural-language
request.

Apply the shared Bakeoff skill contract. Bakeoff is the source of truth for
validation, provider execution, judging, reports, ledgers, and exit codes.

## Preflight

Run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli"
```

Parse `$ARGUMENTS` before deciding whether this is a path or a request.

Recognized flags:

- `--out <dir>` or `--out=<dir>`
- `--run-id <id>` or `--run-id=<id>`
- `--quiet`
- `--keep-worktrees`
- `--no-triage`

Remove recognized flags from the request before classification. Unknown flags
are errors unless the user clearly intended them as natural language text.

Route flags by final type:

- pass `--out`, `--run-id`, and `--quiet` to either `bakeoff research` or
  `bakeoff build`;
- pass `--keep-worktrees` only to `bakeoff build`;
- pass `--no-triage` only to `bakeoff research`;
- stop before execution when a mode-specific flag is supplied for the wrong
  final type.

## Existing Work-Order Path

If the first remaining argument names an existing file, read it and inspect
`type`.

Path-like missing input is an error, not a natural-language request. Treat input
as path-like when it has a path separator, starts with `.`, `~`, or `/`, or ends
in `.json`, `.jsonc`, or `.work-order.json`.

Always run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" validate <path>
```

Then route by `type`:

- `build` -> `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" build <path> [flags]`
- `gather`, `compare`, or `analyze` ->
  `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" research <path> [flags]`

Do not run `bakeoff research` for `type: "build"`, and do not run
`bakeoff build` for research-shaped work orders.

## Natural Language Drafting

Infer the work-order shape silently unless the ambiguity changes safety or cost.

- implementation candidates, competing patches, "build this", "fix this and
  compare", or "pick a winning patch" -> `type: "build"`;
- review/audit/check a PR, branch, diff, or local changes -> `type: "gather"`
  with `facet.id: "code-review"`;
- compare options, vendors, APIs, designs, or approaches -> `type: "compare"`;
- root cause, explanation, design analysis, or synthesis -> `type: "analyze"`;
- fact-finding, inventory, source gathering, or "research" -> `type: "gather"`.

Resolve conflicts conservatively:

- "build a comparison/report/matrix" is research, not build mode, unless the
  user asks for code patches or implementation worktrees;
- if providers must edit code, fix a failing test, or produce competing
  patches, use build mode;
- if build mode would launch code-editing providers and the prompt does not
  clearly authorize implementation, ask one clarification question.

Ask only for missing required pieces:

- build: implementation goal, acceptance criteria, at least one gate verifier,
  and any non-`HEAD` base ref;
- research: missing scope, target, or enough context to cite evidence.

For review-shaped requests, gather read-only git context when useful:

```bash
git status --short
git diff --stat
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
```

Use `git diff` only for bounded context the user asked to review. Recommend
`bakeoff research <path> --base <ref> --diff` when generated review context is
useful.

Draft clean JSON, not a TODO template. Include explicit `schema_version`, `id`,
`type`, `goal`, `background`, `providers`, `judge`, `budgets`, and
`scope_policy.enforcement: "best_effort"`. Reject or repair build work orders
with any provider `scope: "web"`.

Show the full JSON in a fenced `json` block and ask:

```text
Write and run this work order? Reply `yes` to continue, or tell me what to change.
```

Only explicit affirmative replies such as `yes`, `y`, `approve`, `run it`, or
`write and run` count. If the user edits, asks a question, or replies
ambiguously, revise or clarify and show the JSON again before writing.

After approval, write only `./<id>.work-order.json`, applying the collision
policy from the shared skill. Never overwrite an existing work-order file
unless the user explicitly asks.

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" validate <path>
```

Surface validation errors verbatim. Repair the JSON, show it again, and
revalidate only after approval.

## Execution And Summary

Default interactive runs keep CLI heartbeats. Use `--json --quiet` only when
the user asks for quiet or machine-readable output.

On exit `0` or `3`, read the run artifacts and summarize. Exit `3` means a
completed run with unresolved disagreement, not a launcher failure.

The final response must include:

- run id;
- decision kind and exit-code meaning;
- report path;
- relevant triage path/state for research code-review runs;
- `bakeoff show` next command;
- for build runs, the selected patch artifact only when
  `decision.json.canonical_winner` is non-null:
  `<out>/<run-id>/providers/<winner>/build/diff.patch`.

Stop after the Bakeoff handoff. Do not apply patches, create issues, create
branches, commit, push, open PRs, synthesize a third patch, or edit source files
based on provider output unless the user makes a separate explicit request.
