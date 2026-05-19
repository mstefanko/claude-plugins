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

func TestResolveRepositoryRecordsDirtyAndSubmoduleSources(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, false)

	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	if repo.Root != repoDir || repo.BaseCommit == "" || !repo.SourceClean || repo.InvocationRelPath != "." {
		t.Fatalf("repo metadata = %#v", repo)
	}

	if err := os.WriteFile(filepath.Join(repoDir, "scratch.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	repo, err = ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	if repo.SourceClean || repo.SourceDirtyCount != 1 || len(repo.SourceDirtyEntries) != 1 || repo.SourceDirtyEntries[0].Path != "scratch.txt" {
		t.Fatalf("expected dirty source metadata, got %#v", repo)
	}
	if err := os.Remove(filepath.Join(repoDir, "scratch.txt")); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(filepath.Join(repoDir, ".gitmodules"), []byte("[submodule \"x\"]\n\tpath = x\n\turl = ./x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, repoDir, "add", ".gitmodules")
	git(t, repoDir, "commit", "-m", "add gitmodules")
	git(t, repoDir, "update-index", "--add", "--cacheinfo", "160000,1111111111111111111111111111111111111111,submodules/example")
	git(t, repoDir, "commit", "-m", "add gitlink")
	repo, err = ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	if !repo.SourceHasGitmodules || repo.SourceGitlinkCount != 1 || len(repo.SourceGitlinkEntries) != 1 || repo.SourceGitlinkEntries[0].Path != "submodules/example" {
		t.Fatalf("expected submodule source metadata, got %#v", repo)
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
	if err := os.WriteFile(filepath.Join(worktreePath, "asset.bin"), []byte{0x00, 0x01, 0x02, 0x03}, 0o644); err != nil {
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
	if len(capture.ChangedFiles) != 3 {
		t.Fatalf("changed files = %#v", capture.ChangedFiles)
	}
	patch, err := os.ReadFile(capture.PatchPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(patch), "new file mode 100755") {
		t.Fatalf("patch did not preserve executable mode:\n%s", patch)
	}
	if !strings.Contains(string(patch), "GIT binary patch") {
		t.Fatalf("patch did not preserve binary patch:\n%s", patch)
	}
	changedFiles, err := os.ReadFile(capture.ChangedFilesPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(changedFiles), "A\tasset.bin\n") {
		t.Fatalf("changed-files artifact missing binary addition:\n%s", changedFiles)
	}
	diffstat, err := os.ReadFile(capture.DiffstatPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(diffstat), "asset.bin") {
		t.Fatalf("diffstat artifact missing binary addition:\n%s", diffstat)
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

func TestNameStatusFromRawDiff(t *testing.T) {
	cases := []struct {
		name string
		raw  string
		want []ChangedFile
	}{
		{
			name: "modify and add",
			raw: ":100644 100644 abc def M\tfile.go\n" +
				":000000 100644 000 abc A\tnew.go\n",
			want: []ChangedFile{
				{Status: "M", Path: "file.go"},
				{Status: "A", Path: "new.go"},
			},
		},
		{
			name: "rename",
			raw:  ":100644 100644 abc def R100\told.go\tnew.go\n",
			want: []ChangedFile{{Status: "R100", Path: "old.go -> new.go", OldPath: "old.go", NewPath: "new.go"}},
		},
		{
			name: "delete",
			raw:  ":100644 000000 abc 000 D\tremoved.go\n",
			want: []ChangedFile{{Status: "D", Path: "removed.go"}},
		},
		{
			name: "empty",
			raw:  "",
			want: []ChangedFile{},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseNameStatus(nameStatusFromRawDiff(tc.raw))
			if len(got) != len(tc.want) {
				t.Fatalf("got %#v, want %#v", got, tc.want)
			}
			for i := range got {
				if got[i] != tc.want[i] {
					t.Fatalf("entry %d: got %#v, want %#v", i, got[i], tc.want[i])
				}
			}
		})
	}
}

func TestProtectedPathViolations(t *testing.T) {
	changed := []ChangedFile{
		{Status: "M", Path: "scripts/bench-json"},
		{Status: "M", Path: "scripts/bench-json-helper"},
		{Status: "A", Path: "testdata/latency-corpus.json"},
		{Status: "M", Path: "testdata/nested/input.json"},
		{Status: "R100", Path: "old-fixtures/data.json -> fixtures/data.json", OldPath: "old-fixtures/data.json", NewPath: "fixtures/data.json"},
		{Status: "M", Path: "Scripts/bench-json"},
		{Status: "M", Path: "links/bench"},
	}
	violations := ProtectedPathViolations(changed, []string{
		"scripts/bench-json",
		"testdata",
		"old-fixtures",
		"fixtures/data.json",
		"links/bench",
	})
	got := []string{}
	for _, violation := range violations {
		got = append(got, violation.ProtectedPath+"="+violation.ChangedPath)
	}
	want := []string{
		"fixtures/data.json=fixtures/data.json",
		"links/bench=links/bench",
		"old-fixtures=old-fixtures/data.json",
		"scripts/bench-json=scripts/bench-json",
		"testdata=testdata/latency-corpus.json",
		"testdata=testdata/nested/input.json",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("violations = %#v, want %#v", got, want)
	}
	for _, violation := range violations {
		if violation.ChangedPath == "Scripts/bench-json" {
			t.Fatalf("protected path matching should be case-sensitive: %#v", violations)
		}
	}
}

func TestCaptureRenameProtectedPathViolationsFromGit(t *testing.T) {
	ctx := context.Background()
	repoDir := initGitRepo(t, true)
	if err := os.MkdirAll(filepath.Join(repoDir, "fixtures"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repoDir, "fixtures", "data.json"), []byte("base\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	git(t, repoDir, "add", "fixtures/data.json")
	git(t, repoDir, "commit", "-m", "add fixture")

	repo, err := ResolveRepository(ctx, repoDir, "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	parent, err := PrepareWorktreeParent(ctx, repo, filepath.Join(repoDir, "runs", "run-rename"))
	if err != nil {
		t.Fatal(err)
	}
	worktreePath := filepath.Join(parent.Path, "rename")
	if err := CreateDetachedWorktree(ctx, repo, worktreePath); err != nil {
		t.Fatal(err)
	}
	defer CleanupWorktree(ctx, repo, worktreePath, false)

	git(t, worktreePath, "mv", "fixtures/data.json", "fixtures/data-renamed.json")
	capture, err := CaptureChanges(ctx, CaptureOptions{WorktreePath: worktreePath, BaseCommit: repo.BaseCommit, PatchMaxBytes: 100000})
	if err != nil {
		t.Fatal(err)
	}
	if len(capture.ChangedFiles) != 1 {
		t.Fatalf("changed files = %#v", capture.ChangedFiles)
	}
	changed := capture.ChangedFiles[0]
	if !strings.HasPrefix(changed.Status, "R") || changed.OldPath != "fixtures/data.json" || changed.NewPath != "fixtures/data-renamed.json" {
		t.Fatalf("rename metadata = %#v", changed)
	}
	violations := ProtectedPathViolations(capture.ChangedFiles, []string{"fixtures/data.json", "fixtures/data-renamed.json"})
	got := []string{}
	for _, violation := range violations {
		got = append(got, violation.ProtectedPath+"="+violation.ChangedPath)
	}
	want := []string{
		"fixtures/data-renamed.json=fixtures/data-renamed.json",
		"fixtures/data.json=fixtures/data.json",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("violations = %#v, want %#v", got, want)
	}
}

func TestNormalizedPatchDigestNormalizesLineEndings(t *testing.T) {
	left := NormalizedPatchDigest([]byte("diff --git a/a b/a\r\n+one\r\n"))
	right := NormalizedPatchDigest([]byte("diff --git a/a b/a\n+one\n"))
	if left == "" || left != right {
		t.Fatalf("digests = %q / %q", left, right)
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
