package reruncmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/researchcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
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
				return runRerun(cmd.Context(), f, opts)
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

func runRerun(ctx context.Context, f commands.Factory, opts *RerunOptions) error {
	if err := ledger.ValidateLookupRunID(opts.SourceRunID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	sourceRun, err := ledger.ResolveRunDir(opts.Out, opts.SourceRunID)
	if err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	workOrderPath := filepath.Join(sourceRun, "work-order.json")
	if info, err := os.Stat(workOrderPath); err != nil || info.IsDir() {
		return &apperror.ValidationError{Message: fmt.Sprintf("%s has no work-order.json", sourceRun), Err: err}
	}
	return researchcmd.RunResearch(ctx, f, &researchcmd.ResearchOptions{
		WorkOrder:          workOrderPath,
		Out:                opts.Out,
		RunID:              opts.NewRunID,
		Quiet:              opts.Quiet,
		NoTriage:           opts.NoTriage,
		ReplaySourceRunDir: sourceRun,
	})
}
