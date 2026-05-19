package validatecmd

import (
	"context"
	"path/filepath"
	"strconv"
	"strings"

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
	for _, warning := range validateWarnings(wo) {
		streams.Printf("warning: %s\n", warning)
	}
	return nil
}

func validateWarnings(wo *workorder.WorkOrder) []string {
	if wo == nil || wo.Build == nil {
		return nil
	}
	var warnings []string
	for _, verifier := range wo.Build.Verify {
		if verifier.Kind != "metric" {
			continue
		}
		if len(wo.Build.ProtectedPaths) == 0 && len(verifier.Argv) > 0 && repoRelativeCommand(verifier.Argv[0]) {
			warnings = append(warnings, `metric verifier "`+verifier.ID+`" runs repo-relative command "`+verifier.Argv[0]+`" while build.protected_paths is empty; add the verifier script and any data fixtures to build.protected_paths if providers should not edit them`)
		}
		if verifier.Metric != nil && verifier.Metric.MinRuns > 1 {
			warnings = append(warnings, `metric verifier "`+verifier.ID+`" sets metric.min_runs=`+strconv.Itoa(verifier.Metric.MinRuns)+`; final metric JSON must include "n" >= `+strconv.Itoa(verifier.Metric.MinRuns)+` or the metric comparison will be inconclusive`)
		}
	}
	return warnings
}

func repoRelativeCommand(command string) bool {
	command = strings.TrimSpace(command)
	if command == "" || filepath.IsAbs(command) || strings.HasPrefix(command, "../") {
		return false
	}
	return strings.HasPrefix(command, "./") || strings.Contains(command, "/")
}
