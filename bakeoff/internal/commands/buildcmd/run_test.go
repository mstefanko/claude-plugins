package buildcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type buildTestFactory struct {
	streams      output.Streams
	capabilities *provider.CapabilityRegistry
}

func (f buildTestFactory) Streams() output.Streams {
	return f.streams
}

func (f buildTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f buildTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f buildTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f buildTestFactory) Capabilities() *provider.CapabilityRegistry {
	return f.capabilities
}

func TestBuildParticipantArgvRequiresCodexWorkspaceWrite(t *testing.T) {
	participant := workorder.Participant{ID: "codex", Backend: "codex", Model: "codex-test", Effort: "high", Scope: "codebase"}
	argv, metadata, err := buildParticipantArgv(participant, workorder.ScopePolicy{Enforcement: "best_effort"}, "/tmp/worktree", provider.ScopeCapabilities{Backend: "codex", Supports: map[string]bool{"sandbox": true, "disable_feature": true}}, "")
	if err == nil || argv != nil {
		t.Fatalf("expected scope error without workspace-write, argv=%v err=%v", argv, err)
	}
	if metadata["enforcement_level"] != "failed" {
		t.Fatalf("metadata = %#v", metadata)
	}

	argv, _, err = buildParticipantArgv(participant, workorder.ScopePolicy{Enforcement: "best_effort"}, "/tmp/worktree", provider.ScopeCapabilities{Backend: "codex", Supports: map[string]bool{"sandbox": true, "sandbox_workspace_write": true, "disable_feature": true}}, "/tmp/last-message.txt")
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(argv, " ")
	if !strings.Contains(joined, "--sandbox workspace-write") || !strings.Contains(joined, "-C /tmp/worktree") {
		t.Fatalf("codex argv missing workspace controls: %v", argv)
	}
}

func TestBuildEnvScrubsSecrets(t *testing.T) {
	got := runnerenv.SafeEnv([]string{
		"PATH=/bin",
		"BAKEOFF_FAKE_FAIL_PROVIDERS=codex",
		"ANTHROPIC_API_KEY=secret",
		"OPENAI_BASE_URL=https://example.invalid",
		"GH_TOKEN=secret",
		"MY_PASSWORD=secret",
	})
	joined := strings.Join(got, "\n")
	for _, want := range []string{"PATH=/bin", "BAKEOFF_FAKE_FAIL_PROVIDERS=codex"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("expected %s in env %q", want, joined)
		}
	}
	for _, forbidden := range []string{"ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "GH_TOKEN", "MY_PASSWORD"} {
		if strings.Contains(joined, forbidden) {
			t.Fatalf("env leaked %s in %q", forbidden, joined)
		}
	}
}

func TestRenderBuildReportOutcomeAndSingleSelectionBasis(t *testing.T) {
	decision := map[string]any{
		"decision_kind":    "pick_winner",
		"canonical_winner": "claude",
		"selection_basis":  "metric",
	}
	report := renderBuildReport(
		&workorder.WorkOrder{ID: "build-report"},
		"build-run",
		"runs",
		filepath.Join(t.TempDir(), "run"),
		decision,
		buildverify.Result{GatesPassed: true},
		[]providerRun{{
			ID:           "claude",
			WorkerResult: map[string]any{"status": "complete"},
			Capture:      &buildworkspace.CaptureResult{PatchBytes: 123},
			Verify:       buildverify.Result{GatesPassed: true},
		}},
		nil,
		buildDiagnostics{},
	)
	for _, want := range []string{
		"## Outcome",
		"Decision: `pick_winner`",
		"Winner: `claude`",
		"Selection basis: `metric`",
		"Patch: `providers/claude/build/diff.patch`",
		"Next: `bakeoff show build-run`",
	} {
		if !strings.Contains(report, want) {
			t.Fatalf("report missing %q:\n%s", want, report)
		}
	}
	if strings.Count(report, "Selection basis:") != 1 {
		t.Fatalf("report should render selection basis once:\n%s", report)
	}
	if strings.Index(report, "## Outcome") > strings.Index(report, "## Baseline Verification") {
		t.Fatalf("outcome should be first substantive report section:\n%s", report)
	}
}

func TestBuildResultLineSummarizesDecision(t *testing.T) {
	got := buildResultLine(map[string]any{
		"decision_kind":    "pick_winner",
		"canonical_winner": "claude",
		"selection_basis":  "judge",
	})
	if got != "pick_winner, winner=claude, basis=judge" {
		t.Fatalf("buildResultLine = %q", got)
	}
}

