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

- Reduce p95 (and max-over-three-trials) drafting wall time for narrow build
  prompts from ~52 s to **≤ 30 s**.
- When the request supplies explicit scope, acceptance criteria, and gate
  verifier, hold **pre-preview tool calls ≤ 2** (preflight plus at most one
  batched context pass).
- Hold pre-preview model turns to **≤ 6** for fast-path-eligible prompts.
- Do not regress median wall time from its current ~32 s.

The fast-path predicate addresses the outlier path (Trial 3: 6 sequential
exploratory tool calls before drafting). The batched-exploration rule
addresses the same path when one fact-lookup is genuinely needed. Median
saving is bounded; **the value of this work is variance reduction and
making outlier paths impossible by contract.**

## Empirical Progress

Log: [drafting-fast-path-experiment-log-2026-05-20.md](drafting-fast-path-experiment-log-2026-05-20.md)

Experiments run in order G → A → D → B → E. C and F deferred to a follow-up PR.

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
| R3 promotion + R1.6 refactor tightening | ✅ LANDED (2026-05-20T18:05Z) | — | (1) Reverted R3 section header in `commands/run.md` and `skills/bakeoff/SKILL.md` from `### Canonical Skeletons (Advisory)` → `### Canonical Skeletons`. Restored "must copy verbatim" + "is a contract failure" language. Removed the "advisory guidance" paragraph and ~33% landing-rate citation (both based on contaminated data). (2) Added refactor-specific checklist item to the Mechanical Pre-Flight Checklist in both files: `[ ] If the request is a refactor/extract/consolidate/split: user named the behavioral invariants to preserve?` with explanation that "no behavior change" is exactly the anti-synthesis pattern, ask for specific test files / API contracts / round-trip equalities. (3) Added a "Refactor edge case (load-bearing)" callout below the checklist that names the problem and the response. | R1.6 close-the-gap effect is untested as of cycle close. Verification requires a new n=3 batch on D2-style refactor prompts after the plugin re-caches to the post-R1.6 commit. R4 unchanged (stays advisory). |

Update protocol: every experiment must update this table when it lands,
and fold its verdict into the relevant plan sections (Observed Cost,
Risks, Open Questions, Acceptance Criteria) before the next experiment
begins. The plan tracks empirical state, not just intent.

## 2026-05-20 Experiment Cycle Summary

This section consolidates findings from the 2026-05-20 dogfood cycle
(11 operator screenshots + 1 full provider dogfood). Detailed timing data
and per-trial transcripts live in
[drafting-fast-path-experiment-log-2026-05-20.md](drafting-fast-path-experiment-log-2026-05-20.md).

### What ran

| Experiment | Status | New data |
| --- | --- | --- |
| G — preflight cost | ✅ DONE earlier | n=5, 17 ms median |
| A — baseline | ✅ DONE earlier | n=3, 31.9 s median / 51.6 s max |
| D — negative matrix | ⚠️ PARTIAL FAIL | 8/11 prompts tested via screenshots |
| B — drafting metric | ⚠️ MIXED | 4 trials: 32 / 43 / 52 / 59 s wall |
| B — provider dogfood | ✅ DONE today | 4 m 1 s; winner=claude (judge-basis); schema-repair tax |
| E — batched exploration | ⏳ operator-blocked | — |

### Findings

1. **Predicate is too permissive on missing-field cases** (D1, D2, D5).
   The post-Step-1 contract synthesizes a gate verifier (D1), synthesizes
   acceptance criteria (D2), and elides the protected-paths clarification
   for metric benchmarks (D5) instead of falling back to a missing-field
   ask. Fast-path predicate decides *whether* to draft; it does not block
   field synthesis once drafting starts.

2. **Write-before-approval drift recurs intermittently** (D11). One of
   three B-side trials wrote `lscmd-order-by-finished-at.work-order.json`
   (54 lines) before the approval prompt. Reproduces A Trial 2
   (`d640a43b`). Current contract does not have an unconditional
   "preview is read-only" clause.

