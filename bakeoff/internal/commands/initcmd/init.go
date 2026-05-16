package initcmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/spf13/cobra"
)

type InitOptions struct {
	Type  string
	Force bool
}

func NewCmdInit(f commands.Factory, runF func(context.Context, *InitOptions) error) *cobra.Command {
	_ = f
	opts := &InitOptions{}
	cmd := &cobra.Command{
		Use:           "init {gather|compare|analyze|review}",
		Short:         "write an example work order",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.Type = args[0]
			if err := commands.OneOf("type", "gather", "compare", "analyze", "review")(opts.Type); err != nil {
				return err
			}
			if runF == nil {
				return commands.PlaceholderError("init")
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().BoolVar(&opts.Force, "force", false, "overwrite an existing template")
	return cmd
}
