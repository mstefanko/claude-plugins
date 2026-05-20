package buildcmd

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/repocontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runresult"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/scope"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func runBuildProviders(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, baseline buildverify.Result, worktreePaths map[string]string, capabilities map[string]provider.ScopeCapabilities, keepWorktrees bool, quiet bool, repoLayoutBlock string, noRepoLayout bool) ([]providerRun, error) {
	group, groupCtx := errgroup.WithContext(ctx)
	results := make([]providerRun, len(wo.Providers))
	for index, participant := range wo.Providers {
		index := index
		participant := participant
		group.Go(func() error {
			run, err := runOneBuildProvider(groupCtx, f, wo, participant, repo, runDir, baseline, worktreePaths[participant.ID], capabilities[participant.Backend], keepWorktrees, quiet, repoLayoutBlock, noRepoLayout)
			if err != nil && !errors.Is(err, context.Canceled) {
				run = providerRun{
					ID:                  participant.ID,
					WorktreePath:        worktreePaths[participant.ID],
					WorkerResult:        runresult.InternalError(err),
					ProviderArtifactDir: filepath.Join(runDir, "providers", participant.ID),
					IneligibleReasons:   []string{err.Error()},
				}
				if mkdirErr := os.MkdirAll(run.ProviderArtifactDir, 0o700); mkdirErr != nil {
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
func runOneBuildProvider(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, participant workorder.Participant, repo buildworkspace.Repository, runDir string, baseline buildverify.Result, worktreePath string, caps provider.ScopeCapabilities, keepWorktrees bool, quiet bool, repoLayoutBlock string, noRepoLayout bool) (run providerRun, err error) {
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
	if err := os.MkdirAll(providerDir, 0o700); err != nil {
		return run, err
	}
	if err := os.MkdirAll(buildDir, 0o700); err != nil {
		return run, err
	}
	workerPrompt, err := prompt.BuildWorkerPromptWithRepoLayout(wo, participant, buildParticipantRepoLayout(wo, participant, repoLayoutBlock, noRepoLayout))
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
			Env:              runnerenv.SafeEnv(os.Environ()),
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
	if finalStatus(jsonutil.FinalJSONMap(run.WorkerResult)) == "blocked" {
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
			run.ProtectedViolations = buildworkspace.ProtectedPathViolations(capture.ChangedFiles, wo.Build.ProtectedPaths)
			if len(run.ProtectedViolations) > 0 {
				reason := protectedPathIneligibleReason(run.ProtectedViolations)
				run.IneligibleReasons = append(run.IneligibleReasons, reason)
				if err := workorder.WriteJSONAtomic(filepath.Join(buildDir, "protected-paths.json"), map[string]any{
					"reason":     reason,
					"violations": run.ProtectedViolations,
				}); err != nil {
					return run, err
				}
			}
		}
	}
	if len(run.IneligibleReasons) == 0 {
		run.Verify = buildverify.Run(ctx, buildverify.Options{
			CWD:                   providerCWD,
			ProviderID:            participant.ID,
			BaselineResults:       verifierResultsByID(baseline.Results),
			Verifiers:             wo.Build.Verify,
			Env:                   runnerenv.SafeEnv(os.Environ()),
			HeartbeatSeconds:      wo.Budgets.HeartbeatSeconds,
			OutputCapGraceSeconds: wo.Budgets.OutputCapGraceSeconds,
			MaxOutputOverrunBytes: wo.Budgets.MaxOutputOverrunBytes,
			ArtifactDir:           filepath.Join(buildDir, "verify"),
			OnTick:                makeVerifierTickPrinter(f, quiet),
		})
	} else {
		run.Verify = buildverify.Result{Scope: "provider", ProviderID: participant.ID, GatesPassed: false}
	}
	if err := os.MkdirAll(filepath.Join(buildDir, "verify"), 0o700); err != nil {
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

func buildParticipantRepoLayout(wo *workorder.WorkOrder, participant workorder.Participant, repoLayoutBlock string, disabled bool) string {
	return repocontext.LayoutBlockForParticipant(wo.ScopePolicy, participant, repoLayoutBlock, disabled)
}

func protectedPathIneligibleReason(violations []buildworkspace.ProtectedPathViolation) string {
	paths := protectedPathNames(violations)
	if len(paths) == 1 {
		return `patch changed protected path "` + paths[0] + `"; revise the patch or remove that path from build.protected_paths if it is intentionally editable`
	}
	quoted := make([]string, 0, len(paths))
	for _, path := range paths {
		quoted = append(quoted, `"`+path+`"`)
	}
	return "patch changed protected paths " + strings.Join(quoted, ", ") + "; revise the patch or remove those paths from build.protected_paths if they are intentionally editable"
}

func protectedPathNames(violations []buildworkspace.ProtectedPathViolation) []string {
	seen := map[string]bool{}
	paths := []string{}
	for _, violation := range violations {
		if violation.ProtectedPath == "" || seen[violation.ProtectedPath] {
			continue
		}
		seen[violation.ProtectedPath] = true
		paths = append(paths, violation.ProtectedPath)
	}
	return paths
}
