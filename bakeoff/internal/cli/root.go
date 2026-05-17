package cli

import (
	"context"
	"os"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
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
	"github.com/spf13/cobra"
)

const orientation = `bakeoff - run the same research task across multiple agents, then judge.

Four starts. Pick one based on what you want:
  gather   coverage research
  compare  defended pick
  analyze  thorough explanation
  review   code-review recipe

Get started:
  bakeoff init gather
  bakeoff validate gather.work-order.json
  bakeoff research gather.work-order.json

Provider CLIs required on PATH: ` + "`claude`, `codex`" + `.
Run ` + "`bakeoff doctor`" + ` to check.
`

const rootHelp = `usage: bakeoff [-h] [--version]
               {init,validate,research,rerun,triage,runs,ls,show,doctor} ...

Tiny research bakeoff harness.

positional arguments:
  {init,validate,research,rerun,triage,runs,ls,show,doctor}
    init                write an example work order
    validate            validate and dry-run a work order
    research            run a research bakeoff
    rerun               replay a previous work order with a fresh run id
    triage              triage a completed bakeoff report
    runs                inspect run ledgers
    ls                  list past runs
    show                print a run report
    doctor              check provider CLIs, auth, and local readiness

optional arguments:
  -h, --help            show this help message and exit
  --version             show program's version number and exit

Exit codes:
  0  success
  1  generic runtime or verification failure
  2  usage, config, validation, or missing-input error
  3  completed run with unresolved judge disagreement
`

func Main(ctx context.Context, argv []string) int {
	streams := output.NewStreams(os.Stdout, os.Stderr)
	factory := NewFactory(streams)
	root := NewRootCommand(factory)
	root.SetArgs(argv)
	root.SetOut(streams.Out)
	root.SetErr(streams.Err)

	err := root.ExecuteContext(ctx)
	code := ExitCode(err, ctx.Err() == context.Canceled)
	RenderError(streams, err, code)
	return code
}

func NewRootCommand(f *Factory) *cobra.Command {
	root := &cobra.Command{
		Use:           "bakeoff-go",
		Short:         "Tiny research bakeoff harness.",
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       f.BuildInfo().Version,
		CompletionOptions: cobra.CompletionOptions{
			DisableDefaultCmd: true,
		},
		Args: commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			f.Streams().Printf("%s\n", orientation)
			return nil
		},
	}
	root.SetHelpFunc(func(cmd *cobra.Command, args []string) {
		if cmd == root {
			f.Streams().Printf("%s", rootHelp)
			return
		}
		renderCommandHelp(f, cmd)
	})
	root.SetVersionTemplate("{{.Use}} {{.Version}}\n")
	root.SetFlagErrorFunc(func(cmd *cobra.Command, err error) error {
		return &apperror.UsageError{Err: err}
	})
	root.AddCommand(
		initcmd.NewCmdInit(f, nil),
		validatecmd.NewCmdValidate(f, nil),
		researchcmd.NewCmdResearch(f, nil),
		reruncmd.NewCmdRerun(f, nil),
		triagecmd.NewCmdTriage(f, nil),
		runscmd.NewCmdRuns(f, nil),
		lscmd.NewCmdLs(f, nil),
		showcmd.NewCmdShow(f, nil),
		doctorcmd.NewCmdDoctor(f, nil),
	)
	return root
}

func renderCommandHelp(f *Factory, cmd *cobra.Command) {
	if cmd.Short != "" {
		f.Streams().Printf("%s\n\n", cmd.Short)
	}
	f.Streams().Printf("Usage:\n  %s\n", cmd.UseLine())
	if cmd.HasAvailableSubCommands() {
		f.Streams().Printf("\nAvailable Commands:\n")
		for _, child := range cmd.Commands() {
			if !child.IsAvailableCommand() && child.Name() != "help" {
				continue
			}
			f.Streams().Printf("  %-12s %s\n", child.Name(), child.Short)
		}
	}
	flags := cmd.NonInheritedFlags()
	if flags.HasAvailableFlags() {
		usages := strings.TrimRight(flags.FlagUsagesWrapped(80), "\n")
		if usages != "" {
			f.Streams().Printf("\nFlags:\n%s\n", usages)
		}
	}
	f.Streams().Printf("\n")
}
