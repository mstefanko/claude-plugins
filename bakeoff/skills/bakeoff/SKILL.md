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

Bakeoff is a thin CLI wrapper surface. Claude's plugin-side role is to draft
work orders, invoke `bakeoff`, inspect artifacts, and summarize results. The Go
CLI owns validation, provider execution, judging, patch capture, reports,
ledgers, triage, and exit codes.

For `/bakeoff:run`, Claude must not satisfy the requested research, review,
comparison, analysis, or build inline. Claude only drafts work orders, invokes
`bakeoff`, inspects artifacts, and summarizes CLI results. If the request cannot
enter that flow, stop with the documented warning, clarification, or error. Do
not call provider CLIs directly for the user task; only the Bakeoff CLI may
launch providers for this command.

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
If no path or natural-language request remains after flag parsing, stop and ask
the user for a work-order path or request. Do not infer a task from flags alone.

Run the task-fit check after parsing flags and path detection, but before type
inference, JSON drafting, or filename decisions. If the request is a weak fit,
stop and ask for confirmation instead of silently drafting. This is advisory,
not a hard block: the phrase `draft anyway` in the user's reply satisfies the
warning for that turn. `draft anyway` is the only accepted opt-out phrase. Do
not add a flag, persistent preference, or "never warn me again" state.
The warning does not permit an inline answer. After a task-fit warning, do not
answer the task directly unless the user explicitly asks to abandon Bakeoff and
answer inline.

Use this wording shape:

```text
This may not need Bakeoff because <reason>. Bakeoff usually pays off when two
independent providers can produce meaningfully different evidence or patches,
and when there is a verifier, scope, or citation standard. Reply `draft anyway`
to continue with Bakeoff, or tell me how to narrow it.
```

Weak-fit cases:

- purely mechanical or formatter-only work (compound prompts that mix
  formatter-only parts with non-formatter intent do not trigger this category);
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
For build weak-fit prompts, name concrete verifier examples (a project test
command, regression test, or benchmark) in the response so the user knows what
would satisfy the requirement. Combine the task-fit warning and any
missing-field ask in one response when both apply, rather than chaining them
across turns. If the user narrows the request, re-run the task-fit check on
the revised prompt.

After task fit passes or is explicitly confirmed, check for explicit
multi-lens review requests before the generic clean-split check. Do not propose
a split or multi-lens run in the same response as a task-fit warning.

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

If the user declines the split (replies `keep it as one`, `no`, or similar),
continue with one normal work order if task-fit has already passed and all
required fields are present. If the user accepts the split (replies `split` or
equivalent), draft each work order as a separate normal JSON object. Before
writing anything, show a compact review preview for each part, then list the
filenames and commands. Include the full JSON blocks only when the combined
draft is still readable: at most 120 lines and at most 10 KB. For longer split
drafts, say the full JSON is verbose and list available `show part-N` choices
(for example `show part-1`, `show part-2`) alongside the all-parts `show`
command.

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

Derive one base slug from the original request. Append `.part-N` to each
work-order `id`, filename, and supplied `--run-id` value. If the user did not
pass `--run-id`, let the CLI use the work-order id. If a work-order filename or
run directory already exists, append the smallest numeric collision suffix after
`.part-N` and use the same stem for both file and run id, such as
`base.part-1-2.work-order.json` and `--run-id base.part-1-2`. Do not use date
suffixes, and do not overwrite exact files unless the user explicitly asks.

After split approval, write all part files, validate all of them before running
any part, and run them sequentially with the existing CLI commands. Route each
part by its own `type`: `build` uses `bakeoff build`; `gather`, `compare`, and
`analyze` use `bakeoff research`. Apply mode-specific flags to each part.

If any split validation fails, stop before execution, surface the validation
error verbatim, repair the affected JSON, and show the final set again with the
same preview rules before asking for exact `write and run` approval.
`bakeoff validate` warnings are advisory and do not stop the split sequence when
validation exits successfully. During execution, continue after exit `0`, `3`,
or `4`; exit `3` is a completed
Bakeoff handoff with unresolved disagreement, and exit `4` is a
decision-incomplete handoff with durable provider artifacts. Split runs
continue after exit `4` because each part is independent and cheap to keep
going; multi-lens runs stop on exit `4` because each lens is higher-cost and a
decision-incomplete handoff is worth inspecting before spending more lens
budget. Stop the sequence on exit `1`, `2`, `130`, interruption, or command
failure. Summarize completed parts and the failed part before asking whether
to continue.

