package buildcmd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/repocontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func RunBuild(ctx context.Context, f commands.Factory, opts *BuildOptions) error {
	overallStarted := time.Now()
	timings := []buildPhaseTiming{}
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
		runID = ledger.MakeRunID(f.Now(), fsutil.RandomSuffix())
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
	setupLock, err := buildworkspace.AcquireLock(ctx, commonDir, buildSetupLockTimeout)
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
	if err := os.MkdirAll(runDir, 0o700); err != nil {
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
		printSourceStateWarnings(f, repo)
	}

	baselinePath := filepath.Join(parent.Path, "baseline")
	contextMetadata.BaselineWorktreePath = baselinePath
	baselineSetupStarted := time.Now()
	if err := buildworkspace.CreateDetachedWorktree(ctx, repo, baselinePath); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	timings = append(timings, finishPhase("baseline_worktree", "", "", baselineSetupStarted))
	baselineCWD := buildworkspace.WorktreeInvocationPath(repo, baselinePath)
	if err := ensureDirectoryExists(baselineCWD); err != nil {
		buildworkspace.CleanupWorktree(ctx, repo, baselinePath, false)
		return &apperror.ValidationError{Message: err.Error(), Err: err}
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
	baselineVerifyStarted := time.Now()
	baseline := buildverify.Run(ctx, buildverify.Options{
		CWD:                   baselineCWD,
		Baseline:              true,
		Verifiers:             wo.Build.Verify,
		Env:                   runnerenv.SafeEnv(os.Environ()),
		HeartbeatSeconds:      wo.Budgets.HeartbeatSeconds,
		OutputCapGraceSeconds: wo.Budgets.OutputCapGraceSeconds,
		MaxOutputOverrunBytes: wo.Budgets.MaxOutputOverrunBytes,
		ArtifactDir:           filepath.Join(runDir, "baseline", "verify"),
		OnTick:                makeVerifierTickPrinter(f, effectiveQuiet),
	})
	timings = append(timings, finishPhase("baseline_verify", "", "", baselineVerifyStarted))
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "baseline", "verify", "result.json"), baseline); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	baselineCleanupStarted := time.Now()
	baselineCleanup, err := cleanupWorktree(ctx, repo, baselinePath, opts.KeepWorktrees)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	timings = append(timings, finishPhase("baseline_cleanup", "", "", baselineCleanupStarted))
	contextMetadata.BaselineCleanupStatus = baselineCleanup.Status
	if err := buildworkspace.WriteContext(runDir, contextMetadata); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		printVerifierSummary(f, "baseline", baseline)
	}

	if !baseline.GatesPassed {
		workerResults := emptyWorkerResults(wo)
		decisionKind, caveats := baselineFailureDecision(baseline)
		decision := buildDecision(wo, workerResults, nil, baseline, nil, decisionKind, "none", "", caveats)
		exitCode := 1
		timings = append(timings, finishPhase("build_total", "", "", overallStarted))
		if err := finalizeBuildRun(ctx, f, opts, wo, repo, runDir, runID, startedAt, workerResults, decision, baseline, nil, nil, timings, exitCode, humanOutput); err != nil {
			return err
		}
		return buildExitError(exitCode, baselineFailureMessage(decisionKind))
	}

	worktreePaths := map[string]string{}
	providerSetupStarted := time.Now()
	if err := withRepoLock(ctx, repo, buildSetupLockTimeout, func() error {
		for _, participant := range wo.Providers {
			path := filepath.Join(parent.Path, participant.ID)
			if err := buildworkspace.CreateDetachedWorktree(ctx, repo, path); err != nil {
				return err
			}
			worktreePaths[participant.ID] = path
			if err := ensureDirectoryExists(buildworkspace.WorktreeInvocationPath(repo, path)); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		for _, path := range worktreePaths {
			_, _ = cleanupWorktree(ctx, repo, path, false)
		}
		return &apperror.RuntimeError{Err: err}
	}
	timings = append(timings, finishPhase("provider_worktrees", "", "", providerSetupStarted))

	capabilities := providerCapabilities(ctx, f, wo)
	if humanOutput {
		for _, participant := range wo.Providers {
			f.Streams().Printf("[%s] launching in worktree...\n", participant.ID)
		}
	}
	repoLayoutBlock, err := buildRepoLayoutBlock(wo, opts.NoRepoLayout)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	providerRuns, err := runBuildProviders(ctx, f, wo, repo, runDir, baseline, worktreePaths, capabilities, opts.KeepWorktrees, effectiveQuiet, repoLayoutBlock, opts.NoRepoLayout)
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
	promptTrims := []prompt.TrimRecord{}
	for _, run := range providerRuns {
		workerResults[run.ID] = run.WorkerResult
		verifyResults[run.ID] = run.Verify
		promptTrims = append(promptTrims, run.PromptTrims...)
		timings = append(timings, run.PhaseTiming)
		if humanOutput {
			printBuildProviderResult(f, run)
		}
	}
	metricComparisons := buildverify.CompareMetrics(wo.Build.Verify, providerIDs, verifyResults)
	judgeResults := map[string]map[string]any{}
	pass1Order := map[string]string{}
	pass2Order := map[string]string{}
	if buildJudgeNeeded(providerRuns, metricComparisons) {
		if humanOutput {
			f.Streams().Printf("[judge] verifier evidence inconclusive; running swapped build judge...\n")
		}
		judgePhase, err := runBuildJudgePhase(ctx, f, wo, baseline, providerRuns, metricComparisons, runDir, effectiveQuiet, humanOutput)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			return &apperror.RuntimeError{Err: err}
		}
		judgeResults = judgePhase.JudgeResults
		pass1Order = judgePhase.Pass1Order
		pass2Order = judgePhase.Pass2Order
		timings = append(timings, judgePhase.Timings...)
		promptTrims = append(promptTrims, judgePhase.PromptTrims...)
	}
	decision, exitCode := resolveBuildDecision(wo, workerResults, providerRuns, baseline, metricComparisons, judgeResults, pass1Order, pass2Order)
	commands.AttachPromptTrim(decision, promptTrims)
	timings = append(timings, finishPhase("build_total", "", "", overallStarted))
	if err := finalizeBuildRun(ctx, f, opts, wo, repo, runDir, runID, startedAt, workerResults, decision, baseline, providerRuns, metricComparisons, timings, exitCode, humanOutput); err != nil {
		return err
	}
	return buildExitError(exitCode, "build failed")
}

