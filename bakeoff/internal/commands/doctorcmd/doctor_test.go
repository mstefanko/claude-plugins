package doctorcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
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
		t.Fatal(err)
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

func newDoctorFakeFactory(t *testing.T, codexWorkspaceWrite bool) (doctorTestFactory, *bytes.Buffer) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("doctor fake provider scripts require POSIX shell")
	}
	dir := t.TempDir()
	writeDoctorFakeProvider(t, dir, "claude", true)
	writeDoctorFakeProvider(t, dir, "codex", codexWorkspaceWrite)
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))

	lookup := func(name string) (string, error) {
		switch name {
		case "claude", "codex":
			return filepath.Join(dir, name), nil
		default:
			return exec.LookPath(name)
		}
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
	help := "echo 'fake claude help'; echo '--allowedTools'; echo '--disallowedTools'; echo '--tools'; echo '--permission-mode'"
	if name == "codex" {
		help = fmt.Sprintf("echo 'fake codex exec help'; echo '%s'; echo '--disable'; echo '--profile'; echo '--config'; echo '--output-last-message'", sandboxHelp)
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
cat >/dev/null
printf 'bakeoff-build-write-ok-%[1]s\n' > bakeoff-doctor-build-probe.txt
printf '<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>\n'
`, name, help)
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
