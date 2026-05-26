# Dogfood findings — actionable items from the bakeoff reports

Source: the four `dogfood-artifacts-telemetry-split` reports on 2026-05-25.

## Run context

| Run id | Question | Winner | Tiebreak | Kept From Nonwinner |
| --- | --- | --- | --- | --- |
| `dogfood-artifacts-telemetry-split.part-1` | Can the research-replay + artifact-copy logic in `internal/commands/researchcmd/run.go` be extracted into a reusable component, or hardened in place? | codex | `atomic_count` (weak) | 4 items from claude |
| `dogfood-artifacts-telemetry-split.part-2` | Are `internal/manifest` telemetry + `internal/provider` family metadata sufficient to measure judge-bias per `docs/agentic-loop-evidence-synthesis-2026-05-23.md`? | claude | `swap_agreement` (strong) | 7 items from codex |
| `2026-05-25-6b7a` | Independent escalation of part-1 (+gemini, claude-opus synthesis) | codex (supported source) | n/a | 0 |
| `2026-05-25-5e29` | Dispute escalation of part-2 (+gemini, advisory only) | n/a (advisory) | n/a | 0 |

Reports live at `runs/<run-id>/report.md`. Decision details at `runs/<run-id>/decision.json`. Manifests at `runs/<run-id>/manifest.json`.

Family advisory was active on both source runs (claude judge with claude contestant). The part-1 independent escalation included a non-family contestant (gemini) and supported the source decision — strong cheap signal that family bias did not drive part-1's outcome. Part-2 was only dispute-escalated (advisory), so its family check is weaker.

---

## Must-do (correctness; high confidence)

### M1. Hoist `ledger.UpdateLatest` until after replay copies succeed
- **File:** `internal/commands/researchcmd/run.go:232-244` (`RunResearchJudgeOnly`).
- **Problem:** `ledger.UpdateLatest` currently advances `latest` before the review-context + provider copy step. If any copy fails, `latest` is left pointing at an incomplete retry run.
- **Fix:** move the `UpdateLatest` call to after all copy operations succeed; on copy failure, leave `latest` untouched.
- **Source agreement:** part-1 F-003 / R-017 / R-027 — both providers agreed and the judge folded this in.
- **Effort:** S. **Confidence:** high.

### M2. Single shared `ReviewContextArtifacts` constant across call sites
- **Files:**
  - `internal/manifest/manifest.go:45` (already exports the constant; this is the canonical home)
  - `internal/commands/researchcmd/run.go:1009-1028` (re-hardcodes the three filenames)
  - `internal/commands/escalatecmd/escalate.go:1060-1083` (re-hardcodes the three filenames)
- **Fix:** import the existing `manifest.ReviewContextArtifacts` constant at both call sites; delete the local re-declarations.
- **Source agreement:** part-1 F-001 (codex R-019/R-023) + claude R-002 kept-from-nonwinner.
- **Effort:** XS. **Confidence:** high.

---

## Should-do

