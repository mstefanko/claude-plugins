package researchcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type researchTestFactory struct {
	streams output.Streams
}

func (f researchTestFactory) Streams() output.Streams {
	return f.streams
}

func (f researchTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f researchTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f researchTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f researchTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestCopyReplayContextArtifactsRequiresCompleteSet(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source")
	target := filepath.Join(root, "target")
	if err := os.MkdirAll(source, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(target, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "review-context.md"), []byte("context\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	err := copyReplayContextArtifacts(source, target)
	if err == nil || !strings.Contains(err.Error(), "partial review-context artifact set") {
		t.Fatalf("expected partial replay context error, got %v", err)
	}
}

func TestForceReviewContextCaptureFailurePreservesExistingRun(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	runDir := filepath.Join(outDir, "existing-run")
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(runDir, "sentinel.txt")
	if err := os.WriteFile(sentinel, []byte("keep me\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "capture-failure",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	err := RunResearch(context.Background(), nil, &ResearchOptions{
		WorkOrder: workOrderPath,
		Out:       outDir,
		RunID:     "existing-run",
		Force:     true,
		Base:      "definitely-missing-review-base-ref",
		NoTriage:  true,
	})
	if err == nil || !strings.Contains(err.Error(), "review context base ref not found") {
		t.Fatalf("expected review-context capture error, got %v", err)
	}
	data, readErr := os.ReadFile(sentinel)
	if readErr != nil {
		t.Fatalf("existing run was removed: %v", readErr)
	}
	if string(data) != "keep me\n" {
		t.Fatalf("existing run sentinel changed: %q", string(data))
	}
}

func TestRunResearchReclaimsIncompleteRunDirWithoutForce(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf 'claude fake\n'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
cat >/dev/null
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"R-001","claim":"Recovered run.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "recover-incomplete",
		"type":           "gather",
		"run_mode":       "single_provider",
		"goal":           "Recover an incomplete run.",
		"background":     "Incomplete run recovery smoke test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}
	outDir := filepath.Join(root, "runs")
	runDir := filepath.Join(outDir, "recover-incomplete")
	if err := os.MkdirAll(runDir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), "{}"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "recover-incomplete", Quiet: true, NoTriage: true}); err != nil {
		t.Fatalf("RunResearch returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	if !fsutil.FileExists(filepath.Join(runDir, "manifest.json")) {
		t.Fatalf("recovered run did not complete")
	}
}

func TestRunResearchDoesNotReclaimIncompleteRunDirWithUnknownFiles(t *testing.T) {
	root := t.TempDir()
	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "preserve-unknown",
		"type":           "gather",
		"run_mode":       "single_provider",
		"goal":           "Do not reclaim unknown files.",
		"background":     "Preserve unknown files in incomplete run directories.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}
	outDir := filepath.Join(root, "runs")
	runDir := filepath.Join(outDir, "preserve-unknown")
	if err := os.MkdirAll(runDir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), "{}"); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "notes.txt"), "keep\n"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "preserve-unknown", Quiet: true, NoTriage: true})
	if err == nil || !strings.Contains(err.Error(), "already exists; use --force to replace") {
		t.Fatalf("expected existing-run validation error, got %v", err)
	}
	if !fsutil.FileExists(filepath.Join(runDir, "notes.txt")) {
		t.Fatalf("unknown file was removed")
	}
}

