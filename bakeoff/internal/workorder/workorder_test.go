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
	for _, mode := range []string{"gather", "compare", "analyze", "review", "build"} {
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

func TestBuildWorkOrderValidation(t *testing.T) {
	data := validBuildWorkOrder()
	wo, err := Validate(data)
	if err != nil {
		t.Fatal(err)
	}
	if wo.Type != "build" || wo.Build == nil {
		t.Fatalf("build spec missing: %#v", wo)
	}
	if wo.Build.BaseRef != "HEAD" {
		t.Fatalf("base ref = %q", wo.Build.BaseRef)
	}
	if wo.Build.PatchMaxBytes != 100000 {
		t.Fatalf("patch max = %d", wo.Build.PatchMaxBytes)
	}
	if len(wo.Build.ProtectedPaths) != 0 {
		t.Fatalf("protected paths = %#v", wo.Build.ProtectedPaths)
	}
	if got := wo.Build.Verify[0].Kind; got != "gate" {
		t.Fatalf("default verifier kind = %q", got)
	}
	if got := wo.Build.Verify[1].Metric.Name; got != "elapsed_ms" {
		t.Fatalf("metric name = %q", got)
	}
	if got := wo.Build.Verify[1].Metric.MinRuns; got != 1 {
		t.Fatalf("default metric min_runs = %d", got)
	}
}

func TestBuildProtectedPathsValidation(t *testing.T) {
	data := validBuildWorkOrder()
	build := data["build"].(map[string]any)
	build["protected_paths"] = []any{"scripts/bench-json", "testdata/./latency-corpus.json"}
	verify := build["verify"].([]any)
	verify[1].(map[string]any)["metric"].(map[string]any)["min_runs"] = 10

	wo, err := Validate(data)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(wo.Build.ProtectedPaths, ","); got != "scripts/bench-json,testdata/latency-corpus.json" {
		t.Fatalf("protected paths = %#v", wo.Build.ProtectedPaths)
	}
	if got := wo.Build.Verify[1].Metric.MinRuns; got != 10 {
		t.Fatalf("metric min_runs = %d", got)
	}
}

func TestBuildProtectedPathsRejectsUnsafeEntries(t *testing.T) {
	cases := []struct {
		name  string
		value any
		want  string
	}{
		{name: "empty", value: []any{""}, want: "non-empty"},
		{name: "absolute", value: []any{"/scripts/bench-json"}, want: "relative"},
		{name: "parent", value: []any{"scripts/../bench-json"}, want: ".. path traversal"},
		{name: "glob", value: []any{"scripts/*"}, want: "glob"},
		{name: "duplicate", value: []any{"scripts/bench-json", "scripts/./bench-json"}, want: "duplicates"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			data := validBuildWorkOrder()
			data["build"].(map[string]any)["protected_paths"] = tc.value
			_, err := Validate(data)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected %q error, got %v", tc.want, err)
			}
		})
	}
}

func TestBuildMetricValidationRejectsInvalidMinRuns(t *testing.T) {
	data := validBuildWorkOrder()
	verify := data["build"].(map[string]any)["verify"].([]any)
	verify[1].(map[string]any)["metric"].(map[string]any)["min_runs"] = 0
	_, err := Validate(data)
	if err == nil || !strings.Contains(err.Error(), "min_runs") {
		t.Fatalf("expected min_runs validation error, got %v", err)
	}
}

func TestBuildValidationRejectsWebScopeAndMissingGate(t *testing.T) {
	data := validBuildWorkOrder()
	providers := data["providers"].([]any)
	providers[1].(map[string]any)["scope"] = "web"
	_, err := Validate(data)
	if err == nil || !strings.Contains(err.Error(), `scope "web" is not supported`) {
		t.Fatalf("expected web scope rejection, got %v", err)
	}

	data = validBuildWorkOrder()
	build := data["build"].(map[string]any)
	build["verify"] = []any{
		map[string]any{
			"id":                 "metric-only",
			"kind":               "metric",
			"argv":               []any{"./bench"},
			"wall_clock_seconds": 10,
			"max_output_bytes":   1000,
			"metric": map[string]any{
				"name":              "elapsed_ms",
				"direction":         "lower",
				"min_delta_percent": 5,
			},
		},
	}
	_, err = Validate(data)
	if err == nil || !strings.Contains(err.Error(), "at least one gate") {
		t.Fatalf("expected missing gate rejection, got %v", err)
	}
}

func TestBuildValidationRejectsAmbiguousVerifierArgv(t *testing.T) {
	data := validBuildWorkOrder()
	verify := data["build"].(map[string]any)["verify"].([]any)
	verify[0].(map[string]any)["argv"] = []any{"go test", "./..."}
	_, err := Validate(data)
	if err == nil || !strings.Contains(err.Error(), "command path without whitespace") {
		t.Fatalf("expected argv[0] whitespace rejection, got %v", err)
	}

	data = validBuildWorkOrder()
	verify = data["build"].(map[string]any)["verify"].([]any)
	verify[0].(map[string]any)["argv"] = []any{"go", "test\x00./..."}
	_, err = Validate(data)
	if err == nil || !strings.Contains(err.Error(), "control characters") {
		t.Fatalf("expected argv control character rejection, got %v", err)
	}
}

