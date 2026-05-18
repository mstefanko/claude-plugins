package buildcmd

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/scope"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var buildLockTimeout = 5 * time.Second

type providerRun struct {
	ID                  string
	WorktreePath        string
	WorkerResult        map[string]any
	Capture             *buildworkspace.CaptureResult
	Verify              buildverify.Result
	Cleanup             buildworkspace.CleanupResult
	ScopeMetadata       map[string]any
	IneligibleReasons   []string
	Workspace           buildworkspace.WorkspaceMetadata
	ProviderArtifactDir string
}

func RunBuild(ctx context.Context, f commands.Factory, opts *BuildOptions) error {
	humanOutput := !opts.JSON
	effectiveQuiet := opts.Quiet || opts.JSON
	wo, err := workorder.Load(opts.WorkOrder)
	if err != nil {
		return commands.WrapValidation(err)
	}
	if wo.Type != "build" {
		return &apperror.ValidationError{Message: fmt.Sprintf(`type %q work orders must be run with bakeoff research`, wo.Type)}
	}
	sourceText, err := os.ReadFile(opts.WorkOrder)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	runID := opts.RunID
	if runID == "" {
		runID = ledger.MakeRunID(f.Now(), randomSuffix())
	}
	if err := ledger.ValidateRunID(runID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	runDir := ledger.RunDir(opts.Out, runID)
	startedAt := artifact.UTCNow()
	cwd, _ := os.Getwd()
	commonDir, err := buildworkspace.ResolveCommonDir(ctx, cwd)
	if err != nil {
		return commands.WrapValidation(workorder.Validationf("%v", err))
	}
	setupLock, err := buildworkspace.AcquireLock(ctx, commonDir, buildLockTimeout)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	releaseSetupLock := func() error {
		if setupLock == nil {
			return nil
		}
		err := setupLock.Release()
		setupLock = nil
		return err
	}
	defer releaseSetupLock()

	repo, err := buildworkspace.ResolveRepository(ctx, cwd, wo.Build.BaseRef)
	if err != nil {
		return commands.WrapValidation(workorder.Validationf("%v", err))
	}
	if _, err := os.Stat(runDir); err == nil {
		if !opts.Force {
			return &apperror.ValidationError{Message: fmt.Sprintf("%s already exists; use --force to replace", runDir)}
		}
		if err := ledger.EnsureChildPath(opts.Out, runDir); err != nil {
			return &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		if err := forceRemoveRunDir(ctx, repo, runDir); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	} else if err != nil && !os.IsNotExist(err) {
		return &apperror.RuntimeError{Err: err}
	}

	parent, err := buildworkspace.PrepareWorktreeParent(ctx, repo, runDir)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := ledger.UpdateLatest(opts.Out, runID); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), string(sourceText)); err != nil {
		return &apperror.RuntimeError{Err: err}
	}

	providerIDs := providerIDs(wo)
	verifierMetadata := verifierMetadata(wo)
	contextMetadata := buildworkspace.ContextFrom(repo, runID, parent, providerIDs, verifierMetadata)
	if humanOutput {
		printBuildHeader(f, wo, runDir, runID, repo)
	}

	baselinePath := filepath.Join(parent.Path, "baseline")
	contextMetadata.BaselineWorktreePath = baselinePath
	if err := buildworkspace.CreateDetachedWorktree(ctx, repo, baselinePath); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	// The repo build lock guards git worktree admin mutations and source
	// preflight. Baseline verification runs outside the lock in an already
	// detached worktree; cleanup reacquires the lock before removing metadata.
	if err := releaseSetupLock(); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		f.Streams().Printf("[baseline] verifying...\n")
	}
	baseline := buildverify.Run(ctx, buildverify.Options{
		CWD:                   baselinePath,
		Baseline:              true,
		Verifiers:             wo.Build.Verify,
		Env:                   buildEnv(os.Environ()),
		HeartbeatSeconds:      wo.Budgets.HeartbeatSeconds,
		OutputCapGraceSeconds: wo.Budgets.OutputCapGraceSeconds,
		MaxOutputOverrunBytes: wo.Budgets.MaxOutputOverrunBytes,
		ArtifactDir:           filepath.Join(runDir, "verify", "baseline"),
		OnTick:                makeVerifierTickPrinter(f, effectiveQuiet),
	})
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "verify", "baseline", "result.json"), baseline); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	baselineCleanup, err := cleanupWorktree(ctx, repo, baselinePath, opts.KeepWorktrees)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	contextMetadata.BaselineCleanupStatus = baselineCleanup.Status
	if err := buildworkspace.WriteContext(runDir, contextMetadata); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		printVerifierSummary(f, "baseline", baseline)
	}

	if !baseline.GatesPassed {
		workerResults := emptyWorkerResults(wo)
		decision := buildDecision(wo, workerResults, nil, baseline, nil, "baseline_failed", "none", "", []string{"baseline gate verifier failed; providers were not launched"})
		exitCode := 1
		if err := finalizeBuildRun(ctx, f, opts, wo, runDir, runID, startedAt, workerResults, decision, baseline, nil, nil, exitCode, humanOutput); err != nil {
			return err
		}
		return buildExitError(exitCode, "baseline verification failed")
	}

	worktreePaths := map[string]string{}
	if err := withRepoLock(ctx, repo, func() error {
		for _, participant := range wo.Providers {
			path := filepath.Join(parent.Path, participant.ID)
			if err := buildworkspace.CreateDetachedWorktree(ctx, repo, path); err != nil {
				return err
			}
			worktreePaths[participant.ID] = path
		}
		return nil
	}); err != nil {
		for _, path := range worktreePaths {
			_, _ = cleanupWorktree(ctx, repo, path, false)
		}
		return &apperror.RuntimeError{Err: err}
	}

	capabilities := providerCapabilities(ctx, f, wo)
	if humanOutput {
		for _, participant := range wo.Providers {
			f.Streams().Printf("[%s] launching in worktree...\n", participant.ID)
		}
	}
	providerRuns, err := runBuildProviders(ctx, f, wo, repo, runDir, worktreePaths, capabilities, opts.KeepWorktrees, effectiveQuiet)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return err
		}
		return &apperror.RuntimeError{Err: err}
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	workerResults := map[string]map[string]any{}
	verifyResults := map[string]buildverify.Result{}
	for _, run := range providerRuns {
		workerResults[run.ID] = run.WorkerResult
		verifyResults[run.ID] = run.Verify
		if humanOutput {
			printBuildProviderResult(f, run)
		}
	}
	metricComparisons := buildverify.CompareMetrics(wo.Build.Verify, providerIDs, verifyResults)
	decisionKind, selectionBasis, winner, exitCode, caveats := selectBuildWinner(providerRuns, metricComparisons)
	decision := buildDecision(wo, workerResults, providerRuns, baseline, metricComparisons, decisionKind, selectionBasis, winner, caveats)
	if err := finalizeBuildRun(ctx, f, opts, wo, runDir, runID, startedAt, workerResults, decision, baseline, providerRuns, metricComparisons, exitCode, humanOutput); err != nil {
		return err
	}
	return buildExitError(exitCode, "build failed")
}

