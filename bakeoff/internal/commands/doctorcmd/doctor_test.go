package doctorcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/modeldefaults"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
)

type doctorTestFactory struct {
	streams output.Streams
	lookup  provider.LookupFunc
	caps    *provider.CapabilityRegistry
}

func (f doctorTestFactory) Streams() output.Streams {
	return f.streams
}

func (f doctorTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f doctorTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f doctorTestFactory) LookupProvider(name string) (string, error) {
	return f.lookup(name)
}

func (f doctorTestFactory) Capabilities() *provider.CapabilityRegistry {
	return f.caps
}

func TestRunDoctorBuildPreflightUsesFakeProviders(t *testing.T) {
	f, out := newDoctorFakeFactory(t, true)

	err := runDoctor(context.Background(), f, &DoctorOptions{Build: true, SkipAuthProbe: true, Quiet: true, JSON: true})
	if err != nil {
		t.Fatalf("%v\nreport = %#v", err, decodeDoctorReport(t, out))
	}

	report := decodeDoctorReport(t, out)
	if report["status"] != "ok" {
		t.Fatalf("status = %#v, report = %#v", report["status"], report)
	}
	preflight := report["build_preflight"].(map[string]any)
	if preflight["ok"] != true || preflight["temporary_workspace_removed"] != true {
		t.Fatalf("build preflight = %#v", preflight)
	}
	providers := preflight["providers"].(map[string]any)
	for _, backend := range []string{"claude", "codex"} {
		entry := providers[backend].(map[string]any)
		if entry["ok"] != true || entry["workspace_write"] != true {
			t.Fatalf("%s build probe = %#v", backend, entry)
		}
	}
	codexCaps := report["scope_capabilities"].(map[string]any)["codex"].(map[string]any)
	supports := codexCaps["supports"].(map[string]any)
	if supports["sandbox_workspace_write"] != true {
		t.Fatalf("codex supports = %#v", supports)
	}
	authProbes := report["auth_probes"].(map[string]any)
	if len(authProbes) != 0 {
		t.Fatalf("build preflight should not also run auth probes: %#v", authProbes)
	}
}

func TestRunDoctorJSONReportsModelDefaults(t *testing.T) {
	f, out := newDoctorFakeFactory(t, true)

	err := runDoctor(context.Background(), f, &DoctorOptions{
		SkipAuthProbe: true,
		Quiet:         true,
		JSON:          true,
	})
	if err != nil {
		t.Fatal(err)
	}

	report := decodeDoctorReport(t, out)
	defaults := report["defaults"].(map[string]any)
	want := map[string]string{
		"claude_sonnet": modeldefaults.ClaudeSonnet,
		"claude_opus":   modeldefaults.ClaudeOpus,
		"claude_haiku":  modeldefaults.ClaudeHaiku,
		"codex":         modeldefaults.CodexDefault,
		"codex_gpt5":    modeldefaults.CodexGPT5,
	}
	for key, value := range want {
		if defaults[key] != value {
			t.Fatalf("defaults[%s] = %#v, want %q (all %#v)", key, defaults[key], value, defaults)
		}
	}
}

func TestRunDoctorJSONReportsJudgeFamilyAdvisory(t *testing.T) {
	f, out := newDoctorFakeFactoryWithBackends(t, true, "claude", "codex", "gemini")

	err := runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true, Quiet: true, JSON: true})
	if err != nil {
		t.Fatalf("%v\nreport = %#v", err, decodeDoctorReport(t, out))
	}

	report := decodeDoctorReport(t, out)
	providers := report["providers"].(map[string]any)
	claude := providers["claude"].(map[string]any)
	if claude["family"] != provider.ProviderFamilyAnthropic {
		t.Fatalf("claude family = %#v", claude["family"])
	}
	advisory := report["judge_family_advisory"].(map[string]any)
	if advisory["judge_backend"] != "claude" || advisory["judge_family"] != provider.ProviderFamilyAnthropic || advisory["relation"] != provider.JudgeFamilyRelationSameAsSome || advisory["advisory_only"] != true {
		t.Fatalf("judge family advisory = %#v", advisory)
	}
	if got := stringSliceFromJSON(t, advisory["provider_backends"]); !reflect.DeepEqual(got, []string{"claude", "codex"}) {
		t.Fatalf("provider_backends = %#v", got)
	}
	if got := stringSliceFromJSON(t, advisory["ready_non_contestant_judges"]); !reflect.DeepEqual(got, []string{"gemini"}) {
		t.Fatalf("ready_non_contestant_judges = %#v", got)
	}
}

