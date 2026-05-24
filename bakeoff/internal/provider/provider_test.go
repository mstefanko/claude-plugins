package provider

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

type testParticipant struct {
	backend string
	model   string
	effort  string
}

func (p testParticipant) BackendName() string { return p.backend }
func (p testParticipant) ModelName() string   { return p.model }
func (p testParticipant) EffortLevel() string { return p.effort }

func TestProviderCatalog(t *testing.T) {
	if !ValidBackend("gemini") || !ValidBackend("copilot") || ValidBackend("unknown") {
		t.Fatalf("valid backend answers are wrong")
	}
	if got := DefaultModel("gemini"); got != "pro" {
		t.Fatalf("gemini default model = %q", got)
	}
	if got := PromptFlavor("copilot"); got != PromptFlavorGeneric {
		t.Fatalf("copilot prompt flavor = %q", got)
	}
	resolved := ResolveDefaultPair(map[string]bool{"claude": true, "gemini": true})
	if resolved.CanonicalDefaultAvailable || !resolved.RunnableDefaultPair || !reflect.DeepEqual(resolved.SelectedDefaultPair, []string{"claude", "gemini"}) {
		t.Fatalf("fallback resolution = %#v", resolved)
	}
	ambiguous := ResolveDefaultPair(map[string]bool{"claude": true, "gemini": true, "copilot": true})
	if !ambiguous.FallbackRequiresUserChoice || ambiguous.SelectedDefaultPair != nil || len(ambiguous.FallbackCandidates) != 2 {
		t.Fatalf("ambiguous fallback resolution = %#v", ambiguous)
	}
}

func TestProviderFamilyMetadata(t *testing.T) {
	expected := map[string]string{
		"claude":  ProviderFamilyAnthropic,
		"codex":   ProviderFamilyOpenAI,
		"gemini":  ProviderFamilyGoogleGemini,
		"copilot": ProviderFamilyGitHubCopilot,
	}
	if len(KnownBackends()) != len(expected) {
		t.Fatalf("expected family metadata for every known backend")
	}
	for backend, family := range expected {
		if got := FamilyForBackend(backend); got != family {
			t.Fatalf("FamilyForBackend(%q) = %q, want %q", backend, got, family)
		}
		spec, ok := Backend(backend)
		if !ok {
			t.Fatalf("Backend(%q) not found", backend)
		}
		if spec.Family != family {
			t.Fatalf("Backend(%q).Family = %q, want %q", backend, spec.Family, family)
		}
	}
	if got := FamilyForBackend("unknown"); got != ProviderFamilyUnknown {
		t.Fatalf("unknown family = %q, want %q", got, ProviderFamilyUnknown)
	}
	if !SameBackendFamily("claude", "claude") {
		t.Fatalf("same backend should have same family")
	}
	if SameBackendFamily("claude", "codex") {
		t.Fatalf("claude and codex should not have same family")
	}
	if SameBackendFamily("claude", "missing") {
		t.Fatalf("known and unknown families should not compare equal")
	}
	if SameBackendFamily("missing-a", "missing-b") {
		t.Fatalf("unknown families should not compare equal")
	}

	backends := KnownBackends()
	backends[0].Family = "mutated"
	if got := FamilyForBackend("claude"); got != ProviderFamilyAnthropic {
		t.Fatalf("KnownBackends mutation changed catalog family to %q", got)
	}
}

func TestJudgeFamilyRelation(t *testing.T) {
	cases := []struct {
		name      string
		judge     string
		providers []string
		want      string
	}{
		{
			name:      "same as all",
			judge:     "claude",
			providers: []string{"claude", "claude"},
			want:      JudgeFamilyRelationSameAsAll,
		},
		{
			name:      "same as some",
			judge:     "claude",
			providers: []string{"claude", "codex"},
			want:      JudgeFamilyRelationSameAsSome,
		},
		{
			name:      "different from all",
			judge:     "claude",
			providers: []string{"codex", "gemini"},
			want:      JudgeFamilyRelationDifferentFromAll,
		},
		{
			name:      "unknown judge",
			judge:     "missing",
			providers: []string{"claude", "codex"},
			want:      JudgeFamilyRelationUnknown,
		},
		{
			name:      "unknown provider",
			judge:     "claude",
			providers: []string{"claude", "missing"},
			want:      JudgeFamilyRelationUnknown,
		},
		{
			name:      "no providers",
			judge:     "claude",
			providers: nil,
			want:      JudgeFamilyRelationUnknown,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := JudgeFamilyRelation(tc.judge, tc.providers); got != tc.want {
				t.Fatalf("JudgeFamilyRelation(%q, %#v) = %q, want %q", tc.judge, tc.providers, got, tc.want)
			}
		})
	}
}

