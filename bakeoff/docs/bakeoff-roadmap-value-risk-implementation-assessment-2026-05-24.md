# Bakeoff Roadmap Value/Risk Implementation Assessment - 2026-05-24

Status: synthesis report for maintainers

Scope: no code changes. This report combines the user-value review, the
implementation-complexity review, and the final value-versus-risk synthesis for
the evidence-backed Bakeoff roadmap.

Primary inputs:

- `docs/agentic-loop-evidence-synthesis-2026-05-23.md`
- `docs/evidence-backed-bakeoff-roadmap-ideas-2026-05-23.md`
- Current code cross-checks in `internal/workorder/workorder.go`,
  `internal/provider/provider.go`, `internal/decision/decision.go`,
  `internal/report/report.go`, `internal/commands/buildcmd/report.go`,
  `internal/commands/escalatecmd/escalate.go`,
  `internal/commands/reruncmd/rerun.go`,
  `internal/commands/validatecmd/validate.go`,
  `internal/artifact/artifact.go`, `internal/manifest/manifest.go`, and
  `skills/bakeoff-run/SKILL.md`.

## Executive Recommendation

Ship the legibility-heavy work first. The highest-value and lowest-risk roadmap
items are not bigger orchestration loops. They are clearer routing, clearer
selector confidence, better post-run guidance, and stronger report copy around
what the evidence can and cannot prove.

The current product contract is already aligned with the evidence base:

- Normal work orders require exactly two providers in
  `internal/workorder/workorder.go`.
- The provider catalog in `internal/provider/provider.go` knows backends,
  default models, optional status, prompt flavor, and build support, but does
  not yet encode provider family metadata.
- Build selection in `internal/decision/decision.go` is verifier-first: gate
  results, identical patch, metrics, and only then judge fallback.
- Escalation in `internal/commands/escalatecmd/escalate.go` already supports
  `independent`, `witness`, and `dispute`, rejects build source runs, and passes
  structured source artifacts into escalation prompts.
- Reports already render decision outcome, judge status, decision audit, build
  selection basis, provider-authored tests, and bundle/show next-step surfaces.

Recommended direction:

1. Ship routing, report, and next-step clarity now.
2. Ship bounded witness/audit and build verifier guidance soon.
3. Measure judge-family and telemetry ideas before changing policy.
4. Defer orchestration-heavy experiments.
5. Reject hidden synthesis, default debate loops, automatic repo mutation, and
   any confidence mechanism that acts like an uncalibrated gate.

## Ranking Summary

| Tier | Items | Product posture |
| --- | --- | --- |
| Ship Now | Routing copy, route advisor preview, selector confidence, stop-here recommendations, post-run recommendations, judge-only confidence copy, provider-authored test reminder, triage freshness copy, source-run bundle guidance | High value, low to medium implementation risk, improves trust immediately. |
| Ship Soon | Witness audit/falsification, build metric verifier guidance/linting, third-party judge advisory | Valuable, but needs clearer report taxonomy or small metadata work first. |
| Measure First | Local telemetry fields, accepted-finding feedback, `judge_policy`, judge-family rotation recipe | Useful strategic learning, but practical product benefit depends on evidence and low-friction UX. |
| Defer | Witness self-consistency, judge panels/juries, build escalation, batch schema/persistent orchestration | Expensive or ambiguous; likely bloat unless telemetry proves need. |
| Reject/Avoid | Hidden patch synthesis, default debate loops, normal three-worker work orders, auto-apply/merge/commit/push/PR, new public `adversarial` mode, per-finding fanout, large `report.md` parser, verbal-confidence gates, persona lenses as cross-family substitute | Conflicts with thin, artifact-led, user-owned Bakeoff. |

## Ship Now

### Fix Routing Copy

Recommendation: ship now.

Value assessment:

- Very high user value.
- Reduces confusion between `witness`, `dispute`, and `independent`.
- Helps users reach the right loop when they ask for "audit this report",
  "second opinion", "fight the findings", "fresh answer", or a named dispute.
- The roadmap's benefit is accurate and probably understated because routing
  mistakes can waste provider calls and produce the wrong evidence shape.

Code implementation details:

- Primary surface: `skills/bakeoff-run/SKILL.md`.
- Supporting docs: `commands/run.md`, `README.md`, and `docs/cli-reference.md`.
- No schema change is needed.
- Keep the existing mode meanings:
  `independent` means fresh third answer, `witness` means broad advisory audit
  of the current result, and `dispute` means focused contested points.
