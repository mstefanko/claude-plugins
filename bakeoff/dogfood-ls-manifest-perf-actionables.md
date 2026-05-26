# Bakeoff run actionables — `dogfood-ls-manifest-perf`

## Run context

| Field | Value |
| --- | --- |
| Run id | `dogfood-ls-manifest-perf` |
| Date | 2026-05-24 |
| Mode | `build` |
| Goal | Reduce repeated JSON loading and triage-state recomputation when `ls`/`history` scans large run directories, while preserving current ls/history output. |
| Edit scope | `internal/manifest/**`, `internal/commands/lscmd/**` |
| Gate | `manifest-lscmd-tests` → `go test ./internal/manifest ./internal/commands/lscmd -count=1` (baseline + both providers passed) |
| Providers | `claude/sonnet` (high) + `codex/gpt-5.5` (high) |
| Judge | `claude/opus` xhigh |
| Result | `decision_kind: tie`, `canonical_winner: null`, exit `3` |
| Patches | claude 4301 bytes, codex 11381 bytes |
| Judge passes | pass1 (claude=A, codex=B): tie; pass2 (codex=A, claude=B): codex |
| Judge caveat | "position swap did not produce a stable build winner" |

**Acceptance criteria (work order):**

1. lscmd sorting/filtering output stays identical for present, missing, invalid, escalation, and stale-triage manifests (fixtures + goldens).
2. Manifest schema unchanged (no field additions, removals, renames, or type changes in `internal/manifest` types).
3. `ls`/`history` human-readable output is byte-identical to current behavior for the covered manifest states.

**Key artifacts**

- Report: `runs/dogfood-ls-manifest-perf/report.md`
- Decision JSON: `runs/dogfood-ls-manifest-perf/decision.json`
- Claude patch: `runs/dogfood-ls-manifest-perf/providers/claude/build/diff.patch`
- Codex patch: `runs/dogfood-ls-manifest-perf/providers/codex/build/diff.patch`
- Inspect command: `bakeoff show dogfood-ls-manifest-perf`

---

## Background: what the judge actually said

> Both candidates pass the gate, but A achieves the goal without changing semantics: it defers triage StateDetail calls to only the rows that survive filtering/limit, preserving the current disk-as-source-of-truth contract. B inverts that contract by treating the manifest's recorded triage_state as authoritative whenever the triage dir exists, a behavior change B itself flags as a risk; acceptance criteria explicitly cover stale-triage manifests, and B's own tests don't exercise the disk/manifest divergence case. A scores higher on correctness and maintainability while B scores marginally higher on scope control.

The judge's rationale argued for claude on the load-bearing acceptance criterion (stale-triage manifests must still work). Pass2 then flipped to codex after position swap — read as position bias, **not** as a substantive overturn.

---

## 1. Adoption recommendation: neither patch as-is

Adopt a corrected variant of **Claude's structural approach** (lazy refresh after filter + limit), **without** either candidate's "trust the manifest" shortcut. Both candidates mutate the disk-as-source-of-truth semantics around `triage.StateDetail`:

- HEAD (`internal/manifest/manifest.go:201-216`): always recomputes via `triage.StateDetail` when `manifestState != "no"`. Slow but correct.
- Claude: returns `manifestState` verbatim in that branch. Faster but stale-triage-divergence-unsafe.
- Codex: builds `RowForLSScan` / `RefreshLSTriageState` / `lsScanRow` on the same trust-the-manifest premise, then adds a separate lazy-refresh layer in `lscmd/ls.go`.

The right path is to keep HEAD's existing `triageStateForLS` recompute (or guard with `os.Stat(triageDir)` for free wins), and import Codex's *structural* lazy-evaluation in `lscmd/ls.go`: scan all rows cheaply, sort, filter, limit, **then** invoke triage refresh only on the rows that will be displayed.

---

## 2. Direct cherries — land regardless of which approach wins

### `internal/commands/lscmd/ls.go`

- **Cherry from codex:** the split of `rowsForLS` into a scan phase + lazy `ensureTriageState`, the `sortScanRowsByFinishedAt` / `rowFinishedAtLess` extraction, and the post-limit refresh loop.
  - Modification: keep `manifest.RowForLS` as-is (do NOT introduce `RowForLSScan`).
  - Have `ensureTriageState` call `triage.StateDetail(runDir)` only when `manifest_state == "present"` AND the row has not been refreshed yet.

### `internal/manifest/manifest.go:777` (`legacyLSRow`)

- **Cherry from claude:** the `os.Stat(triageDir)` guard before `triage.StateDetail`. Free win for missing/invalid manifest paths — HEAD currently recomputes triage on a run with no `triage/` dir at all, which is wasted I/O.

### `internal/manifest/manifest_test.go`

- **Cherry from claude:** the table-driven `TestRowForLSTriageStateRoundTrip` with 4 cases (`missing-dir`, `yes-with-matching-hashes`, `stale`, `dry_run`). Broader than codex's single case; lands cleanly without other changes.

---

## 3. Test gaps to add before merging anything

