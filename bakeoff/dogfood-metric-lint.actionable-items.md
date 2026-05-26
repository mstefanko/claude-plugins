# Dogfood: metric-lint — Actionable Items Report

## Run info

- **Invocation:** `/bakeoff:run build a performance bakeoff for internal/manifest.RowForLS using a repo-local benchmark metric, but first identify whether a stable benchmark harness and protected fixture paths exist. Acceptance criteria: no metric verifier should run unless its command, min_delta_percent, noise_floor_percent, min_runs, and protected_paths are explicit. --run-id dogfood-metric-lint`
- **Run id:** `dogfood-metric-lint`
- **Date:** 2026-05-24
- **Repo:** `mstefanko-plugins/bakeoff`
- **Base ref:** `main` @ `81c636115e3e`
- **Outcome:** stopped before draft. No `runs/dogfood-metric-lint/` artifacts exist.
- **Why no report.md:** the lint correctly refused to draft, so no providers ran.

## Confirmed: no overlapping prior artifacts

Inspected `runs/` for any prior run that touched `RowForLS` benchmarks, `metric.command`, or `protected_paths`. Nearest neighbors (`runs/2026-05-24-feef*` and earlier) targeted judge-family advisory and telemetry analysis — no overlap with this dogfood scenario. Nothing to merge or supersede.

---

## 1. Reality check before doing the work

`internal/manifest/manifest.go:118 func RowForLS(runDir string) map[string]any` does:

1. One `os.ReadFile` of `manifest.json`.
2. One `json.Unmarshal` into `lsManifest`.
3. Two `os.Stat` / `FileExists` checks.
4. Assembles a ~12-key map and returns.

This is **I/O-bound** and **not a hot path**. Variance under benchmark will be dominated by filesystem cache state, not by code under test. A `BenchmarkRowForLS` is defensible but low-value:

- Real performance regressions in `RowForLS` are unlikely (no loops, no allocations to speak of beyond the unmarshal).
- A metric verifier would need a tight `noise_floor_percent` to be meaningful, but filesystem noise on macOS regularly exceeds 10-20% even with warm caches.
- The lint behavior — refusing to draft against a missing harness — was the value proposition of this run, and it worked.

**Recommendation:** decide first whether you actually want metric-verifier coverage for this function. If the goal was purely to dogfood the lint, you got what you came for and the rest of this report is optional.

The remainder assumes you do want to ship a real benchmark + metric verifier.

---

## 2. Repo punch list (if a benchmark is wanted)

Each item lists the file path, what to add, and why.

### 2.1 `internal/manifest/manifest_bench_test.go` (new file)

Add `BenchmarkRowForLS` that reuses the `writeJSON` helper from `manifest_test.go` (currently around L60+) and seeds a temp dir per iteration.

Skeleton:

```go
package manifest

import (
    "path/filepath"
    "testing"
)

func BenchmarkRowForLS(b *testing.B) {
    for _, fixture := range []string{"minimal", "escalation", "with-triage"} {
        b.Run(fixture, func(b *testing.B) {
            runDir := b.TempDir()
            seedLSManifest(b, runDir, fixture)
            b.ResetTimer()
            for i := 0; i < b.N; i++ {
                _ = RowForLS(runDir)
            }
        })
    }
}
```

`seedLSManifest` reads `testdata/rowforls/<fixture>.json` and writes a `manifest.json` into `runDir`. See §2.4 for the helper signature change.

### 2.2 `internal/manifest/testdata/rowforls/{minimal,escalation,with-triage}.json` (new files)

Three fixtures spanning the three branches in `manifest.go:121-165`:

- `minimal.json` — bare LSManifest with required keys only.
- `escalation.json` — includes escalation metadata so the escalation branch is exercised.
- `with-triage.json` — includes triage detail so the triage branch is exercised.

Pull realistic shapes from `internal/manifest/manifest_test.go` setup blocks (look at the test bodies for the three branches; the existing tests already build these in code — promote them to JSON fixtures).

### 2.3 Root `Makefile` (new file — none exists today)

