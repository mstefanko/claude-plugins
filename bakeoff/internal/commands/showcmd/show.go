package showcmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type ShowOptions struct {
	RunID       string
	Out         string
	Judge       bool
	JudgePrompt bool
	Triage      bool
}

func NewCmdShow(f commands.Factory, runF func(context.Context, *ShowOptions) error) *cobra.Command {
	_ = f
	opts := &ShowOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "show RUN_ID",
		Short:         "print a run report",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return commands.PlaceholderError("show")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.Judge, "judge", false, "show judge output")
	cmd.Flags().BoolVar(&opts.JudgePrompt, "judge-prompt", false, "show judge prompt")
	cmd.Flags().BoolVar(&opts.Triage, "triage", false, "show triage output")
	return cmd
}
