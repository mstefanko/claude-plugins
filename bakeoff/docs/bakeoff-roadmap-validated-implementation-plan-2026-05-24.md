# Bakeoff Roadmap Validated Implementation Plan - 2026-05-24

Status: implementation plan for maintainers

Scope: no code changes. This plan validates and folds in the two roadmap audit
reports:

- `docs/roadmap-audit-implementation-2026-05-24.md`
- `docs/roadmap-audit-value-2026-05-24.md`

It supersedes the ordering in
`docs/bakeoff-roadmap-value-risk-implementation-assessment-2026-05-24.md`
where the audits found a stronger value/risk sequence.

Primary evidence:

- `docs/agentic-loop-evidence-synthesis-2026-05-23.md`
- `docs/evidence-backed-bakeoff-roadmap-ideas-2026-05-23.md`
- Current implementation in `internal/workorder/workorder.go`,
  `internal/provider/provider.go`, `internal/decision/decision.go`,
  `internal/report/report.go`, `internal/commands/buildcmd/report.go`,
  `internal/commands/escalatecmd/escalate.go`,
  `internal/commands/reruncmd/rerun.go`,
  `internal/commands/validatecmd/validate.go`,
  `internal/artifact/artifact.go`, `internal/manifest/manifest.go`,
  `internal/triage/state.go`, and `skills/bakeoff-run/SKILL.md`.

## Validation Summary

The audits are broadly consistent with the prior assessment, but the following
corrections should be folded into the actual implementation plan.

| Audit finding | Validation | Planning decision |
| --- | --- | --- |
| Tighten `witness` is under-bucketed. | Valid. The synthesis names witness tightening in the executive posture, evidence table, implications, open gaps, and roadmap step 1. | Promote to Ship Now, but give it its own slice because implementation is M-L. |
| Accepted-finding feedback is under-weighted. | Valid. The synthesis open gaps put real accepted findings, false positives, cost, latency, and triage time first. | Make it the first Measure-First infrastructure item. |
| Provider-family metadata is a hidden prerequisite. | Valid. `BackendSpec` has no `Family` field today, but third-party judge advisory, `judge_policy`, rotation, and telemetry need it. | Extract a micro-item before any judge-family policy/advisory work. |
| Metric verifier linting is cheaper than rated. | Valid. `validatecmd` warnings are additive and the existing metric warning pattern is already present. | Move earlier as a quick win; complexity S, risk Medium. |
| Several report items collide in `report.go`. | Valid. `internal/report/report.go` and `internal/commands/buildcmd/report.go` will carry selector confidence, witness rendering, judge-only copy, and post-run guidance. | Add a small report-rendering prep slice before broad report changes. |
| Vendor maturity scan is missing. | Valid. The synthesis open gaps include current vendor/framework maturity where it affects product decisions. | Add a Measure-First research item before vendor-specific defaults. |
| Route advisor, stop-here, bundle, third-party advisory values were slightly high. | Valid. Keep buckets, but lower phrasing: high or medium value rather than "understated" or "medium-high" where evidence is thinner. | Keep them in plan because cost is low, but do not let them outrank witness or feedback infrastructure. |

The Reject/Avoid axis stands. No low-evidence bloat item should move into Ship
Now, and no high-evidence item is wrongly rejected.

## Implementation Order

This is the recommended build order.

| Order | Item | Tier | Complexity / risk | Why this order |
| --- | --- | --- | --- | --- |
| 0 | Report renderer prep | Enabler | S / Low-Medium | Reduces collisions before selector-confidence, witness, judge-only, provider-authored test, and post-run report work. |
| 1 | Tighten `witness` audit/falsification | Ship Now | M-L / Medium-High | Highest evidence-backed feature; roadmap step 1; needs its own slice. |
| 2 | Routing copy and task-fit route advisor | Ship Now | S / Low | Aligns user language with the tightened witness contract and keeps wrong loops cheap to avoid. |
| 3 | Metric verifier linting | Ship Now quick win | S / Medium | Cheap build-side safety improvement with strong evidence around noisy metrics. |
| 4 | Selector confidence and report warnings | Ship Now | M / Medium | Trust-building report layer; should land after report prep. |
| 5 | Post-run, stop-here, triage freshness, and bundle guidance | Ship Now | S-M / Medium | One artifact-aware next step, with structured artifacts as source of truth. |
| 6 | Provider-family metadata micro-item | Prerequisite | S-M / Medium | Required before judge-family advisory, telemetry relation fields, `judge_policy`, or rotation. |
| 7 | Accepted-finding feedback capture | Measure-First infrastructure | M / Medium | Top strategic unblocker for false-positive and accepted-outcome measurement. |
| 8 | Local telemetry fields | Measure-First infrastructure | M-L / Medium | Needed before changing judge defaults or productizing judge-family experiments. |
| 9 | Third-party judge advisory | Ship Soon, advisory-only | M / Medium after metadata | Useful warning, but do not change defaults yet. |
| 10 | Internal review benchmark and judge-convergence measurements | Measure First | S-M as recipe, more if productized | Uses feedback and telemetry to decide whether policy changes are justified. |
| 11 | Vendor maturity scan | Measure First research | S / Medium | Covers missing synthesis gap before vendor-specific defaults or integrations. |
| 12 | Optional later experiments | Gated | Variable | `judge_policy`, judge rotation CLI, witness self-consistency, and hard different-family rules wait for measured evidence. |

