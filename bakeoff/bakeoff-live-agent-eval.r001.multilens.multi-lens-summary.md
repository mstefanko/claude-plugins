# Multi-lens review summary — bakeoff-live-agent-eval.r001.multilens

Target diff: `386accc..HEAD` · pair `claude/sonnet` + `codex/gpt-5.5` · judge `claude/opus` · **triage disabled (`--no-triage`)**.

> **All findings below are RAW / UNVERIFIED.** Triage was disabled, so no run filtered false positives, already-fixed items, or evidence gaps. Treat every finding as a lead requiring confirmation against the cited file:line.

## Lens status

| Lens | Run id | Result | Exit | Providers | Report |
|------|--------|--------|------|-----------|--------|
| artifact-contract | `bakeoff-live-agent-eval.r001.multilens.artifact-contract` | `structured_union` (no winner) | 0 | claude ok, codex ok | `runs/bakeoff-live-agent-eval.r001.multilens.artifact-contract/report.md` |
| test-coverage | `bakeoff-live-agent-eval.r001.multilens.test-coverage` | `single_provider_only` (winner codex) ⚠ | 0 | **claude schema_error**, codex ok | `runs/bakeoff-live-agent-eval.r001.multilens.test-coverage/report.md` |
| operator-docs | `bakeoff-live-agent-eval.r001.multilens.operator-docs` | `structured_union` (no winner) | 0 | claude ok, codex ok | `runs/bakeoff-live-agent-eval.r001.multilens.operator-docs/report.md` |

Inspect: `bakeoff show bakeoff-live-agent-eval.r001.multilens.artifact-contract` · `… .test-coverage` · `… .operator-docs`.

> ⚠ **test-coverage is single-provider only.** The Claude worker failed schema validation (`recommended_next_checks` returned objects, not strings) even after a format retry; only Codex findings are present, with no cross-provider dedupe. Treat that lens's coverage as partial.

## Most actionable findings by lens

### artifact-contract (18 items; both providers, no winner)
- **F-002 (medium)** `scope.go:110` flips `enforcement_level` `partial`→`enforced` when `len(mechanisms)>0 && len(fallbackReasons)==0`. Consumers branching on `"partial"` change behavior; backward-compat with prior artifacts not verified.
- **F-006 (medium)** `manifest.go:384-395` experiment fallback reads `workOrder` (`map[string]any` from JSON), so `repetition_index` arrives as `float64`; if not int-coerced it diverges from the meta path and the strict `*int` unmarshal at `verify.go:206`.
- **F-009 (medium)** `manifest.go:385-407` — a partial `meta.experiment` shadows the complete archived work order, so required experiment labels can be omitted from `manifest.json`.
- **F-010 (medium)** `verify.go:85-221` — `runs verify --json` fails open: missing required experiment fields are backfilled with `""`/null instead of being flagged.
- **F-005 / F-008 (low/med)** `decision.go:228-231` writes both `selection_basis` and `spine_tiebreak` (identical values); `manifest.go:476` prefers `selection_basis`, so `spine_tiebreak` is dead on new runs and research `--json` summaries omit `selection_basis` that build summaries expose.
- **F-004 / F-013 (low)** `verify.go:350-379` single-provider validator omits `selection_basis` and `run_mode` assertions — corrupted decision.json passes silently.
- **F-014/F-015/F-016 (conflict/unknown)** Providers disagree on whether single-provider `decision.json` actually persists `run_mode`; if absent, the `report.go:1132` glossary gate is a no-op. Worth confirming in `SingleProviderResult`.

