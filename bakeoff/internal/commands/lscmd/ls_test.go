package lscmd

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type testFactory struct {
	streams output.Streams
}

func (f testFactory) Streams() output.Streams {
	return f.streams
}

func (f testFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f testFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f testFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f testFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

var _ commands.Factory = testFactory{}

func TestHistorySortsLimitsAndSummarizesDisplayedRows(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	writeRun(t, outDir, runSpec{
		ID:         "old-run",
		Type:       "gather",
		FinishedAt: "2026-05-19T10:00:00Z",
		Decision:   "structured_union",
		Triage:     "no",
		Goal:       "Old goal",
	})
	writeRun(t, outDir, runSpec{
		ID:         "new-run",
		Type:       "build",
		FinishedAt: "2026-05-20T10:00:00Z",
		Decision:   "pick_winner",
		Triage:     "yes",
		Goal:       "New goal with a | pipe and extra whitespace\nfor table safety",
	})
	writeRun(t, outDir, runSpec{
		ID:         "missing-finished",
		Type:       "compare",
		FinishedAt: "",
		Decision:   "consensus",
		Triage:     "no",
		Goal:       "Undated goal",
	})

	var stdout bytes.Buffer
	f := testFactory{streams: output.NewStreams(&stdout, &bytes.Buffer{})}
	err := runLs(context.Background(), f, &LsOptions{Out: outDir, History: true, Limit: 2, LimitSet: true})
	if err != nil {
		t.Fatal(err)
	}
	got := stdout.String()
	for _, want := range []string{
		"Recent Bakeoff runs (3 total, showing 2 newest):",
		"| 2026-05-20 10:00 | new-run | build | - | pick_winner | no | New goal with a \\| pipe and extra whitespace for table safety |",
		"| 2026-05-19 10:00 | old-run | gather | - | structured_union | no | Old goal |",
		"Open one with `/bakeoff:inspect <run-id>`.",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("history output missing %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "missing-finished") {
		t.Fatalf("limited history included undated row:\n%s", got)
	}
	if strings.Index(got, "new-run") > strings.Index(got, "old-run") {
		t.Fatalf("history not sorted newest first:\n%s", got)
	}
}

func TestLimitAppliesAfterRecentSortForJSON(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	writeRun(t, outDir, runSpec{ID: "older", Type: "gather", FinishedAt: "2026-05-19T10:00:00Z", Decision: "structured_union", Triage: "no", Goal: "older"})
	writeRun(t, outDir, runSpec{ID: "newer", Type: "build", FinishedAt: "2026-05-20T10:00:00Z", Decision: "pick_winner", Triage: "no", Goal: "newer"})

	var stdout bytes.Buffer
	f := testFactory{streams: output.NewStreams(&stdout, &bytes.Buffer{})}
	err := runLs(context.Background(), f, &LsOptions{Out: outDir, JSON: true, Limit: 1, LimitSet: true})
	if err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Runs []map[string]any `json:"runs"`
	}
	if err := json.Unmarshal(stdout.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Runs) != 1 || payload.Runs[0]["run_id"] != "newer" {
		t.Fatalf("json rows = %#v", payload.Runs)
	}
}

type runSpec struct {
	ID         string
	Type       string
	FinishedAt string
	Decision   string
	Triage     string
	Goal       string
}

func writeRun(t *testing.T, outDir string, spec runSpec) {
	t.Helper()
	runDir := filepath.Join(outDir, spec.ID)
	if err := os.MkdirAll(runDir, 0o700); err != nil {
		t.Fatal(err)
	}
	writeJSON(t, filepath.Join(runDir, "manifest.json"), map[string]any{
		"schema_version": manifest.SchemaVersion,
		"run_id":         spec.ID,
		"type":           spec.Type,
		"facet_id":       nil,
		"decision_kind":  spec.Decision,
		"finished_at":    spec.FinishedAt,
		"artifacts":      map[string]string{"report": "report.md"},
		"triage":         map[string]any{"state": spec.Triage},
	})
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             spec.ID,
		"type":           spec.Type,
		"goal":           spec.Goal,
	})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
}

func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