## Slice 0: Report Renderer Prep

Recommendation: build first as a small enabler.

Evidence and reason for inclusion:

- The implementation audit found that six near-term items touch
  `internal/report/report.go` or `internal/commands/buildcmd/report.go`.
- `internal/report/report.go` already contains outcome, judge status, decision
  audit, escalation, and provider output rendering.
- The work is not valuable to users by itself, but it lowers review collision
  risk for the highest-value report changes.

Implementation details:

- Add small report helper functions for:
  - Advisory blocks.
  - Selector-strength lines.
  - Compact "next step" blocks.
  - Shared wording for "advisory only" and "does not change source decision".
- Keep section ordering stable:
  - Outcome.
  - Selector confidence or advisory status.
  - Status/caveats.
  - Evidence details.
  - Next step.
- Avoid a broad report rewrite.
- Keep build report helpers local to `internal/commands/buildcmd/report.go`
  unless shared code naturally emerges.

Value:

- Indirect but important. It makes the next slices smaller and easier to
  review.

Risk and concerns:

- Complexity: S.
- Risk: Low-Medium.
- Concern: a "prep" PR can become an unbounded refactor.
- Constraint: no behavior changes except harmless helper extraction and exact
  output preservation unless a test intentionally updates a tiny section.

Validation:

- Existing report tests should pass.
- Add no new product claims in this slice.

Open questions:

- Whether build and research reports should share helper code now or only share
  wording conventions. Default: share wording conventions first.

## Slice 1: Tighten `witness` Audit/Falsification

Recommendation: Ship Now, as its own slice.

Evidence and reason for inclusion:

- The synthesis executive summary says the evidence supports tightening
  code-review `witness` into an advisory adversarial audit of the source report.
- The synthesis multi-report agreement says escalation should remain post-run
  and advisory; `witness` and `dispute` should not mutate the source run.
- The synthesis evidence table rates the code-review witness audit contract as
  supported by local implementation analysis, vendor/pattern inference, and
  dogfood evidence.
- The roadmap backlog marks witness tightening as "Now" and the suggested
  implementation sequence lists it first.
- The value audit found this is the strongest case of an evidence-backed item
  being demoted because of effort.

User value:

- Very high.
- Users get a cheap way to challenge report soundness without asking for a
  fresh third answer or mutating the source decision.
- Especially valuable for code-review runs where findings are candidates until
  verified.

Implementation details:

- Primary files:
  - `internal/workorder/workorder.go`
  - `internal/prompt/prompt.go`
  - `internal/prompt/fixtures/escalation-witness.txt`
  - `internal/commands/escalatecmd/escalate.go`
  - `internal/commands/escalatecmd/escalate_test.go`
  - `internal/report/report.go`
  - `internal/report/report_test.go`
- Current `ValidateEscalationWitnessResult` requires fields but accepts
  `material_errors`, `missed_material`, `triage_concerns`, `out_of_scope`,
  `recommended_next_checks`, and `rationale` as untyped arrays.
- Decide and implement a structured witness item schema for at least:
  - `material_errors`
  - `missed_material`
  - `triage_concerns`
- Proposed object shape:
  - `claim`: concise statement.
  - `evidence`: artifact path, file:line, or source report reference.
  - `why_material`: why it matters to the source decision or review findings.
  - `severity`: `low`, `medium`, `high`, or `critical` where applicable.
  - `recommended_check`: concrete human or tool follow-up.
- Keep top-level `would_change_outcome` and `source_decision_effect`, but
  render them as advisory.
- Add code-review-specific target payloads when fresh triage exists:
  - bounded source finding targets, capped to avoid payload blowup;
  - missing-control pass;
  - file:line proof obligations where source artifacts support them.
- Preserve source-run immutability. Witness output must not set a canonical
  winner or overwrite source decision fields.

Risk and concerns:

- Complexity: M-L.
- Risk: Medium-High.
- Concerns:
  - Prompt over-negativity.
  - Schema/prompt drift causing validation failures.
  - Payload growth and prompt trimming hiding relevant evidence.
  - Report noise if every witness item is rendered at full length.
  - The word `witness` still reads less direct than `audit`.
- Mitigations:
  - Keep `witness` advisory-only in report copy.
  - Cap targets.
  - Require evidence pointers, not just critique.
  - Keep report rendering concise with expandable artifact references.

Validation:

- Unit tests for structured witness validation.
- Prompt fixture tests for generic witness and code-review witness.
- Escalation tests for witness run artifacts, no canonical winner, advisory
  report label, fresh triage, stale triage, missing triage, and provider
  failure.
- Dogfood on a code-review run with a third provider.

Open questions before implementation:

- Exact per-item schema: one shared object shape or separate shapes for
  `material_errors`, `missed_material`, and `triage_concerns`.
- Whether to introduce a per-claim verdict schema now or keep the existing
  top-level witness result with structured arrays.
- Whether `confidence` should remain in witness output. If retained, it must be
  advisory text only, never a gate.
- Whether to add an `audit` alias later. Do not rename the runtime mode in this
  slice.

Needs measured before later expansion:

- Whether tightened witness finds material report errors without excessive false
  positives.
- Whether users accept/reject witness findings at a useful rate.
- Whether a different-family witness improves calibration without brittle
  provider availability.

## Slice 2: Routing Copy And Task-Fit Route Advisor

Recommendation: Ship Now after the witness contract is clear.

Evidence and reason for inclusion:

- The roadmap says the normal loop should stay thin and users should be guided
  into the cheapest adequate loop.
- The synthesis says multi-agent benefit is task-shaped, not universal.
- The synthesis also flags the naming tension: `witness` is the right existing
  mode for fighting a report, but the word is weak UX.

User value:

- High.
- Reduces wrong-mode provider calls.
- Helps users distinguish:
  - broad report audit: `witness`;
  - named contested point: `dispute`;
  - fresh third answer: `independent`;
  - no Bakeoff needed: stop or direct command.

Implementation details:

- Primary file: `skills/bakeoff-run/SKILL.md`.
- Supporting docs:
  - `README.md`
  - `docs/cli-reference.md`
  - `commands/run.md`
- Update examples for:
  - "audit this report";
  - "second opinion on this report";
  - "fight the findings";
  - "bare dispute this report";
  - "second opinion on the question";
  - "add Gemini to this completed run";
  - "is finding F-007 real".
- Add a one-line route advisor:
  - `Why this loop: witness audit of current report`
  - `Why this loop: focused dispute packet`
  - `Why this loop: fresh third answer`
  - `Why this loop: build-verifier path`
  - `Why this loop: single-agent advised`
- Keep "draft anyway" for weak-fit warnings.

Risk and concerns:

- Complexity: S.
- Risk: Low.
- Concerns:
  - Overfitting phrases.
  - Too much preview prose.
  - Accidentally making alternatives equal-weight when one route is clearly
    right.
- Mitigation: one primary route; compact alternatives only when ambiguous.

Validation:

- Manual skill scenarios covering the examples above.
- Verify existing route behavior for build, gather/review, compare, analyze,
  multi-lens, and escalation.

Open questions:

- Whether an `audit` alias is needed after users have experience with tightened
  `witness`. Measure usage/confusion first.

## Slice 3: Metric Verifier Linting Quick Win

Recommendation: Ship Now as a cheap build-side safety improvement.

Evidence and reason for inclusion:

- The synthesis says execution evidence should outrank judge preference for
  build tasks, but green tests and metrics can still be misleading.
- The synthesis open gaps call for calibrating metric verifier defaults for
  performance work.
- The roadmap says metric guidance/linting helps reduce false winners.
- The implementation audit found the change is S effort because
  `internal/commands/validatecmd/validate.go` already has additive metric
  warnings.

User value:

- High for build users.
- Prevents obviously weak metric work orders from looking more decisive than
  they are.

Implementation details:

- Primary file: `internal/commands/validatecmd/validate.go`.
- Tests: `internal/commands/validatecmd/validate_test.go`.
- Docs:
  - `docs/work-orders.md`
  - `docs/cli-reference.md`
  - `README.md`
  - `skills/bakeoff-run/SKILL.md`
- Add conservative warnings for metric verifiers:
  - missing `metric.min_delta_percent`;
  - missing `metric.noise_floor_percent`;
  - `metric.min_runs` too low when a noise floor is declared;
  - repo-relative benchmark/probe commands with empty `build.protected_paths`;
  - final metric JSON requirements when `min_runs > 1`.
- Do not add hard validation errors. Keep these warnings.