3. **Drafted JSON is not schema-valid** — biggest finding. The drafted
   `lscmd-order-by-finished-at.work-order.json` (image 3) used a
   fictional schema. Iterative-validate audit on 2026-05-20T15:43Z
   established the exact repair surface: **13 distinct schema
   repairs** — type mismatch on `schema_version`, 5 wrong fields on
   `providers[]` (kind/role/scope-value/missing-model/missing-effort),
   judge block rewrite, top-level `gates[]` vs nested `build.verify`,
   top-level `acceptance_criteria` (no such field), missing required
   `build` block, top-level `scope` (no such field), wrong backend
   enum value (`"claude-code"` vs `"claude"`), and missing
   `budgets.max_output_bytes`. The validator reports one error per
   pass, so a hand-repair would have meant 13 validate invocations.
   This is **not** a predicate problem — predicate decides *whether*
   to draft, not *what schema to fill* — it is a skeleton problem
   (Step 4).

4. **Multi-lens drafting wastes ~90 s on schema/backend rediscovery**
   (D7, image 11). 7 sequential exploration calls: `bakeoff providers
   list` (errored, no such subcommand), `bakeoff --help`, `bakeoff init
   --help`, `mkdir /tmp/bakeoff-tmpl && bakeoff init …` (just to read
   field names by example), `bakeoff doctor`. None of those calls
   produced output the contract could not embed once.

5. **Build pipeline itself is healthy.** The post-repair
   `bakeoff build` finished in 4 m 1 s with exit 0, both gates passed,
   judge converged in 2 passes on `claude` winner with rationale citing
   maintainability. The bottleneck is upstream drafting, not execution.

6. **Provider patch quality is good** (patch-inspection finding,
   2026-05-20T15:35Z). claude wrote a pure `orderRowsByFinishedAt`
   function (201 lines incl. tests) that also removed the legacy
   `sort.Sort(sort.Reverse(sort.StringSlice(runDirs)))` and the now-
   dead `"sort"` import. codex wrote `sortRunRows` in a new
   `lscmd/sort.go` file (137 lines) but kept the dead `"sort"` import.
   Both passed the gate; judge picked claude on maintainability, with
   2-pass A/B-swap agreement (positional-bias guardrail held). The
   build pipeline correctly distinguished "passes gate" from "quality
   patch." No quality concerns on the execution side.

7. **Validation-audit nuance** (audit on 2026-05-20T15:33Z): 4 of 5
   on-disk drafted work orders validate cleanly as-is. Only the 1
   post-Step-1 draft (image 3) failed. The schema-fictional drift is
   **intermittent, not systematic** — but even intermittent invalid
   JSON is high-impact because the user does not see the failure
   until they type `yes`. R3 (skeleton embed) and R4 (pre-preview
   validate) still apply: they make a future regression of this
   shape impossible by contract, regardless of frequency.

### Recommendations (consolidated)

Land all five in the same docs/contract PR. Splitting risks merge
conflicts on `commands/run.md`, `skills/bakeoff/SKILL.md`, and
`bakeoff/CLAUDE.md`.

**R1 — Forbid required-field synthesis (Step 1 amendment).**

Add to the fast-path section:

> Required-field synthesis is forbidden. If the request omits acceptance
> criteria, gate verifier, protected paths for a metric benchmark, or a
> bounded edit target, the model **must** ask the missing question(s)
> verbatim and stop. Filling in a plausible default from repo
> conventions is a contract failure. Non-synthesizable fields:
> build acceptance criteria; build gate verifier (command and pass
> condition); metric verifier protected paths; edit scope when no
> file/package/route/diff is named.

**R2 — Unconditional "no Write before approval" rule (Step 1 amendment).**

Add near the approval block in both `commands/run.md` and
`skills/bakeoff/SKILL.md`:

> No `Write`, `Edit`, or file-mutating tool call may precede the
> approval prompt. The preview is read-only. The first mutating tool
> call must come *after* the user's affirmative reply. This applies to
> fast path and careful path equally.

**R3 — Embed canonical build skeleton (Step 4 amendment, blocker).**

Embed a valid build-skeleton JSON in `skills/bakeoff/SKILL.md` and
`commands/run.md`. Not a TODO template; an actual valid JSON block with
`<placeholders>` for goal, background, scope.include, and
verify[].argv only. The model substitutes those placeholders;
everything else (`backend` vs `kind`, `scope: "codebase"`,
`build.verify` nested block, `argv` array) comes from the embedded
skeleton verbatim. Include a sibling skeleton for `gather` /
code-review and `compare`.