func TestBuildResultValidators(t *testing.T) {
	worker := map[string]any{
		"status":                 "complete",
		"summary":                "Implemented the change.",
		"files_touched":          []any{"main.go"},
		"tests_added_or_changed": []any{"main_test.go"},
		"risks":                  []any{},
		"manual_checks":          []any{"go test ./..."},
	}
	if _, err := ValidateBuildWorkerResult(worker); err != nil {
		t.Fatal(err)
	}

	judge := map[string]any{
		"relation": "compare",
		"scores_a": map[string]any{
			"correctness":          4,
			"verifier_evidence":    5,
			"comparative_evidence": 3,
			"scope_control":        4,
			"test_quality":         4,
			"benchmark_quality":    3,
			"maintainability":      4,
		},
		"scores_b": map[string]any{
			"correctness":          3,
			"verifier_evidence":    5,
			"comparative_evidence": 3,
			"scope_control":        3,
			"test_quality":         3,
			"benchmark_quality":    3,
			"maintainability":      3,
		},
		"winner":    "A",
		"rationale": "A has a cleaner patch.",
		"risks":     []any{},
	}
	if _, err := ValidateBuildJudgeResult(judge); err != nil {
		t.Fatal(err)
	}
}

func TestValidateBackgroundShapes(t *testing.T) {
	t.Run("string", func(t *testing.T) {
		data := validWorkOrder()
		data["background"] = "single string"
		wo, err := Validate(data)
		if err != nil {
			t.Fatal(err)
		}
		if wo.Background != "single string" {
			t.Fatalf("Background = %q", wo.Background)
		}
	})
	t.Run("string array", func(t *testing.T) {
		data := validWorkOrder()
		data["background"] = []any{"line one", "line two"}
		wo, err := Validate(data)
		if err != nil {
			t.Fatal(err)
		}
		if wo.Background != "line one\n\nline two" {
			t.Fatalf("Background = %q", wo.Background)
		}
		if _, ok := wo.Raw["background"].([]any); !ok {
			t.Fatalf("raw background was not preserved as array: %#v", wo.Raw["background"])
		}
	})
	t.Run("empty string array", func(t *testing.T) {
		data := validWorkOrder()
		data["background"] = []any{}
		wo, err := Validate(data)
		if err != nil {
			t.Fatal(err)
		}
		if wo.Background != "" {
			t.Fatalf("Background = %q", wo.Background)
		}
	})
	t.Run("non-string array item", func(t *testing.T) {
		data := validWorkOrder()
		data["background"] = []any{123}
		if _, err := Validate(data); err == nil || !strings.Contains(err.Error(), "background must be a string or an array of strings") {
			t.Fatalf("expected background array validation error, got %v", err)
		}
	})
	t.Run("null", func(t *testing.T) {
		data := validWorkOrder()
		data["background"] = nil
		if _, err := Validate(data); err == nil || !strings.Contains(err.Error(), "background must be a string or an array of strings") {
			t.Fatalf("expected background validation error, got %v", err)
		}
	})
}

func TestWriteTextAtomicWritesPrivateFiles(t *testing.T) {
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
		if got := info.Mode().Perm(); got != 0o600 {
			t.Fatalf("mode = %o, want 0600", got)
		}
		parent, err := os.Stat(filepath.Dir(path))
		if err != nil {
			t.Fatal(err)
		}
		if got := parent.Mode().Perm(); got != 0o700 {
			t.Fatalf("parent mode = %o, want 0700", got)
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

func validBuildWorkOrder() map[string]any {
	return map[string]any{
		"schema_version": 1,
		"id":             "build-routing",
		"type":           "build",
		"goal":           "Implement routing.",
		"background":     "Acceptance criteria.",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "other", "scope": "mixed"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 2000},
		"build": map[string]any{
			"comparison_goal": "Prefer fewer moving parts.",
			"verify": []any{
				map[string]any{
					"id":                 "unit",
					"argv":               []any{"go", "test", "./..."},
					"wall_clock_seconds": 300,
					"max_output_bytes":   60000,
				},
				map[string]any{
					"id":                 "latency",
					"kind":               "metric",
					"argv":               []any{"./bench"},
					"wall_clock_seconds": 300,
					"max_output_bytes":   60000,
					"metric": map[string]any{
						"name":                "elapsed_ms",
						"direction":           "lower",
						"min_delta_percent":   10,
						"noise_floor_percent": 5,
					},
				},
			},
		},
	}
}
