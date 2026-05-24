package verify

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	triagepkg "github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestVerifyFingerprintEntry(t *testing.T) {
	runDir := t.TempDir()
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	size, sha, err := workorder.FileFingerprint(filepath.Join(runDir, "report.md"))
	if err != nil {
		t.Fatal(err)
	}

	if got := VerifyFingerprintEntry(runDir, "report.md", map[string]any{"size_bytes": size, "sha256": sha}); got != "" {
		t.Fatalf("matching fingerprint = %q", got)
	}
	if got := VerifyFingerprintEntry(runDir, "report.md", map[string]any{"size_bytes": size + 1, "sha256": sha}); got != "sha256_or_size" {
		t.Fatalf("mismatched fingerprint = %q", got)
	}
	if got := VerifyFingerprintEntry(runDir, "missing.md", map[string]any{"size_bytes": 0, "sha256": sha}); got != "missing" {
		t.Fatalf("missing fingerprint = %q", got)
	}
	for _, relative := range []string{"../../../etc/passwd", "/etc/passwd", "providers/claude/../../../etc/passwd", ""} {
		if got := VerifyFingerprintEntry(runDir, relative, map[string]any{"size_bytes": size, "sha256": sha}); got != "invalid" {
			t.Fatalf("unsafe fingerprint %q = %q", relative, got)
		}
	}
}

func TestRunRejectsUnsafeManifestPaths(t *testing.T) {
	runDir := t.TempDir()
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), `{"type":"gather"}`); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "decision.json"), `{}`); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	manifestText := `{
  "schema_version": 1,
  "run_id": "` + filepath.Base(runDir) + `",
  "artifact_fingerprints": {
    "../../../etc/passwd": {"sha256": "abc", "size_bytes": 1}
  }
}`
	if err := os.WriteFile(filepath.Join(runDir, "manifest.json"), []byte(manifestText), 0o600); err != nil {
		t.Fatal(err)
	}

	result := Run(runDir, "runs")
	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d", result.ExitCode)
	}
	if len(result.Problems) == 0 || !strings.Contains(strings.Join(result.Problems, "\n"), "unsafe manifest path: ../../../etc/passwd") {
		t.Fatalf("unsafe path problem missing: %#v", result.Problems)
	}
}

func TestRunNextRoutesTriageArtifactStates(t *testing.T) {
	tests := []struct {
		name      string
		outDir    string
		arrange   func(t *testing.T, runDir string)
		wantState string
		wantNext  string
	}{
		{
			name:      "stale",
			outDir:    "custom-runs",
			arrange:   writeStaleTriage,
			wantState: "stale",
			wantNext:  "bakeoff triage RUN_ID --out custom-runs --force",
		},
		{
			name:      "yes",
			outDir:    "runs",
			arrange:   writeCurrentTriage,
			wantState: "yes",
			wantNext:  "bakeoff show RUN_ID --triage",
		},
		{
			name:      "dry_run",
			outDir:    "runs",
			arrange:   writeDryRunTriageStatus,
			wantState: "dry_run",
			wantNext:  "bakeoff triage RUN_ID --force",
		},
		{
			name:      "failed",
			outDir:    "runs",
			arrange:   writeFailedTriageStatus,
			wantState: "failed",
			wantNext:  "bakeoff triage RUN_ID --force",
		},
		{
			name:      "no",
			outDir:    "runs",
			arrange:   func(t *testing.T, runDir string) {},
			wantState: "no",
			wantNext:  "bakeoff show RUN_ID",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := writeVerifyBaseRun(t)
			tt.arrange(t, runDir)

			result := Run(runDir, tt.outDir)
			if result.ExitCode != 0 {
				t.Fatalf("ExitCode = %d, problems = %#v", result.ExitCode, result.Problems)
			}
			if result.Triage.State != tt.wantState {
				t.Fatalf("Triage.State = %q, want %q", result.Triage.State, tt.wantState)
			}
			wantNext := strings.ReplaceAll(tt.wantNext, "RUN_ID", filepath.Base(runDir))
			if result.Next != wantNext {
				t.Fatalf("Next = %q, want %q", result.Next, wantNext)
			}
		})
	}
}

func TestRunNextErrorPathsUnchanged(t *testing.T) {
	t.Run("rerun when work order exists", func(t *testing.T) {
		runDir := t.TempDir()
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), map[string]any{"type": "gather"}); err != nil {
			t.Fatal(err)
		}

		result := Run(runDir, "runs")
		if result.ExitCode == 0 {
			t.Fatalf("ExitCode = 0, want failure")
		}
		want := "bakeoff rerun " + filepath.Base(runDir)
		if result.Next != want {
			t.Fatalf("Next = %q, want %q", result.Next, want)
		}
	})

	t.Run("restore message when work order missing", func(t *testing.T) {
		runDir := t.TempDir()

		result := Run(runDir, "runs")
		if result.ExitCode == 0 {
			t.Fatalf("ExitCode = 0, want failure")
		}
		const want = "restore the listed artifacts or rerun the original work order"
		if result.Next != want {
			t.Fatalf("Next = %q, want %q", result.Next, want)
		}
	})
}

func writeVerifyBaseRun(t *testing.T) string {
	t.Helper()
	runDir := t.TempDir()
	for relative, value := range map[string]any{
		"work-order.json": map[string]any{"type": "gather"},
		"decision.json":   map[string]any{"decision_kind": "winner"},
		"meta.json":       map[string]any{"type": "gather"},
		"manifest.json": map[string]any{
			"schema_version":        1,
			"run_id":                filepath.Base(runDir),
			"type":                  "gather",
			"artifact_fingerprints": map[string]any{},
		},
	} {
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, relative), value); err != nil {
			t.Fatal(err)
		}
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	return runDir
}

func writeCurrentTriage(t *testing.T, runDir string) {
	t.Helper()
	hashes, err := triagepkg.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	writeTriageArtifacts(t, runDir, hashes)
}

func writeStaleTriage(t *testing.T, runDir string) {
	t.Helper()
	hashes, err := triagepkg.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	hashes["decision_sha256"] = "stale"
	writeTriageArtifacts(t, runDir, hashes)
}

func writeTriageArtifacts(t *testing.T, runDir string, hashes map[string]string) {
	t.Helper()
	triageDir := filepath.Join(runDir, "triage")
	if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "final.json"), map[string]any{"input_hashes": hashes}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(triageDir, "triage.md"), "# triage\n"); err != nil {
		t.Fatal(err)
	}
}

func writeDryRunTriageStatus(t *testing.T, runDir string) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "dry_run"}); err != nil {
		t.Fatal(err)
	}
}

func writeFailedTriageStatus(t *testing.T, runDir string) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "exit_error"}); err != nil {
		t.Fatal(err)
	}
}
