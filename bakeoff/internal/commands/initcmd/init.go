package initcmd

import (
	"context"
	"fmt"
	"os"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type InitOptions struct {
	Type  string
	Force bool
}

func NewCmdInit(f commands.Factory, runF func(context.Context, *InitOptions) error) *cobra.Command {
	opts := &InitOptions{}
	cmd := &cobra.Command{
		Use:           "init {gather|compare|analyze|review|build}",
		Short:         "write an example work order",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.Type = args[0]
			if err := commands.OneOf("type", "gather", "compare", "analyze", "review", "build")(opts.Type); err != nil {
				return err
			}
			if runF == nil {
				return runInit(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().BoolVar(&opts.Force, "force", false, "overwrite an existing template")
	return cmd
}

func runInit(_ context.Context, f commands.Factory, opts *InitOptions) error {
	path := fmt.Sprintf("%s.work-order.json", opts.Type)
	if !opts.Force {
		if exists(path) {
			return &apperror.ValidationError{Message: fmt.Sprintf("%s already exists; use --force to overwrite", path)}
		}
	}
	template, err := workorder.InitTemplate(opts.Type)
	if err != nil {
		return commands.WrapValidation(err)
	}
	if err := workorder.WriteTextAtomic(path, template); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	streams := f.Streams()
	streams.Printf("wrote %s\n", path)
	if opts.Type == "review" {
		streams.Printf("recipe: review (mode gather)\n")
	}
	worker, judge := workorder.ModeEffortDefaults(effectiveMode(opts.Type))
	streams.Printf("effort defaults: workers=%s, judge=%s\n", worker, judge)
	return nil
}

func effectiveMode(kind string) string {
	if kind == "review" {
		return "gather"
	}
	return kind
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