- Align wording with the existing escalation guidance in
  `skills/bakeoff-run/SKILL.md`, which already says broad sanity checking maps
  to `witness`, focused verification maps to `dispute`, and fresh answers map
  to `independent`.

Risk assessment:

- Complexity: XS-S.
- Risk: Low.
- Main risk is contradictory wording across skill, README, and CLI reference.
- Mitigation: update all routing surfaces together and keep examples parallel:
  "Audit current report", "Fresh third answer", and "Specific dispute packet".

Tests and validation:

- No Go schema tests required unless command output changes.
- Add or update skill/doc review scenarios for "audit this report", "second
  opinion on this report", "second opinion on the question", "fight the
  findings", and "is finding F-007 real".

### Add Route Advisor Preview

Recommendation: ship now.

Value assessment:

- Very high user value.
- Gives users a compact "why this loop" explanation before spending provider
  calls.
- Helps almost every workflow because task fit is one of the strongest
  evidence-backed themes: multi-agent work is useful only when the task shape
  supports it.
- The roadmap's benefit is accurate and understated.

Code implementation details:

- Primary surface: `skills/bakeoff-run/SKILL.md`, especially the task-fit and
  type-routing sections.
- Supporting surfaces: `commands/run.md`, `README.md`, and preview copy in the
  run workflow.
- No Go schema change is needed if this stays in the natural-language routing
  layer.
- The preview should classify routes with compact labels such as `normal`,
  `build-verifier`, `multi-lens`, `witness`, `dispute`, `independent`, or
  `single-agent advised`.
- Keep it short: one line by default, alternatives only when the artifacts or
  request are genuinely ambiguous.

Risk assessment:

- Complexity: S.
- Risk: Low.
- Main risk is preview prose bloat or giving equal weight to too many options.
- Mitigation: allow one primary route and a compact alternatives line only when
  helpful.

Tests and validation:

- Manual skill regression with deterministic, review, research, build,
  multi-lens, escalation, and weak-fit prompts.
- Confirm weak-fit warnings still allow `draft anyway`.

### Add Selector Confidence Section

Recommendation: ship now.

Value assessment:

- Very high user value.
- Makes gate-selected, metric-selected, judge-selected, unresolved, failed, and
  advisory outcomes visibly different.
- Protects users from treating LLM preference as equivalent to executable
  evidence.
- The roadmap's benefit is accurate and understated because this is central to
  trust in reports.

Code implementation details:

- Research/report renderer: `internal/report/report.go`.
- Build report renderer: `internal/commands/buildcmd/report.go`.
- Decision inputs already expose relevant fields such as `decision_kind`,
  `selection_basis`, `canonical_winner`, `judge_ran`, `judge_completed`,
  `stalled_at`, `judge_passes`, and caveats.
- Build reports already show `Selection basis`; extend that into a concise
  confidence explanation.
- Research reports already render `Outcome`, `Status`, and `Decision Audit`;
  add a new small section or one compact block under outcome.
- No schema change is required if the section is derived from `decision.json`.

Suggested taxonomy:

| Label | Meaning |
| --- | --- |
| `gate` | Required verifier gates selected or eliminated a candidate. |
| `metric` | Metric comparison selected the winner under configured thresholds. |
| `swapped judge` | A/B and B/A judge passes produced a stable decision. |
| `union/dedupe` | Gather/review merged provider findings without picking a winner. |
| `advisory witness` | Escalation audit adds evidence but does not replace source decision. |
| `focused dispute` | Escalation evaluates bounded disputed points. |
| `judge-only` | Selection depended on LLM preference without verifier or metric decision. |
| `unresolved` | Artifacts did not support a stable decision. |

Risk assessment:

- Complexity: S-M.
- Risk: Medium.
- Main risk is turning the section into fake numeric certainty.
- Mitigation: use categorical labels and plain caveats, not percentages or
  confidence scores.

Tests and validation:

- Update report fixture tests for gate winner, metric winner, judge winner,
  judge failure, tie/unresolved, gather union, witness advisory, and dispute.
- Verify build and research report copy stays short.

### Add Clean Stop-Here Recommendations

Recommendation: ship now.

Value assessment:

- Very high user value.
- Saves cost and reduces agentic theater when Bakeoff is not adding value.
- Helps simple deterministic tasks, formatter-only changes, and cases where
  artifacts already answer the question.
- The roadmap's benefit is accurate and probably understated.

Code implementation details:

- Primary surface: `skills/bakeoff-run/SKILL.md`.
- Existing skill guidance already supports weak-fit warnings and at most one
  artifact-aware continuation recommendation.