Risk and concerns:

- Complexity: S.
- Risk: Medium.
- Concerns:
  - False-positive warnings for valid project-specific benchmark setups.
  - Guidance can go stale by language or toolchain.
- Mitigation: generic warnings only; let users make intent explicit in the work
  order.

Validation:

- Table-driven validate tests for each warning.
- One docs example for a stable metric and one inconclusive/noisy metric.

Open questions:

- What threshold should trigger a "min_runs too low" warning. Default: warn
  only for obviously weak values, such as `min_runs` absent or `min_runs == 1`
  when a noise floor is present.

Needs measured before stricter behavior:

- Local false-positive rate of warnings across real build work orders.
- Whether metric warnings reduce judge-only or inconclusive build outcomes.

## Slice 4: Selector Confidence And Report Warnings

Recommendation: Ship Now after report prep.

Evidence and reason for inclusion:

- The synthesis says build gates and metrics should outrank LLM preference.
- The roadmap calls for visibly different selector strength labels.
- The implementation audit says the report work is closer to M because it spans
  research and build renderers plus fixtures.

User value:

- Very high.
- Users can tell when a result was selected by gate, metric, swapped judge,
  union/dedupe, advisory witness, focused dispute, or unresolved state.

Implementation details:

- Primary files:
  - `internal/report/report.go`
  - `internal/report/report_test.go`
  - `internal/commands/buildcmd/report.go`
  - `internal/commands/buildcmd/*_test.go` where build report fixtures live
- Use existing `decision.json` fields:
  - `mode`
  - `decision_kind`
  - `selection_basis`
  - `canonical_winner`
  - `judge_ran`
  - `judge_completed`
  - `stalled_at`
  - `judge_passes`
  - `caveats`
- Add categorical labels, not numeric confidence:
  - `gate`
  - `metric`
  - `swapped judge`
  - `judge-only`
  - `union/dedupe`
  - `advisory witness`
  - `focused dispute`
  - `unresolved`
- Add judge-only degraded confidence copy:
  - weaker than gate/metric evidence;
  - still useful as preference evidence;
  - not equal to executed verifier evidence.
- Add provider-authored tests reminder in build reports near test/probe listings:
  provider-authored tests are supporting evidence, not selector truth.

Risk and concerns:

- Complexity: M.
- Risk: Medium.
- Concerns:
  - Fake precision if labels are overexplained.
  - Report clutter.
  - Fixture churn.
- Mitigation: 3-5 line selector section, categorical terms only, shared helper
  wording from Slice 0.

Validation:

- Report fixture coverage for:
  - gate winner;
  - metric winner;
  - judge winner;
  - judge failure;
  - tie/unresolved;
  - gather union;
  - witness advisory;
  - dispute advisory;
  - provider-authored tests.

Open questions:

- Exact label for research compare/analyze stable judge: `swapped judge` versus
  `stable judge`. Default: `swapped judge`, because the bias control matters.

## Slice 5: Post-Run Guidance, Stop-Here, Triage Freshness, And Bundle Guidance

Recommendation: Ship Now as a structured-artifact guidance slice.

Evidence and reason for inclusion:

- The roadmap says users should be guided into the smallest loop that produces
  useful evidence.
- The synthesis says structured artifacts beat hidden chat state.
- The audits slightly lower the value of route advisor, stop-here, and bundle
  from "very high" to high or medium, but keep them in Ship Now because they
  are cheap and reduce waste.

User value:

- High for post-run recommendations and stop-here.
- Medium-high for triage freshness.
- Medium for source-run bundle guidance.

Implementation details:

- Primary skill/docs:
  - `skills/bakeoff-run/SKILL.md`
  - `README.md`
  - `docs/cli-reference.md`
- Optional code surfaces if command output changes:
  - `internal/commands/showcmd/show.go`
  - `internal/commands/bundlecmd/bundle.go`
  - `internal/triage/state.go`
- Rules:
  - At most one primary continuation recommendation.
  - Use structured artifacts, not `report.md`, as the source of truth.
  - Recommend `bakeoff triage <run-id> --force` first when triage is missing,
    failed, stale, or dry-run only.
  - Offer escalation as fallback after triage guidance, not as an equal sibling
    when triage is clearly stale.
  - Use bundle as the preferred reader for source plus escalation children.
  - Include stop-here when artifacts are sufficient or Bakeoff is a weak fit.

Risk and concerns:

- Complexity: S-M.
- Risk: Medium.
- Concerns:
  - Bad recommendations if only prose is inspected.
  - Recommendation fatigue.
  - Overusing stop-here when the user explicitly asked to continue.
- Mitigation: one primary recommendation, structured artifacts first, explicit
  override path.

