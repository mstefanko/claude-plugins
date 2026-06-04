package buildcmd

import (
	"context"
	"os"
	"path/filepath"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func buildJudgeNeeded(runs []providerRun, metrics []buildverify.MetricComparison) bool {
	gatePassed := []string{}
	for _, run := range runs {
		if patchState(run) == "patch_captured" && run.Verify.GatesPassed {
			gatePassed = append(gatePassed, run.ID)
		}
	}
	if len(gatePassed) != 2 {
		return false
	}
	if identicalEligiblePatchDigests(runs) {
		return false
	}
	metricWinner := ""
	for _, metric := range metrics {
		if !metric.Conclusive || metric.Winner == "" {
			continue
		}
		if metricWinner == "" {
			metricWinner = metric.Winner
			continue
		}
		if metricWinner != metric.Winner {
			return true
		}
	}
	return metricWinner == ""
}

func identicalEligiblePatchDigests(runs []providerRun) bool {
	digests := []string{}
	for _, run := range runs {
		if patchState(run) != "patch_captured" || !run.Verify.GatesPassed || run.Capture == nil || run.Capture.PatchDigest == "" {
			continue
		}
		digests = append(digests, run.Capture.PatchDigest)
	}
	return len(digests) == 2 && digests[0] == digests[1]
}

type buildJudgePhaseResult struct {
	JudgeResults map[string]map[string]any
	Pass1Order   map[string]string
	Pass2Order   map[string]string
	Timings      []buildPhaseTiming
	PromptTrims  []prompt.TrimRecord
}

func runBuildJudgePhase(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, runDir string, quiet bool, humanOutput bool) (buildJudgePhaseResult, error) {
	providerIDs := []string{wo.Providers[0].ID, wo.Providers[1].ID}
	byProvider := map[string]providerRun{}
	for _, run := range runs {
		byProvider[run.ID] = run
	}
	pass1Order := map[string]string{"A": providerIDs[0], "B": providerIDs[1]}
	pass2Order := map[string]string{"A": providerIDs[1], "B": providerIDs[0]}
	pass1, pass1Timing, pass1Trims, err := runSingleBuildJudge(ctx, f, wo, baseline, byProvider, metrics, pass1Order, runDir, "pass1", quiet, humanOutput)
	if err != nil {
		return buildJudgePhaseResult{}, err
	}
	pass2, pass2Timing, pass2Trims, err := runSingleBuildJudge(ctx, f, wo, baseline, byProvider, metrics, pass2Order, runDir, "pass2", quiet, humanOutput)
	if err != nil {
		return buildJudgePhaseResult{}, err
	}
	judgeResults := map[string]map[string]any{"pass1": jsonutil.FinalJSONMap(pass1), "pass2": jsonutil.FinalJSONMap(pass2)}
	if !artifact.ProviderSucceeded(pass1) || !artifact.ProviderSucceeded(pass2) {
		judgeResults["_failure"] = map[string]any{"pass1_status": pass1["status"], "pass2_status": pass2["status"]}
	}
	return buildJudgePhaseResult{
		JudgeResults: judgeResults,
		Pass1Order:   pass1Order,
		Pass2Order:   pass2Order,
		Timings:      []buildPhaseTiming{pass1Timing, pass2Timing},
		PromptTrims:  append(pass1Trims, pass2Trims...),
	}, nil
}

func runSingleBuildJudge(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, baseline buildverify.Result, runs map[string]providerRun, metrics []buildverify.MetricComparison, orderMap map[string]string, runDir string, label string, quiet bool, humanOutput bool) (map[string]any, buildPhaseTiming, []prompt.TrimRecord, error) {
	phaseStarted := time.Now()
	anonymizeCandidates := workorder.SameBackendModelScopeRun(wo)
	sharedEvidence := buildJudgeSharedEvidence(runDir, baseline, metrics, anonymizeCandidates)
	workerA := buildJudgePayloadForCandidate(runDir, runs[orderMap["A"]], "A", anonymizeCandidates)
	workerB := buildJudgePayloadForCandidate(runDir, runs[orderMap["B"]], "B", anonymizeCandidates)
	judgePrompt, err := prompt.BuildJudgePromptWithEvidence(wo, sharedEvidence, workerA, workerB, "build")
	if err != nil {
		return nil, buildPhaseTiming{}, nil, err
	}
	trimResult := prompt.TrimContextToBudget(judgePrompt, runner.MaxPromptBytes, "judge:"+label)
	commands.LogPromptTrim(f, trimResult)
	judgePrompt = trimResult.Text
	promptTrims := commands.TrimRecords(trimResult)
	judgeDir := filepath.Join(runDir, "judge")
	if err := os.MkdirAll(judgeDir, 0o700); err != nil {
		return nil, buildPhaseTiming{}, promptTrims, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, "prompt-"+label+".txt"), judgePrompt); err != nil {
		return nil, buildPhaseTiming{}, promptTrims, err
	}
	lastMessage := ""
	outputLastMessage := commands.OutputLastMessageSupported(ctx, f, wo.Judge)
	if outputLastMessage {
		lastMessage = filepath.Join(judgeDir, "last-message-"+label+".txt")
	}
	cwd, _ := os.Getwd()
	argv, err := provider.BuildParticipantArgv(wo.Judge, cwd, nil, lastMessage, outputLastMessage)
	if err != nil {
		return nil, buildPhaseTiming{}, promptTrims, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] running...\n", label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           judgePrompt,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              cwd,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        workorder.ValidateBuildJudgeResult,
		OnTick:           commands.MakeTickPrinter(f, "judge:"+label, quiet),
		FinalMessagePath: lastMessage,
	}))
	artifact.PreserveJudgeErrorKind(result)
	if err := artifact.WriteJudgeArtifacts(judgeDir, label, result); err != nil {
		return nil, buildPhaseTiming{}, promptTrims, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] %s %vs\n", label, result["status"], result["wall_seconds"])
	}
	return result, finishPhase("judge", "", label, phaseStarted), promptTrims, nil
}