- No schema change is needed.
- The recommendation shape should be advisory, not blocking: say why stopping
  is reasonable and preserve the `draft anyway` escape when drafting is still
  possible.

Risk assessment:

- Complexity: S.
- Risk: Low-Medium.
- Main risk is overusing "stop" when the user explicitly wants a Bakeoff run.
- Mitigation: apply only when the task-fit rule or structured artifacts support
  it, and keep an explicit override path.

Tests and validation:

- Manual scenarios for deterministic command, formatter-only change, already
  sufficient report, weak build request, and explicit "draft anyway".

### Improve Post-Run Recommendations

Recommendation: ship now.

Value assessment:

- High user value.
- Helps users decide what to do after a run: stop, inspect, triage, rerun
  judge, escalate, gather, compare, review, analyze, or build.
- The roadmap's benefit is accurate.

Code implementation details:

- Primary surface: `skills/bakeoff-run/SKILL.md`.
- Supporting command surfaces: `internal/commands/showcmd/show.go`,
  `internal/commands/bundlecmd/bundle.go`, and report next-step copy.
- The skill already requires at most one artifact-aware continuation
  recommendation and says structured artifacts must outrank `report.md`.
- If recommendations become persisted or command-generated, use structured
  inputs from `decision.json`, `meta.json`, `manifest.json`,
  `triage/status.json`, `triage/final.json`, build diagnostics, and verifier
  status.

Risk assessment:

- Complexity: S-M.
- Risk: Medium.
- Main risk is bad advice from stale or prose-only signals.
- Mitigation: derive recommendations from structured artifacts, not rendered
  Markdown. Keep one primary recommendation and move alternatives under a small
  "Other options" section.

Tests and validation:

- Add command/report tests only if command output changes.
- Manual artifact scenarios: judge failed, review triage missing, build winner,
  unresolved compare, gather with triage, escalation advisory, and sufficient
  stop state.

### Add Judge-Only Degraded Confidence Copy

Recommendation: ship now.

Value assessment:

- High user value, especially for build users.
- Prevents users from treating judge-only selection as equal to verifier or
  metric evidence.
- The roadmap's benefit is accurate.

Code implementation details:

- Research report status copy: `internal/report/report.go`.
- Rerun behavior: `internal/commands/reruncmd/rerun.go`.
- Build report copy: `internal/commands/buildcmd/report.go`.
- Docs: `README.md`, `docs/cli-reference.md`, and `skills/bakeoff-run/SKILL.md`.
- The rerun command already limits `--judge-only` to research runs and rejects
  build judge-only reruns.
- Build reports already expose `selection_basis`; add copy when the basis is
  `judge` or when no gate/metric selected the winner.

Risk assessment:

- Complexity: S.
- Risk: Low-Medium.
- Main risk is over-discrediting useful judge decisions.
- Mitigation: say "weaker than verifier/metric evidence", not "useless".

Tests and validation:

- Report tests for build `selection_basis: "judge"`.
- Rerun/help tests if CLI copy changes.
- Ensure copy does not imply build judge-only rerun is supported.

### Add Provider-Authored Tests Reminder

Recommendation: ship now.

Value assessment:

- High value for build users.
- Reminds users that tests or probes authored by a candidate provider are
  supporting evidence, not selector truth.
- The roadmap's benefit is accurate.

Code implementation details:

- Build report renderer: `internal/commands/buildcmd/report.go`.
- Build capture/reporting already lists provider-authored tests and
  benchmarks/probes.
- Work-order docs already describe verifier behavior and protected paths.
- Add concise copy near provider-authored test listings or selector-confidence
  copy.
- No schema change is needed.

Risk assessment:

- Complexity: XS-S.
- Risk: Low.
- Main risk is repetitive report text.
- Mitigation: one short reminder in the build report, not repeated under every
  provider.

Tests and validation:

- Build report fixture for providers that add tests or benchmark/probe files.

### Add Triage Freshness First Copy

Recommendation: ship now.

Value assessment:

- High value for review users.
- Keeps users from escalating a stale, missing, failed, or dry-run triage result
  when `bakeoff triage --force` is cheaper and likely useful.
- The roadmap's benefit is accurate.

Code implementation details:

- Primary surface: `skills/bakeoff-run/SKILL.md`.
- Triage state logic: `internal/triage/state.go`.
- Possible command/report surfaces: `internal/commands/bundlecmd/bundle.go`,
  `internal/commands/showcmd/show.go`, and escalation dry-run copy.
- Existing skill guidance already says to recommend
  `bakeoff triage <run-id> --force` first when source artifacts show failed or
  missing triage.