func TestRunResearchScrubsSecretsFromProviderArtifacts(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
printf 'provider-env:%s:%s:%s\n' "$ANTHROPIC_API_KEY" "$OPENAI_API_KEY" "$APP_JWT"
cat >/dev/null
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"C-001","claim":"Provider did not receive scrubbed secrets.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`)
	writeExecutable(t, filepath.Join(fakeBin, "codex"), `#!/bin/sh
case " $* " in
  *" --help "*) printf '%s\n' '--sandbox read-only workspace-write --disable --output-last-message'; exit 0 ;;
esac
printf 'provider-env:%s:%s:%s\n' "$ANTHROPIC_API_KEY" "$OPENAI_API_KEY" "$APP_JWT"
cat >/dev/null
exit 2
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	secrets := []string{"anthropic-secret-smoke", "openai-secret-smoke", "jwt-secret-smoke"}
	t.Setenv("ANTHROPIC_API_KEY", secrets[0])
	t.Setenv("OPENAI_API_KEY", secrets[1])
	t.Setenv("APP_JWT", secrets[2])

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "secret-smoke",
		"type":           "gather",
		"goal":           "Gather a fact.",
		"background":     "Secret leak smoke test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "secret-smoke", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatalf("RunResearch returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "secret-smoke")
	err = filepath.WalkDir(runDir, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		for _, secret := range secrets {
			if bytes.Contains(data, []byte(secret)) {
				t.Fatalf("secret %q leaked into %s", secret, path)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestRunResearchSingleProviderSuccessSkipsJudgeAndWinner(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf 'claude fake\n'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
cat >/dev/null
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"R-001","claim":"Single provider claim.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "single-provider-success",
		"type":           "gather",
		"run_mode":       "single_provider",
		"goal":           "Gather a baseline fact.",
		"background":     "Single-provider smoke test.",
		"facet": map[string]any{
			"id":      "code-review",
			"kind":    "generic",
			"focus":   "Find actionable defects.",
			"include": []any{"correctness"},
			"exclude": []any{"style-only"},
		},
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory", "repo_layout": "off"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "single-provider-success", Quiet: true})
	if err != nil {
		t.Fatalf("RunResearch returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "single-provider-success")
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["decision_kind"] != "single_provider_result" || decisionDoc["run_mode"] != "single_provider" {
		t.Fatalf("decision = %#v", decisionDoc)
	}
	if decisionDoc["canonical_winner"] != nil || decisionDoc["single_provider"] != "claude" {
		t.Fatalf("single-provider decision should not have winner: %#v", decisionDoc)
	}
	if decisionDoc["judge_ran"] != false || decisionDoc["judge_attempted"] != false || decisionDoc["judge_completed"] != false {
		t.Fatalf("single-provider decision should not run judge: %#v", decisionDoc)
	}
	if _, statErr := os.Stat(filepath.Join(runDir, "judge")); !os.IsNotExist(statErr) {
		t.Fatalf("judge artifacts should not exist: %v", statErr)
	}
	if _, statErr := os.Stat(filepath.Join(runDir, "triage")); !os.IsNotExist(statErr) {
		t.Fatalf("single-provider code-review run should not auto-triage: %v", statErr)
	}

	reportText := string(mustReadFile(t, filepath.Join(runDir, "report.md")))
	for _, want := range []string{"Run mode: `single_provider`", "Result: single-provider result", "Single provider: `claude`"} {
		if !strings.Contains(reportText, want) {
			t.Fatalf("report missing %q:\n%s", want, reportText)
		}
	}
	if strings.Contains(reportText, "Winner:") || strings.Contains(reportText, "Partial result:") {
		t.Fatalf("single-provider report used pairwise outcome wording:\n%s", reportText)
	}
	promptText := string(mustReadFile(t, filepath.Join(runDir, "providers", "claude", "prompt.txt")))
	if !strings.Contains(promptText, "standalone single-provider run") || strings.Contains(promptText, "deduplicate your output against a peer") || strings.Contains(promptText, "A separate judge will") {
		t.Fatalf("single-provider prompt should avoid pairwise comparison wording:\n%s", promptText)
	}
	manifest := readTestJSON(t, filepath.Join(runDir, "manifest.json"))
	if manifest["run_mode"] != "single_provider" || manifest["single_provider"] != "claude" {
		t.Fatalf("manifest single-provider fields = %#v", manifest)
	}
}

func TestRunResearchSingleProviderFailureSkipsJudge(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf 'claude fake\n'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
cat >/dev/null
printf '%s\n' 'provider failed intentionally' >&2
exit 7
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "single-provider-failure",
		"type":           "gather",
		"run_mode":       "single_provider",
		"goal":           "Gather a baseline fact.",
		"background":     "Single-provider failure smoke test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory", "repo_layout": "off"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "single-provider-failure", Quiet: true, NoTriage: true})
	if err == nil {
		t.Fatalf("expected RunResearch to fail\nstdout:\n%s\nstderr:\n%s", out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "single-provider-failure")
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["decision_kind"] != "single_provider_failed" || decisionDoc["stalled_at"] != "providers" {
		t.Fatalf("decision = %#v", decisionDoc)
	}
	if decisionDoc["canonical_winner"] != nil || decisionDoc["single_provider"] != "claude" {
		t.Fatalf("single-provider failure should not have winner: %#v", decisionDoc)
	}
	if decisionDoc["judge_ran"] != false || decisionDoc["judge_attempted"] != false || decisionDoc["judge_completed"] != false {
		t.Fatalf("single-provider failure should not run judge: %#v", decisionDoc)
	}
	if _, statErr := os.Stat(filepath.Join(runDir, "judge")); !os.IsNotExist(statErr) {
		t.Fatalf("judge artifacts should not exist: %v", statErr)
	}
	reportText := string(mustReadFile(t, filepath.Join(runDir, "report.md")))
	if !strings.Contains(reportText, "Result: single-provider failed") || strings.Contains(reportText, "Winner:") {
		t.Fatalf("single-provider failure report used wrong wording:\n%s", reportText)
	}
}

func TestRunResearchDuplicateProvidersUseSeparateArtifactsAndIdenticalPrompts(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf 'claude fake\n'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
prompt=$(cat)
case "$prompt" in
  *"deduplication and conflict-flagging judge"*)
    cat <<'JSON'
<final_json>{"merged_claims":[{"claim":"Merged duplicate claim","sources":["A","B"],"evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns_union":[]}</final_json>
JSON
    ;;
  *)
    cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"R-001","claim":"Duplicate provider claim.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
    ;;
esac
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "duplicate-research",
		"type":           "gather",
		"goal":           "Gather a duplicate fact.",
		"background":     "Duplicate prompt smoke test.",
		"providers": []map[string]any{
			{"id": "claude-a", "backend": "claude", "model": "claude-test", "scope": "codebase", "effort": "high"},
			{"id": "claude-b", "backend": "claude", "model": "claude-test", "scope": "codebase", "effort": "high"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory", "repo_layout": "off"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "duplicate-research", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatalf("RunResearch returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "duplicate-research")
	promptA := mustReadFile(t, filepath.Join(runDir, "providers", "claude-a", "prompt.txt"))
	promptB := mustReadFile(t, filepath.Join(runDir, "providers", "claude-b", "prompt.txt"))
	if !bytes.Equal(promptA, promptB) {
		t.Fatalf("duplicate provider prompts differ")
	}
	for _, id := range []string{"claude-a", "claude-b"} {
		if _, err := os.Stat(filepath.Join(runDir, "providers", id, "final.json")); err != nil {
			t.Fatalf("%s final.json missing: %v", id, err)
		}
		status := readTestJSON(t, filepath.Join(runDir, "providers", id, "status.json"))
		if status["status"] != "ok" {
			t.Fatalf("%s status = %#v", id, status)
		}
	}
	reportText := string(mustReadFile(t, filepath.Join(runDir, "report.md")))
	if !strings.Contains(reportText, "Same-model duplicate run: both workers used claude/claude-test with the same scope") {
		t.Fatalf("report missing duplicate caveat:\n%s", reportText)
	}
}

func TestRunResearchDuplicateProviderFailureIsolation(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	onceDir := filepath.Join(root, "once")
	if err := os.MkdirAll(onceDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf 'claude fake\n'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
cat >/dev/null
if mkdir "$BAKEOFF_FAIL_ONCE_DIR/claimed" 2>/dev/null; then
  printf '%s\n' 'rate_limit_error: retry later' >&2
  exit 9
fi
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"R-001","claim":"Surviving duplicate claim.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("BAKEOFF_FAIL_ONCE_DIR", onceDir)

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "duplicate-failure",
		"type":           "gather",
		"goal":           "Gather a duplicate fact.",
		"background":     "One duplicate provider fails.",
		"providers": []map[string]any{
			{"id": "claude-a", "backend": "claude", "model": "claude-test", "scope": "codebase", "effort": "high"},
			{"id": "claude-b", "backend": "claude", "model": "claude-test", "scope": "codebase", "effort": "high"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory", "repo_layout": "off"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "duplicate-failure", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatalf("RunResearch returned error for single-provider survivor: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "duplicate-failure")
	failures := 0
	successes := 0
	for _, id := range []string{"claude-a", "claude-b"} {
		status := readTestJSON(t, filepath.Join(runDir, "providers", id, "status.json"))
		switch status["status"] {
		case "ok":
			successes++
			if _, err := os.Stat(filepath.Join(runDir, "providers", id, "final.json")); err != nil {
				t.Fatalf("%s final.json missing: %v", id, err)
			}
		case "exit_error":
			failures++
			if status["failure_kind"] != "rate_or_quota_limited" {
				t.Fatalf("%s failure kind = %#v", id, status)
			}
			stderr := string(mustReadFile(t, filepath.Join(runDir, "providers", id, "stderr.txt")))
			if !strings.Contains(stderr, "rate_limit_error") {
				t.Fatalf("%s stderr missing rate limit marker: %q", id, stderr)
			}
		default:
			t.Fatalf("%s unexpected status = %#v", id, status)
		}
	}
	if failures != 1 || successes != 1 {
		t.Fatalf("failures=%d successes=%d", failures, successes)
	}
}

func TestRunResearchOversizedBackgroundTrimsBeforeProviderLaunch(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(root, "provider-invoked")
	fakeScript := `#!/bin/sh
case " $* " in
  *" --version "*) printf '%s fake\n' "$(basename "$0")"; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools --sandbox workspace-write --disable --output-last-message'; exit 0 ;;
esac
printf 'invoked:%s\n' "$(basename "$0")" >> "$BAKEOFF_SENTINEL"
prompt=$(cat)
case "$prompt" in
  *"deduplication and conflict-flagging judge"*)
    cat <<'JSON'
