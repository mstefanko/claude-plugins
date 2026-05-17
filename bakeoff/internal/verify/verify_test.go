package verify

import (
	"path/filepath"
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
}