func runBuildProviders(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, worktreePaths map[string]string, capabilities map[string]provider.ScopeCapabilities, keepWorktrees bool, quiet bool) ([]providerRun, error) {
	group, groupCtx := errgroup.WithContext(ctx)
	results := make([]providerRun, len(wo.Providers))
	for index, participant := range wo.Providers {
		index := index
		participant := participant
		group.Go(func() error {
			run, err := runOneBuildProvider(groupCtx, f, wo, participant, repo, runDir, worktreePaths[participant.ID], capabilities[participant.Backend], keepWorktrees, quiet)
			if err != nil && !errors.Is(err, context.Canceled) {
				run = providerRun{
					ID:                  participant.ID,
					WorktreePath:        worktreePaths[participant.ID],
					WorkerResult:        internalErrorResult(err),
					ProviderArtifactDir: filepath.Join(runDir, "providers", participant.ID),
					IneligibleReasons:   []string{err.Error()},
				}
				if mkdirErr := os.MkdirAll(run.ProviderArtifactDir, 0o755); mkdirErr != nil {
					return mkdirErr
				}
				if writeErr := artifact.WriteProviderArtifacts(run.ProviderArtifactDir, run.WorkerResult); writeErr != nil {
					return writeErr
				}
			} else if err != nil {
				return err
			}
			results[index] = run
			return nil
		})
	}
	if err := group.Wait(); err != nil {
		return nil, err
	}
	return results, nil
}

