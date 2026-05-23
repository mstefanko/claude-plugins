package bundlecmd

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

func TestBundleIncludesSourceChildrenTriageWarningsAndWriteGate(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	writeBundleRun(t, outDir, "source", "gather", map[string]any{"decision_kind": "structured_union"}, map[string]any{"type": "gather"})
	writeBundleRun(t, outDir, "child-a", "gather", map[string]any{"decision_kind": "escalation_advisory_supported"}, map[string]any{
		"type":            "escalation",
		"source_run_id":   "source",
		"source_type":     "gather",
		"escalation_mode": "dispute",
		"added_provider":  "gemini",
	})
	writeZeroSelectedTriage(t, filepath.Join(outDir, "child-a"))
	writeBundleRun(t, outDir, "child-b", "gather", map[string]any{"decision_kind": "escalation_advisory_challenged"}, map[string]any{
		"type":            "escalation",
		"source_run_id":   "source",
		"source_type":     "gather",
		"escalation_mode": "witness",
		"added_provider":  "copilot",
	})
	writeBundleJSON(t, filepath.Join(outDir, "child-b", "triage", "status.json"), map[string]any{"status": "exit_error"})

	var out, errOut bytes.Buffer
	err := runBundle(context.Background(), bundleTestFactory{streams: output.NewStreams(&out, &errOut)}, &BundleOptions{
		RunID: "child-a",
		Out:   outDir,
	})
	if err != nil {
		t.Fatalf("runBundle returned error: %v", err)
	}
	text := out.String()
	for _, want := range []string{
		"# Bakeoff Related Run Bundle: source",
		"- Report: `" + filepath.Join(outDir, "source", "report.md") + "`",
		"| `child-a` | `dispute` | `gemini` | `escalation_advisory_supported` | `yes` (" + triage.ZeroSelectedMessage + ") | `" + filepath.Join(outDir, "child-a", "report.md") + "` |",
		"| `child-b` | `witness` | `copilot` | `escalation_advisory_challenged` | `failed` (exit_error) | `" + filepath.Join(outDir, "child-b", "report.md") + "` |",
		"run missing triage for `source`",
		"inspect zero-selected triage for `child-a`",
		"retry failed triage for `child-b`",
		"Write this derived report if needed: `bakeoff bundle source --out " + outDir + " --write`",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("bundle output missing %q:\n%s", want, text)
		}
	}
	if _, err := os.Stat(filepath.Join(outDir, "source", "related-report.md")); !os.IsNotExist(err) {
		t.Fatalf("bundle without --write should not create related-report.md, stat err=%v", err)
	}

	out.Reset()
	err = runBundle(context.Background(), bundleTestFactory{streams: output.NewStreams(&out, &errOut)}, &BundleOptions{
		RunID: "source",
		Out:   outDir,
		Write: true,
	})
	if err != nil {
		t.Fatalf("runBundle --write returned error: %v", err)
	}
	written := filepath.Join(outDir, "source", "related-report.md")
	data, err := os.ReadFile(written)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "# Bakeoff Related Run Bundle: source") || !strings.Contains(out.String(), "wrote: "+written) {
		t.Fatalf("write output/data mismatch:\nstdout=%s\nfile=%s", out.String(), string(data))
	}
}

type bundleTestFactory struct {
	streams output.Streams
}

func (f bundleTestFactory) Streams() output.Streams {
	return f.streams
}

func (bundleTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (bundleTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (bundleTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (bundleTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(exec.LookPath)
}

func writeBundleRun(t *testing.T, outDir string, runID string, workOrderType string, decision map[string]any, manifestFields map[string]any) {
	t.Helper()
	runDir := filepath.Join(outDir, runID)
	workOrder := map[string]any{
		"schema_version": 1,
		"id":             runID,
		"type":           workOrderType,
		"goal":           "bundle run",
		"background":     "Find actionable defects.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	}
	if workOrderType == "gather" {
		workOrder["facet"] = map[string]any{"id": "code-review", "kind": "generic", "focus": "Find actionable defects.", "include": []any{"correctness bugs"}}
	}
	writeBundleJSON(t, filepath.Join(runDir, "work-order.json"), workOrder)
	if _, ok := decision["mode"]; !ok {
		decision["mode"] = workOrderType
	}
	if _, ok := decision["judge_ran"]; !ok {
		decision["judge_ran"] = false
	}
	writeBundleJSON(t, filepath.Join(runDir, "decision.json"), decision)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# "+runID+"\n\n## Findings\n\n- **F-001** Something actionable.\n"); err != nil {
		t.Fatal(err)
	}
	writeBundleJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": runID, "type": manifestFields["type"]})
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
	writeBundleJSON(t, filepath.Join(runDir, "manifest.json"), manifestDoc)
}

func writeZeroSelectedTriage(t *testing.T, runDir string) {
	t.Helper()
	hashes, err := triage.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	filter := map[string]any{"included": 0, "skipped_non_actionable": 1, "skipped_out_of_facet": 0}
	writeBundleJSON(t, filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "ok", "source_finding_filter": filter})
	writeBundleJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
		"schema_version":                1,
		"status":                        "complete",
		"summary":                       "No findings selected.",
		"items":                         []any{},
		"input_hashes":                  hashes,
		"source_finding_filter":         filter,
		"triage_participant":            map[string]any{"backend": "claude", "model": "judge"},
		"item_counts_by_classification": map[string]any{},
	})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# triage\n"); err != nil {
		t.Fatal(err)
	}
}

func writeBundleJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
