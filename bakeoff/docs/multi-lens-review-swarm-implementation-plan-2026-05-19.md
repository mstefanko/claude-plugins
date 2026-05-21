# Multi-Lens Review Swarm Implementation Plan

Date: 2026-05-19

Status: superseded by
`docs/parallel-multi-lens-review-implementation-plan-2026-05-21.md` for
parallel multi-lens execution choice; retained as historical drafting context

Scope: Claude plugin drafting flow for review-shaped Bakeoff requests

## Recommendation

Add multi-lens code review as a Claude plugin workflow built from separate,
normal Bakeoff work orders. Do not add `facets[]`, provider-specific facets, a
batch work-order schema, or a new Go CLI orchestration mode.

The default stays one normal review:

```text
/bakeoff:run review this diff against main
```

Multi-lens review only happens when the user explicitly asks for multiple
lenses, for example:

```text
/bakeoff:run review this diff against main with security, performance, and UX lenses
/bakeoff:run multi-lens review my local changes for correctness, tests, and security
/bakeoff:run review swarm this PR: security + data correctness + regression tests
```

The plugin should draft 2-3 separate review runs, implemented internally as
normal `type: "gather"` work orders with `facet.id: "code-review"` and
lens-specific `focus`, `include`, and `exclude` text. Each lens run should keep
automatic code-review triage enabled by default. After the runs finish, Claude
should read the artifacts, write a lightweight multi-lens summary markdown
file, and include the same summary in the conversation. Optional synthesis is a
follow-up, not an automatic hidden step.

## Why This Shape

The current Bakeoff code is intentionally centered on one shared facet per run:

- `WorkOrder` has a singular `Facet` field
  (`internal/workorder/workorder.go`).
- Provider-level facets are rejected by validation.
- Worker and judge prompts render one shared facet.
- Review auto-triage keys off `facet.id == "code-review"`.
- Gather reports describe corroboration as worker overlap inside one shared
  facet.

That shape is useful. It makes each run pairwise, auditable, replayable, and
easy to reason about. Multi-lens code review should reuse that model instead of
turning the core work-order schema into a review matrix.

The literature supports multiple review perspectives, but it does not answer
whether one multi-facet work order is better than multiple one-facet work
orders. Since both designs provide lens separation, the implementation decision
should optimize for product clarity and low coordination risk. Separate normal
work orders win on those grounds.

## User-Facing Design

### Entry Point

Use `/bakeoff:run` as the main entry point. Do not add
`/bakeoff:review-swarm` in v1.

The phrase "review swarm" can be accepted as natural language inside
`/bakeoff:run`. If the workflow proves popular, a later
`/bakeoff:review-swarm` command can be added as a thin alias that delegates to
the same instructions.

This keeps the user model simple:

- Normal review: one code-review run.
- Explicit multi-lens review: several normal code-review runs.

### Task-Fit Gate

Run the existing task-fit check before multi-lens handling.

If the review target is not bounded by a branch, PR, diff, file set, or local
changes, stop and use the existing "this may not need Bakeoff" warning. Do not
ask for lenses until the user has supplied a reviewable scope.

Once the review scope is valid, multi-lens handling is just a specialized
clean-split path for review. Do not run the generic clean-split prompt and then
a second multi-lens prompt; show one multi-lens preview.

### Lens Selection

Use free-text lens selection, not a separate UI picker. In user-facing copy,
call these "lenses"; reserve "facet" for internal implementation notes.

Only trigger multi-lens drafting when the user explicitly asks for separate
lenses or review passes. Trigger phrases include:

- `multi-lens`
- `review swarm`
- `with separate lenses`
- `separate review passes`
- `run security and performance as separate reviews`
- `security, performance, and UX lenses`

Do not trigger multi-lens mode just because a normal review mentions multiple
concerns. For example, "review this for security and tests" should draft one
normal review with those concerns in the shared focus. "review this with
security and tests as separate lenses" should draft two lens runs.

Map common terms to lens presets:

| Preset | Synonyms and examples |
| --- | --- |
| correctness | correctness, bugs, behavior, edge cases, error handling, data correctness |
| tests | tests, test coverage, regression tests, missing tests, stale tests |
| security | security, auth, authn, authz, injection, SQL injection, XSS, CSRF, secrets, data exposure, trust boundary |
| performance | performance, perf, latency, memory, resource use, scaling, database queries, N+1 |
| ux_frontend | UX, frontend, UI, accessibility, a11y, copy, loading states, error states, responsive behavior |
| maintainability | maintainability, readability, coupling, architecture risk, migration risk, defect-prone structure |
| reliability | reliability, resilience, concurrency, races, retries, timeouts, idempotency |

Unknown lens terms are allowed when they are narrow review topics. Normalize
them to a safe slug and create custom lens text. Examples:

- `SQL injection` maps to the `security` preset with SQL injection called out
  in the background.
- `accessibility` maps to `ux_frontend`.
- `billing invariants` can become a custom `billing-invariants` lens.

Ask one clarification question when an unknown lens is vague, too broad, or
could mean several presets. Examples: `quality`, `architecture`, `stuff`, or
`everything`.

Recognized user-facing lens labels include:

- `security`
- `correctness`
- `tests`
- `performance`
- `UX/frontend`
- `maintainability`
- `data correctness`
- `reliability`

If the user asks for a multi-lens review but does not name lenses, ask one
short follow-up:

```text
Which 2-3 lenses should I run? Common choices are correctness/tests, security,
performance, UX/frontend behavior, and maintainability.
```

Do not silently choose a swarm for a plain review request. One facet remains the
default.

### Lens Count

Default support should be 2-3 lenses.

If the user asks for more than 3 lenses, warn and ask them to narrow the set or
explicitly approve the larger run:

```text
That would run 5 separate review runs. I recommend narrowing this to 2-3 lenses
unless you really want the extra cost and summary volume. Tell me which lenses
to keep, or say `run all lenses`.
```

The first implementation can hard-stop at 3 unless the user explicitly says to
run all requested lenses with a phrase such as `run all lenses` or
`run all <N>`. Even then, prefer a clear warning over clever automation.

## Preview And Cost Messaging

Before writing files, show a compact preview of every lens run and include a
plain cost note.

Suggested wording:

```text
This will run 3 separate review runs:

1. Security review
2. Performance review
3. UX/frontend behavior review

Each run asks the same two reviewers to inspect the same change from one lens,
then merges and verifies that lens's findings.

Cost note: this is about 3x a normal review. With the current 900s default
budget, each lens can reserve up to about 45 minutes worst-case
(reviewers, merge, verification). Three lenses can therefore reserve up to
about 135 minutes worst-case, though typical runs may finish sooner.

Verification is on for each lens by default. Synthesis is not automatic; after
the runs finish I will summarize the lens results and ask whether you want one
prioritized fix plan.

Write, validate, and run these one after another? Reply `write and run`, reply
`show` to print the full JSON, or tell me what to change.
```

Do not warn on normal single-lens review. The warning exists only when the user
has opted into a multi-lens run. If the generated work orders use a non-default
budget, compute the displayed worst-case from the configured
`wall_clock_seconds`: one worker phase, one merge phase, and one verification
phase per lens when triage is enabled. The two provider reviews run in parallel,
so do not double-count the worker phase.

Use the split-flow approval phrase for multi-lens previews: `write and run`.
This is intentionally different from the single-work-order `yes` prompt because
the user is approving multiple files and multiple runs.

## Work Order Shape

Each lens should be a normal work order:

```jsonc
{
  "schema_version": 1,
  "id": "review-auth.security",
  "type": "gather",
  "goal": "Review the branch diff for actionable security defects.",
  "background": [
    "Shared review target: branch feature/auth against main.",
    "Lens: security. Prioritize concrete data-flow, authz, injection, secret handling, and unsafe trust-boundary changes."
  ],
  "facet": {
    "id": "code-review",
    "kind": "generic",
    "focus": "Find actionable security defects introduced or exposed by the change.",
    "include": [
      "security issues with concrete data-flow or control-flow evidence",
      "authentication, authorization, trust-boundary, injection, secret-handling, and unsafe-deserialization risks",
      "missing or misleading tests for security-sensitive changed behavior"
    ],
    "exclude": [
      "generic best-practice advice without changed-code evidence",
      "style-only preferences without project convention evidence",
      "large rewrites unrelated to the changed behavior",
      "speculation without file:line evidence"
    ]
  }
}
```

Use the existing provider, judge, budgets, scope policy, base, and diff behavior
from normal review drafting. These terms may appear in the developer
documentation, but user-facing preview copy should say "reviewers", "merge",
"verification", and "review settings" instead.

Use readable lens slugs in generated ids and run ids. This is the v1 rule, not
an optional preference:

```text
review-auth.security.work-order.json
review-auth.performance.work-order.json
review-auth.ux.work-order.json
```

Derive one base slug from the request or supplied `--run-id`. Append the lens
slug as the final semantic component:

```text
<base>.<lens>
```

If the base includes a date or other disambiguator, the lens still comes after
the base:

```text
review-auth-20260519.security
review-auth-20260519.performance
```

If the work-order filename or run directory already exists, append a numeric
collision suffix after the lens slug and use the same stem for both the file
and run id:

```text
review-auth.security-2.work-order.json
--run-id review-auth.security-2
```

Never switch multi-lens review to `.part-N` naming. That convention remains for
generic split work orders where the parts do not have stable user-facing names.

## Triage Policy

Keep code-review triage enabled for each lens by default.

Rationale:

- Per-lens triage keeps verification close to the original findings and
  citations.
- The cross-run summary can use cleaner, already-triaged signals.
- Triage is not the dominant cost. The main cost is running multiple provider
  and judge passes.
- Delaying triage until after synthesis creates a bigger, fuzzier target and
  makes intermediate reports noisier.

Default workflow:

```text
multi-lens review = N normal code-review runs
                  + N normal code-review triage runs
                  + one Claude-written cross-run summary
```

Respect `--no-triage` or explicit natural language such as:

```text
run the multi-lens review without triage
```

When triage is disabled, the final summary must say that findings are raw and
unverified.

Do not add cross-run triage in v1. Optional synthesis should consume per-lens
triage outputs when they exist.

Auto-triage currently starts only when `bakeoff research` exits `0`. Review
lens runs are `gather` work orders and normally succeed with exit `0`, but the
summary must still tolerate missing triage artifacts. If a lens exits
non-zero, was run with `--no-triage`, or only has a triage recommendation, mark
that lens as untriaged and summarize raw findings separately from verified
items.

## Cross-Run Summary

After all lens runs finish, Claude should read each run's artifacts and produce
a meaty but bounded summary. This is a convenience summary, not a new Bakeoff
decision artifact.

Read, when present:

- `report.md`
- `decision.json`
- `triage/final.json`
- `triage/triage.md`
- `triage/source_finding_filter.json`

The final assistant response should include:

- Each lens, run id, report path, and triage path/state.
- Status for each run, including stopped or failed runs.
- Counts from triage when available: real issues, needs reproduction, evidence
  gaps, false positives, deferred/documented/ignored items.
- The most actionable findings, grouped by lens.
- Duplicate or overlapping themes across lenses.
- Lenses that came back clean after triage.
- Caveats, including untriaged runs or failed judges.
- The `bakeoff show` commands for individual runs.
- The persisted summary path.
- An optional synthesis prompt.

Write the summary to a markdown file by default so the result survives the
conversation. Use:

```text
<out>/<base>.multi-lens-summary.md
```

Apply the same collision policy as lens run ids:

```text
runs/review-auth.multi-lens-summary.md
runs/review-auth-2.multi-lens-summary.md
```

The final assistant response should include a concise version of the same
summary and link to the file.

Suggested summary shape:

```text
Multi-Lens Review Summary

Summary file: runs/review-auth.multi-lens-summary.md

Runs:
- security: runs/review-auth.security/report.md, verification: runs/review-auth.security/triage/triage.md
- performance: runs/review-auth.performance/report.md, verification: runs/review-auth.performance/triage/triage.md
- ux: runs/review-auth.ux/report.md, verification: runs/review-auth.ux/triage/triage.md

Most Actionable:
1. [security] ...
2. [performance] ...
3. [ux] ...

Overlap:
- Security and correctness both flagged ...

Clean Lenses:
- UX produced no verified real issues.

Next:
- `bakeoff show review-auth.security`
- `bakeoff show review-auth.performance`
- `bakeoff show review-auth.ux`

I can draft a synthesis work order over these verified reports if you want one
prioritized fix plan.
```

## Optional Synthesis

Do not synthesize automatically. Ask after the cross-run summary.

This intentionally preserves the existing split-flow rule: split runs do not
produce an overall winner, merged answer, or cross-run synthesis unless the
user asks for that as a separate follow-up. The cross-run summary above is an
artifact index plus human-readable recap; it must not introduce new findings or
claim to be a final synthesis.

If the user wants synthesis, draft a normal `type: "analyze"` work order whose
background points at the completed reports and triage files. The synthesis
prompt should be constrained:

- Do not invent new findings.
- Prefer triaged `real_issue` and `needs_repro` items over raw report claims.
- Preserve source lens and source run id.
- Merge duplicates only when evidence and changed behavior match.
- Produce one prioritized remediation plan, not a new code-review report.

Suggested follow-up wording:

```text
Want a synthesis pass that dedupes these verified lens results into one
prioritized fix plan?
```

If per-lens triage was disabled, the synthesis preview must say it will consume
raw, untriaged findings.

## Implementation Steps

### 1. Plugin Instructions

Update `skills/bakeoff/SKILL.md` and `commands/run.md`:

- Recognize explicit multi-lens review phrases.
- Preserve one normal review as the default.
- Ask for 2-3 lenses when the user requests a swarm without naming lenses.
- Reuse the existing clean-split workflow for review lenses.
- Run the task-fit gate before lens selection.
- Add the cost note and worst-case wall-clock estimate to multi-lens previews.
- Keep per-lens triage enabled unless disabled by the user.
- Require explicit `write and run` approval before writing or executing files.
- Add the post-run persisted summary requirements.
- Add the optional synthesis follow-up.

### 2. Lens Presets

Add a small instruction-level catalog for common lenses. Keep presets as text
templates in the plugin instructions first; do not add a Go enum.

Initial presets:

| Lens | Focus |
| --- | --- |
| correctness | Changed behavior, edge cases, data correctness, error handling. |
| tests | Missing, misleading, or stale tests for changed behavior. |
| security | Concrete auth, injection, secrets, trust-boundary, and unsafe data-flow risks. |
| performance | Changed hot paths, resource use, repeated work, avoidable I/O, and scaling risks. |
| UX/frontend | User-visible regressions, accessibility, copy/state mismatch, loading/error behavior. |
| maintainability | Defect-prone structure, confusing ownership, fragile coupling, migration risks. |
| reliability | Concurrency, retries, timeouts, idempotency, failure handling, and resilience risks. |

Include the synonym table from "Lens Selection" in the plugin instructions. Do
not treat these as personas. They are facet text presets.

### 3. Drafting And Naming

For each selected lens:

- Create one normal review work order.
- Use `facet.id: "code-review"`.
- Keep providers, judge, budgets, and scope policy aligned across lens runs.
- Add lens-specific goal/background/facet text.
- Use `<base>.<lens>.work-order.json` filenames and matching
  `--run-id <base>.<lens>` values.
- Add numeric collision suffixes after the lens slug.
- Validate all generated work orders before running any.
- Show compact previews by default. Do not print full JSON in the preview.
  `show` may print the full JSON only when it fits the existing 120-line /
  10 KB budget; otherwise offer `show <lens>` or write the files after
  approval.

### 4. Execution

