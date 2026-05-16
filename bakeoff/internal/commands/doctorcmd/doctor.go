package doctorcmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type DoctorOptions struct {
	SkipAuthProbe bool
	Quiet         bool
	JSON          bool
}

func NewCmdDoctor(f commands.Factory, runF func(context.Context, *DoctorOptions) error) *cobra.Command {
	_ = f
	opts := &DoctorOptions{}
	cmd := &cobra.Command{
		Use:           "doctor",
		Short:         "check provider CLIs, auth, and local readiness",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			if runF == nil {
				return commands.PlaceholderError("doctor")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().BoolVar(&opts.SkipAuthProbe, "skip-auth-probe", false, "skip spendful provider auth probes")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a parseable JSON readiness report")
	return cmd
}
