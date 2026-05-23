# Adversarial Code Review Escalation Plan - 2026-05-23

## Summary

Do not add a fourth public escalation mode. Bakeoff already has the right
surface:

- `independent`: fresh third answer;
- `witness`: broad audit of the current result;
- `dispute`: narrow read on contested points.

The missing piece is product semantics: for code-review runs, `witness` should
explicitly mean "fight the report." The added provider should treat report
findings and triage decisions as hypotheses to falsify, not as conclusions to
summarize.

Recommended change: tighten `witness` for `facet.id: "code-review"` and add a
bounded target list so users can challenge the report without naming
individual findings.

## Current Behavior

Review runs are implemented as `type: "gather"` with
`facet.id: "code-review"`.

Current review shape:

```text
same scope -> two independent reviews -> one combined finding list -> automatic triage
```

The two providers enumerate cited findings. The gather judge unions and
deduplicates findings instead of selecting a winner. Triage then checks
candidate findings for actionability, citations, staleness, counterevidence,
and recommended action.

Escalation already supports:

| Mode | Current meaning | Calls |
| --- | --- | --- |
| `independent` | Run a fresh third provider, then synthesize it into the source result. | 1 provider + 1 judge |
| `witness` | Ask another provider whether the source report/decision is supported. | 1 provider |
| `dispute` | Build a packet from contested points and ask the added provider to resolve only those. | 1 provider |

For users who say "fight the claims in this report," `witness` is the best
match. `dispute` is too narrow because it only works when Bakeoff can extract
specific contested points. `independent` is useful, but it optimizes for missed
findings rather than falsifying existing findings.

## Recommendation

Keep the modes. Change the code-review `witness` contract.

User-facing mapping:

- "run another review" -> `independent`
- "challenge this report", "fight the findings", "adversarial review" ->
  `witness`
- "resolve the contested points", "check these evidence gaps" -> `dispute`

Internally, `witness` remains advisory. It should not mutate the source run,
overwrite triage, or produce a new canonical result.

## Why Not Add `adversarial` Mode?

A fourth mode would mostly duplicate `witness`.

It also creates avoidable product and implementation risk:

- users would have to learn the difference between `witness`, `dispute`, and
  `adversarial`;
- reports would need another decision kind or rendering path;
- the command router would have another branch;
- tests would need to prove a distinction that is mostly wording;
- the default escalation story would become harder to explain.

The evidence supports independent/fresh review and scoped falsification. It
does not require a debate loop or a new public mode.

## Proposed Changes

### 1. Strengthen The Code-Review Witness Prompt

Update `internal/prompt/fixtures/escalation-witness.txt` so that when the
source work order is a code-review run, the provider must treat the report as
untrusted candidate evidence.

Add rules like:

```text
For code-review source runs:
- Treat report findings and triage items as hypotheses to falsify.
- Challenge findings that are unsupported by their citations, stale, not
  introduced by the reviewed change, already fixed, out of facet, duplicate,
  severity-overstated, missing a repro, or contradicted by code/tests.
- Put challenged report findings in material_errors.
- Put likely real defects missed by the source report in missed_material.
- Put bad triage classifications, severities, confidence, or recommended
  actions in triage_concerns.
- Require file:line evidence for any actionable review claim.
- Keep all new or challenged findings advisory until a later triage pass.
```

This is the core product change. It makes `witness` adversarial without adding
another workflow.

### 2. Add A Bounded `review_claim_targets` Payload

Today the witness receives the source report, decision, provider finals, judge
results, review context, and triage artifacts. That is enough context, but it
does not explicitly say which claims should be attacked first.

Add a derived payload block for code-review witness runs:

```json
{
  "source": "triage.final.items",
  "truncated": false,
  "omitted_count": 0,
  "targets": [
    {
      "id": "F-001",
      "triage_id": "T-001",
      "source_finding": "Finding text.",
      "classification": "real_issue",
      "severity": "medium",
      "confidence": "high",
      "recommended_action": "fix_now",
      "supporting_evidence": ["path/to/file.go:123"],
      "counterevidence": []
    }
  ]
}
```

Target selection:

1. Prefer `triage/final.json` items when present and fresh.
2. Otherwise fall back to findings parsed from `report.md`.
3. Cap at 10-12 targets.
4. Prefer targets that are currently actionable, high severity, high
   confidence, `fix_now`, `needs_repro`, or `evidence_gap`.
5. Record `omitted_count` when the cap truncates the list.

This lets users fight the report without selecting individual claim IDs, while
keeping token cost and scope bounded.

### 3. Keep The Existing Witness Schema

Do not add a new schema in the first pass. The current witness schema already
has the right buckets:

- `material_errors`
- `missed_material`
- `triage_concerns`
- `out_of_scope`
- `recommended_next_checks`
- `rationale`