Run sequentially using existing commands:

```text
bakeoff research <lens-work-order> --base <base> --diff
```

Use review-specific stop rules:

- Continue after exit `0`.
- Treat exit `3` as a completed but unusual research handoff only if it occurs;
  mark the lens untriaged unless triage artifacts exist.
- Stop on validation failure, exit `1`, exit `2`, exit `4`, exit `130`,
  interruption, or command failure.
- Summarize completed and failed parts before asking whether to continue.

### 5. Summary

After execution, read artifacts from each completed lens run. Build the
cross-run summary and write it to `<out>/<base>.multi-lens-summary.md`. Include
a concise version in the final assistant response. This is a plugin-created
convenience artifact, not a new CLI decision output.

### 6. Optional Synthesis

When the user accepts synthesis, draft and run one normal `analyze` work order
over the completed reports and triage artifacts. Keep this as a separate
approval step.

## Documentation Updates

When implementing, update:

- `skills/bakeoff/SKILL.md`: full behavior and safety rules.
- `commands/run.md`: `/bakeoff:run` user-facing flow.
- `README.md`: short mention that explicit multi-lens review runs separate
  normal review work orders, writes a summary file, and can optionally
  synthesize after approval.
- `docs/work-orders.md`: note that multi-lens review is not a work-order schema
  feature.
- `docs/task-fit-test-scenarios.md`: manual regression scenarios.

No Go source changes are required for v1. The persisted summary is a
plugin-written convenience file, not a CLI artifact. A CLI-level batch command
is still out of scope.

## Test Scenarios

Manual plugin scenarios:

1. Plain review request drafts one normal `code-review` work order.
2. Explicit two-lens request previews two separate work orders with a cost
   note and worst-case wall-clock estimate.
3. `review swarm` without lenses asks which 2-3 lenses to run.
4. Five-lens request warns and asks the user to narrow or explicitly `run all
   lenses`.
5. `--no-triage` applies to all lens runs and the final summary marks findings
   untriaged.
6. A validation failure in one generated lens stops all execution before any
   run starts.
7. One lens fails during execution; the plugin summarizes completed runs and
   asks before continuing.
8. Completed triaged runs produce a cross-run summary with report paths, triage
   paths, top actionable items, overlap, clean lenses, next commands, and a
   persisted summary file.
9. User accepts synthesis; plugin drafts a separate `analyze` work order over
   the triaged artifacts.
10. A request that says "review for security and tests" drafts one normal
    review; a request that says "separate security and tests lenses" drafts two.
11. Unknown narrow lenses become custom lens runs; unknown vague lenses ask one
    clarification question.

## Effort And Risk

Plugin-only v1 is small:

- Drafting and preview rules: 0.5-1 day.
- Lens presets and naming policy: 0.5 day.
- Cross-run artifact summary and summary-file instructions: 0.5-1 day.
- README/work-order docs/test scenarios: 0.5 day.

Expected effort: 1.5-3 days depending on how polished the summary behavior
needs to be.

Risk is low to moderate because the core CLI, work-order schema, provider
runner, judge, report generation, and triage behavior remain unchanged. The
main risks are product-quality risks:

- Too many lenses can overwhelm users.
- Summary text can overstate raw or untriaged findings.
- Lens presets can drift into persona language.
- Cross-run synthesis can accidentally invent a third report.
- Collision handling can desynchronize filenames and run ids if the plugin does
  not use one shared stem.

Mitigate these by keeping the default single-lens, capping normal multi-lens
previews at 2-3 lenses, keeping triage on by default, and requiring explicit
approval for synthesis. Use "lens" in user-facing text and keep "facet",
"judge", "triage", and `type: "gather"` in implementation notes unless the user
asks to see the JSON.

## Non-Goals

- No `facets[]` schema.
- No provider-specific facets.
- No debate swarm inside one work order.
- No new Go CLI batch runner.
- No automatic cross-run triage.
- No automatic synthesis.
- No code fixes or patch application based on review output unless the user
  makes a separate explicit request.