Do not run a decomposition agent, add a DAG runner, create a batch
work-order-list schema, coordinate shared state across parts, or synthesize an
overall winner, merged patch, or merged answer from split runs. Cross-run
synthesis is a separate user request. Multi-lens review has its own bounded
summary rule below; generic split runs remain independent.

## Multi-Lens Review Drafts

Multi-lens review is a specialized review split, not a new work-order schema or
CLI mode. Use it only for natural-language review requests that explicitly ask
for separate lenses or separate review passes. Plain review remains one normal
`type: "gather"` work order with `facet.id: "code-review"`.

Trigger multi-lens only for review-shaped requests where the wording clearly
asks for multiple review passes. Candidate wording includes:

- `multi-lens`;
- `review swarm`;
- `with separate lenses`;
- `separate review passes`;
- `run security and performance as separate reviews`;
- `security, performance, and UX lenses`.

Do not trigger multi-lens just because a normal review names several concerns.
For example, "review this for security and tests" drafts one review with those
concerns in the shared focus. "review this with security and tests as separate
lenses" drafts two lens runs. Do not trigger when `swarm` describes the code, a
team, a plugin, a bug, or any domain object rather than a Bakeoff workflow. If
"review swarm" is ambiguous, ask whether the user wants separate lens runs
before drafting.

Run the task-fit gate first. If the target is not bounded by a branch, PR,
diff, file set, or local-change scope, show the usual "this may not need
Bakeoff" warning and do not ask for lenses yet. Once the review scope is valid,
do not also run the generic clean-split proposal; show one multi-lens preview.

If the user asks for a multi-lens review without naming lenses, ask:

```text
Which 2-3 lenses should I run? Common choices are correctness, tests, security,
performance, UX/frontend behavior, and maintainability.
```

Default support is 2-3 lenses. If the user asks for more than 3, warn before
drafting:

```text
That would run <N> separate review runs. I recommend narrowing this to 2-3
lenses unless you really want the extra cost and summary volume. Tell me which
lenses to keep, or say `run all lenses`.
```

You may hard-stop at 3 unless the user explicitly says `run all lenses` or
`run all <N>`.

Use "lens" in user-facing text. Reserve "facet" for implementation notes and
shown JSON. Lens presets are task filters, not personas:

| Lens slug | Synonyms and examples | Focus |
| --- | --- | --- |
| `correctness` | correctness, bugs, behavior, edge cases, error handling, data correctness | Changed behavior, edge cases, data correctness, and error handling. |
| `tests` | tests, test coverage, regression tests, missing tests, stale tests | Missing, misleading, or stale tests for changed behavior. |
| `security` | security, auth, authn, authz, injection, SQL injection, XSS, CSRF, secrets, data exposure, trust boundary | Concrete auth, injection, secrets, trust-boundary, and unsafe data-flow risks. |
| `performance` | performance, perf, latency, memory, resource use, scaling, database queries, N+1 | Changed hot paths, resource use, repeated work, avoidable I/O, and scaling risks. |
| `ux` | UX, frontend, UI, accessibility, a11y, copy, loading states, error states, responsive behavior | User-visible regressions, accessibility, copy/state mismatch, loading/error behavior. |
| `maintainability` | maintainability, readability, coupling, architecture risk, migration risk | Defect-prone structure, confusing ownership, fragile coupling, and migration risks. |
| `reliability` | reliability, resilience, concurrency, races, retries, timeouts, idempotency | Concurrency, retries, timeouts, idempotency, failure handling, and resilience risks. |

Map `data correctness` to `correctness` with data correctness called out in the
background. Map `SQL injection` to `security` with SQL injection called out in
the background. Map `accessibility` to `ux`. Unknown narrow review topics are
allowed as custom lenses: normalize to a safe kebab slug, keep the focus narrow,
and create custom focus/include/exclude text. Ask one clarification question
for vague unknown lenses such as `quality`, `architecture`, `stuff`, or
`everything`.

For each selected lens, draft one normal review work order:

- `type: "gather"`;
- `facet.id: "code-review"`;
- shared providers, judge, budgets, scope policy, base, and diff behavior from
  normal review drafting;
- lens-specific `goal`, `background`, `facet.focus`, `facet.include`, and
  `facet.exclude`;
- automatic code-review triage enabled unless the user passes `--no-triage` or
  explicitly asks to run without triage. If `--no-triage` is set, include
  `--no-triage` in every generated lens command.

Use a single base slug from the request or supplied `--run-id`. Append the lens
slug as the final semantic component for work-order ids, filenames, and run
ids: `<base>.<lens>`, for example `review-auth.security.work-order.json` with
`--run-id review-auth.security`. If the filename or run directory already
exists, append the numeric collision suffix after the lens slug and use the
same stem for both file and run id, such as
`review-auth.security-2.work-order.json` and
`--run-id review-auth.security-2`. Never switch multi-lens review to `.part-N`
naming.

Before writing files, show a compact multi-lens preview. Do not print full JSON
by default. Include the selected lenses, planned files, run ids, commands,
review settings, whether verification/triage is on, and a cost note:

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
Full JSON may be shown after `show` only when the combined draft fits the
120-line / 10 KB preview budget.
If the draft uses one or more than two providers, name the provider count in the
preview and still count one worker phase because providers run in parallel.

Require explicit `write and run` approval before writing or executing
multi-lens files. For multi-lens, `yes`, `approve`, or `run it` is not enough;
reply by asking for exact `write and run` approval because multiple files and
runs are involved. If the combined JSON is too long, list the available
lens-specific show commands such as `show security` and `show performance`. If
the user replies `show <lens>` with a selected lens label or slug, print only
that lens's JSON and then repeat the multi-lens approval question.

After approval, write every lens file, validate all files before running any,
and run them sequentially with existing commands. If any validation fails, run
no lenses; surface the validation error verbatim, repair the affected JSON, show
the final set again with the same preview rules, and ask for exact
`write and run` approval again. `bakeoff validate` warnings are advisory and do
not stop the lens sequence when validation exits successfully.

```text
bakeoff research <lens-work-order> --run-id <base>.<lens> [--out <dir>] [--base <ref>] [--diff] [--changed-files] [--quiet] [--no-triage] [--no-repo-layout]
```

Continue after exit `0`. Treat exit `3` as a completed but unusual research
handoff if it occurs, and mark that lens untriaged unless triage artifacts
exist. Stop on validation failure, exit `1`, exit `2`, exit `4`, exit `130`,
interruption, or command failure.

On a stopped multi-lens sequence, show a partial-progress block with completed
lenses, run ids, report paths, triage states, the stopped lens and failure
reason, remaining lenses, and whether a partial summary file was written. Ask:

```text
Continue with the remaining lenses? Reply `continue lenses`, or tell me what
to change.
```

After the lens runs finish, read each run's `report.md`, `decision.json`,
`triage/final.json`, `triage/triage.md`, and
`triage/source_finding_filter.json` when present. Write a plugin-created
summary file to `<out>/<base>.multi-lens-summary.md`, applying the same numeric
collision policy to the summary stem. Use sections in this order:

```text
# Multi-Lens Review Summary

Summary file: <path>

## Runs
## Triage Counts
## Most Actionable
## Overlap
## Clean Lenses
## Caveats
## Next Commands
## Optional Synthesis
```

The summary and final response must include each lens, run id, report path,
triage path/state, run status, triage counts when available (`real_issue`,
`needs_repro`, evidence gaps, false positives, deferred, documented, and
ignored items), the most actionable findings grouped by lens, duplicate or
overlapping themes, clean lenses, caveats for untriaged or failed runs,
`bakeoff show` commands, and the persisted summary path. If triage is disabled,
missing, or only recommended, say findings are raw and unverified. If some
lenses failed or were skipped, label the file and final response as a partial
multi-lens summary.

Do not synthesize automatically. Ask: "Want a synthesis pass that dedupes these
verified lens results into one prioritized fix plan?" If the user accepts,
draft a separate normal `type: "analyze"` work order over the completed reports
and triage files. Constrain it to dedupe verified lens results into one
prioritized fix plan without inventing new findings, while preserving source
lens and run id. If per-lens triage was disabled, say synthesis will consume
raw, untriaged findings.

