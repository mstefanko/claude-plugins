package workorder

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestStripJSONCCommentsPreservesMarkersInStrings(t *testing.T) {
	raw := `{
	  // comment
	  "url": "https://example.com/a//b",
	  "glob": "literal /* not comment */ marker",
	  "quote": "escaped \" quote",
	  "slash": "backslash \\ before quote"
	}`

	var parsed map[string]string
	if err := json.Unmarshal([]byte(StripJSONCComments(raw)), &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed["url"] != "https://example.com/a//b" {
		t.Fatalf("comment marker inside string was changed: %#v", parsed["url"])
	}
	if parsed["glob"] != "literal /* not comment */ marker" {
		t.Fatalf("block marker inside string was changed: %#v", parsed["glob"])
	}
}

func TestLoadWorkOrderDefaultsAndSummary(t *testing.T) {
	path := filepath.Join(t.TempDir(), "wo.jsonc")
	err := os.WriteFile(path, []byte(`{
	  "schema_version": 1,
	  "id": "routing",
	  "type": "gather",
	  "goal": "Find routing facts.",
	  "background": "Use https://example.com/docs.",
	  "providers": [
	    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "scope": "codebase" },
	    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "web" }
	  ],
	  "judge": { "backend": "claude", "model": "claude-opus-4-7" },
	  "budgets": { "wall_clock_seconds": 3, "max_output_bytes": 2000 }
	}`), 0o644)
	if err != nil {
		t.Fatal(err)
	}

	wo, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if wo.Providers[0].Effort != "high" || wo.Judge.Effort != "high" {
		t.Fatalf("effort defaults not applied: %#v / %#v", wo.Providers[0], wo.Judge)
	}
	if wo.Budgets.HeartbeatSeconds != 60 || wo.Budgets.OutputCapGraceSeconds != 10 || wo.Budgets.MaxOutputOverrunBytes != 2000 {
		t.Fatalf("budget defaults not applied: %#v", wo.Budgets)
	}
	if wo.ScopePolicy.Enforcement != "best_effort" {
		t.Fatalf("scope policy default not applied: %#v", wo.ScopePolicy)
	}
	if got := FormatBudgetSummary(wo.Budgets); got != "3s wall, 2000 bytes out, 10s cap grace" {
		t.Fatalf("budget summary = %q", got)
	}
}

func TestFacetValidationNormalizesAndRejectsUnsafeText(t *testing.T) {
	data := validWorkOrder()
	data["facet"] = map[string]any{
		"id":      "security",
		"focus":   "Find reachable security risks.",
		"include": []any{"authorization\x00regressions"},
		"exclude": []any{"generic advice"},
		"notes":   "Only\tchanged auth paths.",
	}

	wo, err := Validate(data)
	if err != nil {
		t.Fatal(err)
	}
	if got := wo.Facet.Include[0]; got != "authorization regressions" {
		t.Fatalf("facet include not normalized: %q", got)
	}
	if got := wo.Facet.Notes; got != "Only changed auth paths." {
		t.Fatalf("facet notes not normalized: %q", got)
	}

	data = validWorkOrder()
	data["facet"] = map[string]any{"id": "judge", "focus": "Find risks.", "include": []any{"x"}}
	_, err = Validate(data)
	if err == nil || !strings.Contains(err.Error(), "facet.id is reserved") {
		t.Fatalf("expected reserved facet id error, got %v", err)
	}
}

func TestInitTemplatesMatchFrozenShape(t *testing.T) {
	for _, mode := range []string{"gather", "compare", "analyze", "review"} {
		text, err := InitTemplate(mode)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.HasPrefix(text, "// bakeoff "+mode) {
			t.Fatalf("%s template has unexpected header: %q", mode, text[:40])
		}
		if !strings.HasSuffix(text, "\n") {
			t.Fatalf("%s template must end in newline", mode)
		}
	}
}

func TestWriteTextAtomicWritesWorldReadableFiles(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "work-order.json")
	if err := WriteTextAtomic(path, "ok\n"); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "ok\n" {
		t.Fatalf("content = %q", data)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if got := info.Mode().Perm(); got != 0o644 {
			t.Fatalf("mode = %o, want 0644", got)
		}
	}
}

func TestWriteTextAtomicCleansTempFileWhenRenameFails(t *testing.T) {
	dir := t.TempDir()
	targetDir := filepath.Join(dir, "target")
	if err := os.Mkdir(targetDir, 0o755); err != nil {
		t.Fatal(err)
	}

	if err := WriteTextAtomic(targetDir, "cannot replace directory\n"); err == nil {
		t.Fatal("expected rename failure")
	}

	matches, err := filepath.Glob(filepath.Join(dir, ".target.*.tmp"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 0 {
		t.Fatalf("temporary files were not cleaned up: %#v", matches)
	}
}

func validWorkOrder() map[string]any {
	return map[string]any{
		"schema_version": 1,
		"id":             "routing",
		"type":           "gather",
		"goal":           "Find routing facts.",
		"background":     "",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 2000},
	}
}
