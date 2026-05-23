package showcmd

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestShowIncludesFailedTriageStderrTail(t *testing.T) {
	root := t.TempDir()
	runDir := filepath.Join(root, "runs", "r1")
	writeShowJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "show-triage",
		"type":           "gather",
		"goal":           "triage",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	})
	writeShowJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "structured_union"})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	writeShowJSON(t, filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "exit_error"})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "stderr.txt"), strings.Join([]string{"one", "two", "three"}, "\n")+"\n"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	err := runShow(context.Background(), showTestFactory{streams: output.NewStreams(&out, &errOut)}, &ShowOptions{
		RunID: "r1",
		Out:   filepath.Join(root, "runs"),
	})
	if err != nil {
		t.Fatalf("runShow returned error: %v", err)
	}
	text := out.String()
	for _, want := range []string{"# report", "triage failed: exit_error", "triage stderr tail:", "  one", "  three"} {
		if !strings.Contains(text, want) {
			t.Fatalf("output missing %q:\n%s", want, text)
		}
	}
}

type showTestFactory struct {
	streams output.Streams
}

func (f showTestFactory) Streams() output.Streams {
	return f.streams
}

func (showTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (showTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (showTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (showTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(exec.LookPath)
}

func writeShowJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