func runOneBuildProvider(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, participant workorder.Participant, repo buildworkspace.Repository, runDir string, worktreePath string, caps provider.ScopeCapabilities, keepWorktrees bool, quiet bool) (run providerRun, err error) {
	providerDir := filepath.Join(runDir, "providers", participant.ID)
	buildDir := filepath.Join(providerDir, "build")
	run = providerRun{
		ID:                  participant.ID,
		WorktreePath:        worktreePath,
		ProviderArtifactDir: providerDir,
	}
	cleanupRecorded := false
	defer func() {
		if cleanupRecorded || worktreePath == "" {
			return
		}
		cleanup, cleanupErr := cleanupWorktree(ctx, repo, worktreePath, keepWorktrees)
		run.Cleanup = cleanup
		if cleanupErr != nil {
			run.IneligibleReasons = append(run.IneligibleReasons, "worktree cleanup failed: "+cleanupErr.Error())
			if err == nil {
				err = cleanupErr
			}
		}
	}()
	if err := os.MkdirAll(providerDir, 0o755); err != nil {
		return run, err
	}
	if err := os.MkdirAll(buildDir, 0o755); err != nil {
		return run, err
	}
	workerPrompt, err := prompt.BuildWorkerPrompt(wo, participant)
	if err != nil {
		return run, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(providerDir, "prompt.txt"), workerPrompt); err != nil {
		return run, err
	}
	finalMessagePath := ""
	if participant.Backend == "codex" && caps.Supports["output_last_message"] {
		finalMessagePath = filepath.Join(providerDir, "last-message.txt")
	}
	argv, scopeMetadata, err := buildParticipantArgv(participant, wo.ScopePolicy, worktreePath, caps, finalMessagePath)
	run.ScopeMetadata = scopeMetadata
	if err != nil {
		result := scope.ScopeErrorResult(err, participant, wo.ScopePolicy, worktreePath)
		result["scope_enforcement"] = scopeMetadata
		run.WorkerResult = result
		run.IneligibleReasons = append(run.IneligibleReasons, "scope enforcement failed")
		if writeErr := artifact.WriteProviderArtifacts(providerDir, result); writeErr != nil {
			return run, writeErr
		}
	} else {
		result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
			Argv:             argv,
			Prompt:           workerPrompt,
			Budgets:          commands.RunnerBudgets(wo.Budgets),
			CWD:              worktreePath,
			Env:              buildEnv(os.Environ()),
			Validator:        func(data any) (any, error) { return workorder.ValidateWorkerResult(data, wo.Type) },
			OnTick:           commands.MakeTickPrinter(f, participant.ID, quiet),
			FinalMessagePath: finalMessagePath,
		}))
		result["scope_enforcement"] = scopeMetadata
		run.WorkerResult = result
		if err := artifact.WriteProviderArtifacts(providerDir, result); err != nil {
			return run, err
		}
	}

	if !artifact.ProviderSucceeded(run.WorkerResult) {
		run.IneligibleReasons = append(run.IneligibleReasons, "provider did not complete successfully")
	}
	if finalStatus(finalJSONMap(run.WorkerResult)) == "blocked" {
		run.IneligibleReasons = append(run.IneligibleReasons, "provider reported blocked")
	}
	if len(run.IneligibleReasons) == 0 {
		capture, captureErr := buildworkspace.CaptureChanges(ctx, buildworkspace.CaptureOptions{
			WorktreePath:  worktreePath,
			BaseCommit:    repo.BaseCommit,
			OutputDir:     buildDir,
			PatchMaxBytes: wo.Build.PatchMaxBytes,
		})
		if captureErr != nil {
			run.IneligibleReasons = append(run.IneligibleReasons, "patch capture failed: "+captureErr.Error())
		} else {
			run.Capture = &capture
			if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "capture.json"), capture); err != nil {
				return run, err
			}
			if capture.PatchOverCap {
				run.IneligibleReasons = append(run.IneligibleReasons, "patch exceeded build.patch_max_bytes")
			}
			if capture.GitlinkChangeRejected {
				run.IneligibleReasons = append(run.IneligibleReasons, "patch includes gitlink/submodule changes")
			}
		}
	}
	if len(run.IneligibleReasons) == 0 {
		run.Verify = buildverify.Run(ctx, buildverify.Options{
			CWD:                   worktreePath,
			ProviderID:            participant.ID,
			Verifiers:             wo.Build.Verify,
			Env:                   buildEnv(os.Environ()),
			HeartbeatSeconds:      wo.Budgets.HeartbeatSeconds,
			OutputCapGraceSeconds: wo.Budgets.OutputCapGraceSeconds,
			MaxOutputOverrunBytes: wo.Budgets.MaxOutputOverrunBytes,
			ArtifactDir:           filepath.Join(providerDir, "verify"),
			OnTick:                makeVerifierTickPrinter(f, quiet),
		})
	} else {
		run.Verify = buildverify.Result{Scope: "provider", ProviderID: participant.ID, GatesPassed: false}
	}
	if err := os.MkdirAll(filepath.Join(providerDir, "verify"), 0o755); err != nil {
		return run, err
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(providerDir, "verify", "result.json"), run.Verify); err != nil {
		return run, err
	}
	cleanup, err := cleanupWorktree(ctx, repo, worktreePath, keepWorktrees)
	cleanupRecorded = true
	if err != nil {
		run.IneligibleReasons = append(run.IneligibleReasons, "worktree cleanup failed: "+err.Error())
		cleanup = buildworkspace.CleanupResult{Path: worktreePath, Status: "failed", Error: err.Error()}
	}
	run.Cleanup = cleanup
	run.Workspace = workspaceMetadata(repo, participant, worktreePath, cleanup, run.Capture)
	if err := buildworkspace.WriteWorkspace(filepath.Join(buildDir, "workspace.json"), run.Workspace); err != nil {
		return run, err
	}
	if len(run.IneligibleReasons) > 0 {
		if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "ineligible.json"), map[string]any{"reasons": run.IneligibleReasons}); err != nil {
			return run, err
		}
	}
	return run, nil
}