<final_json>{"merged_claims":[],"conflicts":[],"unknowns_union":[]}</final_json>
JSON
    exit 0
    ;;
esac
cat <<'JSON'
<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`
	writeExecutable(t, filepath.Join(fakeBin, "claude"), fakeScript)
	writeExecutable(t, filepath.Join(fakeBin, "codex"), fakeScript)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("BAKEOFF_SENTINEL", sentinel)

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "oversized-prompt",
		"type":           "gather",
		"goal":           "Gather a fact.",
		"background":     strings.Repeat("x", runner.MaxPromptBytes+1),
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "oversized-prompt", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatalf("RunResearch returned error after trimming oversized background: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	sentinelText := string(mustReadFile(t, sentinel))
	if !strings.Contains(sentinelText, "invoked:claude") || !strings.Contains(sentinelText, "invoked:codex") {
		t.Fatalf("providers were not launched after trim: %q", sentinelText)
	}

	runDir := filepath.Join(outDir, "oversized-prompt")
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	trim, _ := decisionDoc["prompt_trim"].(map[string]any)
	if !strings.Contains(fmt.Sprint(trim), "worker:claude") || !strings.Contains(fmt.Sprint(trim), "context") {
		t.Fatalf("decision missing prompt trim record: %#v", decisionDoc)
	}
	if !strings.Contains(errOut.String(), "prompt_trim: prompt=worker:claude dropped=context") {
		t.Fatalf("stderr missing prompt trim notice:\n%s", errOut.String())
	}
	promptText := string(mustReadFile(t, filepath.Join(runDir, "providers", "claude", "prompt.txt")))
	if !strings.Contains(promptText, "<context>\n</context>") || strings.Contains(promptText, strings.Repeat("x", 64)) {
		t.Fatalf("provider prompt was not trimmed:\n%s", promptText[:min(len(promptText), 200)])
	}
}

func TestRunResearchOversizedRequiredPromptStillRecordsTrimAndDoesNotLaunchProvider(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(root, "provider-invoked")
	fakeScript := `#!/bin/sh
