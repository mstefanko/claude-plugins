package validatecmd

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type validateTestFactory struct {
	streams output.Streams
}

func (f validateTestFactory) Streams() output.Streams {
	return f.streams
}

func (f validateTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f validateTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f validateTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f validateTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestValidateWarnsForUnprotectedRepoRelativeMetricCommand(t *testing.T) {
	path := filepath.Join(t.TempDir(), "build.work-order.json")
	if err := writeValidateBuildWorkOrder(path, nil); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidate(context.Background(), f, &ValidateOptions{WorkOrder: path}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), `warning: metric verifier "score" runs repo-relative command "./scripts/bench-json" while build.protected_paths is empty`) {
		t.Fatalf("missing warning:\n%s", out.String())
	}
}

func TestValidateSuppressesMetricCommandWarningWhenProtectedPathsExist(t *testing.T) {
	path := filepath.Join(t.TempDir(), "build.work-order.json")
	if err := writeValidateBuildWorkOrder(path, []any{"scripts/bench-json"}); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidate(context.Background(), f, &ValidateOptions{WorkOrder: path}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "warning:") {
		t.Fatalf("unexpected warning:\n%s", out.String())
	}
}

func TestValidateWarnsWhenMetricMinRunsNeedsN(t *testing.T) {
	path := filepath.Join(t.TempDir(), "build.work-order.json")
	if err := writeValidateBuildWorkOrderWithMetric(path, []any{"scripts/bench-json"}, map[string]any{"name": "score", "direction": "higher", "min_delta_percent": 1, "min_runs": 10}); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidate(context.Background(), f, &ValidateOptions{WorkOrder: path}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), `warning: metric verifier "score" sets metric.min_runs=10; final metric JSON must include "n" >= 10 or the metric comparison will be inconclusive`) {
		t.Fatalf("missing min_runs warning:\n%s", out.String())
	}
	if strings.Contains(out.String(), "build.protected_paths is empty") {
		t.Fatalf("unexpected protected_paths warning:\n%s", out.String())
	}
}

func TestValidateWarnsForMissingProsePaths(t *testing.T) {
	root := t.TempDir()
	t.Chdir(root)
	if err := os.MkdirAll(filepath.Join(root, "internal", "workorder"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "internal", "workorder", "workorder.go"), []byte("package workorder\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "gather.work-order.json")
	if err := writeValidateGatherWorkOrder(path, "Fix pkg/workorder.", "Existing internal/workorder/workorder.go:1 should not warn."); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidate(context.Background(), f, &ValidateOptions{WorkOrder: path}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if !strings.Contains(text, `warning: goal references "pkg/workorder" which does not exist under <context-root>; did you mean one of: internal/workorder/`) {
		t.Fatalf("missing prose path warning:\n%s", text)
	}
	if strings.Contains(text, "internal/workorder/workorder.go:1 which does not exist") {
		t.Fatalf("existing path emitted warning:\n%s", text)
	}
}

func TestValidateContextPreviewsProviderScopedRepoLayout(t *testing.T) {
	root := t.TempDir()
	t.Chdir(root)
	if err := os.MkdirAll(filepath.Join(root, "docs"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "docs", "guide.md"), []byte("# Guide\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "gather.work-order.json")
	if err := writeValidateGatherWorkOrder(path, "Find docs.", "Use docs/guide.md."); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidateContext(context.Background(), f, &ContextOptions{WorkOrder: path}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if !strings.Contains(text, "context root: "+root) || !strings.Contains(text, "<context>\nUse docs/guide.md.\n</context>") {
		t.Fatalf("missing context preview:\n%s", text)
	}
	if !strings.Contains(text, "<repo_layout>") || !strings.Contains(text, "docs/ — docs") {
		t.Fatalf("missing repo layout preview:\n%s", text)
	}
	if !strings.Contains(text, "claude: receives <context>, <repo_layout>") || !strings.Contains(text, "codex: receives <context>; does not receive <repo_layout>") {
		t.Fatalf("missing provider scope notes:\n%s", text)
	}
}

func TestValidateContextReportsEmptyEligibleRepoLayout(t *testing.T) {
	root := t.TempDir()
	t.Chdir(root)
	path := filepath.Join(root, "gather.work-order.json")
	if err := writeValidateGatherWorkOrder(path, "Find docs.", "Plain context."); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	if err := runValidateContext(context.Background(), f, &ContextOptions{WorkOrder: path, Provider: "claude"}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if strings.Contains(text, "\n<repo_layout>\n") {
		t.Fatalf("empty repo layout should not render block:\n%s", text)
	}
	if !strings.Contains(text, "claude: receives <context>; <repo_layout> enabled but no entries were generated") {
		t.Fatalf("missing empty-layout provider note:\n%s", text)
	}
}

func TestValidateContextRejectsUnknownProvider(t *testing.T) {
	root := t.TempDir()
	t.Chdir(root)
	path := filepath.Join(root, "gather.work-order.json")
	if err := writeValidateGatherWorkOrder(path, "Find docs.", "Use docs."); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	f := validateTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := runValidateContext(context.Background(), f, &ContextOptions{WorkOrder: path, Provider: "missing"})
	if err == nil || !strings.Contains(err.Error(), `unknown provider id "missing"`) {
		t.Fatalf("expected unknown provider error, got %v", err)
	}
}

func writeValidateBuildWorkOrder(path string, protectedPaths []any) error {
	return writeValidateBuildWorkOrderWithMetric(path, protectedPaths, map[string]any{"name": "score", "direction": "higher", "min_delta_percent": 1})
}

func writeValidateGatherWorkOrder(path string, goal string, background string) error {
	return workorder.WriteJSONAtomic(path, map[string]any{
		"schema_version": 1,
		"id":             "validate-gather",
		"type":           "gather",
		"goal":           goal,
		"background":     background,
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 2000},
	})
}

func writeValidateBuildWorkOrderWithMetric(path string, protectedPaths []any, metric map[string]any) error {
	build := map[string]any{
		"verify": []any{
			map[string]any{"id": "unit", "kind": "gate", "argv": []any{"go", "test", "./..."}, "wall_clock_seconds": 10, "max_output_bytes": 1000},
			map[string]any{"id": "score", "kind": "metric", "argv": []any{"./scripts/bench-json"}, "wall_clock_seconds": 10, "max_output_bytes": 1000, "metric": metric},
		},
	}
	if protectedPaths != nil {
		build["protected_paths"] = protectedPaths
	}
	return workorder.WriteJSONAtomic(path, map[string]any{
		"schema_version": 1,
		"id":             "validate-build",
		"type":           "build",
		"goal":           "Validate warnings.",
		"background":     "",
		"providers": []any{
			map[string]any{"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
			map[string]any{"id": "codex", "backend": "codex", "model": "other", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 2000},
		"build":   build,
	})
}