func buildParticipantArgv(participant workorder.Participant, policy workorder.ScopePolicy, worktreePath string, caps provider.ScopeCapabilities, finalMessagePath string) ([]string, map[string]any, error) {
	requestedScope := participant.Scope
	if requestedScope == "" {
		requestedScope = "mixed"
	}
	enforcement := policy.Enforcement
	if enforcement == "" {
		enforcement = "best_effort"
	}
	supports := caps.Supports
	if supports == nil {
		supports = map[string]bool{}
	}
	extraArgs := []string{}
	mechanisms := []string{"worktree_cwd"}
	fallbackReasons := []string{}
	switch participant.Backend {
	case "claude":
		if requestedScope == "codebase" {
			if supports["disallowed_tools"] {
				extraArgs = append(extraArgs, "--disallowedTools", "WebFetch", "WebSearch")
				mechanisms = append(mechanisms, "claude:disallowedTools=WebFetch,WebSearch")
			} else {
				fallbackReasons = append(fallbackReasons, "claude CLI did not advertise --disallowedTools")
			}
		}
	case "codex":
		if supports["sandbox_workspace_write"] {
			extraArgs = append(extraArgs, "--sandbox", "workspace-write")
			mechanisms = append(mechanisms, "codex:sandbox=workspace-write")
		} else {
			fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --sandbox workspace-write")
		}
		if requestedScope == "codebase" {
			if supports["disable_feature"] {
				extraArgs = append(extraArgs, "--disable", "web_search")
				mechanisms = append(mechanisms, "codex:disable=web_search")
			} else {
				fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --disable")
			}
		}
	}
	if participant.Backend == "codex" && !supports["sandbox_workspace_write"] {
		metadata := map[string]any{
			"requested_scope":   requestedScope,
			"policy":            enforcement,
			"effective_scope":   "advisory",
			"enforcement_level": "failed",
			"mechanisms":        mechanisms,
			"fallback_reason":   strings.Join(fallbackReasons, "; "),
			"cwd":               worktreePath,
			"temporary_cwd":     false,
		}
		return nil, metadata, &scope.EnforcementError{Message: strings.Join(fallbackReasons, "; ")}
	}
	metadata := map[string]any{
		"requested_scope":   requestedScope,
		"policy":            enforcement,
		"effective_scope":   requestedScope,
		"enforcement_level": "enforced",
		"mechanisms":        mechanisms,
		"fallback_reason":   nil,
		"cwd":               worktreePath,
		"temporary_cwd":     false,
	}
	if len(fallbackReasons) > 0 {
		metadata["fallback_reason"] = strings.Join(fallbackReasons, "; ")
		if enforcement == "required" {
			metadata["effective_scope"] = "advisory"
			metadata["enforcement_level"] = "failed"
			return nil, metadata, &scope.EnforcementError{Message: strings.Join(fallbackReasons, "; ")}
		}
		metadata["enforcement_level"] = "partial"
	}
	argv, err := provider.BuildParticipantArgv(participant, worktreePath, extraArgs, finalMessagePath, caps.Supports["output_last_message"])
	return argv, metadata, err
}