- If enforced in code later, use structured triage state instead of parsing
  `report.md`.

Risk assessment:

- Complexity: S-M.
- Risk: Low-Medium.
- Main risk is delaying useful escalation after deterministic triage failure.
- Mitigation: advise triage retry first, but offer escalation as fallback and
  do not hard-block witness/dispute when the user insists.

Tests and validation:

- If code copy changes, add tests for missing triage, failed triage, stale
  triage, fresh triage, and user-forced escalation.

### Prefer Source-Run Bundle For Escalation Reading

Recommendation: ship now.

Value assessment:

- Medium-high user value.
- Helps users compare source report, triage, and escalation children without
  mutating the source run.
- Reinforces structured artifacts over hidden chat state.
- The roadmap's benefit is accurate.

Code implementation details:

- Existing surface: `internal/commands/bundlecmd/bundle.go`.
- Docs: `docs/cli-reference.md`, `README.md`, and `skills/bakeoff-run/SKILL.md`.
- No schema change is needed.
- Treat this as routing/docs work unless bundle output needs a small next-step
  improvement.

Risk assessment:

- Complexity: S.
- Risk: Low.
- Main risk is creating another report-like surface to maintain.
- Mitigation: keep bundle derived from existing artifacts and optional.

Tests and validation:

- Bundle tests only if output changes.
- Manual escalation scenario with source run plus one child escalation.

## Ship Soon

### Tighten `witness` Audit/Falsification

Recommendation: ship soon, after routing and selector-confidence copy.

Value assessment:

- High user value.
- Gives users a cheap, advisory audit of a source report, decision, judge
  passes, provider finals, and triage.
- Particularly useful for code-review reports where a user wants to challenge
  the current findings without asking for a fresh third answer.
- The roadmap's benefit is accurate.

Code implementation details:

- Escalation mode dispatch: `internal/commands/escalatecmd/escalate.go`.
- Current `runWitness` builds one witness prompt, runs the added provider once,
  validates with `workorder.ValidateEscalationWitnessResult`, and resolves an
  advisory witness decision.
- Source payload already includes `work_order_json`, `source_report_md`,
  `source_decision_json`, `source_meta_json`, provider finals, judge results,
  review context, and triage artifacts when present.
- Prompt builder and fixtures should define the tighter contract.
- Validation may need stricter per-item JSON objects for `material_errors`,
  `missed_material`, and `triage_concerns`.
- Report rendering in `internal/report/report.go` should label witness output
  advisory and show material errors/missed material without implying the source
  decision changed.

Risk assessment:

- Complexity: M.
- Risk: Medium.
- Main risks are over-negative audits, payload growth, context trimming, and
  the ambiguous `witness` name.
- Mitigation: keep targets bounded, require file/line or artifact proof where
  possible, cap code-review target counts, and render witness output as
  advisory-only.

Tests and validation:

- Prompt fixture tests for generic witness and code-review witness.
- Escalation tests for fresh, stale, missing, and failed triage artifacts.
- Validator tests for structured witness result objects if the schema tightens.
- Report tests for advisory witness output.

### Add Build Metric Verifier Guidance And Linting

Recommendation: ship soon.

Value assessment:

- High value for build and performance users.
- Reduces false winners from noisy metrics and weak metric verifier setup.
- The roadmap's benefit is accurate.

Code implementation details:

- Existing validation warnings: `internal/commands/validatecmd/validate.go`.
- Work-order docs: `docs/work-orders.md`.
- Draft/build docs: `docs/cli-reference.md`, `README.md`, and
  `skills/bakeoff-run/SKILL.md`.
- Current lint already warns when metric verifiers use repo-relative commands
  without protected paths and when `metric.min_runs` requires final JSON `n`.
- Add conservative generic warnings for missing or suspicious metric metadata:
  absent `noise_floor_percent`, absent `min_delta_percent`, `min_runs` too low
  for noisy metrics, or no protected paths for benchmark scripts and fixtures.
- Avoid language-specific rules until there is local evidence.

Risk assessment:

- Complexity: S-M.
- Risk: Medium.
- Main risk is false-positive lint across languages and benchmark styles.
- Mitigation: warnings only, conservative thresholds, and docs explaining how
  to suppress by making work-order intent explicit.

Tests and validation:

- Validate-command tests for metric verifier warnings.
- Work-order doc examples for stable metrics and inconclusive metrics.

### Add Third-Party Judge Advisory

Recommendation: ship soon as advisory only.

Value assessment:

- Medium-high value for judge-heavy and high-risk runs.
- Helps users notice when a non-contestant judge family could reduce
  same-family convergence risk.
- The roadmap's benefit is accurate but narrow.

Code implementation details:

- Provider catalog: `internal/provider/provider.go`.
- Doctor output: `internal/commands/doctorcmd/doctor.go`.
- Work-order validation or preview warnings: `internal/workorder/workorder.go`,
  `internal/commands/validatecmd/validate.go`, and `skills/bakeoff-run/SKILL.md`.
- Current `BackendSpec` has no family field. Add explicit family metadata
  before computing advisory messages.
- Keep generated work orders at exactly two providers.
- Do not auto-switch defaults yet.

Risk assessment:

- Complexity: M.
- Risk: Medium.
- Main risks are weak third backend availability, warning fatigue, and
  simplistic family classification.
- Mitigation: advisory only; explain when a third backend is ready and
  non-contestant, and avoid changing behavior until measured.

Tests and validation:

- Provider catalog tests for family metadata.
- Doctor/validate tests for Claude+Codex only, Claude+Codex+Gemini ready, and
  missing third backend cases.
- Prompt/preview scenario confirming generated work orders still have exactly
  two providers.

## Measure First

### Add Local Telemetry Fields

Recommendation: measure first.

Value assessment:

- Strategic value, delayed direct user value.
- Enables future defaults to be evidence-driven instead of taste-driven.
- The roadmap's benefit is accurate but indirect.

Code implementation details:

- Metadata writing: `internal/artifact/artifact.go`.
- Manifest generation: `internal/manifest/manifest.go`.
- Summary/list/show surfaces: `internal/summary`, `internal/commands/lscmd`,
  `internal/commands/showcmd`, and `internal/commands/bundlecmd`.
- Build diagnostics and decision data can supply selector path, gate/metric
  status, prompt trims, output caps, and provider failure classes.
- Prefer enriching `meta.json`, `decision.json`, `diagnostics.json`,
  `triage/status.json`, and `manifest.json` before adding a new
  `telemetry.json`.
- Keep fields local-only and content-light.

Suggested fields:

| Field family | Examples |
| --- | --- |
| Route | work-order type, facet id, task-fit warning, route classification. |
| Providers | backend, model string, provider family, family diversity. |
| Judge | judge backend, model string, judge-family relation to providers. |
| Selector | union, gate, metric, swapped judge, judge failed, tie, advisory witness, focused dispute. |
| Runtime | wall time, verifier time, prompt trim events, output-cap events, provider failure classes. |
| Review | triage state, stale inputs, classification counts, recommended action counts. |
| Escalation | source run, mode, added provider, advisory outcome, follow-up count. |

Risk assessment:

- Complexity: M-L.
- Risk: Medium.
- Main risks are privacy, artifact bloat, unstable field names, and accidental
  source-content capture.
- Mitigation: define a small schema first, store no source text or prompts in
  telemetry fields, and version additive changes.

Tests and validation:

- Artifact and manifest tests for presence and stability.
- `ls --json` tests only if fields are surfaced there.
- Dogfood matrix across gather, compare, analyze, review, build, and escalation.

### Add Accepted-Finding Feedback Capture

Recommendation: measure first.

Value assessment:

- Strategic value for code-review precision and false-positive measurement.
- Direct daily user value is uncertain unless the UI is extremely frictionless.
- The roadmap's benefit is accurate but adoption-uncertain.

Code implementation details:

- Likely new command or subcommand: for example `bakeoff triage feedback` or a
  small `feedback` command.
- Possible artifact: `triage/feedback.json` or run-level
  `feedback/human-feedback.json`.
- Related surfaces: `internal/triage`, `internal/manifest`, `internal/summary`,
  `internal/commands/showcmd`, and `internal/commands/bundlecmd`.
- Should reference stable finding IDs from structured triage artifacts.

Risk assessment:

- Complexity: M.
- Risk: Medium.
- Main risk is ceremony: users will skip annotations if the workflow feels like
  bookkeeping.
- Mitigation: support tiny, optional annotations and avoid blocking normal
  review or escalation.

Tests and validation:

- Command tests for marking accepted, rejected, fixed, deferred, and converted
  to tests.
- Manifest/bundle/show tests if feedback is displayed.

### Add `judge_policy` Or Draft-Time Judge Knob

Recommendation: measure first; do not add schema first.

Value assessment:

- Medium value for power users and high-risk runs.
- Lets users ask for a non-contestant judge family when available.
- Product value is not yet proven, especially because third backend quality and
  availability vary.