func TestNonContestantJudgeBackends(t *testing.T) {
	ready := map[string]bool{
		"claude":  true,
		"codex":   true,
		"gemini":  true,
		"copilot": false,
	}
	got := NonContestantJudgeBackends([]string{"claude", "codex"}, ready)
	if !reflect.DeepEqual(got, []string{"gemini"}) {
		t.Fatalf("ready non-contestant backends = %#v", got)
	}
	got = NonContestantJudgeBackends([]string{"claude", "codex"}, nil)
	if !reflect.DeepEqual(got, []string{"gemini", "copilot"}) {
		t.Fatalf("all non-contestant backends = %#v", got)
	}
	got = NonContestantJudgeBackends([]string{"claude", "missing"}, ready)
	if got != nil {
		t.Fatalf("unknown provider family should suppress alternatives, got %#v", got)
	}
}

func TestScopeCapabilitiesFromHelp(t *testing.T) {
	claude := ScopeCapabilitiesFromHelp("claude", "--allowedTools --disallowed-tools --tools --permission-mode --output-last-message")
	if !claude.Available || !claude.Supports["allowed_tools"] || !claude.Supports["disallowed_tools"] || !claude.Supports["tools"] || !claude.Supports["permission_mode"] || !claude.Supports["output_last_message"] {
		t.Fatalf("claude capabilities = %#v", claude)
	}

	codex := ScopeCapabilitiesFromHelp("codex", "--sandbox <read-only|workspace-write> --disable --profile --config --output-last-message")
	if !codex.Available || !codex.Supports["sandbox"] || !codex.Supports["sandbox_workspace_write"] || !codex.Supports["disable_feature"] || !codex.Supports["profile"] || !codex.Supports["config"] || !codex.Supports["output_last_message"] {
		t.Fatalf("codex capabilities = %#v", codex)
	}

	gemini := ScopeCapabilitiesFromHelp("gemini", "--model value --approval-mode <default|auto_edit|yolo> --yolo")
	if !gemini.Available || !gemini.Supports["model"] || !gemini.Supports["approval_mode"] || !gemini.Supports["approval_auto_edit"] || !gemini.Supports["approval_yolo"] || !gemini.Supports["yolo_flag"] {
		t.Fatalf("gemini capabilities = %#v", gemini)
	}

	copilot := ScopeCapabilitiesFromHelp("copilot", "--model value --no-ask-user --allow-tool edit --deny-tool web")
	if !copilot.Available || !copilot.Supports["model"] || !copilot.Supports["no_ask_user"] || !copilot.Supports["allow_tool"] || !copilot.Supports["deny_tool"] {
		t.Fatalf("copilot capabilities = %#v", copilot)
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
				"allowed_tools":       true,
				"disallowed_tools":    true,
				"tools":               false,
				"permission_mode":     true,
				"output_last_message": false,
			},
		},
		{
			name:    "claude dashed",
			backend: "claude",
			help:    "--allowed-tools value --disallowed-tools value --tools value --output-last-message value",
			supports: map[string]bool{
				"allowed_tools":       true,
				"disallowed_tools":    true,
				"tools":               true,
				"permission_mode":     false,
				"output_last_message": true,
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

func TestScopeCapabilityProbeFailuresDoNotPoisonCache(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "fake-help")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf '%s\n' '--disallowedTools --output-last-message'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	calls := 0
	registry := NewCapabilityRegistry(func(string) (string, error) {
		calls++
		if calls == 1 {
			return "", exec.ErrNotFound
		}
		return script, nil
	})

	first := registry.DetectScopeCapabilities(context.Background(), "claude")
	if first.Available || first.ProbeError == "" {
		t.Fatalf("first capabilities = %#v, want failed probe", first)
	}
	second := registry.DetectScopeCapabilities(context.Background(), "claude")
	if !second.Available || !second.Supports["disallowed_tools"] {
		t.Fatalf("second capabilities = %#v, want successful re-probe", second)
	}
	if calls != 2 {
		t.Fatalf("probe calls = %d, want 2", calls)
	}
}

func TestGetOrProbeWaitersRespectContextAndProbePanicResolves(t *testing.T) {
	registry := NewCapabilityRegistry(nil)
	started := make(chan struct{})
	release := make(chan struct{})
	done := make(chan ScopeCapabilities, 1)
	go func() {
		done <- registry.getOrProbe(context.Background(), "scope:test", "test", func() ScopeCapabilities {
			close(started)
			<-release
			return ScopeCapabilities{Backend: "test", Available: true, Supports: map[string]bool{"ok": true}}
		})
	}()
	<-started
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	waited := registry.getOrProbe(ctx, "scope:test", "test", func() ScopeCapabilities {
		t.Fatal("waiter should not start a duplicate probe")
		return ScopeCapabilities{}
	})
	if waited.Available || !strings.Contains(waited.ProbeError, "context canceled") {
		t.Fatalf("wait result = %#v", waited)
	}
	close(release)
	if got := <-done; !got.Available || !got.Supports["ok"] {
		t.Fatalf("probe result = %#v", got)
	}

	panicked := registry.getOrProbe(context.Background(), "scope:panic", "panic", func() ScopeCapabilities {
		panic("boom")
	})
	if panicked.Available || !strings.Contains(panicked.ProbeError, "panicked") {
		t.Fatalf("panic result = %#v", panicked)
	}
	recovered := registry.getOrProbe(context.Background(), "scope:panic", "panic", func() ScopeCapabilities {
		return ScopeCapabilities{Backend: "panic", Available: true, Supports: map[string]bool{"ok": true}}
	})
	if !recovered.Available || !recovered.Supports["ok"] {
		t.Fatalf("panic should not poison cache, got %#v", recovered)
	}
}

func TestBuildParticipantArgv(t *testing.T) {
	claude, err := BuildParticipantArgv(testParticipant{backend: "claude", model: "sonnet", effort: "high"}, "", []string{"--disallowedTools", "WebFetch"}, "", false)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"claude", "-p", "--model", "sonnet", "--effort", "high", "--disallowedTools", "WebFetch"}; !reflect.DeepEqual(claude, want) {
		t.Fatalf("claude argv = %#v, want %#v", claude, want)
	}

	claudeLastMessage, err := BuildParticipantArgv(testParticipant{backend: "claude", model: "sonnet", effort: "high"}, "", nil, "/tmp/last.txt", true)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"claude", "-p", "--model", "sonnet", "--effort", "high", "--output-last-message", "/tmp/last.txt"}; !reflect.DeepEqual(claudeLastMessage, want) {
		t.Fatalf("claude argv with last message = %#v, want %#v", claudeLastMessage, want)
	}

	claudeUnsupported, err := BuildParticipantArgv(testParticipant{backend: "claude", model: "sonnet", effort: "high"}, "", nil, "/tmp/last.txt", false)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"claude", "-p", "--model", "sonnet", "--effort", "high"}; !reflect.DeepEqual(claudeUnsupported, want) {
		t.Fatalf("claude argv without last-message support = %#v, want %#v", claudeUnsupported, want)
	}

	codex, err := BuildParticipantArgv(testParticipant{backend: "codex", model: "gpt", effort: "medium"}, "/tmp/work", []string{"--sandbox", "read-only"}, "/tmp/last.txt", true)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"codex", "exec", "-m", "gpt", "-c", `model_reasoning_effort="medium"`, "--skip-git-repo-check", "--sandbox", "read-only", "--output-last-message", "/tmp/last.txt", "-C", "/tmp/work"}
	if !reflect.DeepEqual(codex, want) {
		t.Fatalf("codex argv = %#v, want %#v", codex, want)
	}

	gemini, err := BuildParticipantArgv(testParticipant{backend: "gemini", model: "pro", effort: "high"}, "/tmp/work", []string{"--approval-mode", "auto_edit"}, "", false)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"gemini", "--model", "pro", "--approval-mode", "auto_edit"}; !reflect.DeepEqual(gemini, want) {
		t.Fatalf("gemini argv = %#v, want %#v", gemini, want)
	}

	copilot, err := BuildParticipantArgv(testParticipant{backend: "copilot", model: "auto", effort: "high"}, "/tmp/work", nil, "", false)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"copilot", "--model", "auto", "--no-ask-user"}; !reflect.DeepEqual(copilot, want) {
		t.Fatalf("copilot argv = %#v, want %#v", copilot, want)
	}
}
