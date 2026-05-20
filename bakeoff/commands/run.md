---
description: Draft, validate, and run Bakeoff work orders
argument-hint: "<work-order-path | request> [--run-id ID] [--out runs] [--base REF] [--diff] [--changed-files] [--quiet] [--keep-worktrees] [--no-triage] [--no-repo-layout]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff draft-build:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff validate:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff research:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff build:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff rerun:*), Bash(bakeoff draft-build:*), Bash(bakeoff validate:*), Bash(bakeoff research:*), Bash(bakeoff build:*), Bash(bakeoff rerun:*), Bash(git status:*), Bash(git diff:*), Bash(git rev-parse:*)
---

# /bakeoff:run

Draft, validate, and run a Bakeoff work order from a path, or one or more work
orders from a natural-language request.

Apply the shared Bakeoff skill contract. Bakeoff is the source of truth for
validation, provider execution, judging, reports, ledgers, and exit codes.

## Invocation Contract

The user invoked `/bakeoff:run`; do not satisfy the underlying request inline.
The required path is to preflight, classify the input, draft or validate a work
order, get any required approval, run `bakeoff validate`, and then run
`bakeoff research` or `bakeoff build`.

Before a Bakeoff run starts, the only allowed stops are CLI preflight failure,
missing path-like input, unknown or wrong-mode flags, a task-fit warning,
missing required draft fields, split or multi-lens clarification or approval,
or validation failure needing repair. In those stops, ask or advise only. Do
not perform the requested review, analysis, comparison, or implementation
yourself.

Local file and git reads are allowed only to draft the work order, validate
scope, or summarize Bakeoff artifacts. Do not read target files and produce
substantive findings as a substitute for the CLI.
Do not call provider CLIs directly for the user task; only the Bakeoff CLI may
launch providers for this command.

## Preflight

Run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
```

If this exits `2`, stop and direct the user to install Go 1.24+ and run
`/bakeoff:setup`, set `BAKEOFF_GO_BINARY`, or use the optional release-binary
setup path. Do not build from source implicitly in `/bakeoff:run`.

If this exits with any other non-zero status, stop, surface the check output as
an unexpected CLI resolution failure, and direct the user to `/bakeoff:doctor`.
Do not draft, validate, or run a work order until preflight succeeds.

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
- `--no-repo-layout`

Remove recognized flags from the request before classification. Unknown flags
are errors unless the user clearly intended them as natural language text.
If no path or natural-language request remains after flag parsing, stop and ask
the user for a work-order path or request. Do not infer a task from flags alone.

Route flags by final type:

- pass `--out`, `--run-id`, and `--quiet` to either `bakeoff research` or
  `bakeoff build`;
- pass `--base`, `--diff`, and `--changed-files` only to
  `bakeoff research`;
- pass `--keep-worktrees` only to `bakeoff build`;
- pass `--no-triage` only to `bakeoff research`;
- pass `--no-repo-layout` to either `bakeoff research` or `bakeoff build`;
- stop before execution when a mode-specific flag is supplied for the wrong
  final type.

## Existing Work-Order Path

If the first remaining argument names an existing file, read it and inspect
`type`.

Path-like missing input is an error, not a natural-language request. Treat input
as path-like when it has a path separator, starts with `.`, `~`, or `/`, or ends
in `.json`, `.jsonc`, or `.work-order.json`.
If input is path-like but missing or invalid, report the path error only; do not
reinterpret the remaining words as a natural-language request or answer them
inline.

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

## Drafting Invariants

These invariants apply to **every** natural-language drafting path (fast
path, careful path, split, multi-lens). They are not fast-path-specific.

### Required-Field Synthesis Guidance (Advisory)

If the request omits any of the following, the model **should** prefer
asking the missing question(s) verbatim over synthesizing a default.

**This is prompt-level guidance, not a Go-side semantic gate.** The
clean final-contract dogfood showed the checklist and R1.6 refactor
edge case work on the tested prompt shapes — see
[drafting-fast-path-experiment-log-2026-05-20.md](../docs/drafting-fast-path-experiment-log-2026-05-20.md).
The operator's preview-then-approve flow remains the safety net for
untested wording variants.

The guidance below is worth following: synthesized AC and verifiers
degrade provider-run quality even when the JSON validates. If a field
is missing, ask rather than filling in a plausible default.

Non-synthesizable fields:

- build acceptance criteria;
- build gate verifier (the command and its pass condition);
- metric verifier protected paths (when the request asks for a benchmark);
- edit scope when no file, package, route, diff, or local-change scope
  is named.

This rule supersedes any "infer silently" or "use sensible defaults"
language elsewhere in this file. Synthesis-friendly defaults are limited
to: provider pair, judge, budgets, `scope_policy.enforcement`,
`build.base_ref` when omitted, and the JSON-skeleton field shapes in the
canonical skeletons below.

#### Mechanical Pre-Flight Checklist

Before deciding fast-path eligibility, walk this checklist verbatim.
**Every checkbox must be YES**; if any is NO, the fast path does not
apply — take the careful flow and ask for the missing field verbatim.

```text
[ ] User named the verifier command verbatim?
    (Not "the conventional test command for X", not "the auth tests",
    not "the build". A real verifier is exact argv the user typed:
    `go test ./internal/foo/... -run . -count=1`, `make test`,
    `bundle exec rspec spec/auth_spec.rb`. If you would have to
    invent the verifier from package name or convention, the answer
    is NO.)

