---
description: Draft, validate, and run Bakeoff work orders
argument-hint: "<work-order-path | request> [--run-id ID] [--out runs] [--base REF] [--diff] [--changed-files] [--quiet] [--keep-worktrees] [--no-triage]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff validate:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff research:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff build:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff rerun:*), Bash(bakeoff validate:*), Bash(bakeoff research:*), Bash(bakeoff build:*), Bash(bakeoff rerun:*), Bash(git status:*), Bash(git diff:*), Bash(git rev-parse:*)
---

# /bakeoff:run

Draft, validate, and run a Bakeoff work order from a path, or one or more work
orders from a natural-language request.

Apply the shared Bakeoff skill contract. Bakeoff is the source of truth for
validation, provider execution, judging, reports, ledgers, and exit codes.

## Preflight

Run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
```

If this exits `2`, stop and direct the user to install Go 1.24+ and run
`/bakeoff:setup`, set `BAKEOFF_GO_BINARY`, or use the optional release-binary
setup path. Do not build from source implicitly in `/bakeoff:run`.

Parse `$ARGUMENTS` before deciding whether this is a path or a request.

Recognized flags:

- `--out <dir>` or `--out=<dir>`
- `--run-id <id>` or `--run-id=<id>`
- `--base <ref>` or `--base=<ref>`
- `--diff`
- `--changed-files`
- `--quiet`
- `--keep-worktrees`
- `--no-triage`

Remove recognized flags from the request before classification. Unknown flags
are errors unless the user clearly intended them as natural language text.

Route flags by final type:

- pass `--out`, `--run-id`, and `--quiet` to either `bakeoff research` or
  `bakeoff build`;
- pass `--base`, `--diff`, and `--changed-files` only to
  `bakeoff research`;
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

After task fit passes or is confirmed, check for explicit multi-lens review
requests before the generic clean-split check. Do not propose a split or
multi-lens run in the same response as a task-fit warning.

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
is otherwise valid. If the user accepts, draft every part separately. Before
writing anything, show a compact review preview for each part, then list all
filenames and commands. Include the full JSON blocks only when the combined
draft is still readable: at most 120 lines and at most 10 KB. For longer split
drafts, say the full JSON is verbose and can be printed with `show`.

```text
Draft work orders:
1. <part-1-id> (<type>) -> ./<base-id>.part-1.work-order.json
   Goal: <brief goal>
   Providers: <provider summary>; judge: <judge summary>
2. <part-2-id> (<type>) -> ./<base-id>.part-2.work-order.json
   Goal: <brief goal>
   Providers: <provider summary>; judge: <judge summary>

Files to write:
- ./<base-id>.part-1.work-order.json
- ./<base-id>.part-2.work-order.json

Commands to run:
- bakeoff <research|build> ./<base-id>.part-1.work-order.json ...
- bakeoff <research|build> ./<base-id>.part-2.work-order.json ...