The judge explicitly called out (pass1 risk #4): *"Neither candidate adds a regression test asserting byte-identical ls/history output across the present/missing/invalid/escalation/stale-triage fixture matrix beyond what the existing gate covers."*

### `internal/commands/lscmd/ls_test.go`

1. **Golden-output assertion** comparing `runLs` stdout against HEAD across the full fixture matrix:
   - present (manifest with `triage.state="yes"`, matching triage on disk)
   - missing (no `manifest.json`)
   - invalid (corrupt `manifest.json`)
   - escalation (escalation rows attached)
   - stale-triage (manifest claims `triage.state="yes"` but triage hashes diverge from disk)

   Use the existing setups from `TestHistorySortsLimitsAndSummarizesDisplayedRows`, `TestLimitAppliesAfterRecentSortForJSON`, and `TestJSONRowsProjectEscalationFieldsAndSourceRunFilter` as fixture sources.

2. **Disk/manifest divergence test:** write `manifest.json` with `triage.state="yes"` but no `triage/` directory on disk. Assert the resulting row reports `triage_state="no"`. This is the exact case the judge said neither candidate exercised; failing this test should kill the trust-the-manifest shortcut path.

3. **Filter-then-refresh test:** count `triage.StateDetail` invocations (via test double or `runDir`-scoped stat counter). Assert rows excluded by `--facet`, `--type`, or `--source-run` do **not** invoke `triage.StateDetail`. This is the regression test for the actual optimization goal.

---

## 4. Benchmarks (neither candidate added any)

Both patches claim perf wins with zero comparative evidence in the run. Add these so a future bakeoff has decisive metric evidence:

### `internal/commands/lscmd/ls_bench_test.go::BenchmarkRunLsLargeDir`

- N = 500 and N = 2000 synthetic run dirs.
- Permutations: ±`--triage-state` filter, ±`--limit 10`.
- Compare allocs/op and ns/op against baseline.

### `internal/manifest/manifest_bench_test.go::BenchmarkRowForLSWithTriageDir`

- Single-run hot path.
- Permutations: ±existing `triage/` directory.
- Isolates `triage.StateDetail` cost so future optimizations can be A/B'd.

Once these exist, a metric-style follow-up work order can run with `metric.min_runs >= 2` and `metric.min_delta_percent` set, turning the next bakeoff into a decisive comparison rather than another tie.

---

## 5. Risks worth filing as separate tickets

### A. Latent perf bug in HEAD `triageStateForLS`

- **File:** `internal/manifest/manifest.go:205-215`
- **Issue:** When `manifestState != "no"`, unconditionally calls `triage.StateDetail` even when no `triage/` directory exists on disk. Wasted I/O on every `ls`.
- **Fix:** `os.Stat(triageDir)` guard (claude's cherry from §2 covers `legacyLSRow`; this is the sibling code path).
- **Independent of either patch** — file as a standalone bugfix.

### B. Latent perf bug in `legacyLSRow`

- **File:** `internal/manifest/manifest.go:780`
- **Issue:** Unconditional `triage.StateDetail` for runs with no manifest at all (the "legacy" fallback). Same root cause as A.
- **Fix:** same `os.Stat` guard. Bundling with A is reasonable.

### C. Judge position bias

- **Where:** judge prompt / rubric design.
- **Issue:** pass1 → tie, pass2 → codex despite the rationale arguing for claude. The verdict ↔ narrative mismatch is what made this run inconclusive.
- **Cross-reference:** relevant to in-flight `slice-9-judge-advisory-audit.work-order.json` already in the repo.
- **Suggested ticket:** "build judge: enforce rationale-vs-verdict consistency check before emitting canonical_winner."

### D. Patch path prefix mismatch (worktree vs CWD layout)

- **Where:** `runs/<id>/providers/*/build/changed-files.txt` and `diff.patch`.
- **Issue:** Providers wrote patches with a `bakeoff/` prefix; HEAD's `internal/...` paths live at the repo top-level (the bakeoff plugin's CWD). Confirm patches still apply cleanly to the actual repo root; if they only apply inside the worktree layout, the runner is silently rebasing the patch namespace.
- **Verify:** open both `diff.patch` files; check `--- a/<path>` lines.

### E. Codex stderr volume

- **File:** `runs/dogfood-ls-manifest-perf/providers/codex/stderr.txt`
- **Issue:** Codex produced ~280 KB of stderr on a 3-file patch (truncated to 80 KB retained). Most of it is the deterministic Codex banner block; see the tightening report (P1 item 2) for the adapter-level fix. Worth a one-line ticket here to keep the actionables list complete.

---

## 6. Recommended sequence

1. Land the two free-win `os.Stat` guards (risks A + B). Tiny, no semantics change.
2. Add the test gaps from §3 (especially the disk/manifest divergence test) on `HEAD`. This makes any subsequent optimization patch falsifiable on the stale-triage criterion.
3. Add the benchmarks from §4. Run them on `HEAD` to capture a baseline number.
4. Rewrite the optimization as a single new branch that takes the cherries from §2. Re-run bakeoff with the new tests as gate verifier; the disk/manifest divergence test will now eliminate trust-the-manifest patches automatically.

This converts the tie into a decisive next-round result without picking either current patch.
