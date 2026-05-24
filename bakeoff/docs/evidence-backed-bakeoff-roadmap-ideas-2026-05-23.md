# Evidence-Backed Bakeoff Roadmap Ideas - 2026-05-23

Status: brainstorm and execution-oriented roadmap for maintainers

Scope: no code changes. This document takes the local synthesis and adversarial
review plans as the evidence base, then proposes product directions, backlog
items, architecture options, UX routing improvements, telemetry, and a small
implementation sequence.

Primary inputs:

- `docs/agentic-loop-evidence-synthesis-2026-05-23.md`
- `docs/adversarial-review-plan-evidence-audit-2026-05-23.md`
- `docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md`
- `README.md`
- `skills/bakeoff-run/SKILL.md`
- `docs/work-orders.md`
- `docs/cli-reference.md`
- Current source cross-checks in `internal/provider/provider.go`,
  `internal/workorder/workorder.go`, `internal/commands/researchcmd/run.go`,
  `internal/commands/buildcmd/run.go`, `internal/commands/buildcmd/judge.go`,
  `internal/commands/escalatecmd/escalate.go`, and `internal/decision/decision.go`.

Guiding constraint: keep Bakeoff thin. The ideal loop is not "more agents by
default." It is a human-led, artifact-first loop: scope, independent attempts,
objective gates where possible, bias-aware judging where necessary, explicit
escalation when uncertainty remains, and human ownership before apply, merge, or
deploy.

## 1. Executive Recommendation

Bakeoff should pursue these product directions next:

1. **Make escalation feel like the normal safety valve, not an expert-only
   escape hatch.** Keep normal work orders at exactly two providers, but make
   `witness`, `dispute`, and `independent` easier to choose from source
   artifacts. The strongest immediate work is tightening `witness` into an
   evidence-seeking audit of the source report, especially for code-review runs.

2. **Prefer stronger selectors before bigger orchestration.** For build, keep
   gate and metric verifiers ahead of LLM judgment. For compare/analyze, keep
   position-swapped judging. For judge-only or judge-heavy decisions, add small
   warnings, previews, and later opt-in judge-diversity knobs rather than adding
   a permanent panel by default.

3. **Treat provider and judge diversity as a measured policy, not a slogan.**
   The evidence supports cross-family review for high-risk work and flags
   same-family judge convergence as a real concern. The practical next step is
   a third-party judge preference or lint when a third backend is ready, plus
   telemetry comparing outcomes before changing the generated default.

4. **Guide users into the cheapest adequate loop.** Strengthen task-fit and
   post-run copy so users can see when to use a single agent, normal Bakeoff,
   build mode, multi-lens review, witness/audit, dispute, or independent
   escalation. Do this with previews and report recommendations, not a new
   orchestration layer.

5. **Build a local evidence trail for future policy changes.** Record enough
   run metadata to answer whether third-party judges, rotating judges,
   self-consistency, and multi-lens review actually improve accepted findings,
   decision stability, cost, and developer triage time.

## 2. Evidence-Backed Idea Backlog

