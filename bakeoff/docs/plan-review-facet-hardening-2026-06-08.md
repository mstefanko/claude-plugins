# Plan-Review Facet — Hardening Plan (2026-06-08)

## Purpose

`facet.id: "plan-review"` is a recently added Bakeoff core feature. It was
exercised live by a real plan-review run. The run succeeded end-to-end, but the
ledger surfaced four issues worth fixing or tightening. This file records those
issues with enough run context that a fresh agent can independently reproduce
and verify each claim before changing code.

This is an investigation + fix plan, not a finished design. Each item below is a
**claim to verify first**, then fix. Do not assume the claims are correct;
confirm against the cited artifacts and source.

## Source Run

- **Run id:** `live-v2-experiment-plan-review`
- **Run dir:** `runs/live-v2-experiment-plan-review/`
- **Work order:** `live-v2-experiment-plan-review.work-order.json` (repo root)
- **Type / facet:** `gather` + `facet.id: "plan-review"`, `facet.kind: "generic"`
- **Run mode:** `pairwise` (claude/sonnet + codex/gpt-5.5, judge claude/opus xhigh)
- **Result:** `structured_union`, exit `0`, both providers `ok`, judge ran and completed
- **Plan that was reviewed:** `docs/paper-grade-experiment-analysis-implementation-plan-2026-06-05.md`
- **Inspect commands:**
  - `bakeoff show live-v2-experiment-plan-review`
  - `cat runs/live-v2-experiment-plan-review/manifest.json`
  - `cat runs/live-v2-experiment-plan-review/meta.json`
  - `cat runs/live-v2-experiment-plan-review/report.md`
  - `cat runs/live-v2-experiment-plan-review/decision.json`

Useful ledger facts for the investigation:
- `meta.json` and `manifest.json` both carry `facet_id: "plan-review"`, and
  telemetry `route.facet_id` is `plan-review` — facet projection works.
- `manifest.telemetry.triage` = `{ "state": "no", "item_count": null, "highest_severity": null }`.
- `manifest.telemetry.artifacts.output_truncation_count` = `1`.
- Provider status: codex `stderr_observed_bytes: 411946`, `stderr_truncated: true`,
  `stderr_kind: "diagnostic"`; claude stderr `0 B`.
- Decision: `canonical_winner: null`, `decision_kind: "structured_union"`,
  `selection_basis: null` (all correct for a no-winner union).

---

## Item 1 — Validator false-positive on prose "paths" (BUG, fix)

**Claim.** `bakeoff validate <plan-review work order>` warns about a narrative
phrase as if it were a missing file path.

**Observed evidence.** Validating the source work order produced:

```
warning: background references "meta/manifest/ls/summary" which does not exist
under <context-root>; did you mean one of: internal/summary/?
```

The string `meta/manifest/ls/summary` came from a `background[]` sentence
("projection into `meta/manifest/ls/summary`"), not a real path. The validator's
path-existence heuristic appears to treat any slash-containing token in free
text as a candidate file path.

**Why it matters.** Plan-review and gather work orders routinely describe
artifacts and code areas in prose using slashes. A spurious "missing path"
warning on healthy orders erodes trust in real warnings.

**Investigate.**
- Find the validator code that emits `references "<x>" which does not exist
  under <context-root>` and the "did you mean" suggestion. Grep the validate
  command / workorder validation package for `did you mean` and
  `context-root`.
- Determine which fields are scanned (likely `goal` + `background`) and what
  token regex flags a "path".

**Proposed fix (confirm before implementing).**
- Only treat a token as a path candidate when it has a real file extension OR
  matches an existing on-disk prefix (e.g. `internal/`, `docs/`, `examples/`).
- Or restrict path-existence checks to dedicated path-bearing fields and stop
  scanning narrative `background`/`goal` strings.
- Keep the warning for genuine path-like references (`docs/foo.md`,
  `internal/pkg/file.go`).

**Acceptance.**
- The source work order (or an equivalent fixture with `meta/manifest/ls/summary`
  in `background`) validates with no spurious path warning.
- A work order citing a genuinely missing path (`internal/does-not-exist.go`)
  still warns.
- Existing validator tests pass; add a regression test for the prose case.

---

## Item 2 — Plan-review findings are never triaged (DESIGN GAP, decide + implement)

**Claim.** Plan-review runs ship raw, unverified findings; triage never runs for
this facet, unlike code-review.

**Observed evidence.** `manifest.telemetry.triage.state == "no"`,
`item_count == null`. No `triage/` directory exists under the run dir. The run
produced ~20 severity-tagged, actionable findings, all unverified.

