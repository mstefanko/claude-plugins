package buildcmd

import (
	"bytes"
	"context"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type buildDiagnostics struct {
	SchemaVersion        int                              `json:"schema_version"`
	PhaseTimings         []buildPhaseTiming               `json:"phase_timings,omitempty"`
	PromptSizes          []promptSizeDiagnostic           `json:"prompt_sizes,omitempty"`
	BaselineMetricDeltas []baselineMetricDelta            `json:"baseline_metric_deltas,omitempty"`
	OutputTruncation     []outputTruncationRecord         `json:"output_truncation,omitempty"`
	PatchIntegrityChecks []patchIntegrityCheck            `json:"patch_integrity_checks,omitempty"`
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

type patchIntegrityCheck struct {
	ProviderID string `json:"provider_id"`
	Status     string `json:"status"`
	PatchPath  string `json:"patch_path"`
	CheckBase  string `json:"check_base"`
	BaseCommit string `json:"base_commit,omitempty"`
	Output     string `json:"output,omitempty"`
	Error      string `json:"error,omitempty"`
}

func collectBuildDiagnostics(ctx context.Context, wo *workorder.WorkOrder, repo buildworkspace.Repository, runDir string, baseline buildverify.Result, runs []providerRun, timings []buildPhaseTiming) buildDiagnostics {
	diagnostics := buildDiagnostics{
		SchemaVersion:        1,
		PhaseTimings:         compactPhaseTimings(timings),
		PromptSizes:          collectPromptSizes(runDir, runs),
		OutputTruncation:     collectOutputTruncation(baseline, runs),
		PatchIntegrityChecks: collectPatchIntegrityChecks(ctx, repo, runDir, runs),
		ScopeDiagnostics:     map[string]buildScopeDiagnostics{},
		SourceWarnings:       sourceWarnings(repo),
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
		if size, ok := fsutil.FileSize(path); ok {
			out = append(out, promptSizeDiagnostic{Path: mustRelative(runDir, path), Bytes: size, Kind: "worker", ProviderID: run.ID})
		}
	}
	for _, label := range []string{"pass1", "pass2"} {
		path := filepath.Join(runDir, "judge", "prompt-"+label+".txt")
		if size, ok := fsutil.FileSize(path); ok {
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
	if jsonutil.BoolValue(result["stdout_truncated"]) {
		out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: verifierID, Stream: "stdout", ObservedBytes: jsonutil.IntValue(result["stdout_observed_bytes"]), RetainedBytes: jsonutil.IntValue(result["stdout_bytes"])})
	}
	if jsonutil.BoolValue(result["stderr_truncated"]) {
		out = append(out, outputTruncationRecord{Scope: scope, ProviderID: providerID, VerifierID: verifierID, Stream: "stderr", ObservedBytes: jsonutil.IntValue(result["stderr_observed_bytes"]), RetainedBytes: jsonutil.IntValue(result["stderr_bytes"])})
	}
	return out
}

func collectPatchIntegrityChecks(ctx context.Context, repo buildworkspace.Repository, runDir string, runs []providerRun) []patchIntegrityCheck {
	var out []patchIntegrityCheck
	for _, run := range runs {
		if run.Capture == nil || run.Capture.PatchPath == "" {
			continue
		}
		check := patchIntegrityCheck{
			ProviderID: run.ID,
			PatchPath:  mustRelative(runDir, run.Capture.PatchPath),
			CheckBase:  "base_commit_worktree",
			BaseCommit: repo.BaseCommit,
		}
		out = append(out, check)
	}
	if len(out) == 0 {
		return nil
	}

	checkParent, err := os.MkdirTemp(runDir, ".patch-integrity-")
	if err != nil {
		return patchIntegrityNotChecked(out, err)
	}
	checkRoot := filepath.Join(checkParent, "worktree")
	defer os.RemoveAll(checkParent)
	created := false
	createCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
	err = withRepoLock(createCtx, repo, buildSetupLockTimeout, func() error {
		if err := buildworkspace.CreateDetachedWorktree(createCtx, repo, checkRoot); err != nil {
			return err
		}
		created = true
		return nil
	})
	cancel()
	if err != nil {
		_ = os.RemoveAll(checkRoot)
		return patchIntegrityNotChecked(out, err)
	}
	defer cleanupPatchIntegrityWorktree(ctx, repo, checkRoot, created)

	for i := range out {
		check := &out[i]
		patchArg, err := filepath.Abs(filepath.Join(runDir, check.PatchPath))
		if err != nil {
			check.Status = "not_checked"
			check.Error = err.Error()
			continue
		}
		checkCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
		var stdout, stderr bytes.Buffer
		cmd := exec.CommandContext(checkCtx, "git", "-C", checkRoot, "apply", "--check", "--3way", "--binary", patchArg)
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
		err = cmd.Run()
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
	}
	return out
}

func patchIntegrityNotChecked(checks []patchIntegrityCheck, err error) []patchIntegrityCheck {
	for i := range checks {
		checks[i].Status = "not_checked"
		checks[i].Error = err.Error()
	}
	return checks
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
