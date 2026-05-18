package buildcmd

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	decisionpkg "github.com/mstefanko/claude-plugins/bakeoff/internal/decision"
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

const (
	buildJudgeDiffstatPreviewBytes = 6000
	buildJudgePatchExcerptBytes    = 12000
)

type providerRun struct {
	ID                  string
	WorktreePath        string
	ProviderCWD         string
	WorkerResult        map[string]any
	Capture             *buildworkspace.CaptureResult
	Verify              buildverify.Result
	Cleanup             buildworkspace.CleanupResult
	ScopeMetadata       map[string]any
	ScopeDiagnostics    buildScopeDiagnostics
	IneligibleReasons   []string
	Workspace           buildworkspace.WorkspaceMetadata
	ProviderArtifactDir string
	PhaseTiming         buildPhaseTiming
}

type buildPhaseTiming struct {
	Name        string  `json:"name"`
	ProviderID  string  `json:"provider_id,omitempty"`
	Label       string  `json:"label,omitempty"`
	StartedAt   string  `json:"started_at"`
	FinishedAt  string  `json:"finished_at"`
	WallSeconds float64 `json:"wall_seconds"`
}

type buildScopeDiagnostics struct {
	IntendedPrefix        string                       `json:"intended_prefix"`
	OutOfInvocationFiles  []buildworkspace.ChangedFile `json:"out_of_invocation_files,omitempty"`
	AgentInstructionFiles []buildworkspace.ChangedFile `json:"agent_instruction_files,omitempty"`
	Warnings              []string                     `json:"warnings,omitempty"`
}

type buildDiagnostics struct {
	SchemaVersion        int                              `json:"schema_version"`
	PhaseTimings         []buildPhaseTiming               `json:"phase_timings,omitempty"`
	PromptSizes          []promptSizeDiagnostic           `json:"prompt_sizes,omitempty"`
	BaselineMetricDeltas []baselineMetricDelta            `json:"baseline_metric_deltas,omitempty"`
	OutputTruncation     []outputTruncationRecord         `json:"output_truncation,omitempty"`
	PatchApplyChecks     []patchApplyCheck                `json:"patch_apply_checks,omitempty"`
	ScopeDiagnostics     map[string]buildScopeDiagnostics `json:"scope_diagnostics,omitempty"`
	SourceWarnings       []string                         `json:"source_warnings,omitempty"`
}

type promptSizeDiagnostic struct {
	Path       string `json:"path"`
	Bytes      int64  `json:"bytes"`
	Kind       string `json:"kind"`
	ProviderID string `json:"provider_id,omitempty"`
	Label      string `json:"label,omitempty"`
}

type baselineMetricDelta struct {
	ID            string  `json:"id"`
	Name          string  `json:"name"`
	ProviderID    string  `json:"provider_id"`
	Direction     string  `json:"direction"`
	BaselineValue float64 `json:"baseline_value"`
	ProviderValue float64 `json:"provider_value"`
	DeltaPercent  float64 `json:"delta_percent"`
	Improved      bool    `json:"improved"`
}

type outputTruncationRecord struct {
	Scope         string `json:"scope"`
	ProviderID    string `json:"provider_id,omitempty"`
	VerifierID    string `json:"verifier_id,omitempty"`
	Stream        string `json:"stream"`
	ObservedBytes int    `json:"observed_bytes"`
	RetainedBytes int    `json:"retained_bytes"`
}

