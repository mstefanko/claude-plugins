package draftbuildcmd

import (
	"context"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type DraftBuildOptions struct {
	ID                   string
	Goal                 string
	Acceptance           []string
	Scopes               []string
	Background           []string
	Gates                []string
	ProtectedPaths       []string
	BaseRef              string
	ComparisonGoal       string
	BudgetWallSeconds    int
	BudgetMaxOutputBytes int
	GateWallSeconds      int
	GateMaxOutputBytes   int
}

func NewCmdDraftBuild(f commands.Factory, runF func(context.Context, *DraftBuildOptions) error) *cobra.Command {
	opts := &DraftBuildOptions{
		BaseRef:              workorder.DefaultBuildDraftBaseRef,
		ComparisonGoal:       workorder.DefaultBuildDraftComparisonGoal,
		BudgetWallSeconds:    workorder.DefaultBuildDraftBudgetWallSeconds,
		BudgetMaxOutputBytes: workorder.DefaultBuildDraftBudgetMaxOutputBytes,
		GateWallSeconds:      workorder.DefaultBuildDraftGateWallSeconds,
		GateMaxOutputBytes:   workorder.DefaultBuildDraftGateMaxOutputBytes,
	}
	cmd := &cobra.Command{
		Use:           "draft-build [flags]",
		Short:         "print a validated build work order",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			if _, err := parseGateFlags(opts.Gates); err != nil {
				return commands.WrapValidation(err)
			}
			if runF == nil {
				return runDraftBuild(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.ID, "id", "", "work-order id and suggested filename stem")
	cmd.Flags().StringVar(&opts.Goal, "goal", "", "one-sentence implementation goal")
	cmd.Flags().StringArrayVar(&opts.Acceptance, "acceptance", nil, "observable acceptance criterion (repeatable)")
	cmd.Flags().StringArrayVar(&opts.Scopes, "scope", nil, "edit boundary such as file, package, route, or scope (repeatable)")
	cmd.Flags().StringArrayVar(&opts.Gates, "gate", nil, "gate verifier as <id>=<command> (repeatable)")
	cmd.Flags().StringVar(&opts.BaseRef, "base-ref", workorder.DefaultBuildDraftBaseRef, "build base ref")
	cmd.Flags().StringArrayVar(&opts.Background, "background", nil, "additional context paragraph (repeatable)")
	cmd.Flags().StringArrayVar(&opts.ProtectedPaths, "protected-path", nil, "repository-relative protected path (repeatable)")
	cmd.Flags().StringVar(&opts.ComparisonGoal, "comparison-goal", workorder.DefaultBuildDraftComparisonGoal, "build comparison goal")
	cmd.Flags().IntVar(&opts.BudgetWallSeconds, "budget-wall-seconds", workorder.DefaultBuildDraftBudgetWallSeconds, "work-order wall budget")
	cmd.Flags().IntVar(&opts.BudgetMaxOutputBytes, "budget-max-output-bytes", workorder.DefaultBuildDraftBudgetMaxOutputBytes, "work-order output budget")
	cmd.Flags().IntVar(&opts.GateWallSeconds, "gate-wall-seconds", workorder.DefaultBuildDraftGateWallSeconds, "default wall budget for each gate")
	cmd.Flags().IntVar(&opts.GateMaxOutputBytes, "gate-max-output-bytes", workorder.DefaultBuildDraftGateMaxOutputBytes, "default output budget for each gate")
	return cmd
}

func runDraftBuild(_ context.Context, f commands.Factory, opts *DraftBuildOptions) error {
	gates, err := parseGateFlags(opts.Gates)
	if err != nil {
		return commands.WrapValidation(err)
	}
	doc, err := workorder.DraftBuild(workorder.BuildDraftOptions{
		ID:                   opts.ID,
		Goal:                 opts.Goal,
		Acceptance:           opts.Acceptance,
		Scopes:               opts.Scopes,
		Background:           opts.Background,
		Gates:                gates,
		ProtectedPaths:       opts.ProtectedPaths,
		BaseRef:              opts.BaseRef,
		ComparisonGoal:       opts.ComparisonGoal,
		BudgetWallSeconds:    opts.BudgetWallSeconds,
		BudgetMaxOutputBytes: opts.BudgetMaxOutputBytes,
		GateWallSeconds:      opts.GateWallSeconds,
		GateMaxOutputBytes:   opts.GateMaxOutputBytes,
	})
	if err != nil {
		return commands.WrapValidation(err)
	}
	text, err := workorder.JSONText(doc)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	f.Streams().Printf("%s", text)
	return nil
}

func parseGateFlags(values []string) ([]workorder.GateDraft, error) {
	out := make([]workorder.GateDraft, 0, len(values))
	for i, value := range values {
		index := strings.Index(value, "=")
		if index < 0 {
			return nil, workorder.Validationf("--gate[%d] must use <id>=<command>", i)
		}
		id := strings.TrimSpace(value[:index])
		command := strings.TrimSpace(value[index+1:])
		if id == "" {
			return nil, workorder.Validationf("--gate[%d] id must be non-empty", i)
		}
		if command == "" {
			return nil, workorder.Validationf("--gate[%d] command must be non-empty", i)
		}
		out = append(out, workorder.GateDraft{ID: id, Command: command})
	}
	return out, nil
}
