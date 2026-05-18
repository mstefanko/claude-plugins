package verify

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

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
