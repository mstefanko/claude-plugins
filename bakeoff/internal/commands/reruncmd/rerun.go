package reruncmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/buildcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands/researchcmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type RerunOptions struct {
	SourceRunID  string
	Out          string
	NewRunID     string
	Quiet        bool
	NoTriage     bool
	JudgeOnly    bool
	NoRepoLayout bool
}

var (
	runResearch          = researchcmd.RunResearch
	runResearchJudgeOnly = researchcmd.RunResearchJudgeOnly
	runBuild             = buildcmd.RunBuild
)

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
	cmd.Flags().BoolVar(&opts.JudgeOnly, "judge-only", false, "retry only the failed research judge using existing provider artifacts")
	cmd.Flags().BoolVar(&opts.NoRepoLayout, "no-repo-layout", false, "suppress generated repo layout context")
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
	wo, err := workorder.Load(workOrderPath)
	if err != nil {
		return commands.WrapValidation(err)
	}
	if wo.Type == "build" {
		if opts.JudgeOnly {
			return &apperror.ValidationError{Message: "--judge-only is currently supported only for research runs"}
		}
		f.Streams().Printf("note: build rerun runs against the current source tree, not the original run's snapshot\n")
		return runBuild(ctx, f, &buildcmd.BuildOptions{
			WorkOrder:    workOrderPath,
			Out:          opts.Out,
			RunID:        opts.NewRunID,
			Quiet:        opts.Quiet,
			NoRepoLayout: opts.NoRepoLayout,
		})
	}
	if opts.JudgeOnly {
		if opts.NoRepoLayout {
			return &apperror.ValidationError{Message: "--no-repo-layout has no effect with --judge-only; omit it or run a full rerun"}
		}
		if wo.RunMode == workorder.RunModeSingleProvider {
			return &apperror.ValidationError{Message: "--judge-only requires a pairwise source run with judge evidence"}
		}
		sourceRunID := opts.SourceRunID
		if sourceRunID == "latest" {
			sourceRunID = filepath.Base(sourceRun)
		}
		return runResearchJudgeOnly(ctx, f, &researchcmd.ResearchJudgeOnlyOptions{
			SourceRunDir: sourceRun,
			SourceRunID:  sourceRunID,
			Out:          opts.Out,
			RunID:        opts.NewRunID,
			Quiet:        opts.Quiet,
			NoTriage:     opts.NoTriage,
		})
	}
	return runResearch(ctx, f, &researchcmd.ResearchOptions{
		WorkOrder:          workOrderPath,
		Out:                opts.Out,
		RunID:              opts.NewRunID,
		Quiet:              opts.Quiet,
		NoTriage:           opts.NoTriage,
		NoRepoLayout:       opts.NoRepoLayout,
		ReplaySourceRunDir: sourceRun,
	})
}