Code implementation details:

- Drafting code: `internal/workorder/draft.go`.
- Draft-build CLI: `internal/commands/draftbuildcmd/draft_build.go`.
- Work-order validation: `internal/workorder/workorder.go`.
- Provider catalog: `internal/provider/provider.go`.
- Docs: `docs/work-orders.md` and `docs/cli-reference.md`.
- Prefer a draft-time option first, such as "prefer different judge family",
  rather than adding a first-class work-order schema field.
- Only consider schema after provider family metadata and telemetry prove value.

Risk assessment:

- Complexity: M-L.
- Risk: Medium.
- Main risks are schema churn, brittle provider availability, and confusing
  users when the preferred judge is weaker or unavailable.
- Mitigation: sequence after advisory and telemetry; treat as preference, not
  hard requirement, unless explicitly requested.

Tests and validation:

- Draft tests for available third family, no third family, same-family judge,
  and user-specified judge override.
- Validate tests only if schema changes.

### Add Judge-Family Rotation Recipe

Recommendation: measure first as a dogfood recipe, not a product command.

Value assessment:

- Low-medium daily user value.
- Useful for maintainers measuring judge-convergence bias on durable artifacts.
- The roadmap's benefit is accurate for calibration, not routine usage.

Code implementation details:

- Existing rerun path: `internal/commands/reruncmd/rerun.go`.
- Current `--judge-only` only retries failed research judges using existing
  provider artifacts.
- A productized rotation command would need judge override, run lineage,
  alternate decision artifacts, report rendering, manifest entries, and
  anti-shopping language.
- A recipe can start with documented manual steps over completed runs.

Risk assessment:

- Complexity: S as recipe; M-L as CLI.
- Risk: Medium-High if productized.
- Main risk is judge shopping or confusing alternate judge output with a source
  decision mutation.
- Mitigation: keep source decision unchanged and label alternate judge results
  as audit/calibration artifacts.

Tests and validation:

- No tests for a docs-only recipe.
- If later productized: rerun, research judge, build judge, report, manifest,
  and lineage tests.

## Defer

### Witness Self-Consistency `n=3`

Recommendation: defer.

Value assessment:

- Unproven practical user value.
- Might reduce single-shot audit noise in high-risk witness runs.
- Does not solve same-family blind spots and increases cost.

Code implementation details:

- Current witness path is a single provider call in
  `internal/commands/escalatecmd/escalate.go`.
- Implementing `n=3` would require repeated witness calls, sample artifact
  storage, aggregation semantics, dedupe logic, disagreement reporting,
  validator changes, manifest changes, and report rendering.
- It should not become a generic judge feature without separate evidence.

Risk assessment:

- Complexity: L for witness only; XL if generalized.
- Risk: High.
- Main risks are cost, retry semantics, sample disagreement, false agreement,
  and difficult claim dedupe.
- Mitigation if revisited: run as dogfood experiment after the witness contract
  stabilizes and accepted/rejected witness feedback exists.

Tests and validation:

- Prompt, escalation, validator, aggregation, manifest, and report tests.
- Dogfood comparison of single witness versus `n=3` on the same review reports.

### Judge Panels Or Juries

Recommendation: defer.

Value assessment:

- Narrow value for high-risk calibration.
- Low daily value for routine Bakeoff use.
- Likely bloat unless telemetry shows it improves accepted outcomes enough to
  justify the cost.

Code implementation details:

- Would cut across runner orchestration, provider scheduling, judge prompt
  generation, artifact layout, decision aggregation, reports, manifests, exit
  codes, and tests.
- Current work-order and decision machinery assumes exactly two providers and a
  single selector path.
- A panel should remain an external benchmark or explicit experiment.

Risk assessment:

- Complexity: XL.
- Risk: High.
- Main risks are cost, latency, aggregation ambiguity, failure handling, and
  turning reports into noisy vote tallies.
- Mitigation: do not implement in core until telemetry shows clear value.

Tests and validation:

- Would require broad unit, integration, artifact, and fixture coverage.

### Build Escalation

Recommendation: defer.

Value assessment:

- Unclear user value.
- Users can inspect selected patches, rerun build, or draft a review/analyze
  follow-up instead.
- The current roadmap correctly keeps build escalation out of scope.

Code implementation details:

- `internal/commands/escalatecmd/escalate.go` rejects build source runs.
- Build runs have isolated workspaces, captured patches, verifier results,
  metrics, diagnostics, and selected patch handoff semantics.
