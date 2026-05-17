package manifest_test

import (
	"path/filepath"
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
