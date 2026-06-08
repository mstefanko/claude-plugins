# Plan Review: Soundness and Implementation Clarity (2026-06-05)

Review target: `docs/paper-grade-experiment-analysis-implementation-plan-2026-06-05.md`
Reviewer scope: design soundness, fit with existing architecture, statistical
rigor, and whether each phase is concrete enough for a writer to execute.

## Overall Assessment

The plan is **directionally sound and architecturally respectful**. Its core
decision — keep child runs as ordinary `runs/<run-id>/` ledgers and add
experiment grouping + analysis surfaces around them — is the right call and fits
how Bakeoff already works (`ls`, `show`, `runs verify`, `manifest.json`,
`meta.json` all stay valid). The phasing is also correct: metadata spine first,
scheduler later, statistics last. The research basis is unusually thorough and
the methodological instincts (separate judge preference from verifier evidence,
nullable cost, conservative CIs, calibration before scaling) are correct.

However, it is **a strong architecture document, not yet an execution-ready
implementation plan.** It is execution-ready for **Phase 1 only**. Phases 2-7
are specified at the level of "what artifact and what fields," not "what
function, what signature, what call site, what failure semantics." A writer
handed Phase 3 (scheduler) or Phase 6 (analysis/statistics) today would have to
make many load-bearing design decisions that the plan leaves open. Several of
those decisions interact (run-id shape vs. ledger conventions; scheduler
process model vs. the existing single-run command structure), so they should be
resolved before, not during, implementation.

Verdict in one line: **approve Phase 1 as written; require a design pass on
the run-id/uniqueness convention, the scheduler execution model, and the
statistics module contracts before Phases 2-7 are handed to a writer.**

---

## Per-Piece Analysis

### Layer 1 / Phase 1 — Experiment Metadata (metadata-only)

**Makes sense?** Yes. This is the keystone and it is low-risk.

**Design sound?** Yes, and it fits the codebase well:
- Top-level work-order validation only checks for *required* fields
  (`workorder.go:264`, the `for _, field := range []string{...}` loop). There is
  **no top-level unknown-key rejection** — `facet` and `verifier` reject unknown
  keys, but the top level does not. So adding an optional `experiment` block (and
  later a `run` block) will not break existing work orders. Good.
- `meta.json` is a free-form `map[string]any` written in
  `artifact.WriteMetaWithExtra`, and there is already an `extra` channel. Copying
  the full `experiment` object in is mechanically easy.
- `manifest.json` is also a `map[string]any` assembled in `manifest.go`; hoisting
  flat fields follows the existing pattern (`facet_id`, `source_run_id`,
  `escalation_mode` are already hoisted this way).
- `ls --json` already projects a fixed field set in `manifest.RowForLS`; adding
  experiment fields and an `--experiment` filter mirrors the existing
  `--source-run`/`SourceRun` filter exactly.

**Clarity gaps (small, resolvable by the writer):**
1. The plan says "validate ids/enums and integer fields" but does not give the
   slug regex to reuse. Use the existing `slugRE`
   (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) for `id`, `task_id`, `condition_id`,
   `slot_id`, `provider_pair_id`, `lens_id` so they stay file-path-safe and
   consistent with work-order `id` and `facet.id`.
2. The `experiment` block introduces nested objects (`sampling`, `artifacts`)
   whereas existing nested objects (`facet`, `verifier`) enforce a closed key
   set. Decide explicitly: does `experiment` reject unknown keys (consistent
   with `facet`) or accept them (forward-compatible)? The plan implies open
   (it leaves several fields `null`), but the codebase convention is closed.
   This must be stated or the writer will guess.
3. `repetition_index` and `slot_attempt` are integers; reuse `asInt` and add the
   range check (`>= 0` or `>= 1` — pick one and write it down; the example uses
   `1`-based).
4. "summary JSON: optional `experiment` object" — there are two summaries
   (research `internal/summary` and `buildcmd/summary.go`). State which, or both.

**Verdict: execution-ready** after points 1-4 are pinned (a 2-3 line addendum).

---

### Layer 1 parent layout / Phase 2 — Parent Experiment Artifact

**Makes sense?** Yes — a parent `experiment.json` that scans child manifests by
`experiment_id` is the standard pattern (MLflow/W&B) and reuses existing
manifests as the source of truth.

**Design sound?** Mostly, but with one real architecture collision:

- **`runs/experiments/<id>/` lives inside the same `runs/` dir that `ls` scans.**
  The plan acknowledges this ("teach `ls` to ignore `runs/experiments/`") but
  `ls`/`RowForLS` currently treats every immediate subdir of `--out` as a run
  and falls back to `legacyLSRow(runDir, "missing")` when there is no manifest.
  An `experiments/` dir would currently show up as a broken run row. The fix is
  named but not specified: is `experiments` a *reserved* directory name (so a
  real run can never be named `experiments`)? That needs to be added to run-id
  validation, and `runs verify`/`bundle`/`history` need the same exclusion, not
  just `ls`. The plan lists only `ls`.

**Clarity gaps:**
1. No schema is given for `experiment.json` beyond a field list. A writer needs
   the Go struct or a concrete JSON example (the work-order example is concrete;
   this one is not). Specify `schema_version` value, required vs optional fields,
   and the `children[]` element shape (run-id only? run-id + condition + status?).
2. "Add scan helpers for child manifests by `experiment_id`" — define where this
   lives (`internal/experiment`) and its signature, and the behavior on a child
   whose manifest exists but has no `experiment_id` (ignore) vs. one whose
   manifest is corrupt (warn). The acceptance test says "warnings, not panics"
   but the warning channel (stderr? a field in summary.json?) is unspecified.