type patchApplyCheck struct {
	ProviderID  string `json:"provider_id"`
	Status      string `json:"status"`
	PatchPath   string `json:"patch_path"`
	SourceDirty bool   `json:"source_dirty"`
	Output      string `json:"output,omitempty"`
	Error       string `json:"error,omitempty"`
}

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
		Env:                   buildEnv(os.Environ()),
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
		decision := buildDecision(wo, workerResults, nil, baseline, nil, "baseline_failed", "none", "", []string{"baseline gate verifier failed; providers were not launched"})
		exitCode := 1
		timings = append(timings, finishPhase("build_total", "", "", overallStarted))
		if err := finalizeBuildRun(ctx, f, opts, wo, repo, runDir, runID, startedAt, workerResults, decision, baseline, nil, nil, timings, exitCode, humanOutput); err != nil {
			return err
		}
		return buildExitError(exitCode, "baseline verification failed")
	}

	worktreePaths := map[string]string{}
	providerSetupStarted := time.Now()
	if err := withRepoLock(ctx, repo, func() error {
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
		var err error
		var judgeTimings []buildPhaseTiming
		judgeResults, pass1Order, pass2Order, judgeTimings, err = runBuildJudgePhase(ctx, f, wo, baseline, providerRuns, metricComparisons, runDir, effectiveQuiet, humanOutput)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			return &apperror.RuntimeError{Err: err}
		}
		timings = append(timings, judgeTimings...)
	}
	decision, exitCode := resolveBuildDecision(wo, workerResults, providerRuns, baseline, metricComparisons, judgeResults, pass1Order, pass2Order)
	timings = append(timings, finishPhase("build_total", "", "", overallStarted))
	if err := finalizeBuildRun(ctx, f, opts, wo, repo, runDir, runID, startedAt, workerResults, decision, baseline, providerRuns, metricComparisons, timings, exitCode, humanOutput); err != nil {
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
	phaseStarted := time.Now()
	providerDir := filepath.Join(runDir, "providers", participant.ID)
	buildDir := filepath.Join(providerDir, "build")
	providerCWD := buildworkspace.WorktreeInvocationPath(repo, worktreePath)
	run = providerRun{
		ID:                  participant.ID,
		WorktreePath:        worktreePath,
		ProviderCWD:         providerCWD,
		ProviderArtifactDir: providerDir,
	}
	defer func() {
		run.PhaseTiming = finishPhase("provider_total", participant.ID, "", phaseStarted)
	}()
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
	argv, scopeMetadata, err := buildParticipantArgv(participant, wo.ScopePolicy, providerCWD, caps, finalMessagePath)
	run.ScopeMetadata = scopeMetadata
	if err != nil {
		result := scope.ScopeErrorResult(err, participant, wo.ScopePolicy, providerCWD)
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
			CWD:              providerCWD,
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
			run.ScopeDiagnostics = diagnoseBuildScope(repo, capture.ChangedFiles)
			if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "capture.json"), capture); err != nil {
				return run, err
			}
			if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "scope.json"), run.ScopeDiagnostics); err != nil {
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
			CWD:                   providerCWD,
			ProviderID:            participant.ID,
			Verifiers:             wo.Build.Verify,
			Env:                   buildEnv(os.Environ()),
			HeartbeatSeconds:      wo.Budgets.HeartbeatSeconds,
			OutputCapGraceSeconds: wo.Budgets.OutputCapGraceSeconds,
			MaxOutputOverrunBytes: wo.Budgets.MaxOutputOverrunBytes,
			ArtifactDir:           filepath.Join(buildDir, "verify"),
			OnTick:                makeVerifierTickPrinter(f, quiet),
		})
	} else {
		run.Verify = buildverify.Result{Scope: "provider", ProviderID: participant.ID, GatesPassed: false}
	}
	if err := os.MkdirAll(filepath.Join(buildDir, "verify"), 0o755); err != nil {
		return run, err
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "verify", "result.json"), run.Verify); err != nil {
		return run, err
	}
	cleanup, err := cleanupWorktree(ctx, repo, worktreePath, keepWorktrees)
	cleanupRecorded = true
	if err != nil {
		run.IneligibleReasons = append(run.IneligibleReasons, "worktree cleanup failed: "+err.Error())
		cleanup = buildworkspace.CleanupResult{Path: worktreePath, Status: "failed", Error: err.Error()}
	}
	run.Cleanup = cleanup
	run.Workspace = workspaceMetadata(repo, participant, worktreePath, providerCWD, cleanup, run.Capture)
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

func runBuildJudgePhase(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, runDir string, quiet bool, humanOutput bool) (map[string]map[string]any, map[string]string, map[string]string, []buildPhaseTiming, error) {
	providerIDs := []string{wo.Providers[0].ID, wo.Providers[1].ID}
	byProvider := map[string]providerRun{}
	for _, run := range runs {
		byProvider[run.ID] = run
	}
	pass1Order := map[string]string{"A": providerIDs[0], "B": providerIDs[1]}
	pass2Order := map[string]string{"A": providerIDs[1], "B": providerIDs[0]}
	pass1, pass1Timing, err := runSingleBuildJudge(ctx, f, wo, baseline, byProvider, metrics, pass1Order, runDir, "pass1", quiet, humanOutput)
	if err != nil {
		return nil, nil, nil, nil, err
	}
	pass2, pass2Timing, err := runSingleBuildJudge(ctx, f, wo, baseline, byProvider, metrics, pass2Order, runDir, "pass2", quiet, humanOutput)
	if err != nil {
		return nil, nil, nil, nil, err
	}
	judgeResults := map[string]map[string]any{"pass1": finalJSONMap(pass1), "pass2": finalJSONMap(pass2)}
	if !artifact.ProviderSucceeded(pass1) || !artifact.ProviderSucceeded(pass2) {
		judgeResults["_failure"] = map[string]any{"pass1_status": pass1["status"], "pass2_status": pass2["status"]}
	}
	return judgeResults, pass1Order, pass2Order, []buildPhaseTiming{pass1Timing, pass2Timing}, nil
}