Validation:

- Manual scenarios:
  - sufficient result, stop;
  - review triage missing;
  - review triage failed;
  - judge failed;
  - unresolved compare;
  - build winner;
  - source with escalation children.
- Command tests only if `show` or `bundle` output changes.

Open questions:

- Whether to enforce triage freshness in code or keep it as skill guidance
  initially. Default: skill guidance now, command enforcement later if users
  still escalate stale triage.

## Slice 6: Provider-Family Metadata Micro-Item

Recommendation: build before any judge-family advisory, policy, rotation, or
telemetry relation field.

Evidence and reason for inclusion:

- The synthesis flags judge-family convergence as an unresolved risk.
- The roadmap proposes third-party judge advisory and later judge policy, but
  the implementation audit found all of these depend on family metadata.
- Current `BackendSpec` in `internal/provider/provider.go` lacks a `Family`
  field.

User value:

- Indirect but important.
- Prevents ad-hoc family inference and duplicated metadata work.

Implementation details:

- Primary files:
  - `internal/provider/provider.go`
  - `internal/provider/provider_test.go`
- Add `Family string` to `BackendSpec`.
- Populate current backends with explicit stable values.
- Add helpers if useful:
  - `FamilyForBackend(name string) string`
  - `SameFamily(a, b string) bool`
  - `JudgeFamilyRelation(judge, providers) string`
- Keep this slice metadata-only:
  - no advisory;
  - no default changes;
  - no work-order schema changes.

Risk and concerns:

- Complexity: S-M.
- Risk: Medium.
- Concerns:
  - "Provider family" and "model family" may diverge.
  - Copilot may wrap multiple underlying model families.
  - The code records requested model strings, not provider-resolved dated model
    IDs.
- Mitigation: document family as provider/catalog family, not verified
  underlying model identity.

Validation:

- Provider catalog tests.
- Ensure `KnownBackends` and lookup behavior still preserve metadata.

Open questions:

- Exact family value for Copilot. Options: `github-copilot`, `microsoft`, or
  `unknown`. Default recommendation: use `github-copilot` and document that it
  is a product/provider family, not guaranteed underlying model lineage.
- Whether custom/unknown future backends should get `family: "unknown"` or fail
  closed. Default: unknown family should suppress advisory, not fail validation.

## Slice 7: Accepted-Finding Feedback Capture

Recommendation: first Measure-First infrastructure item.

Evidence and reason for inclusion:

- The synthesis top open gap is an internal review benchmark across real target
  repositories comparing accepted findings, false positives, latency, provider
  cost, and developer triage time.
- The synthesis also marks exact production false-positive rates as weak or
  unknown.
- The value audit correctly says feedback capture is the measurement unlock for
  judge policy, judge rotation, third-party judge defaults, and review
  calibration.

User value:

- Strategic high value.
- Daily direct value depends on friction. If it feels like bookkeeping, users
  will skip it.

Implementation details:

- Primary package area:
  - `internal/triage`
  - new command under `internal/commands` or a triage subcommand
  - `internal/manifest/manifest.go`
  - `internal/commands/showcmd/show.go`
  - `internal/commands/bundlecmd/bundle.go`
- Possible artifact:
  - `triage/human-feedback.json`
- Feedback should reference stable triage finding IDs.
- Minimal actions:
  - `accepted`
  - `rejected`
  - `fixed`
  - `deferred`
  - `converted_to_test`
- Keep comments optional.
- Allow batch annotation from JSON for maintainers running benchmarks.

Risk and concerns:

- Complexity: M.
- Risk: Medium.
- Concerns:
  - Annotation burden.
  - Ambiguous finding identity if triage is rerun.
  - Users may annotate selected samples only, biasing data.
- Mitigation:
  - Optional and local-only.
  - Store triage input hashes or triage run identity with feedback.
  - Make it easy to update or replace feedback after triage rerun.

Validation:

- Command tests for creating, updating, and reading feedback.
- Manifest tests for feedback artifact presence.
- Bundle/show tests if feedback is surfaced.

Open questions:

- Command shape: `bakeoff triage feedback` versus new `bakeoff feedback`.
  Default: triage subcommand, because feedback attaches to triage findings.
- Whether "accepted" means "real issue" or "will fix now". Default: separate
  `accepted` from `fixed`.

Needs measured before policy features:

- Accepted/rejected rate by provider pair.
- Accepted/rejected rate by triage class and severity.
- Developer triage time where available.
- Whether witness/dispute changes improve accepted outcome quality.

## Slice 8: Local Telemetry Fields

Recommendation: build after feedback shape is defined, before policy changes.

Evidence and reason for inclusion:

- The roadmap says future options should be chosen from run evidence, not
  vibes.
- The synthesis open gaps call for production telemetry covering task type,
  provider pair, model aliases, wall time, output truncation, judge result,
  triage class, accepted findings, reruns, and post-merge defects.
- Judge-family advisory, policy, and rotation all need measurement.

User value:

- Strategic high value.
- Direct value is delayed, but it makes future default changes defensible.

Implementation details:

- Primary files:
  - `internal/artifact/artifact.go`
  - `internal/manifest/manifest.go`
  - `internal/summary`
  - `internal/commands/lscmd`
  - `internal/commands/showcmd`
  - `internal/commands/bundlecmd`
  - build diagnostics code
- Prefer additive fields in existing local artifacts:
  - `meta.json`
  - `decision.json`
  - `diagnostics.json`
  - `triage/status.json`
  - `manifest.json`
- Add `telemetry.json` only if existing files become confusing or too large.
- Include:
  - route classification;
  - selector path;
  - provider family diversity;
  - judge-family relation;
  - prompt trims;
  - output caps;
  - triage state;
  - escalation follow-ups;
  - feedback summary if present.
- Do not store source text, prompts, or provider output content in telemetry
  fields.

Risk and concerns:

- Complexity: M-L.
- Risk: Medium.
- Concerns:
  - Privacy.
  - Artifact bloat.
  - Unstable field names.
  - Mixing measurement metadata with source content.
- Mitigation:
  - local-only;
  - content-light;
  - additive schema;
  - stable names before implementation.

Validation:

- Artifact and manifest tests.
- `ls --json` tests only if fields are exposed there.
- Dogfood matrix across gather, compare, analyze, review, build, witness,
  dispute, and independent escalation.

Open questions:

- Whether to include telemetry in `manifest.json` or keep only summaries there.
- Whether to create a local export command now. Default: no export command until
  schema settles.

Needs measured before policy features:

- Judge-family relation versus disagreement or human reversal.
- Third-party judge availability and failure rates.
- Witness accepted/rejected outcome quality.
- Task-fit warning overrides and resulting usefulness.

## Slice 9: Third-Party Judge Advisory

Recommendation: build after provider-family metadata; advisory only.

Evidence and reason for inclusion:

- The synthesis says position swapping handles order bias but not family
  convergence.
- The synthesis also says production solutions for judge-convergence bias are
  unverified, so this should not change defaults yet.
- The roadmap recommends advisory first, policy later.

User value:

- Medium.
- Useful for high-risk or judge-heavy runs.
- Helps users see when a non-contestant judge family exists, without implying
  it is always better.

Implementation details:

- Depends on Slice 6 provider-family metadata.
- Primary files:
  - `internal/provider/provider.go`
  - `internal/commands/doctorcmd/doctor.go`
  - `internal/commands/validatecmd/validate.go`
  - `skills/bakeoff-run/SKILL.md`
  - possibly `internal/workorder/draft.go` for preview/draft advisory
- Advisory surfaces:
  - `bakeoff doctor`;
  - `bakeoff validate` warnings;
  - `/bakeoff:run` preview;
  - draft comments or summary copy.
- Do not auto-switch judge.
- Do not add `judge_policy` schema in this slice.

Risk and concerns:

- Complexity: M after metadata; M-L if bundled with policy.
- Risk: Medium.
- Concerns:
  - Warning fatigue.
  - Third backend might be weaker or unauthenticated.
  - Family metadata might overstate independence.
- Mitigation:
  - advisory copy only;
  - include "not measured locally yet";
  - suppress warning when no ready alternative exists.

Validation:

- Doctor/validate tests for:
  - only two ready families;
  - third family ready;
  - third backend missing/unavailable;
  - judge same family as provider;
  - judge non-contestant family.

Open questions:

- Should advisory trigger for every same-family judge or only judge-heavy modes.
  Default: judge-heavy decisions and preview/draft contexts only.

Needs measured before stronger policy:

- Whether non-contestant judge advisory changes accepted outcomes.
- Whether non-contestant judges reduce swapped-judge disagreement, disputes, or
  human reversals.

## Slice 10: Internal Review Benchmark And Judge-Convergence Measurement

Recommendation: measure before building judge policy or rotation CLI.

Evidence and reason for inclusion:

- The synthesis top open gap calls for an internal benchmark across real target
  repositories.
- The synthesis second open gap calls for judge-convergence measurement by
  rotating judge family on the same completed provider outputs.
- The roadmap says rotation should be measurement/high-risk rerun, not the
  default selector.

User value:

- Strategic.
- Provides evidence to decide whether cross-model review, same-family
  multi-lens, third-party judges, and rotation actually help.