func TestRunDoctorHumanJudgeFamilyAdvisoryIsActionableOnly(t *testing.T) {
	f, out := newDoctorFakeFactoryWithBackends(t, true, "claude", "codex", "gemini")

	err := runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true, Quiet: true})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "- judge family advisory: default judge claude shares provider-family metadata with a selected provider; ready non-contestant judge backends: gemini. Advisory only; no defaults changed.") {
		t.Fatalf("missing human advisory:\n%s", out.String())
	}

	f, out = newDoctorFakeFactory(t, true)
	err = runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true, Quiet: true})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "judge family advisory") {
		t.Fatalf("unexpected human advisory without a ready alternative:\n%s", out.String())
	}
}

func TestRunDoctorBuildPreflightFailsWithoutCodexWorkspaceWrite(t *testing.T) {
	f, out := newDoctorFakeFactory(t, false)

	err := runDoctor(context.Background(), f, &DoctorOptions{Build: true, SkipAuthProbe: true, Quiet: true, JSON: true})
	if err == nil {
		t.Fatal("expected doctor to fail when Codex lacks workspace-write sandbox support")
	}

	report := decodeDoctorReport(t, out)
	if report["status"] != "failed" {
		t.Fatalf("status = %#v, report = %#v", report["status"], report)
	}
	preflight := report["build_preflight"].(map[string]any)
	providers := preflight["providers"].(map[string]any)
	codex := providers["codex"].(map[string]any)
	if codex["ok"] != false || !strings.Contains(codex["reason"].(string), "workspace-write") {
		t.Fatalf("codex build probe = %#v", codex)
	}
}

func TestRunDoctorReportsFallbackPairWhenCodexMissing(t *testing.T) {
	f, out := newDoctorFakeFactoryWithBackends(t, true, "claude", "gemini")

	err := runDoctor(context.Background(), f, &DoctorOptions{
		SkipAuthProbe: true,
		Quiet:         true,
		JSON:          true,
	})
	if err != nil {
		t.Fatalf("%v\nreport = %#v", err, decodeDoctorReport(t, out))
	}

	report := decodeDoctorReport(t, out)
	if report["canonical_default_available"] != false || report["runnable_default_pair_available"] != true {
		t.Fatalf("default readiness = %#v", report)
	}
	selected := report["selected_default_pair"].([]any)
	if len(selected) != 2 || selected[0] != "claude" || selected[1] != "gemini" {
		t.Fatalf("selected pair = %#v", selected)
	}
	providers := report["providers"].(map[string]any)
	gemini := providers["gemini"].(map[string]any)
	if gemini["required_for_selected_default"] != true || gemini["default_model"] != modeldefaults.GeminiDefault {
		t.Fatalf("gemini provider report = %#v", gemini)
	}
}

func TestRunDoctorReportsAmbiguousFallbackChoice(t *testing.T) {
	f, out := newDoctorFakeFactoryWithBackends(t, true, "claude", "gemini", "copilot")

	err := runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true, Quiet: true, JSON: true})
	if err != nil {
		t.Fatalf("%v\nreport = %#v", err, decodeDoctorReport(t, out))
	}

	report := decodeDoctorReport(t, out)
	if report["selected_default_pair"] != nil || report["fallback_requires_user_choice"] != true || report["runnable_default_pair_available"] != true {
		t.Fatalf("fallback choice report = %#v", report)
	}
	candidates := report["fallback_candidates"].([]any)
	if len(candidates) != 2 {
		t.Fatalf("fallback candidates = %#v", candidates)
	}
}

