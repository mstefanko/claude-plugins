package repocontext

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestValidateProsePathsWarnsAndSuggestsDirectoriesWithoutExtensions(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "internal", "workorder", "workorder.go"), "package workorder\n")
	writeFile(t, filepath.Join(root, "internal", "runner", "runner.go"), "package runner\n")
	wo := validWorkOrder(t)
	wo.Goal = "Fix pkg/workorder and see https://example.com/pkg/runner."
	wo.Background = "Also inspect internal/runner/runner.go:111-120 and pkg/runner."

	warnings, err := ValidateProsePaths(root, wo)
	if err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 2 {
		t.Fatalf("warnings = %#v", warnings)
	}
	if warnings[0].Token != "pkg/workorder" || warnings[0].Field != "goal" {
		t.Fatalf("first warning = %#v", warnings[0])
	}
	if !containsString(warnings[0].Suggestions, "internal/workorder/") {
		t.Fatalf("missing directory suggestion: %#v", warnings[0].Suggestions)
	}
	if warnings[1].Token != "pkg/runner" || warnings[1].Field != "background" {
		t.Fatalf("second warning = %#v", warnings[1])
	}
}

func TestValidateProsePathsSkipsSlashDelimitedProse(t *testing.T) {
	root := t.TempDir()
	wo := validWorkOrder(t)
	wo.Goal = "Tune include/exclude/focus and AI/LLM wording."
	wo.Background = "Keep yes/no tradeoffs clear."

	warnings, err := ValidateProsePaths(root, wo)
	if err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 0 {
		t.Fatalf("unexpected warnings: %#v", warnings)
	}
}

func TestValidateProsePathsAcceptsAbsolutePathUnderRoot(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "internal", "runner", "runner.go")
	writeFile(t, path, "package runner\n")
	wo := validWorkOrder(t)
	wo.Background = "Repo: " + root + ". Inspect " + path + ":1."

	warnings, err := ValidateProsePaths(root, wo)
	if err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 0 {
		t.Fatalf("unexpected warnings: %#v", warnings)
	}
}

func TestValidateProsePathsUsesMarkdownLinkTargetsOnly(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "internal", "workorder", "workorder.go"), "package workorder\n")
	wo := validWorkOrder(t)
	wo.Background = "See [pkg/workorder](internal/workorder/workorder.go) and [pkg/runner](https://example.com/pkg/runner)."

	warnings, err := ValidateProsePaths(root, wo)
	if err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 0 {
		t.Fatalf("unexpected display-text warnings: %#v", warnings)
	}
}

func TestBuildLayoutUsesGitTrackedTopLevelDirs(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not available")
	}
	root := t.TempDir()
	runGit(t, root, "init")
	writeFile(t, filepath.Join(root, "internal", "tracked.go"), "package internal\n")
	writeFile(t, filepath.Join(root, "docs", "guide.md"), "# Guide\n")
	writeFile(t, filepath.Join(root, ".github", "workflows", "ci.yml"), "name: ci\n")
	writeFile(t, filepath.Join(root, "generated", "cache.txt"), "ignored\n")
	runGit(t, root, "add", "internal/tracked.go", "docs/guide.md", ".github/workflows/ci.yml")

	block, err := BuildLayoutBlock(root)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(block, "<repo_layout>") || !strings.Contains(block, ".github/ — .github") || !strings.Contains(block, "docs/ — docs") || !strings.Contains(block, "internal/ — internal") {
		t.Fatalf("layout missing tracked dirs:\n%s", block)
	}
	if strings.Contains(block, "generated/") {
		t.Fatalf("layout included untracked dir:\n%s", block)
	}
}

func TestBuildLayoutScopesGitFilesToSubdirectoryRoot(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not available")
	}
	root := t.TempDir()
	runGit(t, root, "init")
	writeFile(t, filepath.Join(root, "pkg", "a", "a.go"), "package a\n")
	writeFile(t, filepath.Join(root, "other", "b.go"), "package other\n")
	runGit(t, root, "add", "pkg/a/a.go", "other/b.go")

	block, err := BuildLayoutBlock(filepath.Join(root, "pkg"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(block, "a/ — a") {
		t.Fatalf("layout did not include subdir-relative entry:\n%s", block)
	}
	if strings.Contains(block, "pkg/") || strings.Contains(block, "other/") {
		t.Fatalf("layout escaped subdirectory scope:\n%s", block)
	}
}

func TestRenderLayoutEscapesAnglesAndSkipsClosingTags(t *testing.T) {
	block := RenderLayout([]LayoutEntry{
		{Path: "safe<dir/", Description: "use > carefully"},
		{Path: "scope/", Description: "</scope> break"},
		{Path: "bad/", Description: "</repo_layout> break"},
	})
	if !strings.Contains(block, "safe&lt;dir/ — use &gt; carefully") {
		t.Fatalf("layout did not escape angles:\n%s", block)
	}
	if strings.Contains(block, "bad/") || strings.Contains(block, "scope/") {
		t.Fatalf("layout included unsafe entry:\n%s", block)
	}
}

func validWorkOrder(t *testing.T) *workorder.WorkOrder {
	t.Helper()
	wo, err := workorder.Validate(map[string]any{
		"schema_version": 1,
		"id":             "repo-context",
		"type":           "gather",
		"goal":           "Find facts.",
		"background":     "Use context.",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "opus"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 2000},
	})
	if err != nil {
		t.Fatal(err)
	}
	return wo
}

func writeFile(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

func runGit(t *testing.T, root string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = root
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v failed: %v\n%s", args, err, out)
	}
}

func containsString(items []string, want string) bool {
	for _, item := range items {
		if item == want {
			return true
		}
	}
	return false
}