[ ] User named acceptance criteria as observable behaviors?
    (Not "edits stay in scope" — that is scope restatement.
    Not "go build succeeds" / "go test passes" — those are verifier
    restatements. Not "no observable behavior change" — that is
    vacuous. Not "the helper has a single responsibility" — that
    is a style preference. Real AC describe observable outputs,
    error conditions, ordering, boundary values, or invariants the
    verifier can test.)

[ ] User named the edit boundary?
    (File, package, route, diff, or local-change scope — not
    "the auth thing", not "the slow part".)

[ ] If the request asks for a metric benchmark: user named
    protected paths?
    (Files the providers must not edit — the measuring stick.
    A benchmark request without protected paths is not fast-path
    eligible; ask for the metric harness path and direction.)

[ ] If the request is a refactor ("extract X", "rename Y",
    "consolidate Z", "split A into B"): user named the behavioral
    invariants to preserve?
    (Not the implicit "no behavior change" — that is exactly the
    anti-synthesis pattern. Ask for the specific test files,
    API contracts, exit-code mappings, byte-equality conditions,
    or round-trip equalities that must hold. Refactors hide
    missing AC inside the verb; ask anyway.)
```

**Refactor edge case (load-bearing):** Refactor and extract requests
trigger a known soft spot. The model sees an explicit verifier, an
explicit scope, an explicit goal, and treats "no behavior change" as
implicit AC. The Anti-Synthesis Patterns below list "no behavior
change" as vacuous, but the refactor framing tends to override the
example. For refactor requests, the checklist item above is not
optional — ask for the specific behavioral invariants even if the
synthesized version ("existing tests pass", "round-trip equality")
looks reasonable. The user knows the invariants that matter; the
model is guessing.

#### Anti-Synthesis Patterns (Examples To Avoid)

The following are **NOT** acceptance criteria — they are scope or
verifier restatements that synthesize the missing AC:

- "Edits are confined to `<scope>`." (scope restatement)
- "`go build ./...` succeeds." (verifier restatement)
- "`go test ./...` passes." (verifier restatement)
- "No observable behavior change." (vacuous — no asserted behavior)
- "The helper has a single responsibility." (style preference, not
  testable behavior)
- "Default-value resolution is consolidated." (restatement of the goal,
  not a behavior the verifier can check)

The following are **NOT** verifier commands — they are placeholders
the model must NOT fill in:

- "the conventional test command for `<package>`" (ambiguous; ask)
- "the auth tests" (ambiguous; ask)
- "the build" (ambiguous; ask)
- `go test ./internal/<pkg>/...` invented from package name when the
  user did not provide it (synthesis from convention)

When you catch yourself writing one of these, stop and ask the user
for the real value instead.

### No Write Before Approval

No `Write`, `Edit`, or file-mutating tool call may precede the approval
prompt. The preview is read-only. The first mutating tool call must come
*after* the user's affirmative reply (`yes`, `y`, `approve`, `run it`,
or `write and run` for split/multi-lens). This applies to fast path and
careful path equally.

`bakeoff draft-build` is pre-approval safe: it is read-only and writes only the
validated JSON draft to stdout. It does not create or modify a work-order file.

### Available Backends

Available provider backends: `claude` (Claude Code) and `codex` (Codex
CLI). Available judge backends: `claude`. The model **must not** probe
the CLI to discover backends or schema. The following commands are
**not** drafting-time discovery tools and must not be run from the
drafting flow:

- `bakeoff providers list` (does not exist);
- `bakeoff --help` (canonical info is in this file and the skill);
- `bakeoff init` (writes a TODO template; never run from drafting);
- `bakeoff doctor` (operator-only diagnostic);
- scratch `mkdir /tmp/...` followed by `bakeoff init` (forbidden — use
  `bakeoff draft-build` for build drafts and the documented examples below for
  non-build drafts).

If the user names an unknown backend, ask one clarification question;
do not improvise.

### Canonical Skeletons

For build fast-path drafts, do **not** hand-copy a full JSON skeleton. Run
`bakeoff draft-build` with the extracted id, goal, acceptance criteria, edit
scope, gate verifier, and any optional base/protected paths. Use the emitted
JSON as the preview source. The command owns the canonical build shape,
provider/judge defaults, budgets, `build.verify[].argv`, and self-validation
before stdout.

`draft-build` supports gate verifier drafting first. Metric verifier drafts,
generated fixtures, and protected benchmark harnesses still use the careful
manual path.

**Gather / code-review skeleton:** see `examples/gather.work-order.json`
and `examples/review.work-order.json`; same provider/judge/budgets
shape; `type: "gather"`; no `build` block; `facet.id: "code-review"`
for review-shaped requests.

**Compare skeleton:** see `examples/compare.work-order.json`; same
provider/judge/budgets shape; `type: "compare"`; no `build` block.

For non-build and manual build drafts, copy field names and structure from the
examples. Common drift patterns to avoid:

- `providers[].kind` — use `providers[].backend`.
- `providers[].role` — does not exist; remove.
- `providers[].scope: "local"` — use `"codebase"`.
- `providers[].backend: "claude-code"` — use `"claude"`. The id is
  `claude-code` but the backend value is `claude`.
- `judge: {id, kind, role}` — use `judge: {backend, model, effort}`.
- Top-level `gates[]` — use nested `build.verify[]`.
- `verify[].command: "..."` string — use `verify[].argv: [...]` array.
- Top-level `acceptance_criteria` — does not exist; criteria belong in
  `background` (string or string-array).
- Top-level `scope` — does not exist; use `scope_policy.enforcement` for
  policy and `build.protected_paths` for path lists.
- `schema_version: "1.0"` — use integer `1`.

### Pre-Preview Internal Validate (Advisory)

For build fast-path drafts, `bakeoff draft-build` self-validates before writing
JSON to stdout. No extra temp-file `bakeoff validate` is needed before the
preview; use the emitted JSON directly.

For non-build drafts and manual build drafts, after building the work-order
JSON in memory and before showing the preview, the model **should** internally
invoke `bakeoff validate` against the JSON (write to a temp file if needed). If
validation fails, repair the JSON using the examples above and re-validate.
Repeat until validation passes, then show the preview.

**This is advisory guidance, not an enforced invariant.** Cross-batch
dogfood data showed pre-preview validate lands at ~27% — the model
skips this step when it has framed the request as fast-path-eligible.
Softening this rule trades fewer prompt obligations for occasional
user-visible repair-and-reapprove cycles. The safety net is the
post-write `bakeoff validate` step (#7 below), which runs
unconditionally before `bakeoff build` or `bakeoff research` and
catches fictional schema before any provider runs.

User-visible flow:

1. preflight (`bakeoff-ensure-cli --check`);
2. build fast path: run `bakeoff draft-build` and capture stdout JSON;
3. other drafts: **(should)** internal `bakeoff validate` → repair if needed
   → re-validate;
4. show the compact preview (`draft-build` output is already validated; other
   drafts are validated when step 3 ran);
5. wait for approval;
6. write the file to the working directory;
7. on-disk `bakeoff validate` (**enforced** safety gate);
8. run `bakeoff build` or `bakeoff research`.

When step 3 is skipped and step 7 catches fictional schema, the user
sees a repair-and-reapprove cycle. That cycle is the cost of skipping
step 3; it is not unsafe.

## Natural Language Drafting

Existing work-order paths do not enter this flow. For natural-language input,
run the task-fit check before silent type inference or JSON drafting.

If the request is a weak fit, stop and warn instead of drafting. Use the phrase
"this may not need Bakeoff" and name the reason:

- purely mechanical or formatter-only work (compound prompts that mix
  formatter-only parts with non-formatter intent do not trigger this category);
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

The warning is advisory. The phrase `draft anyway` in the user's reply
satisfies it for that turn only; this is the only accepted opt-out phrase. Do
not add a task-fit flag or persistent opt-out. If the user narrows the
request, re-run the check on the narrowed prompt.
Task-fit confirmation does not waive required work-order fields; for example,
build mode still needs a gate verifier before a valid work order can run. For
build weak-fit prompts, name concrete verifier examples (a project test
command, regression test, or benchmark) in the response so the user knows what
would satisfy the requirement. Combine the task-fit warning and any
missing-field ask in one response when both apply, rather than chaining them
across turns.
The task-fit warning is not permission to answer directly. Stop at the warning
until the user narrows or confirms; after confirmation, continue through the
Bakeoff draft, validate, and run flow. Do not answer directly unless the user
explicitly asks to abandon Bakeoff and answer inline.

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

If the user declines the split (replies `keep it as one`, `no`, or similar),
continue with one normal work order if task-fit has already passed and all
required fields are present. If the user accepts (replies `split` or
equivalent), draft every part separately. Before writing anything, show a
compact review preview for each part, then list all filenames and commands.
Include the full JSON blocks only when the combined draft is still readable:
at most 120 lines and at most 10 KB. For longer split drafts, say the full
JSON is verbose and list available `show part-N` choices (for example
`show part-1`, `show part-2`) alongside the all-parts `show` command.

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
ask the same approval question again. If the user replies `show part-N` with a
specific part, print only that part's JSON and repeat the multi-file
`write and run` approval question.
Require exact `write and run` approval before writing or executing split files.
For splits, `yes`, `approve`, or `run it` is not enough; reply by asking for
exact `write and run` approval because multiple files and runs are involved.

For split work orders, derive one base slug from the original request. Append
`.part-N` to each work-order `id`, filename, and supplied `--run-id` value. If
no run id was supplied, let the CLI use the part work-order ids. If a
work-order filename or run directory already exists, append the smallest numeric
collision suffix after `.part-N` and use the same stem for both file and run id,
such as `base.part-1-2.work-order.json` and `--run-id base.part-1-2`. Do not
use date suffixes, and do not overwrite exact files unless the user explicitly
asks.

After split approval, write all files, validate all files, and only then run
the parts sequentially. If any validation fails, run no parts; surface the
validation error verbatim, repair the affected JSON, show the final set again
with the same preview rules, and ask for exact `write and run` approval again.
`bakeoff validate` warnings are advisory; preserve them in the summary when
relevant, but do not stop the split sequence when validation exits successfully.
Route each part by its own `type`: `build` uses
`bakeoff build`; `gather`, `compare`, and `analyze` use `bakeoff research`.
Apply the same mode-specific flag routing to each part. Continue after exit
`0`, `3`, or `4`; exit `4` is a decision-incomplete handoff with durable
provider artifacts and should include the judge-only rerun recommendation when
applicable. Split runs continue after exit `4` because each part is
independent and cheap to keep going; multi-lens runs stop on exit `4` because
each lens is higher-cost and a decision-incomplete handoff is worth inspecting
before spending more lens budget. Stop on exit `1`, `2`, `130`, interruption,
or command failure, summarize completed parts and the failed part, and ask
before running any remaining parts.

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

Trigger phrases are candidates only when the request is review-shaped and the
phrase is being used to request multiple review passes. They include:

- `multi-lens`
- `review swarm`
- `with separate lenses`
- `separate review passes`
- `run security and performance as separate reviews`
- `security, performance, and UX lenses`

Do not trigger multi-lens just because a normal review mentions multiple
concerns. "review this for security and tests" drafts one normal review.
"review this with security and tests as separate lenses" drafts two lens runs.
Do not trigger when `swarm` describes the code, a team, a plugin, a bug, or any
domain object rather than a Bakeoff workflow. If "review swarm" is ambiguous,
ask whether the user wants separate lens runs before drafting.

Run the task-fit gate before lens selection. If the review target is not
bounded by a branch, PR, diff, file set, or local changes, stop with the usual
"this may not need Bakeoff" warning and do not ask for lenses yet.

If the user asks for multi-lens review without naming lenses, ask:

```text
Which 2-3 lenses should I run? Common choices are correctness, tests, security,
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
or clearly asks to run without triage. If `--no-triage` is set, include
`--no-triage` in every generated lens command.

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