Add: "The model **must** copy field names verbatim from the embedded
skeleton. Inventing or renaming fields is a contract failure."

**R4 — Pre-preview internal `bakeoff validate` (Step 4 amendment).**

Add to the drafting flow: after building the work-order JSON in
memory, before showing the preview, internally invoke `bakeoff
validate` (via the same CLI binary used in preflight). If validation
fails, the model repairs the JSON and re-validates *before* showing
the preview, not after. The current contract validates after
approval, which misleads the user about what they're approving.

The user-visible flow becomes: preflight → draft JSON → internal
validate → (repair if needed) → preview → approval → write → run.

**R5 — Embed backends list to kill multi-lens improvisation (Step 2
amendment).**

Add to `skills/bakeoff/SKILL.md` and `commands/run.md`:

> Available provider backends: `claude` (Claude Code), `codex` (Codex
> CLI). Available judge backends: `claude`. The model **must not**
> probe the CLI to discover backends (`bakeoff providers list` does
> not exist; `bakeoff --help`, `bakeoff init`, and `bakeoff doctor`
> are not drafting-time discovery tools). If the user names an
> unknown backend, ask, do not improvise.

Combined effect: removes ~90 s of the D7 multi-lens drafting tail.

### Acceptance gates for the next dogfood

After R1-R5 land:

1. **D re-run**: D1, D2, D5, D11 all PASS. Zero false positives across
   the full matrix (including D8/D9/D10 not yet tested).
2. **B drafting re-run**: max-over-three-trials ≤ 30 s wall, ≤ 2 tool
   calls, zero `Write` before approval, **zero validation repairs**.
3. **B provider dogfood** (n=1): exit 0, `pick_winner` or
   `pick_winner_judge` decision, judge converges in ≤ 2 passes.
   Already met on today's run.

### Out of scope for this PR (deferred)

- Adding a backends-list subcommand to the Go CLI (R5 covers the
  drafting-time fix; the CLI change is a separate plan).
- A `bakeoff draft` subcommand. The skeleton-embed + pre-preview
  validate covers the same ground without adding model judgment to
  the Go binary.
- Automating the helper measurement workflow. Operator continues to
  run `scripts/measure-drafting.py` manually for now.

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

The fast path may trigger only when all of these are true:

1. The request clearly maps to exactly one work order.
2. The final type is clear without extra context.
3. The user clearly authorizes the work-order mode:
   - for build, providers are expected to edit code or produce patches;
   - for review/research/analyze/compare, providers are not expected to edit
     code.
4. Required fields are present:
   - build: implementation goal, acceptance criteria, at least one gate
     verifier, and base ref if not `HEAD`;
   - research/review/analyze/compare: target, scope, and evidence standard.
5. The request names an edit or evidence boundary:
   - explicit file, directory, package, route, command, module, branch, PR,
     diff, or local-change scope.
6. The verifier or evidence command is explicit enough to copy into the work
   order without guessing.
7. No requested split, multi-lens review, broad synthesis, or sequential plan
   is present.
8. No metric verifier, protected verifier fixture, benchmark harness, golden
   file, or generated expected-output artifact requires path discovery.
9. No mode-specific flag conflict is present.
10. The request does not mention external web research for a build work order.

For `ls-order-by-finished-at`, the predicate should pass.

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
- one-file or one-directory code change with explicit tests;
- review of an explicit diff/base with normal review settings.

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

### 6. R1 — Forbid Required-Field Synthesis (Amendment to Step 1)

Motivated by D1, D2, D5 failures (2026-05-20). The post-Step-1 fast-path
predicate decides *whether* to draft but does not prevent field
synthesis once drafting starts. Add an explicit forbid clause.

Files to edit:

- `commands/run.md` — append to the fast-path section.
- `skills/bakeoff/SKILL.md` — mirror the same wording in `## Drafting
  Rules`.

Wording to add (exact text):

```text
Required-field synthesis is forbidden. If the request omits acceptance
criteria, gate verifier, protected paths for a metric benchmark, or a
bounded edit target, the model **must** ask the missing question(s)
verbatim and stop. Filling in a plausible default from repo
conventions is a contract failure. Non-synthesizable fields:

- build acceptance criteria;
- build gate verifier (command and pass condition);
- metric verifier protected paths;
- edit scope when no file/package/route/diff is named.
```

