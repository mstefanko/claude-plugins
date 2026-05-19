# Review: `plugin-task-fit-and-split-plan-2026-05-19.md`

Date: 2026-05-19
Reviewer: agent-deep-analysis
Status: review — execution-readiness audit

## Summary

Plan scope: add a lightweight task-fit warning and clean-split suggestion to
the Bakeoff plugin's natural-language drafting flow. Changes are constrained to
plugin instructions (`skills/bakeoff/SKILL.md`, `commands/run.md`) and docs; no
Go CLI changes. Rejected alternatives (decomposition agent, DAG, work-order-list
schema, cross-run synthesis, >2 providers) are explicit and load-bearing.

Verdict: **plan is largely execution-ready** but contains several ambiguities,
one factually mis-labeled line reference, an under-specified ordering question
between the task-fit and clean-split checks, and a thin acceptance/test rubric.
A writer could pick it up today, but would have to make ~5 judgment calls that
the plan should pin first.

Confidence: HIGH that the direction is right; MEDIUM that the breakdown is
unambiguous enough to hand to a swarm writer without follow-up clarification.

## 1. Implementation Clarity — vague / hand-wavy sections

### 1.1 Ordering of task-fit vs clean-split is implicit
Section 2 ("Clean-Split Check") says "Run this check only for large
natural-language requests." Section 1 ("Task-Fit Check") says "Run this check
after parsing flags and before drafting JSON". The two checks could both fire on
the same request, but the plan never states whether task-fit runs before or
after clean-split, or whether a single request can produce both a weak-fit
warning AND a split proposal in the same turn.

Resolution from surrounding context: `commands/run.md` runs Preflight → Existing
Work-Order Path → Natural Language Drafting. The natural fit is: Preflight →
Task-Fit Check → Clean-Split Check → Drafting. The plan should state this
sequence explicitly in step 2 of the Implementation Work Breakdown.

### 1.2 "Large natural-language request" is undefined
The clean-split check only fires for "large" requests but the plan never says
what "large" means (token count? number of distinct goals? evidence surfaces?).
Without a heuristic, two writers will encode this differently. Recommend: define
as "the request describes 2+ distinct goals OR 2+ unrelated evidence surfaces"
and skip a size threshold entirely — the existing 6 conditions in the split
check are the real gate.

### 1.3 "Shared context is short enough to repeat safely"
This is the only condition in the split-check list that requires judgment with
no anchor. Repeat what? How short? The plan should say "if the background block
fits in <N> lines or can be summarized in 1-2 sentences" or similar.

### 1.4 Run-id rule has an implicit case
The lightest-run model says:
- If `--run-id base` supplied → `base-part-1`, etc.
- If no run id supplied → "let the CLI use each work-order id"

Missing case: what if the user supplies `--run-id` but it already collides with
existing runs? The plan defers to "the existing collision policy" via line
reference, which is correct, but doesn't say whether `-part-N` is appended
before or after the date suffix from `SKILL.md:117`. Concretely: does
`base-part-1` then become `base-part-1-20260519` on collision, or
`base-20260519-part-1`? Plan should pin one.

### 1.5 Re-validation loop after split
Step 8 says "validate each file with `bakeoff validate <path>`". If part 2
fails validation, does the runner stop, or proceed with parts 1 and 3? The plan
doesn't say. Recommend: stop on first validation failure, report which file
failed, do not run any of the parts.

### 1.6 Partial-failure during sequential execution
Step 9 runs each file sequentially. If part 1 exits non-zero (or exit `3`
unresolved), does part 2 still run? The plan's risks section gestures at
"sequential execution is simple" but doesn't define the failure-stop policy.
Recommend: continue through all parts, surface per-part exit codes in the final
summary, do not abort on a non-zero/exit-3 part.

## 2. Open Questions Inventory

The plan has an explicit "Risks And Open Questions" section. Below is every
unresolved item, with resolution where the repo answers it.

| # | Question (paraphrased from plan) | Status | Resolution (from repo) or recommended answer |
|---|----------------------------------|--------|----------------------------------------------|
| Q1 | Over-splitting → cost / evidence noise | Mitigated by 2-3 cap | Acceptable; no action |
| Q2 | Weak-fit warnings too eager | Mitigated by material-change rule | Needs concrete trigger criteria — "material change" is undefined; suggest: only warn when one of (no verifier for build / no scope for review / no symptom for analyze) is true |
| Q3 | Split summaries must not auto-synthesize | Stated as non-goal | Reinforced by `commands/run.md:156` ("Stop after the Bakeoff handoff. Do not... synthesize a third patch") — no action |
| Q4 | Sequential vs parallel execution | Sequential for v1 | OK |
| Q5 | Overwrite/rerun behavior for split run ids | "do not replace unless user explicitly confirms exact run ids" | Under-specified — see §1.4 |
| Q6 | Tiny wrapper command later | Deferred | OK |

Additional unresolved items NOT in the plan's questions section but discovered
during this review:

