package reviewcontext

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

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

	context, err := Build(Options{BaseRef: "HEAD", IncludePatch: true}, repo, "2026-05-16T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	if context.BaseRef != "HEAD" || context.Patch == nil || changedFileCount(context.ChangedFiles) != 1 {
		t.Fatalf("unexpected context: %#v", context)
	}
	markdown := RenderMarkdown(context)
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
			map[string]any{"id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "claude-opus-4-7"},
		"budgets": map[string]any{"wall_clock_seconds": float64(30), "max_output_bytes": float64(1000)},
	})
	if err != nil {
		t.Fatal(err)
	}
	applied, err := Apply(wo, context)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(applied.Background, "<generated_review_context>") || !strings.Contains(applied.Background, "Original background.") {
		t.Fatalf("background missing generated context:\n%s", applied.Background)
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
