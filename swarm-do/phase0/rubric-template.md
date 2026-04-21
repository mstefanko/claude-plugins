# Phase 0 Codex Cross-Model Review — Pre-Registered Rubric

This rubric is **pre-registered**: the operator fills in all "(fill in)"
sections BEFORE running a single review. Locking definitions ahead of time
keeps adjudication honest. After the experiment runs, only the results
table and the final decision field are updated.

The overall experiment design lives in
`~/.claude/plans/codex-swarm-integration.md` Section 2. This file is the
working adjudication sheet for one instance of that experiment.

---

## 1. Phase cohort pre-registration

Target: 12-15 phases. Stratify across kinds (overlap allowed — one phase
can count toward more than one stratum).

Minimum counts:

- 3 `bug` phases
- 3 `feature` phases
- 2 `refactor` phases
- 2-4 `high-risk` phases (auth, money, migrations, parser/serializer)
- >=3 `follow-up-rework` phases (phases whose predecessor needed rework)

| # | phase_id | kind(s) | repo | rationale for inclusion |
|---|----------|---------|------|-------------------------|
| 1 | (fill in) | (fill in) | (fill in) | (fill in) |
| 2 | (fill in) | (fill in) | (fill in) | (fill in) |
| 3 | (fill in) | (fill in) | (fill in) | (fill in) |
| 4 | (fill in) | (fill in) | (fill in) | (fill in) |
| 5 | (fill in) | (fill in) | (fill in) | (fill in) |
| 6 | (fill in) | (fill in) | (fill in) | (fill in) |
| 7 | (fill in) | (fill in) | (fill in) | (fill in) |
| 8 | (fill in) | (fill in) | (fill in) | (fill in) |
| 9 | (fill in) | (fill in) | (fill in) | (fill in) |
| 10 | (fill in) | (fill in) | (fill in) | (fill in) |
| 11 | (fill in) | (fill in) | (fill in) | (fill in) |
| 12 | (fill in) | (fill in) | (fill in) | (fill in) |
| 13 | (fill in) | (fill in) | (fill in) | (fill in) |
| 14 | (fill in) | (fill in) | (fill in) | (fill in) |
| 15 | (fill in) | (fill in) | (fill in) | (fill in) |

Cohort locked on: (date)
Locked by: (operator)

---

## 2. Verdict definitions

These MUST be written before any adjudication runs.

### True positive

(fill in — what counts as a real, actionable defect caught by the
reviewer? Examples: "a defect the operator would fix before merge";
"a defect that would have caused a production incident if shipped")

### False positive

(fill in — what is clearly not a real defect? Examples: "the code is
correct and the reviewer misread it"; "the concern is valid in general
but does not apply to this codebase's invariants")

### Ambiguous

(fill in — what goes in the "cannot decide" bucket? Examples:
"plausibly correct concern but requires information not in the diff";
"style preference masquerading as a defect")

### Duplicate match rule (preset)

Two findings (one from Claude, one from Codex) are the same finding when
**all three** hold:

1. Same file path.
2. Same defect class (category in the output schema; treat `types`/`null`
   as a single class for duplicate purposes).
3. Line references are within ±3 lines of each other.

Only exact matches on all three count as duplicates. Near-misses count as
two separate findings.

---

## 3. Blinded adjudication protocol (preset)

1. After both reviews finish, merge all Claude findings and all Codex
   findings into one flat list.
2. Strip source attribution. Replace with a random ID per finding.
3. The operator rates each anonymized finding against the True positive
   / False positive / Ambiguous definitions above.
4. Lock the verdicts (write them to the results table or a separate
   locked file).
5. Only then unblind — map each random ID back to its source
   (Claude / Codex Mode A / Codex Mode B) and fill the results table.

No peeking at the source before verdicts are locked. If the operator
accidentally sees the source during rating, that finding is excluded
from the experiment.

---

## 4. GO / NO-GO decision thresholds (preset from plan Section 2)

- **GO-EVERY-DO** — Mode A (scoped, no repo access) surfaces at least
  one non-overlapping **real** issue in **>=30%** of phases in the cohort,
  AND averages **<2 false flags per phase**.

- **GO-TARGETED** — Mode A fails the above threshold, BUT Mode B
  (repo-aware read-only) meets it. In this outcome Codex review becomes
  an opt-in step for high-risk / follow-up-rework phases rather than
  every phase.

- **NO-GO** — both modes are noise>signal. Do not wire Codex review into
  the swarm. Revisit after a model bump or after the plan's assumptions
  change.

Interpretation note: the "non-overlapping" requirement means the Codex
finding must NOT be a duplicate (per the rule in Section 2) of a Claude
finding on the same phase. Duplicates are evidence of agreement, not of
added coverage.

---

## 5. Results table

Fill one row per phase per mode. A single phase thus produces two rows
(one Mode A, one Mode B) if both were run.

| phase_id | phase_kind | model | effort | claude_found | codex_A_found | codex_B_found | adjudication | latency_A | latency_B | cost_A | cost_B |
|----------|-----------|-------|--------|--------------|---------------|---------------|--------------|-----------|-----------|--------|--------|
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |
| (fill) | (fill) | gpt-5.4 | high | (n) | (n) | (n) | (TP/FP/Amb breakdown) | (s) | (s) | ($) | ($) |

Column notes:
- `claude_found`, `codex_A_found`, `codex_B_found` = count of findings
  surfaced, NOT count of true positives. Split happens in `adjudication`.
- `adjudication` = `TP:n / FP:n / Amb:n` after blinded rating is unlocked.
- `latency` = wall-clock seconds reported by the wrapper on stderr.
- `cost` = approximate USD from Codex usage reporting.

---

## 6. Final decision

One of: `GO-EVERY-DO | GO-TARGETED | NO-GO`

Decision: (fill in)
Decided on: (date)
Decided by: (operator)
Rationale: (fill in — cite the cohort numbers that drove the pick)