- Q7: **Ordering** of task-fit vs clean-split checks (see §1.1).
- Q8: **Definition of "large"** request for clean-split gating (see §1.2).
- Q9: **Re-validation failure semantics** (see §1.5).
- Q10: **Partial-failure mid-sequence** semantics (see §1.6).
- Q11: **Approval re-prompt on revision** — if user says "change part 2", does
       the plugin re-show all three blocks or only the changed one? Plan is silent.
- Q12: **Background block sharing** — when drafting N work orders from one
       request, is the `background` field duplicated verbatim across parts, or
       does each part get a focused background? Plan implies "shared context...
       repeat safely" but doesn't say verbatim vs tailored.
- Q13: **Run-id when split is approved but base id collides** — see §1.4.

## 3. Risks / Gaps / Contradictions

### 3.1 Acceptance criteria are weak on verifiability
Current acceptance criteria (lines 340-351 of plan) are restatements of intent,
not testable conditions. Examples of stronger criteria a writer should add:

- "Given prompt `format these files`, the plugin emits the weak-fit warning
  string verbatim and does not write a `.work-order.json` until the user
  confirms."
- "Given a multi-goal prompt that matches all six split conditions, the plugin
  emits the split proposal with exactly 2-3 JSON blocks and one approval
  question."
- "Given approval, the plugin writes exactly `<base>-part-1.work-order.json`,
  `<base>-part-2.work-order.json` (etc.) and runs `bakeoff validate` on each
  before any `bakeoff research`/`bakeoff build` invocation."

Without these, "manual validation" in step 4 will drift between operators.

### 3.2 No rollout/backwards-compat plan
The change is plugin-instructions-only, so the blast radius is small, but the
plan should still call out:
- Existing work-order paths (`Existing Work-Order Path` section in
  `commands/run.md`) are explicitly **not** subject to the new checks. The plan
  says "do not split existing work-order paths" but does not say anything about
  task-fit. Should `bakeoff validate path.json` skip the task-fit warning?
  Probably yes — the user already drafted the file. State this.
