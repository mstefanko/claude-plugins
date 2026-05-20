# Drafting Phase Speedups Implementation Plan

Date: 2026-05-20

## Goal

Reduce the `/bakeoff:run` natural-language drafting phase for obvious,
well-scoped work orders without weakening Bakeoff's replayability,
verification, approval, or run-isolation guarantees.

The immediate dogfood target is the `ls-order-by-finished-at` build work order:

- target area: `internal/commands/lscmd/**`;
- explicit goal: order `bakeoff ls` output by `finished_at` descending;
- explicit acceptance criteria;
- explicit gate verifier: `go build ./... && go test ./internal/commands/lscmd/... -run . -count=1`;
- normal build topology: two build providers, one judge, codebase scope;
- no requested split, multi-lens review, metric benchmark, protected verifier
  fixture, or non-`HEAD` base.

That request was reported as taking about 10 minutes to prepare before
provider execution. **Experiment A (2026-05-20) refuted that as a typical
baseline:** three fresh-session trials of the same prompt under the pre-PR
contract measured 25.5 s, 31.9 s, and 51.6 s — median 31.9 s,
ratio 2.02× between fastest and slowest. The 10-minute anecdote appears to
have been a high-water dogfood, not a steady-state cost.

The plan therefore targets **tail behavior and exploration discipline**, not
median wall time:

- Keep narrow build drafting within the measured baseline envelope
  (A max 51.6 s) while treating **≤ 30 s** p95/max-over-three as an
  aspirational follow-up target, not a first-PR ship gate.
- When the request supplies explicit scope, acceptance criteria, and gate
  verifier, hold **pre-preview tool calls ≤ 2** (preflight plus at most one
  batched context pass).
- Watch pre-preview model turns against A's 6-turn median; do not trade
  reliability for turn-count targets.
- Do not regress the safety and validation behavior that makes provider
  execution replayable.

The fast-path predicate addresses the outlier path (Trial 3: 6 sequential
exploratory tool calls before drafting). The batched-exploration rule
addresses the same path when one fact-lookup is genuinely needed. Median
saving is bounded; **the value of this work is variance reduction and
making outlier paths impossible by contract.**

## Empirical Progress

Log: [drafting-fast-path-experiment-log-2026-05-20.md](drafting-fast-path-experiment-log-2026-05-20.md)

Experiments run in order G → A → D → B → E. C and F deferred to a follow-up PR.
This table is chronological: rows before the plugin-cache methodology
correction are preserved as lab history, but later clean-cache rows supersede
their conclusions for implementation decisions.

