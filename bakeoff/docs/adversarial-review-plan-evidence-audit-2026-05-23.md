# Adversarial Review Plan Evidence Audit - 2026-05-23

## 1. Verdict: adopt with changes

Adopt the plan's direction, but not as written. The evidence supports tightening
`witness` into a falsification-oriented audit, and the current architecture
strongly supports reusing `witness` instead of adding a public `adversarial`
mode.

The main correction is scope: the generic "treat the source result as
hypotheses to test" behavior should apply to all non-build `witness` runs, not
only `facet.id == "code-review"`. The code-review-specific payload and checks
should remain gated to code-review gather runs because they depend on code
review triage artifacts, file:line evidence, and reviewed-change semantics.

## 2. What the plan gets right

- Reusing `witness` is the right product and code path. The current CLI has only
  `independent`, `witness`, and `dispute` in
  `internal/commands/escalatecmd/escalate.go:33-37`, with validation in
  `validateMode`. A fourth mode would add branching in command routing,
  decision resolution, report rendering, docs, and skill guidance without a new
  runtime shape.
- The evidence supports a small escalation surface. The code-review memo
  recommends a small default path plus explicit escalation for high-risk,
  surprising, incomplete, or challenged reviews, and explicitly names `witness`
  as the adversarial audit of report and triage.
- The plan correctly keeps `witness` advisory. Existing code and reports already
  enforce this shape: `decision.ResolveEscalationWitness` never sets a canonical
  winner for advisory witness decisions, and `renderWitnessAssessment` prints
  that the result does not select a new winner.
- The routing correction is real. `skills/bakeoff-run/SKILL.md:182-184`
  currently maps bare "second opinion" to `independent`, which is wrong for
  "second opinion on this report" or "audit this report".
- Building a bounded target list from triage is better than parsing
  `report.md`. The architecture already treats structured artifacts as
  canonical and warns the skill not to let `report.md` override structured
  signals.
- The plan correctly avoids reusing `triageGapItems` as-is. That helper only
  returns classifications `needs_repro` and `evidence_gap`, so it would skip
  high-priority `fix_now` findings that are exactly what an adversarial witness
  should try to falsify.
- The plan correctly identifies the payload whitelist in
  `renderEscalationPayloadBlocks`. Adding any new prompt block requires
  registering it there.

## 3. Required corrections before implementation

1. Generalize the witness rules, but keep code-review targets specialized.
   Replace `RenderReviewWitnessRulesBlock` with a more accurately named
   `RenderWitnessAuditRulesBlock`. It should emit a generic burden-of-proof
   block for every witness prompt, then append a code-review subsection only
   when the source run is a code-review gather run. Delete the DoD claim that
   non-review witness prompts are byte-for-byte unchanged, or narrow it to "no
   code-review target payload is emitted for non-review runs."

2. Make the facet visible to prompt rendering. The plan says to gate the helper
   on `facet.id == "code-review"` by mirroring
   `RenderTriageReviewContractRules`, but the witness payload built by
   `sourcePayload(src)` does not include a top-level `facet` key. Either add
   non-rendered keys such as `payload["facet"] = src.WorkOrder.Raw["facet"]`
   and `payload["source_mode"] = src.WorkOrder.Type` before prompt assembly, or
   change the prompt builder signature to receive the work order. Without this,
   a copied triage helper will always see an empty facet.

3. Gate `review_claim_targets` more tightly than facet id alone. Build targets
   only when `src.WorkOrder.Type == "gather"`,
   `triagepkg.FacetID(src.WorkOrder.Raw) == triagepkg.CodeReviewFacetID`,
   `triageState(src.TriageArtifacts) == "yes"`, and
   `src.TriageArtifacts["final"].items` is non-empty. Do not rank stale or
   failed triage output. Existing `readTriageArtifacts` can include `final`
   even when triage state is stale.

4. Fix the ranking vocabulary. `recommended_action` values are
   `fix_now`, `document`, `defer`, `ignore`, and `reproduce`; `needs_repro` is a
   classification, not an action. Rank actions as `fix_now` then `reproduce`;
   rank classifications as `real_issue`, `needs_repro`, then `evidence_gap`;
   then severity `high`, `medium`, `low`, `none`; then confidence `high`,
   `medium`, `low`.

