package buildcmd

import (
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildverify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestBuildSummaryIncludesExperiment(t *testing.T) {
	got := buildSummary(
		buildworkspace.Repository{},
		t.TempDir(),
		"run-1",
		"runs",
		map[string]any{"decision_kind": "both_failed", "judge_ran": false},
		buildverify.Result{},
		nil,
		nil,
		buildDiagnostics{},
		1,
		&workorder.ExperimentSpec{
			ID:              "review-auth",
			TaskID:          "auth-review",
			ConditionID:     "pairwise.security",
			RunKind:         "pairwise",
			RepetitionIndex: 1,
		},
	)
	experiment := got["experiment"].(map[string]any)
	if experiment["id"] != "review-auth" || experiment["task_id"] != "auth-review" {
		t.Fatalf("experiment = %#v", experiment)
	}
}