func buildEnv(environ []string) []string {
	out := make([]string, 0, len(environ))
	for _, entry := range environ {
		key, _, found := strings.Cut(entry, "=")
		if !found || shouldScrubEnvKey(key) {
			continue
		}
		out = append(out, entry)
	}
	return out
}

func shouldScrubEnvKey(key string) bool {
	upper := strings.ToUpper(key)
	if strings.HasPrefix(upper, "ANTHROPIC_") || strings.HasPrefix(upper, "OPENAI_") {
		return true
	}
	for _, marker := range []string{"API_KEY", "ACCESS_KEY", "PRIVATE_KEY", "SECRET", "TOKEN", "PASSWORD"} {
		if strings.Contains(upper, marker) {
			return true
		}
	}
	return false
}

func providerCapabilities(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder) map[string]provider.ScopeCapabilities {
	out := map[string]provider.ScopeCapabilities{}
	for _, participant := range wo.Providers {
		if _, ok := out[participant.Backend]; ok {
			continue
		}
		out[participant.Backend] = f.Capabilities().DetectScopeCapabilities(ctx, participant.Backend)
	}
	return out
}

func selectBuildWinner(runs []providerRun, metrics []buildverify.MetricComparison) (string, string, string, int, []string) {
	gatePassed := []string{}
	for _, run := range runs {
		if len(run.IneligibleReasons) == 0 && run.Verify.GatesPassed {
			gatePassed = append(gatePassed, run.ID)
		}
	}
	switch len(gatePassed) {
	case 0:
		return "both_failed_verification", "gate", "", 1, []string{"no provider passed required gate verifiers"}
	case 1:
		return "single_provider_only", "gate", gatePassed[0], 0, []string{"required gate verifiers selected the only passing provider"}
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
			return "tie", "none", "", 3, []string{"metric verifiers selected conflicting winners; build judge is not implemented until Phase 5"}
		}
	}
	if metricWinner != "" {
		return "pick_winner", "metric", metricWinner, 0, []string{}
	}
	return "tie", "none", "", 3, []string{"both providers passed gates; no metric verifier produced a clear winner; build judge is not implemented until Phase 5"}
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
			entry["patch_over_cap"] = run.Capture.PatchOverCap
			entry["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			entry["patch_path"] = "providers/" + run.ID + "/build/diff.patch"
			entry["changed_files"] = run.Capture.ChangedFiles
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

func finalizeBuildRun(ctx context.Context, f commands.Factory, opts *BuildOptions, wo *workorder.WorkOrder, runDir string, runID string, startedAt string, workerResults map[string]map[string]any, decision map[string]any, baseline buildverify.Result, providerRuns []providerRun, metrics []buildverify.MetricComparison, exitCode int, humanOutput bool) error {
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), decision); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	reportText := renderBuildReport(wo, runID, runDir, decision, baseline, providerRuns, metrics)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), reportText); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := artifact.WriteMeta(ctx, runDir, wo, runID, startedAt, workerResults, f.LookupProvider); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		f.Streams().Printf("manifest: %s\n", filepath.Join(runDir, "manifest.json"))
		f.Streams().Printf("report: %s\n", filepath.Join(runDir, "report.md"))
		if winner, _ := decision["canonical_winner"].(string); winner != "" {
			f.Streams().Printf("patch:  %s\n", filepath.Join(runDir, "providers", winner, "build", "diff.patch"))
		}
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(runID, opts.Out, ""))
	}
	if opts.JSON {
		if err := summary.Print(f.Streams().Out, buildSummary(runDir, runID, opts.Out, decision, baseline, providerRuns, metrics, exitCode)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	return nil
}

func renderBuildReport(wo *workorder.WorkOrder, runID string, runDir string, decision map[string]any, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison) string {
	lines := []string{
		"# Bakeoff Report: " + wo.ID,
		"",
		"Mode: `build`",
		"Decision: `" + stringValue(decision["decision_kind"]) + "`",
		"Selection basis: `" + stringValue(decision["selection_basis"]) + "`",
		"",
		"## Baseline Verification",
		"",
		fmt.Sprintf("- Gates passed: `%t`", baseline.GatesPassed),
	}
	lines = append(lines, verifierLines(baseline.Results)...)
	lines = append(lines, "", "## Provider Builds", "")
	for _, run := range runs {
		lines = append(lines, fmt.Sprintf("### %s", run.ID), "")
		lines = append(lines, fmt.Sprintf("- Worker status: `%s`", stringValue(run.WorkerResult["status"])))
		lines = append(lines, fmt.Sprintf("- Gates passed: `%t`", run.Verify.GatesPassed))
		if run.Capture != nil {
			lines = append(lines, fmt.Sprintf("- Patch bytes: `%d`", run.Capture.PatchBytes))
			lines = append(lines, fmt.Sprintf("- Patch: `%s`", filepath.Join("providers", run.ID, "build", "diff.patch")))
		}
		if len(run.IneligibleReasons) > 0 {
			lines = append(lines, "- Ineligible reasons:")
			for _, reason := range run.IneligibleReasons {
				lines = append(lines, "  - "+reason)
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
			lines = append(lines, fmt.Sprintf("- `%s`: winner `%s`, delta %.3g%%, threshold %.3g%% (%s)", metric.ID, winner, metric.DeltaPercent, metric.Threshold, reason))
		}
		lines = append(lines, "")
	}
	if winner, _ := decision["canonical_winner"].(string); winner != "" {
		patch := filepath.Join(runDir, "providers", winner, "build", "diff.patch")
		lines = append(lines, "## Winner Handoff", "", "Winner: `"+winner+"`", "", "```text", "git apply --3way --binary "+patch, "```", "")
	}
	if caveats := listValue(decision["caveats"]); len(caveats) > 0 {
		lines = append(lines, "## Caveats", "")
		for _, caveat := range caveats {
			lines = append(lines, "- "+fmt.Sprint(caveat))
		}
		lines = append(lines, "")
	}
	lines = append(lines, fmt.Sprintf("Run ID: `%s`", runID), "")
	return strings.Join(lines, "\n")
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
		} else if result.Metric != nil && result.Metric.Error != "" {
			line += ", metric inconclusive: " + result.Metric.Error
		}
		lines = append(lines, line)
	}
	return lines
}