func buildJudgeSharedEvidence(runDir string, baseline buildverify.Result, metrics []buildverify.MetricComparison, anonymize bool) map[string]any {
	return map[string]any{
		"baseline_verify":  compactVerifyResultForJudge(runDir, baseline, !anonymize, !anonymize),
		"metric_decisions": metricDecisionMaps(metrics),
	}
}

func buildJudgePayload(runDir string, run providerRun) map[string]any {
	return buildJudgePayloadForCandidate(runDir, run, "", false)
}

func buildJudgePayloadForCandidate(runDir string, run providerRun, label string, anonymize bool) map[string]any {
	payload := map[string]any{
		"worker_final_json": jsonutil.FinalJSONMap(run.WorkerResult),
		"runner_status":     compactRunnerStatusForJudge(run.WorkerResult, !anonymize),
		"workspace":         compactWorkspaceForJudge(runDir, run, !anonymize),
		"scope_diagnostics": run.ScopeDiagnostics,
		"verify":            compactVerifyResultForJudge(runDir, run.Verify, !anonymize, !anonymize),
	}
	if anonymize {
		payload["candidate_label"] = label
	} else {
		payload["provider_id"] = run.ID
	}
	if len(run.IneligibleReasons) > 0 {
		payload["ineligible_reasons"] = run.IneligibleReasons
	}
	if run.Capture != nil {
		patch := map[string]any{
			"patch_bytes":             run.Capture.PatchBytes,
			"patch_digest":            run.Capture.PatchDigest,
			"patch_over_cap":          run.Capture.PatchOverCap,
			"gitlink_change_rejected": run.Capture.GitlinkChangeRejected,
			"changed_files":           run.Capture.ChangedFiles,
			"test_files":              run.Capture.TestFiles,
			"benchmark_files":         run.Capture.BenchmarkFiles,
		}
		if len(run.ProtectedViolations) > 0 {
			patch["protected_path_violations"] = run.ProtectedViolations
			if !anonymize {
				patch["protected_paths_path"] = mustRelative(runDir, filepath.Join(runDir, "providers", run.ID, "build", "protected-paths.json"))
			}
		}
		if run.Capture.DiffstatPath != "" {
			if preview, truncated, err := readTextPreview(run.Capture.DiffstatPath, buildJudgeDiffstatPreviewBytes); err == nil {
				patch["diffstat"] = preview
				patch["diffstat_truncated"] = truncated
			} else {
				patch["diffstat_error"] = err.Error()
			}
			if !anonymize {
				if relative, err := relativePath(runDir, run.Capture.DiffstatPath); err == nil {
					patch["diffstat_path"] = relative
				} else {
					patch["diffstat_path"] = run.Capture.DiffstatPath
					patch["diffstat_path_error"] = err.Error()
				}
			}
		}
		if run.Capture.PatchPath != "" {
			if !anonymize {
				if relative, err := relativePath(runDir, run.Capture.PatchPath); err == nil {
					patch["patch_path"] = relative
				} else {
					patch["patch_path"] = run.Capture.PatchPath
					patch["patch_path_error"] = err.Error()
				}
			}
			if preview, truncated, err := readTextPreview(run.Capture.PatchPath, buildJudgePatchExcerptBytes); err == nil {
				patch["patch_excerpt"] = preview
				patch["patch_excerpt_truncated"] = truncated
			} else {
				patch["patch_excerpt_error"] = err.Error()
			}
		}
		payload["patch"] = patch
	}
	return payload
}

