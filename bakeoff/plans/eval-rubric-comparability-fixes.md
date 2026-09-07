# Eval rubric & comparability fixes — implementation plan

> Origin: audit of `bakeoff-live-agent-eval.r001.evaluator-2` (the gemini
> single-provider meta-eval that scored the six r001 conditions). The audit
> found the *arithmetic* sound but the *methodology* unsound. This plan fixes
> the methodology for future eval runs.

## Why this plan exists

The r001 eval produced precise-looking numbers (pairwise lift 2.33×, multilens
lift 2.48×/5.78×) that are **not trustworthy as a benchmark**. None of the
defects are Bakeoff core bugs — Bakeoff recorded the raw signals correctly. The
defects live in the **rubric** (hand-written prose in the work-order
`background`) and in the **absence of an external analysis/calibration layer**.

The repo already drew the architectural line in
`docs/paper-grade-experiment-analysis-implementation-plan-2026-06-05.md`:
Bakeoff keeps metadata labels + a stable manifest contract + a repetition
example; **analysis, statistics, evaluator calibration, and rubrics move
out**. This plan executes against that line.

## Run info (reproduce / investigate from here)

- Audited eval run dir: `runs/bakeoff-live-agent-eval.r001.evaluator-2/`
  (gitignored; staged copy of sources under `experiments/`).
- Source conditions (staged, readable): `experiments/bakeoff-live-agent-eval.r001.*`.
- Eval work order: `bakeoff-live-agent-eval.r001.evaluator-2.work-order.json`
  (untracked). The rubric is the STEP 1/2/3 prose in its `background`.
- Re-derive any number with: read each source `manifest.json`
  (`started_at`/`finished_at`/`providers`) and the eval `report.md` ledger.

## Confirmed sound — do NOT "fix" these

- **Wall-time source field**: `finished_at − started_at` per source manifest is
  correct (498/336/664/773/264/755s all verified).
- **Score/precision/union arithmetic**: independently recomputed; reproduces to
  the digit (9/9/21/52; 87.5/100/92.3/100%; union=41). Not hallucinated.
- **Findings are real**: spot-checked cited findings exist in source `report.md`.
- **Manifest raw contract**: timestamps + provider list are accurate. Keep
  Bakeoff core out of scope (see non-issues).

## Defects → fix surface (ranked)

### 1. Wall time summed across parallel lenses  (CONFIRMED, high impact)
All three multilens lenses started at the identical timestamp (`18:31:10Z`) —
they ran **concurrently**. The rubric summed them (773+264+755 = 1792s); true
elapsed = **max = 773s**. The reported number is cumulative compute mislabeled
as wall time.
- **Surface:** rubric prose + external analysis script.
- **Fix:** define two distinct metrics — `wall_clock_elapsed_s = max(finish) −
  min(start)` over concurrently-launched runs, and `cumulative_provider_s = Σ`.
  Detect concurrency from overlapping `[started_at, finished_at]` intervals, not
  from labels. Never present the sum as "wall time."

### 2. Conditions reviewed different surfaces  (CONFIRMED, high impact)
single/pairwise are general code-review; the three multilens lenses have
specialized focuses (artifact-contract, test-coverage, operator-docs). The
operator-docs lens surfaced a finding *category* the others never sought. So
multilens "coverage" largely reflects 3× more review surface, not superiority.
- **Surface:** work-order **templates** + experiment recipe.
- **Fix:** all conditions in a comparison must review **one shared task
  surface** (same files/diff, same finding taxonomy), anchored by a shared
  `experiment.task_id`. Lens specialization is allowed only as a *within-
  multilens* decomposition of that same surface, not a different surface.

### 3. Union coverage is circular  (CONFIRMED, medium impact)
The 41-cluster union denominator is built from the same evaluator's own
clustering; multilens contributed 31/60 raw rows, so it mechanically dominates a
union it largely defines.
- **Surface:** rubric + external analysis.
- **Fix:** clustering must be done **independently of condition identity** (blind
  to which condition a finding came from) before union/coverage is computed.
  Report cluster-merge decisions as an auditable artifact. Consider a fixed,
  pre-registered ground-truth issue set instead of a self-derived union.