- Existing users with muscle memory expect the natural-language flow to draft
  one work order with no extra friction. The weak-fit warning is new friction.
  Plan should mention a phrasing test or short opt-out (e.g., a `--no-fit-check`
  flag, though I'd argue against adding one in v1).

### 3.3 Testing strategy is "manual validation" only
Step 4 says "no Go tests should be required because this first pass changes
only plugin/docs behavior". That is true for the Go CLI but not for the plugin
contract itself. There is no test harness today for plugin instructions, so the
plan's choice is reasonable — but it should be explicit that no automated check
exists and the manual scenarios in step 4 are the regression suite.

Stronger version: write the 6 scenarios in step 4 as a checklist in a new
`docs/task-fit-test-scenarios.md` so they can be re-run after each plugin
instruction change.

### 3.4 The non-goals list duplicates "Rejected Alternatives"
Step 1 of the work breakdown says to add explicit non-goals (no decomposition
agent, no DAG, no work-order-list schema, no cross-run synthesis) into
`SKILL.md`. The plan itself already enumerates the same five rejected
alternatives. The writer should link to the plan rather than rewriting the
list — and the plan should say which is canonical.

### 3.5 No mention of `examples/`
`bakeoff/examples/` contains `gather.work-order.json`, `compare.work-order.json`,
`analyze.work-order.json`, `review.work-order.json`, `build.work-order.json`.
A natural follow-up would be to add an `examples/split/` directory showing a
2- or 3-part split for a canonical multi-goal prompt. The plan does not call
this out. Recommend: add as a step 5 (optional) so future maintainers see the
intended shape.

## 4. File Paths, Command Names, Line References — verification

| Plan reference | Verified? | Notes |
|----------------|-----------|-------|
| `skills/bakeoff/SKILL.md` | YES | Exists; current headers verified |
| `commands/run.md` | YES | Exists; current headers verified |
| `docs/work-orders.md` | YES | Exists (`Common Fields` section present) |
| Section `Work-Order Classification` in SKILL.md | YES | Line 20 of SKILL.md |
| `Natural Language Drafting` in commands/run.md | YES | Line 69 of commands/run.md |
| `commands/run.md:114-126` (cited in Lightest Run Model) | **PARTIAL MISLABEL** | These lines in `run.md` are the approval+collision text. The plan calls them "show full JSON and waiting for explicit approval before writing or running". Lines 114-126 cover approval *and* the post-approval write step (no overwrite). Reference is accurate enough but slightly imprecise — the "show JSON" instruction is actually line 114, not the full 114-126 range. Minor. |
| `skills/bakeoff/SKILL.md:104-122` | YES | This is the "Approval And Filename Collisions" section, accurate. |
| `skills/bakeoff/SKILL.md:117-122` (collision policy) | YES | Lines 117-122 cover the date-suffix and numeric-suffix collision rules. Accurate. |
| `bakeoff validate`, `bakeoff research`, `bakeoff build` | YES | All present in `allowed-tools` of `commands/run.md` and used in current docs |
| `docs/competitive-builds-evidence-2026-05-18.md` (cited in Evidence Sources) | YES | File exists. |
| `bakeoff init` (mentioned in Drafting Rules) | YES | Referenced in `SKILL.md` line 42 as "Do not call `bakeoff init` for generated work orders" |
| `--out`, `--run-id`, `--quiet`, `--keep-worktrees`, `--no-triage` flags | YES | All match `commands/run.md` Preflight list |
| `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff"` path pattern | YES | Matches current `commands/run.md` |
| Schema-version `1`, work-order types `gather/compare/analyze/build` | YES | Matches `docs/work-orders.md` Common Fields |
| Facet `code-review` for review | YES | Matches both SKILL.md and run.md |

**One concrete issue**: the plan's run-id rule says
"`./<base-id>-part-1.work-order.json`" but the existing collision policy in
`SKILL.md:120-122` is `./<id>-2.work-order.json`, `./<id>-3.work-order.json`,
etc. So `<base>-part-N` overlaps with the existing `<id>-N` suffix space.
A writer needs to either:
- Use a different separator (e.g., `<base>.part-1.work-order.json`), or
- Pick part numbers that don't collide with the existing suffix range, or
- Explicitly state that the `-part-N` suffix takes precedence and the
  collision policy then applies `-part-N-2`, `-part-N-3` on subsequent
  collisions.

This is not catastrophic but a writer will hit it on day one.

## 5. Work Breakdown — actionability

The 4-step breakdown is broadly executable but each step needs ~1 small
clarification:

**Step 1 (SKILL.md addition):**
- Specify exact insertion point: after the `## Work-Order Classification`
  section (ends line 40) and before `## Drafting Rules` (line 41). Plan says
  "after Work-Order Classification" but doesn't pin "before Drafting Rules".
- Suggested header text is fine.
- Non-goals list is duplicated with Rejected Alternatives — see §3.4.

**Step 2 (commands/run.md addition):**
- Plan says "In `Natural Language Drafting`, add the executable behavior" —
  but does this *append* to the existing section, or replace the existing
  draft flow with a check-first flow? The existing section already has its
  own order (classify → ask for missing pieces → draft JSON → show → ask
  approval → write → validate). The new behavior should slot in BEFORE
  classification. Plan should state explicitly: "insert the task-fit check
  as the first paragraph of the Natural Language Drafting section, before the
  silent type inference."

**Step 3 (README and work-orders.md):**
- Marked "optional". Recommend making it required — without it, users won't
  discover the new behavior.
- "Near the natural-language drafting or thin launcher section" is too loose.
  Specify: README `Quick Start` section (currently includes the
  natural-language draft examples).

**Step 4 (Manual validation):**
- See §3.3 — convert to a checklist file so it survives.

**Missing step 5 (recommended):**
- Add a short example pair (one weak-fit prompt and one split-prompt) to
  `examples/` or as inline JSON in the new SKILL.md section, so the plugin has
  a worked example to mirror.

## 6. Recommendation to the writer

Before starting, the writer should resolve Q7-Q13 (see §2) — most can be
answered in 1-2 sentences each. Specifically:

1. Pin the **ordering**: Task-Fit before Clean-Split, both before drafting.
2. Pin the **"large" definition** for clean-split gating.
3. Pin the **partial-failure** policy for sequential execution: continue,
   summarize per-part exit codes.
4. Pin the **run-id namespace** to avoid collision with existing `-N` suffix
   (e.g., use `<base>.part-N.work-order.json` or document
   `<base>-part-N` precedence).
5. Pin the **background-block strategy** for split parts: tailored per part,
   with the user-supplied background as a header summary.
6. Convert the manual-validation scenarios into a checked-in checklist.

Once those are answered, the breakdown is small enough that a single writer
session should complete steps 1-3 in well under an hour. Step 4 is a manual
QA pass and should be a separate session.

## 7. Sources

- `bakeoff/docs/plugin-task-fit-and-split-plan-2026-05-19.md` — plan under review
- `bakeoff/skills/bakeoff/SKILL.md:20,41,104,117,124` — verified section anchors
- `bakeoff/commands/run.md:15,45,69,114,137` — verified section anchors
- `bakeoff/docs/work-orders.md` — Common Fields confirms `schema_version`,
  `type` enum, provider scopes
- `bakeoff/docs/competitive-builds-evidence-2026-05-18.md` — exists; cited
- `bakeoff/examples/{gather,compare,analyze,review,build}.work-order.json` —
  existing canonical examples
- `bakeoff/README.md` Quick Start — confirms natural-language draft flow

## Confidence

- **Direction:** HIGH (>=85%). The recommendation is well-grounded in the
  rejected alternatives and in the existing thin-launcher posture.
- **Execution-readiness:** MEDIUM (~65%). A writer can start, but will need
  ~6 small clarifications during execution that should be pinned in the plan
  first.

## Status

NEEDS_REVISION before a swarm writer executes. The plan author should add a
"Decisions to pin before execution" section covering Q7-Q13 and §1.1-1.6.
After that, the plan is ready.
