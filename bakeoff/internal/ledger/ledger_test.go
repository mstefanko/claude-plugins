package ledger

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestMakeRunIDAndValidateRunID(t *testing.T) {
	got := MakeRunID(time.Date(2026, 5, 16, 12, 0, 0, 0, time.UTC), "abcdef")
	if got != "2026-05-16-abcd" {
		t.Fatalf("run id = %q", got)
	}
	if err := ValidateRunID("2026-05-16-abcd"); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"latest", ".", "..", "../escape"} {
		if err := ValidateRunID(id); err == nil {
			t.Fatalf("ValidateRunID(%q) unexpectedly succeeded", id)
		}
	}
}

func TestResolveLatestFromFile(t *testing.T) {
	out := t.TempDir()
	runDir := filepath.Join(out, "run-1")
	if err := os.Mkdir(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(out, "latest"), []byte("run-1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	resolved, err := ResolveRunDir(out, "latest")
	if err != nil {
		t.Fatal(err)
	}
	if resolved != runDir {
		t.Fatalf("resolved = %q, want %q", resolved, runDir)
	}
}

func TestEnsureChildPathRejectsEscape(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "runs")
	if err := EnsureChildPath(parent, filepath.Dir(parent)); err == nil {
		t.Fatal("expected escape to be rejected")
	}
}
