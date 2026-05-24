# Bakeoff Roadmap Audit — Value/Evidence Side - 2026-05-24

Auditor scope: value and evidence traceability only. Implementation
complexity is being reviewed by a parallel agent and is intentionally
out of scope here.

Sources cited by file and section:
- Synthesis: `docs/agentic-loop-evidence-synthesis-2026-05-23.md` (referred to as **SYN**)
- Roadmap ideas: `docs/evidence-backed-bakeoff-roadmap-ideas-2026-05-23.md` (referred to as **RM**)
- Assessment under audit: `docs/bakeoff-roadmap-value-risk-implementation-assessment-2026-05-24.md` (referred to as **ASSESS**)

---

## Summary Table

| Item | ASSESS value rating | My value rating | Evidence strength | Agree? |
| --- | --- | --- | --- | --- |
| Fix routing copy | Very high | Very high | Strong | Agree |
| Add route advisor preview | Very high | High | Medium | Mostly agree (slight over-rating) |
| Add selector confidence section | Very high | Very high | Strong | Agree |
| Add stop-here recommendations | Very high | High | Medium | Mostly agree (slight over-rating) |
| Improve post-run recommendations | High | High | Medium | Agree |
| Judge-only degraded confidence copy | High | High | Strong | Agree |
| Provider-authored tests reminder | High | High | Strong | Agree |
| Triage freshness first copy | High | Medium-high | Medium | Agree |
| Source-run bundle for escalation | Medium-high | Medium | Weak-Medium | Slight over-rating |
| **Tighten `witness` audit/falsification** | High (Ship **Soon**) | **Very high (Ship Now)** | **Strong** | **Disagree — under-bucketed** |
| Build metric verifier guidance/linting | High (Ship Soon) | High (Ship Soon) | Strong | Agree |
| Third-party judge advisory | Medium-high (Ship Soon) | Medium (Ship Soon, advisory-only) | Medium | Slight over-rating |
| **Local telemetry fields** | Strategic, indirect (Measure first) | **High strategic (Measure first, but elevate priority)** | **Strong** | Disagree on priority weight |
| **Accepted-finding feedback capture** | Strategic, adoption-uncertain (Measure first) | **High strategic (Measure first, but the #1 research unlock)** | **Strong** | **Disagree — under-weighted** |
| `judge_policy` knob | Medium (Measure first) | Low-medium (Measure first) | Weak | Agree |
| Judge-family rotation recipe | Low-medium (Measure first) | Low-medium (Measure first) | Medium | Agree |
| Witness self-consistency n=3 | Unproven (Defer) | Unproven (Defer) | Weak | Agree |
| Judge panels/juries | Narrow (Defer) | Narrow (Defer) | Weak | Agree |
| Build escalation | Unclear (Defer) | Unclear (Defer) | Weak (negative evidence) | Agree |
| Batch schema | Low (Defer) | Low (Defer) | Weak (negative evidence) | Agree |
| Hidden patch synthesis | Reject | Reject | Strong (against) | Agree |
| Default debate loops | Reject | Reject | Strong (against) | Agree |
| 3 worker providers in normal WOs | Avoid | Avoid | Strong (against) | Agree |
| Auto-apply/merge/commit/push/PR | Reject | Reject | Strong (against) | Agree |
| New `adversarial` mode | Reject for now | Reject for now | Strong (against) | Agree |
| Per-finding fanout | Defer/reject | Defer/reject | Medium (against) | Agree |
| Large `report.md` parser | Avoid | Avoid | Medium (against) | Agree |
| Verbal confidence gates | Reject | Reject | Strong (against) | Agree |
| Persona lenses as cross-family substitute | Avoid | Avoid | Strong (against) | Agree |

---

## Detailed Notes Where I Disagree

### 1. Tighten `witness` audit/falsification — BUCKET WRONG

**ASSESS:** "Ship Soon, after routing and selector-confidence copy."
**My verdict:** This is the single most-multi-sourced recommendation in
the synthesis and should sit in **Ship Now** alongside routing copy. The
sequencing dependency on routing/selector copy is real but small; both
can ship in the same slice.

Direct evidence from SYN:
- SYN §1 Executive Summary: *"The evidence supports tightening
  code-review `witness` into an advisory adversarial audit of the source
  report"* — listed as a positive product posture conclusion, not a "soon."
- SYN §2 Multi-report agreement row "Escalation should remain post-run
  and advisory where appropriate": *"`witness` and `dispute` should not
  mutate the source run or replace its winner"* — this is exactly the
  contract the tightening codifies.
- SYN §4 Evidence Strength: *"Code-review `witness` should become an
  adversarial audit contract"* — rated **Moderate**, supported by
  v2 plan + dogfood + run `2026-05-23-e476`.
- SYN §5 Implications: explicitly names *"tighten it into an
  adversarial audit of source findings and keep it advisory"* under
  **Options That Should Stay Selective**.
- SYN §6 Open Gaps #3: *"Dogfood the v2 code-review `witness`
  contract..."* — flagged as an active research priority.
- RM §7 Suggested Sequence puts witness tightening as **step 1**, ahead
  of routing copy.

The assessment moves it to "Ship Soon" because it needs the new
report taxonomy and tighter validator. That is implementation reasoning,
which is out of scope for the value audit. On value alone, witness is a
Ship-Now item. The user's stated worry is exactly this case: a
high-evidence item deferred because of effort.

### 2. Accepted-finding feedback capture — UNDER-WEIGHTED

**ASSESS:** "Strategic value... direct daily user value is uncertain
unless the UI is extremely frictionless." Measure-first.
**My verdict:** Measure-first is correct, but the value rating
understates how much downstream policy depends on this. SYN §6 Open
Gaps lists *"Run an internal review benchmark across real target
repositories comparing single-model, same-family multi-lens, and
cross-model review on accepted findings, false positives, latency,
provider cost, and developer triage time"* as **gap #1**. Without
accepted-finding capture, every "measure first" item in this very
assessment (judge rotation, judge_policy, third-party judge defaults)
stays measurement-blocked.

SYN §4 marks *"Exact false-positive reduction rates for cross-model
review on production PRs are known"* as **Weak / a documented gap**.
The only way to close that gap from local data is human accept/reject
annotation tied to triage IDs.

Recommendation: keep the Measure-first bucket but **prioritize this
ahead of `judge_policy` and judge-family rotation recipe**. It is the
unblocker, not a peer.

### 3. Local telemetry fields — UNDER-PRIORITIZED WITHIN MEASURE-FIRST

**ASSESS:** "Strategic value, delayed direct user value... measure first."
**My verdict:** Correct bucket, but the synthesis treats telemetry as
load-bearing for almost every future policy decision. SYN §6 Open Gaps
#9 explicitly calls for *"Collect production telemetry for Bakeoff
runs"*. RM §5 Verification/Telemetry Ideas devotes an entire section to
this and explicitly says *"Future options should be chosen from run
evidence, not vibes."*

The assessment's Sequencing section gets this right at step 4
("Add local telemetry before changing judge defaults...") but the body
text under-sells how dependent the rest of Measure-First and Defer
items are on it.

### 4. Route advisor preview — SLIGHT OVER-RATING

**ASSESS:** "Very high user value... understated."
**My verdict:** High value, but evidence is medium not strong. SYN §6
Open Gaps #11 *"Build a task-fit rubric that predicts when Bakeoff
should warn..."* is listed as research-worthy, not a confirmed-pattern
recommendation. SYN §2 has *"Multi-agent benefit is task-shaped"* which
supports the underlying claim. Calling the benefit "understated" is
inference, not synthesized evidence. Keep in Ship Now; tone down the
"understated" framing.

### 5. Stop-here recommendations — SLIGHT OVER-RATING

Same pattern as #4. The "agentic theater" critique is plausible and
RM §2 supports it, but SYN does not strongly cite stop-here behavior as
a high-value item independently. It is a corollary of task-fit warning,
which is medium evidence. Keep in Ship Now, drop "understated" claim.

### 6. Source-run bundle for escalation — SLIGHT OVER-RATING

**ASSESS:** "Medium-high user value."
**My verdict:** Closer to medium. SYN §2 row *"Structured artifacts
beat hidden chat state"* supports the underlying principle, but the
specific value of bundle-as-escalation-reader is barely cited. RM §2
lists it once, no SYN backing for "bundle is the preferred reader."
Keep in Ship Now (docs work is cheap), but the value rating is the
weakest of the Ship-Now block.

### 7. Third-party judge advisory — VALUE RATING SLIGHTLY OVERSTATED

**ASSESS:** "Medium-high value."
**My verdict:** Medium. The evidence is real but the synthesis is
careful: SYN §4 marks *"Production systems have solved
judge-convergence bias"* as **Unverified** and *"Claude+Codex+Gemini
has been directly benchmarked against same-family multi-lens..."* also
**Unverified**. SYN §6 Open Gaps #2 names this as something to measure,
not something to ship with confidence. Advisory-only with explicit
"we have not measured this yet" copy is the correct posture. Keep in
Ship Soon.

---

## Top 3 Corrections

1. **Witness tightening should be Ship Now, not Ship Soon.** It is the
   most evidence-saturated item in the entire synthesis (§1, §2, §4,
   §5, §6 #3) and RM §7 lists it as implementation step 1. This is the
   clearest case of an evidence-backed item being demoted by
   implementation reasoning, which is exactly what the user asked to
   flag.

2. **Accepted-finding feedback capture is the #1 strategic unblocker,
   not a peer with `judge_policy`.** SYN §6 Open Gaps #1 explicitly
   names this as the top research priority, and SYN §4 marks production
   false-positive rates as a documented evidence gap. Without it, the
   measure-first items below it cannot be measured. Re-order
   Measure-First so accepted-finding feedback is the first item.

3. **The assessment is broadly defensible on the Reject/Avoid axis and
   on the Build core.** No evidence-backed item is wrongly Rejected. No
   thinly-evidenced item is wrongly in Ship Now. The Bloat Watchlist
   matches SYN §5 "De-Emphasize" and §6 cautions accurately. The audit's
   pressure points are concentrated in Ship Soon vs Ship Now ordering
   and in priority weighting within Measure First — not in the Reject
   bucket.

---

## Items Missing From The Roadmap

Cross-checking SYN §6 Open Gaps against the assessment:

- **SYN §6 #5** *"Test whether `--prefer-different-family` or a hard
  different-family rule for witness escalation improves calibration..."*
  — partially covered by the third-party judge advisory, but witness
  escalation specifically is not called out. Worth a sub-bullet under
  witness tightening or third-party judge advisory.

- **SYN §6 #10** *"Research current vendor/framework maturity only
  where it affects a product decision: Gemini/Copilot review
  false-positive rates, Devin-style autonomy, Cursor/Jules
  background-agent workflows, AutoGen GraphFlow/Magentic-One, and
  LangGraph persistence tradeoffs."* — not in the assessment at all.
  This is small but legitimate research scope, currently invisible.

- **SYN §6 #4** *"Verify `ValidateEscalationWitnessResult` accepts
  structured objects in `material_errors`, `missed_material`, and
  `triage_concerns`, or decide on the v2 per-claim verdict schema."* —
  mentioned in passing under witness tightening but framed as
  implementation detail. On the value side, the schema decision is a
  product question worth surfacing separately.

- **SYN §6 #12** *"Decide UX naming for `witness`..."* — RM mentions it
  as a "Later" follow-up; the assessment folds it into routing copy
  but does not call out the audit/witness rename question on its own.
  Low value, but worth listing.

None of these are major omissions. The roadmap covers the substance of
SYN §6.

---

## Confidence

**HIGH (~85%)** that:
- Witness should be Ship Now (multi-source confirmation in SYN).
- Accepted-finding feedback is under-weighted (SYN §6 #1 is explicit).
- No high-evidence item is wrongly Rejected/Avoided.
- No low-evidence item is wrongly in Ship Now.

**MEDIUM (~65%)** that:
- Route advisor and stop-here are slightly over-rated by the assessment
  rather than correctly rated. This is a "tone of writing" disagreement
  more than a bucketing disagreement.

## Status

COMPLETE
