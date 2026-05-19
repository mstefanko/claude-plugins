package researchcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
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
<final_json>{"status":"complete","claims":[{"id":"C-001","claim":"Provider did not receive scrubbed secrets.","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
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
<final_json>{"merged_claims":[{"claim":"Merged claim","sources":["A","B"],"evidence":["judge:1"],"confidence":"high"}],"conflicts":[],"unknowns_union":[]}</final_json>
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
				map[string]any{"id": "C-001", "claim": id + " claim", "evidence": []any{"evidence:1"}, "confidence": "high"},
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

func writeExecutable(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o755); err != nil {
		t.Fatal(err)
	}
}