## Drafting Invariants

These invariants apply to **every** natural-language drafting path (fast
path, careful path, split, multi-lens). They are not fast-path-specific.
See `commands/run.md → ## Drafting Invariants` for the canonical wording;
this section must stay in sync with that file.

### Required-Field Synthesis Guidance (Advisory)

If the request omits any of the following, the model **should** prefer
asking the missing question(s) verbatim over synthesizing a default.

**This is prompt-level guidance, not a Go-side semantic gate.** The
clean final-contract dogfood showed the checklist and R1.6 refactor
edge case work on the tested prompt shapes — see
`docs/drafting-fast-path-experiment-log-2026-05-20.md`. The operator's
preview-then-approve flow remains the safety net for untested wording
variants.

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

### Available Backends

Available provider backends: `claude` (Claude Code) and `codex` (Codex
CLI). Available judge backends: `claude`. The model **must not** probe
the CLI to discover backends or schema. The following commands are
**not** drafting-time discovery tools and must not be run from the
drafting flow:

- `bakeoff providers list` (does not exist);
- `bakeoff --help` (canonical info is in this skill and `commands/run.md`);
- `bakeoff init` (writes a TODO template; never run from drafting);
- `bakeoff doctor` (operator-only diagnostic);
- scratch `mkdir /tmp/...` followed by `bakeoff init` (forbidden — use
  the embedded skeletons below).

If the user names an unknown backend, ask one clarification question;
do not improvise.

### Canonical Skeletons

The model **must** copy field names and structure verbatim from the
canonical skeleton for the resolved work-order type. Inventing or
renaming fields is a contract failure. Substitute only the angle-bracket
placeholders. Do not omit other fields. Do not add fields not in the
skeleton. If unsure of a default, copy the skeleton value verbatim.

**Build skeleton:**

```json
{
  "schema_version": 1,
  "id": "<kebab-id>",
  "type": "build",
  "goal": "<one-sentence implementation goal>",
  "background": [
    "<acceptance criteria as one or more bullets within this array>",
    "Bakeoff will capture candidate patches from isolated worktrees and will not apply them to this checkout."
  ],
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "scope_policy": { "enforcement": "best_effort" },
  "judge": { "backend": "claude", "model": "opus", "effort": "xhigh" },
  "build": {
    "base_ref": "HEAD",
    "comparison_goal": "Prefer the patch that satisfies the acceptance criteria with the smallest maintainable change.",
    "verify": [
      {
        "id": "<verifier-id>",
        "kind": "gate",
        "argv": ["sh", "-c", "<verifier-command>"],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  },
  "budgets": {
    "wall_clock_seconds": 1200,
    "max_output_bytes": 80000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 80000
  }
}
```

**Gather / code-review skeleton:** see `examples/gather.work-order.json`
and `examples/review.work-order.json`; same provider/judge/budgets
shape; `type: "gather"`; no `build` block; `facet.id: "code-review"`
for review-shaped requests.

**Compare skeleton:** see `examples/compare.work-order.json`; same
provider/judge/budgets shape; `type: "compare"`; no `build` block.

Common drift patterns to avoid (all observed in 2026-05-20 dogfood):

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

After building the work-order JSON in memory and before showing the
preview, the model **should** internally invoke `bakeoff validate`
against the JSON (write to a temp file if needed). If validation
fails, repair the JSON using the canonical skeleton and re-validate.
Repeat until validation passes, then show the preview.