### test-coverage (11 items; CODEX ONLY — partial)
- **F-007 (high)** `researchcmd/run.go:61-232` reclaim path: tests do **not** assert that a dir containing `decision.json`/`manifest.json` is preserved without `--force`; a regression could delete a completed run on run-id retry.
- **F-001/F-002/F-010/F-011 (medium/low)** Experiment-metadata tests supply `task_id`/`condition_id`/`run_kind`/`repetition_index` in fixtures but never assert them (manifest, verify, research-summary, build-summary). A regression dropping those fields stays green.
- **F-003/F-004 (medium)** New single-provider verifier branches (invalid decision_kind, missing single_provider, judge flags) and the manifest-vs-decision `run_mode` OR-trigger are only partially asserted; neither OR source is covered independently.
- **F-005 (medium)** Diagnostic-stderr truncation test covers only a *successful* provider, leaving the `ProviderSucceeded` guard untested for failed providers.

### operator-docs (17 findings + conflict/unknowns; both providers, no winner)
- **Dominant theme — plan/doc drift (multi-source, medium):** the new hardening/plan docs describe work that the **same diff already shipped**. Confirmed across both providers:
  - **F-005** artifact-contract plan still frames `summary.json` Option A/B as the sole ship-blocker, but `work-orders.md` already chose "command JSON summaries".
  - **F-006/F-007** plan's two `## P2` items ("stale pairwise wording", "verify lacks single-provider semantics") are already implemented (`report.go reportGlossary` gate; `verify.go validateSingleProviderDecision`).
  - **F-008/F-009** telemetry-plan Findings 1 & 4 (`selection_basis: null`, `enforcement_level: partial`) already corrected in `decision.go`/`scope.go`.
  - **F-010/F-014/F-015** plan-review/telemetry plans still list stderr-truncation alarm, slash-prose path warnings, and missing trunc indicator as open — all already resolved.
  - **F-011/F-012/F-013** `plans/single-provider-hardening-plan.md` and `plans/experiment-metadata-hardening.md` (incl. `Status: "no code written yet"`) describe implemented code as open gaps.
- **F-001 (medium)** `single-provider-artifact-contract-hardening-plan-…md` has **two `## P2` headings** — breaks priority ordering.
- **F-002 (medium)** `plans/single-provider-hardening-plan.md` P3 tells operators to grep `summary.go` for the glossary, but it lives in `report.go:reportGlossary` — instruction dead-ends.
- **F-004 (medium)** `work-orders.md` references `bakeoff triage` explicitly, but no `bakeoff triage` section exists in the `cli-reference.md` diff (see also unknown F-019 — may exist pre-diff).
- **F-016 (low)** `cli-reference.md:298-300` documents a `canonical_winner` key in the build JSON summary, but `buildcmd/summary.go` emits only `winner`.

## Cross-lens overlap
- **`enforcement_level` partial→enforced**: artifact-contract F-002, test-coverage F-008, operator-docs F-009.
- **`selection_basis`/`spine_tiebreak` dual field & untested tiebreaks**: artifact-contract F-005/F-008, test-coverage F-009, operator-docs F-008.
- **Single-provider verifier gaps (missing assertions)**: artifact-contract F-004/F-013, test-coverage F-003/F-004.
- **Diagnostic-stderr truncation undercount**: artifact-contract F-011, test-coverage F-005, operator-docs F-010.
- **`bakeoff triage` reference validity**: operator-docs F-004 + unknown F-019.

These overlaps were surfaced independently per lens; corroboration is not proof of correctness (esp. with triage off).

## Clean lenses
None. All three lenses surfaced actionable findings.

## Caveats
- Triage disabled → all findings raw/unverified.
- test-coverage lens is single-provider (codex only) due to a Claude schema_error; coverage is partial and not cross-checked.
- `latest` may point to any one of the three children, not the group. Use the explicit run ids above.
- Several operator-docs items depend on files not in the diff (`examples/repetition-loop.sh`, a pre-diff `bakeoff triage` section); see that lens's Unknowns F-019–F-021.

## Optional Synthesis
**Not requested.** A separate `type: "analyze"` synthesis pass over the three completed reports could dedupe the cross-lens overlaps into one prioritized fix plan (preferring corroborated/multi-source items). Usable artifacts exist for all three lenses, so this is available on request. I will not run it automatically.