case " $* " in
  *" --version "*) printf '%s fake\n' "$(basename "$0")"; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools --sandbox workspace-write --disable --output-last-message'; exit 0 ;;
esac
printf 'invoked:%s\n' "$(basename "$0")" >> "$BAKEOFF_SENTINEL"
cat >/dev/null
cat <<'JSON'
<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`
	writeExecutable(t, filepath.Join(fakeBin, "claude"), fakeScript)
	writeExecutable(t, filepath.Join(fakeBin, "codex"), fakeScript)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("BAKEOFF_SENTINEL", sentinel)

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "oversized-required-prompt",
		"type":           "gather",
		"goal":           strings.Repeat("g", runner.MaxPromptBytes+1),
		"background":     strings.Repeat("x", runner.MaxPromptBytes+1),
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "oversized-required-prompt", Quiet: true, NoTriage: true})
	if err == nil {
		t.Fatalf("expected RunResearch to fail for oversized required prompt\nstdout:\n%s\nstderr:\n%s", out.String(), errOut.String())
	}
	if _, statErr := os.Stat(sentinel); !os.IsNotExist(statErr) {
		t.Fatalf("provider binary was launched; sentinel stat err = %v", statErr)
	}

	runDir := filepath.Join(outDir, "oversized-required-prompt")
	status := readTestJSON(t, filepath.Join(runDir, "providers", "claude", "status.json"))
	if status["failure_kind"] != "prompt_too_large" {
		t.Fatalf("provider status failure_kind = %#v", status)
	}
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["stalled_at"] != "providers" {
		t.Fatalf("decision stalled_at = %#v", decisionDoc["stalled_at"])
	}
	if !strings.Contains(fmt.Sprint(decisionDoc["prompt_trim"]), "worker:claude") {
		t.Fatalf("decision missing prompt trim record: %#v", decisionDoc)
	}
	reportText := string(mustReadFile(t, filepath.Join(runDir, "report.md")))
	if !strings.Contains(reportText, "failure kind: prompt_too_large") {
		t.Fatalf("report missing failure kind:\n%s", reportText)
	}
}

func TestRunResearchClassifiedJudgeFailureKeepsJudgeErrorKind(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	fakeScript := `#!/bin/sh
case " $* " in
  *" --version "*) printf '%s fake\n' "$(basename "$0")"; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools --sandbox workspace-write --disable --output-last-message'; exit 0 ;;
esac
prompt=$(cat)
case "$prompt" in
  *"deduplication and conflict-flagging judge"*)
    printf '%s\n' 'rate_limit_error: retry later' >&2
    exit 9
    ;;