### 4. score/call ignores judge calls  (CONFIRMED, medium impact)
Each multilens lens is `run_mode: pairwise` → 6 worker calls **+ 3 judge
calls**; pairwise = 2 + 1; singles = 1 + 0. The cost metric counts only
workers, understating multi-judge conditions.
- **Surface:** external analysis script (cost accounting — explicitly "move
  out" per the paper-grade plan).
- **Fix:** cost denominator = worker calls + judge calls (and optionally token
  or wall cost). Report score per *total* provider invocation.

### 5. Self-refereed validity / no judge  (CONFIRMED, high impact)
The evaluator was `single_provider` → no judge ran. Every valid/severity call is
one unaudited model opinion. Multilens precision = 100% (31/31) is a red flag;
severity never exceeded 3 (blocker=5 tier unused).
- **Surface:** evaluator **work-order** + calibration layer.
- **Fix:** run the evaluator as a 2-provider `analyze`/`compare` with a
  **cross-family judge**, or add a second-model / human calibration pass.
  Report inter-rater agreement. Treat single-model validity as provisional.

### 6. n = 1  (CONFIRMED, medium impact)
One repetition per condition (`r001`); ratios on integer scores of 6–14
findings. No variance, no CI.
- **Surface:** repetition harness.
- **Fix:** run `REPETITIONS ≥ 3` via `examples/repetition-loop.sh` with
  `experiment.repetition_index`; report mean ± spread, not point ratios.

## Work items (where the code/docs actually land)

1. **`examples/eval-rubric-recipe.md`** (NEW) — versioned, reviewed rubric. The
   STEP 1/2/3 methodology with the corrected rules from defects #1–#5 baked in
   (parallel-aware wall time, shared surface requirement, blind clustering,
   judge-inclusive cost, judged/calibrated validity). Replaces ad-hoc
   `background` prose. Cross-link from `examples/README.md`.

2. **Eval work-order template** (NEW, under `examples/` or alongside the recipe)
   — analyze/compare work order that (a) points all conditions at one shared
   `task_id` surface, (b) uses a 2-provider evaluator + cross-family judge,
   (c) carries `experiment` labels. Validates with `bakeoff validate`.

3. **External analysis script** (NEW, OUTSIDE the plugin — e.g. a `scripts/` or
   separate repo per the paper-grade plan) — reads staged run artifacts and
   computes: parallel-aware `wall_clock_elapsed_s` + `cumulative_provider_s`,
   judge-inclusive cost, blind clustering, union/precision, per-condition score,
   lift with repetition mean ± spread. Emits a report table. **No scoring logic
   in Bakeoff core.**

4. **`docs/` methodology note** (NEW or fold into the paper-grade plan) — record
   the five rules so they are not re-discovered each run: parallel wall time,
   shared review surface, blind clustering, judge-inclusive cost, judged
   evaluator with reported agreement.

5. **`examples/README.md`** (EDIT) — link the recipe + template; note the
   `OUT_DIR=experiments` requirement for gemini evaluators (gitignore caveat
   already documented in `repetition-loop.sh`).

## Explicit non-issues (do not act)

- **No Bakeoff core (`internal/`, `cmd/`) changes.** Manifests already record
  the correct raw fields; interpretation is the external layer's job.
- Do not add a scheduler, matrix expansion, parallel-exec, or statistics export
  into Bakeoff — the paper-grade plan scopes these out.
- Do not "fix" the `experiments/` staging convention — it is the intended
  workaround for gemini's gitignore-aware reads.

## Open questions to close before building

- Ground-truth issue set: pre-register a fixed defect list, or keep a
  blind-clustered self-derived union? (Affects #3.)
- Evaluator pairing: 2-provider `analyze` vs `compare` with which cross-family
  judge? (Affects #5; pick a judge not in either evaluator family.)
- Where does the external analysis script live — `scripts/` in this repo
  (convenient) or a separate analysis repo (cleaner per paper-grade plan)?

## Definition of done

- A reviewed `examples/eval-rubric-recipe.md` encodes the five corrected rules.
- A validating eval work-order template enforces a shared review surface and a
  judged (cross-family) evaluator.
- An external script reproduces r001's *sound* numbers and corrects the wall-
  time, cost, clustering, and repetition handling — producing numbers that are
  defensible as a benchmark.
- `docs/` records the methodology; `examples/README.md` links it.
- Re-running the r001 conditions through the new recipe yields wall time ≈ 773s
  for multilens (not 1792s) and judge-inclusive cost, with the methodology
  auditable end to end.
