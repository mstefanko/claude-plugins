package researchcmd

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

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