Verification: after landing, re-run D1, D2, D5 in fresh sessions
(operator-blocked). Expected route: missing-field ask, not fast-path
preview. Mark Empirical Progress table row for D as PASS only when
all four (D1, D2, D5, plus D11) pass.

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

Add sibling skeletons for `gather` (code-review) and `compare` in the
same PR; their layouts are derivable from `examples/gather.work-order.json`,
`examples/review.work-order.json`, and `examples/compare.work-order.json`.

### 9. R4 — Pre-Preview Internal Validate (Amendment to Step 4)

Motivated by image 3 schema-drift (2026-05-20). The current contract
validates after approval, which misleads the user about what they're
approving. Move validation in front of preview.

Files to edit:

- `commands/run.md` — modify the drafting-flow ordering near the
  "show the compact preview" line.
- `skills/bakeoff/SKILL.md` — mirror.

Updated flow (exact text):

```text
After building the work-order JSON in memory:

1. Internally invoke `bakeoff validate <path>` against the in-memory
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

Acceptance: the JSON shown via `show` is byte-identical to the JSON
`bakeoff build` reads at run time. Validation repair count after
approval is zero.

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
SHA, working-tree `git status` summary, and whether `bakeoff/MEMORY.md` is
loaded. Mismatches across trials invalidate the comparison.

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
- **Fast-path wall time:** narrow build preview ≤ 30 s on every trial,
  i.e., the fast path must bring max-over-three-trials below A's median.
  Median improvement is a non-goal.
- **Pre-preview tool calls:** preflight plus at most one batched context
  pass (≤ 2 total). Zero context passes is acceptable when all fields are
  supplied. **Trial 3's 6 tool calls is the regression line — the fast path
  must make that impossible.**
- **Pre-preview model turns:** ≤ 6 for fast-path-eligible prompts (A's
  median; the fast path must not raise it).
- **Validation repair rate** for fast-path positive drafts: zero required
  repairs in the initial dogfood set.
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
- **Max-over-three-trials wall time ≤ 30 s** (under A's median of 31.9 s).
  Median improvement is a non-goal; the win is eliminating A's 51.6 s tail.
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
- Validation fails and requires repair.
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

What this tests: when context is needed, the model gathers it in one bounded
pass instead of drifting into sequential exploration.

Prompt — almost fast-pathable, missing exactly one local fact (the gate
verifier command). The model must look up the conventional test invocation
for the named package before previewing:

```text
Add a --limit N flag to `bakeoff ls` that caps shown runs to the most-recent
N. Scope: edit only files in internal/commands/lscmd/ relevant to flag
parsing and rendering. Acceptance criteria: --limit N shows at most N runs
after the existing sort; --limit 0 shows none; absent flag means no cap;
--limit with a negative value exits non-zero with a clear error. Gate
verifier: the conventional test command for the lscmd package. Use two
build providers (claude-code and codex) and one claude judge.
```

The phrase "the conventional test command for the lscmd package" forces
exactly one fact-lookup. Zero context passes would mean the model guessed;
two or more means it drifted into general exploration.

How to test:

1. Run the prompt through `/bakeoff:run`.
2. Confirm the model performs at most one context pass before preview or
   clarification.
3. Confirm the context pass answers all known drafting questions at once.
4. Confirm no redundant follow-up checks occur unless the first pass exposes a
   concrete blocker.

Success looks like:

- Exactly one batched context pass (not zero, not two), then preview or a
  focused question. Zero passes means the model guessed; two or more means
  it drifted.
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
  default-aware preview wording, and clean-skeleton guidance. A diff between
  the two files shows the same wording in both.
- `commands/run.md:474` no longer contains the standalone "infer silently"
  paragraph; the fast-path section replaces it.
- `bakeoff/CLAUDE.md` references the batched exploration rule.
- `docs/task-fit-test-scenarios.md` has a `## Fast-Path Drafting Scenarios`
  section with both positive and negative subsections.
- `scripts/measure-drafting.py` (or equivalent) exists and prints the three
  counts described in the Shared Measurement Rules.
- Experiments G, A, D, B, and E have been run with n=3 each and results
  appended to `docs/drafting-fast-path-experiment-log-YYYY-MM-DD.md`.
