package provider

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestScopeCapabilitiesFromHelp(t *testing.T) {
	claude := ScopeCapabilitiesFromHelp("claude", "--allowedTools --disallowed-tools --tools --permission-mode")
	if !claude.Available || !claude.Supports["allowed_tools"] || !claude.Supports["disallowed_tools"] || !claude.Supports["tools"] || !claude.Supports["permission_mode"] {
		t.Fatalf("claude capabilities = %#v", claude)
	}

	codex := ScopeCapabilitiesFromHelp("codex", "--sandbox <read-only|workspace-write> --disable --profile --config --output-last-message")
	if !codex.Available || !codex.Supports["sandbox"] || !codex.Supports["sandbox_workspace_write"] || !codex.Supports["disable_feature"] || !codex.Supports["profile"] || !codex.Supports["config"] || !codex.Supports["output_last_message"] {
		t.Fatalf("codex capabilities = %#v", codex)
	}
}

func TestScopeCapabilitiesFromHelpVariants(t *testing.T) {
	cases := []struct {
		name     string
		backend  string
		help     string
		supports map[string]bool
	}{
		{
			name:    "claude camel case",
			backend: "claude",
			help:    "Usage: claude -p [--allowedTools tools] [--disallowedTools tools] [--permission-mode mode]",
			supports: map[string]bool{
				"allowed_tools":    true,
				"disallowed_tools": true,
				"tools":            false,
				"permission_mode":  true,
			},
		},
		{
			name:    "claude dashed",
			backend: "claude",
			help:    "--allowed-tools value --disallowed-tools value --tools value",
			supports: map[string]bool{
				"allowed_tools":    true,
				"disallowed_tools": true,
				"tools":            true,
				"permission_mode":  false,
			},
		},
		{
			name:    "codex without last message",
			backend: "codex",
			help:    "codex exec --sandbox read-only --disable web_search --profile p --config k=v",
			supports: map[string]bool{
				"sandbox":                 true,
				"sandbox_workspace_write": false,
				"disable_feature":         true,
				"profile":                 true,
				"config":                  true,
				"output_last_message":     false,
			},
		},
		{
			name:    "codex workspace write sandbox",
			backend: "codex",
			help:    "codex exec --sandbox <read-only|workspace-write|danger-full-access>",
			supports: map[string]bool{
				"sandbox":                 true,
				"sandbox_workspace_write": true,
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ScopeCapabilitiesFromHelp(tc.backend, tc.help)
			if !got.Available {
				t.Fatalf("capabilities unavailable: %#v", got)
			}
			for key, want := range tc.supports {
				if got.Supports[key] != want {
					t.Fatalf("supports[%s] = %v, want %v (all %#v)", key, got.Supports[key], want, got.Supports)
				}
			}
		})
	}
}

func TestProbeFailureWithoutHelpMarksBackendUnavailable(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "fake-help")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 42\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	registry := NewCapabilityRegistry(func(string) (string, error) {
		return script, nil
	})

	caps := registry.DetectScopeCapabilities(context.Background(), "claude")
	if caps.Available {
		t.Fatalf("capabilities = %#v, want unavailable", caps)
	}
	if !strings.Contains(caps.ProbeError, "probe failed") {
		t.Fatalf("probe error = %q, want probe failed", caps.ProbeError)
	}
}

func TestMissingProbeUsesPythonStyleDiagnostic(t *testing.T) {
	registry := NewCapabilityRegistry(func(string) (string, error) {
		return "", exec.ErrNotFound
	})

	caps := registry.DetectScopeCapabilities(context.Background(), "claude")
	if caps.Available {
		t.Fatalf("capabilities = %#v, want unavailable", caps)
	}
	want := "FileNotFoundError: [Errno 2] No such file or directory: 'claude'"
	if caps.ProbeError != want {
		t.Fatalf("probe error = %q, want %q", caps.ProbeError, want)
	}
}

func TestBuildParticipantArgv(t *testing.T) {
	claude, err := BuildParticipantArgv(workorder.Participant{Backend: "claude", Model: "sonnet", Effort: "high"}, "", []string{"--disallowedTools", "WebFetch"}, "", false)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"claude", "-p", "--model", "sonnet", "--effort", "high", "--disallowedTools", "WebFetch"}; !reflect.DeepEqual(claude, want) {
		t.Fatalf("claude argv = %#v, want %#v", claude, want)
	}

	codex, err := BuildParticipantArgv(workorder.Participant{Backend: "codex", Model: "gpt", Effort: "medium"}, "/tmp/work", []string{"--sandbox", "read-only"}, "/tmp/last.txt", true)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"codex", "exec", "-m", "gpt", "-c", `model_reasoning_effort="medium"`, "--skip-git-repo-check", "--sandbox", "read-only", "--output-last-message", "/tmp/last.txt", "-C", "/tmp/work"}
	if !reflect.DeepEqual(codex, want) {
		t.Fatalf("codex argv = %#v, want %#v", codex, want)
	}
}
