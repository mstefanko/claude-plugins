package validatecmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type ValidateOptions struct {
	WorkOrder string
}

func NewCmdValidate(f commands.Factory, runF func(context.Context, *ValidateOptions) error) *cobra.Command {
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
				return runValidate(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	return cmd
}

func runValidate(_ context.Context, f commands.Factory, opts *ValidateOptions) error {
	wo, err := workorder.Load(opts.WorkOrder)
	if err != nil {
		return commands.WrapValidation(err)
	}
	streams := f.Streams()
	streams.Printf("valid work order\n")
	streams.Printf("  id:      %s\n", wo.ID)
	streams.Printf("  mode:    %s\n", wo.Type)
	if wo.Facet != nil {
		streams.Printf("  facet:   %s\n", wo.Facet.ID)
	}
	streams.Printf("  budgets: %s\n", workorder.FormatBudgetSummary(wo.Budgets))
	streams.Printf("  scope:   %s\n", wo.ScopePolicy.Enforcement)
	streams.Printf("  providers:\n")
	for _, provider := range wo.Providers {
		streams.Printf("    - %s: %s %s (%s, %s)\n", provider.ID, provider.Backend, provider.Model, provider.Scope, provider.Effort)
	}
	streams.Printf("  judge:   %s %s (%s)\n", wo.Judge.Backend, wo.Judge.Model, wo.Judge.Effort)
	return nil
}