5. Fix the target object shape. Triage items already have `id` and
   `source_finding_id`. Use `triage_id` for the triage item id and
   `source_finding_id` for `F-NNN`; do not overload `id` as `F-NNN`. Preserve
   `source_finding`, `classification`, `severity`, `confidence`,
   `recommended_action`, `supporting_evidence`, and `counterevidence`.

6. Remove the validator uncertainty. `ValidateEscalationWitnessResult` already
   requires those buckets to be arrays but does not constrain item shape, so
   objects are accepted. No validator relax is needed for v1.

7. Align structured witness items with report rendering. `genericItemLines`
   renders `claim`, `description`, `loser_note`, `evidence`, and
   `source_provider`; it does not render `counterevidence`, `counterexample`,
   `challenge_type`, or `source_finding_id`. Either require every structured
   witness item to include display-compatible `claim` and `evidence`, or add a
   small report rendering update for witness-specific fields.

8. Soften the counterexample rule. The evidence supports concrete evidence and
   fresh skeptical review. It does not prove every behavioral or security
   concern must have a runnable input. Use "counterexample, call trace, failing
   scenario, or static proof where applicable"; otherwise send it to
   `recommended_next_checks`.

9. Calibrate the citations. The plan's local evidence is enough without making
   new external papers load-bearing. Some cited papers and practitioner pages
   support separated critique broadly, but not the exact Bakeoff payload design.
   The plan should say the citations motivate the prompt shape, while the local
   architecture and prior evidence justify the implementation.

10. If CLI help changes, update the user docs too. The plan updates the
    `--mode` flag help in `NewCmdEscalate`; either avoid changing that help in
    v1 or also update `docs/cli-reference.md` so generated/help docs do not
    drift.

## 4. Scope recommendation: generalized witness/audit behavior

Use generalized witness audit behavior for all non-build escalation sources:

- All `witness` prompts should say the source report, decision, provider
  outputs, judge passes, and triage are hypotheses to test, not conclusions to
  defend.
- All `witness` prompts should require concrete citations in the evidence format
  available to the run, such as file:line for codebase scope or URLs for web
  scope.
- All `witness` prompts should push unsupported concerns into
  `recommended_next_checks` instead of actionable buckets.
- Code-review gather runs should get an additional code-review subsection for
  reviewed-change relevance, file:line proof obligations, severity/confidence
  challenges, and the missing-control pass.
- Only code-review gather runs with fresh triage should receive
  `<review_claim_targets>`.

Do not generalize by `risk` yet because the work-order schema has no first-class
risk field. Do not generalize by arbitrary `facet.id` values because facet ids
are user-defined slugs, not a stable taxonomy. The stable current axis is mode
plus the special `code-review` facet.

## 5. Simpler alternatives considered and why they do or don't suffice

- Prompt-only witness tightening: cheapest and likely gets most of the value.
  It should be the baseline even if target payload work slips. It does not solve
  attention ordering when triage has many items.
- Reuse existing `<triage_artifacts>` without `<review_claim_targets>`:
  viable for v1 if implementation time is tight. It avoids new payload code, but
  asks the model to discover priority from a potentially large JSON object and
  can accidentally focus stale triage unless the prompt is careful.
- Add `<review_claim_targets>`: still a reasonable minimal payload once the
  corrections above are made. It adds only a small derived, bounded, non-source
  artifact and avoids a report parser.
- Reuse `triageGapItems`: insufficient because it omits `fix_now` real issues.
- Expand `dispute` to fight every finding: wrong surface. `dispute` earns its
  place by being packet-driven and narrow.
- Add public `--mode adversarial`: not worth it. It duplicates `witness` and
  increases CLI, docs, report, and routing surface.
- Multi-round debate or per-finding fanout: too much orchestration for the
  evidence. Local evidence already warns that multi-agent failure is often
  coordination and specification overhead.

## 6. Implementation risk checklist tied to exact files/functions

- `internal/prompt/prompt.go:BuildEscalationWitnessPrompt` and
  `buildEscalationPrompt`: add witness audit rule replacement without affecting
  dispute, independent-gather union, or synthesis fixtures.