func runSingleBuildJudge(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, baseline buildverify.Result, runs map[string]providerRun, metrics []buildverify.MetricComparison, orderMap map[string]string, runDir string, label string, quiet bool, humanOutput bool) (map[string]any, buildPhaseTiming, error) {
	phaseStarted := time.Now()
	sharedEvidence := buildJudgeSharedEvidence(runDir, baseline, metrics)
	workerA := buildJudgePayload(runDir, runs[orderMap["A"]])
	workerB := buildJudgePayload(runDir, runs[orderMap["B"]])
	judgePrompt, err := prompt.BuildJudgePromptWithEvidence(wo, sharedEvidence, workerA, workerB, "build")
	if err != nil {
		return nil, buildPhaseTiming{}, err
	}
	judgeDir := filepath.Join(runDir, "judge")
	if err := os.MkdirAll(judgeDir, 0o755); err != nil {
		return nil, buildPhaseTiming{}, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, "prompt-"+label+".txt"), judgePrompt); err != nil {
		return nil, buildPhaseTiming{}, err
	}
	lastMessage := ""
	if wo.Judge.Backend == "codex" {
		lastMessage = filepath.Join(judgeDir, "last-message-"+label+".txt")
	}
	cwd, _ := os.Getwd()
	argv, err := provider.BuildParticipantArgv(wo.Judge, cwd, nil, lastMessage, commands.CodexOutputLastMessageSupported(ctx, f, wo.Judge))
	if err != nil {
		return nil, buildPhaseTiming{}, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] running...\n", label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           judgePrompt,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              cwd,
		Env:              buildEnv(os.Environ()),
		Validator:        workorder.ValidateBuildJudgeResult,
		OnTick:           commands.MakeTickPrinter(f, "judge:"+label, quiet),
		FinalMessagePath: lastMessage,
	}))
	if err := artifact.WriteJudgeArtifacts(judgeDir, label, result); err != nil {
		return nil, buildPhaseTiming{}, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] %s %vs\n", label, result["status"], result["wall_seconds"])
	}
	return result, finishPhase("judge", "", label, phaseStarted), nil
}

func buildJudgeSharedEvidence(runDir string, baseline buildverify.Result, metrics []buildverify.MetricComparison) map[string]any {
	return map[string]any{
		"baseline_verify":  compactVerifyResult(runDir, baseline),
		"metric_decisions": metricDecisionMaps(metrics),
	}
}