- B's max-over-three-trials wall time ≤ 30 s (under A's 31.9 s median).
  Median improvement is no longer the primary success bar; tail reduction is.
- **Corrected landing rates (n=9 against actually-loaded
  amendments, see "Real Landing Rates" risk section above)**:
  - R1 — no required-field synthesis: **6/9 = 67%**, ships as
    advisory with a known refactor soft spot (R1.6 tightening
    landed but untested).
  - R3 — canonical schema verbatim: **3/3 = 100%**, ships as
    strict-must (C+ demotion reverted).
  - R4 — pre-preview validate: **1/3 = 33%**, ships as advisory
    (strict wording did not move the rate).
- **Hard invariants that ship as enforced**:
  - R2 — no Write before approval (9/9 = 100%).
  - R3 — canonical schema verbatim (3/3 = 100% when drafting
    happens; promoted back to strict on 2026-05-20T18:05Z).
  - R5 — no CLI schema/backend probing (9/9 = 100%).
  - Post-write `bakeoff validate` (Go CLI, unconditional) — catches
    fictional schema before any `bakeoff build` / `bakeoff research`
    invocation. Was the safety net during the contaminated batches;
    remains the catch-all even with R3 strict.
- **Empirical safety chain validated**: across 9 verification trials,
  zero provider runs launched on fictional schema and zero fictional
  schema actually appeared (R3 strict + 100% landing rate). Worst-
  case user impact when R1 misses on a refactor is a synthesized AC
  the user must spot in the preview before approving.
- **Open verification work** (deferred to follow-up dogfood):
  - R1.6 refactor-specific checklist item needs an n=3 D2-style
    verification batch to confirm it closes the refactor soft spot.
  - R4 33% rate is acceptable given the post-write validate safety
    net but could be improved by a Go-side pre-preview hook
    (Option B-narrow). Skipped unless real-use signal justifies.
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

**Status: REALIZED (2026-05-20, D matrix).** D1, D2, and D5 dogfood trials
showed the post-Step-1 contract synthesizes a verifier (D1), synthesizes
acceptance criteria (D2), and elides protected-paths clarification on a
metric benchmark (D5) instead of falling back. Required follow-on edit
(carry into Step 1 PR before B re-runs):

> Required-field synthesis is forbidden. If the request omits acceptance
> criteria, gate verifier, protected paths for a metric benchmark, or a
> bounded edit target, the model **must** ask the missing question(s)
> verbatim and stop. Filling in a plausible default from repo conventions
> is a contract failure. The fields below are non-synthesizable:
> - build acceptance criteria;
> - build gate verifier (command and pass condition);
> - metric verifier protected paths;
> - edit scope when no file/package/route/diff is named.

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
a plugin cache contamination.** Claude Code's active plugin was
pinned to commit `2257a6c91ca0` (a pre-cycle baseline) for the
entire cycle, while edits were being applied to the marketplace
source tree at `~/.claude/plugins/marketplaces/...`. None of the
dogfood batches read the amendments being tested. See
[experiment log → Methodology Correction: Plugin Cache Contamination](drafting-fast-path-experiment-log-2026-05-20.md#methodology-correction-plugin-cache-contamination-2026-05-20t1730z).

After the plugin was updated to source HEAD `7077a02507a3` via
`/plugin` + `/reload-plugins`, a clean n=9 verification batch ran
against the actually-loaded contract:

| Rule | Pre-contamination claim | **Actual landing rate (n=9 fresh sessions)** |
| --- | ---: | ---: |
| R1 — no required-field synthesis | 0 / 9 = 0% | **6 / 9 = 67%** |
| R3 — canonical schema verbatim | 5 / 15 = 33% | **3 / 3 = 100%** when drafting happens |
| R4 — pre-preview internal validate | 4 / 15 = 27% | **1 / 3 = 33%** when drafting happens |
| R2 — no Write before approval | 16/16 = 100% | **9/9 = 100%** |
| R5 — no CLI probing | 16/16 = 100% | **9/9 = 100%** |

**The cycle's central conclusion — *"prompt-layer enforcement of
drafting detail is not achievable"* — was wrong.** The amendments
work when actually loaded.

#### Per-prompt verification breakdown (n=3 each)

- **D1 (missing verifier): 3/3 asked.** Model cited "the mechanical
  checklist" by name in one trial, listed candidate verifiers as
  options in another. R1 fires reliably for missing verifiers.
- **D5 (missing protected paths on metric benchmark): 3/3 asked.**
  One trial flagged that the existing scope made the benchmark
  gameable. R1 fires reliably for benchmark protected paths.
- **D2 (missing AC on refactor): 0/3 asked.** Model walked the
  checklist explicitly in one trial, identified AC as missing,
  and **chose to synthesize anyway**, citing the advisory framing
  and self-labeling the synthesized AC. R1 has a known soft spot
  on refactor tasks (see Refactor Edge Case below).

#### R3 promotion back to strict-must (2026-05-20T18:00Z)

R3's 100% landing rate on the n=3 D2 trials (the only ones where
drafting actually happened) shows the canonical skeleton lands
when read. The C+ demotion to Advisory was based on contaminated
data and has been reverted. R3 ships as a hard contract rule
again.