- Escalating build artifacts would need new semantics: what the added provider
  sees, whether it can inspect patches, whether it can run verifiers, and how
  advice relates to canonical winner.

Risk assessment:

- Complexity: L.
- Risk: High.
- Main risks are confusing advisory review with build selection, source
  snapshot mismatch, and accidental patch synthesis pressure.
- Mitigation: keep explicit review/analyze follow-up as the supported path.

Tests and validation:

- Keep existing rejection coverage.
- Add docs tests only if docs clarify the recommended follow-up route.

### Batch Schema Or Persistent Multi-Run Orchestration

Recommendation: defer.

Value assessment:

- Low near-term user value.
- Conflicts with Bakeoff's explicit run IDs and artifact-led audit trail.
- Likely to turn Bakeoff into a workflow engine.

Code implementation details:

- Current work-order validation, ledgers, reports, summaries, and commands
  assume one normal work order at a time.
- Multi-lens and split workflows can remain separate normal runs plus explicit
  synthesis.
- A batch schema would touch work-order schema, validation, runner orchestration,
  ledgers, manifests, status reporting, cancellation, summaries, and docs.

Risk assessment:

- Complexity: XL.
- Risk: High.
- Main risks are state desync, hidden dependencies, cancellation complexity,
  and confusing `latest` semantics across concurrent children.
- Mitigation: keep explicit split/multi-lens recipes with separate run IDs.

Tests and validation:

- Not recommended now. If revisited, would require end-to-end orchestration
  tests, ledger tests, and cancellation/failure tests.

## Reject Or Avoid

### Hidden Patch Synthesis Or Cherry-Picking

Recommendation: reject.

Value assessment:

- Rejecting this has high user value because it preserves auditability.
- Users avoid unverified hybrid patches and hidden merge debt.

Code implementation details:

- Current build flow selects or hands off provider patches; it does not merge
  or synthesize them.
- Preserve the invariant in README, CLI docs, build report copy, and prompts.
- Any derived patch should be a new explicit build/review loop with fresh
  verification.

Risk assessment:

- Complexity if implemented: L.
- Risk if implemented: High.
- Main risks are unverified derived changes, attribution confusion, and stale
  verifier evidence.

### Default Debate Loops

Recommendation: reject for default use.

Value assessment:

- Rejecting this has high value because it avoids latency, cost, and muddier
  reports.
- The practical benefit is not proven for routine Bakeoff tasks.

Code implementation details:

- Keep normal runs pairwise: two providers and one selector.
- `internal/workorder/workorder.go` already enforces exactly two providers.
- Debate-style experiments should remain external or dogfood-only.

Risk assessment:

- Complexity if productized: XL.
- Risk if productized: High.
- Main risks are orchestration complexity, coordination overhead, and unclear
  stopping rules.

### Three Worker Providers In Normal Work Orders

Recommendation: avoid.

Value assessment:

- Avoiding this preserves the simple two-provider mental model.
- Third-provider value is better captured by explicit escalation.

Code implementation details:

- `validateProviders` in `internal/workorder/workorder.go` requires exactly two
  providers.
- Do not change the v1 work-order schema for routine runs.
- Add third providers through `bakeoff escalate` where source and child run
  artifacts stay separate.

Risk assessment:

- Complexity if implemented: XL.
- Risk if implemented: High.
- Main risks are schema churn, report redesign, selector redesign, and higher
  provider failure surface.

### Auto-Apply, Auto-Merge, Auto-Commit, Auto-Push, Or Auto-PR

Recommendation: reject.

Value assessment:

- Rejecting this has very high safety value.
- Protects human ownership of scope, review, merge, and deployment.

Code implementation details:

- Preserve Bakeoff as a handoff and evidence tool.
- Do not add hidden repo mutation to runs.
- If users ask for apply/commit/PR behavior, it should be a separate explicit
  user request outside the Bakeoff run.

Risk assessment:

- Complexity if implemented: M-L.
- Risk if implemented: High.
- Main risks are surprising repository mutation, broken audit boundary, and
  increased blast radius.

### New Public `adversarial` Escalation Mode

Recommendation: reject for now.

Value assessment:

- Low incremental value over a tightened `witness` mode.
- Avoids mode-name and schema bloat.

Code implementation details:

- Current escalation modes are `independent`, `witness`, and `dispute`.
- Improve `witness` copy and prompt contract first.
- Consider an `audit` alias only after users build enough experience to justify
  naming changes.

Risk assessment:

- Complexity if implemented: S-M.
- Risk: Medium.
- Main risks are duplicate mode semantics and confusing routing.