func buildJudgePayload(runDir string, run providerRun) map[string]any {
	payload := map[string]any{
		"provider_id":       run.ID,
		"worker_final_json": finalJSONMap(run.WorkerResult),
		"runner_status":     compactRunnerStatus(run.WorkerResult),
		"workspace":         compactWorkspace(runDir, run),
		"scope_diagnostics": run.ScopeDiagnostics,
		"verify":            compactVerifyResult(runDir, run.Verify),
	}
	if len(run.IneligibleReasons) > 0 {
		payload["ineligible_reasons"] = run.IneligibleReasons
	}
	if run.Capture != nil {
		patch := map[string]any{
			"patch_bytes":             run.Capture.PatchBytes,
			"patch_over_cap":          run.Capture.PatchOverCap,
			"gitlink_change_rejected": run.Capture.GitlinkChangeRejected,
			"changed_files":           run.Capture.ChangedFiles,
			"test_files":              run.Capture.TestFiles,
			"benchmark_files":         run.Capture.BenchmarkFiles,
		}
		if run.Capture.DiffstatPath != "" {
			if preview, truncated, err := readTextPreview(run.Capture.DiffstatPath, buildJudgeDiffstatPreviewBytes); err == nil {
				patch["diffstat"] = preview
				patch["diffstat_truncated"] = truncated
			} else {
				patch["diffstat_error"] = err.Error()
			}
			if relative, err := relativePath(runDir, run.Capture.DiffstatPath); err == nil {
				patch["diffstat_path"] = relative
			} else {
				patch["diffstat_path"] = run.Capture.DiffstatPath
				patch["diffstat_path_error"] = err.Error()
			}
		}
		if run.Capture.PatchPath != "" {
			if relative, err := relativePath(runDir, run.Capture.PatchPath); err == nil {
				patch["patch_path"] = relative
			} else {
				patch["patch_path"] = run.Capture.PatchPath
				patch["patch_path_error"] = err.Error()
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

func compactRunnerStatus(result map[string]any) map[string]any {
	status := artifact.StatusWithoutPayload(result)
	delete(status, "io")
	delete(status, "output_bytes")
	if scopeMetadata, ok := status["scope_enforcement"].(map[string]any); ok {
		compactScope := map[string]any{}
		for _, key := range []string{"requested_scope", "effective_scope", "enforcement_level", "policy", "mechanisms", "fallback_reason", "temporary_cwd", "cwd"} {
			if value, exists := scopeMetadata[key]; exists {
				compactScope[key] = value
			}
		}
		status["scope_enforcement"] = compactScope
	}
	return status
}

func compactWorkspace(runDir string, run providerRun) map[string]any {
	return map[string]any{
		"base_ref":                   run.Workspace.BaseRef,
		"base_commit":                shortCommit(run.Workspace.BaseCommit),
		"cleanup_status":             run.Workspace.CleanupStatus,
		"provider_cwd":               mustRelative(runDir, run.Workspace.ProviderCWD),
		"provider_head":              shortCommit(run.Workspace.ProviderHead),
		"provider_head_is_base":      run.Workspace.ProviderHeadIsBase,
		"provider_committed_changes": run.Workspace.ProviderCommittedChanges,
		"worktree_retained":          run.Workspace.WorktreeRetained,
		"worktree_removed":           run.Workspace.WorktreeRemoved,
	}
}

func compactVerifyResult(runDir string, result buildverify.Result) map[string]any {
	out := map[string]any{
		"scope":        result.Scope,
		"gates_passed": result.GatesPassed,
		"results":      compactVerifierResults(runDir, result.Results),
	}
	if result.ProviderID != "" {
		out["provider_id"] = result.ProviderID
	}
	return out
}

func compactVerifierResults(runDir string, results []buildverify.VerifierResult) []map[string]any {
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
		if result.StdoutPath != "" {
			entry["stdout_path"] = mustRelative(runDir, result.StdoutPath)
		}
		if result.StderrPath != "" {
			entry["stderr_path"] = mustRelative(runDir, result.StderrPath)
		}
		if result.StatusPath != "" {
			entry["status_path"] = mustRelative(runDir, result.StatusPath)
		}
		if result.MetricPath != "" {
			entry["metric_path"] = mustRelative(runDir, result.MetricPath)
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
	}
	decision, exitCode := decisionpkg.ResolveBuild(input)
	if judgeFailure != nil {
		decision["caveats"] = append(listStrings(decision["caveats"]), fmt.Sprintf("build judge failed: pass1=%v, pass2=%v", judgeFailure["pass1_status"], judgeFailure["pass2_status"]))
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
		if run.Capture != nil {
			status["patch_bytes"] = run.Capture.PatchBytes
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
			entry["patch_over_cap"] = run.Capture.PatchOverCap
			entry["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			entry["scope_diagnostics"] = run.ScopeDiagnostics
			entry["patch_path"] = "providers/" + run.ID + "/build/diff.patch"
			entry["changed_files"] = run.Capture.ChangedFiles
			entry["test_files"] = run.Capture.TestFiles
			entry["benchmark_files"] = run.Capture.BenchmarkFiles
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
			"id":                metric.ID,
			"name":              metric.Name,
			"direction":         metric.Direction,
			"delta_percent":     metric.DeltaPercent,
			"threshold_percent": metric.Threshold,
			"conclusive":        metric.Conclusive,
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
			entry["patch_over_cap"] = run.Capture.PatchOverCap
			entry["gitlink_change_rejected"] = run.Capture.GitlinkChangeRejected
			entry["scope_diagnostics"] = run.ScopeDiagnostics
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

func collectBuildDiagnostics(ctx context.Context, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, baseline buildverify.Result, runs []providerRun, timings []buildPhaseTiming) buildDiagnostics {
	diagnostics := buildDiagnostics{
		SchemaVersion:    1,
		PhaseTimings:     compactPhaseTimings(timings),
		PromptSizes:      collectPromptSizes(runDir, runs),
		OutputTruncation: collectOutputTruncation(baseline, runs),
		PatchApplyChecks: collectPatchApplyChecks(ctx, repo, runDir, runs),
		ScopeDiagnostics: map[string]buildScopeDiagnostics{},
		SourceWarnings:   sourceWarnings(repo),
	}
	for _, run := range runs {
		if len(run.ScopeDiagnostics.OutOfInvocationFiles) > 0 || len(run.ScopeDiagnostics.AgentInstructionFiles) > 0 || len(run.ScopeDiagnostics.Warnings) > 0 {
			diagnostics.ScopeDiagnostics[run.ID] = run.ScopeDiagnostics
		}
	}
	if len(diagnostics.ScopeDiagnostics) == 0 {
		diagnostics.ScopeDiagnostics = nil
	}
	diagnostics.BaselineMetricDeltas = collectBaselineMetricDeltas(wo, baseline, runs)
	return diagnostics
}

func collectPromptSizes(runDir string, runs []providerRun) []promptSizeDiagnostic {
	var out []promptSizeDiagnostic
	for _, run := range runs {
		path := filepath.Join(runDir, "providers", run.ID, "prompt.txt")
		if size, ok := fileSize(path); ok {
			out = append(out, promptSizeDiagnostic{Path: mustRelative(runDir, path), Bytes: size, Kind: "worker", ProviderID: run.ID})
		}
	}
	for _, label := range []string{"pass1", "pass2"} {
		path := filepath.Join(runDir, "judge", "prompt-"+label+".txt")
		if size, ok := fileSize(path); ok {
			out = append(out, promptSizeDiagnostic{Path: mustRelative(runDir, path), Bytes: size, Kind: "judge", Label: label})
		}
	}
	return out
}

func collectBaselineMetricDeltas(wo *workorder.WorkOrder, baseline buildverify.Result, runs []providerRun) []baselineMetricDelta {
	baselineMetrics := map[string]buildverify.VerifierResult{}
	for _, result := range baseline.Results {
		if result.Kind == "metric" && result.Metric != nil && result.Metric.Value != nil {
			baselineMetrics[result.ID] = result
		}
	}
	directions := map[string]string{}
	if wo != nil && wo.Build != nil {
		for _, verifier := range wo.Build.Verify {
			if verifier.Kind == "metric" && verifier.Metric != nil {
				directions[verifier.ID] = verifier.Metric.Direction
			}
		}
	}
	var out []baselineMetricDelta
	for _, run := range runs {
		for _, result := range run.Verify.Results {
			if result.Kind != "metric" || result.Metric == nil || result.Metric.Value == nil {
				continue
			}
			base, ok := baselineMetrics[result.ID]
			if !ok || base.Metric == nil || base.Metric.Value == nil {
				continue
			}
			baselineValue := *base.Metric.Value
			providerValue := *result.Metric.Value
			direction := directions[result.ID]
			if direction == "" {
				direction = "lower"
			}
			improvement := providerValue - baselineValue
			if direction == "lower" {
				improvement = baselineValue - providerValue
			}
			denominator := math.Abs(baselineValue)
			if denominator == 0 {
				denominator = math.Max(math.Abs(providerValue), 1)
			}
			out = append(out, baselineMetricDelta{
				ID:            result.ID,
				Name:          result.Metric.Name,
				ProviderID:    run.ID,
				Direction:     direction,
				BaselineValue: baselineValue,
				ProviderValue: providerValue,
				DeltaPercent:  round3(math.Abs(improvement) / denominator * 100),
				Improved:      improvement > 0,
			})
		}
	}
	return out
}

func collectOutputTruncation(baseline buildverify.Result, runs []providerRun) []outputTruncationRecord {
	var out []outputTruncationRecord
	for _, item := range truncationRecordsFromVerifier("baseline", "", baseline.Results) {
		out = append(out, item)
	}
	for _, run := range runs {
		out = append(out, truncationRecordsFromRunner("provider", run.ID, "", run.WorkerResult)...)
		out = append(out, truncationRecordsFromVerifier("verify", run.ID, run.Verify.Results)...)
	}
	return out
}

func truncationRecordsFromVerifier(scope string, providerID string, results []buildverify.VerifierResult) []outputTruncationRecord {
	var out []outputTruncationRecord
	for _, result := range results {
		if result.StdoutTruncated {
			out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: result.ID, Stream: "stdout", ObservedBytes: result.StdoutObservedBytes, RetainedBytes: result.StdoutBytes})
		}
		if result.StderrTruncated {
			out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: result.ID, Stream: "stderr", ObservedBytes: result.StderrObservedBytes, RetainedBytes: result.StderrBytes})
		}
	}
	return out
}

func truncationRecordsFromRunner(scope string, providerID string, verifierID string, result map[string]any) []outputTruncationRecord {
	var out []outputTruncationRecord
	if boolValue(result["stdout_truncated"]) {
		out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: verifierID, Stream: "stdout", ObservedBytes: intValue(result["stdout_observed_bytes"]), RetainedBytes: intValue(result["stdout_bytes"])})
	}
	if boolValue(result["stderr_truncated"]) {
		out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: verifierID, Stream: "stderr", ObservedBytes: intValue(result["stderr_observed_bytes"]), RetainedBytes: intValue(result["stderr_bytes"])})
	}
	return out
}