**Why it matters.** Plan-review output is shaped exactly like code-review output
(actionable defects with severity/confidence). code-review auto-triages to
separate real issues from false positives; plan-review does not, yet nothing in
the run summary makes that contract explicit.

**Investigate.**
- Find where auto-triage is gated by facet. Grep the research/triage code for
  `code-review` and `facet` to see the condition that enables triage.
- Decide the intended contract: should `plan-review` auto-triage (verify each
  claim against its cited plan line + repo line), or is it untriaged-by-design?

**Two acceptable outcomes (pick one, document the decision).**
- **A. Extend triage to plan-review.** Wire a triage pass that checks each
  finding's plan citation and repo citation. Project `triage.state`/counts into
  manifest like code-review does.
- **B. Document untriaged-by-design.** If triage is intentionally code-review
  only, make the run summary / docs state that plan-review findings are raw, so
  the "unverified" status is a documented contract rather than silent.

**Acceptance.**
- The chosen behavior is documented in `docs/work-orders.md` and/or
  `docs/cli-reference.md`.
- If A: a plan-review run shows a non-`no` triage state with item counts; tests
  cover facet-gated triage.

---

## Item 3 — Weak semantic dedup in the union selector (QUALITY, tighten)

**Claim.** The `structured_union` merge deduped only near-exact matches and left
many semantically-overlapping findings as separate items, inflating the count.

**Observed evidence (from `report.md`).** The same underlying defect appears
multiple times across provider-set buckets:
- claude `F-001` ("reserve single_agent_baseline") ≈ claude+codex `F-013`
  (same defect, multi-source).
- claude `F-002`, `F-003`, `F-004`, `F-005`, `F-006` are all facets of
  "Phase 1 work already implemented," which is also captured by claude+codex
  `F-011`.

Net effect: ~20 findings for ~8 distinct defects. The selector label is
`union/dedupe`, so dedup is expected to handle this.

**Why it matters.** For a paper-grade comparison surface (the stated goal of the
plan under review), redundant findings inflate counts and reader load and make
cross-run comparison noisier.

**Investigate.**
- Locate the gather union/dedupe logic (judge merge for `structured_union`).
  Determine whether dedup is exact-text only or attempts semantic clustering.
- Inspect `judge/result.json` and `judge/prompt.txt` in the run dir to see what
  the judge was asked to dedup and what it returned.

**Proposed fix (confirm scope before implementing).**
- Strengthen clustering so semantically-overlapping claims merge into one
  finding with combined sources, OR
- At minimum, cross-reference single-source findings that are already covered by
  a multi-source finding (e.g. "see F-011").

**Acceptance.**
- A re-run (or a fixture replay) over the same inputs yields fewer redundant
  findings, with overlapping claims merged or cross-referenced.
- No loss of distinct defects; verify the 8 distinct issues all survive.

---

## Item 4 — Diagnostic stderr trips truncation telemetry (MINOR, tighten)

**Claim.** A healthy codex run looks like it overran output because benign
diagnostic stderr is counted toward truncation telemetry.

**Observed evidence.** codex `stderr_observed_bytes: 411946`, truncated to
60 KB (`stderr_truncated: true`), and `telemetry.artifacts.output_truncation_count: 1`
— on an exit-0, status-`ok` run. The dropped stderr is rollout chatter, e.g.:

```
ERROR codex_core::session: failed to record rollout items: thread <id> not found
```

The `stderr_kind: "diagnostic"` classifier correctly identified the noise.

**Why it matters.** Truncation telemetry should flag real output-cap problems.
Counting benign, already-classified-`diagnostic` stderr makes a clean run look
degraded.

**Investigate.**
- Find where `output_truncation_count` is incremented and whether it
  distinguishes stdout truncation from `diagnostic`-classified stderr
  truncation.

**Proposed fix (confirm before implementing).**
- Do not increment the truncation/overrun alarm for stderr already classified
  `diagnostic`, OR track diagnostic-stderr truncation in a separate,
  non-alarming counter. Keep stdout truncation behavior unchanged.

**Acceptance.**
- A run whose only truncation is diagnostic stderr reports
  `output_truncation_count: 0` (or a separate diagnostic counter), while stdout
  truncation still increments the alarm.

---

## Suggested order

1. Item 1 (validator false positive) — smallest, clearest, highest trust impact.
2. Item 2 (triage contract) — needs a decision before code.
3. Item 3 (dedup) — larger, behavioral; scope carefully.
4. Item 4 (diagnostic truncation telemetry) — minor polish.

## Out of scope

- Rewriting the reviewed plan (`docs/paper-grade-experiment-analysis-implementation-plan-2026-06-05.md`).
  Its staleness defects are tracked separately by the run's report.
- Any change to provider count, judge semantics, or `latest` behavior.