### Per-Finding Agent Fanout

Recommendation: defer/reject.

Value assessment:

- Unproven daily value.
- Likely to increase cost and review fatigue.
- Bounded witness targets capture much of the practical value.

Code implementation details:

- Would require per-finding target extraction, child run creation, concurrency,
  artifact lineage, report aggregation, and dedupe.
- Use structured triage artifacts for bounded witness/dispute instead.

Risk assessment:

- Complexity if implemented: L-XL.
- Risk: High.
- Main risks are cost, duplicated findings, noisy reports, and poor reviewer
  ergonomics.

### Large `report.md` Parser For Escalation Targets

Recommendation: avoid.

Value assessment:

- Avoiding this has medium value because it keeps structured artifacts
  canonical.
- Users benefit from fewer brittle target-selection failures.

Code implementation details:

- Prefer `decision.json`, `meta.json`, `manifest.json`, `triage/status.json`,
  `triage/final.json`, provider finals, and diagnostics.
- `report.md` may provide background for humans, but should not be the source
  of truth for automated target extraction.

Risk assessment:

- Complexity if implemented: M.
- Risk: High.
- Main risks are brittle parsing, stale rendered text, and inconsistent behavior
  across report versions.

### Verbal Confidence Gates

Recommendation: reject.

Value assessment:

- Rejecting this has high safety value.
- Prevents uncalibrated model confidence from becoming automatic action.

Code implementation details:

- Selector-confidence reporting should remain categorical and evidence-based.
- Do not gate apply, merge, or winner selection on single-model verbal
  confidence.
- If confidence is recorded, render it as advisory text only.

Risk assessment:

- Complexity if implemented: M.
- Risk: High.
- Main risks are fake precision, over-automation, and poor calibration.

### Provider-Persona Lenses As Cross-Family Substitute

Recommendation: avoid.

Value assessment:

- Medium value to clarify the distinction.
- Persona/lens prompts can focus attention, but they do not remove shared
  model-family blind spots.

Code implementation details:

- Keep multi-lens review as an explicit selective workflow when users ask for
  concrete lenses.
- Do not present same-family persona lenses as equivalent to cross-family
  provider diversity.
- Routing copy should say this plainly.

Risk assessment:

- Complexity if implemented as substitute: S-M.
- Risk: Medium.
- Main risks are misleading users and overclaiming independence.

## Bloat Watchlist

The ideas most likely to become bloat are:

- Judge panels or juries.
- Witness or judge self-consistency.
- Judge rotation as a first-class command.
- `judge_policy` as work-order schema before telemetry exists.
- Batch schema or persistent multi-run orchestration.
- Per-finding agent fanout.
- New public `adversarial` mode.
- Any confidence mechanism that pretends model certainty is a reliable gate.

These ideas are not all bad forever. They are bad defaults now because their
practical benefit is unproven and their implementation surface is wide.

## Sequencing

1. Ship routing copy, route advisor, selector-confidence section, stop-here
   recommendations, post-run recommendations, judge-only confidence copy,
   provider-authored test reminder, triage freshness copy, and source-bundle
   guidance.
2. Tighten `witness` and build metric linting after the confidence/report
   taxonomy is in place.
3. Add provider-family metadata before third-party judge advisory.
4. Add local telemetry before changing judge defaults, adding judge rotation
   commands, or experimenting with self-consistency.
5. Keep orchestration-heavy ideas outside the default product until local
   evidence shows they improve accepted outcomes without unacceptable cost,
   latency, confusion, or failure surface.

## Authoritative Next Implementation Plan

The next implementation slice should be small and user-visible:

1. Documentation and skill copy pass:
   - Update `skills/bakeoff-run/SKILL.md`.
   - Align `README.md`, `commands/run.md`, and `docs/cli-reference.md`.
   - Cover routing, route advisor, stop-here, triage freshness, and bundle
     guidance.

2. Report confidence pass:
   - Add selector-confidence rendering to `internal/report/report.go`.
   - Add build selector-confidence rendering to
     `internal/commands/buildcmd/report.go`.
   - Add judge-only degraded-confidence copy and provider-authored test
     reminder.

3. Focused test pass:
   - Add report fixture coverage for major selector paths.
   - Add build report fixture coverage for provider-authored tests and
     judge-selected builds.
   - Add skill/doc scenarios for routing language.

4. Then start bounded witness work:
   - Define the witness target contract.
   - Update prompts and validation.
   - Keep witness advisory-only.
   - Use structured artifacts and bounded targets.

This order maximizes immediate user value while keeping the architecture thin.
