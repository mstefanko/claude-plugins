package triagecmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type TriageOptions struct {
	RunID  string
	Out    string
	Force  bool
	DryRun bool
	Quiet  bool
	JSON   bool
}

func NewCmdTriage(f commands.Factory, runF func(context.Context, *TriageOptions) error) *cobra.Command {
	_ = f
	opts := &TriageOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "triage RUN_ID",
		Short:         "triage a completed bakeoff report",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return commands.PlaceholderError("triage")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "replace an existing triage directory")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "build triage inputs without invoking a provider")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a final JSON summary")
	return cmd
}