func compactRunnerStatusForJudge(result map[string]any, includePaths bool) map[string]any {
	status := artifact.StatusWithoutPayload(result)
	delete(status, "io")
	delete(status, "output_bytes")
	if scopeMetadata, ok := status["scope_enforcement"].(map[string]any); ok {
		compactScope := map[string]any{}
		for _, key := range []string{"requested_scope", "effective_scope", "enforcement_level", "policy", "mechanisms", "fallback_reason", "minimum_controls", "minimum_controls_satisfied", "minimum_control_failures", "temporary_cwd", "cwd"} {
			if key == "cwd" && !includePaths {
				continue
			}
			if value, exists := scopeMetadata[key]; exists {
				compactScope[key] = value
			}
		}
		status["scope_enforcement"] = compactScope
	}
	return status
}

func compactWorkspaceForJudge(runDir string, run providerRun, includePaths bool) map[string]any {
	out := map[string]any{
		"base_ref":                   run.Workspace.BaseRef,
		"base_commit":                shortCommit(run.Workspace.BaseCommit),
		"cleanup_status":             run.Workspace.CleanupStatus,
		"provider_head":              shortCommit(run.Workspace.ProviderHead),
		"provider_head_is_base":      run.Workspace.ProviderHeadIsBase,
		"provider_committed_changes": run.Workspace.ProviderCommittedChanges,
		"worktree_retained":          run.Workspace.WorktreeRetained,
		"worktree_removed":           run.Workspace.WorktreeRemoved,
	}
	if includePaths {
		out["provider_cwd"] = mustRelative(runDir, run.Workspace.ProviderCWD)
	}
	return out
}

func compactVerifyResultForJudge(runDir string, result buildverify.Result, includeProviderID bool, includePaths bool) map[string]any {
	out := map[string]any{
		"scope":        result.Scope,
		"gates_passed": result.GatesPassed,
		"results":      compactVerifierResultsForJudge(runDir, result.Results, includePaths),
	}
	if includeProviderID && result.ProviderID != "" {
		out["provider_id"] = result.ProviderID
	}
	return out
}

func compactVerifierResultsForJudge(runDir string, results []buildverify.VerifierResult, includePaths bool) []map[string]any {
	out := make([]map[string]any, 0, len(results))
	for _, result := range results {
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
		if includePaths && result.StdoutPath != "" {
			entry["stdout_path"] = mustRelative(runDir, result.StdoutPath)
		}
		if includePaths && result.StderrPath != "" {
			entry["stderr_path"] = mustRelative(runDir, result.StderrPath)
		}
		if includePaths && result.StatusPath != "" {
			entry["status_path"] = mustRelative(runDir, result.StatusPath)
		}
		if includePaths && result.MetricPath != "" {
			entry["metric_path"] = mustRelative(runDir, result.MetricPath)
		}
		if result.BaselineExpectation != "" {
			entry["baseline_expectation"] = result.BaselineExpectation
		}
		if result.BaselineMatched != nil {
			entry["baseline_matched"] = *result.BaselineMatched
		}
		if result.Transition != "" {
			entry["transition"] = result.Transition
		}
		if result.ArtifactError != "" {
			entry["artifact_error"] = result.ArtifactError
		}
		if result.Metric != nil {
			entry["metric"] = result.Metric
		}
		out = append(out, entry)
	}
	return out
}
