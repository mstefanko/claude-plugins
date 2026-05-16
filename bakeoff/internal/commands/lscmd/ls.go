package lscmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type LsOptions struct {
	Out         string
	JSON        bool
	Facet       string
	TriageState string
}

func NewCmdLs(f commands.Factory, runF func(context.Context, *LsOptions) error) *cobra.Command {
	_ = f
	opts := &LsOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "ls",
		Short:         "list past runs",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := commands.ValidateEnumFlag(opts.TriageState, "triage-state", "no", "dry_run", "yes", "stale"); err != nil {
				return err
			}
			if runF == nil {
				return commands.PlaceholderError("ls")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a manifest-backed JSON listing")
	cmd.Flags().StringVar(&opts.Facet, "facet", "", "filter by facet id")
	cmd.Flags().StringVar(&opts.TriageState, "triage-state", "", "filter by triage state")
	return cmd
}
