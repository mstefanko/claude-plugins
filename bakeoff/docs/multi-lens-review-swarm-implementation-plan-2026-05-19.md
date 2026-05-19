# Multi-Lens Review Swarm Implementation Plan

Date: 2026-05-19

Status: proposed

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

The plugin should draft 2-3 separate `type: "gather"` work orders, each with
the normal `facet.id: "code-review"` shape and a lens-specific `focus`,
`include`, and `exclude`. Each lens run should keep automatic code-review
triage enabled by default. After the runs finish, Claude should read the
artifacts and produce a cross-run summary. Optional synthesis is a follow-up,
not an automatic hidden step.

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

### Lens Selection

Use free-text lens selection, not a separate UI picker.

Recognize explicit lens phrases such as:

- `security`
- `correctness`
- `tests`
- `performance`
- `UX`
- `frontend`
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
That would run 5 separate review work orders. I recommend narrowing this to 2-3
lenses unless you really want the extra cost and summary volume. Tell me which
3 to keep, or say `run all 5`.
```

The first implementation can hard-stop at 3 unless the user explicitly says to
run all requested lenses. Even then, prefer a clear warning over clever
automation.

## Preview And Cost Messaging

Before writing files, show a compact preview of every lens run and include a
plain cost note.

Suggested wording:

```text
This will run 3 separate review work orders:

1. Security review
2. Performance review
3. UX/frontend behavior review

Each run uses the normal code-review facet shape, narrowed to one lens.
Cost note: this is about 3x a normal review. Each lens runs two providers, one
judge, and code-review triage unless disabled.

Write, validate, and run these one after another? Reply `write and run`, reply
`show` to print the full JSON, or tell me what to change.
```

Do not warn on normal single-lens review. The warning exists only when the user
has opted into a multi-lens run.

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
from normal review drafting. The only difference is the lens-specific `goal`,
`background`, and facet text.

Prefer readable lens slugs in generated ids and run ids:

```text
review-auth.security.work-order.json
review-auth.performance.work-order.json
review-auth.ux.work-order.json
```

If this conflicts with the existing generic split-flow implementation, numeric
`.part-N` names are acceptable for the first patch, but lens slugs are better
for the user-facing artifact list.

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
- An optional synthesis prompt.

Suggested summary shape:

```text
Multi-Lens Review Summary

Runs:
- security: runs/review-auth.security/report.md, triage: runs/review-auth.security/triage/triage.md
- performance: runs/review-auth.performance/report.md, triage: runs/review-auth.performance/triage/triage.md
- ux: runs/review-auth.ux/report.md, triage: runs/review-auth.ux/triage/triage.md

Most Actionable:
1. [security] ...
2. [performance] ...
3. [ux] ...

Overlap:
- Security and correctness both flagged ...

Clean Lenses:
- UX produced no triaged real issues.

Next:
- `bakeoff show review-auth.security`
- `bakeoff show review-auth.performance`
- `bakeoff show review-auth.ux`

I can draft a synthesis work order over these triaged reports if you want one
prioritized fix plan.
```

## Optional Synthesis

Do not synthesize automatically. Ask after the cross-run summary.

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
Want a synthesis pass that dedupes these triaged lens results into one
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
- Add the cost note to multi-lens previews.
- Keep per-lens triage enabled unless disabled by the user.
- Require explicit `write and run` approval before writing or executing files.
- Add the post-run cross-run summary requirements.
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

Do not treat these as personas. They are facet text presets.

### 3. Drafting And Naming

For each selected lens:

- Create one normal review work order.
- Use `facet.id: "code-review"`.
- Keep providers, judge, budgets, and scope policy aligned across lens runs.
- Add lens-specific goal/background/facet text.
- Prefer `<base>.<lens>.work-order.json` filenames.
- Validate all generated work orders before running any.

### 4. Execution

Run sequentially using existing commands:

```text
bakeoff research <lens-work-order> --base <base> --diff
```

Use the existing split-flow stop rules:

- Continue after exit `0` or `3`.
- Stop on validation failure, exit `1`, exit `2`, exit `130`, interruption, or
  command failure.
- Summarize completed and failed parts before asking whether to continue.

### 5. Summary

After execution, read artifacts from each completed lens run. Build the
cross-run summary in the final assistant response. Do not write a new summary
artifact in v1 unless the user asks.

If future users repeatedly want a persisted summary, add a lightweight
`multi-lens-summary.md` file later. That should still be a plugin-created
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
  normal review work orders and summarizes them.
- `docs/work-orders.md`: note that multi-lens review is not a work-order schema
  feature.
- `docs/task-fit-test-scenarios.md`: manual regression scenarios.

No Go source changes are required for v1 unless the implementation chooses to
add a persisted summary artifact or a CLI-level batch command, which this plan
does not recommend.

## Test Scenarios

Manual plugin scenarios:

1. Plain review request drafts one normal `code-review` work order.
2. Explicit two-lens request previews two separate work orders with a cost
   note.
3. `review swarm` without lenses asks which 2-3 lenses to run.
4. Five-lens request warns and asks the user to narrow or explicitly run all.
5. `--no-triage` applies to all lens runs and the final summary marks findings
   untriaged.
6. A validation failure in one generated lens stops all execution before any
   run starts.
7. One lens fails during execution; the plugin summarizes completed runs and
   asks before continuing.
8. Completed triaged runs produce a cross-run summary with report paths, triage
   paths, top actionable items, overlap, clean lenses, and next commands.
9. User accepts synthesis; plugin drafts a separate `analyze` work order over
   the triaged artifacts.

## Effort And Risk

Plugin-only v1 is small:

- Drafting and preview rules: 0.5-1 day.
- Lens presets and naming policy: 0.5 day.
- Cross-run artifact summary instructions: 0.5-1 day.
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

Mitigate these by keeping the default single-lens, capping normal multi-lens
previews at 2-3 lenses, keeping triage on by default, and requiring explicit
approval for synthesis.

## Non-Goals

- No `facets[]` schema.
- No provider-specific facets.
- No debate swarm inside one work order.
- No new Go CLI batch runner.
- No automatic cross-run triage.
- No automatic synthesis.
- No code fixes or patch application based on review output unless the user
  makes a separate explicit request.