func TestRunBuildMutatesIsolatedWorktreesAndCapturesPatches(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "build-test",
		"type":           "build",
		"goal":           "Write fake build output.",
		"background":     "Fake providers write files so the harness can capture patches.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "codebase"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"build": map[string]any{
			"base_ref":        "HEAD",
			"comparison_goal": "Prefer the lower fake score.",
			"patch_max_bytes": 100000,
			"verify": []map[string]any{
				{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
				{"id": "score", "kind": "metric", "argv": []string{"./metric.sh"}, "wall_clock_seconds": 5, "max_output_bytes": 2000, "metric": map[string]any{"name": "score", "direction": "lower", "min_delta_percent": 10}},
			},
		},
		"budgets": map[string]any{"wall_clock_seconds": 5, "max_output_bytes": 10000, "heartbeat_seconds": 0, "output_cap_grace_seconds": 1, "max_output_overrun_bytes": 10000},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	fakeBin := filepath.Join(moduleRoot(t), "tests", "parity", "fakes")
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	factory := buildTestFactory{streams: output.NewStreams(&out, &errOut)}
	factory.capabilities = provider.NewCapabilityRegistry(factory.LookupProvider)

	oldWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(repoDir); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWD)

	outDir := filepath.Join(root, "runs")
	err = RunBuild(context.Background(), factory, &BuildOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "build-run", Quiet: true, JSON: true})
	if err != nil {
		runDir := filepath.Join(outDir, "build-run")
		claudeStderr, _ := os.ReadFile(filepath.Join(runDir, "providers", "claude", "stderr.txt"))
		codexStderr, _ := os.ReadFile(filepath.Join(runDir, "providers", "codex", "stderr.txt"))
		t.Fatalf("RunBuild returned error: %v\nfakeBin=%s\nstdout:\n%s\nstderr:\n%s\nclaude stderr:\n%s\ncodex stderr:\n%s", err, fakeBin, out.String(), errOut.String(), claudeStderr, codexStderr)
	}
	runDir := filepath.Join(outDir, "build-run")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["canonical_winner"] != "claude" || decision["selection_basis"] != "metric" {
		t.Fatalf("decision = %#v", decision)
	}
	for _, providerID := range []string{"claude", "codex"} {
		patchPath := filepath.Join(runDir, "providers", providerID, "build", "diff.patch")
		patch, err := os.ReadFile(patchPath)
		if err != nil {
			t.Fatalf("%s patch missing: %v", providerID, err)
		}
		if !strings.Contains(string(patch), providerID+"-build.txt") || !strings.Contains(string(patch), "bakeoff-build-output.txt") {
			t.Fatalf("%s patch did not capture fake files:\n%s", providerID, patch)
		}
		workspace := readJSONFile(t, filepath.Join(runDir, "providers", providerID, "build", "workspace.json"))
		if workspace["cleanup_status"] != "removed" {
			t.Fatalf("%s workspace cleanup = %#v", providerID, workspace)
		}
	}
	diagnostics := readJSONFile(t, filepath.Join(runDir, "diagnostics.json"))
	if diagnostics["schema_version"] != float64(1) {
		t.Fatalf("diagnostics missing schema version: %#v", diagnostics)
	}
	if _, ok := diagnostics["prompt_sizes"].([]any); !ok {
		t.Fatalf("diagnostics missing prompt sizes: %#v", diagnostics)
	}
	if _, ok := diagnostics["phase_timings"].([]any); !ok {
		t.Fatalf("diagnostics missing phase timings: %#v", diagnostics)
	}
	if _, ok := diagnostics["baseline_metric_deltas"].([]any); !ok {
		t.Fatalf("diagnostics missing baseline metric deltas: %#v", diagnostics)
	}
	if checks, ok := diagnostics["patch_integrity_checks"].([]any); !ok {
		t.Fatalf("diagnostics missing patch integrity checks: %#v", diagnostics)
	} else {
		for _, raw := range checks {
			check, _ := raw.(map[string]any)
			if check["status"] != "passed" || check["check_base"] != "base_commit_worktree" {
				t.Fatalf("unexpected patch integrity check: %#v", check)
			}
		}
	}
	if _, err := os.Stat(filepath.Join(runDir, "worktrees", "claude")); !os.IsNotExist(err) {
		t.Fatalf("provider worktree should have been removed, stat err=%v", err)
	}
	if !strings.Contains(out.String(), `"command": "build"`) || !strings.Contains(out.String(), `"winner": "claude"`) {
		t.Fatalf("summary stdout missing build winner:\n%s", out.String())
	}
	report, err := os.ReadFile(filepath.Join(runDir, "report.md"))
	if err != nil {
		t.Fatal(err)
	}
	reportText := string(report)
	for _, want := range []string{
		"Checkpoint: Bakeoff selected this exact provider patch and has not applied it.",
		"Use this report and the selected patch artifact as handoff material for a fresh session",
		"Post-run edits, synthesis, or reimplementation are outside this bakeoff decision.",
		"Patch artifact: `providers/claude/build/diff.patch`",
		"score=1, unit=points, n=10, statistic=sample, method=fake metric",
	} {
		if !strings.Contains(reportText, want) {
			t.Fatalf("report missing handoff contract %q:\n%s", want, reportText)
		}
	}
	for _, forbidden := range []string{"Manual apply command", "git apply"} {
		if strings.Contains(reportText, forbidden) {
			t.Fatalf("report should not include apply instructions %q:\n%s", forbidden, reportText)
		}
	}
}