func TestRunDoctorFailsWhenClaudeMissing(t *testing.T) {
	f, out := newDoctorFakeFactoryWithBackends(t, true, "gemini", "copilot")

	err := runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true, Quiet: true, JSON: true})
	if err == nil {
		t.Fatal("expected doctor to fail without claude")
	}
	report := decodeDoctorReport(t, out)
	if report["status"] != "failed" || report["runnable_default_pair_available"] != false {
		t.Fatalf("report = %#v", report)
	}
}

func newDoctorFakeFactory(t *testing.T, codexWorkspaceWrite bool) (doctorTestFactory, *bytes.Buffer) {
	return newDoctorFakeFactoryWithBackends(t, codexWorkspaceWrite, "claude", "codex")
}

func newDoctorFakeFactoryWithBackends(t *testing.T, codexWorkspaceWrite bool, backends ...string) (doctorTestFactory, *bytes.Buffer) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("doctor fake provider scripts require POSIX shell")
	}
	dir := t.TempDir()
	fakeBackends := map[string]bool{}
	for _, backend := range backends {
		fakeBackends[backend] = true
		writeDoctorFakeProvider(t, dir, backend, codexWorkspaceWrite)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))

	lookup := func(name string) (string, error) {
		if fakeBackends[name] {
			return filepath.Join(dir, name), nil
		}
		if name == "gemini" || name == "copilot" || name == "codex" || name == "claude" {
			return "", exec.ErrNotFound
		}
		return exec.LookPath(name)
	}
	var out, errOut bytes.Buffer
	f := doctorTestFactory{
		streams: output.NewStreams(&out, &errOut),
		lookup:  lookup,
	}
	f.caps = provider.NewCapabilityRegistry(lookup)
	return f, &out
}

func writeDoctorFakeProvider(t *testing.T, dir string, name string, codexWorkspaceWrite bool) {
	t.Helper()
	sandboxHelp := "--sandbox read-only"
	if codexWorkspaceWrite {
		sandboxHelp = "--sandbox <read-only|workspace-write>"
	}
	expectedModel := provider.DefaultModel(name)
	help := "echo 'fake claude help'; echo '--allowedTools'; echo '--disallowedTools'; echo '--tools'; echo '--permission-mode'"
	switch name {
	case "codex":
		help = fmt.Sprintf("echo 'fake codex exec help'; echo '%s'; echo '--disable'; echo '--profile'; echo '--config'; echo '--output-last-message'", sandboxHelp)
	case "gemini":
		help = "echo 'fake gemini help'; echo '--model'; echo '--approval-mode <default|auto_edit|yolo>'; echo '--yolo'"
	case "copilot":
		help = "echo 'fake copilot help'; echo '--model'; echo '--no-ask-user'; echo '--allow-tool'; echo '--deny-tool'"
	}
	script := fmt.Sprintf(`#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "%[1]s fake 1.0"
  exit 0
fi
for arg in "$@"; do
  if [ "$arg" = "--help" ]; then
    %[2]s
    exit 0
  fi
done
model=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model|-m)
      shift
      model="${1:-}"
      ;;
  esac
  shift
done
if [ "$model" != "%[3]s" ]; then
  echo "unexpected model for %[1]s: $model" >&2
  exit 42
fi
cat >/dev/null
printf 'bakeoff-build-write-ok-%[1]s\n' > bakeoff-doctor-build-probe.txt
printf '<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>\n'
`, name, help, expectedModel)
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

func decodeDoctorReport(t *testing.T, out *bytes.Buffer) map[string]any {
	t.Helper()
	var report map[string]any
	if err := json.Unmarshal(out.Bytes(), &report); err != nil {
		t.Fatalf("doctor JSON did not decode: %v\n%s", err, out.String())
	}
	return report
}

func stringSliceFromJSON(t *testing.T, value any) []string {
	t.Helper()
	items, ok := value.([]any)
	if !ok {
		t.Fatalf("value is not a JSON array: %#v", value)
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		text, ok := item.(string)
		if !ok {
			t.Fatalf("array item is not a string: %#v", item)
		}
		out = append(out, text)
	}
	return out
}