**This is advisory guidance, not an enforced invariant.** Cross-batch
dogfood data showed pre-preview validate lands at ~27% — the model
skips this step when it has framed the request as fast-path-eligible.
The safety net is the post-write `bakeoff validate` step (#7 below),
which runs unconditionally before `bakeoff build` or `bakeoff
research` and catches fictional schema before any provider runs.

User-visible flow:

1. preflight (`bakeoff-ensure-cli --check`);
2. build the JSON in memory from the user's request plus skeleton
   defaults;
3. **(should)** internal `bakeoff validate` → repair if needed → re-validate;
4. show the compact preview (with the validated JSON);
5. wait for approval;
6. write the file to the working directory;
7. on-disk `bakeoff validate` (**enforced** safety gate);
8. run `bakeoff build` or `bakeoff research`.

When step 3 is skipped and step 7 catches fictional schema, the user
sees a repair-and-reapprove cycle. That cycle is the cost of skipping
step 3; it is not unsafe.

## Drafting Rules

For one-work-order drafting, first try the **obvious one-work-order fast
path** below. If any predicate condition fails, fall through to the careful
type-routing and missing-field rules that follow.

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
3. Build the work-order draft from the supplied user text plus the
   canonical build skeleton (see [Canonical Skeletons](#canonical-skeletons)).
   Substitute only `<placeholder>` values. Do **not** invent fields, do
   **not** rename `backend`/`scope`/`build.verify`/etc., do **not**
   restate `build.patch_max_bytes` — let Go validation apply the
   default.
4. **Do not perform repo exploration** unless the supplied target or
   verifier cannot be rendered into the work order without it. Available
   backends are embedded in [Available Backends](#available-backends);
   do not probe the CLI to discover them. If one fact is genuinely
   missing, perform exactly one batched read/search pass that answers
   all drafting questions at once. Sequential probes are a fast-path
   violation.
5. **Prefer internally validating the in-memory JSON via `bakeoff validate`**
   (see [Pre-Preview Internal Validate](#pre-preview-internal-validate)).
   If validation runs and fails, repair using the canonical skeleton and
   re-validate until it passes before previewing.
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

### General drafting rules

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

- research: Claude `sonnet` high and Codex `gpt-5.5` high, with scope selected
  by task shape;
- build: both providers use `scope: "codebase"`;
- judge: Claude `opus` xhigh.

Use Claude aliases for generated defaults. Use full provider model ids only
when the user asks to pin a specific version.

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
- provider `scope: "codebase"` only.

Do not include `build.patch_max_bytes` in generated drafts. The Go CLI
owns that default; omit the field and let validation fill it.

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

Before writing a natural-language draft, show a compact review preview instead
of dumping raw JSON by default. Include the id and type, planned file path,
providers, judge, budget, scope policy, goal, a brief background summary, and
the command that will run. Include the full JSON in a fenced `json` block only
when the draft is still readable: at most 120 lines and at most 10 KB. For
longer drafts, say the full JSON is verbose and can be printed with `show`;
still show the planned `./<id>.work-order.json` path.

Ask:

```text
Write, validate, and run this work order? Reply `yes` to continue, reply `show` to print the full JSON, or tell me what to change.
```

Only explicit affirmative replies such as `yes`, `y`, `approve`, `run it`, or
`write and run` count. If the user replies `show`, print the full JSON and ask
the same approval question again. If the user edits, asks a question, or
replies ambiguously, revise or clarify and show the updated preview before
writing.

If `runs/<id>` already exists, append the smallest numeric suffix needed to make
the run id unique before showing JSON for approval.

Write only `./<id>.work-order.json`. If that filename exists, do not overwrite
it. Use `./<id>-2.work-order.json`, `./<id>-3.work-order.json`, and so on,
unless the user explicitly asks to replace a file.

## Validation Before Run

Run `bakeoff validate <path>` before `bakeoff research` or `bakeoff build`.

Surface validation errors verbatim. Repair JSON, show the updated preview with
the same rules, and revalidate only after approval.

Route existing work-order paths by `type`:

- `type: "build"` -> `bakeoff build <path>`;
- `type: "gather"`, `type: "compare"`, or `type: "analyze"` ->
  `bakeoff research <path>`.

Do not reinterpret missing path-like input as natural language.
If input is path-like but missing or invalid, report the path error only; do not
reinterpret the remaining words as a natural-language request or answer them
inline.

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

For every completed or decision-incomplete run, summarize:

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

Exit code `4` means the decision is incomplete because the judge failed or did
not converge, while provider artifacts are durable. When all providers are
`ok` or `ok_after_format_retry` and the judge status failed, recommend
`bakeoff rerun <run-id> --judge-only` first. A full
`bakeoff rerun <run-id>` is secondary.

## Permission Semantics

Command `allowed-tools` frontmatter is a packaged convenience: it pre-approves
listed tools and does not deny all other tools by itself.

`Write` and `Edit` in `/bakeoff:run` are only for drafting work-order files and
plugin-created multi-lens summary files. They are never permission to apply,
rewrite, combine, or publish provider patches after a build.

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