func TestPatchIntegrityChecksUseBaseCommitWorktree(t *testing.T) {
	ctx := context.Background()
	repoDir := initBuildGitRepo(t)
	repo, err := buildworkspace.ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	runDir := t.TempDir()
	worktreePath := filepath.Join(t.TempDir(), "provider")
	if err := buildworkspace.CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}
	defer buildworkspace.CleanupWorktree(ctx, repo, worktreePath, false)

	if err := os.WriteFile(filepath.Join(worktreePath, "README.md"), []byte("provider patch\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	captureDir := filepath.Join(runDir, "providers", "claude", "build")
	capture, err := buildworkspace.CaptureChanges(ctx, buildworkspace.CaptureOptions{
		WorktreePath:  worktreePath,
		BaseCommit:    repo.BaseCommit,
		OutputDir:     captureDir,
		PatchMaxBytes: 100000,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repoDir, "README.md"), []byte("dirty source checkout\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	checks := collectPatchIntegrityChecks(ctx, repo, runDir, []providerRun{{
		ID:      "claude",
		Capture: &capture,
	}})
	if len(checks) != 1 {
		t.Fatalf("checks = %#v", checks)
	}
	check := checks[0]
	if check.Status != "passed" || check.CheckBase != "base_commit_worktree" || check.BaseCommit != repo.BaseCommit {
		t.Fatalf("check = %#v", check)
	}
}