esac
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"C-001","claim":"Provider claim.","evidence":["fake:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`
	writeExecutable(t, filepath.Join(fakeBin, "claude"), fakeScript)
	writeExecutable(t, filepath.Join(fakeBin, "codex"), fakeScript)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "judge-rate-limit",
		"type":           "gather",
		"goal":           "Gather a fact.",
		"background":     "Judge failure classification smoke.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "advisory"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "judge-rate-limit", Quiet: true, NoTriage: true})
	if err == nil {
		t.Fatalf("expected RunResearch to fail for judge error\nstdout:\n%s\nstderr:\n%s", out.String(), errOut.String())
	}

	runDir := filepath.Join(outDir, "judge-rate-limit")
	judgeStatus := readTestJSON(t, filepath.Join(runDir, "judge", "status.json"))
	if judgeStatus["failure_kind"] != "rate_or_quota_limited" || judgeStatus["judge_error_kind"] != "rate_or_quota_limited" {
		t.Fatalf("judge status missing classified kinds: %#v", judgeStatus)
	}
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["judge_error_kind"] != "rate_or_quota_limited" {
		t.Fatalf("decision judge_error_kind = %#v", decisionDoc["judge_error_kind"])
	}
	if decisionDoc["stalled_at"] != "judge" {
		t.Fatalf("decision stalled_at = %#v", decisionDoc["stalled_at"])
	}
}

