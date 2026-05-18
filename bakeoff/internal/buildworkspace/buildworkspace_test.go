package buildworkspace

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestResolveRepositoryRejectsDirtyAndSubmoduleSources(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, false)

	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	if repo.Root != repoDir || repo.BaseCommit == "" || !repo.SourceClean {
		t.Fatalf("repo metadata = %#v", repo)
	}

	if err := os.WriteFile(filepath.Join(repoDir, "scratch.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = ResolveRepository(ctx, repoDir, "HEAD")
	if err == nil || !strings.Contains(err.Error(), "source checkout is dirty") {
		t.Fatalf("expected dirty checkout rejection, got %v", err)
	}
	if err := os.Remove(filepath.Join(repoDir, "scratch.txt")); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(filepath.Join(repoDir, ".gitmodules"), []byte("[submodule \"x\"]\n\tpath = x\n\turl = ./x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, repoDir, "add", ".gitmodules")
	git(t, repoDir, "commit", "-m", "add gitmodules")
	_, err = ResolveRepository(ctx, repoDir, "HEAD")
	if err == nil || !strings.Contains(err.Error(), ".gitmodules") {
		t.Fatalf("expected submodule rejection, got %v", err)
	}
}

func TestResolveRepositoryRejectsUnsafeBaseRefs(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, false)
	for _, baseRef := range []string{"HEAD@{1}", "main..feature", "HEAD:path", "HEAD\x00"} {
		_, err := ResolveRepository(ctx, repoDir, baseRef)
		if err == nil {
			t.Fatalf("expected %q to be rejected", baseRef)
		}
	}
}

func TestPrepareWorktreeParentUsesIgnoredPathOrFallback(t *testing.T) {
	ctx := context.Background()
	ignoredRepo := initGitRepo(t, true)
	ignored, err := ResolveRepository(ctx, ignoredRepo, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, ignored, filepath.Join(ignoredRepo, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	if !parent.InsideSource || !parent.InsideIgnoredSource || parent.FallbackUsed {
		t.Fatalf("ignored parent metadata = %#v", parent)
	}

	trackedIgnoredRepo := initGitRepo(t, true)
	if err := os.MkdirAll(filepath.Join(trackedIgnoredRepo, "runs"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(trackedIgnoredRepo, "runs", "kept.txt"), []byte("tracked\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, trackedIgnoredRepo, "add", "-f", "runs/kept.txt")
	git(t, trackedIgnoredRepo, "commit", "-m", "track runs")
	trackedIgnored, err := ResolveRepository(ctx, trackedIgnoredRepo, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err = PrepareWorktreeParent(ctx, trackedIgnored, filepath.Join(trackedIgnoredRepo, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(parent.Path)
	if !parent.FallbackUsed || parent.InsideSource {
		t.Fatalf("tracked ignored parent should fall back, got %#v", parent)
	}

	trackedRepo := initGitRepo(t, false)
	tracked, err := ResolveRepository(ctx, trackedRepo, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err = PrepareWorktreeParent(ctx, tracked, filepath.Join(trackedRepo, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(parent.Path)
	if parent.InsideSource || parent.InsideIgnoredSource || !parent.FallbackUsed {
		t.Fatalf("fallback parent metadata = %#v", parent)
	}
}

func TestCreateCaptureAndCleanupDetachedWorktree(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, true)
	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, repo, filepath.Join(repoDir, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	worktreePath := filepath.Join(parent.Path, "claude")
	if err := CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(filepath.Join(worktreePath, "README.md"), []byte("updated\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(worktreePath, "script.sh"), []byte("#!/bin/sh\necho ok\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	captureDir := filepath.Join(repoDir, "runs", "run-1", "providers", "claude", "build")
	capture, err := CaptureChanges(ctx, CaptureOptions{WorktreePath: worktreePath, BaseCommit: repo.BaseCommit, OutputDir: captureDir, PatchMaxBytes: 100000})
	if err != nil {
		t.Fatal(err)
	}
	if !capture.ProviderHeadIsBase || capture.ProviderCommittedChanges || capture.PatchBytes == 0 || capture.PatchOverCap {
		t.Fatalf("capture metadata = %#v", capture)
	}
	if len(capture.ChangedFiles) != 2 {
		t.Fatalf("changed files = %#v", capture.ChangedFiles)
	}
	patch, err := os.ReadFile(capture.PatchPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(patch), "new file mode 100755") {
		t.Fatalf("patch did not preserve executable mode:\n%s", patch)
	}

	cleanup := CleanupWorktree(ctx, repo, worktreePath, false)
	if cleanup.Status != "removed" || !cleanup.GitWorktreeRemoved || !cleanup.FilesystemPathRemoved {
		t.Fatalf("cleanup = %#v", cleanup)
	}
	if _, err := os.Stat(worktreePath); !os.IsNotExist(err) {
		t.Fatalf("worktree path still exists or stat failed unexpectedly: %v", err)
	}
}

func TestCaptureProviderCommitAndPatchCap(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, true)
	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, repo, filepath.Join(repoDir, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	worktreePath := filepath.Join(parent.Path, "codex")
	if err := CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}
	defer CleanupWorktree(ctx, repo, worktreePath, false)

	if err := os.WriteFile(filepath.Join(worktreePath, "README.md"), []byte("provider commit\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, worktreePath, "add", "README.md")
	git(t, worktreePath, "commit", "-m", "provider commit")

	capture, err := CaptureChanges(ctx, CaptureOptions{WorktreePath: worktreePath, BaseCommit: repo.BaseCommit, PatchMaxBytes: 1})
	if err != nil {
		t.Fatal(err)
	}
	if capture.ProviderHeadIsBase || !capture.ProviderCommittedChanges || !capture.PatchOverCap {
		t.Fatalf("capture metadata = %#v", capture)
	}

	subdir := filepath.Join(worktreePath, "nested")
	if err := os.MkdirAll(subdir, 0o755); err != nil {
		t.Fatal(err)
	}
	_, err = CaptureChanges(ctx, CaptureOptions{WorktreePath: subdir, BaseCommit: repo.BaseCommit, PatchMaxBytes: 100000})
	if err == nil || !strings.Contains(err.Error(), "git worktree root") {
		t.Fatalf("expected worktree root error, got %v", err)
	}
}

func TestCaptureFlagsGitlinkChanges(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, true)
	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, repo, filepath.Join(repoDir, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	worktreePath := filepath.Join(parent.Path, "gitlink")
	if err := CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}
	defer CleanupWorktree(ctx, repo, worktreePath, false)

	modulePath := filepath.Join(worktreePath, "module")
	if err := os.MkdirAll(modulePath, 0o755); err != nil {
		t.Fatal(err)
	}
	git(t, modulePath, "init")
	git(t, modulePath, "config", "core.hooksPath", ".git/hooks")
	git(t, modulePath, "config", "user.email", "bakeoff@example.com")
	git(t, modulePath, "config", "user.name", "Bakeoff Test")
	if err := os.WriteFile(filepath.Join(modulePath, "README.md"), []byte("nested\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, modulePath, "add", ".")
	git(t, modulePath, "commit", "-m", "nested")
	capture, err := CaptureChanges(ctx, CaptureOptions{WorktreePath: worktreePath, BaseCommit: repo.BaseCommit, PatchMaxBytes: 100000})
	if err != nil {
		t.Fatal(err)
	}
	if !capture.GitlinkChangeRejected {
		t.Fatalf("expected gitlink rejection metadata, got %#v", capture)
	}
}

func TestLockAndGitlinkHelpers(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, false)
	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	lock, err := AcquireLock(ctx, repo.CommonDir, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, err = AcquireLock(ctx, repo.CommonDir, 50*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "another build run is active") {
		t.Fatalf("expected active lock error, got %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}
	lock, err = AcquireLock(ctx, repo.CommonDir, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}

	emptyLockPath := filepath.Join(repo.CommonDir, lockFileName)
	if err := os.WriteFile(emptyLockPath, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = AcquireLock(ctx, repo.CommonDir, 50*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "another build run is active") {
		t.Fatalf("fresh empty lock should not be stolen, got %v", err)
	}
	old := time.Now().Add(-lockStaleAfter - time.Minute)
	if err := os.Chtimes(emptyLockPath, old, old); err != nil {
		t.Fatal(err)
	}
	lock, err = AcquireLock(ctx, repo.CommonDir, time.Second)
	if err != nil {
		t.Fatalf("expected stale empty lock to be replaced: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(emptyLockPath, []byte(fmt.Sprintf("pid=%d\ncreated_at=2000-01-01T00:00:00Z\n", os.Getpid())), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(emptyLockPath, old, old); err != nil {
		t.Fatal(err)
	}
	lock, err = AcquireLock(ctx, repo.CommonDir, time.Second)
	if err != nil {
		t.Fatalf("expected stale current-pid lock to be replaced by mtime sanity: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}

	deadPID := 99999999
	if alive, known := processAlive(deadPID); !known || alive {
		t.Skipf("cannot prove test PID %d is dead on this platform", deadPID)
	}
	if err := os.WriteFile(filepath.Join(repo.CommonDir, lockFileName), []byte("pid=99999999\ncreated_at=2000-01-01T00:00:00Z\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	lock, err = AcquireLock(ctx, repo.CommonDir, time.Second)
	if err != nil {
		t.Fatalf("expected stale lock to be replaced: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}

	raw := ":160000 160000 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb M\tmodule\n"
	if !HasGitlinkDiff(raw) {
		t.Fatal("expected gitlink diff detection")
	}
}

func TestCleanupCanRetainWorktree(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, true)
	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, repo, filepath.Join(repoDir, "runs", "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	worktreePath := filepath.Join(parent.Path, "retained")
	if err := CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}
	retained := CleanupWorktree(ctx, repo, worktreePath, true)
	if retained.Status != "retained" || !retained.Retained {
		t.Fatalf("retained cleanup = %#v", retained)
	}
	removed := CleanupWorktree(ctx, repo, worktreePath, false)
	if removed.Status != "removed" {
		t.Fatalf("final cleanup = %#v", removed)
	}

	orphan := filepath.Join(t.TempDir(), "orphan-worktree-path")
	if err := os.MkdirAll(orphan, 0o755); err != nil {
		t.Fatal(err)
	}
	failed := CleanupWorktree(ctx, Repository{Root: filepath.Join(repoDir, "missing")}, orphan, false)
	if failed.Status != "failed" || failed.Error == "" || !failed.FilesystemPathRemoved {
		t.Fatalf("cleanup failure metadata = %#v", failed)
	}

	missing := filepath.Join(t.TempDir(), "missing-worktree-path")
	missingResult := CleanupWorktree(ctx, Repository{Root: filepath.Join(repoDir, "missing")}, missing, false)
	if missingResult.Status != "failed" || missingResult.FilesystemPathRemoved {
		t.Fatalf("missing cleanup metadata = %#v", missingResult)
	}
}

func initGitRepo(t *testing.T, ignoreRuns bool) string {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not available")
	}
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	git(t, dir, "init")
	git(t, dir, "config", "core.hooksPath", ".git/hooks")
	git(t, dir, "config", "user.email", "bakeoff@example.com")
	git(t, dir, "config", "user.name", "Bakeoff Test")
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("base\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if ignoreRuns {
		if err := os.WriteFile(filepath.Join(dir, ".gitignore"), []byte("runs/\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	git(t, dir, "add", ".")
	git(t, dir, "commit", "-m", "initial")
	return dir
}

func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, out)
	}
	return string(out)
}
