package ledger

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
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

func TestValidateLookupRunIDAllowsLatestOnlyAsLookupAlias(t *testing.T) {
	if err := ValidateLookupRunID("latest"); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"../escape", "/tmp/run", "nested/run"} {
		if err := ValidateLookupRunID(id); err == nil {
			t.Fatalf("ValidateLookupRunID(%q) unexpectedly succeeded", id)
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

func TestResolveLatestFromSymlink(t *testing.T) {
	out := t.TempDir()
	runDir := filepath.Join(out, "run-1")
	if err := os.Mkdir(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("run-1", filepath.Join(out, "latest")); err != nil {
		t.Skipf("symlink not available: %v", err)
	}
	resolved, err := ResolveRunDir(out, "latest")
	if err != nil {
		t.Fatal(err)
	}
	if resolved != runDir {
		t.Fatalf("resolved = %q, want %q", resolved, runDir)
	}
}

func TestUpdateLatestConcurrent(t *testing.T) {
	out := t.TempDir()
	const runCount = 64
	known := make(map[string]string, runCount)
	for i := 0; i < runCount; i++ {
		runID := fmt.Sprintf("run-%02d", i)
		runDir := filepath.Join(out, runID)
		if err := os.Mkdir(runDir, 0o755); err != nil {
			t.Fatal(err)
		}
		known[runID] = runDir
	}

	var wg sync.WaitGroup
	errs := make(chan error, runCount)
	for runID := range known {
		wg.Add(1)
		go func() {
			defer wg.Done()
			errs <- UpdateLatest(out, runID)
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatalf("UpdateLatest returned error: %v", err)
		}
	}

	resolved, err := ResolveRunDir(out, "latest")
	if err != nil {
		t.Fatal(err)
	}
	runID := filepath.Base(resolved)
	if known[runID] != resolved {
		t.Fatalf("latest resolved to %q, want one of %v", resolved, known)
	}
	if _, err := os.Lstat(filepath.Join(out, ".latest.tmp")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf(".latest.tmp artifact err = %v, want not exist", err)
	}
	matches, err := filepath.Glob(filepath.Join(out, ".latest.*.tmp"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 0 {
		t.Fatalf("temporary latest artifacts remain: %v", matches)
	}
}

func TestUpdateLatestFileFallbackWritesCompleteLatest(t *testing.T) {
	originalSymlink := latestSymlink
	latestSymlink = func(string, string) error {
		return errors.New("symlink unsupported")
	}
	defer func() {
		latestSymlink = originalSymlink
	}()

	out := t.TempDir()
	for _, runID := range []string{"run-old", "run-new"} {
		if err := os.Mkdir(filepath.Join(out, runID), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(out, "latest"), []byte("run-old\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	if err := UpdateLatest(out, "run-new"); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(out, "latest"))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "run-new\n" {
		t.Fatalf("latest contents = %q, want complete fallback file", string(data))
	}
	resolved, err := ResolveRunDir(out, "latest")
	if err != nil {
		t.Fatal(err)
	}
	if resolved != filepath.Join(out, "run-new") {
		t.Fatalf("resolved = %q, want run-new", resolved)
	}
	matches, err := filepath.Glob(filepath.Join(out, ".latest.*.tmp"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 0 {
		t.Fatalf("temporary latest artifacts remain: %v", matches)
	}
}

func TestResolveLatestRejectsPathTarget(t *testing.T) {
	out := t.TempDir()
	if err := os.WriteFile(filepath.Join(out, "latest"), []byte("../escape\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveRunDir(out, "latest"); err == nil {
		t.Fatal("expected latest path target to be rejected")
	}
}

func TestResolveLatestRejectsAbsoluteSymlinkTarget(t *testing.T) {
	out := t.TempDir()
	target := filepath.Join(t.TempDir(), "run-1")
	if err := os.Mkdir(target, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(out, "latest")); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveRunDir(out, "latest"); err == nil {
		t.Fatal("expected latest absolute symlink target to be rejected")
	}
}

func TestResolveRunDirRejectsSymlinkEscape(t *testing.T) {
	out := t.TempDir()
	target := filepath.Join(t.TempDir(), "run-1")
	if err := os.Mkdir(target, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(out, "run-1")); err != nil {
		t.Skipf("symlink not available: %v", err)
	}
	if _, err := ResolveRunDir(out, "run-1"); err == nil {
		t.Fatal("expected symlinked run directory outside --out to be rejected")
	}
}

func TestEnsureChildPathRejectsEscape(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "runs")
	if err := EnsureChildPath(parent, filepath.Dir(parent)); err == nil {
		t.Fatal("expected escape to be rejected")
	}
}

func TestEnsureChildPathRejectsSymlinkEscape(t *testing.T) {
	parent := t.TempDir()
	target := t.TempDir()
	link := filepath.Join(parent, "run-1")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink not available: %v", err)
	}
	if err := EnsureChildPath(parent, link); err == nil {
		t.Fatal("expected symlink escape to be rejected")
	}
}
