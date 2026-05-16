package runscmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type VerifyOptions struct {
	RunID string
	Out   string
	JSON  bool
}

func NewCmdRuns(f commands.Factory, verifyF func(context.Context, *VerifyOptions) error) *cobra.Command {
	cmd := &cobra.Command{
		Use:           "runs",
		Short:         "inspect run ledgers",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	cmd.AddCommand(NewCmdRunsVerify(f, verifyF))
	return cmd
}

func NewCmdRunsVerify(f commands.Factory, runF func(context.Context, *VerifyOptions) error) *cobra.Command {
	_ = f
	opts := &VerifyOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "verify RUN_ID",
		Short:         "verify one run ledger",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return commands.PlaceholderError("runs verify")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a parseable JSON verification report")
	return cmd
}
