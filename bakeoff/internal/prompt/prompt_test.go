package prompt

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestPromptFixturesMatchFrozenPythonOracle(t *testing.T) {
	for _, mode := range []string{"gather", "compare", "analyze"} {
		wo := fixtureWorkOrder(t, mode)
		for _, provider := range wo.Providers {
			got, err := BuildWorkerPrompt(wo, provider)
			if err != nil {
				t.Fatal(err)
			}
			assertFixture(t, filepath.Join("prompts", "worker-"+mode+"-"+provider.ID+".txt"), got)
		}
		judge, err := BuildJudgePrompt(wo, fixtureWorkerResult("A"), fixtureWorkerResult("B"), mode)
		if err != nil {
			t.Fatal(err)
		}
		assertFixture(t, filepath.Join("prompts", "judge-"+mode+".txt"), judge)
	}

	triagePayload := map[string]any{
		"schema_version": 1,
		"run_id":         "prompt-fixture",
		"facet": map[string]any{
			"id":      "code-review",
			"kind":    "generic",
			"focus":   "Find actionable defects introduced or exposed by the change.",
			"include": []any{"correctness bugs and edge cases"},
			"exclude": []any{"style-only preferences"},
		},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
		"source_findings": []any{
			map[string]any{
				"source_finding_id": "F-001",
				"source":            "report",
				"text":              "Fake merged claim",
				"citations":         []any{"src/fake.py:1"},
			},
		},
		"citation_checks": []any{},
		"report_md":       "# Report\n\nFake merged claim.",
		"artifacts":       map[string]any{},
	}
	triage, err := BuildTriagePrompt(triagePayload, workorder.Budgets{WallClockSeconds: 3, MaxOutputBytes: 20000, HeartbeatSeconds: 0, OutputCapGraceSeconds: 10, MaxOutputOverrunBytes: 20000})
	if err != nil {
		t.Fatal(err)
	}
	assertFixture(t, filepath.Join("prompts", "triage.txt"), triage)
}

func fixtureWorkOrder(t *testing.T, mode string) *workorder.WorkOrder {
	t.Helper()
	secondScope := "mixed"
	if mode == "gather" {
		secondScope = "web"
	}
	data := map[string]any{
		"schema_version": 1,
		"id":             mode + "-prompt-fixture",
		"type":           mode,
		"goal":           "Document the prompt contract.",
		"background":     "Stable prompt fixture context.",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "fake-codex", "scope": secondScope},
		},
		"judge":   map[string]any{"backend": "claude", "model": "fake-judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
		"facet": map[string]any{
			"id":      "code-review",
			"kind":    "generic",
			"focus":   "Find actionable defects introduced or exposed by the change.",
			"include": []any{"correctness bugs and edge cases"},
			"exclude": []any{"style-only preferences"},
		},
	}
	wo, err := workorder.Validate(data)
	if err != nil {
		t.Fatal(err)
	}
	return wo
}

func fixtureWorkerResult(label string) map[string]any {
	return map[string]any{
		"status":                  "complete",
		"position":                label + " position",
		"claims":                  []any{map[string]any{"id": "R-001", "claim": label + " claim", "evidence": []any{"fake:1"}, "confidence": "high"}},
		"conflicts":               []any{},
		"unknowns":                []any{},
		"recommended_next_checks": []any{},
	}
}

func assertFixture(t *testing.T, relative string, got string) {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
	expectedPath := filepath.Join(root, "tests", "parity", "fixtures", relative)
	expected, err := os.ReadFile(expectedPath)
	if err != nil {
		t.Fatal(err)
	}
	if got != string(expected) {
		t.Fatalf("%s drifted\nlen got=%d want=%d", relative, len(got), len(expected))
	}
}
