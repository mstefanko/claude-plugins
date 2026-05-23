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
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
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

func TestShowPrintsRelatedEscalationsAndSiblings(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeShowRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "pick_winner"}, map[string]any{"type": "compare"})
	writeShowRun(t, outDir, "child-a", "compare", map[string]any{"decision_kind": "escalation_advisory_supported"}, map[string]any{
		"type":            "escalation",
		"source_run_id":   "source",
		"source_type":     "compare",
		"escalation_mode": "dispute",
		"added_provider":  "gemini",
	})
	writeShowJSON(t, filepath.Join(outDir, "child-a", "triage", "status.json"), map[string]any{"status": "dry_run"})
	writeShowRun(t, outDir, "child-b", "compare", map[string]any{"decision_kind": "escalation_advisory_challenged"}, map[string]any{
		"type":            "escalation",
		"source_run_id":   "source",
		"source_type":     "compare",
		"escalation_mode": "witness",
		"added_provider":  "copilot",
	})

	var out, errOut bytes.Buffer
	err := runShow(context.Background(), showTestFactory{streams: output.NewStreams(&out, &errOut)}, &ShowOptions{
		RunID: "source",
		Out:   outDir,
	})
	if err != nil {
		t.Fatalf("runShow source returned error: %v", err)
	}
	text := out.String()
	for _, want := range []string{
		"related escalations:",
		"child-a  dispute  gemini  escalation_advisory_supported  triage:dry_run",
		"child-b  witness  copilot  escalation_advisory_challenged  triage:no",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("source show missing %q:\n%s", want, text)
		}
	}

	out.Reset()
	err = runShow(context.Background(), showTestFactory{streams: output.NewStreams(&out, &errOut)}, &ShowOptions{
		RunID: "child-b",
		Out:   outDir,
	})
	if err != nil {
		t.Fatalf("runShow escalation returned error: %v", err)
	}
	text = out.String()
	for _, want := range []string{
		"source run: source",
		"sibling escalations:",
		"child-a  dispute  gemini  escalation_advisory_supported  triage:dry_run",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("escalation show missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "child-b  witness") {
		t.Fatalf("escalation show should not list itself as sibling:\n%s", text)
	}
}

func TestShowPrintsZeroSelectedTriageWarning(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	runDir := filepath.Join(outDir, "review")
	writeShowRun(t, outDir, "review", "gather", map[string]any{"decision_kind": "structured_union"}, map[string]any{"type": "gather"})
	hashes, err := triage.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	filter := map[string]any{"included": 0, "skipped_non_actionable": 2, "skipped_out_of_facet": 0}
	writeShowJSON(t, filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "ok", "source_finding_filter": filter})
	writeShowJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{"schema_version": 1, "status": "complete", "summary": "none", "items": []any{}, "input_hashes": hashes, "source_finding_filter": filter})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# triage\n"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	err = runShow(context.Background(), showTestFactory{streams: output.NewStreams(&out, &errOut)}, &ShowOptions{
		RunID: "review",
		Out:   outDir,
	})
	if err != nil {
		t.Fatalf("runShow returned error: %v", err)
	}
	if !strings.Contains(out.String(), triage.ZeroSelectedMessage) {
		t.Fatalf("show missing zero-selected warning:\n%s", out.String())
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

func writeShowRun(t *testing.T, outDir string, runID string, workOrderType string, decision map[string]any, manifestFields map[string]any) {
	t.Helper()
	runDir := filepath.Join(outDir, runID)
	writeShowJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             runID,
		"type":           workOrderType,
		"goal":           "show run",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	})
	if _, ok := decision["mode"]; !ok {
		decision["mode"] = workOrderType
	}
	if _, ok := decision["judge_ran"]; !ok {
		decision["judge_ran"] = false
	}
	writeShowJSON(t, filepath.Join(runDir, "decision.json"), decision)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# "+runID+"\n"); err != nil {
		t.Fatal(err)
	}
	writeShowJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": runID, "type": manifestFields["type"]})
	manifestDoc := map[string]any{
		"schema_version": 1,
		"run_id":         runID,
		"type":           manifestFields["type"],
		"decision_kind":  decision["decision_kind"],
		"artifacts":      map[string]any{"report": "report.md"},
		"triage":         map[string]any{"state": "no"},
	}
	for key, value := range manifestFields {
		manifestDoc[key] = value
	}
	writeShowJSON(t, filepath.Join(runDir, "manifest.json"), manifestDoc)
}
