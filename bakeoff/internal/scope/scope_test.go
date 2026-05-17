package scope

import (
	"context"
	"reflect"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestBuildExecutionForRequiredMissingControls(t *testing.T) {
	_, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "claude", Backend: "claude", Model: "m", Effort: "high", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "required"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "claude", Available: true, Supports: map[string]bool{}},
		"",
	)
	if err == nil {
		t.Fatal("expected required scope controls to fail")
	}
}

func TestBuildExecutionForCodexCodebase(t *testing.T) {
	execution, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "codex", Backend: "codex", Model: "gpt", Effort: "high", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "codex", Available: true, Supports: map[string]bool{"sandbox": true, "disable_feature": true}},
		"",
	)
	if err != nil {
		t.Fatal(err)
	}
	wantMechanisms := []string{"codex:sandbox=read-only", "codex:disable=web_search"}
	if got := execution.Metadata["mechanisms"]; !reflect.DeepEqual(got, wantMechanisms) {
		t.Fatalf("mechanisms = %#v, want %#v", got, wantMechanisms)
	}
	if execution.CWD != "/work" {
		t.Fatalf("cwd = %q", execution.CWD)
	}
}