3. "Add `summary.json` and `summary.md` generation" is deferred ("can be added
   after child metadata is stable") yet Phase 2's acceptance tests list parent
   summary behavior. Decide whether summaries are in Phase 2 or later; right now
   the phase is internally inconsistent.

**Verdict: needs a schema + a reserved-dir decision before implementation.**

---

### Layer 2 / Phase 3 — Controlled Repetition Scheduler

This is the **least execution-ready** phase and the highest-risk one.

**Makes sense?** The intent (deterministic slot expansion, resume, no-overwrite
retries) is right and matches SWE-bench/lm-eval-harness practice.

**Design soundness concerns:**
1. **Execution model is undefined.** `bakeoff experiment run` must launch many
   child runs. The existing commands (`researchcmd/run.go`, `buildcmd/run.go`)
   are single-run, in-process, and own their own run dir. Does the scheduler
   (a) invoke the `bakeoff` binary as a subprocess per child, (b) call the
   `researchcmd`/`buildcmd` run functions in-process in a loop, or (c) call them
   in goroutines for `--parallel M`? The plan lists `researchcmd/run.go` and
   `buildcmd/run.go` in Phase 3 files (implying in-process calls) but those run
   functions are not currently structured as reentrant library calls (they print
   to `f.Streams()`, resolve their own run id, write `latest`). `--parallel M`
   over in-process calls that each write a shared `runs/latest` file is a race.
   This must be designed, not discovered.
2. **Run-id shape conflicts with conventions.** Proposed child id
   `<experiment-id>.r001.<provider-pair-id>.<lens-id>` will *pass* `ValidateRunID`
   (the regex allows `.` and `-`), so it is technically legal. But it abandons
   the `MakeRunID` date-prefix convention (`YYYY-MM-DD-xxxx`) that `ls`/`history`
   sorting and humans rely on, and it can collide on re-run of the same plan
   (same id deterministically → would overwrite a prior experiment's child). The
   plan says "never overwrite counted evidence" and "retry creates a new attempt"
   but the id formula has no attempt component, so two attempts of the same slot
   produce the *same* directory name. `slot_attempt` exists in metadata but not
   in the id. This is a direct contradiction that must be resolved (e.g.
   `...r001.<pair>.<lens>.a01`).
3. **Matrix semantics undefined.** `--matrix providers=claude:sonnet,codex:gpt-5.5`
   plus `--lenses security,correctness` plus `--repetitions N`: is the cross
   product (pairs × lenses × reps)? How are *pairs* formed from a provider list
   (the work order needs exactly 2 providers — `workorder.go:421`,
   `draft.go:137`)? `provider_pair_id` implies a pair, but the matrix syntax
   lists individual providers. The mapping from CLI matrix flags to concrete
   2-provider work orders is the heart of the scheduler and is completely
   unspecified.
4. **`task_snapshot_sha256` is referenced everywhere but never defined.** What is
   hashed? For research there is no source tree; for build there is `base_ref`.
   Define the canonical input set that the hash covers (work-order JSON minus
   volatile fields? source commit? evaluator pack?) — otherwise `--resume`'s
   "validate the parent snapshot hash" check is unimplementable.

**Clarity gaps:** retry taxonomy ("transient infrastructure failure" vs.
"counted failure") is asserted but there is no mapping from existing
`decision_kind`/exit-code/`runner.classify` results to those buckets. The runner
already classifies failures (`internal/runner/classify.go`); the plan should say
which classifications count as transient.

**Verdict: not execution-ready. Needs a dedicated design doc for the execution
model, run-id/attempt scheme, matrix→work-order expansion, and snapshot hash.**

---

### Layer 3 / Phase 4 — Single-Agent Baseline

**Makes sense?** Yes, and the distinction from `single_provider_only` is
correct and important. Today `single_provider_only` is a *build* `decision_kind`
emitted when only one of two providers produced an eligible patch
(`decision.go`); it is genuinely a degraded-bakeoff signal, not a baseline. The
plan correctly refuses to overload it.

**Design soundness concerns:**
1. **Two enforcement sites, not one.** `providers must have exactly 2 entries`
   is enforced in **both** `validateProviders` (`workorder.go:421`) and the
   drafting path `draft.go:137-138`. Adding `run.kind: single_agent_baseline`
   that requires exactly one provider means changing both, and the validation
   must branch on `run.kind` *before* the provider-count check. The plan lists
   `workorder.go` but not `draft.go`; the writer will miss the draft path and
   ship a CLI that validates baselines but cannot draft them.
2. **`judge` is a required top-level field** (`workorder.go:264`) and
   `validateJudge` requires it differ from both providers. Making `judge`
   optional for baselines means removing it from the required list conditionally
   and handling `judge: null`. The plan says "judge absent or null" — confirm
   which (the required-field loop checks *presence*, so `judge: null` present
   passes the loop but fails `validateJudge`'s object assertion;
   *absent* fails the loop). Pick one; they need different code.
3. **Prompt parity is asserted but not specified.** "Remove peer/judge/dedup
   wording from research worker prompts in baseline mode" — the worker prompts
   live in `internal/prompt` fixtures. The plan does not say whether this is a
   new fixture variant, a template conditional, or runtime string surgery. This
   is a correctness-sensitive change (parity is the whole point of a baseline)
   and needs a concrete mechanism.
4. New decision kinds (`single_agent_baseline`, `single_agent_failed`,
   `baseline_failed`, `single_agent_failed_verification`,
   `single_agent_ineligible`) are proposed but not reconciled with the existing
   decision-kind enum used by `manifest`/`ls`/`report`. `ls` validates a `--type`
   enum but decision kinds flow through more loosely; still, `report.go` and the
   summaries switch on decision kind. Enumerate the full set and the exit code
   for each (research uses exit 4 for judge-failed; what exit code is a
   baseline?).

**Verdict: design is right; needs the dual-enforcement, judge-optionality, and
prompt-parity mechanisms pinned. Medium effort once pinned.**

---

### Layer 4 / Phase 5 — Evaluator Packs

**Makes sense?** Yes — versioned, hashed, copied-into-ledger evaluator packs are
the correct way to make judging reproducible and are well-grounded in the cited
literature.

**Design soundness concerns:**
1. **Built-in pack must reproduce today's prompts byte-for-byte.** The plan says
   "default built-in packs reproduce today's fixture rubrics so old work orders
   behave the same." Today rubrics are embedded in `internal/prompt` fixtures and
   composed at runtime (the prompt code has facet-conditional rule blocks, e.g.
   the code-review witness rules seen in `prompt.go`). Extracting these into a
   `pack.json` + `rubric.md` and re-injecting via an `<evaluator_pack>` block
   risks changing the prompt text (and therefore judge behavior and every prompt
   hash). The plan needs a concrete parity strategy: golden-prompt snapshot tests
   proving the built-in pack produces identical judge prompts to today's path.
   "Preserve built-in packs" is stated as a goal but the parity *test* is the
   hard part and is only implied.
2. `judge/prompt-manifest.json` is a new artifact; confirm it gets added to
   `CoreFingerprintArtifacts` in `manifest.go` (the plan says "include in
   fingerprints" — good, but name the constant).
3. Pack resolution path: `evaluator_pack.path` is relative — relative to what?
   cwd? work-order dir? a bundled packs dir? "Missing required pack fails before
   provider spend" requires resolution to happen at validation time, before the
   run dir even exists. State the resolution root.

**Verdict: sound; the parity test strategy and pack-path resolution root must be
specified. This is the phase most likely to silently change behavior.**

---

### Layer 5 / Phase 6 — Analysis and Export

**Makes sense?** Yes — read-only export over manifests, with conservative stats,
before any leaderboard UI, is the right sequencing.

**Design soundness concerns:**
1. **The export depends on fields that earlier phases must guarantee.** Many
   export columns (`provider_pair_id`, `lens_id`, `selection_basis`,
   `slot_attempt`, evaluator hashes, trace `capture_level`) only exist if the
   relevant phase shipped. The export spec should declare every field
   *nullable* and the writer should not assume presence. The "Analysis Fields To
   Keep Stable" section is good but does not mark nullability.
2. **`comparisons.jsonl` semantics for non-pairwise runs.** Single-agent
   baselines have no comparison; multi-lens children are separate runs. Define
   what a comparison row is for a baseline (none) and how cross-condition
   comparisons (baseline vs. pairwise) are represented — the paper claim
   ("multi-agent improves over single-agent") is a *cross-run* comparison, but
   `comparisons.jsonl` as specified is *within-run* (left/right provider). The
   plan does not define the cross-condition comparison row, which is the actual
   unit the headline claim needs.

**Statistical concerns: see the dedicated section below.**

**Verdict: needs the statistics contracts pinned (below) and the
cross-condition comparison unit defined. Otherwise structurally sound.**

---

### Layer 6 / Phase 7 — Trace Depth

**Makes sense?** Yes, and the honesty rule ("Bakeoff cannot recover hidden
reasoning… `capture_level` honestly") is exactly right and the most important
sentence in this section.

**Design soundness:** Good. Codex-first is the right call because the launch path
already uses `codex exec ... --output-last-message` and adding `--json` NDJSON
teeing is incremental. The argv builder (`BuildParticipantArgv` in `provider.go`)
already special-cases each backend, so adding trace flags has an obvious home.

**Clarity gaps:**
1. Bounded-file teeing: "tee raw structured streams to bounded files" — specify
   the cap (reuse `budgets.max_output_bytes`? a separate trace cap?) and the
   truncation marker, consistent with how stdout capture is already bounded.
2. Gemini "isolated per-run OTel setup without mutating user settings" is flagged
   as conditional — keep it explicitly out of scope for the first trace slice; do
   not let it block Codex.

**Verdict: lowest-risk of the later phases; can be scoped to Codex-only and
shipped independently.**

---

## Methodological / Statistical Concerns (paper-grade rigor)

The plan's statistical instincts are good but several methods are named without
the assumptions that make them valid. For a paper-grade claim these are not
nitpicks — they are the difference between a defensible result and a retracted
one.

1. **Unit of analysis / non-independence.** Bootstrapping "over run rows" for
   pairwise rates is only valid if rows are independent. Repetitions of the
   *same task* are not independent observations of "quality"; they are repeated
   measures on one task. With one or few tasks, the CI will be far too narrow
   (pseudo-replication). The plan must state the resampling unit: bootstrap over
   **tasks** (cluster bootstrap), not over runs, when generalizing across tasks.
   This is the single most important methodological fix.

2. **`pass@k` vs `pass^k` applicability.** `pass@k` (HumanEval estimator)
   measures *objective* success on a verifiable task. It is meaningful for
   **build** runs with a real verifier gate. It is **not** meaningful for
   research/compare runs whose only signal is LLM-judge preference — there is no
   ground-truth "pass." The plan applies `pass@k`/`pass^k` generically; it should
   restrict them to runs with an objective gate and forbid them on judge-only
   modes. Otherwise the appendix will report a rigorous-looking metric over a
   subjective signal.

3. **LLM-judge bias quantification, not just controls.** Position swap is already
   done (the existing judge runs pass1/pass2 with swapped order — `decision.go`).
   The plan should *report the swap-disagreement rate* as a first-class metric
   (it is the position-bias estimate Bakeoff already has the data for) rather
   than only using it to declare ties. Self-enhancement bias (a Claude judge
   preferring Claude output) is named in the research basis but the plan has no
   mechanism to detect it; for the headline claim, judge identity must be
   recorded and, ideally, the judge must be a third backend distinct from both
   compared providers (the existing `validateJudge` already forbids
   judge==provider by backend+model, which helps, but does not prevent
   same-family judging).

4. **Multiple comparisons.** A matrix of pairs × lenses × tasks produces many
   simultaneous comparisons. The plan reports per-comparison CIs but no
   family-wise correction or explicit "exploratory, not confirmatory" framing.
   For paper grade, state the correction (or pre-register the single primary
   comparison and treat the rest as exploratory).

5. **Tie handling is a modeling choice, not a footnote.** "Decisive win rate"
   vs. "tie-adjusted win rate" need exact definitions (does a tie count as 0.5,
   or is it excluded?). Both are defensible but they yield different numbers;
   the formula must be in the spec, deterministic, and seed-independent.

6. **Calibration sample-size honesty.** The calibration output lists
   "human-human agreement" and "judge-human agreement" but with the small label
   counts likely in practice, agreement statistics (e.g. Cohen's kappa) are
   themselves high-variance. The acceptance test ("handle empty, small, skewed,
   low-agreement labels") is good; add: report CIs on the agreement statistics
   and refuse to claim calibration below a stated minimum N.

7. **Cost-quality is correctly nullable.** Good. One addition: wall-time and
   output-bytes are *not* proxies for cost and should never be substituted into a
   cost-quality curve; the plan says this in the risks section — make it a hard
   rule in the export code, not just prose.

---

## Concrete List: What Must Be Clarified Before Implementation

Ordered roughly by phase / dependency.

**Phase 1 (small — pin and go):**
1. `experiment` block: closed key set (reject unknown keys, like `facet`) or
   open? State it.
2. Reuse `slugRE` for all experiment id-like fields; state min/max and 0- vs
   1-based for integer indices.
3. Which summary(ies) get the `experiment` object — research, build, or both.

**Phase 2:**
4. Concrete `experiment.json` schema (struct + JSON example), including
   `children[]` element shape and `schema_version` value.
5. Make `experiments` a **reserved run-id** and exclude `runs/experiments/` from
   *all* run scanners (`ls`, `history`, `runs verify`, `bundle`), not just `ls`.
6. Decide whether parent summaries are in Phase 2 or deferred (remove the
   internal inconsistency in the acceptance tests).

**Phase 3 (needs a design doc):**
7. Scheduler execution model: subprocess vs in-process vs goroutines; and how
   `--parallel M` avoids races on shared `runs/latest` and run-id allocation.
8. Child run-id scheme that includes `slot_attempt` so retries do not collide,
   and a decision on keeping vs dropping the `YYYY-MM-DD` date prefix.
9. Matrix→work-order expansion: how a provider list + lenses + repetitions maps
   to concrete 2-provider work orders and `provider_pair_id`s.
10. Definition of `task_snapshot_sha256`: exact input set hashed, for research
    and for build.
11. Mapping from existing `runner.classify` / exit codes / decision kinds to the
    "transient vs counted" retry buckets.

**Phase 4:**
12. Branch the provider-count rule on `run.kind` in **both** `workorder.go:421`
    and `draft.go:137`.
13. Decide `judge: null` (present) vs `judge` absent for baselines; they need
    different validation code.
14. Concrete prompt-parity mechanism for baseline worker prompts (fixture
    variant vs template conditional) + a parity test.
15. Full enumeration of baseline decision kinds and their exit codes.

**Phase 5:**
16. Golden-prompt parity test proving the built-in evaluator pack yields
    byte-identical judge prompts to today's path.
17. `evaluator_pack.path` resolution root (must resolve at validation time,
    pre-run).
18. Name the `CoreFingerprintArtifacts` additions (`judge/prompt-manifest.json`,
    evaluator files).

**Phase 6:**
19. Mark every export field nullable; do not assume later-phase fields exist.
20. Define the **cross-condition** comparison unit (baseline vs pairwise) — the
    actual unit the headline claim needs — distinct from within-run
    `comparisons.jsonl`.
21. Statistics contracts: resampling unit = task (cluster bootstrap); restrict
    `pass@k`/`pass^k` to objective-gate runs; exact tie-rate formulas; report
    swap-disagreement rate; multiple-comparison stance; agreement-stat CIs and
    minimum N.

**Phase 7:**
22. Trace file size cap + truncation marker (reuse output budget or separate).
23. Explicitly scope first trace slice to Codex; defer Gemini OTel.

---

## Summary Verdict

- **Phase 1: execution-ready** after a short addendum (items 1-3). Approve.
- **Phases 2, 4, 5, 7: design-sound but under-specified** — each needs a handful
  of named decisions pinned before a writer starts, but no rethink.
- **Phase 3 (scheduler): not execution-ready** — needs a dedicated design pass on
  the execution model, run-id/attempt collision, matrix expansion, and snapshot
  hash. This is the riskiest phase and the one most likely to be reworked if
  implemented from the plan as written.
- **Statistics (cross-cutting Phase 6): needs the resampling unit and metric
  applicability rules fixed** before any number is reported, or the "paper-grade"
  claim is not defensible.

Recommended next step: ship Phase 1 from this plan; commission a short Phase 3
scheduler design doc and a one-page statistics methods spec; then the remaining
phases are ready to hand to a writer.
