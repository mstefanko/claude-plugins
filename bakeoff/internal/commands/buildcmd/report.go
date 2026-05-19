package buildcmd

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func renderBuildReport(wo *workorder.WorkOrder, runID string, outDir string, runDir string, decision map[string]any, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, diagnostics buildDiagnostics) string {
	_ = runDir
	lines := []string{
		"# Bakeoff Report: " + wo.ID,
		"",
		"## Outcome",
		"",
		"Mode: `build`",
		"Decision: `" + jsonutil.StringValue(decision["decision_kind"]) + "`",
	}
	if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
		lines = append(lines, "Winner: `"+winner+"`")
	} else {
		lines = append(lines, "Result: `"+jsonutil.StringValue(decision["decision_kind"])+"`")
	}
	lines = append(lines, "Selection basis: `"+jsonutil.StringValue(decision["selection_basis"])+"`")
	if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
		lines = append(lines, "Patch: `"+filepath.Join("providers", winner, "build", "diff.patch")+"`")
	}
	lines = append(lines, "Verifier gates: "+buildVerifierGateSummary(baseline, runs))
	if runID != "" {
		lines = append(lines, "Next: `"+ledger.BakeoffShowCommand(runID, outDir, "")+"`")
	}
	if len(diagnostics.SourceWarnings) > 0 {
		lines = append(lines, "", "## Source Context", "")
		for _, warning := range diagnostics.SourceWarnings {
			lines = append(lines, "- "+warning)
		}
	}
	lines = append(lines, "", "## Baseline Verification", "", fmt.Sprintf("- Gates passed: `%t`", baseline.GatesPassed))
	lines = append(lines, verifierLines(baseline.Results)...)
	lines = append(lines, "", "## Provider Builds", "")
	for _, run := range runs {
		lines = append(lines, fmt.Sprintf("### %s", run.ID), "")
		lines = append(lines, fmt.Sprintf("- Worker status: `%s`", jsonutil.StringValue(run.WorkerResult["status"])))
		lines = append(lines, fmt.Sprintf("- Gates passed: `%t`", run.Verify.GatesPassed))
		if run.Capture != nil {
			lines = append(lines, fmt.Sprintf("- Patch bytes: `%d`", run.Capture.PatchBytes))
			lines = append(lines, fmt.Sprintf("- Patch: `%s`", filepath.Join("providers", run.ID, "build", "diff.patch")))
			lines = append(lines, fmt.Sprintf("- Changed files: `%d`", len(run.Capture.ChangedFiles)))
			if len(run.ScopeDiagnostics.OutOfInvocationFiles) > 0 || len(run.ScopeDiagnostics.AgentInstructionFiles) > 0 {
				lines = append(lines, "- Scope diagnostics:")
				if len(run.ScopeDiagnostics.OutOfInvocationFiles) > 0 {
					lines = append(lines, "  - Out-of-invocation files:")
					lines = append(lines, changedFileBulletLines(run.ScopeDiagnostics.OutOfInvocationFiles)...)
				}
				if len(run.ScopeDiagnostics.AgentInstructionFiles) > 0 {
					lines = append(lines, "  - Agent instruction/config files:")
					lines = append(lines, changedFileBulletLines(run.ScopeDiagnostics.AgentInstructionFiles)...)
				}
			}
			if len(run.Capture.TestFiles) > 0 {
				lines = append(lines, "- Provider-authored tests:")
				lines = append(lines, changedFileBulletLines(run.Capture.TestFiles)...)
			}
			if len(run.Capture.BenchmarkFiles) > 0 {
				lines = append(lines, "- Provider-authored benchmarks/probes:")
				lines = append(lines, changedFileBulletLines(run.Capture.BenchmarkFiles)...)
			}
		}
		if len(run.ProtectedViolations) > 0 {
			lines = append(lines, "- Protected path changes:")
			for _, violation := range run.ProtectedViolations {
				lines = append(lines, fmt.Sprintf("  - `%s` changed `%s` (protected `%s`)", violation.Status, violation.ChangedPath, violation.ProtectedPath))
			}
		}
		if len(run.IneligibleReasons) > 0 {
			lines = append(lines, "- Ineligible reasons:")
			for _, reason := range run.IneligibleReasons {
				lines = append(lines, "  - "+reason)
			}
		}
		if final := jsonutil.FinalJSONMap(run.WorkerResult); len(final) > 0 {
			if risks := jsonutil.ListValue(final["risks"]); len(risks) > 0 {
				lines = append(lines, "- Provider risks:")
				for _, risk := range risks {
					lines = append(lines, "  - "+fmt.Sprint(risk))
				}
			}
			if checks := jsonutil.ListValue(final["manual_checks"]); len(checks) > 0 {
				lines = append(lines, "- Manual checks:")
				for _, check := range checks {
					lines = append(lines, "  - "+fmt.Sprint(check))
				}
			}
		}
		lines = append(lines, verifierLines(run.Verify.Results)...)
		lines = append(lines, "")
	}
	if len(metrics) > 0 {
		lines = append(lines, "## Metric Comparisons", "")
		for _, metric := range metrics {
			winner := metric.Winner
			if winner == "" {
				winner = "none"
			}
			reason := metric.Reason
			if reason == "" {
				reason = "clear thresholded winner"
			}
			lines = append(lines, fmt.Sprintf("- `%s`: winner `%s`, delta %.3g%%, min_delta %.3g%% met=%t, noise_floor %.3g%% met=%t (%s)", metric.ID, winner, metric.DeltaPercent, metric.MinDeltaPercent, metric.MeetsMinDelta, metric.NoiseFloorPercent, metric.MeetsNoiseFloor, reason))
		}
		lines = append(lines, "")
	}
	if len(diagnostics.BaselineMetricDeltas) > 0 {
		lines = append(lines, "## Baseline Metric Deltas", "")
		for _, delta := range diagnostics.BaselineMetricDeltas {
			direction := "unchanged"
			if delta.Improved {
				direction = "improved"
			} else if delta.DeltaPercent > 0 {
				direction = "regressed"
			}
			lines = append(lines, fmt.Sprintf("- `%s` %s: %s %.3g%% vs baseline (baseline %.6g, provider %.6g)", delta.ID, delta.ProviderID, direction, delta.DeltaPercent, delta.BaselineValue, delta.ProviderValue))
		}
		lines = append(lines, "")
	}
	if len(diagnostics.OutputTruncation) > 0 {
		lines = append(lines, "## Output Truncation", "")
		for _, item := range diagnostics.OutputTruncation {
			label := item.Scope
			if item.ProviderID != "" {
				label += ":" + item.ProviderID
			}
			if item.VerifierID != "" {
				label += ":" + item.VerifierID
			}
			lines = append(lines, fmt.Sprintf("- `%s` %s retained %d of %d observed bytes", label, item.Stream, item.RetainedBytes, item.ObservedBytes))
		}
		lines = append(lines, "", "Provider and verifier stdout/stderr artifacts are audit logs. Truncation is recorded for review, but it does not by itself change the decision when final JSON, patch capture, and verifier artifacts are available.")
		lines = append(lines, "")
	}
	if len(diagnostics.PatchIntegrityChecks) > 0 {
		lines = append(lines, "## Patch Integrity Checks", "")
		for _, check := range diagnostics.PatchIntegrityChecks {
			line := fmt.Sprintf("- `%s`: `%s`", check.ProviderID, check.Status)
			if check.Error != "" {
				line += " (" + check.Error + ")"
			}
			lines = append(lines, line)
		}
		lines = append(lines, "")
	}
	if len(diagnostics.PromptSizes) > 0 {
		lines = append(lines, "## Prompt Sizes", "")
		for _, size := range diagnostics.PromptSizes {
			label := size.Kind
			if size.ProviderID != "" {
				label += ":" + size.ProviderID
			}
			if size.Label != "" {
				label += ":" + size.Label
			}
			lines = append(lines, fmt.Sprintf("- `%s`: `%d` bytes (`%s`)", label, size.Bytes, size.Path))
		}
		lines = append(lines, "")
	}
	if len(diagnostics.PhaseTimings) > 0 {
		lines = append(lines, "## Phase Timings", "")
		for _, timing := range diagnostics.PhaseTimings {
			label := timing.Name
			if timing.ProviderID != "" {
				label += ":" + timing.ProviderID
			}
			if timing.Label != "" {
				label += ":" + timing.Label
			}
			lines = append(lines, fmt.Sprintf("- `%s`: %.3gs", label, timing.WallSeconds))
		}
		lines = append(lines, "")
	}
	if ran, _ := decision["judge_ran"].(bool); ran {
		lines = append(lines, "## Judge Audit", "")
		if maps, ok := decision["order_maps"].(map[string]any); ok {
			for _, pass := range []string{"pass1", "pass2"} {
				if raw, ok := maps[pass]; ok {
					order := buildJudgeOrderMap(raw)
					lines = append(lines, fmt.Sprintf("- %s: A=`%s`, B=`%s`", pass, order["A"], order["B"]))
				}
			}
		}
		if passes, ok := decision["judge_passes"].(map[string]any); ok {
			for _, pass := range []string{"pass1", "pass2"} {
				summary, _ := passes[pass].(map[string]any)
				if summary == nil {
					continue
				}
				winner := jsonutil.StringValue(summary["canonical_winner"])
				if winner == "" {
					winner = jsonutil.StringValue(summary["positional_winner"])
				}
				if winner == "" {
					winner = "none"
				}
				lines = append(lines, fmt.Sprintf("- %s winner: `%s`", pass, winner))
			}
		}
		for _, rationale := range jsonutil.ListValue(decision["judge_rationale"]) {
			if text := strings.TrimSpace(fmt.Sprint(rationale)); text != "" {
				lines = append(lines, "- "+text)
			}
		}
		lines = append(lines, "")
	}
	if winner, _ := decision["canonical_winner"].(string); winner != "" {
		lines = append(lines, "## Winner Handoff", "", "Winner: `"+winner+"`")
		lines = append(lines, "Checkpoint: Bakeoff selected this exact provider patch and has not applied it.")
		lines = append(lines, "Use this report and the selected patch artifact as handoff material for a fresh session before any repository changes.")
		lines = append(lines, "Post-run edits, synthesis, or reimplementation are outside this bakeoff decision. Treat any such result as a derived patch and rerun verification before citing it as ready.")
		if rationale := jsonutil.ListValue(decision["judge_rationale"]); len(rationale) > 0 && jsonutil.StringValue(decision["selection_basis"]) == "judge" {
			lines = append(lines, "Why: "+fmt.Sprint(rationale[0]))
		}
		if run := providerRunByID(runs, winner); run != nil {
			if run.Capture != nil {
				lines = append(lines, "Patch artifact: `"+filepath.Join("providers", winner, "build", "diff.patch")+"`")
				lines = append(lines, "Diffstat artifact: `"+filepath.Join("providers", winner, "build", "diffstat.txt")+"`")
				if len(run.Capture.TestFiles) > 0 {
					lines = append(lines, fmt.Sprintf("Provider-authored tests: `%d`", len(run.Capture.TestFiles)))
				}
				if len(run.Capture.BenchmarkFiles) > 0 {
					lines = append(lines, fmt.Sprintf("Provider-authored benchmarks/probes: `%d`", len(run.Capture.BenchmarkFiles)))
				}
			}
			if run.Cleanup.Retained {
				lines = append(lines, "Retained worktree: `"+run.WorktreePath+"`")
			}
			if final := jsonutil.FinalJSONMap(run.WorkerResult); len(final) > 0 {
				if risks := jsonutil.ListValue(final["risks"]); len(risks) > 0 {
					lines = append(lines, "Risks:")
					for _, risk := range risks {
						lines = append(lines, "- "+fmt.Sprint(risk))
					}
				}
				if checks := jsonutil.ListValue(final["manual_checks"]); len(checks) > 0 {
					lines = append(lines, "Manual checks:")
					for _, check := range checks {
						lines = append(lines, "- "+fmt.Sprint(check))
					}
				}
			}
		}
		lines = append(lines, "")
	}
	if caveats := jsonutil.ListValue(decision["caveats"]); len(caveats) > 0 {
		lines = append(lines, "## Caveats", "")
		for _, caveat := range caveats {
			lines = append(lines, "- "+fmt.Sprint(caveat))
		}
		lines = append(lines, "")
	}
	lines = append(lines, fmt.Sprintf("Run ID: `%s`", runID), "")
	return strings.Join(lines, "\n")
}

