package summary

import (
	"path/filepath"
	"testing"
)

func TestProviderStatusSummaryCompactsFailure(t *testing.T) {
	got := ProviderStatusSummary(map[string]any{
		"status":       "schema_error",
		"wall_seconds": 1.25,
		"output_bytes": 10,
		"stdout_bytes": 8,
		"stderr_bytes": 2,
	})

	if got.Status != "failed" || got.RawStatus != "schema_error" {
		t.Fatalf("summary = %#v", got)
	}
	if got.WallSeconds != 1.25 || got.OutputBytes != 10 {
		t.Fatalf("summary metrics = %#v", got)
	}
}

func TestCommandStatus(t *testing.T) {
	if CommandStatus(0) != "ok" {
		t.Fatal("exit 0 should be ok")
	}
	if CommandStatus(3) != "judge_disagreement" {
		t.Fatal("exit 3 should be judge_disagreement")
	}
	if CommandStatus(4) != "decision_incomplete" {
		t.Fatal("exit 4 should be decision_incomplete")
	}
	if CommandStatus(1) != "failed" {
		t.Fatal("exit 1 should be failed")
	}
}

func TestBuildResearchIncludesStalledAt(t *testing.T) {
	runDir := t.TempDir()
	got := BuildResearch(runDir, "run-1", filepath.Dir(runDir), map[string]any{
		"decision_kind": "both_failed",
		"stalled_at":    "providers",
		"judge_ran":     false,
	}, map[string]map[string]any{}, 1, false, nil)
	if got.StalledAt != "providers" {
		t.Fatalf("stalled_at = %q", got.StalledAt)
	}
}
