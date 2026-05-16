package validatecmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type ValidateOptions struct {
	WorkOrder string
}

func NewCmdValidate(f commands.Factory, runF func(context.Context, *ValidateOptions) error) *cobra.Command {
	_ = f
	opts := &ValidateOptions{}
	cmd := &cobra.Command{
		Use:           "validate WORK_ORDER",
		Short:         "validate and dry-run a work order",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.WorkOrder = args[0]
			if runF == nil {
				return commands.PlaceholderError("validate")
			}
			return runF(cmd.Context(), opts)
		},
	}
	return cmd
}