```make
.PHONY: bench-manifest

bench-manifest:
	go test -run=^$$ -bench=BenchmarkRowForLS -benchmem -count=3 ./internal/manifest
```

`-count=3` because the metric verifier will need `min_runs >= 2`; three iterations gives the verifier room to compute a noise floor.

This Makefile target becomes the `metric.command` in a future work order: `metric.command: ["make", "bench-manifest"]` (or invoked directly as the `argv`).

### 2.4 `writeJSON` helper signature change

**File:** `internal/manifest/manifest_test.go` (around L60 — `writeJSON` helper)

**Current:** `func writeJSON(t *testing.T, ...)`.

**Change to:** `func writeJSON(tb testing.TB, ...)` so it can be called from both `*testing.T` (existing tests) and `*testing.B` (the new benchmark).

Update all call sites in `manifest_test.go` — `t` already implements `testing.TB`, so no caller changes other than the type widening.

### 2.5 Metric protected-paths allowlist

When you draft the real metric work order, `metric.protected_paths` must include at least:

- `internal/manifest/testdata/rowforls/**` (fixtures)
- `internal/manifest/manifest_bench_test.go` (the benchmark itself — providers must not rewrite it to win)
- `internal/manifest/manifest_test.go` (the `writeJSON` helper they could otherwise game)
- `Makefile` (the `bench-manifest` target)

Without all four, a provider could swap the benchmark for a no-op and "improve" the metric.

### 2.6 `docs/cli-reference.md` — document `make bench-manifest`

One line under a "Benchmarks" subsection so future work orders can cite it by name rather than by ad-hoc shell.

---

## 3. Plugin punch list

Separate from repo work — these are gaps the dogfood exposed in the plugin source itself (you are working in the plugin's repo).

### 3.1 `skills/bakeoff-run/SKILL.md` — add a "missing harness" precheck step

Add a precheck near §"Single Work-Order Drafting" that says: when a `metric.*` field is required and the target package has zero `Benchmark*` funcs / no `testdata/` / no Makefile target, **abort before the preview** with an explicit "scaffold first" message instead of stalling mid-draft.

This codifies what this run did by intuition.

### 3.2 `skills/bakeoff-run/SKILL.md` — codify the stop-summary shape

Add an example of the punch-list a metric-lint stop should return to the user, so future runs are consistent.

### 3.3 `internal/commands/doctorcmd/` — `bakeoff doctor --check=metric-harness PKG`

Add a subprobe so the skill can ground the precheck in a CLI call rather than ad-hoc `ctx_batch_execute` (or fallback Bash) probes. The subprobe would inspect a package for:

- presence of `Benchmark*` funcs
- presence of `testdata/` or fixture dir
- candidate Makefile bench target

JSON output the skill can parse. This pushes the brittle shell discovery out of the prompt and into Go.

See related items in the tightening report (`dogfood-metric-lint.tightening-report.md` §2.1–§2.4) for the validation-side gates that should pair with this.

---

## 4. Suggested order if you do all of it

1. **Decide whether you want the benchmark at all** (§1). If no, stop here.
2. §2.4 (`writeJSON` signature) — unlocks §2.1 and §2.2.
3. §2.2 (fixtures) — independent, can be parallel with §2.4.
4. §2.1 (benchmark file).
5. §2.3 (Makefile target).
6. Run `make bench-manifest` locally to confirm it produces stable numbers — if filesystem variance exceeds ~15%, abandon the metric-verifier idea and stop.
7. §2.5 + §2.6 (allowlist note + doc).
8. Re-invoke `/bakeoff:run` with the now-grounded request. The lint should pass; a real metric verifier work order should draft.
9. §3.1–§3.3 separately, in plugin-tightening branch.

## 5. Deferred / out of scope

- Refactoring `RowForLS` for benchability — it's already simple. Perf gains would be noise.
- Adding `go test -bench` to CI — orthogonal; metric-verifier work orders run benchmarks locally per-run, not on every CI build.
- A general "metric-verifier scaffolding" command in the Bakeoff CLI — interesting but out of scope for the current punch list.