- `internal/prompt/prompt.go:renderEscalationPayloadBlocks`: register
  `review_claim_targets`, and keep non-rendered helper keys such as `facet` out
  of the block whitelist unless intentionally displayed.
- `internal/prompt/prompt.go:RenderTriageReviewContractRules`: do not copy this
  blindly; it assumes top-level `payload["facet"]`.
- `internal/prompt/fixtures/escalation-witness.txt`: add a placeholder for audit
  rules near the existing untrusted-data/advisory prose.
- `internal/commands/escalatecmd/escalate.go:runWitness`: attach non-rendered
  prompt metadata and optional `review_claim_targets` before
  `BuildEscalationWitnessPrompt`.
- `internal/commands/escalatecmd/escalate.go:sourcePayload`: keep it mode-free
  unless the implementation chooses to make `facet` a common non-rendered helper
  key for escalation prompts.
- `internal/commands/escalatecmd/escalate.go:buildDisputePacket`: reuse only the
  cap/omitted-count pattern, not the dispute semantics.
- `internal/commands/escalatecmd/escalate.go:triageGapItems`: do not reuse for
  witness target selection.
- `internal/commands/escalatecmd/escalate.go:readTriageArtifacts` and
  `triageState`: account for stale, failed, dry-run, or absent triage before
  deriving targets.
- `internal/commands/escalatecmd/escalate.go:loadSourceRun`: build escalation
  remains unsupported for `build` source runs; generalized witness behavior
  means all non-build source modes only.
- `internal/commands/escalatecmd/escalate.go:finalizeEscalationRun`: auto-triage
  remains advisory and should not mutate the source run.
- `internal/workorder/workorder.go:ValidateEscalationWitnessResult`: no v1
  validator change is required unless the plan starts requiring a strict item
  schema.
- `internal/workorder/workorder.go:validateTriageItem`: use the actual triage
  field names and enum values when deriving targets.
- `internal/report/report.go:renderWitnessAssessment` and `genericItemLines`:
  structured witness objects must either fit the current display fields or the
  renderer must learn the new fields.
- `skills/bakeoff-run/SKILL.md`: update route mapping so "audit this report",
  "second opinion on this report", "challenge/fight this report", and bare
  "dispute this report" prefer `witness`; "fresh answer" and "second opinion on
  the question" still prefer `independent`.

## 7. Revised recommendation/work breakdown

1. Rename the proposed helper to `RenderWitnessAuditRulesBlock(payload any)` and
   make it emit a generic witness audit block for all witness prompts.
2. Add a code-review subsection inside that helper when the payload metadata
   says `source_mode == "gather"` and `facet.id == "code-review"`.
3. Add `<witness_audit_rules></witness_audit_rules>` to
   `internal/prompt/fixtures/escalation-witness.txt` and replace it in
   `buildEscalationPrompt`.
4. In `runWitness`, add prompt-only metadata keys for `source_mode` and `facet`
   before calling `BuildEscalationWitnessPrompt`.
5. Implement `buildReviewClaimTargets(src sourceRun)` only for fresh
   code-review gather triage. Use actual triage enum values and field names,
   cap at 12, and record `selected` plus `omitted_count`.
6. Register `review_claim_targets` in `renderEscalationPayloadBlocks` and attach
   it in `runWitness` only when the target list is non-empty.
7. Adjust the suggested witness item shape to include display-compatible
   `claim`, `evidence`, and `confidence`; keep `counterevidence`,
   `counterexample`, `source_finding_id`, and `challenge_type` optional unless
   report rendering is updated.
8. Update `skills/bakeoff-run/SKILL.md` routing copy for report-audit phrases.
9. Add tests:
   - generic witness renders audit rules;
   - code-review witness renders generic plus code-review rules;
   - non-review witness does not render `review_claim_targets`;
   - code-review witness with fresh triage renders targets;
   - stale/missing triage renders no targets but prompt assembly still works;
   - generated structured witness items either render evidence in
     `report.RenderEscalation` or the prompt shape uses fields the renderer
     already displays.
10. Run focused tests for prompt, escalation, workorder validation, and report
    rendering before handing implementation off.
