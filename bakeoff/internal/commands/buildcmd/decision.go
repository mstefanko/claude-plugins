package buildcmd

import (
	"fmt"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	decisionpkg "github.com/mstefanko/claude-plugins/bakeoff/internal/decision"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func resolveBuildDecision(wo *workorder.WorkOrder, workerResults map[string]map[string]any, runs []providerRun, baseline buildverify.Result, metrics []buildverify.MetricComparison, judgeResults map[string]map[string]any, pass1Order map[string]string, pass2Order map[string]string) (map[string]any, int) {
	judgeFailure := judgeResults["_failure"]
	judgeResultsForDecision := map[string]map[string]any{}
	if judgeFailure == nil {
		for key, value := range judgeResults {
			judgeResultsForDecision[key] = value
		}
	}
	input := decisionpkg.BuildResolutionInput{
		WorkOrder:        wo,
		ProviderIDs:      providerIDs(wo),
		ProviderStatuses: buildProviderStatuses(wo, workerResults, runs),
		GateResults:      buildGateResults(runs),
		MetricResults:    buildMetricResults(runs),
		MetricDecisions:  metricDecisionMaps(metrics),
		JudgeResults:     judgeResultsForDecision,
		Pass1Order:       pass1Order,
		Pass2Order:       pass2Order,
		BaselineVerify:   baseline,
		ProviderBuild:    buildProviderArtifacts(runs),
		Caveats:          buildMetricCaveats(runs, metrics),
	}
	decision, exitCode := decisionpkg.ResolveBuild(input)
	if judgeFailure != nil {
		decision["caveats"] = append(jsonutil.ListStrings(decision["caveats"]), fmt.Sprintf("build judge failed: pass1=%v, pass2=%v", judgeFailure["pass1_status"], judgeFailure["pass2_status"]))
		if exitCode == 3 {
			exitCode = 1
		}
	}
	return decision, exitCode
}

func buildProviderStatuses(wo *workorder.WorkOrder, workerResults map[string]map[string]any, runs []providerRun) map[string]map[string]any {
	statuses := map[string]map[string]any{}
	byProvider := map[string]providerRun{}
	for _, run := range runs {
		byProvider[run.ID] = run
	}
	for _, participant := range wo.Providers {
		result := workerResults[participant.ID]
		status := artifact.StatusWithoutPayload(result)
		status["runner_status"] = status["status"]
		status["stderr_path"] = "providers/" + participant.ID + "/stderr.txt"
		run, ok := byProvider[participant.ID]
		if !ok {
			status["patch_state"] = "provider_failed"
			status["verify_state"] = "not_run"
			statuses[participant.ID] = status
			continue
		}
		status["gates_passed"] = run.Verify.GatesPassed
		status["ineligible_reasons"] = run.IneligibleReasons
		status["worktree_cleanup"] = run.Cleanup.Status
		status["verify_result_path"] = "providers/" + participant.ID + "/build/verify/result.json"
		status["patch_state"] = patchState(run)
		status["verify_state"] = verifyState(run)
		status["metric_state"] = metricState(run)
		status["scope_diagnostics"] = run.ScopeDiagnostics
		if len(run.ProtectedViolations) > 0 {
			status["protected_path_violations"] = run.ProtectedViolations
			status["protected_paths_path"] = "providers/" + participant.ID + "/build/protected-paths.json"
		}
		if run.Capture != nil {
			status["patch_bytes"] = run.Capture.PatchBytes
			status["patch_digest"] = run.Capture.PatchDigest
			status["patch_over_cap"] = run.Capture.PatchOverCap
			status["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			status["patch_path"] = "providers/" + participant.ID + "/build/diff.patch"
			status["diffstat_path"] = "providers/" + participant.ID + "/build/diffstat.txt"
			status["changed_files_path"] = "providers/" + participant.ID + "/build/changed-files.txt"
			status["workspace_path"] = "providers/" + participant.ID + "/build/workspace.json"
			status["changed_files"] = run.Capture.ChangedFiles
			status["provider_authored_tests"] = len(run.Capture.TestFiles) > 0
			status["provider_authored_benchmarks"] = len(run.Capture.BenchmarkFiles) > 0
		}
		statuses[participant.ID] = status
	}
	return statuses
}

func buildProviderArtifacts(runs []providerRun) map[string]any {
	out := map[string]any{}
	for _, run := range runs {
		entry := map[string]any{
			"gates_passed":       run.Verify.GatesPassed,
			"ineligible_reasons": run.IneligibleReasons,
			"worktree_cleanup":   run.Cleanup.Status,
		}
		if run.Capture != nil {
			entry["patch_bytes"] = run.Capture.PatchBytes
			entry["patch_digest"] = run.Capture.PatchDigest
			entry["patch_over_cap"] = run.Capture.PatchOverCap
			entry["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			entry["scope_diagnostics"] = run.ScopeDiagnostics
			entry["patch_path"] = "providers/" + run.ID + "/build/diff.patch"
			entry["changed_files"] = run.Capture.ChangedFiles
			entry["test_files"] = run.Capture.TestFiles
			entry["benchmark_files"] = run.Capture.BenchmarkFiles
		}
		if len(run.ProtectedViolations) > 0 {
			entry["protected_path_violations"] = run.ProtectedViolations
			entry["protected_paths_path"] = "providers/" + run.ID + "/build/protected-paths.json"
		}
		out[run.ID] = entry
	}
	return out
}

func buildGateResults(runs []providerRun) map[string]map[string]map[string]any {
	out := map[string]map[string]map[string]any{}
	for _, run := range runs {
		out[run.ID] = map[string]map[string]any{}
		for _, result := range run.Verify.Results {
			if result.Kind != "gate" {
				continue
			}
			out[run.ID][result.ID] = verifierResultMap(result)
		}
	}
	return out
}

func buildMetricResults(runs []providerRun) map[string]map[string]map[string]any {
	out := map[string]map[string]map[string]any{}
	for _, run := range runs {
		out[run.ID] = map[string]map[string]any{}
		for _, result := range run.Verify.Results {
			if result.Kind != "metric" {
				continue
			}
			entry := verifierResultMap(result)
			if result.Metric != nil {
				entry["metric"] = result.Metric
			}
			out[run.ID][result.ID] = entry
		}
	}
	return out
}

func verifierResultMap(result buildverify.VerifierResult) map[string]any {
	entry := map[string]any{
		"id":                    result.ID,
		"kind":                  result.Kind,
		"status":                result.Status,
		"exit_code":             result.ExitCode,
		"wall_seconds":          result.WallSeconds,
		"stdout_bytes":          result.StdoutBytes,
		"stderr_bytes":          result.StderrBytes,
		"stdout_observed_bytes": result.StdoutObservedBytes,
		"stderr_observed_bytes": result.StderrObservedBytes,
		"stdout_truncated":      result.StdoutTruncated,
		"stderr_truncated":      result.StderrTruncated,
	}
	if result.StdoutPath != "" {
		entry["stdout_path"] = result.StdoutPath
	}
	if result.StderrPath != "" {
		entry["stderr_path"] = result.StderrPath
	}
	if result.StatusPath != "" {
		entry["status_path"] = result.StatusPath
	}
	if result.MetricPath != "" {
		entry["metric_path"] = result.MetricPath
	}
	return entry
}

func metricDecisionMaps(metrics []buildverify.MetricComparison) []map[string]any {
	out := make([]map[string]any, 0, len(metrics))
	for _, metric := range metrics {
		entry := map[string]any{
			"id":                  metric.ID,
			"name":                metric.Name,
			"direction":           metric.Direction,
			"delta_percent":       metric.DeltaPercent,
			"min_delta_percent":   metric.MinDeltaPercent,
			"noise_floor_percent": metric.NoiseFloorPercent,
			"meets_min_delta":     metric.MeetsMinDelta,
			"meets_noise_floor":   metric.MeetsNoiseFloor,
			"min_runs":            metric.MinRuns,
			"threshold_percent":   metric.Threshold,
			"conclusive":          metric.Conclusive,
		}
		if metric.Winner != "" {
			entry["winner"] = metric.Winner
		}
		if metric.Reason != "" {
			entry["reason"] = metric.Reason
		}
		out = append(out, entry)
	}
	return out
}

func buildMetricCaveats(runs []providerRun, metrics []buildverify.MetricComparison) []string {
	caveats := []string{}
	seen := map[string]bool{}
	add := func(caveat string) {
		if caveat == "" || seen[caveat] {
			return
		}
		seen[caveat] = true
		caveats = append(caveats, caveat)
	}
	for _, run := range runs {
		for _, result := range run.Verify.Results {
			if result.Kind != "metric" || result.Metric == nil || result.Metric.SampleJSONLinesIgnored == 0 {
				continue
			}
			add(fmt.Sprintf("metric `%s` for provider `%s`: ignored %d earlier metric JSON line(s); emit one final aggregate JSON object", result.ID, run.ID, result.Metric.SampleJSONLinesIgnored))
		}
	}
	for _, metric := range metrics {
		if metric.Conclusive || metric.Reason == "" || !strings.Contains(metric.Reason, "metric.min_runs") {
			continue
		}
		add(fmt.Sprintf("metric `%s`: %s", metric.ID, metric.Reason))
	}
	return caveats
}

func patchState(run providerRun) string {
	if run.Capture == nil {
		if len(run.IneligibleReasons) > 0 {
			return "provider_failed"
		}
		return "no_patch"
	}
	if run.Capture.PatchOverCap {
		return "patch_over_cap"
	}
	if run.Capture.GitlinkChangeRejected {
		return "submodule_change_rejected"
	}
	if len(run.ProtectedViolations) > 0 {
		return "protected_path_changed"
	}
	return "patch_captured"
}

func verifyState(run providerRun) string {
	if patchState(run) != "patch_captured" || len(run.Verify.Results) == 0 {
		return "not_run"
	}
	if run.Verify.GatesPassed {
		return "gate_passed"
	}
	return "gate_failed"
}

func metricState(run providerRun) string {
	hasMetric := false
	for _, result := range run.Verify.Results {
		if result.Kind != "metric" {
			continue
		}
		hasMetric = true
		if result.Metric != nil && result.Metric.Conclusive {
			return "metric_decisive"
		}
	}
	if hasMetric {
		return "metric_inconclusive"
	}
	return "not_run"
}

func buildDecision(wo *workorder.WorkOrder, workerResults map[string]map[string]any, providerRuns []providerRun, baseline buildverify.Result, metrics []buildverify.MetricComparison, decisionKind string, selectionBasis string, winner string, caveats []string) map[string]any {
	statuses := map[string]any{}
	for _, participant := range wo.Providers {
		result := workerResults[participant.ID]
		status := artifact.StatusWithoutPayload(result)
		status["stderr_path"] = "providers/" + participant.ID + "/stderr.txt"
		statuses[participant.ID] = status
	}
	providerBuild := map[string]any{}
	for _, run := range providerRuns {
		entry := map[string]any{
			"gates_passed":       run.Verify.GatesPassed,
			"ineligible_reasons": run.IneligibleReasons,
			"worktree_cleanup":   run.Cleanup.Status,
		}
		if run.Capture != nil {
			entry["patch_bytes"] = run.Capture.PatchBytes
			entry["patch_digest"] = run.Capture.PatchDigest
			entry["patch_over_cap"] = run.Capture.PatchOverCap
			entry["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			entry["scope_diagnostics"] = run.ScopeDiagnostics
			entry["patch_path"] = "providers/" + run.ID + "/build/diff.patch"
			entry["changed_files"] = run.Capture.ChangedFiles
		}
		if len(run.ProtectedViolations) > 0 {
			entry["protected_path_violations"] = run.ProtectedViolations
			entry["protected_paths_path"] = "providers/" + run.ID + "/build/protected-paths.json"
		}
		providerBuild[run.ID] = entry
	}
	return map[string]any{
		"mode":               "build",
		"decision_kind":      decisionKind,
		"selection_basis":    selectionBasis,
		"canonical_winner":   nilIfEmpty(winner),
		"judge_ran":          false,
		"judge_rationale":    []string{},
		"provider_statuses":  statuses,
		"baseline_verify":    baseline,
		"provider_build":     providerBuild,
		"metric_comparisons": metrics,
		"caveats":            caveats,
	}
}
