package summary

import (
	"encoding/json"
	"os"
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

func TestProviderStatusSummaryCompactsSalvagedAsWarn(t *testing.T) {
	got := ProviderStatusSummary(map[string]any{"status": "salvaged"})
	if got.Status != "warn" || got.RawStatus != "salvaged" {
		t.Fatalf("summary = %#v", got)
	}
}

func TestProviderStatusSummaryCompactsFormatRetryAsOK(t *testing.T) {
	got := ProviderStatusSummary(map[string]any{"status": "ok_after_format_retry"})
	if got.Status != "ok" || got.RawStatus != "ok_after_format_retry" {
		t.Fatalf("summary = %#v", got)
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

func TestBuildResearchRecommendsJudgeOnlyForResearchExit4WithSucceededProvidersAndFailedJudge(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("gather", "claude", "codex"))
	writeSummaryJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "exit_error"})

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "gather",
		"decision_kind":   "provider_union_only",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
			"codex":  map[string]any{"status": "ok_after_format_retry"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff rerun run-1 --judge-only" {
		t.Fatalf("next = %q", got.Next)
	}
	if len(got.NextAlternatives) != 1 || got.NextAlternatives[0] != "bakeoff rerun run-1" {
		t.Fatalf("next alternatives = %#v", got.NextAlternatives)
	}
}

func TestBuildResearchRecommendsJudgeOnlyWhenJudgeStatusMissingAfterAttempt(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("gather", "claude", "codex"))

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "gather",
		"decision_kind":   "provider_union_only",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
			"codex":  map[string]any{"status": "ok"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff rerun run-1 --judge-only" {
		t.Fatalf("next = %q", got.Next)
	}
}

func TestBuildResearchSuppressesJudgeOnlyWhenAProviderFailed(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("gather", "claude", "codex"))
	writeSummaryJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "exit_error"})
	writeSummaryFile(t, filepath.Join(runDir, "report.md"), "prose says bakeoff rerun run-1 --judge-only\n")

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "gather",
		"decision_kind":   "provider_union_only",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
			"codex":  map[string]any{"status": "schema_error"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff show run-1" {
		t.Fatalf("next = %q", got.Next)
	}
	if len(got.NextAlternatives) != 0 {
		t.Fatalf("next alternatives = %#v", got.NextAlternatives)
	}
}

func TestBuildResearchSuppressesJudgeOnlyForBuildMode(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("build", "claude", "codex"))
	writeSummaryJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "exit_error"})

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "build",
		"decision_kind":   "judge_failed",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
			"codex":  map[string]any{"status": "ok"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff show run-1" {
		t.Fatalf("next = %q", got.Next)
	}
	if len(got.NextAlternatives) != 0 {
		t.Fatalf("next alternatives = %#v", got.NextAlternatives)
	}
}

func TestBuildResearchIgnoresReportMarkdownWhenStructuredJudgeSucceeded(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("gather", "claude", "codex"))
	writeSummaryJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "ok"})
	writeSummaryFile(t, filepath.Join(runDir, "report.md"), "prose says bakeoff rerun run-1 --judge-only\n")

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "gather",
		"decision_kind":   "provider_union_only",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
			"codex":  map[string]any{"status": "ok"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff show run-1" {
		t.Fatalf("next = %q", got.Next)
	}
	if len(got.NextAlternatives) != 0 {
		t.Fatalf("next alternatives = %#v", got.NextAlternatives)
	}
}

func TestBuildResearchRequiresAllDeclaredProvidersToSucceed(t *testing.T) {
	runDir := t.TempDir()
	writeSummaryJSON(t, filepath.Join(runDir, "work-order.json"), summaryWorkOrder("gather", "claude", "codex"))
	writeSummaryJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "exit_error"})

	got := BuildResearch(runDir, "run-1", "runs", map[string]any{
		"mode":            "gather",
		"decision_kind":   "provider_union_only",
		"judge_ran":       true,
		"judge_completed": false,
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok"},
		},
	}, nil, 4, false, nil)

	if got.Next != "bakeoff show run-1" {
		t.Fatalf("next = %q", got.Next)
	}
}

func summaryWorkOrder(mode string, providerIDs ...string) map[string]any {
	providers := make([]any, 0, len(providerIDs))
	for i, id := range providerIDs {
		backend := "claude"
		model := "sonnet"
		if i == 1 {
			backend = "codex"
			model = "gpt-5.5"
		}
		providers = append(providers, map[string]any{
			"id":      id,
			"backend": backend,
			"model":   model,
			"scope":   "codebase",
			"effort":  "high",
		})
	}
	out := map[string]any{
		"schema_version": 1,
		"id":             "summary-test",
		"type":           mode,
		"goal":           "test summary routing",
		"background":     "test",
		"providers":      providers,
		"judge": map[string]any{
			"backend": "gemini",
			"model":   "pro",
			"effort":  "high",
		},
		"budgets": map[string]any{
			"wall_clock_seconds":       60,
			"max_output_bytes":         1000,
			"heartbeat_seconds":        10,
			"output_cap_grace_seconds": 10,
			"max_output_overrun_bytes": 1000,
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
	}
	if mode == "build" {
		out["build"] = map[string]any{
			"base_ref":        "HEAD",
			"comparison_goal": "test",
			"verify": []any{map[string]any{
				"id":                 "test",
				"kind":               "gate",
				"argv":               []any{"true"},
				"wall_clock_seconds": 5,
				"max_output_bytes":   1000,
			}},
		}
	}
	return out
}

func writeSummaryJSON(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	writeSummaryFile(t, path, string(data))
}

func writeSummaryFile(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}