Each run asks the configured reviewers to inspect the same change from one
lens, then merges and verifies that lens's findings.

Cost note: this is about <N>x a normal review. With the configured
<budget-seconds> second budget, each lens can reserve up to about
<per-lens-minutes> minutes worst-case (reviewers, merge, verification). <N>
lenses can therefore reserve up to about <computed-total> minutes worst-case,
though typical runs may finish sooner.

Verification is on for each lens by default. Synthesis is not automatic; after
the runs finish I will summarize the lens results and ask whether you want one
prioritized fix plan.

Write, validate, and run these one after another? Reply `write and run`, reply
`show` to print the full JSON, or tell me what to change.
```

Compute the displayed worst-case from `budgets.wall_clock_seconds`: one worker
phase, one merge phase, and one verification phase per lens when triage is
enabled. Provider reviews run in parallel, so do not double-count the worker
phase. For the default 900-second budget with triage enabled, this is 45
minutes per lens. If `--no-triage` is set, omit the verification phase, state
that findings will be raw and unverified, and use two phases in the estimate.
If the draft uses one or more than two providers, name the provider count in the
preview and still count one worker phase because providers run in parallel.

Use `write and run` as the multi-lens approval phrase. For multi-lens, `yes`,
`approve`, or `run it` is not enough; reply by asking for exact `write and run`
approval because multiple files and runs are involved. If the user replies
`show`, print full JSON only when the combined draft fits the existing
120-line / 10 KB budget. If it does not fit, list the available lens-specific
show commands such as `show security` and `show performance`. If the user
replies `show <lens>` with a selected lens label or slug, print only that
lens's JSON and then repeat the multi-lens approval question.

After approval, write all lens files, validate every file, and only then run
the lens runs sequentially. If any validation fails, run no lenses; surface the
validation error verbatim, repair the affected JSON, show the final set again
with the same preview rules, and ask for exact `write and run` approval again.
`bakeoff validate` warnings are advisory and do not stop the lens sequence when
validation exits successfully. Route every lens through `bakeoff research`:

```text
bakeoff research <lens-work-order> --run-id <base>.<lens> [--out <dir>] [--base <ref>] [--diff] [--changed-files] [--quiet] [--no-triage] [--no-repo-layout]
```

Continue after exit `0`. Treat exit `3` as a completed but unusual research
handoff only if it occurs; mark the lens untriaged unless triage artifacts
exist. Stop on validation failure, exit `1`, exit `2`, exit `4`, exit `130`,
interruption, or command failure.

On a stopped multi-lens sequence, show a partial-progress block with:

- completed lenses, run ids, report paths, and triage states;
- the stopped lens, command, exit code or failure reason, and any artifact paths
  that exist;
- remaining lenses not yet run;
- whether a partial summary file was written.

Ask before continuing remaining lenses:

```text
Continue with the remaining lenses? Reply `continue lenses`, or tell me what
to change.
```

After all completed lens runs finish, read artifacts when present:

- `report.md`
- `decision.json`
- `triage/final.json`
- `triage/triage.md`
- `triage/source_finding_filter.json`

Write a markdown summary to `<out>/<base>.multi-lens-summary.md`, applying the
same numeric collision policy as lens run ids. Use this section layout:

```text
# Multi-Lens Review Summary