func collectPatchApplyChecks(ctx context.Context, repo buildworkspace.Repository, runDir string, runs []providerRun) []patchApplyCheck {
	var out []patchApplyCheck
	for _, run := range runs {
		if run.Capture == nil || run.Capture.PatchPath == "" {
			continue
		}
		check := patchApplyCheck{ProviderID: run.ID, PatchPath: mustRelative(runDir, run.Capture.PatchPath), SourceDirty: !repo.SourceClean}
		checkCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
		var stdout, stderr bytes.Buffer
		cmd := exec.CommandContext(checkCtx, "git", "-C", repo.Root, "apply", "--check", "--3way", "--binary", run.Capture.PatchPath)
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
		err := cmd.Run()
		cancel()
		output := strings.TrimSpace(stdout.String() + stderr.String())
		if len(output) > 4000 {
			output = output[:4000] + "\n[truncated]\n"
		}
		check.Output = output
		if err != nil {
			check.Status = "failed"
			check.Error = err.Error()
		} else {
			check.Status = "passed"
		}
		out = append(out, check)
	}
	return out
}

func diagnoseBuildScope(repo buildworkspace.Repository, changed []buildworkspace.ChangedFile) buildScopeDiagnostics {
	prefix := strings.Trim(filepath.ToSlash(repo.InvocationRelPath), "/")
	if prefix == "" {
		prefix = "."
	}
	diagnostics := buildScopeDiagnostics{IntendedPrefix: prefix}
	for _, file := range changed {
		path := normalizeChangedPath(file.Path)
		if prefix != "." && path != prefix && !strings.HasPrefix(path, prefix+"/") {
			diagnostics.OutOfInvocationFiles = append(diagnostics.OutOfInvocationFiles, file)
		}
		if isAgentInstructionPath(path) {
			diagnostics.AgentInstructionFiles = append(diagnostics.AgentInstructionFiles, file)
		}
	}
	if len(diagnostics.OutOfInvocationFiles) > 0 {
		diagnostics.Warnings = append(diagnostics.Warnings, "patch changes files outside the invocation directory")
	}
	if len(diagnostics.AgentInstructionFiles) > 0 {
		diagnostics.Warnings = append(diagnostics.Warnings, "patch changes local agent instruction/config files")
	}
	return diagnostics
}

