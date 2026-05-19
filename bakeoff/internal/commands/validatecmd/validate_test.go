package validatecmd

import (
	"bytes"
	"context"
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

func writeValidateBuildWorkOrder(path string, protectedPaths []any) error {
	return writeValidateBuildWorkOrderWithMetric(path, protectedPaths, map[string]any{"name": "score", "direction": "higher", "min_delta_percent": 1})
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