Summary file: <path>

## Runs
...

## Triage Counts
...

## Most Actionable
...

## Overlap
...

## Clean Lenses
...

## Caveats
...

## Next Commands
...

## Optional Synthesis
...
```

The summary and final response must include each lens, run id, report path,
triage path/state, run status, triage counts when available (`real_issue`,
`needs_repro`, evidence gaps, false positives, deferred, documented, and
ignored items), most actionable findings grouped by lens, overlapping themes,
clean lenses, caveats for untriaged or failed runs, `bakeoff show` commands,
and the persisted summary path. If triage was disabled, artifacts are missing,
or triage was only recommended, say findings are raw and unverified. If some
lenses failed or were skipped, label the file and final response as a partial
multi-lens summary.

Do not synthesize automatically. Ask: "Want a synthesis pass that dedupes these
verified lens results into one prioritized fix plan?" If accepted, draft a
normal `type: "analyze"` work order over the completed reports and triage
files. It must not invent new findings; it should prefer verified `real_issue`
and `needs_repro` items, preserve source lens and run id, merge duplicates only
when evidence and changed behavior match, and produce one prioritized
remediation plan.

For one-work-order drafting, first try the **obvious one-work-order fast
path** below. If any predicate condition fails, fall through to the careful
type-routing and missing-field rules that follow — those rules are the
authoritative silent-inference logic when the fast path does not apply.

### Obvious One-Work-Order Fast Path

Build mode only in v1. Skip cautious exploration and go from preflight
straight to preview when **all** of the following hold:

1. The request clearly maps to exactly one build work order.
2. Required fields are present in the user's text:
   - implementation goal;
   - acceptance criteria;
   - at least one gate verifier (a concrete command-line invocation);
   - an explicit edit boundary: file, directory, package, route, or scope
     expression;
   - base ref, when the user names a non-`HEAD` base.
3. The gate verifier is explicit enough to copy into the work order without
   guessing.
4. No metric verifier, protected verifier fixture, benchmark harness, golden
   file, or generated expected-output artifact requires path discovery.
5. No requested split, multi-lens review, broad synthesis, or sequential plan
   is present.
6. No mode-specific flag conflict is present.
7. The request does not mention external web research, does not require
   `scope: web`, and does not need secrets or provider auth material.

When all conditions hold, take the fast-path action:

1. Run the mandatory CLI preflight (`scripts/bakeoff-ensure-cli --check`).
2. Parse flags and mode.
3. Run `bakeoff draft-build` with the extracted id, goal, acceptance criteria,
   scope, gate verifier, and optional base/protected paths. Use the emitted
   JSON as the draft. Do **not** invent missing acceptance criteria, scope, or
   verifier commands just to satisfy the flags.
4. **Do not perform repo exploration** unless the supplied target or
   verifier cannot be rendered into the work order without it. Available
   backends are embedded in [Available Backends](#available-backends);
   do not probe the CLI to discover them. If one fact is genuinely
   missing, perform exactly one batched read/search pass that answers
   all drafting questions at once. In context-mode sessions, that pass
   means one `ctx_batch_execute` call; do not approximate it with chained
   Bash/Read/Grep calls. Sequential probes are a fast-path violation.
5. Treat `draft-build` failure as a drafting error: ask for the missing or
   invalid value rather than hand-authoring around it. The command validates
   before stdout (see [Pre-Preview Internal Validate](#pre-preview-internal-validate)).
6. Show the compact preview with default-aware lines. Non-default values
   must appear inline (do not hide them behind a "default" label).
7. Wait for the same approval phrase as the current single-work-order flow:
   `yes`, `y`, `approve`, or `run it`. The stricter `write and run` phrase
   is for split or multi-lens flows only — do not adopt it here.
8. **Do not write the work-order file or call any tool that mutates the
   working tree until the user approves** (see [No Write Before
   Approval](#no-write-before-approval)). This applies even after the
   internal validate has passed — the on-disk write waits for the
   user's affirmative reply.
9. After approval, write the file, run on-disk `bakeoff validate` as an
   audit-redundancy check (the result should match the pre-preview
   validate), then run `bakeoff build`.

Full JSON remains available with `show` at any point.

**Fast-path fallback rules.** Do not fast-path; take the careful drafting
flow (or ask one targeted question) when any of these are true:

- missing acceptance criteria for build mode;
- missing gate verifier for build mode;
- unclear edit boundary or package/route/file scope;
- uncertain type — "build a report/comparison/matrix" wording may mean
  research or compare mode, not build;
- metric benchmark request without explicit metric command, direction, or
  protected measuring files;
- verifier commands that appear to depend on generated fixtures, snapshots,
  goldens, or harness files providers must not edit;
- requested split or multi-lens review;
- review requests without a bounded branch, PR, diff, file set, or
  local-change scope;
- analyze/RCA requests without symptom, log, reproduction, trace, file set,
  incident, or command to inspect;
- path-like missing input — if the user typed a path that does not exist,
  surface a CLI path error; do not reinterpret as natural language;
- unknown flags or mode-specific flag conflicts;
- non-`HEAD` base ambiguity;
- build providers with `scope: web`;
- a request that would require secrets or provider auth material in the
  work order.

Review, research, analyze, and compare requests continue to use the careful
flow regardless of how complete the request looks. Lifting the build-only
limit on the fast path requires a follow-up plan after build dogfood proves
the predicate safe.

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
  explicit edit boundary, and any non-`HEAD` base ref;
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

For build fast-path drafts, the clean JSON comes from `bakeoff draft-build`.
Manual JSON drafting is reserved for non-build types and build cases that need
metric verifier fields or careful path discovery.

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
policy from the shared skill: if the filename exists, append the smallest
numeric suffix (`./<id>-2.work-order.json`, `./<id>-3.work-order.json`, ...)
and do not use date suffixes. Never overwrite an existing work-order file
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