func normalizeChangedPath(path string) string {
	if strings.Contains(path, " -> ") {
		parts := strings.Split(path, " -> ")
		path = parts[len(parts)-1]
	}
	return strings.Trim(filepath.ToSlash(path), "/")
}

func isAgentInstructionPath(path string) bool {
	path = strings.Trim(filepath.ToSlash(path), "/")
	base := filepath.Base(path)
	if base == "CLAUDE.md" || base == "AGENTS.md" {
		return true
	}
	return strings.HasPrefix(path, ".claude/") || strings.HasPrefix(path, ".codex/") || strings.Contains(path, "/.claude/") || strings.Contains(path, "/.codex/")
}

func compactPhaseTimings(timings []buildPhaseTiming) []buildPhaseTiming {
	out := make([]buildPhaseTiming, 0, len(timings))
	for _, timing := range timings {
		if timing.Name == "" {
			continue
		}
		out = append(out, timing)
	}
	return out
}

func finalizeBuildRun(ctx context.Context, f commands.Factory, opts *BuildOptions, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, runID string, startedAt string, workerResults map[string]map[string]any, decision map[string]any, baseline buildverify.Result, providerRuns []providerRun, metrics []buildverify.MetricComparison, timings []buildPhaseTiming, exitCode int, humanOutput bool) error {
	diagnostics := collectBuildDiagnostics(ctx, wo, repo, runDir, baseline, providerRuns, timings)
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "diagnostics.json"), diagnostics); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), decision); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	reportText := renderBuildReport(wo, runID, runDir, decision, baseline, providerRuns, metrics, diagnostics)
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
		if err := summary.Print(f.Streams().Out, buildSummary(repo, runDir, runID, opts.Out, decision, baseline, providerRuns, metrics, diagnostics, exitCode)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	return nil
}