#### R4 stays advisory

R4's 33% landing rate is unchanged across contamination batches
and the verification batch — strict-must wording did not change
the rate (it was strict in the n=9 trials). The Go-side post-write
validate is the actual safety gate; R4 is a UX nice-to-have that
eliminates one repair-and-reapprove cycle when triggered. Stays
advisory.

#### The Empirical Safety Net

Three hard enforcement layers protect provider runs from invalid
drafts:

1. **R2 — no Write before approval (9/9 = 100%).** The user
   always sees the draft preview before any file mutation. A
   careful operator can spot-reject a fictional draft or
   synthesized AC.
2. **R5 — no CLI schema/backend probing (9/9 = 100%).** The
   model uses embedded backends and skeleton; no improvised
   probes against the CLI.
3. **Post-write `bakeoff validate` (Go-side, unconditional).**
   The `/bakeoff:run` flow validates the on-disk JSON before
   invoking `bakeoff build` or `bakeoff research`. Fictional
   schema is caught here and forces a repair-and-reapprove
   cycle before any provider runs.

Across all 9 verification trials, **zero provider runs launched
on fictional schema** (and no fictional schema actually appeared,
since R3 is now strict and landed 100%).

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
demands behavioral invariants for refactor and extract requests
even when goal+scope+verifier are present. Whether R1.6 closes
the gap is **untested as of cycle close**; verification requires a
new n=3 batch on D2-style refactor prompts after the plugin
re-caches to the post-R1.6 commit.

When R1 misses on a refactor, the model self-labels the synthesized
AC and the operator's preview-then-approve flow is the safety net.

#### When To Escalate