| Idea | Evidence basis | Affected CLI/plugin surfaces | Expected benefit | Cost/risk | Priority |
| --- | --- | --- | --- | --- | --- |
| Tighten `witness` into an audit/falsification contract for all non-build runs, with code-review-specific target payloads when fresh triage exists. | The synthesis and both adversarial plans agree `witness` is the right existing surface; `dispute` is too narrow and `independent` optimizes for fresh recall. Source confirms `runWitness` already keeps output advisory. | `bakeoff escalate --mode witness`, `/bakeoff:escalate`, `skills/bakeoff-run/SKILL.md`, `internal/prompt`, `internal/commands/escalatecmd`, `internal/report`. | Users get a cheap way to challenge reports without changing source decisions or adding a fourth mode. | Prompt over-negativity; payload growth. Mitigate with evidence requirements, cap-12 targets, and advisory labeling. | Now |
| Fix routing copy for "audit this report", "second opinion on this report", "fight the findings", and bare "dispute this report". | `skills/bakeoff-run/SKILL.md` currently maps broad "second opinion" to `independent`; the audit plan says report-focused language should prefer `witness`. | `skills/bakeoff-run/SKILL.md`, `README.md`, `docs/cli-reference.md`. | Lower mode confusion; users reach the right loop with fewer clarifying turns. | Mostly copy risk; avoid overfitting phrases. | Now |
| Add a "selector confidence" section to reports. | Build evidence says verifiers outrank judges; judge evidence says swapped agreement is useful but incomplete. Current decisions already expose `selection_basis`, `judge_completed`, `stalled_at`, and caveats. | `report.md`, `decision.json`, `internal/report`, `internal/commands/buildcmd/report.go`. | Makes gate-selected, metric-selected, judge-selected, unresolved, and advisory outcomes visibly different. | Could clutter reports; keep to 3-5 lines. | Now |
| Add preview/report copy for judge-only degraded confidence when no verifier or metric evidence decided the build. | Competitive-build evidence says judge-only selection is weaker; current build already records `selection_basis: "judge"`. | Build reports, `/bakeoff:run` summary, `bakeoff build` stdout. | Prevents users treating LLM preference as equivalent to executed evidence. | Copy only; must not imply judge decisions are useless. | Now |
| Add a third-party judge preference advisory when a third backend is available. | Position swaps handle order bias, not family convergence. The synthesis marks judge convergence as a gap worth measuring. `provider.ResolveDefaultPair` already knows available backends; `workorder.validateJudge` only requires backend+model differs from each provider. | `/bakeoff:doctor`, `/bakeoff:run` preview, generated work-order drafting, `internal/provider/provider.go`, `internal/workorder`. | Users see when the judge shares family with a contestant and when a non-contestant judge is possible. | Different judges may be weaker or less available; do not hard-switch default until measured. | Now as advisory; Next as policy |
| Add an opt-in `judge_policy` or draft-time knob for "prefer non-contestant judge family". | Same as above, plus user request to consider third-party judges when three providers are available. | Work-order generation, possibly `bakeoff draft-build`, `docs/work-orders.md`, `docs/cli-reference.md`. | Lets high-risk runs choose Claude+Codex workers with Gemini judge, or Claude+Gemini workers with Codex judge, without adding a third worker. | Schema churn if first-class; prefer preview/draft policy before schema. | Next |
| Add local judge-family rotation dogfood command or recipe. | The synthesis names rotating judge family as the way to measure convergence. Current `bakeoff rerun --judge-only` retries failed research judges only, not successful alternate-judge experiments. | New recipe first; later `bakeoff rerun --judge-only --judge BACKEND[:MODEL]` if warranted. | Lets maintainers rejudge durable provider artifacts with another family and compare decisions. | Could look like cherry-picking a judge; must present as audit/measurement, not replacement. | Later |
| Add optional witness self-consistency at `n=3` for high-risk audits. Speculative. | The v2 plan lists witness self-consistency as field-supported but outside v1; synthesis says self-review is not independent but voting can reduce single-shot critique noise. | `bakeoff escalate --mode witness --self-consistency 3` or hidden dogfood recipe; report dedupe. | Potentially reduces false-positive churn in adversarial witness outputs. | Dedupe complexity, cost, same-family blind spots remain. | Later experiment |
| Add a local "route advisor" block to `/bakeoff:run` previews. | Existing task-fit rules already warn weak fits; synthesis says multi-agent benefit is task-shaped. | `skills/bakeoff-run/SKILL.md`, `/bakeoff:run` preview templates. | Users learn why the chosen loop is normal Bakeoff, build, multi-lens, escalation, or single-agent. | Too much prose in previews. Keep one line plus alternatives only when ambiguous. | Now |
| Improve post-run recommendations with explicit loop choices. | Current skill allows one artifact-aware continuation recommendation and can recommend triage, judge-only rerun, escalation, analyze, review, or build. | `skills/bakeoff-run/SKILL.md`, `bakeoff show`, `bakeoff bundle`. | Moves users toward the next evidence-backed step without auto-chaining. | Recommendation fatigue; keep at most one primary recommendation. | Now |
| Add "triage freshness first" escalation gating copy. | Skill already recommends `bakeoff triage <run-id> --force` before escalation when triage failed or is missing; evidence says AI findings remain candidates until verified. | `/bakeoff:run` post-run summary, `/bakeoff:inspect`, `bakeoff bundle`. | Keeps users from escalating stale review artifacts when a cheap triage retry is better. | May delay useful escalation after deterministic triage failure; offer fallback. | Now |
| Add telemetry fields for selector path, judge family relation, provider family diversity, output caps, prompt trims, triage state, and escalation follow-ups. | Synthesis calls out missing production false-positive, cost, latency, and judge-convergence measurements. Current ledgers already have `decision.json`, `meta.json`, `triage`, diagnostics, and timing artifacts. | `meta.json`, `decision.json`, `diagnostics.json`, optional `telemetry.json`, `bakeoff ls --json`. | Future defaults become evidence-driven instead of taste-driven. | Privacy and local data volume; keep local-only and avoid source-content upload. | Now |
| Add accepted-finding feedback capture as a local optional artifact. | Code-review evidence lacks production false-positive rates; triage classifies candidate findings but humans decide what was real. | New local command or `triage` annotation file, for example `runs/<id>/triage/human-feedback.json`. | Measures precision and developer usefulness. | Users may not annotate; avoid making workflow heavier. | Later |
| Add build metric verifier guidance and linting. | Build evidence says metrics can be decisive but noisy; work orders support `min_delta_percent`, `noise_floor_percent`, and `min_runs`. | `docs/work-orders.md`, `bakeoff validate`, `bakeoff draft-build` docs. | Better performance bakeoffs with fewer false winners. | Language/tool-specific guidance can go stale; start with generic lint and docs. | Next |
| Add "provider-authored tests are evidence, not selector" report reminder. | README and build prompts already say shared verifiers decide; evidence supports fixed verifiers over provider-authored checks. | Build report, worker prompts, README. | Reduces over-trust in a candidate's self-added tests. | Copy repetition. | Now |
| Add source-run bundle as the preferred escalation reader. | `bakeoff bundle` already reconstructs source plus escalation children; synthesis favors structured artifacts over hidden chat state. | `bakeoff bundle`, `/bakeoff:inspect`, docs. | Easier to compare source report, triage, and escalation children without mutating anything. | Bundle can become another report to maintain; keep derived and optional. | Next |
| Add clean "stop here" recommendations when Bakeoff is not adding value. | Evidence says more agents are not automatically better; skill already has weak-fit warnings. | `/bakeoff:run` task-fit copy and post-run summary. | Saves cost and prevents agentic theater. | Users may feel blocked; provide `draft anyway` escape. | Now |
| Reject hidden patch synthesis between build candidates. | Synthesis marks patch synthesis/cherry-picking as unverified and risky; README says Bakeoff stops at handoff. | N/A except docs and copy. | Protects auditability and avoids derived unverified patches. | Users may want synthesis; direct them to an explicit follow-up build/review. | Reject |
| Reject default multi-round debate loops. | V2 plan rejects debate loops for cost/latency and inconsistent gains; synthesis says coordination overhead is a recurring failure mode. | N/A except docs and routing. | Keeps thin architecture intact. | None; can revisit with local benchmark. | Reject for default |