func renderBuildReport(wo *workorder.WorkOrder, runID string, runDir string, decision map[string]any, baseline buildverify.Result, runs []providerRun, metrics []buildverify.MetricComparison, diagnostics buildDiagnostics) string {
	lines := []string{
		"# Bakeoff Report: " + wo.ID,
		"",
		"Mode: `build`",
		"Decision: `" + stringValue(decision["decision_kind"]) + "`",
		"Selection basis: `" + stringValue(decision["selection_basis"]) + "`",
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
		lines = append(lines, fmt.Sprintf("- Worker status: `%s`", stringValue(run.WorkerResult["status"])))
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
		if len(run.IneligibleReasons) > 0 {
			lines = append(lines, "- Ineligible reasons:")
			for _, reason := range run.IneligibleReasons {
				lines = append(lines, "  - "+reason)
			}
		}
		if final := finalJSONMap(run.WorkerResult); len(final) > 0 {
			if risks := listValue(final["risks"]); len(risks) > 0 {
				lines = append(lines, "- Provider risks:")
				for _, risk := range risks {
					lines = append(lines, "  - "+fmt.Sprint(risk))
				}
			}
			if checks := listValue(final["manual_checks"]); len(checks) > 0 {
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
			lines = append(lines, fmt.Sprintf("- `%s`: winner `%s`, delta %.3g%%, threshold %.3g%% (%s)", metric.ID, winner, metric.DeltaPercent, metric.Threshold, reason))
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
		lines = append(lines, "")
	}
	if len(diagnostics.PatchApplyChecks) > 0 {
		lines = append(lines, "## Patch Apply Checks", "")
		for _, check := range diagnostics.PatchApplyChecks {
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
					order, _ := raw.(map[string]string)
					if order == nil {
						if obj, ok := raw.(map[string]any); ok {
							order = map[string]string{"A": stringValue(obj["A"]), "B": stringValue(obj["B"])}
						}
					}
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
				winner := stringValue(summary["canonical_winner"])
				if winner == "" {
					winner = stringValue(summary["positional_winner"])
				}
				if winner == "" {
					winner = "none"
				}
				lines = append(lines, fmt.Sprintf("- %s winner: `%s`", pass, winner))
			}
		}
		for _, rationale := range listValue(decision["judge_rationale"]) {
			if text := strings.TrimSpace(fmt.Sprint(rationale)); text != "" {
				lines = append(lines, "- "+text)
			}
		}
		lines = append(lines, "")
	}
	if winner, _ := decision["canonical_winner"].(string); winner != "" {
		patch := filepath.Join(runDir, "providers", winner, "build", "diff.patch")
		lines = append(lines, "## Winner Handoff", "", "Winner: `"+winner+"`")
		lines = append(lines, "Selection basis: `"+stringValue(decision["selection_basis"])+"`")
		if rationale := listValue(decision["judge_rationale"]); len(rationale) > 0 && stringValue(decision["selection_basis"]) == "judge" {
			lines = append(lines, "Why: "+fmt.Sprint(rationale[0]))
		}
		if run := providerRunByID(runs, winner); run != nil {
			if run.Capture != nil {
				lines = append(lines, "Patch: `"+filepath.Join("providers", winner, "build", "diff.patch")+"`")
				lines = append(lines, "Diffstat: `"+filepath.Join("providers", winner, "build", "diffstat.txt")+"`")
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
			if final := finalJSONMap(run.WorkerResult); len(final) > 0 {
				if risks := listValue(final["risks"]); len(risks) > 0 {
					lines = append(lines, "Risks:")
					for _, risk := range risks {
						lines = append(lines, "- "+fmt.Sprint(risk))
					}
				}
				if checks := listValue(final["manual_checks"]); len(checks) > 0 {
					lines = append(lines, "Manual checks:")
					for _, check := range checks {
						lines = append(lines, "- "+fmt.Sprint(check))
					}
				}
			}
		}
		lines = append(lines, "", "```text", "git apply --3way --binary "+patch, "```", "")
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
			entry["patch_path"] = filepath.Join(runDir, "providers", run.ID, "build", "diff.patch")
		}
		providers[run.ID] = entry
	}
	return map[string]any{
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
		if fileExists(path) {
			out[key] = path
		}
	}
	return out
}

func workspaceMetadata(repo buildworkspace.Repository, participant workorder.Participant, worktreePath string, providerCWD string, cleanup buildworkspace.CleanupResult, capture *buildworkspace.CaptureResult) buildworkspace.WorkspaceMetadata {
	workspace := buildworkspace.WorkspaceMetadata{
		GitRoot:          repo.Root,
		BaseRef:          repo.BaseRef,
		BaseCommit:       repo.BaseCommit,
		WorktreePath:     worktreePath,
		ProviderCWD:      providerCWD,
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
	if items, ok := value.([]any); ok {
		return items
	}
	if items, ok := value.([]string); ok {
		out := make([]any, len(items))
		for i, item := range items {
			out[i] = item
		}
		return out
	}
	return []any{}
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

func listStrings(value any) []string {
	switch typed := value.(type) {
	case []string:
		return append([]string(nil), typed...)
	case []any:
		out := make([]string, 0, len(typed))
		for _, item := range typed {
			out = append(out, fmt.Sprint(item))
		}
		return out
	default:
		return []string{}
	}
}

func boolValue(value any) bool {
	if typed, ok := value.(bool); ok {
		return typed
	}
	return false
}

func intValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	default:
		return 0
	}
}

func finishPhase(name string, providerID string, label string, started time.Time) buildPhaseTiming {
	finished := time.Now()
	return buildPhaseTiming{
		Name:        name,
		ProviderID:  providerID,
		Label:       label,
		StartedAt:   started.UTC().Format(time.RFC3339Nano),
		FinishedAt:  finished.UTC().Format(time.RFC3339Nano),
		WallSeconds: round3(finished.Sub(started).Seconds()),
	}
}

func round3(value float64) float64 {
	return math.Round(value*1000) / 1000
}

func fileSize(path string) (int64, bool) {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return 0, false
	}
	return info.Size(), true
}