func buildJudgeOrderMap(raw any) map[string]string {
	switch order := raw.(type) {
	case map[string]string:
		return order
	case map[string]any:
		return map[string]string{"A": jsonutil.StringValue(order["A"]), "B": jsonutil.StringValue(order["B"])}
	default:
		return map[string]string{}
	}
}

func buildVerifierGateSummary(baseline buildverify.Result, runs []providerRun) string {
	parts := []string{"baseline=" + passFail(baseline.GatesPassed)}
	for _, run := range runs {
		parts = append(parts, run.ID+"="+passFail(run.Verify.GatesPassed))
	}
	return strings.Join(parts, ", ")
}

func buildResultLine(decision map[string]any) string {
	winner := jsonutil.StringValue(decision["canonical_winner"])
	if winner == "" {
		winner = "none"
	}
	return fmt.Sprintf("%s, winner=%s, basis=%s", jsonutil.StringValue(decision["decision_kind"]), winner, jsonutil.StringValue(decision["selection_basis"]))
}

func passFail(passed bool) string {
	if passed {
		return "passed"
	}
	return "failed"
}

func verifierLines(results []buildverify.VerifierResult) []string {
	if len(results) == 0 {
		return []string{"- Verifiers: none run"}
	}
	lines := []string{}
	for _, result := range results {
		line := fmt.Sprintf("- `%s` (%s): `%s`", result.ID, result.Kind, result.Status)
		if result.Metric != nil && result.Metric.Value != nil {
			line += fmt.Sprintf(", %s=%.6g", result.Metric.Name, *result.Metric.Value)
			if metadata := metricMetadataSummary(result.Metric); metadata != "" {
				line += ", " + metadata
			}
		} else if result.Metric != nil && result.Metric.Error != "" {
			line += ", metric inconclusive: " + result.Metric.Error
		}
		if result.Metric != nil && len(result.Metric.MetadataWarnings) > 0 {
			line += "; warnings: " + strings.Join(result.Metric.MetadataWarnings, "; ")
		}
		lines = append(lines, line)
	}
	return lines
}

func metricMetadataSummary(metric *buildverify.MetricResult) string {
	if metric == nil {
		return ""
	}
	parts := []string{}
	if metric.Unit != "" {
		parts = append(parts, "unit="+metric.Unit)
	}
	if metric.N != nil {
		parts = append(parts, fmt.Sprintf("n=%d", *metric.N))
	}
	if metric.Statistic != "" {
		parts = append(parts, "statistic="+metric.Statistic)
	}
	if metric.Method != "" {
		parts = append(parts, "method="+metric.Method)
	}
	return strings.Join(parts, ", ")
}

func changedFileBulletLines(files []buildworkspace.ChangedFile) []string {
	lines := []string{}
	for _, file := range files {
		lines = append(lines, fmt.Sprintf("  - `%s` %s", file.Status, file.Path))
	}
	return lines
}

func providerRunByID(runs []providerRun, id string) *providerRun {
	for i := range runs {
		if runs[i].ID == id {
			return &runs[i]
		}
	}
	return nil
}
