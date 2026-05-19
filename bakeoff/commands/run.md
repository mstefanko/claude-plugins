---
description: Draft, validate, and run Bakeoff work orders
argument-hint: "<work-order-path | request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff validate:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff research:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff build:*), Bash(bakeoff validate:*), Bash(bakeoff research:*), Bash(bakeoff build:*), Bash(git status:*), Bash(git diff:*), Bash(git rev-parse:*)
---

# /bakeoff:run

Draft, validate, and run a Bakeoff work order from a path, or one or more work
orders from a natural-language request.

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

Existing work-order paths do not enter this flow. For natural-language input,
run the task-fit check before silent type inference or JSON drafting.

If the request is a weak fit, stop and warn instead of drafting. Use the phrase
"this may not need Bakeoff" and name the reason:

- mechanical edits or formatter-only work;
- build requests with no meaningful verifier or acceptance criterion;
- vague requests without a target, scope, or evidence standard;
- review requests without a bounded branch, PR, diff, file set, or local-change
  scope;
- RCA or analyze requests without a concrete symptom, log, reproduction,
  trace, file set, incident, or command to inspect;
- highly sequential planning where each answer depends on the prior result.

Recommended wording:

```text
This may not need Bakeoff because <reason>. Bakeoff usually pays off when two
independent providers can produce meaningfully different evidence or patches,
and when there is a verifier, scope, or citation standard. Reply `draft anyway`
to continue with Bakeoff, or tell me how to narrow it.
```

The warning is advisory. A clear same-turn phrase such as `draft anyway` or
"run Bakeoff anyway" satisfies it for that turn only. Do not add a task-fit
flag or persistent opt-out. If the user narrows the request, re-run the check.
Task-fit confirmation does not waive required work-order fields; for example,
build mode still needs a gate verifier before a valid work order can run.

After task fit passes or is confirmed, run the clean-split check before
drafting. Do not propose a split in the same response as a task-fit warning.

Suggest a split only when the request has 2-3 obvious independent parts, each
part has its own goal and evidence surface or verifier, no part depends on
another Bakeoff result, shared context fits in 1-2 repeatable sentences, and
every part maps to an existing work-order type. Do not split existing
work-order paths, sequential plans, more than three parts, under-scoped parts,
or anything needing shared state, a final merge agent, or cross-run synthesis.

Use this wording shape:

```text
This looks like it cleanly splits into <N> independent Bakeoff work orders:

1. <part one goal>
2. <part two goal>
3. <part three goal>

Each can run separately with the same shared context, and none depends on
another result. Reply `split` to draft separate work orders, or tell me to keep
it as one.
```

If the user declines the split, continue with one normal work order if the task
is otherwise valid. If the user accepts, draft every part separately. Show a
one-line summary above each full JSON block, then list all filenames and
commands before writing anything:

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

One approval covers only the currently shown set. If the user changes any part,
show the full final set again before asking for approval.

For split work orders, derive one base slug from the original request. Append
`.part-N` to each work-order `id`, filename, and supplied `--run-id` value. If
no run id was supplied, let the CLI use the part work-order ids. Apply filename
and run-id collision policy after appending `.part-N`; do not overwrite exact
files unless the user explicitly asks.

After split approval, write all files, validate all files, and only then run
the parts sequentially. If any validation fails, run no parts; surface the
validation error verbatim, repair the affected JSON, show the full final set,
and ask for approval again. Route each part by its own `type`: `build` uses
`bakeoff build`; `gather`, `compare`, and `analyze` use `bakeoff research`.
Apply the same mode-specific flag routing to each part. Continue after exit
`0` or `3`. Stop on exit `1`, `2`, `130`, interruption, or command failure,
summarize completed parts and the failed part, and ask before running any
remaining parts.

Summarize split runs independently. Do not produce an overall winner, merged
patch, merged answer, or cross-run synthesis unless the user asks for that as a
separate follow-up.

For one-work-order drafting, infer the work-order shape silently unless the
ambiguity changes safety or cost.

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