func buildSummary(runDir string, runID string, outDir string, decision map[string]any, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, exitCode int) map[string]any {
	providers := map[string]any{}
	for _, run := range runs {
		entry := map[string]any{
			"status":             summary.CompactStatus(run.WorkerResult["status"]),
			"raw_status":         run.WorkerResult["status"],
			"gates_passed":       run.Verify.GatesPassed,
			"ineligible_reasons": run.IneligibleReasons,
		}
		if run.Capture != nil {
			entry["patch_bytes"] = run.Capture.PatchBytes
			entry["patch_path"] = filepath.Join(runDir, "providers", run.ID, "build", "diff.patch")
		}
		providers[run.ID] = entry
	}
	return map[string]any{
		"schema_version":   1,
		"command":          "build",
		"status":           buildCommandStatus(exitCode),
		"exit_code":        exitCode,
		"warnings":         []string{},
		"run_id":           runID,
		"mode":             "build",
		"run_dir":          runDir,
		"decision_kind":    decision["decision_kind"],
		"selection_basis":  decision["selection_basis"],
		"winner":           decision["canonical_winner"],
		"baseline":         map[string]any{"gates_passed": baseline.GatesPassed, "results": baseline.Results},
		"providers":        providers,
		"metric_summaries": metrics,
		"artifacts":        buildArtifactPaths(runDir),
		"next":             ledger.BakeoffShowCommand(runID, outDir, ""),
	}
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
		"decision":      "decision.json",
		"meta":          "meta.json",
		"manifest":      "manifest.json",
		"report":        "report.md",
	} {
		path := filepath.Join(runDir, relative)
		if fileExists(path) {
			out[key] = path
		}
	}
	return out
}

