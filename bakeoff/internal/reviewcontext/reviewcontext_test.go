package reviewcontext

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/modeldefaults"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestBuildApplyAndRenderReviewContext(t *testing.T) {
	repo := t.TempDir()
	runGitForTest(t, repo, "init")
	runGitForTest(t, repo, "config", "core.hooksPath", "/dev/null")
	if err := os.WriteFile(filepath.Join(repo, "app.go"), []byte("package main\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	runGitForTest(t, repo, "add", "app.go")
	runGitForTest(t, repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init")
	if err := os.WriteFile(filepath.Join(repo, "app.go"), []byte("package main\n\nfunc main() {}\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	reviewCtx, err := Build(context.Background(), Options{BaseRef: "HEAD", IncludePatch: true}, repo, "2026-05-16T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	if reviewCtx.BaseRef != "HEAD" || reviewCtx.Patch == nil || changedFileCount(reviewCtx.ChangedFiles) != 1 {
		t.Fatalf("unexpected context: %#v", reviewCtx)
	}
	markdown := RenderMarkdown(reviewCtx)
	if !strings.Contains(markdown, "## Patch") || !strings.Contains(markdown, "app.go") {
		t.Fatalf("markdown missing patch context:\n%s", markdown)
	}

	wo, err := workorder.Validate(map[string]any{
		"schema_version": float64(1),
		"id":             "review-context-test",
		"type":           "gather",
		"goal":           "Find bugs.",
		"background":     "Original background.",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": modeldefaults.ClaudeSonnet, "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": modeldefaults.CodexDefault, "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": modeldefaults.ClaudeOpus},
		"budgets": map[string]any{"wall_clock_seconds": float64(30), "max_output_bytes": float64(1000)},
	})
	if err != nil {
		t.Fatal(err)
	}
	applied, err := Apply(wo, reviewCtx)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(applied.Background, "<generated_review_context>") || !strings.Contains(applied.Background, "Original background.") {
		t.Fatalf("background missing generated context:\n%s", applied.Background)
	}

	arrayWO, err := workorder.Validate(map[string]any{
		"schema_version": float64(1),
		"id":             "review-context-array-test",
		"type":           "gather",
		"goal":           "Find bugs.",
		"background":     []any{"Base branch: main.", "Acceptance criteria: pass."},
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": modeldefaults.ClaudeSonnet, "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": modeldefaults.CodexDefault, "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": modeldefaults.ClaudeOpus},
		"budgets": map[string]any{"wall_clock_seconds": float64(30), "max_output_bytes": float64(1000)},
	})
	if err != nil {
		t.Fatal(err)
	}
	appliedArray, err := Apply(arrayWO, reviewCtx)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(appliedArray.Background, "Base branch: main.\n\nAcceptance criteria: pass.\n\n<generated_review_context>") {
		t.Fatalf("array background not joined with generated context:\n%s", appliedArray.Background)
	}
	rawBackground, ok := appliedArray.Raw["background"].([]any)
	if !ok {
		t.Fatalf("raw array background was not preserved: %#v", appliedArray.Raw["background"])
	}
	if len(rawBackground) != 3 || !strings.Contains(rawBackground[2].(string), "<generated_review_context>") {
		t.Fatalf("raw array background missing appended context: %#v", rawBackground)
	}
}

func TestBuildCancelsGitSubprocessesWithContext(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("test uses a POSIX shell fake git")
	}
	binDir := t.TempDir()
	fakeGit := filepath.Join(binDir, "git")
	if err := os.WriteFile(fakeGit, []byte("#!/bin/sh\nsleep 5\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	started := time.Now()
	_, err := Build(ctx, Options{BaseRef: "HEAD"}, t.TempDir(), "2026-05-16T00:00:00Z")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Build error = %v, want deadline exceeded", err)
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("git subprocess did not stop promptly: %s", elapsed)
	}
}

func runGitForTest(t *testing.T, cwd string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = cwd
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, output)
	}
}
