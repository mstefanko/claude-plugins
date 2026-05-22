package ledger

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
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

func TestUpdateLatestConcurrentCLIResearch(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping CLI process concurrency test in short mode")
	}

	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	repoRoot := filepath.Clean(filepath.Join(cwd, "..", ".."))
	temp := t.TempDir()
	binary := filepath.Join(temp, "bakeoff")
	build := exec.Command("go", "build", "-o", binary, "./cmd/bakeoff")
	build.Dir = repoRoot
	build.Env = append(os.Environ(), "GOCACHE="+filepath.Join(temp, "go-cache"))
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("go build failed: %v\n%s", err, output)
	}

	workOrderPath := filepath.Join(temp, "gather.work-order.json")
	workOrder := map[string]any{
		"schema_version": 1,
		"id":             "cli-latest-concurrency",
		"type":           "gather",
		"goal":           "Gather a fake concurrency fact.",
		"background":     "CLI-level smoke test for concurrent latest updates.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 20, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}
	workOrderBytes, err := json.MarshalIndent(workOrder, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(workOrderPath, append(workOrderBytes, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}

	out := filepath.Join(temp, "runs")
	fakeBin := filepath.Join(repoRoot, "tests", "parity", "fakes")
	const runCount = 8
	known := make(map[string]string, runCount)
	errs := make(chan error, runCount)
	var wg sync.WaitGroup
	for i := 0; i < runCount; i++ {
		runID := fmt.Sprintf("cli-run-%02d", i)
		known[runID] = filepath.Join(out, runID)
		wg.Add(1)
		go func() {
			defer wg.Done()
			cmd := exec.Command(binary, "research", workOrderPath, "--out", out, "--run-id", runID, "--json", "--quiet", "--no-triage", "--no-repo-layout")
			cmd.Dir = repoRoot
			cmd.Env = withPath(os.Environ(), fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
			output, err := cmd.CombinedOutput()
			if err != nil {
				errs <- fmt.Errorf("%s failed: %w\n%s", runID, err, output)
				return
			}
			errs <- nil
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}

	for runID, runDir := range known {
		for _, name := range []string{"manifest.json", "decision.json", "report.md"} {
			if _, err := os.Stat(filepath.Join(runDir, name)); err != nil {
				t.Fatalf("%s missing %s: %v", runID, name, err)
			}
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
	matches, err := filepath.Glob(filepath.Join(out, ".latest.*.tmp"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 0 {
		t.Fatalf("temporary latest artifacts remain: %v", matches)
	}
}

func withPath(env []string, value string) []string {
	out := make([]string, 0, len(env)+1)
	for _, entry := range env {
		if strings.HasPrefix(entry, "PATH=") {
			continue
		}
		out = append(out, entry)
	}
	return append(out, "PATH="+value)
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