func TestRunResearchJudgeOnlySucceedsWithCopiedProviderArtifacts(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'claude fake\n'
  exit 0
fi
cat >/dev/null
cat <<'JSON'
<final_json>{"merged_claims":[{"claim":"Merged claim","sources":["A","B"],"evidence":["judge:1"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns_union":[]}</final_json>
JSON
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	outDir := filepath.Join(root, "runs")
	sourceRun := filepath.Join(outDir, "source")
	writeJudgeOnlySourceRun(t, sourceRun, "gather", "exit_error")
	before := mustReadFile(t, filepath.Join(sourceRun, "judge", "status.json"))

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearchJudgeOnly(context.Background(), factory, &ResearchJudgeOnlyOptions{
		SourceRunDir: sourceRun,
		SourceRunID:  "source",
		Out:          outDir,
		RunID:        "retry",
		Quiet:        true,
		NoTriage:     true,
	})
	if err != nil {
		t.Fatalf("RunResearchJudgeOnly returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "retry")
	decision := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decision["decision_kind"] != "structured_union" || decision["judge_completed"] != true {
		t.Fatalf("decision = %#v", decision)
	}
	meta := readTestJSON(t, filepath.Join(runDir, "meta.json"))
	if meta["source_run_id"] != "source" || meta["source_run_dir"] != sourceRun || meta["rerun_mode"] != "judge_only" {
		t.Fatalf("meta = %#v", meta)
	}
	if _, err := os.Stat(filepath.Join(runDir, "providers", "claude", "final.json")); err != nil {
		t.Fatalf("copied provider final missing: %v", err)
	}
	manifest := readTestJSON(t, filepath.Join(runDir, "manifest.json"))
	if manifest["source_run_id"] != "source" || manifest["rerun_mode"] != "judge_only" {
		t.Fatalf("manifest rerun fields = %#v", manifest)
	}
	telemetry := manifest["telemetry"].(map[string]any)
	if telemetry["source_run_id"] != "source" || telemetry["rerun_mode"] != "judge_only" {
		t.Fatalf("telemetry rerun fields = %#v", telemetry)
	}
	fingerprints := manifest["artifact_fingerprints"].(map[string]any)
	for _, relative := range []string{"providers/claude/status.json", "providers/codex/final.json", "judge/status.json", "judge/result.json"} {
		if _, ok := fingerprints[relative]; !ok {
			t.Fatalf("missing fingerprint for %s in %#v", relative, fingerprints)
		}
	}
	if got := mustReadFile(t, filepath.Join(sourceRun, "judge", "status.json")); !bytes.Equal(got, before) {
		t.Fatalf("source run judge status changed")
	}
	latest, err := os.Readlink(filepath.Join(outDir, "latest"))
	if err == nil && latest != "retry" {
		t.Fatalf("latest symlink = %q", latest)
	}
	if err != nil {
		if data := strings.TrimSpace(string(mustReadFile(t, filepath.Join(outDir, "latest")))); data != "retry" {
			t.Fatalf("latest file = %q", data)
		}
	}
	if !strings.Contains(out.String(), "judge-only rerun reuses provider artifacts from source") {
		t.Fatalf("missing reuse note:\n%s", out.String())
	}
}

func TestRunResearchJudgeOnlyMissingProviderArtifactDoesNotCreateRetryRun(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	sourceRun := filepath.Join(outDir, "source")
	writeJudgeOnlySourceRun(t, sourceRun, "gather", "exit_error")
	if err := os.Remove(filepath.Join(sourceRun, "providers", "codex", "final.json")); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearchJudgeOnly(context.Background(), factory, &ResearchJudgeOnlyOptions{
		SourceRunDir: sourceRun,
		SourceRunID:  "source",
		Out:          outDir,
		RunID:        "retry",
		Quiet:        true,
		NoTriage:     true,
	})
	if err == nil || !strings.Contains(err.Error(), "provider codex final.json is required") {
		t.Fatalf("expected missing provider artifact error, got %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	if _, statErr := os.Stat(filepath.Join(outDir, "retry")); !os.IsNotExist(statErr) {
		t.Fatalf("retry run was created before preflight completed: %v", statErr)
	}
	if _, statErr := os.Lstat(filepath.Join(outDir, "latest")); !os.IsNotExist(statErr) {
		t.Fatalf("latest was updated before preflight completed: %v", statErr)
	}
}

func TestRunResearchJudgeOnlyReplayContextFailurePreservesLatest(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	if err := os.MkdirAll(filepath.Join(outDir, "prior"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := ledger.UpdateLatest(outDir, "prior"); err != nil {
		t.Fatal(err)
	}
	sourceRun := filepath.Join(outDir, "source")
	writeJudgeOnlySourceRun(t, sourceRun, "gather", "exit_error")
	if err := workorder.WriteTextAtomic(filepath.Join(sourceRun, "review-context.md"), "partial context\n"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearchJudgeOnly(context.Background(), factory, &ResearchJudgeOnlyOptions{
		SourceRunDir: sourceRun,
		SourceRunID:  "source",
		Out:          outDir,
		RunID:        "retry",
		Quiet:        true,
		NoTriage:     true,
	})
	if err == nil || !strings.Contains(err.Error(), "partial review-context artifact set") {
		t.Fatalf("expected replay context error, got %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	if got := latestValue(t, outDir); got != "prior" {
		t.Fatalf("latest = %q, want prior", got)
	}
}

func TestCopyProviderArtifactDirsPreflightsBeforeMutation(t *testing.T) {
	root := t.TempDir()
	sourceRun := filepath.Join(root, "source")
	targetRun := filepath.Join(root, "target")
	wo := writeJudgeOnlySourceRun(t, sourceRun, "gather", "exit_error")
	if err := os.Remove(filepath.Join(sourceRun, "providers", "codex", "status.json")); err != nil {
		t.Fatal(err)
	}

	err := copyProviderArtifactDirs(wo, sourceRun, targetRun)
	if err == nil || !strings.Contains(err.Error(), "provider codex status.json is required") {
		t.Fatalf("expected missing status error, got %v", err)
	}
	if _, statErr := os.Stat(filepath.Join(targetRun, "providers", "claude")); !os.IsNotExist(statErr) {
		t.Fatalf("copied first provider before preflight completed: %v", statErr)
	}
}

func TestCopyFilePreservesBinaryBytes(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source.bin")
	target := filepath.Join(root, "nested", "target.bin")
	want := []byte{0x00, 0xff, 0x01, 0xfe}
	if err := os.WriteFile(source, want, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := copyFile(source, target); err != nil {
		t.Fatal(err)
	}
	if got := mustReadFile(t, target); !bytes.Equal(got, want) {
		t.Fatalf("copied bytes = %v, want %v", got, want)
	}
}

func TestRunResearchJudgeOnlyRunsAutoTriageForCodeReview(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'claude fake\n'
  exit 0
fi
prompt=$(cat)
case "$prompt" in
  *source_findings*)
    cat <<'JSON'
<final_json>{"schema_version":1,"status":"complete","summary":"No actionable issues.","items":[],"unknowns":[]}</final_json>
JSON
    ;;
  *)
    cat <<'JSON'
<final_json>{"merged_claims":[{"claim":"Merged review finding","sources":["A","B"],"evidence":["file.go:12"],"severity":"medium","confidence":"high"}],"conflicts":[],"unknowns_union":[]}</final_json>
JSON
    ;;
esac
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	outDir := filepath.Join(root, "runs")
	sourceRun := filepath.Join(outDir, "source")
	writeJudgeOnlySourceRun(t, sourceRun, "gather", "exit_error")
	addCodeReviewFacet(t, sourceRun)

	var out, errOut bytes.Buffer
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearchJudgeOnly(context.Background(), factory, &ResearchJudgeOnlyOptions{
		SourceRunDir: sourceRun,
		SourceRunID:  "source",
		Out:          outDir,
		RunID:        "retry-code-review",
		Quiet:        true,
	})
	if err != nil {
		t.Fatalf("RunResearchJudgeOnly returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "retry-code-review")
	if _, err := os.Stat(filepath.Join(runDir, "triage", "final.json")); err != nil {
		t.Fatalf("auto-triage final missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(runDir, "triage", "triage.md")); err != nil {
		t.Fatalf("auto-triage markdown missing: %v", err)
	}
	manifest := readTestJSON(t, filepath.Join(runDir, "manifest.json"))
	triageSummary, _ := manifest["triage"].(map[string]any)
	if triageSummary["state"] != "yes" {
		t.Fatalf("triage manifest summary = %#v", triageSummary)
	}
	if !strings.Contains(out.String(), "auto-triage starting") {
		t.Fatalf("missing auto-triage note:\n%s", out.String())
	}
}

func TestLoadResearchWorkerResultsFromArtifactsValidation(t *testing.T) {
	cases := []struct {
		name     string
		mutate   func(string)
		wantText string
	}{
		{
			name: "missing final",
			mutate: func(runDir string) {
				if err := os.Remove(filepath.Join(runDir, "providers", "codex", "final.json")); err != nil {
					t.Fatal(err)
				}
			},
			wantText: "final.json",
		},
		{
			name: "malformed final",
			mutate: func(runDir string) {
				if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "providers", "codex", "final.json"), map[string]any{"status": "complete"}); err != nil {
					t.Fatal(err)
				}
			},
			wantText: "claims is required",
		},
		{
			name: "failed status",
			mutate: func(runDir string) {
				if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "providers", "codex", "status.json"), map[string]any{"status": "exit_error"}); err != nil {
					t.Fatal(err)
				}
			},
			wantText: "not successful",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			runDir := filepath.Join(t.TempDir(), "run")
			wo := writeJudgeOnlySourceRun(t, runDir, "gather", "exit_error")
			tc.mutate(runDir)
			_, err := loadResearchWorkerResultsFromArtifacts(wo, runDir)
			if err == nil || !strings.Contains(err.Error(), tc.wantText) {
				t.Fatalf("expected %q error, got %v", tc.wantText, err)
			}
		})
	}
}

func TestRunResearchJudgeOnlyRejectsNoFailedJudgeAttempt(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	sourceRun := filepath.Join(outDir, "source")
	writeJudgeOnlySourceRun(t, sourceRun, "gather", "ok")
	if err := workorder.WriteJSONAtomic(filepath.Join(sourceRun, "decision.json"), map[string]any{
		"mode":            "gather",
		"decision_kind":   "structured_union",
		"judge_ran":       true,
		"judge_attempted": true,
		"judge_completed": true,
	}); err != nil {
		t.Fatal(err)
	}

	factory := researchTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}
	err := RunResearchJudgeOnly(context.Background(), factory, &ResearchJudgeOnlyOptions{
		SourceRunDir: sourceRun,
		SourceRunID:  "source",
		Out:          outDir,
		RunID:        "retry",
		Quiet:        true,
		NoTriage:     true,
	})
	if err == nil || !strings.Contains(err.Error(), "judge already completed") {
		t.Fatalf("expected successful judge rejection, got %v", err)
	}
}

func TestFinalizeResearchRunWrapsDecisionIncomplete(t *testing.T) {
	root := t.TempDir()
	runDir := filepath.Join(root, "runs", "incomplete")
	rawWorkOrder := map[string]any{
		"schema_version": 1,
		"id":             "incomplete",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), rawWorkOrder); err != nil {
		t.Fatal(err)
	}
	wo, err := workorder.Load(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		t.Fatal(err)
	}
	workerResults := map[string]map[string]any{
		"claude": {"status": "ok", "final_json": map[string]any{"claims": []any{}, "unknowns": []any{}}},
		"codex":  {"status": "ok", "final_json": map[string]any{"claims": []any{}, "unknowns": []any{}}},
	}
	decisionDoc := map[string]any{
		"mode":              "gather",
		"decision_kind":     "provider_union_only",
		"judge_ran":         true,
		"judge_attempted":   true,
		"judge_completed":   false,
		"provider_statuses": map[string]any{"claude": map[string]any{"status": "ok"}, "codex": map[string]any{"status": "ok"}},
		"caveats":           []any{"gather judge failed with exit_error"},
	}

	factory := researchTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}
	err = finalizeResearchRun(context.Background(), factory, researchFinalizeOptions{
		WorkOrder:      wo,
		Out:            filepath.Dir(runDir),
		RunID:          "incomplete",
		RunDir:         runDir,
		StartedAt:      "2026-05-19T00:00:00Z",
		WorkerResults:  workerResults,
		DecisionDoc:    decisionDoc,
		JudgeResults:   map[string]map[string]any{"pass1": {}},
		ExitCode:       4,
		NoTriage:       true,
		LookupProvider: factory.LookupProvider,
	})
	var incomplete *apperror.DecisionIncompleteError
	if !errors.As(err, &incomplete) {
		t.Fatalf("expected DecisionIncompleteError through wrapping, got %T %v", err, err)
	}
}

func TestResearchResultLineSummarizesGatherAndWinnerModes(t *testing.T) {
	gather := researchResultLine(&workorder.WorkOrder{Type: "gather"}, map[string]any{
		"mode":          "gather",
		"decision_kind": "structured_union",
		"judge_ran":     true,
	}, "")
	if gather != "structured_union, judge=yes" {
		t.Fatalf("gather result line = %q", gather)
	}
	compare := researchResultLine(&workorder.WorkOrder{Type: "compare"}, map[string]any{
		"decision_kind":    "pick_winner",
		"canonical_winner": "claude",
		"spine_tiebreak":   "most_corroborated",
	}, "")
	if compare != "winner=claude, spine_tiebreak=most_corroborated" {
		t.Fatalf("compare result line = %q", compare)
	}
	consensus := researchResultLine(&workorder.WorkOrder{Type: "compare"}, map[string]any{
		"decision_kind": "consensus",
		"judge_ran":     true,
	}, "")
	if consensus != "consensus (both providers agree)" {
		t.Fatalf("consensus result line = %q", consensus)
	}
	unresolved := researchResultLine(&workorder.WorkOrder{Type: "compare"}, map[string]any{
		"decision_kind": "tie",
		"judge_ran":     true,
	}, "")
	if unresolved != "no winner (unresolved disagreement, spine_tiebreak=judge)" {
		t.Fatalf("unresolved result line = %q", unresolved)
	}
}

func writeJudgeOnlySourceRun(t *testing.T, runDir string, mode string, judgeStatus string) *workorder.WorkOrder {
	t.Helper()
	workOrder := map[string]any{
		"schema_version": 1,
		"id":             "judge-only-source",
		"type":           mode,
		"goal":           "Gather facts.",
		"background":     "Judge-only retry test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), workOrder); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"claude", "codex"} {
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "providers", id, "status.json"), map[string]any{
			"status":            "ok",
			"wall_seconds":      1.0,
			"output_bytes":      120,
			"final_json_source": "stdout",
			"scope_enforcement": map[string]any{"requested_scope": "codebase", "effective_scope": "codebase", "enforcement_level": "best_effort"},
		}); err != nil {
			t.Fatal(err)
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "providers", id, "final.json"), map[string]any{
			"status": "complete",
			"claims": []any{
				map[string]any{"id": "C-001", "claim": id + " claim", "evidence": []any{"evidence:1"}, "severity": "medium", "confidence": "high"},
			},
			"conflicts":               []any{},
			"unknowns":                []any{id + " unknown"},
			"recommended_next_checks": []any{},
		}); err != nil {
			t.Fatal(err)
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, "providers", id, "stdout.txt"), "stdout\n"); err != nil {
			t.Fatal(err)
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, "providers", id, "stderr.txt"), "stderr\n"); err != nil {
			t.Fatal(err)
		}
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), map[string]any{
		"mode":              mode,
		"decision_kind":     "provider_union_only",
		"judge_ran":         true,
		"judge_attempted":   true,
		"judge_completed":   false,
		"provider_statuses": map[string]any{},
		"caveats":           []any{"gather judge failed with exit_error"},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": judgeStatus, "exit_code": 1}); err != nil {
		t.Fatal(err)
	}
	wo, err := workorder.Load(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		t.Fatal(err)
	}
	return wo
}

func addCodeReviewFacet(t *testing.T, runDir string) {
	t.Helper()
	workOrderPath := filepath.Join(runDir, "work-order.json")
	raw := readTestJSON(t, workOrderPath)
	raw["facet"] = map[string]any{
		"id":      "code-review",
		"kind":    "generic",
		"focus":   "Find actionable defects introduced or exposed by the change.",
		"include": []any{"correctness bugs and edge cases"},
		"exclude": []any{"style-only preferences"},
	}
	if err := workorder.WriteJSONAtomic(workOrderPath, raw); err != nil {
		t.Fatal(err)
	}
}

func readTestJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data := mustReadFile(t, path)
	var obj map[string]any
	if err := json.Unmarshal(data, &obj); err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return obj
}

func mustReadFile(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func latestValue(t *testing.T, outDir string) string {
	t.Helper()
	path := filepath.Join(outDir, "latest")
	if link, err := os.Readlink(path); err == nil {
		return link
	}
	return strings.TrimSpace(string(mustReadFile(t, path)))
}

func writeExecutable(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o755); err != nil {
		t.Fatal(err)
	}
}
