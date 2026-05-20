package commands_test

import (
	"bytes"
	"context"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/buildcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/doctorcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/draftbuildcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/initcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/lscmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/reruncmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/researchcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/runscmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/showcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/triagecmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/validatecmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/spf13/cobra"
)

type fakeFactory struct {
	streams output.Streams
}

func (f fakeFactory) Streams() output.Streams {
	return f.streams
}

func (f fakeFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f fakeFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f fakeFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f fakeFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func testFactory() fakeFactory {
	return fakeFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}
}

func execute(cmd *cobra.Command, args ...string) error {
	cmd.SetArgs(args)
	cmd.SetOut(&bytes.Buffer{})
	cmd.SetErr(&bytes.Buffer{})
	return cmd.ExecuteContext(context.Background())
}

func TestCommandOptions(t *testing.T) {
	t.Run("init", func(t *testing.T) {
		var got *initcmd.InitOptions
		cmd := initcmd.NewCmdInit(testFactory(), func(_ context.Context, opts *initcmd.InitOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "review", "--force"); err != nil {
			t.Fatal(err)
		}
		want := &initcmd.InitOptions{Type: "review", Force: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("validate", func(t *testing.T) {
		var got *validatecmd.ValidateOptions
		cmd := validatecmd.NewCmdValidate(testFactory(), func(_ context.Context, opts *validatecmd.ValidateOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "work.json"); err != nil {
			t.Fatal(err)
		}
		want := &validatecmd.ValidateOptions{WorkOrder: "work.json"}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("draft-build", func(t *testing.T) {
		var got *draftbuildcmd.DraftBuildOptions
		cmd := draftbuildcmd.NewCmdDraftBuild(testFactory(), func(_ context.Context, opts *draftbuildcmd.DraftBuildOptions) error {
			copy := *opts
			copy.Acceptance = append([]string(nil), opts.Acceptance...)
			copy.Scopes = append([]string(nil), opts.Scopes...)
			copy.Background = append([]string(nil), opts.Background...)
			copy.Gates = append([]string(nil), opts.Gates...)
			copy.ProtectedPaths = append([]string(nil), opts.ProtectedPaths...)
			got = &copy
			return nil
		})
		err := execute(cmd,
			"--id", "draft-build-options",
			"--goal", "Draft a build work order.",
			"--acceptance", "Rows sort by name, then time.",
			"--acceptance", "Errors stay readable.",
			"--scope", "internal/commands/lscmd",
			"--scope", "docs, examples",
			"--background", "Keep commas, please.",
			"--protected-path", "scripts/bench-json",
			"--base-ref", "main",
			"--comparison-goal", "Prefer the simplest green patch.",
			"--budget-wall-seconds", "1",
			"--budget-max-output-bytes", "2",
			"--gate-wall-seconds", "3",
			"--gate-max-output-bytes", "4",
			"--gate", "tests=go test ./..., -run TestDraft",
		)
		if err != nil {
			t.Fatal(err)
		}
		want := &draftbuildcmd.DraftBuildOptions{
			ID:                   "draft-build-options",
			Goal:                 "Draft a build work order.",
			Acceptance:           []string{"Rows sort by name, then time.", "Errors stay readable."},
			Scopes:               []string{"internal/commands/lscmd", "docs, examples"},
			Background:           []string{"Keep commas, please."},
			Gates:                []string{"tests=go test ./..., -run TestDraft"},
			ProtectedPaths:       []string{"scripts/bench-json"},
			BaseRef:              "main",
			ComparisonGoal:       "Prefer the simplest green patch.",
			BudgetWallSeconds:    1,
			BudgetMaxOutputBytes: 2,
			GateWallSeconds:      3,
			GateMaxOutputBytes:   4,
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("draft-build invalid gate", func(t *testing.T) {
		cmd := draftbuildcmd.NewCmdDraftBuild(testFactory(), func(_ context.Context, opts *draftbuildcmd.DraftBuildOptions) error {
			return nil
		})
		err := execute(cmd, "--gate", "missing-separator")
		if err == nil || !strings.Contains(err.Error(), "<id>=<command>") {
			t.Fatalf("expected invalid gate syntax error, got %v", err)
		}
	})
	t.Run("research", func(t *testing.T) {
		var got *researchcmd.ResearchOptions
		cmd := researchcmd.NewCmdResearch(testFactory(), func(_ context.Context, opts *researchcmd.ResearchOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		err := execute(cmd, "work.json", "--out", "ledger", "--run-id", "run-1", "--force", "--quiet", "--no-triage", "--base", "main", "--diff", "--changed-files", "--json", "--no-repo-layout")
		if err != nil {
			t.Fatal(err)
		}
		want := &researchcmd.ResearchOptions{
			WorkOrder:    "work.json",
			Out:          "ledger",
			RunID:        "run-1",
			Force:        true,
			Quiet:        true,
			NoTriage:     true,
			Base:         "main",
			Diff:         true,
			ChangedFiles: true,
			JSON:         true,
			NoRepoLayout: true,
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("build", func(t *testing.T) {
		var got *buildcmd.BuildOptions
		cmd := buildcmd.NewCmdBuild(testFactory(), func(_ context.Context, opts *buildcmd.BuildOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		err := execute(cmd, "work.json", "--out", "ledger", "--run-id", "run-1", "--force", "--quiet", "--json", "--keep-worktrees", "--no-repo-layout")
		if err != nil {
			t.Fatal(err)
		}
		want := &buildcmd.BuildOptions{
			WorkOrder:     "work.json",
			Out:           "ledger",
			RunID:         "run-1",
			Force:         true,
			Quiet:         true,
			JSON:          true,
			KeepWorktrees: true,
			NoRepoLayout:  true,
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("rerun", func(t *testing.T) {
		var got *reruncmd.RerunOptions
		cmd := reruncmd.NewCmdRerun(testFactory(), func(_ context.Context, opts *reruncmd.RerunOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "source", "--out", "ledger", "--run-id", "next", "--quiet", "--no-triage", "--judge-only", "--no-repo-layout"); err != nil {
			t.Fatal(err)
		}
		want := &reruncmd.RerunOptions{SourceRunID: "source", Out: "ledger", NewRunID: "next", Quiet: true, NoTriage: true, JudgeOnly: true, NoRepoLayout: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("triage", func(t *testing.T) {
		var got *triagecmd.TriageOptions
		cmd := triagecmd.NewCmdTriage(testFactory(), func(_ context.Context, opts *triagecmd.TriageOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "run-1", "--out", "ledger", "--force", "--dry-run", "--quiet", "--json"); err != nil {
			t.Fatal(err)
		}
		want := &triagecmd.TriageOptions{RunID: "run-1", Out: "ledger", Force: true, DryRun: true, Quiet: true, JSON: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("runs verify", func(t *testing.T) {
		var got *runscmd.VerifyOptions
		cmd := runscmd.NewCmdRuns(testFactory(), func(_ context.Context, opts *runscmd.VerifyOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "verify", "latest", "--out", "ledger", "--json"); err != nil {
			t.Fatal(err)
		}
		want := &runscmd.VerifyOptions{RunID: "latest", Out: "ledger", JSON: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("ls", func(t *testing.T) {
		var got *lscmd.LsOptions
		cmd := lscmd.NewCmdLs(testFactory(), func(_ context.Context, opts *lscmd.LsOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "--out", "ledger", "--json", "--facet", "code-review", "--triage-state", "yes"); err != nil {
			t.Fatal(err)
		}
		want := &lscmd.LsOptions{Out: "ledger", JSON: true, Facet: "code-review", TriageState: "yes"}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("show", func(t *testing.T) {
		var got *showcmd.ShowOptions
		cmd := showcmd.NewCmdShow(testFactory(), func(_ context.Context, opts *showcmd.ShowOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "run-1", "--out", "ledger", "--judge-prompt"); err != nil {
			t.Fatal(err)
		}
		want := &showcmd.ShowOptions{RunID: "run-1", Out: "ledger", JudgePrompt: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
	t.Run("doctor", func(t *testing.T) {
		var got *doctorcmd.DoctorOptions
		cmd := doctorcmd.NewCmdDoctor(testFactory(), func(_ context.Context, opts *doctorcmd.DoctorOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		if err := execute(cmd, "--build", "--skip-auth-probe", "--quiet", "--json"); err != nil {
			t.Fatal(err)
		}
		want := &doctorcmd.DoctorOptions{SkipAuthProbe: true, Build: true, Quiet: true, JSON: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
}
