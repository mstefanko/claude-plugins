package reruncmd

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
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/buildcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/researchcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type rerunTestFactory struct {
	streams output.Streams
}

func (f rerunTestFactory) Streams() output.Streams {
	return f.streams
}

func (f rerunTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f rerunTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f rerunTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f rerunTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestRunRerunDispatchesBuildWorkOrder(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	sourceRun := filepath.Join(outDir, "build-source")
	if err := os.MkdirAll(sourceRun, 0o755); err != nil {
		t.Fatal(err)
	}
	writeRerunBuildWorkOrder(t, filepath.Join(sourceRun, "work-order.json"))

	oldRunBuild, oldRunResearch := runBuild, runResearch
	defer func() {
		runBuild = oldRunBuild
		runResearch = oldRunResearch
	}()
	var got buildcmd.BuildOptions
	runBuild = func(_ context.Context, _ commands.Factory, opts *buildcmd.BuildOptions) error {
		got = *opts
		return nil
	}
	runResearch = func(_ context.Context, _ commands.Factory, _ *researchcmd.ResearchOptions) error {
		t.Fatal("research runner should not be called for build work orders")
		return nil
	}

	var out, errOut bytes.Buffer
	f := rerunTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := runRerun(context.Background(), f, &RerunOptions{SourceRunID: "build-source", Out: outDir, NewRunID: "build-copy", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatal(err)
	}
	if got.WorkOrder != filepath.Join(sourceRun, "work-order.json") || got.Out != outDir || got.RunID != "build-copy" || !got.Quiet {
		t.Fatalf("build options = %#v", got)
	}
	if !strings.Contains(out.String(), "current source tree") {
		t.Fatalf("missing build rerun warning:\n%s", out.String())
	}
}

func TestRunRerunDispatchesResearchWorkOrder(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	sourceRun := filepath.Join(outDir, "research-source")
	if err := os.MkdirAll(sourceRun, 0o755); err != nil {
		t.Fatal(err)
	}
	writeRerunResearchWorkOrder(t, filepath.Join(sourceRun, "work-order.json"))

	oldRunBuild, oldRunResearch := runBuild, runResearch
	defer func() {
		runBuild = oldRunBuild
		runResearch = oldRunResearch
	}()
	runBuild = func(_ context.Context, _ commands.Factory, _ *buildcmd.BuildOptions) error {
		t.Fatal("build runner should not be called for research work orders")
		return nil
	}
	var got researchcmd.ResearchOptions
	runResearch = func(_ context.Context, _ commands.Factory, opts *researchcmd.ResearchOptions) error {
		got = *opts
		return nil
	}

	f := rerunTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}
	err := runRerun(context.Background(), f, &RerunOptions{SourceRunID: "research-source", Out: outDir, NewRunID: "research-copy", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatal(err)
	}
	if got.WorkOrder != filepath.Join(sourceRun, "work-order.json") || got.Out != outDir || got.RunID != "research-copy" || !got.Quiet || !got.NoTriage || got.ReplaySourceRunDir != sourceRun {
		t.Fatalf("research options = %#v", got)
	}
}

func TestRunRerunRequiresSourceWorkOrder(t *testing.T) {
	outDir := filepath.Join(t.TempDir(), "runs")
	if err := os.MkdirAll(filepath.Join(outDir, "missing-work-order"), 0o755); err != nil {
		t.Fatal(err)
	}
	f := rerunTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}
	err := runRerun(context.Background(), f, &RerunOptions{SourceRunID: "missing-work-order", Out: outDir})
	if err == nil || !strings.Contains(err.Error(), "has no work-order.json") {
		t.Fatalf("expected missing work-order error, got %v", err)
	}
}

func writeRerunResearchWorkOrder(t *testing.T, path string) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, map[string]any{
		"schema_version": 1,
		"id":             "research-source",
		"type":           "gather",
		"goal":           "Gather facts.",
		"background":     "Rerun dispatch test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}
}

func writeRerunBuildWorkOrder(t *testing.T, path string) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, map[string]any{
		"schema_version": 1,
		"id":             "build-source",
		"type":           "build",
		"goal":           "Build the feature.",
		"background":     "Rerun dispatch test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "codebase"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"build": map[string]any{
			"base_ref":        "HEAD",
			"comparison_goal": "Prefer the more complete patch.",
			"patch_max_bytes": 100000,
			"verify": []map[string]any{
				{"id": "unit", "kind": "gate", "argv": []string{"true"}, "wall_clock_seconds": 5, "max_output_bytes": 2000},
			},
		},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}
}