func TestRunBuildUsesInvocationSubdirectory(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	writeAndCommitFile(t, repoDir, "app/README.md", "app\n", 0o644)
	writeAndCommitFile(t, repoDir, "app/metric.sh", `#!/bin/sh
if [ -f claude-build.txt ]; then
  printf '{"score":1}\n'
else
  printf '{"score":2}\n'
fi
`, 0o755)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "subdir-cwd", 100000, nil)
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTestFromCWD(t, filepath.Join(repoDir, "app"), workOrderPath, outDir, BuildOptions{RunID: "subdir-cwd", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	runDir := filepath.Join(outDir, "subdir-cwd")
	context := readJSONFile(t, filepath.Join(runDir, "build-context.json"))
	if context["source_invocation_relative_path"] != "app" {
		t.Fatalf("context invocation path = %#v", context)
	}
	workspace := readJSONFile(t, filepath.Join(runDir, "providers", "claude", "build", "workspace.json"))
	if !strings.HasSuffix(fmt.Sprint(workspace["provider_cwd"]), "/app") {
		t.Fatalf("workspace provider cwd = %#v", workspace)
	}
	capture := readJSONFile(t, filepath.Join(runDir, "providers", "claude", "build", "capture.json"))
	changed, _ := capture["changed_files"].([]any)
	if len(changed) == 0 || !strings.Contains(fmt.Sprint(changed), "app/claude-build.txt") {
		t.Fatalf("captured changes should be rooted under app: %#v", capture)
	}
	scope := readJSONFile(t, filepath.Join(runDir, "providers", "claude", "build", "scope.json"))
	if _, ok := scope["out_of_invocation_files"]; ok {
		t.Fatalf("subdir-local edits should not be scope drift: %#v", scope)
	}
}

func TestDiagnoseBuildScopeFlagsInstructionAndOutOfInvocationFiles(t *testing.T) {
	repo := buildworkspace.Repository{InvocationRelPath: "bakeoff"}
	diagnostics := diagnoseBuildScope(repo, []buildworkspace.ChangedFile{
		{Status: "A", Path: "CLAUDE.md"},
		{Status: "M", Path: "bakeoff/internal/prompt/prompt.go"},
		{Status: "M", Path: "docs/notes.md"},
	})
	if len(diagnostics.OutOfInvocationFiles) != 2 || len(diagnostics.AgentInstructionFiles) != 1 {
		t.Fatalf("scope diagnostics = %#v", diagnostics)
	}
}

func TestRunBuildGateVerifierSelectsOnlyPassingPatch(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	writeAndCommitFile(t, repoDir, "gate-no-codex.sh", `#!/bin/sh
if [ -f codex-build.txt ]; then
  exit 1
fi
test -f README.md
`, 0o755)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "gate-winner", 100000, []map[string]any{
		{"id": "no-codex", "kind": "gate", "argv": []string{"./gate-no-codex.sh"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "gate-winner", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "gate-winner", "decision.json"))
	if decision["decision_kind"] != "pick_winner" || decision["selection_basis"] != "gate" || decision["canonical_winner"] != "claude" || decision["judge_ran"] != false {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestRunBuildProtectedPathMakesProviderIneligible(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "protected-one", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	data := readJSONFile(t, workOrderPath)
	build := data["build"].(map[string]any)
	build["protected_paths"] = []any{"codex-build.txt"}
	if err := workorder.WriteJSONAtomic(workOrderPath, data); err != nil {
		t.Fatal(err)
	}
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "protected-one", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build should continue with claude after codex protected path violation: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	runDir := filepath.Join(outDir, "protected-one")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "single_provider_only" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision = %#v", decision)
	}
	statuses := decision["provider_statuses"].(map[string]any)
	codexStatus := statuses["codex"].(map[string]any)
	if codexStatus["patch_state"] != "protected_path_changed" || codexStatus["verify_state"] != "not_run" {
		t.Fatalf("codex status = %#v", codexStatus)
	}
	reason := fmt.Sprint(codexStatus["ineligible_reasons"])
	if !strings.Contains(reason, `patch changed protected path "codex-build.txt"; revise the patch or remove that path from build.protected_paths if it is intentionally editable`) {
		t.Fatalf("missing exact protected path reason: %#v", codexStatus)
	}
	protected := readJSONFile(t, filepath.Join(runDir, "providers", "codex", "build", "protected-paths.json"))
	if !strings.Contains(fmt.Sprint(protected["violations"]), "codex-build.txt") {
		t.Fatalf("protected artifact = %#v", protected)
	}
	if _, err := os.Stat(filepath.Join(runDir, "providers", "codex", "build", "verify", "readme")); !os.IsNotExist(err) {
		t.Fatalf("codex verification should be skipped, stat err=%v", err)
	}
}

func TestRunBuildBothProtectedPathViolationsUseBothFailed(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "protected-both", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	data := readJSONFile(t, workOrderPath)
	build := data["build"].(map[string]any)
	build["protected_paths"] = []any{"bakeoff-build-output.txt"}
	if err := workorder.WriteJSONAtomic(workOrderPath, data); err != nil {
		t.Fatal(err)
	}
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "protected-both", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected both providers to be ineligible\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "protected-both", "decision.json"))
	if decision["decision_kind"] != "both_failed" || decision["selection_basis"] != "none" || decision["canonical_winner"] != nil {
		t.Fatalf("decision = %#v", decision)
	}
	if strings.Contains(fmt.Sprint(decision), "both_ineligible") {
		t.Fatalf("should not add a new decision kind for protected paths: %#v", decision)
	}
	if !strings.Contains(fmt.Sprint(decision["caveats"]), "protected path") {
		t.Fatalf("missing protected path caveat: %#v", decision)
	}
}

func TestRunBuildIdenticalCapturedPatchesTieWithoutJudge(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "identical-patch", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	t.Setenv("BAKEOFF_FAKE_IDENTICAL_BUILD_PATCH", "1")
	t.Setenv("BAKEOFF_FAKE_JUDGE_MODE", "build_pick_claude")
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "identical-patch", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected unresolved identical-patch tie\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	runDir := filepath.Join(outDir, "identical-patch")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "tie" || decision["selection_basis"] != "identical_patch" || decision["judge_ran"] != false {
		t.Fatalf("decision = %#v", decision)
	}
	if _, err := os.Stat(filepath.Join(runDir, "judge", "result-pass1.json")); !os.IsNotExist(err) {
		t.Fatalf("judge should not run for identical patches, stat err=%v", err)
	}
}

func TestRunBuildBothPassJudgeWinner(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "judge-winner", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	t.Setenv("BAKEOFF_FAKE_JUDGE_MODE", "build_pick_claude")
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "judge-winner", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	runDir := filepath.Join(outDir, "judge-winner")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "pick_winner" || decision["selection_basis"] != "judge" || decision["canonical_winner"] != "claude" || decision["judge_ran"] != true {
		t.Fatalf("decision = %#v", decision)
	}
	if _, err := os.Stat(filepath.Join(runDir, "judge", "result-pass1.json")); err != nil {
		t.Fatalf("missing build judge result: %v", err)
	}
	report, err := os.ReadFile(filepath.Join(runDir, "report.md"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(report), "## Winner Handoff") || !strings.Contains(string(report), "Selection basis: `judge`") {
		t.Fatalf("report missing judge handoff:\n%s", report)
	}
	if !strings.Contains(string(report), "derived patch") {
		t.Fatalf("report missing derived patch boundary:\n%s", report)
	}
}

func TestRunBuildBothFailVerification(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	writeAndCommitFile(t, repoDir, "gate-no-build-output.sh", `#!/bin/sh
if [ -f claude-build.txt ] || [ -f codex-build.txt ]; then
  exit 1
fi
test -f README.md
`, 0o755)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "both-fail-verify", 100000, []map[string]any{
		{"id": "no-build-output", "kind": "gate", "argv": []string{"./gate-no-build-output.sh"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "both-fail-verify", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected verifier failure\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "both-fail-verify", "decision.json"))
	if decision["decision_kind"] != "both_failed_verification" || decision["selection_basis"] != "none" || decision["canonical_winner"] != nil {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestRunBuildMetricInconclusiveFallsBackToJudge(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	writeAndCommitFile(t, repoDir, "metric-equal.sh", `#!/bin/sh
printf '{"score":1}\n'
`, 0o755)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "metric-judge", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
		{"id": "score", "kind": "metric", "argv": []string{"./metric-equal.sh"}, "wall_clock_seconds": 5, "max_output_bytes": 2000, "metric": map[string]any{"name": "score", "direction": "lower", "min_delta_percent": 10}},
	})
	t.Setenv("BAKEOFF_FAKE_JUDGE_MODE", "build_pick_claude")
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "metric-judge", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "metric-judge", "decision.json"))
	if decision["selection_basis"] != "judge" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestRunBuildJudgeDisagreementExitsThree(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "judge-disagree", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	t.Setenv("BAKEOFF_FAKE_JUDGE_MODE", "build_always_a")
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "judge-disagree", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected unresolved build\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "judge-disagree", "decision.json"))
	if decision["decision_kind"] != "tie" || decision["selection_basis"] != "none" || decision["canonical_winner"] != nil {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestRunBuildJudgeFailureDoesNotResolveAsJudgeRun(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "judge-fails", 100000, []map[string]any{
		{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	t.Setenv("BAKEOFF_FAKE_FAIL_JUDGE", "1")
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "judge-fails", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected judge failure\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "judge-fails", "decision.json"))
	if decision["judge_ran"] != false || decision["selection_basis"] != "none" {
		t.Fatalf("decision = %#v", decision)
	}
	caveats, _ := decision["caveats"].([]any)
	if len(caveats) == 0 || !strings.Contains(fmt.Sprint(caveats), "build judge failed") {
		t.Fatalf("missing judge failure caveat: %#v", decision)
	}
}

func TestBuildJudgeTextPreviewReportsErrorsAndSanitizesUTF8(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "patch.diff")
	if err := os.WriteFile(path, []byte{'h', 'i', ' ', 0xe2, 0x82}, 0o644); err != nil {
		t.Fatal(err)
	}
	preview, truncated, err := readTextPreview(path, 4)
	if err != nil {
		t.Fatal(err)
	}
	if !truncated || !strings.Contains(preview, "\uFFFD") || !strings.Contains(preview, "[truncated]") {
		t.Fatalf("preview=%q truncated=%t", preview, truncated)
	}
	if _, _, err := readTextPreview(filepath.Join(dir, "missing"), 4); err == nil {
		t.Fatal("expected missing file error")
	}
}

func TestBuildJudgePayloadCompactsSharedEvidenceAndPatchExcerpt(t *testing.T) {
	runDir := t.TempDir()
	providerDir := filepath.Join(runDir, "providers", "claude", "build")
	if err := os.MkdirAll(providerDir, 0o755); err != nil {
		t.Fatal(err)
	}
	diffstatPath := filepath.Join(providerDir, "diffstat.txt")
	patchPath := filepath.Join(providerDir, "diff.patch")
	if err := os.WriteFile(diffstatPath, []byte(" main.go | 1 +\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(patchPath, []byte(strings.Repeat("x", buildJudgePatchExcerptBytes+20)), 0o644); err != nil {
		t.Fatal(err)
	}
	exitCode := 0
	verify := buildverify.Result{
		Scope:       "provider",
		ProviderID:  "claude",
		GatesPassed: true,
		Results: []buildverify.VerifierResult{{
			ID:         "unit",
			Kind:       "gate",
			Status:     buildverify.StatusPassed,
			ExitCode:   &exitCode,
			StatusPath: filepath.Join(providerDir, "verify", "unit", "status.json"),
		}},
	}
	run := providerRun{
		ID:           "claude",
		WorkerResult: map[string]any{"status": "ok", "payload": map[string]any{"status": "complete"}},
		Capture: &buildworkspace.CaptureResult{
			ChangedFiles: []buildworkspace.ChangedFile{{Status: "M", Path: "main.go"}},
			PatchBytes:   buildJudgePatchExcerptBytes + 20,
			PatchPath:    patchPath,
			DiffstatPath: diffstatPath,
		},
		Verify: verify,
		Workspace: buildworkspace.WorkspaceMetadata{
			BaseRef:                  "HEAD",
			BaseCommit:               "1234567890abcdef",
			ProviderCWD:              filepath.Join(runDir, "worktrees", "claude"),
			CleanupStatus:            "removed",
			ProviderHead:             "abcdef1234567890",
			ProviderHeadIsBase:       false,
			ProviderCommittedChanges: true,
			WorktreeRemoved:          true,
		},
	}
	shared := buildJudgeSharedEvidence(runDir, verify, []buildverify.MetricComparison{{ID: "score", Name: "score", Direction: "lower", Winner: "claude", Conclusive: true}})
	payload := buildJudgePayload(runDir, run)

	if _, ok := payload["baseline_verify"]; ok {
		t.Fatal("candidate payload should not duplicate shared baseline verification")
	}
	if _, ok := payload["metric_decisions"]; ok {
		t.Fatal("candidate payload should not duplicate shared metric decisions")
	}
	if shared["baseline_verify"] == nil || shared["metric_decisions"] == nil {
		t.Fatalf("shared evidence missing verifier context: %#v", shared)
	}
	if _, ok := payload["capture"]; ok {
		t.Fatal("candidate payload should not include full capture metadata")
	}
	patch := payload["patch"].(map[string]any)
	if got := patch["patch_path"]; got != "providers/claude/build/diff.patch" {
		t.Fatalf("patch_path = %#v", got)
	}
	excerpt, _ := patch["patch_excerpt"].(string)
	if !patch["patch_excerpt_truncated"].(bool) || !strings.Contains(excerpt, "[truncated]") {
		t.Fatalf("expected truncated patch excerpt, patch=%#v", patch)
	}
	verifyPayload := payload["verify"].(map[string]any)
	resultPayload := verifyPayload["results"].([]map[string]any)[0]
	if got := resultPayload["status_path"]; got != "providers/claude/build/verify/unit/status.json" {
		t.Fatalf("status_path = %#v", got)
	}
}

func TestRunBuildBaselineFailureSkipsProviders(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "baseline-fails", 100000, []map[string]any{
		{"id": "missing", "kind": "gate", "argv": []string{"test", "-f", "definitely-missing"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "baseline-fails", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected baseline failure\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	runDir := filepath.Join(outDir, "baseline-fails")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "baseline_failed" {
		t.Fatalf("decision = %#v", decision)
	}
	if _, err := os.Stat(filepath.Join(runDir, "providers", "claude")); !os.IsNotExist(err) {
		t.Fatalf("providers should not be launched, stat err=%v", err)
	}
}

func TestRunBuildBaselineMustFailPassSurpriseSkipsProviders(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "baseline-surprise", 100000, []map[string]any{
		{"id": "target", "kind": "gate", "baseline": "must_fail", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "baseline-surprise", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected baseline expectation failure\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	runDir := filepath.Join(outDir, "baseline-surprise")
	decision := readJSONFile(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "baseline_expectation_failed" {
		t.Fatalf("decision = %#v", decision)
	}
	caveats := fmt.Sprint(decision["caveats"])
	if !strings.Contains(caveats, "expected baseline `must_fail`, observed `passed`") {
		t.Fatalf("missing expectation caveat: %#v", decision)
	}
	if _, err := os.Stat(filepath.Join(runDir, "providers", "claude")); !os.IsNotExist(err) {
		t.Fatalf("providers should not be launched, stat err=%v", err)
	}
}

func TestRunBuildMayFailBaselineIsInformational(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "baseline-may-fail", 100000, []map[string]any{
		{"id": "target", "kind": "gate", "baseline": "may_fail", "argv": []string{"test", "-f", "bakeoff-build-output.txt"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
	})
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "baseline-may-fail", Quiet: true, JSON: true})
	if err != nil {
		t.Fatalf("may_fail baseline should not block providers: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	runDir := filepath.Join(outDir, "baseline-may-fail")
	baseline := readJSONFile(t, filepath.Join(runDir, "baseline", "verify", "result.json"))
	results := baseline["results"].([]any)
	first := results[0].(map[string]any)
	if first["baseline_expectation"] != "may_fail" || first["baseline_matched"] != true || first["status"] != "failed" {
		t.Fatalf("baseline result = %#v", first)
	}
	providerStatus := readJSONFile(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "target", "status.json"))
	if providerStatus["transition"] != "baseline_failed_to_provider_passed" {
		t.Fatalf("provider status = %#v", providerStatus)
	}
}

func TestRunBuildKeepWorktreesAndForceCleanup(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "keep-force", 100000, nil)
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "keep-force", Quiet: true, JSON: true, KeepWorktrees: true}); err != nil {
		t.Fatalf("first build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	runDir := filepath.Join(outDir, "keep-force")
	if _, err := os.Stat(filepath.Join(runDir, "worktrees", "claude")); err != nil {
		t.Fatalf("expected retained worktree: %v", err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "sentinel.txt"), []byte("old\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "keep-force", Force: true, Quiet: true, JSON: true}); err != nil {
		t.Fatalf("force build failed: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	if _, err := os.Stat(filepath.Join(runDir, "sentinel.txt")); !os.IsNotExist(err) {
		t.Fatalf("force should remove old run contents, stat err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(runDir, "worktrees", "claude")); !os.IsNotExist(err) {
		t.Fatalf("force rerun should clean provider worktree, stat err=%v", err)
	}
}

func TestRunBuildPatchOverCapMakesProviderIneligible(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "patch-cap", 1, nil)
	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "patch-cap", Quiet: true, JSON: true})
	if err == nil {
		t.Fatalf("expected patch cap failure\nstdout:\n%s\nstderr:\n%s", out, errOut)
	}
	ineligible := readJSONFile(t, filepath.Join(outDir, "patch-cap", "providers", "claude", "build", "ineligible.json"))
	reasons, _ := ineligible["reasons"].([]any)
	if len(reasons) == 0 || !strings.Contains(fmt.Sprint(reasons[0]), "patch exceeded") {
		t.Fatalf("ineligible = %#v", ineligible)
	}
}

func TestRunBuildCodexMissingWorkspaceWriteRecordsScopeError(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "codex-scope", 100000, nil)
	t.Setenv("BAKEOFF_FAKE_SCOPE_HELP_MODE", "none")
	outDir := filepath.Join(root, "runs")
	if out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "codex-scope", Quiet: true, JSON: true}); err != nil {
		t.Fatalf("build should continue with claude after codex scope_error: %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	status := readJSONFile(t, filepath.Join(outDir, "codex-scope", "providers", "codex", "status.json"))
	if status["status"] != "scope_error" {
		t.Fatalf("codex status = %#v", status)
	}
	scopeMetadata, _ := status["scope_enforcement"].(map[string]any)
	if scopeMetadata["enforcement_level"] != "failed" || !strings.Contains(fmt.Sprint(scopeMetadata["fallback_reason"]), "workspace-write") {
		t.Fatalf("codex scope metadata = %#v", scopeMetadata)
	}
	decision := readJSONFile(t, filepath.Join(outDir, "codex-scope", "decision.json"))
	if decision["decision_kind"] != "single_provider_only" || decision["selection_basis"] != "gate" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestRunBuildValidationRejectsWebScope(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "web-scope", 100000, nil)
	data := readJSONFile(t, workOrderPath)
	providers, _ := data["providers"].([]any)
	provider0, _ := providers[0].(map[string]any)
	provider0["scope"] = "web"
	if err := workorder.WriteJSONAtomic(workOrderPath, data); err != nil {
		t.Fatal(err)
	}
	_, _, err := runBuildTest(t, repoDir, workOrderPath, filepath.Join(root, "runs"), BuildOptions{RunID: "web-scope", Quiet: true, JSON: true})
	if err == nil || !strings.Contains(err.Error(), `scope "web"`) {
		t.Fatalf("expected web scope validation error, got %v", err)
	}
}

func TestRunBuildFailsWhenSameRepoLockHeld(t *testing.T) {
	repoDir := initBuildGitRepo(t)
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "build.work-order.json")
	writeBuildWorkOrder(t, workOrderPath, "locked", 100000, nil)
	repo, err := buildworkspace.ResolveRepository(context.Background(), repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	lock, err := buildworkspace.AcquireLock(context.Background(), repo.CommonDir, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	previousTimeout := buildSetupLockTimeout
	buildSetupLockTimeout = 50 * time.Millisecond
	defer func() { buildSetupLockTimeout = previousTimeout }()

	outDir := filepath.Join(root, "runs")
	out, errOut, err := runBuildTest(t, repoDir, workOrderPath, outDir, BuildOptions{RunID: "locked", Quiet: true, JSON: true})
	if err == nil || !strings.Contains(err.Error(), "another build run is active") {
		t.Fatalf("expected same-repo lock failure, got %v\nstdout:\n%s\nstderr:\n%s", err, out, errOut)
	}
	if _, statErr := os.Stat(filepath.Join(outDir, "locked", "providers")); !os.IsNotExist(statErr) {
		t.Fatalf("providers should not be launched while lock is held, stat err=%v", statErr)
	}
}

func writeBuildWorkOrder(t *testing.T, path string, id string, patchMaxBytes int, verify []map[string]any) {
	t.Helper()
	if verify == nil {
		verify = []map[string]any{
			{"id": "readme", "kind": "gate", "argv": []string{"test", "-f", "README.md"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
			{"id": "score", "kind": "metric", "argv": []string{"./metric.sh"}, "wall_clock_seconds": 5, "max_output_bytes": 2000, "metric": map[string]any{"name": "score", "direction": "lower", "min_delta_percent": 10}},
		}
	}
	if err := workorder.WriteJSONAtomic(path, map[string]any{
		"schema_version": 1,
		"id":             id,
		"type":           "build",
		"goal":           "Write fake build output.",
		"background":     "Fake providers write files so the harness can capture patches.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "codebase"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"build": map[string]any{
			"base_ref":        "HEAD",
			"comparison_goal": "Prefer the lower fake score.",
			"patch_max_bytes": patchMaxBytes,
			"verify":          verify,
		},
		"budgets": map[string]any{"wall_clock_seconds": 5, "max_output_bytes": 10000, "heartbeat_seconds": 0, "output_cap_grace_seconds": 1, "max_output_overrun_bytes": 10000},
	}); err != nil {
		t.Fatal(err)
	}
}

func runBuildTest(t *testing.T, repoDir string, workOrderPath string, outDir string, opts BuildOptions) (string, string, error) {
	t.Helper()
	return runBuildTestFromCWD(t, repoDir, workOrderPath, outDir, opts)
}

func runBuildTestFromCWD(t *testing.T, cwd string, workOrderPath string, outDir string, opts BuildOptions) (string, string, error) {
	t.Helper()
	var out, errOut bytes.Buffer
	fakeBin := filepath.Join(moduleRoot(t), "tests", "parity", "fakes")
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	factory := buildTestFactory{streams: output.NewStreams(&out, &errOut)}
	factory.capabilities = provider.NewCapabilityRegistry(factory.LookupProvider)

	oldWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(cwd); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(oldWD)

	opts.WorkOrder = workOrderPath
	opts.Out = outDir
	err = RunBuild(context.Background(), factory, &opts)
	return out.String(), errOut.String(), err
}

func initBuildGitRepo(t *testing.T) string {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not available")
	}
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	git(t, dir, "init")
	git(t, dir, "config", "core.hooksPath", ".git/hooks")
	git(t, dir, "config", "user.email", "bakeoff@example.com")
	git(t, dir, "config", "user.name", "Bakeoff Test")
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("base\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	metric := `#!/bin/sh
if [ -f claude-build.txt ]; then
  printf '{"score":1,"unit":"points","n":10,"statistic":"sample","method":"fake metric"}\n'
else
  printf '{"score":2,"unit":"points","n":10,"statistic":"sample","method":"fake metric"}\n'
fi
`
	if err := os.WriteFile(filepath.Join(dir, "metric.sh"), []byte(metric), 0o755); err != nil {
		t.Fatal(err)
	}
	git(t, dir, "add", ".")
	git(t, dir, "commit", "-m", "initial")
	return dir
}

func writeAndCommitFile(t *testing.T, repoDir string, relative string, contents string, mode os.FileMode) {
	t.Helper()
	path := filepath.Join(repoDir, relative)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(contents), mode); err != nil {
		t.Fatal(err)
	}
	git(t, repoDir, "add", relative)
	git(t, repoDir, "commit", "-m", "add "+relative)
}

func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, out)
	}
	return string(out)
}

func readJSONFile(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func moduleRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find go.mod")
		}
		dir = parent
	}
}