### S1. Atomic copy semantics in `copyFile`
- **File:** `internal/commands/researchcmd/run.go:942-957`.
- **Problem:** `copyFile` writes target files directly, while `internal/workorder/io.go:25 WriteTextAtomic` exists and is used by every other writer in the same file. A crash mid-copy leaves a partial target.
- **Fix:** rewrite `copyFile` to use temp-file + rename via `WriteTextAtomic` (or an equivalent binary-safe variant if `WriteTextAtomic` is text-only — check the helper's signature).
- **Source agreement:** codex part-1 R-015; claude disagreed in part-1 R-004 but the gemini independent escalation tilted toward this hardening.
- **Effort:** S. **Confidence:** high.

### S2. Separate preflight loop from copy loop for provider directories
- **File:** `internal/commands/researchcmd/run.go:853-882`.
- **Problem:** the current loop interleaves `requireProviderReplayArtifacts` (preflight) with `copyDirectoryTree` (mutation). Failure on provider N leaves providers 0..N-1 already populated with no cleanup.
- **Fix:** two-pass — first loop runs all `requireProviderReplayArtifacts` checks, second loop runs the copies only if every preflight passed. On copy failure, undo partial state (or document idempotency).
- **Source agreement:** part-1 F-004 + R-026.
- **Effort:** S. **Confidence:** high.

### S3. Add `judge.winner_backend` + `judge.winner_family` to telemetry
- **File:** `internal/manifest/manifest.go:334-371` (`telemetrySummary`); lines 373-410 already implement `telemetryProviderBackends` which resolves provider id → backend for the same map. `canonical_winner` is only at the manifest top-level (line 92).
- **Problem:** for judge-bias measurement (the literal question of part-2), aggregations need to filter by judge family vs winner family. Today consumers must join `decision.json.canonical_winner` → `manifest.providers[winner].backend` → `provider.BackendSpec.Family` themselves.
- **Fix:** in `telemetrySummary`, project `canonical_winner` → `winner_backend` → `winner_family`. Use the existing catalog lookup; if catalog lookup fails, set `winner_family="unknown"`.
- **Source agreement:** part-2 R-015 and R-016 (both providers converged); also B-R-025 from codex; escalation E-005 confirmed `winner_family` is not computed anywhere in `scripts/`.
- **Effort:** S. **Confidence:** high.

### S4. Add `judge.decided_by_judge` (project `selection_basis`) to telemetry
- **Files:**
  - `internal/decision/decision.go:279, 297, 303, 312, 345` already set `selection_basis` ∈ {`gate`, `metric`, `judge`, `identical_patch`, `none`}.
  - `internal/manifest/manifest.go:358-364` (`telemetry.judge` block) does not surface it.
- **Fix:** project the decision's `selection_basis` into `telemetry.judge.decided_by_judge` (or `telemetry.judge.selection_basis`, matching the source name to avoid drift).
- **Source agreement:** part-2 R-008 / R-016, codex F-010. Escalation E-002 verified field presence in decision.json.
- **Effort:** S. **Confidence:** high.

### S5. Add `judge.order_maps`, `judge.judge_passes`, `judge.position_swap_used` to telemetry
- **Files:**
  - `internal/decision/decision.go:116-117` already writes `order_maps` and `judge_passes` to decision.json.
  - `internal/manifest/manifest.go` telemetry block does not project them.
- **Fix:** project all three onto `telemetry.judge`. For escalation runs without a synthesis judge, emit `null`/empty so the schema is uniform.
- **Source agreement:** part-2 R-009 / F-002; escalation D-001.
- **Effort:** S. **Confidence:** high.

### S6. Hoist `source_run_id` + `rerun_mode` into telemetry for non-escalation judge-only reruns
- **Files:**
  - `internal/manifest/manifest.go:323` already hoists `source_run_id` for escalation manifests; `RowForLS` at line 154 already reads it for escalations.
  - The judge-only-rerun path does *not* set these telemetry fields.
- **Fix:** for `bakeoff rerun <id> --judge-only`, populate `telemetry.source_run_id` and `telemetry.rerun_mode = "judge_only"` so reruns are queryable the same way escalations are.
- **Source agreement:** part-2 F-003 + codex F-012.
- **Effort:** XS. **Confidence:** high.

---

## Nice-to-have

### N1. Move `copyDirectoryTree` / `copyFile` / `pathInside` to `internal/fsutil/`
- **Files:** helpers currently in `internal/commands/researchcmd/run.go`; `internal/fsutil/fsutil.go` exists and is the named home for filesystem utilities.
- **Fix:** move the helpers, preserving the symlink-inside-root policy. Caller sites in `researchcmd/run.go` and `escalatecmd/escalate.go` update to import from `fsutil`.
- **Source agreement:** part-1 F-008/F-009; gemini escalation concurs.
- **Effort:** S. **Confidence:** high (refactor, not correctness).

### N2. Tests for replay edge cases
Three test gaps named and verified:
- Mid-loop partial-copy failure (provider K succeeds, provider K+1 fails; what is the on-disk and `latest` state?).
- Symlink-inside-root vs symlink-outside-root behavior of `copyDirectoryTree`.
- Partial review-context (missing one of the three review artifacts) in judge-only path.
- **Effort:** M. **Confidence:** high. **Source:** part-1 F-005 / F-006 / F-007.

### N3. Extend `RowForLS` projection for bias analysis
- **File:** `internal/manifest/manifest.go:154` (`RowForLS`).
- **Fix:** add `judge_family`, `family_relation`, `canonical_winner` to the row projection so `bakeoff ls` / `bakeoff inspect` consumers don't re-parse manifests.
- **Effort:** S. **Confidence:** medium. **Source:** part-2 F-007 + codex F-011.

### N4. Documentation note on `BackendSpec.Family`
- **File:** `internal/provider/provider.go:81-86`.
- **Fix:** add a doc comment clarifying that `BackendSpec.Family` is catalog metadata declared by the plugin, not verified model lineage. Today the field has no comment and consumers may over-trust it.
- **Effort:** XS. **Source:** part-2 F-005.

---

## Speculation flagged

Items from the reports that name symbols/files that do not exist in the repo. Treat as naming suggestions, not as missing code.

### SP1. Gemini's `internal/runreplay` package
- Escalation `2026-05-25-6b7a` proposed an `internal/runreplay` package with `StageJudgeReplay` and `LoadWorkerResults` functions. `grep` confirms none of those names exist.
- Treat as a *naming proposal* for the eventual extraction package, not as a current code reference.

### SP2. Codex's invented function names
- Codex's part-1 R-004 proposed `StageReviewContextArtifacts`, `StageProviderArtifactDirs`, `LoadResearchWorkerResultsFromArtifacts`, `ValidateJudgeOnlySource`. None exist as named functions today.
- The *behaviors* these names describe are real (the loops/blocks exist inline in `researchcmd/run.go`). The names are aspirational targets for an extraction pass.

### SP3. Claude's reference to `copyProviderArtifactDirs`
- Claude part-1 F-011 referred to a `copyProviderArtifactDirs` function. The loop body it describes is real (around `researchcmd/run.go:853-882`), but the loop is currently inline, not a named function.
- Minor miscitation; the underlying code reference is correct, only the function name is wrong.

### SP4. Part-1 directional disagreement (not hallucination, real disagreement)
- Claude part-1 R-018 concluded "do not create a new package; harden in place." Codex part-1 R-028 leaned extraction. The escalation judge correctly flagged this as a real disagreement, and the gemini independent escalation tilted toward extraction. Treat as an open design decision, not as a verified consensus action.

---

## Cross-report agreement (highest-confidence convergence)

These items appeared in *both* providers within a run and were endorsed by escalation:

1. **Review-context constant deduplication** — part-1 codex R-019/F-001 + claude kept R-002 (M2 above).
2. **In-place hardening before extraction** — part-1 codex R-025, claude R-018 agrees, gemini escalation agrees; the only open disagreement is whether the *eventual* extraction package should exist (informs N1 and SP1).
3. **Decision-level telemetry projection (`order_maps`, `judge_passes`, `selection_basis`)** — part-2 R-008/R-009/R-016 (claude winner), part-2 F-010 (codex kept), escalation E-001/E-002 explicitly verified the fields exist in `decision.json` but not in telemetry (S4 and S5 above).
4. **`winner_family` derivation gap** — part-2 R-005/R-006/R-016 (claude) + B-R-025 (codex) + escalation E-005 (S3 above).

---

## Recommended next bakeoff

A clean `type=build` work order emerges from the telemetry-projection items:

- **Goal:** extend `telemetrySummary` in `internal/manifest/manifest.go` to emit `judge.winner_backend`, `judge.winner_family`, `judge.decided_by_judge`, `judge.order_maps`, `judge.judge_passes`, `judge.position_swap_used`, and hoist `source_run_id` + `rerun_mode` for non-escalation judge-only reruns.
- **Acceptance criterion:** all new fields populated correctly for default-pair runs (`claude` + `codex`) AND for custom provider-id runs (e.g. `left`/`right` → backends `gemini`/`codex`). `winner_family="unknown"` when catalog lookup fails. Manifest schema stays uniform between research and escalation runs (escalation emits `null` for synthesis-only fields where there is no synthesis judge).
- **Gate verifier:** `go test ./internal/manifest/...` — add three test cases mirroring `internal/manifest/manifest_test.go:325-344` (`TestWriteRunManifestTelemetryResolvedProviderBackendsKeepWorkOrderOrder`):
  1. Default-pair run with claude winner — assert exact key presence and `winner_family="claude"` (or the catalog's actual family slug).
  2. Custom-id run with `left`/`right` IDs mapping to gemini/codex backends — assert `winner_backend` and `winner_family` are still derived from the catalog.
  3. Catalog miss (unknown backend) — assert `winner_family="unknown"`, no panic, no nil deref.

**Why this is the right next bakeoff:** the change is verifier-ready (existing test scaffolding mirrors the new cases), the behavioral contract is observable from a single JSON file, and providers already converged on the field set during this dogfood. Confidence high; effort S; blast radius small (telemetry-only, no caller changes).

### What is *not* a clean build target yet

- **Replay/staging extraction** (the eventual `internal/runreplay` package or equivalent). Both providers disagreed on signature shape (`[]string` vs `*workorder.WorkOrder`) and on whether atomic writes belong inside the extracted helpers or stay in the caller. Needs a design pass — possibly a `type=compare` work order on two proposed package layouts — before a `type=build` order is appropriate.
- **`ledger.UpdateLatest` ordering fix** (M1 above). Small enough to land as a direct PR without a bakeoff. ~5-line change; obvious correctness fix; the test in `RunResearchJudgeOnly`'s suite can be extended in the same PR.

---

## Cross-reference index

For each item above, the relevant run artifacts are:

- **M1, M2, S1, S2, N1, N2** — primary evidence in `runs/dogfood-artifacts-telemetry-split.part-1/report.md`; corroboration in `runs/2026-05-25-6b7a/report.md`.
- **S3, S4, S5, S6, N3, N4** — primary evidence in `runs/dogfood-artifacts-telemetry-split.part-2/report.md`; advisory cross-check in `runs/2026-05-25-5e29/report.md`.
- Per-claim line numbers and quoted snippets live in the report bodies; the audit prompts cross-referenced each named symbol against the live tree before recommending an action.