func buildRepoLayoutBlock(wo *workorder.WorkOrder, disabled bool) (string, error) {
	if !repocontext.AnyParticipantReceivesLayout(wo, disabled) {
		return "", nil
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	return repocontext.BuildLayoutBlock(cwd)
}

func finalizeBuildRun(ctx context.Context, f commands.Factory, opts *BuildOptions, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, runID string, startedAt string, workerResults map[string]map[string]any, decision map[string]any, baseline buildverify.Result, providerRuns []providerRun, metrics []buildverify.MetricComparison, timings []buildPhaseTiming, exitCode int, humanOutput bool) error {
	diagnostics := collectBuildDiagnostics(ctx, wo, repo, runDir, baseline, providerRuns, timings)
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "diagnostics.json"), diagnostics); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), decision); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	reportText := renderBuildReport(wo, runID, opts.Out, runDir, decision, baseline, providerRuns, metrics, diagnostics)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), reportText); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := artifact.WriteMeta(ctx, runDir, wo, runID, startedAt, artifact.MetaOptions{
		WorkerResults:  workerResults,
		Decision:       decision,
		ExitCode:       exitCode,
		LookupProvider: f.LookupProvider,
	}); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		f.Streams().Printf("manifest: %s\n", filepath.Join(runDir, "manifest.json"))
		f.Streams().Printf("report: %s\n", filepath.Join(runDir, "report.md"))
		f.Streams().Printf("result: %s\n", buildResultLine(decision))
		if winner, _ := decision["canonical_winner"].(string); winner != "" {
			f.Streams().Printf("winner patch artifact: %s\n", filepath.Join(runDir, "providers", winner, "build", "diff.patch"))
		}
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(runID, opts.Out, ""))
	}
	if opts.JSON {
		if err := summary.Print(f.Streams().Out, buildSummary(repo, runDir, runID, opts.Out, decision, baseline, providerRuns, metrics, diagnostics, exitCode)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	return nil
}
