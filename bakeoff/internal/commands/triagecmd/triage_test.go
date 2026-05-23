package triagecmd

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

func TestTriageValidatorRejectsUnknownCitationCheckIDs(t *testing.T) {
	validator := triageValidator(
		map[string]bool{"F-001": true},
		map[string]bool{"C-001": true},
		"run-1",
		map[string]string{"decision_sha256": "d"},
		map[string]any{"backend": "claude"},
		map[string]int{"included": 1},
	)
	_, err := validator(map[string]any{
		"schema_version": 1,
		"status":         "complete",
		"summary":        "checked",
		"items": []any{
			map[string]any{
				"id":                  "T-001",
				"source_finding_id":   "F-001",
				"source_finding":      "finding",
				"classification":      "real_issue",
				"severity":            "medium",
				"confidence":          "high",
				"supporting_evidence": []any{},
				"counterevidence":     []any{},
				"citation_check_ids":  []any{"C-999"},
				"recommended_action":  "fix_now",
				"rationale":           "reason",
			},
		},
		"unknowns": []any{},
	})
	if err == nil || !strings.Contains(err.Error(), "citation_check_ids must reference citation_checks") {
		t.Fatalf("expected citation_check_ids validation error, got %v", err)
	}
}

func TestProviderFailureSummariesExposeFailureArtifactPaths(t *testing.T) {
	runDir := t.TempDir()
	writeJSON(t, filepath.Join(runDir, "providers", "codex", "failure.json"), map[string]any{
		"provider_id":   "codex",
		"backend":       "codex",
		"model":         "gpt",
		"status":        "timeout",
		"failure_kind":  "timeout",
		"stderr_tail":   "timed out",
		"raw_artifacts": map[string]any{"stderr": "stderr.txt"},
	})
	failures := providerFailureSummaries(runDir)
	if len(failures) != 1 {
		t.Fatalf("failures = %#v", failures)
	}
	got := failures[0]
	if got["path"] != "providers/codex/failure.json" || got["provider_id"] != "codex" || got["failure_kind"] != "timeout" {
		t.Fatalf("failure summary = %#v", got)
	}
	if raw, ok := got["raw_artifacts"].(map[string]any); !ok || raw["stderr"] != "stderr.txt" {
		t.Fatalf("raw artifacts = %#v", got["raw_artifacts"])
	}
}

func TestForceTriageProviderFailurePreservesPreviousTriage(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	fakeClaude := filepath.Join(fakeBin, "claude")
	if err := os.WriteFile(fakeClaude, []byte("#!/bin/sh\nprintf 'not json'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	runDir := filepath.Join(root, "runs", "r1")
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "triage-force",
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
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "structured_union", "judge_ran": true})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "cwd": root})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n\n## Findings\n\n- **F-001** bug in file.go:1\n"); err != nil {
		t.Fatal(err)
	}
	oldFinal := map[string]any{"summary": "old triage", "input_hashes": map[string]any{}}
	writeJSON(t, filepath.Join(runDir, "triage", "final.json"), oldFinal)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# old triage\n"); err != nil {
		t.Fatal(err)
	}

	exitCode, err := Run(context.Background(), testFactory{}, &TriageOptions{
		RunID:  "r1",
		Out:    filepath.Join(root, "runs"),
		Force:  true,
		JSON:   true,
		RunDir: runDir,
	})
	if err != nil {
		t.Fatal(err)
	}
	if exitCode != 1 {
		t.Fatalf("exitCode = %d", exitCode)
	}
	data, err := os.ReadFile(filepath.Join(runDir, "triage", "triage.md"))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "# old triage\n" {
		t.Fatalf("previous triage was not preserved: %q", string(data))
	}
	final, err := workorder.ReadRequiredObject(filepath.Join(runDir, "triage", "final.json"))
	if err != nil {
		t.Fatal(err)
	}
	if final["summary"] != "old triage" {
		t.Fatalf("final.json was replaced: %#v", final)
	}
}

func TestForceTriageSuccessArchivesPreviousTriage(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	fakeClaude := filepath.Join(fakeBin, "claude")
	if err := os.WriteFile(fakeClaude, []byte("#!/bin/sh\ncat >/dev/null\nprintf '<final_json>{\"schema_version\":1,\"status\":\"complete\",\"summary\":\"new triage\",\"items\":[],\"unknowns\":[]}</final_json>\\n'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))

	runDir := filepath.Join(root, "runs", "r1")
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "triage-force",
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
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "structured_union", "judge_ran": true})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "cwd": root})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n\n## Findings\n\n- **F-001** bug in file.go:1\n"); err != nil {
		t.Fatal(err)
	}
	writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{"summary": "old triage", "input_hashes": map[string]any{}})
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# old triage\n"); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	exitCode, err := Run(context.Background(), testFactory{streams: output.NewStreams(&out, &errOut)}, &TriageOptions{
		RunID:  "r1",
		Out:    filepath.Join(root, "runs"),
		Force:  true,
		RunDir: runDir,
	})
	if err != nil {
		t.Fatal(err)
	}
	if exitCode != 0 {
		t.Fatalf("exitCode = %d", exitCode)
	}
	archives, err := filepath.Glob(filepath.Join(runDir, "triage.failed-*"))
	if err != nil {
		t.Fatal(err)
	}
	if len(archives) != 1 {
		t.Fatalf("archives = %#v", archives)
	}
	if data, err := os.ReadFile(filepath.Join(archives[0], "triage.md")); err != nil || string(data) != "# old triage\n" {
		t.Fatalf("archived old triage data=%q err=%v", string(data), err)
	}
	final, err := workorder.ReadRequiredObject(filepath.Join(runDir, "triage", "final.json"))
	if err != nil {
		t.Fatal(err)
	}
	if final["summary"] != "new triage" {
		t.Fatalf("new final.json = %#v", final)
	}
	if !strings.Contains(out.String(), "archived prior triage to ") {
		t.Fatalf("missing archive notice:\nstdout=%s\nstderr=%s", out.String(), errOut.String())
	}
	latest, err := os.Readlink(filepath.Join(root, "runs", "latest"))
	if err == nil && latest != "r1" {
		t.Fatalf("latest symlink = %q", latest)
	}
	if err != nil {
		data, readErr := os.ReadFile(filepath.Join(root, "runs", "latest"))
		if readErr != nil {
			t.Fatal(readErr)
		}
		if data := strings.TrimSpace(string(data)); data != "r1" {
			t.Fatalf("latest file = %q", data)
		}
	}
}

type testFactory struct {
	streams output.Streams
}

func (f testFactory) Streams() output.Streams {
	if f.streams.Out != nil {
		return f.streams
	}
	return output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})
}

func (testFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (testFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (testFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (testFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(exec.LookPath)
}

func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