## 3. Judge/Provider Architecture Ideas

### Third-Party Judge When A Third Provider Is Available

Recommendation: **pursue as an advisory first, then as an opt-in or selective
default after measurement.**

The evidence says LLM judges are useful but biased. Bakeoff already handles
position bias for compare/analyze and build judge fallback by running A/B and
B/A passes. That does not address judge-family convergence. A Claude judge over
Claude+Codex outputs can still share style, priors, or blind spots with the
Claude provider, even when the judge model differs. Current validation only
requires the judge backend+model pair to differ from each provider backend+model
pair, so a same-backend judge is allowed.

The most Bakeoff-compatible idea is not "three providers in the work order."
It is: when at least three backend families are ready, prefer or suggest a
non-contestant judge family for judge-heavy runs. Example: Claude+Codex workers
with Gemini judge, or Claude+Gemini workers with Codex judge. This keeps the
normal shape at two workers plus one selector.

When warranted:

- High-risk compare/analyze decisions where the judge determines the answer.
- Build runs where gates pass for both providers, metrics are inconclusive, and
  the LLM judge becomes the selector.
- Code-review synthesis or escalation reports where family convergence would be
  materially concerning.
- Internal judge-convergence dogfood runs.

When not warranted:

- Gather/code-review union where the judge is deduping rather than picking a
  winner, unless local data shows a family-specific dedupe problem.
- Build decisions selected by gates or conclusive metrics.
- Machines where the third backend is missing, unauthenticated, or materially
  less capable for the task.

Implementation posture:

- Now: show a preview warning or `doctor` advisory when the generated judge
  shares a backend family with a provider and another ready backend could judge.
- Next: add a draft-time policy such as "prefer different judge family" without
  changing the work-order provider count.