func mustRelative(base string, path string) string {
	if relative, err := relativePath(base, path); err == nil {
		return relative
	}
	return path
}

func ensureDirectoryExists(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return fmt.Errorf("invocation path %q is not present in the selected base_ref worktree; commit that directory or run build from a path present in base_ref", path)
		}
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("invocation path %q is not a directory in the selected base_ref worktree", path)
	}
	return nil
}

func sourceWarnings(repo buildworkspace.Repository) []string {
	var warnings []string
	if !repo.SourceClean {
		warnings = append(warnings, fmt.Sprintf("source checkout is dirty; providers use committed base %s and ignore %d uncommitted source change(s)", shortCommit(repo.BaseCommit), repo.SourceDirtyCount))
	}
	if repo.SourceHasGitmodules {
		warnings = append(warnings, "source checkout contains .gitmodules; build worktrees do not initialize submodules automatically")
	}
	if repo.SourceGitlinkCount > 0 {
		warnings = append(warnings, fmt.Sprintf("source checkout contains %d gitlink/submodule entries; provider patches that modify gitlinks are still rejected", repo.SourceGitlinkCount))
	}
	return warnings
}

func printSourceStateWarnings(f commands.Factory, repo buildworkspace.Repository) {
	for _, warning := range sourceWarnings(repo) {
		f.Streams().Printf("  warning:        %s\n", warning)
	}
	if repo.InvocationRelPath != "" && repo.InvocationRelPath != "." {
		f.Streams().Printf("  invocation cwd: %s\n", repo.InvocationRelPath)
	}
}

func readTextPreview(path string, limit int) (string, bool, error) {
	if path == "" || limit <= 0 {
		return "", false, fmt.Errorf("path and positive limit are required")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", false, err
	}
	truncated := false
	if len(data) <= limit {
		return strings.ToValidUTF8(string(data), "\uFFFD"), false, nil
	}
	data = data[:limit]
	truncated = true
	return strings.ToValidUTF8(string(data), "\uFFFD") + "\n[truncated]\n", truncated, nil
}

func relativePath(base string, path string) (string, error) {
	relative, err := filepath.Rel(base, path)
	if err != nil || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		if err == nil {
			err = fmt.Errorf("%s is outside %s", path, base)
		}
		return "", err
	}
	return filepath.ToSlash(relative), nil
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