Write these files and run them one after another? Reply `write and run` to
continue, reply `show` to print the full JSON, or tell me what to change.
```

One approval covers only the currently shown set. If the user changes any part,
show the final set again with the same preview rules before asking for
approval. If the user replies `show`, print the full JSON for every part and
ask the same approval question again.

For split work orders, derive one base slug from the original request. Append
`.part-N` to each work-order `id`, filename, and supplied `--run-id` value. If
no run id was supplied, let the CLI use the part work-order ids. Apply filename
and run-id collision policy after appending `.part-N`; do not overwrite exact
files unless the user explicitly asks.

After split approval, write all files, validate all files, and only then run
the parts sequentially. If any validation fails, run no parts; surface the
validation error verbatim, repair the affected JSON, show the final set again
with the same preview rules, and ask for approval again. `bakeoff validate`
warnings are advisory; preserve them in the summary when relevant, but do not
stop the split sequence when validation exits successfully. Route each part by
its own `type`: `build` uses
`bakeoff build`; `gather`, `compare`, and `analyze` use `bakeoff research`.
Apply the same mode-specific flag routing to each part. Continue after exit
`0` or `3`. Stop on exit `1`, `2`, `130`, interruption, or command failure,
summarize completed parts and the failed part, and ask before running any
remaining parts.

Summarize split runs independently. Do not produce an overall winner, merged
patch, merged answer, or cross-run synthesis unless the user asks for that as a
separate follow-up. Multi-lens review has its own bounded summary rule below;
generic split runs remain independent.

## Multi-Lens Review

Use this path only for review-shaped natural-language requests that explicitly
ask for separate lenses or separate review passes. Do not add
`/bakeoff:review-swarm` in v1, and do not create a batch work-order schema.
Plain review remains one normal `type: "gather"` work order with
`facet.id: "code-review"`.

Trigger phrases include:

- `multi-lens`
- `review swarm`
- `with separate lenses`
- `separate review passes`
- `run security and performance as separate reviews`
- `security, performance, and UX lenses`

Do not trigger multi-lens just because a normal review mentions multiple
concerns. "review this for security and tests" drafts one normal review.
"review this with security and tests as separate lenses" drafts two lens runs.

Run the task-fit gate before lens selection. If the review target is not
bounded by a branch, PR, diff, file set, or local changes, stop with the usual
"this may not need Bakeoff" warning and do not ask for lenses yet.

If the user asks for multi-lens review without naming lenses, ask:

```text
Which 2-3 lenses should I run? Common choices are correctness/tests, security,
performance, UX/frontend behavior, and maintainability.
```

Default support is 2-3 lenses. For more than 3, warn and ask the user to narrow
or explicitly approve all:

```text
That would run <N> separate review runs. I recommend narrowing this to 2-3
lenses unless you really want the extra cost and summary volume. Tell me which
lenses to keep, or say `run all lenses`.
```

Recognized lens presets:

| Lens slug | Synonyms and examples | Focus |
| --- | --- | --- |
| `correctness` | correctness, bugs, behavior, edge cases, error handling, data correctness | Changed behavior, edge cases, data correctness, error handling. |
| `tests` | tests, test coverage, regression tests, missing tests, stale tests | Missing, misleading, or stale tests for changed behavior. |
| `security` | security, auth, authn, authz, injection, SQL injection, XSS, CSRF, secrets, data exposure, trust boundary | Concrete auth, injection, secrets, trust-boundary, and unsafe data-flow risks. |
| `performance` | performance, perf, latency, memory, resource use, scaling, database queries, N+1 | Changed hot paths, resource use, repeated work, avoidable I/O, and scaling risks. |
| `ux` | UX, frontend, UI, accessibility, a11y, copy, loading states, error states, responsive behavior | User-visible regressions, accessibility, copy/state mismatch, loading/error behavior. |
| `maintainability` | maintainability, readability, coupling, architecture risk, migration risk | Defect-prone structure, confusing ownership, fragile coupling, migration risks. |
| `reliability` | reliability, resilience, concurrency, races, retries, timeouts, idempotency | Concurrency, retries, timeouts, idempotency, failure handling, resilience risks. |

Map `SQL injection` to `security` with SQL injection called out in background.
Map `accessibility` to `ux`. Unknown narrow lenses are allowed as custom safe
kebab slugs, such as `billing-invariants`. Ask one clarification question for
vague unknown lenses such as `quality`, `architecture`, `stuff`, or
`everything`.

For each selected lens, draft one normal review work order. Use
`type: "gather"`, `facet.id: "code-review"`, the normal review providers,
judge, budgets, scope policy, and review-context flags. Add lens-specific
`goal`, `background`, `facet.focus`, `facet.include`, and `facet.exclude`.
Keep automatic code-review triage enabled unless the user passes `--no-triage`
or clearly asks to run without triage.

Derive one base slug from the request or supplied `--run-id`. Append the lens
slug as the final semantic component for work-order ids, filenames, and run
ids: `<base>.<lens>`. Examples:

```text
review-auth.security.work-order.json      --run-id review-auth.security
review-auth.performance.work-order.json   --run-id review-auth.performance
review-auth.ux.work-order.json            --run-id review-auth.ux
```

If a work-order filename or run directory already exists, append a numeric
collision suffix after the lens slug and use the same stem for both file and
run id, for example `review-auth.security-2.work-order.json` and
`--run-id review-auth.security-2`. Never use `.part-N` names for multi-lens
review.

Before writing files, show a compact preview. Use user-facing terms such as
"reviewers", "merge", "verification", and "review settings"; reserve "facet",
"judge", and `type: "gather"` for shown JSON or implementation notes. Do not
print full JSON by default.

```text
This will run <N> separate review runs:

1. Security review
2. Performance review
3. UX/frontend behavior review

Each run asks the same two reviewers to inspect the same change from one lens,
then merges and verifies that lens's findings.

Cost note: this is about <N>x a normal review. With the current 900s default
budget, each lens can reserve up to about 45 minutes worst-case (reviewers,
merge, verification). <N> lenses can therefore reserve up to about
<computed-total> minutes worst-case, though typical runs may finish sooner.

