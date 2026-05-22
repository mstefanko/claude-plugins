package scope

import (
	"context"
	"errors"
	"os"
	"reflect"
	"strings"
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

func TestBuildExecutionForClaudeAndCodexWebScopes(t *testing.T) {
	claude, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "claude", Backend: "claude", Model: "m", Effort: "high", Scope: "web"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "claude", Available: true, Supports: map[string]bool{"allowed_tools": true}},
		"",
	)
	if err != nil {
		t.Fatal(err)
	}
	if !containsAll(claude.Argv, "--allowedTools", "WebFetch", "WebSearch") {
		t.Fatalf("claude argv missing web scope controls: %#v", claude.Argv)
	}
	if claude.Metadata["temporary_cwd"] != true {
		t.Fatalf("claude web scope should use a temporary cwd: %#v", claude.Metadata)
	}
	if _, err := os.Stat(claude.CWD); err != nil {
		t.Fatalf("temporary cwd missing before cleanup: %v", err)
	}
	Cleanup(claude.CleanupPaths)
	if _, err := os.Stat(claude.CWD); !os.IsNotExist(err) {
		t.Fatalf("temporary cwd was not cleaned up: %v", err)
	}

	codex, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "codex", Backend: "codex", Model: "gpt", Effort: "high", Scope: "web"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "codex", Available: true, Supports: map[string]bool{"sandbox": true, "output_last_message": true}},
		"/tmp/last-message.txt",
	)
	if err != nil {
		t.Fatal(err)
	}
	defer Cleanup(codex.CleanupPaths)
	if !containsAll(codex.Argv, "--sandbox", "read-only", "--output-last-message", "/tmp/last-message.txt", "-C", codex.CWD) {
		t.Fatalf("codex argv missing web scope controls: %#v cwd=%s", codex.Argv, codex.CWD)
	}
	if codex.CWD == "/work" || codex.Metadata["temporary_cwd"] != true {
		t.Fatalf("codex web scope cwd metadata = cwd %q metadata %#v", codex.CWD, codex.Metadata)
	}
}

func TestBuildExecutionMixedScopeRequiredIsEnforced(t *testing.T) {
	execution, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "claude", Backend: "claude", Model: "m", Scope: "mixed"},
		workorder.ScopePolicy{Enforcement: "required"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "claude", Available: true, Supports: map[string]bool{}},
		"",
	)
	if err != nil {
		t.Fatal(err)
	}
	if execution.Metadata["enforcement_level"] != "enforced" || execution.Metadata["fallback_reason"] != nil {
		t.Fatalf("mixed required metadata = %#v", execution.Metadata)
	}
}

func TestBuildExecutionForGenericOptionalProviderIsPartial(t *testing.T) {
	execution, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "gemini", Backend: "gemini", Model: "pro", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "gemini", Available: true, Supports: map[string]bool{"model": true}},
		"",
	)
	if err != nil {
		t.Fatal(err)
	}
	if execution.Metadata["enforcement_level"] != "partial" || execution.Metadata["fallback_reason"] == nil {
		t.Fatalf("gemini metadata = %#v", execution.Metadata)
	}
	if !containsAll(execution.Argv, "gemini", "--model", "pro") {
		t.Fatalf("gemini argv = %#v", execution.Argv)
	}
}

func TestBuildExecutionForRequiredOptionalProviderControlsFails(t *testing.T) {
	_, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "copilot", Backend: "copilot", Model: "auto", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "required"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "copilot", Available: true, Supports: map[string]bool{"no_ask_user": true}},
		"",
	)
	if err == nil || !strings.Contains(err.Error(), "advisory") {
		t.Fatalf("expected optional provider required scope failure, got %v", err)
	}
}

func TestBuildExecutionUsesFrozenCapsBeforeRegistry(t *testing.T) {
	registry := provider.NewCapabilityRegistry(func(string) (string, error) {
		return "", errors.New("registry should not be consulted when frozen caps are provided")
	})
	execution, err := BuildExecution(
		context.Background(),
		registry,
		workorder.Participant{ID: "codex", Backend: "codex", Model: "gpt", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "codex", Available: true, Supports: map[string]bool{"sandbox": true, "disable_feature": true, "output_last_message": true}},
		"/tmp/last-message.txt",
	)
	if err != nil {
		t.Fatal(err)
	}
	if !containsAll(execution.Argv, "--output-last-message", "/tmp/last-message.txt") {
		t.Fatalf("argv did not use frozen output_last_message capability: %#v", execution.Argv)
	}
}

func TestBuildExecutionAddsClaudeLastMessageFromCaps(t *testing.T) {
	execution, err := BuildExecution(
		context.Background(),
		nil,
		workorder.Participant{ID: "claude", Backend: "claude", Model: "sonnet", Scope: "codebase"},
		workorder.ScopePolicy{Enforcement: "best_effort"},
		"/work",
		"/work/runs/r1",
		&provider.ScopeCapabilities{Backend: "claude", Available: true, Supports: map[string]bool{"disallowed_tools": true, "output_last_message": true}},
		"/tmp/last-message.txt",
	)
	if err != nil {
		t.Fatal(err)
	}
	if !containsAll(execution.Argv, "--output-last-message", "/tmp/last-message.txt") {
		t.Fatalf("claude argv did not include output_last_message capability: %#v", execution.Argv)
	}
}

func TestScopeErrorResultUsesConsistentStatusShape(t *testing.T) {
	result := ScopeErrorResult(
		&EnforcementError{Message: "missing controls"},
		workorder.Participant{ID: "claude", Backend: "claude", Scope: "codebase"},
		workorder.ScopePolicy{},
		"/work",
	)
	if result["status"] != StatusScopeError || result["stderr_bytes"] != len("missing controls") || result["stderr_observed_bytes"] != len("missing controls") {
		t.Fatalf("scope error shape = %#v", result)
	}
	if _, ok := result["io"]; !ok {
		t.Fatalf("scope error result missing io metadata: %#v", result)
	}
	scopeMetadata := result["scope_enforcement"].(map[string]any)
	if scopeMetadata["policy"] != "best_effort" || scopeMetadata["temporary_cwd"] != false {
		t.Fatalf("scope metadata = %#v", scopeMetadata)
	}
}

func containsAll(items []string, values ...string) bool {
	text := "\x00" + strings.Join(items, "\x00") + "\x00"
	for _, value := range values {
		if !strings.Contains(text, "\x00"+value+"\x00") {
			return false
		}
	}
	return true
}
