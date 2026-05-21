package buildcmd

import (
	"path/filepath"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
)

func buildSummary(repo buildworkspace.Repository, runDir string, runID string, outDir string, decision map[string]any, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, diagnostics buildDiagnostics, exitCode int) map[string]any {
	providers := map[string]any{}
	for _, run := range runs {
		entry := map[string]any{
			"status":             summary.CompactStatus(run.WorkerResult["status"]),
			"raw_status":         run.WorkerResult["status"],
			"gates_passed":       run.Verify.GatesPassed,
			"ineligible_reasons": run.IneligibleReasons,
			"scope_diagnostics":  run.ScopeDiagnostics,
		}
		if run.Capture != nil {
			entry["patch_bytes"] = run.Capture.PatchBytes
			entry["patch_digest"] = run.Capture.PatchDigest
			entry["patch_path"] = filepath.Join(runDir, "providers", run.ID, "build", "diff.patch")
		}
		if len(run.ProtectedViolations) > 0 {
			entry["protected_path_violations"] = run.ProtectedViolations
			entry["protected_paths_path"] = filepath.Join(runDir, "providers", run.ID, "build", "protected-paths.json")
		}
		providers[run.ID] = entry
	}
	out := map[string]any{
		"schema_version":   1,
		"command":          "build",
		"status":           buildCommandStatus(exitCode),
		"exit_code":        exitCode,
		"warnings":         sourceWarnings(repo),
		"run_id":           runID,
		"mode":             "build",
		"run_dir":          runDir,
		"decision_kind":    decision["decision_kind"],
		"selection_basis":  decision["selection_basis"],
		"winner":           decision["canonical_winner"],
		"judge_ran":        decision["judge_ran"],
		"baseline":         map[string]any{"gates_passed": baseline.GatesPassed, "results": baseline.Results},
		"providers":        providers,
		"metric_summaries": metrics,
		"diagnostics":      diagnostics,
		"artifacts":        buildArtifactPaths(runDir),
		"next":             ledger.BakeoffShowCommand(runID, outDir, ""),
	}
	if stalledAt, _ := decision["stalled_at"].(string); stalledAt != "" {
		out["stalled_at"] = stalledAt
	}
	return out
}

func buildCommandStatus(exitCode int) string {
	if exitCode == 0 {
		return "ok"
	}
	if exitCode == 3 {
		return "unresolved"
	}
	return "failed"
}

func buildArtifactPaths(runDir string) map[string]any {
	out := map[string]any{}
	for key, relative := range map[string]string{
		"work_order":    "work-order.json",
		"build_context": "build-context.json",
		"diagnostics":   "diagnostics.json",
		"decision":      "decision.json",
		"meta":          "meta.json",
		"manifest":      "manifest.json",
		"report":        "report.md",
	} {
		path := filepath.Join(runDir, relative)
		if fsutil.FileExists(path) {
			out[key] = path
		}
	}
	return out
}
