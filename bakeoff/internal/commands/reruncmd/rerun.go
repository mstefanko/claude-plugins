package reruncmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type RerunOptions struct {
	SourceRunID string
	Out         string
	NewRunID    string
	Quiet       bool
	NoTriage    bool
}

func NewCmdRerun(f commands.Factory, runF func(context.Context, *RerunOptions) error) *cobra.Command {
	_ = f
	opts := &RerunOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "rerun SOURCE_RUN_ID",
		Short:         "replay a previous work order with a fresh run id",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.SourceRunID = args[0]
			if runF == nil {
				return commands.PlaceholderError("rerun")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().StringVar(&opts.NewRunID, "run-id", "", "explicit new run id")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.NoTriage, "no-triage", false, "skip automatic triage for code-review runs")
	return cmd
}
