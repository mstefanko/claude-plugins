package cli

import (
	"context"
	"os"

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

const orientation = `bakeoff-go - run the same research task across multiple agents, then judge.

Four starts. Pick one based on what you want:
  gather   coverage research
  compare  defended pick
  analyze  thorough explanation
  review   code-review recipe

Get started:
  bakeoff-go init gather
  bakeoff-go validate gather.work-order.json
  bakeoff-go research gather.work-order.json

Provider CLIs required on PATH: ` + "`claude`, `codex`" + `.
Run ` + "`bakeoff-go doctor`" + ` to check.
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
			f.Streams().Printf("%s", orientation)
			return nil
		},
	}
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