- Later: change generated defaults only after telemetry shows better decision
  stability, lower dispute rate, or better accepted outcomes.

### Rotating Judge Family

Recommendation: **use for measurement and high-risk reruns, not as the default
selector.**

Rotating judge family means reusing durable provider artifacts and asking a
different judge backend to decide the same compare/analyze or build judge case.
It directly measures the unresolved gap identified by the synthesis: production
systems have not proven a general solution for judge-convergence bias.

When warranted:

- A judge-selected decision is surprising or merge-critical.
- A source run exits unresolved because swapped passes disagree.
- Maintainers are running a calibration benchmark over historical runs.

Risks:

- Users may shop for a favorable judge.
- Successful rejudging could be mistaken for mutating the source decision.

Thin version:

- Keep rotated judging as a new run or explicit audit artifact.
- Preserve the source decision unchanged.
- Render "alternate judge result" as advisory unless the user requested a new
  run with that judge before launch.

### Judge Jury Or Panel

Recommendation: **defer for normal product use; consider only as a benchmark or
high-risk opt-in.**

The evidence base mentions juries as a way to reduce single-judge bias, and the
review docs use "cheap jury" language for union/dedupe plus triage. But a
standing judge panel is a heavier orchestration layer: more calls, more
aggregation rules, more failure cases, and more report surface. It fights the
thin architecture unless the task is high-stakes enough to justify it.

When warranted:

- Security-sensitive or migration-critical decisions where gates cannot encode
  the real risk.
- Internal benchmarking of judge policies.
- A future enterprise profile where cost/latency is explicitly accepted.

When not warranted:

- Default `/bakeoff:run`.
- Routine review or research.
- Any build where gates or metrics already selected a winner.

Thin version:

- Offer a separate "judge audit" or "jury experiment" recipe over completed
  artifacts.
- Report panel disagreement and abstain on weak agreement.
- Never auto-merge or auto-apply based on a panel.

### Self-Consistency

Recommendation: **speculative but worth a bounded experiment for witness and
judge audit, not for final autonomous action.**

Self-consistency runs the same role multiple times and keeps material that
survives agreement. It can reduce single-shot variance, especially in critique,
but it does not create true independence when all samples come from the same
model family. It should not substitute for verifiers or cross-family evidence.

When warranted:

- `witness` audit on high-risk code-review reports where false positives are
  costly.
- Alternate judge audit where a single judge pass is too brittle.
- Internal calibration to compare "third-family single judge" vs "same-family
  self-consistency n=3".

When not warranted:

- Normal default runs.
- Build selection with meaningful executable gates.
- Any path that would use verbal confidence as an automatic threshold.

Thin version:

- Cap at `n=3`.
- Require duplicate detection on claim plus evidence, not just similar wording.
- Render vote counts and disagreements as evidence, not as an automatic gate.

## 4. Loop UX Ideas

Goal: guide users into the smallest loop that produces useful evidence.

| User intent / artifact state | Recommended loop | UX idea | Why it stays thin |
| --- | --- | --- | --- |
| Simple deterministic task, formatter-only change, or one obvious command can answer it. | Single-agent or direct command, not Bakeoff. | Keep the existing weak-fit warning, but add a one-line reason and `draft anyway` escape. | No new runtime. |
| Research, compare, or analyze question where independent answers may disagree. | Normal two-provider Bakeoff. | Preview says "two independent providers, one mode-specific selector." | Existing `bakeoff research`. |
| Code review of a diff, branch, PR, or local change. | Review as `gather` plus `facet.id: "code-review"` with auto-triage. | Preview calls out scope, base/diff context, and triage state. | Existing facet and triage. |
| Implementation where verifier evidence can decide. | Build mode. | Require acceptance criteria, edit scope, and gate verifier; show when provider-authored tests are non-decisive. | Existing `bakeoff build` and `draft-build`. |
| Explicit 2-3 separate review lenses. | Multi-lens review. | Use the existing explicit trigger path; summary states each lens is a normal run and synthesis is a separate follow-up. | Separate normal work orders, no batch schema. |
| Broad "is this report sound?", "audit this report", "second opinion on this report", "fight the findings". | `witness`. | Route to `bakeoff escalate <run> --mode witness --dry-run`, with advisory-only copy. | Existing escalation mode. |
| Specific finding, tie, unknown, or contested point. | `dispute`. | Route to `dispute` only when artifacts expose focused points or named finding ids. | Existing bounded packet. |
| Fresh third answer after an unresolved or incomplete source run. | `independent`. | Route "second opinion on the question" or "add Gemini to this completed run" to independent escalation. | Separate escalation run; no three-provider work order. |
| Source review triage missing, failed, stale, or dry-run only. | Triage retry first. | Recommend `bakeoff triage <run-id> --force` before escalation, with escalation as fallback. | Existing triage command. |
| Judge failed after both providers completed. | Judge-only rerun for research. | Recommend `bakeoff rerun <run-id> --judge-only` before a full rerun. | Existing rerun surface. |