func workspaceMetadata(repo buildworkspace.Repository, participant workorder.Participant, worktreePath string, cleanup buildworkspace.CleanupResult, capture *buildworkspace.CaptureResult) buildworkspace.WorkspaceMetadata {
	workspace := buildworkspace.WorkspaceMetadata{
		GitRoot:          repo.Root,
		BaseRef:          repo.BaseRef,
		BaseCommit:       repo.BaseCommit,
		WorktreePath:     worktreePath,
		WorktreeRetained: cleanup.Retained,
		WorktreeRemoved:  cleanup.Status == "removed",
		CleanupStatus:    cleanup.Status,
		ProviderID:       participant.ID,
		ProviderBackend:  participant.Backend,
		ProviderModel:    participant.Model,
		ProviderEffort:   participant.Effort,
	}
	if capture != nil {
		workspace.ProviderHead = capture.ProviderHead
		workspace.ProviderHeadIsBase = capture.ProviderHeadIsBase
		workspace.ProviderCommittedChanges = capture.ProviderCommittedChanges
	}
	return workspace
}

func cleanupWorktree(ctx context.Context, repo buildworkspace.Repository, path string, keep bool) (buildworkspace.CleanupResult, error) {
	var result buildworkspace.CleanupResult
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
	defer cancel()
	err := withRepoLock(cleanupCtx, repo, func() error {
		result = buildworkspace.CleanupWorktree(cleanupCtx, repo, path, keep)
		if result.Status == "failed" {
			return errors.New(result.Error)
		}
		return nil
	})
	return result, err
}

func forceRemoveRunDir(ctx context.Context, repo buildworkspace.Repository, runDir string) error {
	worktreeParent := filepath.Join(runDir, "worktrees")
	entries, err := os.ReadDir(worktreeParent)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		result := buildworkspace.CleanupWorktree(ctx, repo, filepath.Join(worktreeParent, entry.Name()), false)
		if result.Status == "failed" {
			return errors.New(result.Error)
		}
	}
	return os.RemoveAll(runDir)
}

func withRepoLock(ctx context.Context, repo buildworkspace.Repository, fn func() error) error {
	lock, err := buildworkspace.AcquireLock(ctx, repo.CommonDir, buildLockTimeout)
	if err != nil {
		return err
	}
	err = fn()
	if releaseErr := lock.Release(); err == nil {
		err = releaseErr
	}
	return err
}

func printBuildHeader(f commands.Factory, wo *workorder.WorkOrder, runDir string, runID string, repo buildworkspace.Repository) {
	providers := []string{}
	for _, participant := range wo.Providers {
		providers = append(providers, fmt.Sprintf("%s (%s, %s)", participant.ID, participant.Model, participant.Scope))
	}
	f.Streams().Printf("bakeoff build     run-id: %s\n", runID)
	f.Streams().Printf("  mode:           %s\n", wo.Type)
	f.Streams().Printf("  run dir:        %s/\n", runDir)
	f.Streams().Printf("  base:           %s (%s)\n", repo.BaseRef, shortCommit(repo.BaseCommit))
	f.Streams().Printf("  providers:      %s\n", strings.Join(providers, ", "))
	f.Streams().Printf("  budgets:        %s\n", workorder.FormatBudgetSummary(wo.Budgets))
	f.Streams().Printf("  scope policy:   %s\n", wo.ScopePolicy.Enforcement)
}

