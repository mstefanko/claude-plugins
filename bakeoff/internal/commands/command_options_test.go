package commands_test

import (
	"bytes"
	"context"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/doctorcmd"
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
	t.Run("research", func(t *testing.T) {
		var got *researchcmd.ResearchOptions
		cmd := researchcmd.NewCmdResearch(testFactory(), func(_ context.Context, opts *researchcmd.ResearchOptions) error {
			copy := *opts
			got = &copy
			return nil
		})
		err := execute(cmd, "work.json", "--out", "ledger", "--run-id", "run-1", "--force", "--quiet", "--no-triage", "--base", "main", "--diff", "--changed-files", "--json")
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
		if err := execute(cmd, "source", "--out", "ledger", "--run-id", "next", "--quiet", "--no-triage"); err != nil {
			t.Fatal(err)
		}
		want := &reruncmd.RerunOptions{SourceRunID: "source", Out: "ledger", NewRunID: "next", Quiet: true, NoTriage: true}
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
		if err := execute(cmd, "--skip-auth-probe", "--quiet", "--json"); err != nil {
			t.Fatal(err)
		}
		want := &doctorcmd.DoctorOptions{SkipAuthProbe: true, Quiet: true, JSON: true}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %#v, want %#v", got, want)
		}
	})
}