Small UX additions:

- Add a "Why this loop" line in the preview: `normal`, `build-verifier`,
  `multi-lens`, `witness`, `dispute`, `independent`, or `single-agent advised`.
- Use parallel noun phrases when offering choices: "Audit current report",
  "Fresh third answer", "Specific dispute packet".
- Keep at most one primary post-run recommendation, followed by compact
  alternatives only when the artifacts clearly support them.
- In reports, label selector strength: `gate`, `metric`, `swapped judge`,
  `union/dedupe`, `advisory witness`, `focused dispute`, `unresolved`.
- Avoid inventing a new top-level "agentic loop" command. The existing commands
  are enough if the routing copy is sharp.

## 5. Verification/Telemetry Ideas

Future options should be chosen from run evidence, not vibes. Keep telemetry
local, artifact-based, and content-light.

Measure per run:

- Work-order type, facet id, route classification, whether task-fit warned, and
  whether user overrode the warning.
- Provider backends, model strings, provider family diversity, judge backend,
  judge model, and judge-family relation to providers.
- Available backend set from `doctor` at draft time, including whether a
  third-party judge was possible.
- Selector path: union, gate, metric, swapped judge, provider union only,
  judge failed, tie, witness advisory, dispute advisory, independent synthesis.
- Exit code, `decision_kind`, `selection_basis`, `stalled_at`,
  `canonical_winner`, caveat count, judge pass agreement/disagreement.
- Wall time per phase, provider failure class, judge failure class, verifier
  runtime, prompt trim events, output-cap events, and retained/observed bytes.
- Build verifier strength: number of gates, baseline expectation,
  protected-path count, metric thresholds, metric noise metadata, and whether
  provider-authored tests/probes were present.
- Review triage state and counts by `recommended_action`, `classification`,
  severity, confidence, citation-check failures, stale findings, and source
  finding filter results.
- Escalation follow-ups per source run: mode, added provider, advisory outcome,
  whether it questioned or supported the source, and whether it led to triage or
  another normal run.
- Optional human feedback: which findings were accepted, rejected, fixed,
  deferred, or converted into tests; which selected build patch was applied; and
  post-merge defect/regression links when users provide them.

Use telemetry to answer:

- Do third-party judges reduce swapped-judge disagreement, post-run disputes, or
  human reversals compared with same-family judges?
- Does rotating judge family change outcomes on the same artifacts often enough
  to justify a product knob?
- Does witness self-consistency reduce false-positive witness findings without
  missing material errors?
- Which task-fit warnings are overridden, and do overridden runs produce useful
  artifacts?
- When do multi-lens reviews find additional accepted issues versus duplicating
  normal review?
- Which verifier patterns produce stable build winners, and which metric
  thresholds are too noisy?
- Does cross-model review improve accepted finding recall enough to justify
  latency on routine diffs, or only on high-risk diffs?

Implementation shape:

- Prefer enriching existing `meta.json`, `decision.json`, `diagnostics.json`,
  `triage/status.json`, and `manifest.json` before adding a new file.
- If a new file is useful, make it local-only, for example
  `runs/<run-id>/telemetry.json`, with no source text, no prompts, and no
  automatic upload.
- Add an export/report command only after the artifact schema settles.

## 6. Things To Avoid Or Defer