| Exp | Status | Trials | Headline | Effect on plan |
| --- | --- | --- | --- | --- |
| G — Preflight cost | ✅ PASS (2026-05-20) | n=5 | Median 17 ms, range 3 ms, ≈0.01% of 2-3 min budget | Preflight-caching risk closed for this PR. Observed-cost-pattern updated. |
| Helper — `scripts/measure-drafting.py` | ✅ DONE (2026-05-20) | validated | Parses Claude Code JSONL; extracts start/stop/wall/turns/tool_calls | A no longer blocked on tooling. |
| Calibration trace (real, non-A prompt) | 🔎 reference only | n=1 | 45.2 s, 8 turns, 3 tool calls on a compare-mode `/bakeoff:run` from 2026-05-19 | Indicates the 10 min anecdote is high-water, not typical. Does **not** substitute for A. |
| A — Baseline | ✅ MEASURED (2026-05-20) | n=3 | Median 31.9 s / max 51.6 s / 2.02× variance; one trial used 6 exploratory tool calls | **Rewrote Goal targets and Shared Measurement thresholds.** 10-min anecdote refuted. Plan now targets tail/exploration discipline, not median. Trial 2 surfaced a contract-drift case (write before approval) → added to D. |
| Step 1 contract edits | ✅ LANDED (2026-05-20) | — | Fast-path predicate + action + fallback + approval phrase + build-only v1 added to `commands/run.md` (rewrote line-474 "infer silently" paragraph) and to `## Drafting Rules` in `SKILL.md`. Steps 2-5 (batched exploration wording, preview defaults, skeleton, scenarios) still pending. | D unblocked. |
| D — Negative matrix | ⚠️ PARTIAL FAIL (2026-05-20) | n=11, dogfood screenshots | D3, D4, D6, D7 PASS. **D1, D2, D5 FAIL** — model synthesized verifier/AC/protected-paths instead of asking. D11 intermittent FAIL — one B-side trial wrote `.work-order.json` before approval, recurring A Trial-2 drift. | **Predicate is too permissive on missing-field cases.** Step 1 contract needs a hard "do not synthesize required fields" clause. Write-before-approval drift needs an explicit "preview must precede any Write" rule. Both gates added to Step 1 carry-over. |
| B — Positive target | ⚠️ MIXED (2026-05-20) | n=4 dogfood screenshots | Wall times 32 s / 43 s / 52 s / 59 s (one with source-read exploration). Image 3 wrote file before approval (FAIL on D11 gate). | Drafting wall time hits the ≤ 30 s target on the cleanest trial only. **Variance still 1.8×.** Need post-fix re-run after D1/D2/D5/D11 fixes land. |
| B — Provider dogfood signal | ✅ DONE (2026-05-20) | n=1 | 4 m 1 s total; `decision_kind=pick_winner`, winner=claude, judge-basis (both providers passed gate; 2-pass judge agreement). **Validation required major repair before run** (schema-fictional draft). | Build pipeline healthy. Bottleneck is upstream drafting schema-drift, not execution. New Step 4 acceptance criterion: zero validation repairs on fast-path drafts. |
| E — Batched exploration | ⏳ operator-blocked | — | — | Blocked on Step 2 (batched-exploration wording) landing. Now strongly motivated by A Trial 3 (6 sequential tool calls) and Image 11 multi-lens (7 sequential calls, 2 m 12 s). |
| R1-R5 contract amendments | ✅ LANDED (2026-05-20) | — | New `## Drafting Invariants` section in `commands/run.md` (line 109) and `skills/bakeoff/SKILL.md` (line 408). Covers required-field-synthesis forbid (R1), no-Write-before-approval (R2), available-backends list (R5), canonical skeletons (R3), pre-preview internal validate (R4). Both files diff-checked for drift (none beyond intentional cross-references). `bakeoff/CLAUDE.md` updated with batched-exploration + no-Write reminders. | D and B drafting re-runs unblocked. E unblocked. Five experiments now runnable in a single fresh-session batch. |
| Post-R1-R5 fresh-session batch | ⚠️ PARTIAL (2026-05-20) | n=5 | R2 ✅ 100 %, R5 ✅ 100 %, R3 ✅ 80 % (D1 holdout), R4 ✅ 60 % (D1 skipped, D11 reused, E unclear). **R1 ❌ 0 %** — D1 synthesized verifier, D2 synthesized AC, D5 elided protected-paths ask. D11 PASS (existing-file detection). E 3 batched context calls (target 1). | Schema, write-discipline, and backend-list amendments are doing their job. R1 needs tightening: hoist fallback above fast-path action, add mechanical checklist, add anti-synthesis examples. R1.1-R1.4 amendments authored below and landed in `commands/run.md` + `SKILL.md`. |
| R1.1-R1.4 tightening pass | ✅ LANDED (2026-05-20) | — | Added (1) gating clarification — missing required fields disqualify fast-path before the action block; (2) Mechanical Pre-Flight Checklist subsection with 4 verbatim yes/no questions; (3) Anti-Synthesis Patterns subsection listing concrete examples of AC restatements that look like AC but aren't; (4) Verifier anti-synthesis examples ("the conventional test command", "the auth tests", invented-from-convention argv). Both files diff-checked for drift. | D1/D2/D5 re-run unblocked. Acceptance gate: all three land in missing-field-ask, zero synthesized fields. |
| Post-R1.1-R1.4 fresh-session batch 2 | ❌ FAIL (2026-05-20) | n=3 | D1, D2, D5 all synthesized again. D1 also produced fictional schema (R3 ❌, R4 ❌). D2 used canonical schema and did pre-preview validate (R3+R4 ✅) but still synthesized AC. **Cross-batch R1 landing rate: 0/6.** | Prompt-layer enforcement of R1 has hit its ceiling. Two amendments (R1 + R1.1-R1.4 = 5 prompt mechanisms) have not moved the rate off 0 %. Architectural change needed. |
| Architectural decision: prompt-only R1 is not viable | ⏳ pending operator (2026-05-20) | — | Two passes proven insufficient: contract text cannot reliably stop the model from framing a request with goal+scope as "clean fast-path" and synthesizing missing AC/verifier. Three options now on the table — A: mandatory `REQUIRED-FIELD CHECK:` output marker (R1.5, last prompt-layer attempt); B: Go-side write-time linter (`bakeoff lint-draft`) for synthesized-looking AC patterns; C: accept the limit and demote R1 to best-effort. Recommend A first; B if A fails. | Plan pauses on R1 until operator picks A, B, or C. R3/R4 remain working when triggered; R2/R5 holding at 100 %. |
| R1.5 mandatory output marker | ✅ LANDED (2026-05-20) | — | Added `#### Required-Field Check Marker (Mandatory Output)` subsection to `commands/run.md` and `skills/bakeoff/SKILL.md`. Specifies a verbatim `REQUIRED-FIELD CHECK:` block the model must emit before any preview/draft/Write. Fields: `verifier_verbatim`, `ac_as_behaviors`, `edit_boundary_named`, `benchmark_protected_paths`, `decision`. If `decision: ask-for: <field>`, no preview JSON may follow. Operator grep-audits `REQUIRED-FIELD CHECK:` in transcripts as the canonical pass/fail signal. | Last prompt-layer attempt at R1. Batch 3 (D1, D2, D5 fresh sessions) is the gate. If R1.5 also lands at 0 %, fall through to Option C (accept R1 best-effort, document as known gap). Skip Option B unless real-use telemetry later shows R1 drift causing problems. |
| Post-R1.5 fresh-session batch 3 | ❌ FAIL (2026-05-20) | n=3 | **R1.5 marker absent in 0/3 responses.** D1, D2, D5 all fast-pathed with fictional schema and synthesized fields. Cross-batch R1 rate after three amendments: **0/9**. Side-finding: batch 3 produced more fictional schema than batch 2 (3/3 vs 2/3) — more contract text correlated with worse R3/R4 discipline, not better. R1.5 actively harmed schema quality. | Prompt-layer R1 enforcement is conclusively not achievable. Option C (accept the limit) selected. |
| R1.5 rollback + R1 demotion (Option C) | ✅ LANDED (2026-05-20) | — | (1) Removed `#### Required-Field Check Marker (Mandatory Output)` subsection from `commands/run.md` and `skills/bakeoff/SKILL.md`. (2) Renamed `### Required-Field Synthesis Is Forbidden` → `### Required-Field Synthesis Guidance (Advisory)`. (3) Softened the language: "must ask the missing question" → "should prefer asking", "contract failure" → "is not a contract violation". (4) Added a one-paragraph why-this-is-advisory note citing the 0/9 dogfood landing rate and the experiment log. The mechanical checklist and anti-synthesis examples remain as educational content. | R2, R3, R4, R5 remain hard invariants. R1 ships as advisory guidance with a documented prompt-layer limitation. Real-use safety net is the operator's preview-then-approve flow. Future work (Option B Go-side linter) only if telemetry shows synthesis drift causing real problems. Plan closed. |
| Post-cycle consistency audit | ✅ PASS (2026-05-20T16:35Z) | — | Verified: zero `REQUIRED-FIELD CHECK:` references anywhere (R1.5 fully rolled back). Both files have `### Required-Field Synthesis Guidance (Advisory)` section (R1 demoted, line-wrapped "should prefer asking" present). No orphaned "must ask the missing" language. Two `is a contract failure` occurrences remain in the R3 Canonical Skeletons section — intentional, since field-invention is still an R3 violation. Subsection structure identical between `commands/run.md` and `skills/bakeoff/SKILL.md` (R1 Advisory + Mechanical Checklist + Anti-Synthesis Patterns + R2 + R5 + R3 + R4). Line counts: `commands/run.md` 900, `SKILL.md` 924 (was 669 + 691 pre-cycle; net +464 lines after R1.5 rollback). Cross-references plan↔log present (8 from plan, 3 from log). `bakeoff validate` passes on `lscmd-order-by-finished-at.work-order.json`. | Contract is internally consistent. R3 enforcement language (still "contract failure") and R1 advisory language (now "should prefer") coexist correctly — different rules with different enforcement strictness. Cycle truly closed; no rollback artifacts. |
| Post-rollback batch 4 | ❌ FAIL (2026-05-20T17:00Z) | n=4 | **R3/R4 did NOT recover after R1.5 rollback.** 4/4 trials produced fictional schema (`schema_version: "1.0.0"` or `"1"`, `providers[].kind`/`name`/`provider`, `scope: "repo"`, top-level `acceptance_criteria`/`verifiers[]`, no `build` block, missing `budgets.max_output_bytes`). 4/4 trials skipped pre-preview validate. R2 ✅ 4/4 (no Write before approval). R5 ✅ 4/4 (no CLI probing). Cross-batch R3/R4 stays at 0% post-rollback. | **The hypothesis that R1.5 was harming R3/R4 was wrong.** R3/R4 are not enforceable via contract alone — same prompt-layer ceiling as R1. The safety net is downstream: R2 + post-write `bakeoff validate` catches fictional schema before any provider runs. Friction-only impact for the user, not broken bakeoffs. Two paths forward: (A) extend Option C to R3+R4 (demote to advisory) and ship; (B) build a small Go-side pre-preview validate hook that the model cannot skip — much smaller and safer than the R1 synthesis linter previously considered. Recommend B for R4 specifically. |
| C+ — R3 + R4 demotion to advisory | ✅ LANDED (2026-05-20T17:15Z) | — | (1) Renamed `### Canonical Skeletons` → `### Canonical Skeletons (Advisory)` in both `commands/run.md` and `skills/bakeoff/SKILL.md`. Softened "must copy verbatim" → "should copy verbatim", removed "is a contract failure" framing. Added why-this-is-advisory note citing ~33% landing rate. (2) Renamed `### Pre-Preview Internal Validate` → `### Pre-Preview Internal Validate (Advisory)`. Softened "must internally invoke" → "should internally invoke". Marked step 3 of the user-visible flow as `**(should)**` and step 7 (post-write validate) as `**enforced** safety gate`. Added explicit statement that skipping step 3 incurs a repair-and-reapprove cycle but is not unsafe. (3) Skeleton bodies, drift-pattern lists, and flow ordering preserved — only the enforcement language softened. | **Source-only as of audit (cache contains pre-C+ version).** Hard invariants are R2 (no Write before approval, 100%) + R5 (no CLI probing, 100%) + post-write `bakeoff validate` (Go-side, can't be skipped). R1/R3/R4 ship as advisory guidance with documented landing rates. The safety net is empirically proven: across 16 trials, zero broken bakeoffs reached a provider run. Friction cost on fictional drafts is one repair-and-reapprove cycle. Plan closed pending verification of methodology. |
| ❌ **METHODOLOGY CORRECTION: plugin cache contamination** | ⚠️ CYCLE DATA UNRELIABLE (2026-05-20T17:30Z) | — | **All four dogfood batches ran against cached pre-R1-R5 contract**, not the amendments being landed in source. Plugin cache is at `~/.claude/plugins/cache/mstefanko-plugins/bakeoff/<sha>/`, separate from the marketplace source tree where edits were applied. Cache mtime audit + screenshot timestamps prove batches 1-4 all ran against `0c8f2f8c9b59` (mtime 12:21, no amendments); the R1-R5 cache `419d1194a769` was created at 13:05 — after batch 4 finished at 13:04. | Invalidates R1 0/9, R3 ~33%, R4 ~27% landing-rate claims (measured baseline, not amendments). What survives: R2 100% (baseline already covers it), validation audit (cache-independent), schema-drift repair count (static-file analysis), B's provider dogfood execution (used `bin/bakeoff` binary directly). Verification trial against current cache `419d1194a769` (which has R1 advisory + R3/R4 strict-must + R1.5 rollback) needed before re-asserting conclusions. |
| Plugin update + verification n=9 batch | ✅ CLEAN DATA (2026-05-20T18:00Z) | n=9 (3 per prompt) | Operator ran `/plugin` + `/reload-plugins` to promote source HEAD `7077a02507a3` into the active cache. Verified `installed_plugins.json` pin matches HEAD. Three D-style prompts × 3 trials each, all confirmed running against `7077a02507a3` via bash preflight. **Real landing rates: R1 6/9 = 67% (D1 3/3, D5 3/3, D2 0/3 — refactor soft spot); R3 3/3 = 100% when drafting happens; R4 1/3 = 33% when drafting happens; R2 9/9 = 100%; R5 9/9 = 100%.** | **Cycle's "prompt-layer ceiling" conclusion was wrong** — the amendments work when actually loaded. Decisions: (a) R3 promoted back to strict-must (was demoted in C+ based on contaminated data); (b) R1 gets refactor-specific tightening (R1.6) since D2 fails consistently on refactor-style prompts; (c) R4 stays advisory (33% rate held even with strict wording in batches 1-4, so demotion is honest). |
| R3 promotion + R1.6 refactor tightening | ✅ LANDED (2026-05-20T18:05Z) | — | (1) Reverted R3 section header in `commands/run.md` and `skills/bakeoff/SKILL.md` from `### Canonical Skeletons (Advisory)` → `### Canonical Skeletons`. Restored "must copy verbatim" + "is a contract failure" language. Removed the "advisory guidance" paragraph and ~33% landing-rate citation (both based on contaminated data). (2) Added refactor-specific checklist item to the Mechanical Pre-Flight Checklist in both files: `[ ] If the request is a refactor/extract/consolidate/split: user named the behavioral invariants to preserve?` with explanation that "no behavior change" is exactly the anti-synthesis pattern, ask for specific test files / API contracts / round-trip equalities. (3) Added a "Refactor edge case (load-bearing)" callout below the checklist that names the problem and the response. | R1.6 close-the-gap effect verified in the next row. R4 unchanged (stays advisory). |
| R1.6 verification batch (D2 × 3) | ✅ PASS (2026-05-20T18:15Z) | n=3 | After `/plugin` update to source HEAD `a3e882b8e423` ("Reworking"), operator ran 3 fresh D2 sessions. **All 3 trials cited R1.6 by name** (three different paraphrases: "the contract's refactor-edge-case rule", "the contract's load-bearing refactor edge case", "the contract flags refactors as a known soft spot") **and asked for behavioral invariants instead of synthesizing**. Multi-select option presentation across trials offered Public API unchanged / byte-identical defaults / resolution order preserved / strict-vs-loose / paste-your-own — all healthy variations on the same underlying constraint. No drafted JSON in any trial. | R1.6 closes the refactor soft spot. **R1 effective landing rate is 100% across the verification prompts under their final contract** (D1 3/3, D5 3/3, D2-with-R1.6 3/3). Cycle CLOSED. |
| Final corroboration batch (B + D8/D9/D10) | ✅ PASS (2026-05-20T18:25Z) | n=4 | (a) **B drafting metric** on the lscmd positive case: canonical schema in compact preview (`schema_version: 1`, `providers[].backend`, nested `build.verify[].argv`, full `budgets`), default-aware note on `build.protected_paths`, no Write before approval. Model explicitly cited *"using the canonical build skeleton"*. Wall **40 s** — above the original ≤ 30 s goal but within A baseline range (31.9 s median / 51.6 s max). R4 not visible. (b) **D8** (3-way split): split recognized AND R1 missing-field check fired for verifier+AC, correctly stacked. (c) **D9** (path-like missing input): path error reported per contract; not reinterpreted as natural-language request. (d) **D10** (scope:web on build): rejection + secondary "verifier doesn't actually verify the deliverable" insight. | All testable predictions verified. **R1/R2/R3/R5 land at 100% on tested prompts; R4 at 25-33% (advisory, backstopped by Go-side post-write validate).** Wall time held within baseline range despite +258 contract lines. Cycle EMPIRICALLY CLOSED. Optional deferred work (C1/C2 variants, conditional-trigger contract trimming, Go-side pre-preview hook) is non-blocking. |
| Step 5: Fast-Path Drafting Scenarios | ✅ LANDED (2026-05-20T18:35Z) | — | Added `## Fast-Path Drafting Scenarios` section to `docs/task-fit-test-scenarios.md` per Step 5 of the plan. Covers: (a) positive fast-path triggers (narrow Go package build, single-file change, existing-file reuse); (b) R1 missing-required-field cases (D1 no-verifier, D2 no-AC non-refactor, D2-with-R1.6 refactor invariants, D5 metric protected paths, D4 vague target); (c) routing/mode-conflict cases (D3 "build a comparison matrix" → compare, D6 unbounded review, D7 multi-lens, D8 obvious 3-way split, D9 path-like missing input, D10 scope:web rejection); (d) R2/R3/R5 always-on invariants as sanity checks; (e) R4 advisory framing; (f) known soft spot documentation (refactor + missing AC). Each scenario lists exact prompt + expected behavior anchored to verified-cycle observations. | Step 5 of the original Implementation Steps is now complete. Scenario file is the canonical manual regression checklist for any future change to `commands/run.md` / `skills/bakeoff/SKILL.md` `## Drafting Invariants` section. |
| Coverage-gap batch (D7, B trial 2, E) | ✅ STRONG RESULTS (2026-05-20T18:45Z) | n=3 | **D7 multi-lens: 4× wall reduction** (132 s → 32 s) with zero CLI probing (vs 7 sequential pre-cycle). R5 + embedded skeleton load-bearing verified. Model also cross-reasoned task-fit + multi-lens, rejecting the docs-only working tree. **B drafting trial 2: 52 s, R4 pre-preview validate FIRED**, canonical schema. R3 + R4 both held. R4 rate now 2/5 = 40% (up from 1/4 = 25%). **E: 0 context calls** — the R1.4 anti-synthesis example "'the conventional test command for `<package>`'" matched the prompt verbatim, model asked for the verifier instead of exploring. E's original design is now obsolete (prompt template tips over R1, so batched-exploration on a real fact-lookup needs a new prompt). | Three load-bearing gaps closed. R5 verified on its load-bearing case (D7). R4 trending positive (40%). E findings stronger than design intent (R1 anti-synthesis preempts exploration). The cycle's R1/R2/R3/R5 claims are now triple-verified on the prompts most likely to exercise them. |
| **REMAINING GAPS** (corroboration only) | ⚠️ DEFERRED (2026-05-20T18:45Z) | — | After the coverage-gap batch, remaining gaps are: **D3** (compare-matrix routing) — contaminated trial only; type-inference logic wasn't changed by amendments. **D4** (vague target task-fit) — same. **D6** (unbounded review task-fit) — same. **C1/C2** (held-out positive variants) — never run. **B drafting trial 3** — n=2 now; one more would give n=3 median. **E with a non-anti-synthesis prompt** — original E prompt tips over R1, would need a new prompt design (sketched in experiment log). | None blocking ship. Documented in `docs/task-fit-test-scenarios.md` as expected behaviors with prompt+outcome rows even where not n=3 verified. Future light-touch dogfood could close these if anyone wants tighter confidence intervals. |

Update protocol: every experiment must update this table when it lands,
and fold its verdict into the relevant plan sections (Observed Cost,
Risks, Open Questions, Acceptance Criteria) before the next experiment
begins. The plan tracks empirical state, not just intent.

## 2026-05-20 Experiment Cycle Summary

This is the authoritative read after the plugin-cache contamination
correction. Earlier rows in the empirical table remain useful lab history, but
the clean-cache batches decide what ships.

Detailed timing data and per-trial notes live in
[drafting-fast-path-experiment-log-2026-05-20.md](drafting-fast-path-experiment-log-2026-05-20.md).

### Final Findings

| Area | Final evidence | Decision |
| --- | --- | --- |
| Baseline | A measured 25.5 s / 31.9 s median / 51.6 s max. | The 10-minute anecdote is a high-water dogfood, not the baseline. |
| Preflight | G measured 17 ms median. | Do not cache preflight in this PR. |
| R1 missing-field synthesis | Clean final-contract prompts landed at 100% on tested shapes: D1 3/3, D5 3/3, D2-with-R1.6 3/3, plus D8/D10 corroboration. | Ship advisory guidance plus the mechanical checklist and R1.6 refactor edge-case item. Do not build a Go-side synthesis linter. |
| R2 no Write before approval | 19/19 clean trials had no pre-approval mutating tool call. | Hard invariant. |
| R3 canonical build skeleton | 5/5 clean drafting-positive trials used canonical schema when drafting happened. | Hard invariant for build drafts; strict-must wording is justified. |
| R4 pre-preview validate | 2/5 clean drafting-positive trials visibly ran pre-preview validate. | Advisory only; post-write `bakeoff validate` remains the enforced safety gate. |
| R5 embedded backends/no CLI probing | 19/19 clean trials avoided CLI schema/backend probing; D7 improved from 132 s and 7 probes to 32 s and zero probes. | Hard invariant and the strongest wall-time win. |
| B positive target | Clean B trials were 40 s and 52 s, canonical schema, no pre-approval Write; one trial fired R4. | Reliability improved and wall time stayed inside A's baseline envelope. The original ≤ 30 s target is deferred. |
| E batched exploration | The original E prompt now trips R1.4 ("conventional test command") and asks with zero context calls. | Original E is obsolete; true fact-lookup batching needs a new prompt and is deferred. |

### What Ships

The first docs/contract PR stays build-focused:

- R2: no `Write`, `Edit`, or file-mutating call before approval.
- R3: canonical **build** skeleton copied verbatim, with AC carried in
  `background[]`, `providers[].backend`, nested `build.verify[].argv`,
  full budgets, and no fictional fields.
- R5: embedded backend/schema facts; no drafting-time CLI probing.
- R1: advisory required-field guidance, mechanical checklist,
  anti-synthesis examples, and the load-bearing R1.6 refactor checklist
  item. It is prompt-enforced on tested shapes, but not a Go-side semantic
  gate.
- R4: advisory pre-preview validate. Skipping it is acceptable when the
  enforced post-write `bakeoff validate` still runs before provider
  execution.

### Deferred

- C1/C2 held-out positive variants and a third post-amendment B timing trial
  for tighter confidence intervals.
- A redesigned E prompt that requires one real local fact lookup without
  matching an R1 anti-synthesis example.
- Go-side pre-preview validate hook, only if real use shows the
  repair-and-reapprove cycle is frequent or confusing.
- Go-side synthesis linter, unless telemetry shows synthesized AC/verifiers
  causing "solved the wrong thing" runs.
- Contract slimming / conditional-trigger trimming, because current evidence
  does not justify another wording refactor in the first PR.

## Implementation Lessons Learned (2026-05-20)

These are the changes the experiment cycle proved are load-bearing,
plus the implementation details that would have been wrong without
the cycle's data. Future revisions of this plan or related work
should treat these as standing observations.

### 1. Plugin-cache pinning is the methodology pitfall

The Claude Code plugin system reads contract files (`commands/run.md`,
`skills/bakeoff/SKILL.md`, `bakeoff/CLAUDE.md`) from
`~/.claude/plugins/cache/<org>/<plugin>/<sha>/`, **not from the
marketplace source tree**. Source edits do not take effect in fresh
sessions until: (a) the source is committed and pushed; (b) Claude
Code's plugin manager re-caches via `/plugin` + `/reload-plugins`;
and (c) `installed_plugins.json`'s `gitCommitSha` matches the
intended commit.

Any future drafting-contract dogfood must include this checklist
**before** running fresh-session trials:

```sh
# 1. Edit source
# 2. Commit + push
# 3. /plugin → update bakeoff
# 4. /reload-plugins
# 5. Verify:
python3 -c "
import json
d = json.load(open('/Users/mstefanko/.claude/plugins/installed_plugins.json'))
def w(o):
    if isinstance(o, dict):
        if 'installPath' in o and 'bakeoff' in o.get('installPath',''): return o
        for v in o.values():
            r = w(v)
            if r: return r
    elif isinstance(o, list):
        for v in o:
            r = w(v)
            if r: return r
e = w(d)
print('pin:', e['gitCommitSha'])
print('grep test:', open(e['installPath']+'/commands/run.md').read().count('<distinctive amendment phrase>'))
"
# expect pin == source HEAD and grep test >= 1
# 6. Only then run fresh-session trials
```

Skipping this checklist cost the cycle 16 trials of contaminated
data (4 batches over ~6 hours of operator time) measuring the
pre-cycle baseline contract while believing they measured the
amendments. Recovery required 12 clean trials over ~1 hour after
the methodology bug was identified.

### 2. R1 advisory wording lands; "must" wording is not required

The verification cycle showed R1 lands at 100% on tested prompts
even with **"should prefer asking"** rather than **"must ask"**.
Three contract amendments under contamination (R1, R1.1-R1.4,
R1.5 mandatory output marker) all landed at 0/9 *because the
contract was never read*; once read, even the softest "should"
wording produced the asking behavior. Strict-must wording is not
required for R1 and would not improve it.

Implication: future contract additions for behaviors the model
should perform should default to "should" wording with concrete
examples (anti-synthesis patterns, checklist items), not "must"
wording. The examples and checklist do more work than the modal
verb.

### 3. The mechanical pre-flight checklist is what the model cites

Across multiple verification trials, the model named the
Mechanical Pre-Flight Checklist verbatim — not the surrounding
R1 prose — as the reason for asking instead of synthesizing.
Example trial output: *"Assessing the request against the
mechanical pre-flight checklist: [✗] Acceptance criteria named as
observable behaviors — only the goal, scope, and verifier are
stated."*

Implication: structured checklists with `[ ]` / `[✓]` / `[✗]`
format are the highest-density contract element the model
internalizes. Future invariant additions should prefer this
structure over free-form prose where possible.

### 4. Refactor framing overrides general anti-synthesis examples

R1.6's "load-bearing refactor edge case" was necessary because the
general Anti-Synthesis Patterns (with "no behavior change" listed
as an example to avoid) did not stop the model from
synthesizing exactly that AC on refactor prompts. The model would
walk the checklist, identify AC as missing, and **still synthesize**
because the refactor verb ("extract", "consolidate") carries an
implicit "no behavior change" intent.

Closing the gap required:
- A specific checklist item for refactor/extract/consolidate/split
  asking for behavioral invariants verbatim.
- A "**Refactor edge case (load-bearing)**" callout that explicitly
  notes "the refactor framing tends to override the example".
- Naming the workaround in the callout: ask for specific test
  files, API contracts, exit-code mappings, byte-equality
  conditions, round-trip equalities.

Implication: when an anti-synthesis pattern is also implicit in
the task's verb, the contract needs a verb-specific override.
Generic examples are necessary but not sufficient.

### 5. R3 canonical skeleton lands 100% — but only as strict-must

The C+ demotion of R3 to Advisory ("should copy verbatim") was
based on contaminated data showing ~33%. The actual rate against
the loaded contract was 100% at strict-must. Reverting C+ on R3
was the right call.

Implication for schema-shaped invariants: where there is a single
canonical structure (JSON schema, field names, enum values),
strict-must wording with a verbatim example block is the right
contract shape. The Examples-of-Drift list ("`providers[].kind` →
use `providers[].backend`", etc.) is what the model uses to
diagnose its own near-misses.

### 6. R4 pre-preview validate is fundamentally advisory

R4's pre-preview validate ran in 1/3 of the first clean drafting
trials and 2/5 by cycle close. That is useful when it fires, but not
reliable enough to treat as a hard contract invariant. The model treats
it as an optional extra check on fast-path trips.

Implication: any further work to enforce pre-preview validate
needs a Go-side hook (Option B-narrow), not a contract change.
The current state (advisory + Go-side post-write validate
backstop) is the stable answer.

### 7. Background-as-array carries acceptance criteria

The plan originally treated `background` as freeform string. The
verification trials showed the model naturally writes
`background: [...]` arrays carrying AC bullets, the
"Bakeoff will capture candidate patches" boilerplate, and other
context. This works correctly with `bakeoff validate` (which
accepts either string or string-array).

Implication: the canonical skeleton documents `background` as an
array. The skeleton entry `"background": ["<acceptance criteria
as one or more bullets within this array>", "Bakeoff will capture
candidate patches from isolated worktrees and will not apply them
to this checkout."]` is the right shape.

### 8. Default-aware preview language is welcomed by the model

The verification trials showed the model voluntarily including
default-aware notes in the compact preview (e.g., "(with
`build.protected_paths` not set — scope guidance lives in
background)"). This was not strictly mandated by the contract.

Implication: the Step 3 "preview defaults wording" goal was met
informally — the model naturally surfaces non-default values and
notes about omitted optional fields. Step 3 does not need a
strict-must rule.

### 9. Wall-time impact of contract bloat is modest

The amended contract is 927 lines vs 669 lines baseline (+258
lines of invariants + skeleton + checklists + anti-synthesis
examples). Clean B drafting metric trials against the post-amendment
contract clocked 40 s and 52 s — effectively within A's baseline range
(31.9 s median / 51.6 s max). The contract additions did not
materially regress speed.

Implication: the assumption that "more contract → slower drafting"
is not strongly supported by the data. The ≤ 30 s wall target
from the original cycle goal is not yet hit on a single trial,
but the larger contract is not the regression force.

### 10. R5 + embedded skeleton are the highest-impact amendment by wall-time

The coverage-gap batch on 2026-05-20T18:45Z showed D7 (multi-lens)
running **4× faster** under the amended contract: 132 s → 32 s.
Pre-cycle, the model spent ~90 s probing `bakeoff providers list`
(doesn't exist), `bakeoff --help`, `bakeoff init`, scratch `/tmp`
`bakeoff init` to read field names by example, and `bakeoff
doctor`. Post-cycle: zero CLI probes; the embedded backends list
and canonical skeleton are enough.

R5's "do not probe the CLI" rule combined with the embedded
backends + skeleton is the single most impactful contract change
in the cycle by wall-time delta. The cost of writing these into
the contract was ~150 lines; the benefit is consistently ~100 s
per multi-lens-shaped draft.

Implication: future contract additions that embed reference content
(field lists, enum values, structural schemas) have an attractive
ROI compared to prose-only rules. The model uses the embedded
content directly and avoids improvising lookups.

### 11. R1 anti-synthesis examples can preempt exploration entirely

The E batched-exploration trial showed an unexpected effect: the
R1.4 anti-synthesis example *"'the conventional test command for
`<package>`' (ambiguous; ask)"* matched the E prompt's wording
verbatim. The model recognized the pattern and asked for the
verifier without exploring at all — zero context calls.

This means the cycle's documented "batched exploration" claim
(exactly one context pass for prompts requiring one fact-lookup)
is **not separately verified**. The prompt designed to test it
now tips over R1 first.

Implication: the R1 anti-synthesis examples are more powerful than
the rule's "ask, don't synthesize" framing suggested. They function
as **pattern recognizers** that fire before exploration even
begins. Future tests of batched exploration need prompts that don't
match any anti-synthesis pattern.

Documented example for future testing (not run this cycle):

```
... Gate verifier: go test ./internal/commands/lscmd/... -count=1.
Before drafting, look up whether internal/commands/lscmd/ uses
table-driven tests or function-per-case tests so the work order
can name the test style in the background. ...
```

That phrasing requires a real fact-lookup but does not match any
of the anti-synthesis examples.

### 12. R4 may be quietly recovering — keep watching

R4's landing rate at cycle close was 1/4 = 25%. After the
coverage-gap batch added one more drafting trial where R4 fired,
the rate is 2/5 = 40%. Still below "reliable" but the trend is
positive. With more sampling under the amended contract, R4 may
land somewhere in the 30-50% range without further intervention.

Implication: the Go-side pre-preview validate hook (Option
B-narrow) remains deferred. If a future light-touch dogfood
shows R4 lands at ≥ 50% consistently, the hook becomes
unnecessary. If real-use signal shows operators hitting the
repair-and-reapprove cycle frequently, escalate to the hook.

### 13. Open verification gaps (acknowledged, narrowed)

After the 2026-05-20T18:45Z coverage-gap batch, the remaining
plan-defined experiments not run against the post-amendment cache
are:

- **D3** (compare-matrix routing): contaminated trial only. Type-
  inference logic wasn't changed by amendments; high probability
  of identical behavior.
- **D4** (vague target task-fit): contaminated trial only. Task-fit
  logic wasn't changed.
- **D6** (unbounded review task-fit): contaminated trial only.
  Task-fit logic wasn't changed.
- **B drafting trial 3**: n=2 currently (40 s, 52 s). One more
  would give n=3 with proper median; wall distribution is
  already known to be in the 40-50 s band.
- **C1/C2** held-out positive variants: never run.
- **E with a new prompt**: original E prompt is now obsolete (see
  observation 11).

D7 was the load-bearing verification for R5 and is answered. The
original E prompt answered a stronger anti-synthesis question but did
not verify true fact-lookup batching; redesigned E remains deferred.
The remaining gaps are corroboration. Documented in
`docs/task-fit-test-scenarios.md` as expected behaviors with
prompt+outcome rows.

## Non-Goals

Do not change these invariants:

- Do not skip `/bakeoff:run` CLI preflight.
- Do not skip explicit user approval before writing or running a natural
  language draft.
- Do not skip `bakeoff validate` before `bakeoff build` or `bakeoff research`.
- Do not let natural-language drafting mutate source files.
- Do not move provider execution, judging, baseline verification, patch
  capture, artifact writing, ledger semantics, or exit-code semantics out of
  the Go CLI.
- Do not add a broad natural-language drafting engine to the Go CLI in this
  pass.
- Do not add a batch work-order schema, a DAG runner, or hidden synthesis.
- Do not reduce review triage, build baseline verification, protected-path
  enforcement, or scope enforcement during actual runs.

This is a drafting-phase optimization only. Completed work orders should still
be normal Bakeoff work orders and should run through the same CLI validation
and execution path as today.

## Current State

`/bakeoff:run` currently does the right safety work, but the natural-language
contract encourages cautious re-evaluation on every invocation.

Relevant current contracts:

- `commands/run.md` mandates `scripts/bakeoff-ensure-cli --check` before any
  draft or run, and routes existing work-order paths through validation.
- Natural-language input runs task-fit checks, split checks, multi-lens review
  checks, type inference, missing-field checks, preview rendering, approval,
  file writing, validation, and then execution.
- `skills/bakeoff/SKILL.md` duplicates much of the natural-language drafting
  contract and the work-order default values.
- Generated drafts must be clean JSON, not TODO init templates.
- Build drafts require `build.base_ref`, a non-empty verifier suite with at
  least one gate verifier, build-only `codebase` providers, and the default
  build budgets unless the user overrides them.
- Go validation in `internal/workorder/workorder.go` remains the structural
  source of truth after the draft is written.
- Build execution in `internal/commands/buildcmd/run.go` still performs
  repository resolution, run-id validation, baseline worktree setup, baseline
  verifier execution, provider worktree setup, provider execution, patch
  capture, provider verification, and final artifacts.

The slow phase is therefore mostly above the Go CLI: the model reloads a large
branching contract, then often performs cautious repo exploration even when the
request already contains enough information to draft safely.

## Observed Drafting Cost Pattern

The attached dogfood post-mortem called out four sequential tool round-trips
before preview:

1. `bakeoff-ensure-cli --check` preflight.
2. Repository/branch/file listing context.
3. Search for command/package layout.
4. Redundant file existence/line-count checks.

Only the preflight is contract-mandated. The others are useful when scope,
package, route, verifier, or target files are ambiguous; they are marginal for
a request that already supplies a target scope, acceptance criteria, and
verifier.

The bigger cost is not shell execution. Each extra exploration step creates a
new model turn, and the model repeatedly considers task-fit, split, multi-lens,
mode-routing, preview, approval, and validation rules.

**Empirical update (2026-05-20, Experiment G).** Step 1 — preflight — costs
~17 ms median on a warm cache with `dist/bakeoff` prebuilt. Effectively
zero against the 2-3 minute target. The contract should not treat preflight
as a cost driver; the remaining wall time is the model's drafting and
exploration turns, not shell execution.

## Recommended Design

Add a strict fast path for obvious one-work-order natural-language drafts, then
fall back to the current careful path whenever anything important is unclear.

The fast path should still produce a normal work order, show the normal preview,
wait for normal approval, write a normal `*.work-order.json` file, run normal
`bakeoff validate`, and then run normal `bakeoff build` or
`bakeoff research`.

### Fast-Path Predicate

The v1 fast path may trigger only for build-mode drafts when all of these are
true:

1. The request clearly maps to exactly one build work order.
2. The user clearly authorizes code-editing provider work.
3. Required build fields are present: implementation goal, acceptance criteria,
   at least one gate verifier, and base ref if not `HEAD`.
4. The request names an edit boundary:
   - explicit file, directory, package, route, command, module, branch, PR,
     diff, or local-change scope.
5. The verifier command is explicit enough to copy into the work order without
   guessing.
6. No requested split, multi-lens review, broad synthesis, or sequential plan
   is present.
7. No metric verifier, protected verifier fixture, benchmark harness, golden
   file, or generated expected-output artifact requires path discovery.
8. No mode-specific flag conflict is present.
9. The request does not mention external web research for a build work order.

For `ls-order-by-finished-at`, the predicate should pass.
Review, research, analyze, and compare drafts remain on the careful path in
this PR even when their target is bounded.

### Fast-Path Action

When the predicate passes:

1. Run the mandatory CLI preflight.
2. Parse flags and mode.
3. Build the work-order draft from the supplied user text plus defaults.
4. Do not perform repo exploration unless the supplied target/verifier cannot
   be rendered without it.
5. Show the compact preview.
6. Wait for the same approval phrase as the current one-work-order flow.
7. Write the file, validate, and run normally.

The preview should state when defaults are used rather than expanding all
default details inline:

- providers: default build pair, unless changed;
- judge: default judge, unless changed;
- budget: default build or research budget, unless changed;
- scope policy: default `best_effort`, unless changed.

Full JSON remains available with `show`.

## Fallback Rules

The fast path must not trigger when the request is incomplete or ambiguous.
Fall back to the existing careful flow or ask one question for:

- missing acceptance criteria for build mode;
- missing gate verifier for build mode;
- unclear edit boundary or package/route/file scope;
- uncertain type, especially "build a report/comparison" wording that may mean
  research rather than code-editing build mode;
- requested metric benchmark without clear metric command, direction, or
  protected measuring files;
- verifier commands that appear to depend on generated fixtures, snapshots,
  goldens, or harness files that providers must not edit;
- requested split or multi-lens review;
- review requests without bounded branch, PR, diff, file set, or local changes;
- analyze/RCA requests without a symptom, log, reproduction, trace, file set,
  incident, or command to inspect;
- path-like missing input;
- unknown flags or mode-specific flag conflicts;
- non-`HEAD` base ambiguity;
- build providers with `scope: web`;
- a request that would require secrets or provider auth material in the work
  order.

These fallback rules are the main protection against degrading runs where
acceptance criteria, package/routes, or verification are not clear.

## Batched Exploration Rule

When exploration is needed, require one batched context pass before preview
instead of multiple sequential shell/model turns.

Recommended command-contract wording:

```text
For natural-language drafting, if local context is needed before preview,
prefer one batched read/search pass that answers all drafting questions at
once. Do not run separate file-existence, branch, package-layout, and line-count
commands unless the first pass exposes a concrete blocker.
```

For this plugin's context-mode environment, that means using
`ctx_batch_execute` where available. In generic environments, the same idea can
be expressed as one grouped read/search step through the available tool.

Exploration should answer only drafting questions:

- Does the target path/package named by the user plausibly exist?
- Is there an obvious verifier package or test path?
- Is there a protected verifier fixture or metric harness to list?
- Is a review diff/base requested and bounded?

Exploration should not become a substitute for the providers' investigation.

## Template And Substitution Strategy

Default templates with substitution are useful, but they are a secondary lever.
They reduce JSON construction and validation-repair risk; they do not by
themselves remove the slow model turns spent re-reading and interpreting the
drafting contract.

Recommended approach:

1. Add clean draft skeletons or helper text for natural-language drafts.
2. Keep `bakeoff init` templates as human starter templates with TODO
   placeholders.
3. Do not use TODO init templates for generated drafts.
4. Keep defaults in one place in the plugin instructions, or move toward a
   generated defaults block if this duplication keeps causing drift.
5. Substitute only values that are present or safely defaulted:
   - `id`;
   - `type`;
   - `goal`;
   - `background`;
   - default providers;
   - default judge;
   - default budgets;
   - default `scope_policy`;
   - build `base_ref`;
   - build verifier commands supplied by the user.
6. Do not synthesize missing acceptance criteria, missing verifier commands, or
   protected paths from a template.

Expected impact: modest but worthwhile. It should make fast-path drafts more
mechanical and less error-prone, but the noticeable wall-clock gain comes from
the fast-path predicate plus fewer exploration turns.

## Contract Slimming

The command and skill contracts currently repeat large chunks of the same
rules. Slimming them should improve model latency and reduce contradictory
interpretation.

Recommended cleanup:

1. Keep non-negotiable safety rules prominent:
   - preflight first;
   - existing paths validate and route by type;
   - natural-language drafts require approval;
   - validate before run;
   - do not satisfy the user task inline;
   - do not call provider CLIs directly;
   - do not apply or synthesize patches after build handoff.
2. Move repeated default tables into one section.
3. Put split and multi-lens rules behind clear trigger headings.
4. Put one-work-order fast-path rules before deep split/multi-lens details.
5. Keep detailed multi-lens summary requirements, but avoid making every normal
   build draft pay attention to them unless multi-lens triggers.

This should be a wording refactor, not a behavior reduction.

## Implementation Steps

Steps 1-5 ship as a single docs PR (no sequencing between them); they all edit
overlapping files (`commands/run.md`, `skills/bakeoff/SKILL.md`,
`docs/task-fit-test-scenarios.md`). Splitting them into separate PRs invites
merge conflicts on the same two files.

### Source Of Truth

`commands/run.md` is the canonical contract. `skills/bakeoff/SKILL.md` is a
mirror and must be updated in the same PR with the same wording. Diff-check
the two files before opening the PR; any drift is a review blocker. The
machine-readable-defaults open question is deferred to a follow-up plan.

### 1. Add Fast-Path Contract

Update `commands/run.md` and `skills/bakeoff/SKILL.md`:

- Insert the "Obvious One-Work-Order Fast Path" section immediately after the
  block beginning `For one-work-order drafting, infer the work-order shape
  silently unless the ambiguity changes safety or cost.` near
  `commands/run.md:474`. Rewrite that paragraph so it becomes the entry point
  to the fast path rather than an overlapping rule; the fast-path predicate
  below replaces the informal "infer silently" guidance.
- Define the strict predicate.
- Define the fast-path action.
- State explicitly that fast-path drafts still require preflight, preview,
  approval, write, validate, and normal execution.
- State explicitly that the fast-path uses the same approval phrase as the
  current single-work-order flow (`yes`, `y`, `approve`, or `run it`). Do
  not adopt the stricter `write and run` phrase from the split / multi-lens
  flows.
- State explicitly that unclear acceptance criteria, verifier, package/route,
  scope, base, metric, protected path, split, multi-lens, or mode conflicts
  fall back to the current careful flow.
- Limit the v1 fast path to build mode. Review, research, analyze, and
  compare requests continue through the current careful flow. Lifting that
  limit is a follow-up plan after Experiment B and D pass.

### 2. Add Batched Exploration Guidance

Update `commands/run.md`, `skills/bakeoff/SKILL.md`, and `bakeoff/CLAUDE.md`:

- Require a single batched context pass when exploration is necessary.
- Name the questions that pass should answer.
- Discourage redundant proof commands after the first pass.
- Preserve the ability to run more commands when the first pass exposes a real
  blocker.

### 3. Add Preview Defaults Wording

Update the one-work-order preview instructions:

- Allow default-aware preview lines.
- Show deviations from defaults explicitly.
- Keep `show` for full JSON.
- Keep the same approval phrase (`yes`, `y`, `approve`, or `run it`).

Default-state example:

```text
Providers: default build pair (claude sonnet high, codex gpt-5.5 high)
Judge: default claude opus xhigh
Budget: default build budget
Scope: best_effort, codebase providers
```

Deviation example (template the writer should mirror — non-default values
must appear inline, not behind a default label):

```text
Providers: claude opus xhigh, codex gpt-5.5 xhigh        (non-default models)
Judge: default claude opus xhigh
Budget: build, build_walltime_seconds 1800              (raised from default)
Scope: strict, codebase providers                        (non-default policy)
Base ref: main                                           (non-default)
Protected paths: testdata/golden/**                      (set; default empty)
```

### 4. Add Clean Draft Skeleton Guidance

Add a small generated-draft skeleton section for build mode. This can be purely
instructional at first; no Go code is required.

The skeleton should mirror the existing defaults:

- two providers;
- judge;
- build budget;
- `scope_policy.enforcement: "best_effort"`;
- `build.base_ref: "HEAD"` unless supplied;
- `build.verify` from the supplied gate verifier;
- `protected_paths: []` unless a protected metric/fixture path is clear.

Do not hardcode `build.patch_max_bytes` (or any other Go-side default) into
the skeleton. The Go CLI (`internal/workorder/workorder.go`) is the source of
truth for that value; doc skeletons that restate it will silently drift.
Omit the field from generated drafts and let validation fill in the default.

Do not call `bakeoff init` from the natural-language drafting flow.

### 5. Add Scenario Tests Or Checklist

Extend `docs/task-fit-test-scenarios.md`. That file currently contains a
single `## Checklist` heading and has room; do not start a new file. Add a
new top-level `## Fast-Path Drafting Scenarios` section underneath, with
positive and negative subsections.

Scenario rows must use the wording finalized in Step 1's predicate; this
step depends on Step 1 inside the same PR.

Wire-into-CI is out of scope for this PR. The scenarios are an inspectable
checklist, not an automated test suite.

Cover both positive and negative cases.

Fast path should trigger:

- narrow Go package build with explicit acceptance criteria and gate verifier;
- one-file or one-directory build change with explicit tests.

Careful path should continue to handle bounded review/research/analyze/compare
requests in this PR; do not treat them as fast-path positives until a separate
plan expands v1 beyond build mode.

Fast path should not trigger:

- build request with no verifier;
- build request with no acceptance criteria;
- request with unclear package/route/file scope;
- "build a comparison matrix" without code-edit intent;
- metric verifier with unclear protected measuring files;
- review request with no bounded target;
- multi-lens review request;
- clean split request;
- path-like missing input;
- unknown mode-specific flags.

The scenario docs should state expected behavior: fast preview, fallback
question, task-fit warning, split proposal, or normal existing-path route.

### 6. R1 — Required-Field Guidance + R1.6 Refactor Tightening

Motivated by D1, D2, D5, and the later D2 refactor soft spot. The final
contract does **not** use a Go-side synthesis gate and does **not** rely on
mandatory output markers. It ships prompt guidance that proved effective once
the plugin cache actually loaded it.

Files to edit:

- `commands/run.md` — keep R1 inside `## Drafting Invariants` so it applies to
  fast path, careful path, split, and multi-lens drafting.
- `skills/bakeoff/SKILL.md` — mirror the same wording and keep the command file
  as the canonical reference.

Final contract shape:

- Header: `### Required-Field Synthesis Guidance (Advisory)`.
- Mechanical pre-flight checklist with explicit yes/no questions for verifier,
  acceptance criteria, edit boundary, benchmark protected paths, and
  refactor/extract behavioral invariants.
- Anti-synthesis examples for fake AC and fake verifier commands.
- R1.6 refactor callout: refactor/extract/consolidate/split prompts must name
  the behavioral invariants to preserve; implicit "no behavior change" is not
  enough.

Verification: D1 3/3 (missing verifier), D5 3/3 (metric protected paths), and
D2-with-R1.6 3/3 (refactor missing invariants) ask instead of drafting under
the final loaded contract. D8 and D10 corroborate stacked routing/missing-field
behavior. A synthesized field on an untested shape is a preview-review problem,
not a structural schema failure.

### 7. R2 — No Write Before Approval (Amendment to Step 1)

Motivated by A Trial 2 (`d640a43b`) and B image 3 (2026-05-20). The
current contract assumes preview → approval → write order but does
not state it as an invariant. Add an unconditional clause.

Files to edit:

- `commands/run.md` — insert near the approval-block instructions.
- `skills/bakeoff/SKILL.md` — same wording mirrored.

Wording to add (exact text):

```text
No `Write`, `Edit`, or file-mutating tool call may precede the
approval prompt. The preview is read-only. The first mutating tool
call must come *after* the user's affirmative reply. This applies to
fast path and careful path equally.
```

Verification: every B and C trial transcript inspected for `Write`
tool calls preceding the approval line. Zero pre-approval `Write`
calls = PASS.

### 8. R3 — Embed Canonical Build Skeleton (Amendment to Step 4)

Motivated by image 3 schema-drift (2026-05-20). Iterative-validate
audit established 13 distinct repairs needed. Prose-only defaults are
insufficient: 5 of 13 errors were invalid field names (`kind`/`role`/
`gates`/`acceptance_criteria`/`scope`). Embedding a verbatim valid
JSON skeleton with placeholders is the only fix.

Files to edit:

- `skills/bakeoff/SKILL.md` — add a `### Canonical Build Skeleton`
  subsection under `## Drafting Rules`.
- `commands/run.md` — mirror the same skeleton block near the
  natural-language drafting section.

Skeleton content (valid against the v1 schema; placeholders use
angle brackets):

```json
{
  "schema_version": 1,
  "id": "<kebab-id>",
  "type": "build",
  "goal": "<one-sentence implementation goal>",
  "background": [
    "<acceptance criteria as one or more bullets within this array>",
    "Bakeoff will capture candidate patches from isolated worktrees and will not apply them to this checkout."
  ],
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "scope_policy": { "enforcement": "best_effort" },
  "judge": { "backend": "claude", "model": "opus", "effort": "xhigh" },
  "build": {
    "base_ref": "HEAD",
    "comparison_goal": "Prefer the patch that satisfies the acceptance criteria with the smallest maintainable change.",
    "verify": [
      {
        "id": "<verifier-id>",
        "kind": "gate",
        "argv": ["sh", "-c", "<verifier-command>"],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  },
  "budgets": {
    "wall_clock_seconds": 1200,
    "max_output_bytes": 80000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 80000
  }
}
```

Rule wording (exact text):

```text
The model **must** copy field names and structure verbatim from the
canonical skeleton. Inventing or renaming fields (e.g., `kind` instead
of `backend`, `role` on providers, top-level `gates` or
`acceptance_criteria`) is a contract failure. Substitute only the
angle-bracket placeholders; do not omit other fields and do not add
fields not in the skeleton. Repeat the skeleton verbatim if you are
unsure of a default — defaults belong in this skeleton, not in your
working memory.
```

Do **not** expand the first PR into full gather/review/compare skeleton work.
The v1 fast path is build-only, and the clean evidence only proves the build
skeleton. Keep the gather/review/compare references as careful-path examples;
write exact skeletons for those modes in a follow-up if a later plan expands
the fast path beyond build.

### 9. R4 — Pre-Preview Internal Validate (Advisory)

Motivated by image 3 schema-drift (2026-05-20). Pre-preview validation improves
preview quality when the model performs it, but clean dogfood only showed it
landing in 2/5 drafting-positive trials. It therefore ships as advisory
guidance, not a first-PR hard gate.

Files to edit:

- `commands/run.md` — modify the drafting-flow ordering near the
  "show the compact preview" line.
- `skills/bakeoff/SKILL.md` — mirror.

Recommended flow:

```text
After building the work-order JSON in memory:

1. Prefer internally invoking `bakeoff validate <path>` against the in-memory
   JSON (write to a temp file if needed).
2. If validation fails, repair the JSON using the canonical skeleton
   and re-validate. Repeat until validation passes.
3. **Then** show the compact preview to the user.
4. Wait for approval.
5. Write the file to the working directory.
6. Run `bakeoff validate` against the final on-disk file (audit
   redundancy is intentional — proves the on-disk file matches what
   the user approved).
7. Run `bakeoff build` or `bakeoff research`.
```

Acceptance: pre-preview validation firing is a positive signal but not a
blocker. The enforced gate is step 6: post-write `bakeoff validate` must run
before `bakeoff build` or `bakeoff research`. If step 1 is skipped and step 6
catches schema drift, the flow must repair and re-preview before provider
execution.

### 10. R5 — Embed Backends List (Amendment to Step 2)

Motivated by D7 multi-lens drafting (2026-05-20, image 11). The
model spent ~90 s improvising CLI probes (`bakeoff providers list`
errored, then `bakeoff --help`, `bakeoff init --help`, `/tmp`
scratch `bakeoff init`, `bakeoff doctor`) just to discover backends
and schema. Embed the answer.

Files to edit:

- `skills/bakeoff/SKILL.md` — add to the top of `## Drafting Rules`.
- `commands/run.md` — mirror.

Wording to add (exact text):

```text
Available provider backends: `claude` (Claude Code), `codex`
(Codex CLI). Available judge backends: `claude`. The model **must
not** probe the CLI to discover backends. The following commands
are **not** drafting-time discovery tools and must not be run from
the drafting flow:

- `bakeoff providers list` (does not exist);
- `bakeoff --help` (slow; canonical info is in this skill);
- `bakeoff init` (writes a TODO template; never run from drafting);
- `bakeoff doctor` (operator-only diagnostic; not for drafts);
- scratch `mkdir /tmp/...` followed by `bakeoff init` (forbidden).

If the user names an unknown backend, ask one clarification
question, do not improvise.
```

Verification: re-run D7 (multi-lens) in a fresh session after the
amendment lands. Expected: zero `bakeoff providers list / --help /
init / doctor` calls from the drafting flow. Wall time for multi-lens
drafting should drop from ~2 m 12 s to ~45-60 s.

### 11. Run Defined Drafting Experiments

Run the experiments in the "Experiment Protocol" section before declaring the
contract change successful.

The experiments should answer four questions:

1. Does the target narrow build reach preview faster?
2. Does the fast path avoid unnecessary exploration without skipping preflight,
   approval, or validation?
3. Does the fast path correctly refuse ambiguous, underspecified, split, or
   metric-sensitive requests?
4. Do draft skeletons/default-aware previews reduce draft friction without
   hiding important deviations?

Record results in a small experiment log, either appended to this plan or in a
new `docs/drafting-fast-path-experiment-log-YYYY-MM-DD.md` file. Each row
should include prompt id, expected route, actual route, pre-preview model
turns, pre-preview tool calls, pre-preview wall time, validation result when
checked, and notes.

## Experiment Protocol

These experiments measure the drafting phase, not provider implementation
quality. Provider runs are already useful; the question is whether Bakeoff can
reach a correct, validated work-order preview faster and with fewer avoidable
turns.

### Recommended Run Order

Run experiments in this order; the listed sequence (A through G) below is for
reference only, not for execution:

1. **G — Preflight Cost Check.** Cheap, self-contained, parallelizable. Runs
   independently of the contract change. Establishes whether preflight is a
   meaningful fraction of the drafting budget before any other experiment
   interprets its wall-time numbers.
2. **A — Baseline The Current Flow.** Must complete before B/C/E/F because
   each of those interprets results against the baseline. The "10 minute"
   anecdote in the goal section is a single dogfood data point, not a
   measured baseline.
3. **D — Negative Guardrail Matrix.** No provider spend and no approval, so
   safe to run before any positive case. Confirms the fast path is not
   permissive on prompts it should refuse.
4. **B — Fast Path Positive Target.** The motivating case. Run only after D
   passes; otherwise a permissive fast path could trigger a real provider run.
5. **C — Fast Path Positive Variants.** Confirms B was not an overfit case.
6. **E — Batched Exploration.** Exercises the fallback rule.
7. **F — Template And Default Preview Impact.** Requires before/after pairs;
   defer to a follow-up PR if the first PR ships all docs changes together.

### Shared Measurement Rules

Use the same measurement rules for every experiment:

- Start the timer when `/bakeoff:run` is invoked.
- Stop the timer when the first approval-ready preview is shown, or when the
  command correctly stops with a warning/clarifying question.
- Wall time uses the operator's transcript timestamps (start of the user
  message that contains `/bakeoff:run`, and the timestamp on the first
  preview / question / warning assistant message). Report to the nearest
  whole second. Do not eyeball with a stopwatch.
- Count model turns and tool calls from the transcript using the
  instrumentation helper (see below). Two operators counting by hand will
  diverge.
- Record whether mandatory preflight ran.
- Record whether local repo exploration ran and why.
- Record whether the preview includes all required route information:
  work-order id, type, file path, providers or default-provider label, judge or
  default-judge label, budget or default-budget label, scope policy, goal,
  background summary, verifier summary, and command.
- For positive draft cases, request `show` or otherwise inspect the proposed
  JSON before approving a spendful provider run.
- Validate shown or written JSON with `bakeoff validate` when possible. A
  validation-only check is enough for most experiments; a full provider run is
  required only where the experiment says so.
- Do not count provider execution time in drafting-phase metrics.

**Repetition policy.** LLM drafting is non-deterministic and one trial can
land anywhere in the run-to-run variance band. Run every prompt **three
times** (n=3) in fresh transcripts and report the median plus the
minimum/maximum for wall time, model turns, and tool calls. A single-trial
result counts as exploratory data only.

**Environment pinning.** Record per-run: Claude model version, plugin git
SHA, active plugin-cache SHA, working-tree `git status` summary, and whether
`bakeoff/MEMORY.md` is loaded. Before any fresh-session batch that tests
contract wording, run `/plugin` + `/reload-plugins`, then verify
`installed_plugins.json` points at the intended source commit and grep the
cache for a distinctive amendment phrase. Mismatches across trials invalidate
the comparison.

**Instrumentation helper.** Before running A, write a small transcript-parse
script (Python or shell) that, given a Claude Code transcript file, prints
`turns_pre_preview`, `tool_calls_pre_preview`, and `wall_seconds_pre_preview`.
Park it at `scripts/measure-drafting.py` (or similar). Every experiment uses
the same helper so counts are comparable across operators. This is a
prerequisite for A; if the helper is not written, A's numbers cannot be
trusted.

Use these thresholds, calibrated against Experiment A (measured baseline of
n=3 trials on the canonical narrow build prompt):

- **Baseline (measured 2026-05-20):** median 31.9 s, min 25.5 s, max 51.6 s
  wall time; median 6 turns; median 2 tool calls; max 6 tool calls.
- **Fast-path wall time:** narrow build preview should remain inside A's
  measured envelope (max 51.6 s) unless a regression is explained by a
  reliability gain. The original ≤ 30 s target is retained as an aspirational
  follow-up target, not a first-PR ship gate. Median improvement is a non-goal.
- **Pre-preview tool calls:** preflight plus at most one batched context
  pass (≤ 2 total). Zero context passes is acceptable when all fields are
  supplied. **Trial 3's 6 tool calls is the regression line — the fast path
  must make that impossible.**
- **Pre-preview model turns:** ≤ 6 for fast-path-eligible prompts (A's
  median; the fast path must not raise it).
- **Validation repair rate** for fast-path positive drafts: zero provider runs
  launch before post-write validation passes. Pre-preview repairs are welcome
  but not mandatory.
- **False-positive fast-path rate on negative cases:** zero. Any ambiguous
  prompt that fast-paths is a failure.

The 10-minute baseline in the original plan draft is **superseded** by the
A measurement; the 2-3 minute and 50%-reduction targets are obsolete.

### Experiment A: Baseline The Current Flow

What this tests: the current cost and behavior before the fast-path contract is
implemented.

Prompt: use the exact `ls-order-by-finished-at` request text already quoted
in Experiment B below. (Re-quoted there for self-containment; A and B share
the same prompt by design — B's "did the fast path help" claim is meaningful
only if A measures the same input.) A's run uses the unmodified contract
(check out the pre-PR commit or stash uncommitted contract edits before
running).

How to test:

1. Confirm the working tree is on the pre-PR contract (no fast-path section
   in `commands/run.md`). Record the git SHA.
2. Open a fresh Claude Code session with no prior bakeoff conversation in
   context. Disable or rename `bakeoff/MEMORY.md` for the trial if it
   contains drafting hints.
3. Invoke `/bakeoff:run` with the shared prompt.
4. Stop measurement at the first approval-ready preview (do not approve).
5. Run the instrumentation helper against the transcript to record preflight,
   tool calls, model turns, and wall seconds.
6. Repeat three times in fresh sessions. Report median, min, and max.

Success means this establishes a believable baseline: three trials agree
within roughly a factor of two on wall time, and all three reach an
approval-ready preview. It is not expected to be fast.

Failure means the baseline is not comparable: extra cached context, prompt
drift, an unrecorded SHA, or wide trial-to-trial variance. Re-run.

### Experiment B: Fast Path Positive Target

What this tests: the strict fast path triggers for the motivating case and
does not degrade the work-order contract.

Prompt:

```text
Order bakeoff ls output by finished_at descending; stable, deterministic
fallback for legacy/malformed runs missing or with unparsable finished_at; add
focused unit tests for the ordering function. Scope: edit only
internal/commands/lscmd/**. Acceptance criteria: newest-first by finished_at;
missing/unparsable finished_at after well-formed runs; deterministic secondary
key by run id; tests cover happy path, missing finished_at, unparsable
finished_at, and ties by run id. Gate verifier: go build ./... && go test
./internal/commands/lscmd/... -run . -count=1. Use two build providers
(claude-code and codex) and one claude judge.
```

How to test:

1. Run `/bakeoff:run <prompt>` after the fast-path contract change in a fresh
   session, three times in three fresh sessions. Report median, min, and max.
2. Confirm preflight runs.
3. Confirm no repo exploration occurs unless the draft cannot render the
   supplied scope or verifier without it.
4. Stop measurement at preview.
5. Inspect the JSON via `show` or the written file.
6. Validate the work order.
7. Run one full provider dogfood once, after the preview and validation pass
   on at least two of three trials. This step is signal, not metric: the
   provider wall time is not part of the drafting measurement.

Success looks like:

- The flow goes from preflight to approval-ready preview without sequential
  repo probing on all three trials.
- Wall time stays within A's measured envelope (max 51.6 s) while preserving
  reliability. The original ≤ 30 s max target is a follow-up speed goal, not a
  first-PR blocker.
- **Pre-preview tool calls ≤ 2 on every trial** (preflight plus at most one
  batched context pass). A Trial 3's 6 tool calls is the regression line.
- Pre-preview model turns ≤ 6 on every trial.
- Pre-preview tool calls are preflight only, or preflight plus one justified
  batched context pass.
- The generated work order has `type: "build"`, build providers with
  `scope: "codebase"`, `scope_policy.enforcement: "best_effort"`,
  `build.base_ref: "HEAD"`, the supplied verifier, the supplied scope, and the
  supplied acceptance criteria.
- `bakeoff validate` passes without repair.
- The full provider dogfood, if run, follows the same `bakeoff build` semantics
  as before.

Failure looks like:

- The model performs multiple exploratory turns before preview.
- The draft omits acceptance criteria, scope, verifier, provider defaults,
  judge, budget, or approval instructions.
- The draft guesses a verifier or target path not supplied by the user.
- Post-write validation fails and provider execution would proceed anyway.
- The flow skips preflight, approval, or validation.

### Experiment C: Fast Path Positive Variants

What this tests: the predicate is not overfit to one `lscmd` prompt. The
`lscmd` motivating case was used while tuning the predicate; both prompts
below must be **held-out** — authored by a different person than the
predicate author, or at minimum audited by a second person to confirm they
were not implicitly steered to fit. Record who authored each prompt.

Prompts (single-file and package-level; sanity-check both against the
current tree before running — they reference real packages but specific
behavior claims may need adjustment):

C1 — single-file change:

```text
In internal/commands/showcmd/, add a --section flag accepting one of
goal|verify|providers|judge that limits which work-order section the command
prints. Default output (no flag) must be byte-identical to today. Scope:
edit only files inside internal/commands/showcmd/. Acceptance criteria:
each --section value prints only the named section; an unknown value exits
non-zero with a clear error; with no flag, output equals today's output
verbatim. Gate verifier: go build ./... && go test
./internal/commands/showcmd/... -run . -count=1. Use two build providers
(claude-code and codex) and one claude judge.
```

C2 — package-level Go change:

```text
In internal/commands/doctorcmd/, add a --json mode that emits the doctor
checklist as a JSON array. Each element has fields id (string), status (one
of ok|warn|fail), and hint (string, may be empty). Default human output and
exit code rules must remain unchanged. Scope: edit only files inside
internal/commands/doctorcmd/. Acceptance criteria: --json emits a valid
JSON array parseable by `jq .`; each check appears as exactly one object;
exit code with --json matches the exit code of the same run without --json.
Gate verifier: go build ./... && go test ./internal/commands/doctorcmd/...
-run . -count=1. Use two build providers (claude-code and codex) and one
claude judge.
```

How to test:

1. Run each prompt through `/bakeoff:run` three times in fresh sessions.
2. Stop at preview.
3. Inspect generated JSON with `show`.
4. Validate the JSON when practical.
5. Do not run providers unless the draft behavior itself is being dogfooded
   end to end.

Success looks like:

- Both prompts fast-path to preview on all three trials.
- Each preview uses defaults compactly and shows deviations.
- Each JSON validates without repair.
- No prompt performs more than one context pass.

Failure looks like:

- Either prompt falls back despite meeting all predicate requirements.
- Either prompt needs JSON repair.
- The preview hides non-default values or fails to show the verifier.
- The model relies on repo-specific heuristics instead of supplied scope.

### Experiment D: Negative Guardrail Matrix

What this tests: the fast path does not trigger when it would make Bakeoff less
safe or less verifiable.

Run these prompts and record the actual route:

| Prompt id | Prompt shape | Expected route |
| --- | --- | --- |
| D1 | Build request with an implementation goal but no verifier | Missing-field ask or task-fit warning |
| D2 | Build request with verifier but no acceptance criteria | Missing-field ask |
| D3 | "Build a comparison matrix of CLI approaches" with no code-edit intent | Research/compare route, or clarification |
| D4 | Request names a vague route/package such as "fix the auth thing" | Scope clarification |
| D5 | Metric benchmark request with no protected harness/golden paths | Clarification asking for protected paths and metric command |
| D6 | Review request with no branch, diff, file set, or local-change scope | Task-fit warning |
| D7 | Explicit multi-lens review request | Multi-lens preview path, not fast path |
| D8 | Obvious 2-3 independent-part request | Split proposal path, not fast path |
| D9 | Missing path-like input — literally type `./missing.work-order.json` as the user message | Path error from CLI, not natural-language reinterpretation |
| D10 | Build request with `scope: web` on a build provider, or external-web research requirement on a build prompt | Validation rejection (do not fast-path; do not silently coerce to `scope: codebase`) |
| D11 | Re-run the A baseline prompt and watch for the contract-drift surfaced in A Trial 2 (`d640a43b`): the model wrote the work-order file **before** the approval prompt | Preview must precede file write; no `Write` tool call until the user has approved. Any fast-path or careful-path implementation that calls `Write` before approval is a failure. |

How to test:

1. Run each prompt until the first preview, warning, or question.
2. Do not approve provider execution.
3. Record whether fast path triggered.
4. Record whether the response matches the expected route.

Success looks like:

- Zero negative prompts fast-path.
- Each prompt lands in the expected warning, clarification, split,
  multi-lens, existing-path, or careful-drafting route.
- No response answers the user task inline.

Failure looks like:

- Any negative prompt reaches an approval-ready single-work-order preview
  through the fast path.
- The flow silently invents a verifier, acceptance criterion, protected path,
  or scope.
- A path-like missing input is treated as natural language.

**False-positive soft signal.** This experiment is the only check on the
"zero false positives on negative cases" target, and the only judge is the
operator reading the transcript. Treat it as a soft signal, not a guarantee.
If a marginal case is borderline, file it for review rather than counting it
as a pass.

### Experiment E: Batched Exploration

What this tests: when a real drafting fact is needed, the model gathers it in
one bounded pass instead of drifting into sequential exploration.

The original E prompt used "the conventional test command for the lscmd
package." That wording is now obsolete because R1.4 correctly treats it as a
missing verifier and asks without exploring. Use a prompt where the verifier is
explicit and the requested lookup is useful background, not a required field:

```text
Add a --limit N flag to `bakeoff ls` that caps shown runs to the most-recent
N. Scope: edit only files in internal/commands/lscmd/ relevant to flag
parsing and rendering. Acceptance criteria: --limit N shows at most N runs
after the existing sort; --limit 0 shows none; absent flag means no cap;
--limit with a negative value exits non-zero with a clear error. Gate
verifier: go build ./... && go test ./internal/commands/lscmd/... -count=1.
Before drafting, look up whether internal/commands/lscmd/ uses table-driven
tests or function-per-case tests so the work order can name the test style in
the background. Use two build providers (claude-code and codex) and one claude
judge.
```

This prompt requires one local fact lookup without asking the model to invent a
verifier.

How to test:

1. Run the prompt through `/bakeoff:run`.
2. Confirm the model performs at most one context pass before preview or
   clarification.
3. Confirm the context pass answers all known drafting questions at once.
4. Confirm no redundant follow-up checks occur unless the first pass exposes a
   concrete blocker.

Success looks like:

- At most one batched context pass, then preview or a focused question. Zero
  passes is acceptable only if the model explicitly declines to include the
  optional test-style fact rather than guessing it; two or more means it
  drifted.
- The pass is limited to drafting facts, not provider-level investigation.
- No separate file-existence plus line-count plus branch checks unless each is
  tied to a blocker.

Failure looks like:

- Multiple sequential exploration turns answer questions that were known at the
  start.
- The model reads target source files deeply enough to start solving the task
  inline.
- The context pass expands beyond draft validation and becomes open-ended
  research.

### Experiment F: Template And Default Preview Impact

What this tests: clean draft skeletons and default-aware previews improve
draft reliability and readability without becoming hidden behavior.

**Scope note.** F requires comparing drafts under two different contract
states (with vs. without skeleton/default-preview wording). The first PR
ships all docs changes together, so there is no clean "after-skeleton,
before-default-preview" intermediate. Defer F to a follow-up PR, or split
the first PR into "predicate + batched exploration" then "skeleton + preview
wording" if F is required for signoff. The default in this plan is to defer.

How to test (when run):

1. For the positive prompts in Experiments B and C, compare drafts produced
   before and after skeleton/default-preview wording.
2. Count validation repairs.
3. Count preview length in lines.
4. Inspect whether defaults and deviations are understandable without printing
   full JSON.
5. Use `show` and confirm the full JSON contains explicit concrete values.

Success looks like:

- Preview is shorter and still includes the required decision information.
- Full JSON remains explicit and clean.
- Validation repair rate does not increase.
- Deviations from defaults are visible in preview.

Failure looks like:

- Preview hides verifier, base ref, protected paths, non-default provider,
  judge, budget, or scope details.
- Full JSON depends on TODO placeholders or implicit fields.
- Users need `show` to understand basic run cost or route.

### Experiment G: Preflight Cost Check

Status: **PASS** (2026-05-20). Median 17 ms across n=5 warm trials,
range 3 ms, byte-identical output. ≈0.01% of the 2-3 minute preview budget.
Full data: [experiment log → G](drafting-fast-path-experiment-log-2026-05-20.md#g--preflight-cost-check).

Caveat carried into the plan: trials were warm-cache and `dist/bakeoff`
was already built. The build-fallback path (when `dist/bakeoff` is missing)
was not measured and is out of scope for this experiment; it only matters
on first-run-after-install. If a future dogfood shows real first-run cost,
revisit then.

What this tested: whether preflight is worth optimizing later.

How tested:

1. Ran `scripts/bakeoff-ensure-cli --check` five times in the same environment.
2. Recorded wall time and output.
3. Did not change the run contract based on this experiment alone.

Success criteria (both met):

- Preflight is a small fraction of drafting wall time.
- No preflight caching is needed in the first PR.

Failure criteria (none triggered):

- Preflight regularly accounts for a meaningful share of the target 2-3 minute
  preview budget, or it has high variance.
- If that happens, open a separate follow-up plan for session-scoped preflight
  caching with binary path/version invalidation.

## Acceptance Criteria

Behavioral:

- Obvious narrow build requests with explicit acceptance criteria, scope, and
  verifier go straight from preflight to preview.
- Existing work-order paths still bypass natural-language drafting and run
  validation first.
- Ambiguous or unsafe requests still warn or ask for missing information.
- Split and multi-lens behavior is unchanged when explicitly triggered.
- One-work-order previews can summarize defaults without dumping full JSON.
- Full JSON remains available through `show`.
- Generated JSON remains clean and validates through the Go CLI.
- No run-time verification, baseline, artifact, judge, triage, ledger, or
  provider-scope behavior is weakened.
- Scenario documentation covers fast-path triggers and fast-path fallbacks.

## Definition Of Done

The first PR is done when all of the following are true:

- `commands/run.md` and `skills/bakeoff/SKILL.md` both contain the fast-path
  predicate, fast-path action, fallback rules, batched exploration guidance,
  default-aware preview wording, R1/R1.6 guidance, R2, R3 build skeleton, R4
  advisory wording, and R5. A diff between the two files shows the same
  wording in both, except for intentional cross-reference phrasing.
- `commands/run.md:474` no longer contains the standalone "infer silently"
  paragraph; the fast-path section replaces it.
- `bakeoff/CLAUDE.md` references the batched exploration rule.
- `docs/task-fit-test-scenarios.md` has a `## Fast-Path Drafting Scenarios`
  section with both positive and negative subsections.
- `scripts/measure-drafting.py` (or equivalent) exists and prints the three
  counts described in the Shared Measurement Rules.
- Fresh-session verification batches record the active plugin cache SHA after
  `/plugin` + `/reload-plugins`; any batch without cache confirmation is
  treated as historical/corroborating only.
- Experiments G and A established the baseline; clean-cache D/B/D7/E-style
  verification results are appended to
  `docs/drafting-fast-path-experiment-log-2026-05-20.md`.
- B drafting remains inside A's measured envelope (A max 51.6 s) while
  preserving canonical schema and no pre-approval writes. The original ≤ 30 s
  target is deferred.
- **Final landing rates (n=19 clean trials across final-contract
  verification batches, see "Real Landing Rates" risk section below)**:
  - R1 — no required-field synthesis: **100% on the tested prompts
    under final contract** (D1 3/3, D5 3/3, D2-with-R1.6 3/3, D8
    missing-field, D10 task-fit). Ships as advisory + R1.6
    refactor tightening (verified).
  - R2 — no Write before approval: **19/19 = 100%**. Ships as a hard
    invariant.
  - R3 — canonical schema verbatim: **5/5 = 100%** when drafting
    happens (D2 ×3 + B drafting ×2). Ships as strict-must for build
    drafts.
  - R4 — pre-preview validate: **2/5 = 40%** when drafting happens.
    Ships as advisory; backstopped by Go-side post-write validate.
  - R5 — no CLI schema/backend probing: **19/19 = 100%**. Ships as a
    hard invariant.
  - **Wall time**: B drafting on lscmd positive case clocked at
    40 s and 52 s (n=2 clean post-amendment trials) — above the original
    ≤ 30 s goal but within the A baseline range (31.9 s median / 51.6 s
    max). The +258
    contract lines did not materially regress speed.
- **Hard invariants that ship as enforced**:
  - R2 — no Write before approval.
  - R3 — canonical build schema verbatim.
  - R5 — no CLI schema/backend probing.
  - Post-write `bakeoff validate` (Go CLI, unconditional) — catches
    fictional schema before any `bakeoff build` / `bakeoff research`
    invocation. Remains the catch-all even with R3 strict.
- **Empirical safety chain validated**: across clean verification trials,
  zero provider runs launched on fictional schema and zero fictional schema
  appeared when drafting happened under final R3.
- **Open verification work** (none blocking; cycle closed):
  - R4 40% rate is acceptable given the post-write validate safety
    net but could be improved by a Go-side pre-preview hook
    (Option B-narrow). Skipped unless real-use signal justifies.
  - Optional corroboration deferred to follow-up: D3/D4/D6 routing
    re-runs against the final cache, C1/C2 held-out positive variants, a
    third lscmd B drafting timing trial, and redesigned E fact-lookup
    batching. None blocking.
- No B or C trial issues a `Write` before the approval prompt. Audited by
  grepping each trial's transcript for `Write` tool calls preceding the
  approval line emitted by the model.
- No Go runtime code under `internal/` is touched by this PR.

C and F are not blockers for the first PR; they live in a follow-up.

## Rollback

If the fast path proves too permissive in practice, revert the docs PR.
Because no Go runtime code changes, revert is safe and complete: removing the
fast-path section restores the prior careful flow on the next `/bakeoff:run`
invocation. No data, ledger, or work-order migration is required. The
experiment log stays on disk as historical record.

## Risks And Mitigations

### Risk: Fast Path Runs Ambiguous Builds

If the predicate is too permissive, Bakeoff may launch expensive provider runs
without a real verifier or without clear acceptance criteria.

Mitigation: require explicit acceptance criteria, explicit gate verifier, and a
bounded edit target for build fast path. Treat missing or implied fields as
fallback, not as template-fill opportunities.

**Status: mitigated on tested prompt shapes (2026-05-20 clean-cache
verification).** Early D batches showed synthesis drift, but the cache
contamination audit proved those batches were not reading the amendments.
Under the final loaded contract, D1, D5, and D2-with-R1.6 all asked instead of
drafting across n=3 each. This remains prompt-layer behavior rather than a
Go-side semantic guarantee; the preview-then-approve flow is still the safety
net for untested wording variants.

### Risk: Write Before Approval (D11 Drift)

The current contract requires preview → approval → Write. A Trial 2 and one
B-side dogfood (image 3) showed the model issuing a `Write` for
`*.work-order.json` *before* asking for approval. This is a safety violation
because the file then exists on disk regardless of whether the user types
`yes`.

Mitigation: add an unconditional rule near the approval block in
`commands/run.md` and `skills/bakeoff/SKILL.md`:

> No `Write`, `Edit`, or file-mutating tool call may precede the approval
> prompt. The preview is read-only. The first mutating tool call must come
> *after* the user's affirmative reply. This applies to fast path and
> careful path equally.

Add D11-style audit (transcript inspection for `Write` before the approval
line) to every B and C trial protocol, not just D11.

### Risk: Package Or Route Guessing Creates Bad Work Orders

Heuristics like `bakeoff <subcmd> -> internal/commands/<subcmd>cmd` are useful
inside this repo but dangerous as universal rules.

Mitigation: use repo-specific heuristics only when the user supplied enough
text to make the target obvious, or after a batched context pass confirms it.
Do not encode this as a general plugin rule.

### Risk: Metrics And Protected Paths Are Under-Specified

Metric work orders can be invalid in spirit even when JSON validates if
providers can edit the measuring stick.

Mitigation: do not fast-path metric verifier requests unless the metric
command, direction, expected output contract, and protected paths are explicit
or confirmed by exploration.

### Risk: Contract Slimming Removes Safety Language

The current contract is large partly because it records hard-won safety edges.

Mitigation: slim by deduping and reordering, not by deleting invariants. Keep a
checklist of invariants before and after the rewrite.

### Risk: Default-Aware Preview Hides Important Deviations

Summarizing defaults is safe only if deviations are called out.

Mitigation: preview defaults compactly, but always show non-default providers,
judge, budget, scope policy, base ref, verifier suite, protected paths, and
mode-specific flags.

### Real Landing Rates (Corrected 2026-05-20T18:00Z After Contamination Audit)

**The original 16-trial dataset across batches 1-4 was invalidated by
a plugin cache contamination.** Claude Code's active plugin read a
pre-cycle cache (`0c8f2f8c9b59` during the dogfood batches) while edits
were being applied to the marketplace source tree at
`~/.claude/plugins/marketplaces/...`. None of those dogfood batches read
the amendments being tested. See
[experiment log → Methodology Correction: Plugin Cache Contamination](drafting-fast-path-experiment-log-2026-05-20.md#methodology-correction-plugin-cache-contamination-2026-05-20t1730z).

After `/plugin` + `/reload-plugins`, clean verification batches ran
against the actually-loaded contract:

| Rule | Pre-contamination claim | **Final clean landing rate** |
| --- | ---: | ---: |
| R1 — no required-field synthesis | 0 / 9 = 0% | **100% on tested final-contract prompts** (D1 3/3, D5 3/3, D2-with-R1.6 3/3, plus D8/D10 corroboration) |
| R2 — no Write before approval | 16/16 = 100% | **19/19 = 100%** |
| R3 — canonical schema verbatim | 5 / 15 = 33% | **5/5 = 100%** when drafting happens |
| R4 — pre-preview internal validate | 4 / 15 = 27% | **2/5 = 40%** when drafting happens |
| R5 — no CLI probing | 16/16 = 100% | **19/19 = 100%** |

**The cycle's central conclusion — *"prompt-layer enforcement of
drafting detail is not achievable"* — was wrong.** The amendments
work when actually loaded.

#### Per-prompt verification breakdown

- **D1 (missing verifier): 3/3 asked.** Model cited "the mechanical
  checklist" by name in one trial, listed candidate verifiers as
  options in another. R1 fires reliably for missing verifiers.
- **D5 (missing protected paths on metric benchmark): 3/3 asked.**
  One trial flagged that the existing scope made the benchmark
  gameable. R1 fires reliably for benchmark protected paths.
- **D2 before R1.6 (missing AC on refactor): 0/3 asked.** Model walked the
  checklist explicitly in one trial, identified AC as missing, and chose to
  synthesize anyway. This exposed the refactor soft spot.
- **D2 after R1.6: 3/3 asked.** All three trials cited the refactor edge-case
  rule by name or close paraphrase and asked for behavioral invariants instead
  of drafting.

#### R3 promotion back to strict-must (2026-05-20T18:00Z)

R3's 100% landing rate on the n=3 D2 trials (the only ones where
drafting actually happened) shows the canonical skeleton lands
when read. The C+ demotion to Advisory was based on contaminated
data and has been reverted. R3 ships as a hard contract rule
again.

#### R4 stays advisory

R4's final clean landing rate is 2/5 = 40% when drafting happens. The Go-side
post-write validate is the actual safety gate; R4 is a UX nice-to-have that
eliminates one repair-and-reapprove cycle when triggered. It stays advisory.

#### The Empirical Safety Net

Three hard enforcement layers protect provider runs from invalid
drafts:

1. **R2 — no Write before approval (19/19 = 100%).** The user
   always sees the draft preview before any file mutation. A
   careful operator can spot-reject a fictional draft or
   synthesized AC.
2. **R5 — no CLI schema/backend probing (19/19 = 100%).** The
   model uses embedded backends and skeleton; no improvised
   probes against the CLI.
3. **Post-write `bakeoff validate` (Go-side, unconditional).**
   The `/bakeoff:run` flow validates the on-disk JSON before
   invoking `bakeoff build` or `bakeoff research`. Fictional
   schema is caught here and forces a repair-and-reapprove
   cycle before any provider runs.

Across all clean verification trials, **zero provider runs launched
on fictional schema** (and no fictional schema actually appeared when
drafting happened under final R3).

#### Refactor Edge Case: R1 Misses On Missing-AC When Goal Is "Extract" / "Refactor" / "Consolidate"

D2 trial 3 is the cycle's most informative single trial. The
model emitted, verbatim:

> "[✓] Verifier named verbatim... [✗] Acceptance criteria named
> as observable behaviors — only the goal, scope, and verifier
> are stated... The AC checkbox is NO. Per the contract, advisory
> guidance says to ask, but the preview-then-approve flow is the
> safety net. I'll draft with synthesized AC anchored to
> observable, testable behaviors (not the anti-patterns 'no
> behavior change' or 'defaults are consolidated') and let you
> redirect from the preview."

This is the model **rationally exercising the "should" wording's
flexibility on refactor tasks**, not a contract-reading failure.
The synthesized AC items the model produces ("round-trip
equality", "existing tests pass", "exported API surface
unchanged") are reasonable but they are the model's guess at
intent, not the user's stated intent.

R1.6 (the refactor-specific checklist item added 2026-05-20T18:00Z
to `commands/run.md` and `skills/bakeoff/SKILL.md`) explicitly
demands behavioral invariants for refactor and extract requests even when
goal+scope+verifier are present. It closed the observed gap in a clean n=3
D2 verification batch: all three trials asked for invariants instead of
drafting.

If R1 ever misses on a new refactor wording, the operator's
preview-then-approve flow remains the safety net.

#### When To Escalate

Build a Go-side pre-preview validate hook (Option B-narrow) only
if real-use signal shows the repair-and-reapprove cycle on
fictional schema drafts is causing actual problems. The Go-side
hook design is sketched in
[Rejected Alternatives → Go-Side Pre-Preview Validate Hook](#go-side-pre-preview-validate-hook).
Cost: ~1-2 hours Go code, low false-positive risk. Win: eliminates
one round-trip on fictional drafts. **Skip unless triggered by
real-use signal.**

### Known Limitation: R1 Is Prompt-Enforced, Not Semantically Guaranteed

**Status: mitigated, not mathematically enforced (2026-05-20).** Once the
plugin cache actually loaded the final contract, R1 landed at 100% on the
tested prompt shapes, including the R1.6 refactor edge case. That is enough to
ship the docs/contract change. It is still not a Go-side semantic guarantee:
an untested prompt could phrase missing AC, verifier, or protected paths in a
way that the model fails to catch.

Concrete residual failure mode: a user submits a prompt with goal + scope but
forgets to include AC, verifier, or protected paths. The model drafts plausible
defaults and the operator approves the preview without catching the synthesis.
The provider run then optimizes for criteria the user did not explicitly name.

Mitigations already in place:

1. **Mechanical checklist + R1.6.** The model has a compact checklist and a
   refactor-specific edge-case rule, both verified on the final prompt set.
2. **Preview-then-approve.** The operator sees the draft before any provider
   run starts and can reject synthesized AC or verifiers.
3. **Post-write validation.** Structural schema drift is caught before provider
   execution; this does not catch semantic synthesis, but it prevents broken
   bakeoffs.

Escalate to the deferred Go-side synthesis linter only if real-use telemetry
shows runs solving the wrong thing, synthesized verifiers passing unintended
tests, or benchmark prompts running without protected measuring paths. Until
then, the linter is bloaty relative to observed risk.

### Risk: Drafted JSON Is Not Just Imperfect — It Is Not Schema-Valid

**Status: realized once, mitigated by R3 + post-write validation.**
Validation audit on 2026-05-20T15:33Z showed 4/5 on-disk drafts validate
cleanly; only the 1 post-Step-1 draft (image 3,
`lscmd-order-by-finished-at.work-order.json`) failed. Even intermittent
invalid JSON is high-impact because it creates a repair-and-reapprove cycle.
The clean final-contract batches later showed R3 at 5/5 when drafting
happened.

The drafted `lscmd-order-by-finished-at.work-order.json` (image 3) required
**major** repair before `bakeoff validate` would accept it. A follow-up
iterative-validate audit on 2026-05-20T15:43Z (see
[experiment log → Schema-drift repair-surface audit](drafting-fast-path-experiment-log-2026-05-20.md#schema-drift-repair-surface-audit-2026-05-20t1543z))
established the precise repair surface: **13 distinct schema repairs**
spanning type mismatches (1), invalid field names (5), invalid enum
values (2), missing required fields (4), and a missing required `build`
block (1). The validator reports one error per pass, so a user
repairing this draft by hand would have invoked `bakeoff validate` 13
times. The draft used
field names and structures from a fictional schema:
`providers[].kind` (should be `backend`), `providers[].role` (does not
exist), `providers[].scope: "local"` (should be `"codebase"`), `judge.id/
kind/role` (should be `backend/model/effort`), top-level `gates` array
(should be nested `build.verify`), `command: "..."` string (should be
`argv: [...]` array), top-level `acceptance_criteria` array (no such
field — criteria belong in `background`), and a missing required `build`
block entirely.

This is **not** a predicate-strictness problem — the predicate decides
whether to draft, not what shape to fill. It is a **skeleton problem**
(Step 4). The current skill contract describes defaults in prose but does
not pin the canonical JSON shape, so the model improvises.

Mitigation (carry into the same docs PR):

1. Embed a canonical valid build-skeleton JSON in `skills/bakeoff/SKILL.md`
   and `commands/run.md`. Not a TODO template; an actual valid JSON block
   with `<placeholders>` for the few fields the user actually supplies
   (goal, background, scope.include, verify[].argv).
2. State that the model **must** copy field names verbatim from the
   embedded skeleton. Inventing or renaming fields is a contract failure.
3. Add advisory pre-preview internal `bakeoff validate`. If the model performs
   it and finds a problem, it should repair before showing the preview.
4. Keep the enforced post-write `bakeoff validate` before `bakeoff build` /
   `bakeoff research`; zero provider runs may launch on invalid schema.

### Risk: Preflight Caching Masks Broken CLI State

Caching preflight could save seconds but might hide a missing or broken binary.

Mitigation: do not cache preflight in the first implementation. Measure it
separately later. If caching is added, keep a short session-only cache and
invalidate on binary path/version changes.

Status: **closed for this PR.** Experiment G measured preflight at 17 ms
median (warm cache, prebuilt `dist/bakeoff`) — a non-issue against the
2-3 minute target. Caching would shave milliseconds at best. Revisit only
if a future dogfood shows the build-fallback path (no `dist/bakeoff`) is a
real share of first-run cost.

### Risk: Fast Path Degrades Review Or Analyze Requests

Build requests are easiest to fast-path because the verifier and edit scope can
be concrete. Review and analyze requests often need bounded evidence surfaces.

Mitigation: start with build-mode fast path. Add review/research fast-path
rules only after build dogfood proves the predicate is safe.

## Rejected Alternatives

### Skip Preflight On Repeat Invocations

This saves only a few seconds and weakens the existing `/bakeoff:run`
readiness contract. Keep it out of the first pass.

### Move Natural-Language Drafting Into The Go CLI

A `bakeoff draft` helper may eventually reduce plugin prompt complexity, but a
real natural-language draft command would either duplicate model-side judgment
or add a new LLM dependency to the CLI. That is too much machinery for this
optimization.

### Use `bakeoff init` Templates For Generated Drafts

The init templates are human starter files with TODO placeholders. Generated
work orders should be clean JSON that validates without inheriting TODO
scaffolding.

### Go-Side Pre-Preview Validate Hook

Considered as Option B-narrow during the 2026-05-20 cycle. Deferred to a
follow-up plan, not rejected outright. The clean-cache data showed R3 holding
at 5/5 and R4 firing only 2/5, so the hook would improve preview UX rather
than provider-run safety.

Concept: a `PreToolUse` hook on `Write` (or a small wrapper script
that wraps the `/bakeoff:run` drafting flow) that shells out to
`bakeoff validate` against the in-memory work-order JSON before
the preview is shown to the user. If validation fails, the hook
returns the validation errors to the model so it can repair before
showing any preview. The model cannot skip the hook.

Why this is much smaller and safer than the R1 synthesis linter
considered earlier:

- The check is objective: `bakeoff validate` defines schema validity;
  there is no fuzzy pattern matching.
- False-positive risk is near zero — a valid work order is a valid
  work order.
- Maintenance cost is the same as `bakeoff validate` itself.
- The hook is plumbing, not policy.

Why it was deferred:

- The actual safety net (post-write `bakeoff validate`) already
  prevents broken bakeoffs from running. The hook would only
  eliminate one user-visible repair-and-reapprove cycle on
  fictional drafts — a UX polish, not a safety improvement.
- Adds a maintenance surface (hook entry in `settings.json`) that
  could drift out of sync if removed by a user.
- Dogfood overestimates real-use prevalence of fictional drafts;
  the operator's real prompts may rarely trigger the friction.

Revisit when one of these signals appears:

- Operators report the repair-and-reapprove cycle is annoying or
  confusing in real use.
- The repair loop fails to converge — model keeps producing the
  same fictional schema across multiple repair attempts.
- A specific schema-drift pattern starts hitting users in
  production builds.

### Go-Side Synthesis Linter

Considered as Option B during the 2026-05-20 R1-enforcement cycle.
Rejected for this PR. The proposal was a `bakeoff lint-draft <path>`
subcommand (or a flag on `bakeoff validate`) that flags
synthesized-looking AC patterns (scope restatements like "edits stay
in scope", verifier restatements like "go build succeeds", vacuous
claims like "no behavior change") and synthesized-looking verifiers
(`go test ./<scope>/...` invented from package name when the user
did not provide it). Hard fail with a clear error before
`bakeoff build` runs.

Reasons rejected:

- **Clean-cache dogfood did not justify a linter.** R1 landed at 100% on the
  tested final-contract prompts after R1.6. Real-use prompts usually include
  AC + verifier — the user is trying to get a real bakeoff to run. The actual
  prevalence of synthesis drift in real use is unknown.
- **False-positive risk on legitimate AC.** "Behavior is
  preserved for callers of API X" trips the "behavior preserved"
  pattern but is a legitimate AC. Pattern-based linting will
  reject valid work orders sometimes. False positives erode
  trust faster than false negatives.
- **False-negative risk via rephrasing.** Model rephrases "no
  behavior change" → "the change is non-observable" → "callers
  see no difference". Arms race the linter cannot win.
- **Maintenance debt.** Model phrasing drifts every few months.
  Linter patterns go stale silently. No volunteer base to
  refresh fuzzy heuristics.
- **Coupling.** Linter must mirror the contract's definition of
  "real AC". When the contract changes (new field, new mode),
  the linter must change in sync — silent drift hazard.
- **The thing that actually breaks `bakeoff build` is fictional
  schema, and R3 + R4 already catch that.** R1 is about
  spirit-of-intent drift (provider solves a similar problem,
  not the exact one) — less catastrophic than schema drift.
- **Cost-to-value ratio is poor.** ~200-400 LOC for ~2.5%
  estimated catch rate on real-use prompts (5% prevalence × 50%
  pattern coverage). Not worth it without real-use telemetry
  showing R1 drift is causing problems.

Revisit when one of these signals appears:

- Operator reports a run "solved the wrong thing" — provider
  patches match synthesized AC, not user intent.
- A synthesized verifier causes a `bakeoff build` to pass on
  tests the user did not intend.
- A benchmark prompt runs without protected paths and a
  provider edits the measuring stick.

### Add Repo-Specific Global Heuristics

Rules such as `internal/commands/<subcmd>cmd` are helpful for this repository
but should not be global Bakeoff behavior. Keep them as optional exploration
results or explicit user-supplied context.

## Open Questions

Resolved before drafting this revision:

- **Build-only v1?** Yes. Review/research/analyze/compare stay on the careful
  flow. Revisit after B and D pass. (Resolved in Step 1.)
- **Where do scenarios live?** Extend `docs/task-fit-test-scenarios.md`.
  (Resolved in Step 5.)
- **Hardcode `patch_max_bytes` in skeleton?** No. Omit and let Go default
  apply. (Resolved in Step 4.)
- **Signoff scope.** Experiment B requires one full provider dogfood (n=1
  signal, not metric) plus preview timing and validation-only checks on the
  other two trials. (Resolved in B.)

Still open (not blockers for the first PR):

- Is there a practical way to make `commands/run.md` reference
  `skills/bakeoff/SKILL.md` without duplicating all rules, given plugin command
  packaging? Follow-up plan if duplication keeps causing drift.
- Should generated-draft defaults eventually come from a machine-readable
  source so docs, examples, and command instructions cannot drift? Same
  follow-up.

## Suggested First PR

Ship a docs/contract-only change first. The implementation should reflect the
final clean-cache evidence, not the invalidated mid-cycle batches:

1. Keep the first PR docs/contract-only; no Go runtime code under `internal/`.
2. Ship build-only fast-path rules plus R2, R3 build skeleton, R5, R1 advisory
   checklist/R1.6, R4 advisory validate, and scenario checklist coverage.
3. Keep review/research/analyze/compare fast-path expansion out of this PR.
4. Use `scripts/measure-drafting.py` for timing/counts and record active plugin
   cache SHA before every fresh-session batch.
5. Treat G, A, clean D/R1.6, B, D7, and E-obsolete findings in the experiment
   log as the evidence base for this PR.
6. Defer C1/C2, a third B timing trial, redesigned E fact-lookup batching,
   Go-side hooks, synthesis linting, and contract slimming.

C and F remain follow-up material: C needs held-out prompt authoring by a
second person, and F requires comparing drafts across contract states that this
PR intentionally collapses into one change.

This first PR should not touch Go runtime code. That keeps the blast radius low
and verifies whether the real bottleneck is contract-side, as the dogfood
post-mortem suggests.
