package buildcmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type BuildOptions struct {
	WorkOrder     string
	Out           string
	RunID         string
	Force         bool
	Quiet         bool
	JSON          bool
	KeepWorktrees bool
	NoRepoLayout  bool
}

func NewCmdBuild(f commands.Factory, runF func(context.Context, *BuildOptions) error) *cobra.Command {
	opts := &BuildOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "build WORK_ORDER",
		Short:         "run a competitive build bakeoff",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.WorkOrder = args[0]
			if runF == nil {
				return RunBuild(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().StringVar(&opts.RunID, "run-id", "", "explicit run id")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "replace an existing run directory")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider and verifier heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a final JSON summary")
	cmd.Flags().BoolVar(&opts.KeepWorktrees, "keep-worktrees", false, "retain build worktrees for debugging")
	cmd.Flags().BoolVar(&opts.NoRepoLayout, "no-repo-layout", false, "suppress generated repo layout context")
	return cmd
}