Implementation details:

- Start as docs/scripts/dogfood recipe, not core CLI.
- Inputs:
  - completed runs;
  - accepted-finding feedback;
  - local telemetry;
  - provider family metadata.
- Outputs:
  - benchmark report artifact under `docs/` or `research/`;
  - summary of accepted findings, false positives, latency, provider cost where
    known, judge disagreement, escalation outcomes, and triage time.
- Keep source decisions immutable.

Risk and concerns:

- Complexity: S-M as recipe; M-L if productized.
- Risk: Medium.
- Concerns:
  - Selection bias in benchmark repositories.
  - Judge shopping if alternate judge output looks like a replacement decision.
  - Cost and provider availability.
- Mitigation:
  - label as calibration;
  - use fixed run sets;
  - report disagreement, not just winners.

Validation:

- Run benchmark on a fixed local sample.
- Confirm results can be derived without reading source text or prompts where
  possible.

Open questions:

- Which repositories and run types form the first benchmark set.
- Whether cost can be measured directly or only approximated.

Needs measured before implementing:

- `judge_policy`.
- judge-family rotation as a CLI.
- hard different-family judge defaults.
- default third-party judge selection.

## Slice 11: Vendor And Framework Maturity Scan

Recommendation: add as Measure-First research before vendor-specific product
decisions.

Evidence and reason for inclusion:

- The synthesis open gaps explicitly call for researching current
  vendor/framework maturity only where it affects product decisions:
  Gemini/Copilot review false-positive rates, Devin-style autonomy,
  Cursor/Jules background-agent workflows, AutoGen GraphFlow/Magentic-One, and
  LangGraph persistence tradeoffs.
- The value audit found this was missing from the prior assessment.

User value:

- Medium strategic value.
- Prevents Bakeoff from copying external patterns that do not fit the thin,
  artifact-led architecture.

Implementation details:

- Create a focused research report, not code.
- Scope questions:
  - Does current Gemini/Copilot evidence justify changing review defaults?
  - Do background-agent products have patterns Bakeoff should copy for
    artifact handoff without auto-merge?
  - Do orchestration frameworks show persistence patterns worth adopting, or do
    they push Bakeoff toward a workflow engine?
  - Are vendor claims backed by benchmarks relevant to Bakeoff tasks?
- Use current primary sources when the scan is performed. Vendor maturity is
  time-sensitive.
- Tie every finding to a product decision; avoid general market survey sprawl.

Risk and concerns:

- Complexity: S research pass.
- Risk: Medium.
- Concerns:
  - Current vendor info changes quickly.
  - Marketing claims can look like evidence.
  - Research can sprawl.
- Mitigation:
  - restrict to product-decision questions;
  - prefer primary sources and benchmark reports;
  - record uncertainty explicitly.

Validation:

- Produce a dated report with citations.
- Identify which Bakeoff roadmap items, if any, should change because of the
  scan.

Open questions:

- Which product decision should trigger the first scan. Default: only scan
  before changing provider defaults, adding background-agent behavior, or
  adopting orchestration persistence.

## Later Gated Items

These should not be implemented until the required measurement exists.

### `judge_policy` Or Prefer-Different-Family Knob

Do not implement as schema now.

Prerequisites:

- Provider-family metadata.
- Third-party advisory dogfood.
- Telemetry showing judge-family relation.
- Accepted-finding feedback or human reversal data.

Measurement required:

- Non-contestant judges reduce disagreement, disputes, or human reversals.
- Provider availability is reliable enough that the preference does not make
  drafting brittle.

Concern:

- Product value is weak without data; a schema knob can become permanent UI
  surface before it earns its keep.

### Judge-Family Rotation CLI

Keep as recipe until measured.

Prerequisites:

- Provider-family metadata.
- Telemetry.
- Fixed benchmark set.
- Report lineage design that labels alternate decisions as calibration.

Measurement required:

- Rotation changes outcomes often enough to justify product surface.
- Alternate judge results correlate with accepted findings or lower reversal
  rates.

Concern:

- Judge shopping and source-decision confusion.

### Witness Self-Consistency `n=3`

Defer.

Prerequisites:

- Tightened witness contract shipped.
- Accepted/rejected witness feedback exists.
- Single-witness false-positive and false-negative patterns are known.

Measurement required:

- `n=3` reduces false positives or missed material errors enough to justify
  cost and report complexity.

Concern:

- Same-family self-consistency does not solve family-level blind spots.

### Hard Different-Family Witness Or Judge Rule

Defer.

Prerequisites:

- Provider-family metadata.
- Third-party advisory.
- Telemetry.
- Witness and judge-family benchmark data.

Measurement required:

- Different-family rule improves calibration without provider availability
  brittleness.

Concern:

- A worse or unavailable third provider can reduce quality even if family is
  different.

## Items To Keep Rejected Or Avoided

The audits validate the prior reject/avoid bucket.

| Item | Decision | Reason |
| --- | --- | --- |
| Hidden patch synthesis or cherry-picking | Reject | Derived patches need their own explicit build/review loop and fresh verification. |
| Default debate loops | Reject for default | Cost, latency, and coordination complexity are not justified by current evidence. |
| Three worker providers in normal work orders | Avoid | Keep exact-two-provider normal work orders; use escalation for third-provider evidence. |
| Auto-apply, auto-merge, auto-commit, auto-push, auto-PR | Reject | Violates user-owned handoff and increases blast radius. |
| New public `adversarial` escalation mode | Reject for now | Tightened `witness` covers the need without mode bloat. |
| Per-finding agent fanout | Defer/reject | High cost and review fatigue; bounded witness targets should come first. |
| Large `report.md` parser | Avoid | Structured artifacts are canonical and less brittle. |
| Verbal confidence gates | Reject | Single-model verbal confidence is not calibrated enough for automatic action. |
| Persona lenses as cross-family substitute | Avoid | Lenses can focus attention but do not replace provider-family diversity. |
| Build escalation | Defer | Current code rejects build source escalation; prefer inspect, rerun build, or explicit review/analyze follow-up. |
| Judge panels or juries | Defer | Too much orchestration surface without local evidence of routine value. |
| Batch schema or persistent orchestration | Defer | Pushes Bakeoff toward workflow-engine behavior and away from explicit run artifacts. |

## Open Questions Register

| Question | Needed for | Default answer until decided |
| --- | --- | --- |
| What is the exact structured witness item schema? | Slice 1 | Shared object with `claim`, `evidence`, `why_material`, optional `severity`, and `recommended_check`. |
| Should witness use per-claim verdicts now? | Slice 1 | No, unless schema review shows top-level result plus arrays is insufficient. |
| Should `confidence` remain in witness output? | Slice 1 | Yes, but advisory only and never a gate. |
| Should `audit` become an alias for `witness`? | Slice 2 or later | Not yet. Improve copy first and measure confusion. |
| What family should Copilot use? | Slice 6 | `github-copilot`, documented as provider family, not guaranteed underlying model family. |
| Should unknown provider family block warnings? | Slice 6/9 | No. Unknown suppresses family advisories. |
| Which command owns human feedback? | Slice 7 | Prefer `bakeoff triage feedback`. |
| What does "accepted" mean? | Slice 7 | Real issue accepted by human; separate from `fixed`. |
| Should telemetry get a new file? | Slice 8 | Prefer existing artifacts first; add `telemetry.json` only if needed. |
| Should third-party judge advisory fire for all same-family judges? | Slice 9 | No. Start with judge-heavy/high-risk contexts. |
| Which repositories form the first internal benchmark set? | Slice 10 | Pick a fixed small set of real code-review runs with feedback. |
| When is vendor maturity scan required? | Slice 11 | Before changing provider defaults, adding background-agent behavior, or adopting orchestration persistence. |

## Measurement Gates

Do not implement these until the listed measurement exists.

| Future item | Required measurement |
| --- | --- |
| `judge_policy` schema or default | Telemetry plus feedback showing non-contestant judges improve accepted outcomes, disagreement rate, dispute rate, or human reversal rate. |
| Judge rotation CLI | Fixed-run benchmark showing rotation produces useful calibration without judge-shopping confusion. |
| Witness self-consistency | Single-witness feedback showing noise or missed material errors that `n=3` can plausibly improve. |
| Hard different-family rule | Provider availability and outcome data showing different-family witnesses/judges improve calibration without brittleness. |
| Default third-party judge selection | Advisory dogfood plus telemetry showing better decision stability or accepted outcomes. |
| Vendor-specific provider defaults | Vendor maturity scan tied to Bakeoff use cases, with current evidence and uncertainty recorded. |
| Build metric hard errors | Local validate-warning data showing warnings are accurate enough to become failures. |
| Build escalation | Evidence that inspect/rerun/review/analyze follow-ups are insufficient and a build-specific advisory path has clear semantics. |

## Concrete First Milestone

Milestone 1 should be:

1. Slice 0 report renderer prep.
2. Slice 1 tightened witness audit/falsification.
3. Slice 2 routing copy aligned to tightened witness.
4. Slice 3 metric verifier linting.

This milestone covers the audit corrections without opening the heavier
judge-family policy work. It also turns the most evidence-backed roadmap item
into a real, testable feature while preserving Bakeoff's thin architecture.
