package researchcmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type ResearchOptions struct {
	WorkOrder          string
	Out                string
	RunID              string
	Force              bool
	Quiet              bool
	NoTriage           bool
	Base               string
	Diff               bool
	ChangedFiles       bool
	JSON               bool
	ReplaySourceRunDir string
}

func NewCmdResearch(f commands.Factory, runF func(context.Context, *ResearchOptions) error) *cobra.Command {
	_ = f
	opts := &ResearchOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "research WORK_ORDER",
		Short:         "run a research bakeoff",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.WorkOrder = args[0]
			if runF == nil {
				return RunResearch(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().StringVar(&opts.RunID, "run-id", "", "explicit run id")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "replace an existing run directory")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.NoTriage, "no-triage", false, "skip automatic triage for code-review runs")
	cmd.Flags().StringVar(&opts.Base, "base", "", "capture git review context against REF (default for review context: HEAD)")
	cmd.Flags().BoolVar(&opts.Diff, "diff", false, "include a bounded unified patch in generated review context")
	cmd.Flags().BoolVar(&opts.ChangedFiles, "changed-files", false, "include changed-file context against the base ref")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a final JSON summary")
	return cmd
}