Verification is on for each lens by default. Synthesis is not automatic; after
the runs finish I will summarize the lens results and ask whether you want one
prioritized fix plan.

Write, validate, and run these one after another? Reply `write and run`, reply
`show` to print the full JSON, or tell me what to change.
```

When budgets are not the 900-second research default, compute the worst-case
from `wall_clock_seconds`: one worker phase, one merge phase, and one
verification phase per lens when triage is enabled. The two provider reviews
run in parallel, so do not double-count the worker phase. If `--no-triage` is
set, omit the verification phase and state that findings will be raw and
unverified.

Use `write and run` as the multi-lens approval phrase. If the user replies
`show`, print full JSON only when the combined draft fits the existing
120-line / 10 KB budget; otherwise offer `show <lens>` or ask for approval to
write the files.

After approval, write all lens files, validate every file, and only then run
the lens runs sequentially. Route every lens through `bakeoff research`:

```text
bakeoff research <lens-work-order> --run-id <base>.<lens> [--out <dir>] [--base <ref>] [--diff] [--changed-files] [--quiet] [--no-triage]
```

Continue after exit `0`. Treat exit `3` as a completed but unusual research
handoff only if it occurs; mark the lens untriaged unless triage artifacts
exist. Stop on validation failure, exit `1`, exit `2`, exit `4`, exit `130`,
interruption, or command failure. Summarize completed and failed lenses before
asking whether to continue.

After all completed lens runs finish, read artifacts when present:

- `report.md`
- `decision.json`
- `triage/final.json`
- `triage/triage.md`
- `triage/source_finding_filter.json`

Write a markdown summary to `<out>/<base>.multi-lens-summary.md`, applying the
same numeric collision policy as lens run ids. The summary and final response
must include each lens, run id, report path, triage path/state, run status,
triage counts when available (`real_issue`, `needs_repro`, evidence gaps, false
positives, deferred, documented, and ignored items), most actionable findings
grouped by lens, overlapping themes, clean lenses, caveats for untriaged or
failed runs, `bakeoff show` commands, and the persisted summary path. If triage
was disabled, artifacts are missing, or triage was only recommended, say
findings are raw and unverified.

Do not synthesize automatically. Ask: "Want a synthesis pass that dedupes these
verified lens results into one prioritized fix plan?" If accepted, draft a
normal `type: "analyze"` work order over the completed reports and triage
files. It must not invent new findings; it should prefer verified `real_issue`
and `needs_repro` items, preserve source lens and run id, merge duplicates only
when evidence and changed behavior match, and produce one prioritized
remediation plan.

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

Before approval, show a compact review preview instead of dumping raw JSON by
default. Include the id and type, planned file path, providers, judge, budget,
scope policy, goal, a brief background summary, and the command that will run.
Include the full JSON in a fenced `json` block only when the draft is still
readable: at most 120 lines and at most 10 KB. For longer drafts, say the full
JSON is verbose and can be printed with `show`; still show the planned
`./<id>.work-order.json` path.

Ask:

```text
Write, validate, and run this work order? Reply `yes` to continue, reply `show` to print the full JSON, or tell me what to change.
```

Only explicit affirmative replies such as `yes`, `y`, `approve`, `run it`, or
`write and run` count. If the user replies `show`, print the full JSON and ask
the same approval question again. If the user edits, asks a question, or
replies ambiguously, revise or clarify and show the updated preview before
writing.

After approval, write only `./<id>.work-order.json`, applying the collision
policy from the shared skill. Never overwrite an existing work-order file
unless the user explicitly asks.

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" validate <path>
```

Surface validation errors verbatim. Repair the JSON, show the updated preview
with the same rules, and revalidate only after approval.

## Execution And Summary

Default interactive runs keep CLI heartbeats. Use `--json --quiet` only when
the user asks for quiet or machine-readable output.

On exit `0`, `3`, or `4`, read the run artifacts and summarize. Exit `3` means
a completed run with unresolved disagreement, not a launcher failure. Exit `4`
means the decision is incomplete because the judge failed or did not converge;
provider artifacts are durable.

When exit `4` is paired with all providers reporting `ok` or
`ok_after_format_retry` and a failed judge status, make the first recommended
next action:

```bash
bakeoff rerun <run-id> --judge-only
```

Mention a normal full `bakeoff rerun <run-id>` only as a secondary option.

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