The prompt should ask the provider to use structured objects inside those
arrays. Suggested object shape for `material_errors`:

```json
{
  "source_finding_id": "F-001",
  "challenge_type": "unsupported_citation",
  "claim": "The report says ...",
  "counterevidence": ["path/to/file.go:123"],
  "effect": "questions_source",
  "confidence": "high",
  "rationale": "Why the report claim should not be treated as actionable."
}
```

This avoids validator churn and preserves backward compatibility.

### 4. Make Reports Label The Mode Clearly

Keep the report section as `## Witness Assessment`, but add a code-review
specific sentence when the source run is a code-review run:

```text
This is an adversarial audit of the source review report. It is advisory and
does not replace source triage.
```

If the report contains `material_errors`, `missed_material`, or
`triage_concerns`, the post-run summary should recommend inspection rather than
implying the source report was updated.

### 5. Keep Auto-Triage Conservative

Escalation currently supports auto-triage for code-review escalation outputs.
For adversarial witness outputs, treat triage as useful but not magical:

- do not mark witness findings actionable solely because the witness emitted
  them;
- keep the report wording advisory;
- if triage selects zero findings, report that clearly rather than hiding the
  audit result;
- do not mutate the source run's triage artifacts.

## Implementation Work Breakdown

1. Add code-review witness guidance to
   `internal/prompt/fixtures/escalation-witness.txt`.
2. Extend escalation payload rendering to support a new
   `<review_claim_targets>` block.
3. Build `review_claim_targets` only for `witness` mode when the source run is
   `type: "gather"` with `facet.id: "code-review"`.
4. Extract targets from `triage/final.json` when present; otherwise use
   report finding parsing.
5. Cap targets and record truncation metadata.
6. Update the witness prompt fixture tests.
7. Add escalation command tests proving code-review witness prompts contain
   `review_claim_targets`.
8. Add tests proving non-review witness prompts do not include the block.
9. Update slash-command/router docs so "fight/challenge/adversarial audit"
   maps to `witness`.
10. Update CLI docs to describe code-review witness as adversarial audit.

## Suggested Prompt Contract

The useful adversarial instruction is not "be harsh." It is a burden-of-proof
contract:

```text
Assume the source report may contain real findings, false positives, stale
comments, and missed defects. Your job is to test the report, not defend it.

For each target, ask:
1. Is the issue introduced or exposed by the reviewed change?
2. Do the cited files and lines semantically support the claim?
3. Is there counterevidence in code, tests, docs, or triage artifacts?
4. Is this out of the source facet or acceptance criteria?
5. Is the severity, confidence, and recommended action overstated?
6. Does the claim need repro before action?
7. Did the source report miss a more important adjacent defect?

Emit only evidence-backed challenges and missed material. If evidence is
insufficient, say so in recommended_next_checks instead of inventing a defect.
```

This is the part that makes the run adversarial. The model is not debating a
peer; it is attacking the report's proof obligations.

## Rejected Alternatives

### Add `--mode adversarial`

Rejected. It overlaps with `witness` and expands the public mode list without a
clear new runtime shape.

### Make `dispute` Fight Every Finding

Rejected for v1. `dispute` is valuable because it is narrow. Expanding it to
all report findings turns it into witness with extra packet machinery.

### Run A Debate Loop

Rejected. Back-and-forth debate increases latency, cost, and report complexity.
The evidence supports fresh/contextual review and scoped falsification more
than multi-round argument.

### Run An Agent Per Finding

Rejected. It is expensive, noisy, and likely to create review fatigue. A
bounded target list gives most of the benefit with much less machinery.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Witness output becomes too negative or speculative. | Require file:line evidence and put unsupported concerns in `recommended_next_checks`. |
| Users confuse advisory witness findings with source triage. | Label reports as advisory and do not mutate the source run. |
| Payload grows too large. | Cap targets and include `omitted_count`. |
| Prompt-only change misses important claims buried in the report. | Add `review_claim_targets` so the audit has explicit targets. |
| Validator rejects useful structured detail. | Keep arrays as `[]any` and document preferred object fields without requiring them yet. |

## Definition Of Done

- A user can ask Bakeoff to "fight this review report" and the plugin routes to
  `bakeoff escalate <run> --mode witness`.
- Code-review witness prompts include adversarial review instructions.
- Code-review witness prompts include bounded claim targets when available.
- Non-review witness behavior remains unchanged.
- Witness reports remain advisory and do not replace source decisions or source
  triage.
- Tests cover prompt rendering, target selection, truncation, and non-review
  absence.

## Expected Outcome

This gives Bakeoff the evidence-backed adversarial behavior users are likely to
want: a fresh provider attacks the report's claims and triage decisions. It
does so without adding a new public mode, changing the work-order schema, or
turning escalation into a large orchestration system.