func printVerifierSummary(f commands.Factory, label string, result buildverify.Result) {
	f.Streams().Printf("[%s] gates passed: %t\n", label, result.GatesPassed)
}

func printBuildProviderResult(f commands.Factory, run providerRun) {
	status := stringValue(run.WorkerResult["status"])
	f.Streams().Printf("[%s] %s gates=%t", run.ID, status, run.Verify.GatesPassed)
	if run.Capture != nil {
		f.Streams().Printf(" patch=%d bytes", run.Capture.PatchBytes)
	}
	if len(run.IneligibleReasons) > 0 {
		f.Streams().Printf(" ineligible=%s", strings.Join(run.IneligibleReasons, "; "))
	}
	f.Streams().Printf("\n")
}

func makeVerifierTickPrinter(f commands.Factory, quiet bool) func(string, runner.Tick) {
	if quiet {
		return nil
	}
	return func(label string, tick runner.Tick) {
		commands.MakeTickPrinter(f, label, false)(tick)
	}
}

func emptyWorkerResults(wo *workorder.WorkOrder) map[string]map[string]any {
	results := map[string]map[string]any{}
	for _, participant := range wo.Providers {
		results[participant.ID] = map[string]any{}
	}
	return results
}

func providerIDs(wo *workorder.WorkOrder) []string {
	ids := make([]string, 0, len(wo.Providers))
	for _, participant := range wo.Providers {
		ids = append(ids, participant.ID)
	}
	return ids
}

func verifierMetadata(wo *workorder.WorkOrder) []buildworkspace.VerifierMetadata {
	out := []buildworkspace.VerifierMetadata{}
	for _, verifier := range wo.Build.Verify {
		out = append(out, buildworkspace.VerifierMetadata{ID: verifier.ID, Kind: verifier.Kind})
	}
	return out
}

func internalErrorResult(err error) map[string]any {
	message := fmt.Sprintf("internal build task error: %T: %v", err, err)
	stderrBytes := len([]byte(message))
	return map[string]any{
		"status":                runner.StatusExitError,
		"exit_code":             nil,
		"wall_seconds":          0,
		"output_bytes":          0,
		"stdout_bytes":          0,
		"stderr_bytes":          stderrBytes,
		"stdout_observed_bytes": 0,
		"stderr_observed_bytes": stderrBytes,
		"stdout_truncated":      false,
		"stderr_truncated":      false,
		"io":                    map[string]any{"stdout_bytes": 0, "stderr_bytes": stderrBytes, "stdout_observed_bytes": 0, "stderr_observed_bytes": stderrBytes, "total_observed_bytes": stderrBytes},
		"stdout":                "",
		"stderr":                message,
		"final_json":            nil,
	}
}

func buildExitError(exitCode int, message string) error {
	if exitCode == 0 {
		return nil
	}
	if exitCode == 3 {
		return &apperror.SilentError{Err: &apperror.JudgeDisagreementError{Message: "build unresolved"}}
	}
	return &apperror.SilentError{Err: fmt.Errorf("%s", message)}
}

func finalJSONMap(result map[string]any) map[string]any {
	final, _ := result["final_json"].(map[string]any)
	if final == nil {
		return map[string]any{}
	}
	return final
}

func finalStatus(final map[string]any) string {
	status, _ := final["status"].(string)
	return status
}

func nilIfEmpty(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func listValue(value any) []any {
	items, _ := value.([]any)
	if items == nil {
		return []any{}
	}
	return items
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func shortCommit(commit string) string {
	if len(commit) <= 12 {
		return commit
	}
	return commit[:12]
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func randomSuffix() string {
	var data [2]byte
	if _, err := rand.Read(data[:]); err != nil {
		return "0000"
	}
	return hex.EncodeToString(data[:])
}