| Feature | Decision | Why |
| --- | --- | --- |
| Three worker providers in normal work orders | Avoid | Current schema, docs, and evidence all support exactly two providers plus one selector. Add a third provider through explicit escalation. |
| Hidden auto-apply, auto-merge, auto-commit, auto-push, or auto-PR | Reject | It erases Bakeoff's auditable handoff boundary and violates the user-owned merge/deploy loop. |
| Hidden patch synthesis or cherry-picking between build candidates | Reject | The synthesis marks this as unverified and risky. A derived patch needs its own explicit build/review loop. |
| New public `adversarial` escalation mode | Reject for now | It duplicates `witness` without a new runtime shape. Improve `witness` copy and prompt contract first. |
| Default judge panels | Defer | Useful for calibration or high-risk opt-in, but too expensive and orchestration-heavy for the default path. |
| Default self-consistency on every judge or witness | Defer | Speculative, costs more, and does not solve family-level blind spots. |
| Per-finding agent fanout | Defer/reject | Too much cost and review fatigue. Bounded witness targets capture most of the value. |
| Large report parsers for deriving escalation targets from `report.md` | Avoid | Structured artifacts are canonical; parsing rendered markdown adds brittle surface. |
| Verbal confidence thresholds as automatic gates | Reject | Single-model verbal confidence is not calibrated enough for automatic action. |
| Provider-persona lenses as a substitute for cross-family diversity | Avoid | Same-family lenses can focus attention, but do not remove shared blind spots. |
| Build escalation | Defer | Current docs explicitly do not support build escalation. Prefer inspecting selected patch, rerunning build, or drafting a review/analysis follow-up. |
| Batch schema or persistent multi-run orchestration layer | Defer | Existing split and multi-lens flows use separate normal work orders and explicit run ids, which preserves auditability. |

## 7. Suggested Next Implementation Sequence

1. **Ship witness/audit tightening.**
   - Surfaces: `internal/prompt`, `internal/commands/escalatecmd`, `internal/report`, `skills/bakeoff-run/SKILL.md`.
   - Dependencies: fresh code-review triage target selection, prompt block whitelist, report rendering fields.
   - Tests/dogfood: prompt tests for generic witness and code-review witness; escalation tests for fresh/stale/missing triage; dogfood on `runs/2026-05-23-0313` or a similar code-review run with a Gemini witness.

2. **Clean up loop routing copy.**
   - Surfaces: `skills/bakeoff-run/SKILL.md`, `README.md`, `docs/cli-reference.md`.
   - Dependencies: witness wording from step 1.
   - Tests/dogfood: manual prompt scenarios for "audit this report", "second opinion on this report", "second opinion on the question", "is F-007 real", and "add Gemini to this completed run".

3. **Add selector-confidence reporting.**
   - Surfaces: research reports, build reports, escalation reports, `/bakeoff:run` summaries.
   - Dependencies: none beyond existing `decision.json`.
   - Tests/dogfood: fixture reports for gate winner, metric winner, judge winner, judge disagreement, structured union, witness advisory, and dispute advisory.

4. **Add local telemetry fields needed for judge policy experiments.**
   - Surfaces: `meta.json`, `decision.json`, build diagnostics, triage status, optional local `telemetry.json`.
   - Dependencies: define stable names for provider family, judge family relation, selector path, and escalation mode.
   - Tests/dogfood: run a small matrix of compare/analyze/build/review tasks and verify telemetry can be summarized without reading prompts or source text.

5. **Introduce third-party judge advisory.**
   - Surfaces: `bakeoff doctor --json`, `/bakeoff:run` preview, possibly `bakeoff validate` warnings.
   - Dependencies: telemetry fields from step 4; provider family metadata in the catalog.
   - Tests/dogfood: scenarios with Claude+Codex only, Claude+Codex+Gemini ready, and multiple optional peers ready. Verify generated work orders still have exactly two providers.

6. **Run a judge-family rotation benchmark before changing defaults.**
   - Surfaces: dogfood script or documented recipe first; only later a CLI flag if the recipe proves useful.
   - Dependencies: telemetry from steps 4 and 5.
   - Tests/dogfood: rejudge a fixed set of completed runs with another ready backend and compare outcome stability, caveats, and human acceptance.

7. **Experiment with witness self-consistency only if witness/audit creates too much noise.**
   - Surfaces: escalation dogfood branch or opt-in flag.
   - Dependencies: claim dedupe design and accepted/rejected witness feedback.
   - Tests/dogfood: compare single witness vs `n=3` on the same review reports; measure material errors found, false positives, latency, and user triage time.

8. **Only then consider default policy changes.**
   - Candidate changes: generated drafts prefer a non-contestant judge when a third family is ready; high-risk review copy recommends third-family witness; build reports more strongly discourage judge-only selection.
   - Ship criteria: local telemetry shows improvement in decision stability or accepted outcomes without unacceptable provider failure, latency, or user confusion.

