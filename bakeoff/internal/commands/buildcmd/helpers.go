package buildcmd

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var (
	buildSetupLockTimeout   = 5 * time.Second
	buildCleanupLockTimeout = 30 * time.Second
)

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
	status := jsonutil.StringValue(run.WorkerResult["status"])
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

func buildExitError(exitCode int, message string) error {
	if exitCode == 0 {
		return nil
	}
	if exitCode == 3 {
		return &apperror.SilentError{Err: &apperror.JudgeDisagreementError{Message: "build unresolved"}}
	}
	return &apperror.SilentError{Err: fmt.Errorf("%s", message)}
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