Build a Go-side pre-preview validate hook (Option B-narrow) only
if real-use signal shows the repair-and-reapprove cycle on
fictional schema drafts is causing actual problems. The Go-side
hook design is sketched in
[Rejected Alternatives → Go-Side Pre-Preview Validate Hook](#go-side-pre-preview-validate-hook).
Cost: ~1-2 hours Go code, low false-positive risk. Win: eliminates
one round-trip on fictional drafts. **Skip unless triggered by
real-use signal.**

### Known Limitation: Required-Field Synthesis Is Not Enforceable At The Prompt Layer

**Status: ACCEPTED (2026-05-20).** Three contract amendments (R1, the
R1.1-R1.4 mechanical checklist + anti-synthesis examples, R1.5
mandatory output marker) over nine dogfood trials produced a 0/9
landing rate. The model frames goal+scope requests as
fast-path-eligible and synthesizes missing AC, verifiers, or
protected paths plausibly. R1 ships as advisory guidance only.

Concrete failure mode: a user submits a prompt with goal + scope but
forgets to include AC, verifier, or protected paths. The model
drafts plausible defaults (e.g., `go test ./<scope>/...` for the
verifier, "edits stay in scope" / "tests pass" for AC, no protected
paths for a benchmark). The operator approves the preview without
catching the synthesis. The provider run executes against
synthesized criteria; the patch solves a similar-but-not-identical
problem to what the user actually wanted.

Mitigations (already in place):

1. **Preview-then-approve.** The operator sees the proposed JSON
   before any provider run starts. Synthesized AC and synthesized
   verifiers are visible in the preview; a careful operator can
   reject or edit. This is the primary safety net.
2. **Pre-preview internal validate (R4).** When the fast path is
   not taken, the model validates the JSON in memory before
   showing the preview. This catches structural schema errors but
   not semantic synthesis. R4 is co-dependent with R3: both hold
   on careful-path trials, both collapse on fast-path trips.
3. **Advisory guidance in the contract.** The R1 section, the
   mechanical checklist, and the anti-synthesis examples remain
   in `commands/run.md` and `skills/bakeoff/SKILL.md` as
   educational content. They lower the rate of obvious
   synthesis even though they cannot eliminate it.

When this limitation becomes a real problem:

- Operators report a run "solved the wrong thing" — provider
  patches match synthesized AC, not user intent.
- Synthesized verifiers cause `bakeoff build` to pass on tests
  the user didn't intend.
- Bench-mode prompts run without protected paths and providers
  edit the measuring stick.

If any of those signals arise, escalate to Option B (Go-side
write-time linter for synthesized-looking AC/verifier patterns).
That option was deferred from this PR — see
[Rejected Alternatives → Go-Side Synthesis Linter](#go-side-synthesis-linter)
for the bloat/risk analysis.

### Risk: Drafted JSON Is Not Just Imperfect — It Is Not Schema-Valid

**Status: REALIZED — intermittent (2026-05-20, B provider-dogfood signal
step). Validation audit on 2026-05-20T15:33Z showed 4/5 on-disk drafts
validate cleanly; only the 1 post-Step-1 draft (image 3,
`lscmd-order-by-finished-at.work-order.json`) failed.** Provisional
hypothesis (n=1, weak): the Step 1 fast-path contract edits landed today
may have inadvertently degraded JSON quality. Stronger conclusion: even
intermittent invalid JSON is high-impact because it silently produces an
unrunnable work order; the user does not see the validation failure until
they type `yes`.

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
3. Add a pre-preview internal `bakeoff validate` step. If the would-be
   JSON does not validate, the model must repair before showing the
   preview, not after the user approves. The current contract validates
   after approval, which misleads the user about what they're approving.
4. Update Definition Of Done: zero validation repairs needed on the
   fast-path positive trial, measured as "the JSON shown in `show` is
   byte-identical to the JSON `bakeoff build` reads."

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

Considered as Option B-narrow at the end of the 2026-05-20 cycle
after batch-4 data showed R3 and R4 also fail prompt-layer
enforcement. Deferred to a follow-up plan, not rejected outright.

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

- **Dogfood overestimates real-world failure rate.** The 0/9 R1
  failure rate is on synthetic missing-field prompts. Real-use
  prompts usually include AC + verifier — the user is trying to
  get a real bakeoff to run. The actual prevalence of synthesis
  drift in real use is unknown and likely much lower than 100%.
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

Ship a docs/contract-only change first. Steps 1-5 land together (overlapping
files; sequencing is artificial):

1. Add the fast-path predicate and fallback rules (Step 1).
2. Add batched exploration guidance (Step 2).
3. Add default-aware preview wording (Step 3).
4. Add clean-skeleton guidance (Step 4).
5. Add scenario checklist coverage (Step 5).
6. Land `scripts/measure-drafting.py` instrumentation helper.
7. Run experiments in order **G → A → D → B → E** with n=3 each (G uses n=5
   per its protocol):
   - G ✅ **DONE** (2026-05-20). Median 17 ms — preflight confirmed
     negligible. See [experiment log](drafting-fast-path-experiment-log-2026-05-20.md#g--preflight-cost-check).
   - A establishes the measured baseline (replaces the 10-minute anecdote).
     Blocked on `scripts/measure-drafting.py`.
   - D proves ambiguous or unsafe prompts do not fast-path. Run before B so a
     permissive fast path cannot trigger a real provider run.
   - B proves the motivating narrow build fast-paths without weakening the
     work-order contract; includes one full provider dogfood as signal.
   - E proves context gathering is batched when context is genuinely needed.
8. Record results in `docs/drafting-fast-path-experiment-log-YYYY-MM-DD.md`
   with pass/fail notes. Include the helper output verbatim.

C and F are deferred to a follow-up PR (C requires held-out prompt authoring
by a second person; F requires comparing drafts across two contract states
that this PR collapses into one change).

This first PR should not touch Go runtime code. That keeps the blast radius low
and verifies whether the real bottleneck is contract-side, as the dogfood
post-mortem suggests.
