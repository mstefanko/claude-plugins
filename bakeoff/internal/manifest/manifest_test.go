package manifest_test

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/verify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestWriteRunManifestAndVerifyFingerprints(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "both_failed", "judge_ran": false, "provider_statuses": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "type": "gather", "resolved_models": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		t.Fatal(err)
	}
	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode != 0 || result.Fingerprints.CheckedCount != 4 {
		t.Fatalf("verify result = %#v", result)
	}

	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# changed\n"); err != nil {
		t.Fatal(err)
	}
	result = verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode == 0 || result.Fingerprints.Status != "failed" {
		t.Fatalf("expected fingerprint failure, got %#v", result)
	}
}

func TestWriteRunManifestFingerprintsProviderAndJudgeEvidence(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeText(t, filepath.Join(runDir, "providers", "claude", "prompt.txt"), "provider prompt\n")
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "status.json"), map[string]any{"status": "ok", "final_json_source": "last_message"})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "final.json"), map[string]any{"ok": true})
	writeText(t, filepath.Join(runDir, "providers", "claude", "last-message.txt"), "<final_json>{}\n")
	writeText(t, filepath.Join(runDir, "judge", "prompt.txt"), "judge prompt\n")
	writeJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "ok"})
	writeJSON(t, filepath.Join(runDir, "judge", "result.json"), map[string]any{"winner": "claude"})
	writeText(t, filepath.Join(runDir, "judge", "last-message.txt"), "<final_json>{}\n")

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	fingerprints := value["artifact_fingerprints"].(map[string]any)
	for _, relative := range []string{
		"providers/claude/prompt.txt",
		"providers/claude/status.json",
		"providers/claude/final.json",
		"providers/claude/last-message.txt",
		"judge/prompt.txt",
		"judge/status.json",
		"judge/result.json",
		"judge/last-message.txt",
	} {
		if _, ok := fingerprints[relative]; !ok {
			t.Fatalf("missing fingerprint for %s in %#v", relative, fingerprints)
		}
	}

	writeText(t, filepath.Join(runDir, "providers", "claude", "prompt.txt"), "changed provider prompt\n")
	writeJSON(t, filepath.Join(runDir, "judge", "result.json"), map[string]any{"winner": "codex"})
	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode == 0 || result.Fingerprints.Status != "failed" {
		t.Fatalf("expected provider/judge fingerprint failure, got %#v", result)
	}
	paths := []string{}
	for _, mismatch := range result.Fingerprints.Mismatches {
		paths = append(paths, mismatch["path"])
	}
	got := strings.Join(paths, ",")
	if !strings.Contains(got, "providers/claude/prompt.txt") || !strings.Contains(got, "judge/result.json") {
		t.Fatalf("missing expected mismatches: %#v", result.Fingerprints.Mismatches)
	}
}

func TestWriteRunManifestRejectsPartialReviewContextArtifacts(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeText(t, filepath.Join(runDir, "review-context.md"), "review\n")
	if _, err := manifest.WriteRunManifest(runDir); err == nil || !strings.Contains(err.Error(), "review context artifacts must be all-or-none") {
		t.Fatalf("expected partial review context error, got %v", err)
	}
}

func writeMinimalRun(t *testing.T, runDir string) {
	t.Helper()
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "both_failed", "judge_ran": false, "provider_statuses": map[string]any{}})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "type": "gather", "resolved_models": map[string]any{}})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")
}

func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}

func writeText(t *testing.T, path string, value string) {
	t.Helper()
	if err := workorder.WriteTextAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
