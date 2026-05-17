package runscmd

import (
	"context"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/verify"
	"github.com/spf13/cobra"
)

type VerifyOptions struct {
	RunID string
	Out   string
	JSON  bool
}

func NewCmdRuns(f commands.Factory, verifyF func(context.Context, *VerifyOptions) error) *cobra.Command {
	cmd := &cobra.Command{
		Use:           "runs",
		Short:         "inspect run ledgers",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	cmd.AddCommand(NewCmdRunsVerify(f, verifyF))
	return cmd
}

func NewCmdRunsVerify(f commands.Factory, runF func(context.Context, *VerifyOptions) error) *cobra.Command {
	_ = f
	opts := &VerifyOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "verify RUN_ID",
		Short:         "verify one run ledger",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return runVerify(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a parseable JSON verification report")
	return cmd
}

func runVerify(_ context.Context, f commands.Factory, opts *VerifyOptions) error {
	if err := ledger.ValidateVerifyRunID(opts.RunID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	runDir, err := ledger.ResolveRunDir(opts.Out, opts.RunID)
	if err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	if ledger.IsPathLikeRunID(opts.RunID) {
		if err := ledger.EnsureVerifyPathInsideOut(opts.Out, runDir); err != nil {
			return &apperror.ValidationError{Message: err.Error(), Err: err}
		}
	}
	displayOutDir := ledger.OutputDirForResolvedRun(opts.Out, runDir)
	result := verify.Run(runDir, displayOutDir)
	if opts.JSON {
		if err := summary.Print(f.Streams().Out, result); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	} else {
		printVerifyHuman(f, result)
	}
	if result.ExitCode != 0 {
		return &apperror.SilentError{Err: errVerifyFailed{}}
	}
	return nil
}

func printVerifyHuman(f commands.Factory, result verify.Result) {
	fingerprints := result.Fingerprints
	f.Streams().Printf("run verify: %s\n", result.RunID)
	f.Streams().Printf("  run dir: %s\n", result.RunDir)
	f.Streams().Printf("  manifest: %s\n", result.Manifest.Status)
	f.Streams().Printf("  required artifacts: %s\n", result.RequiredArtifacts.Status)
	f.Streams().Printf("  fingerprints: %s (%d checked)\n", fingerprints.Status, fingerprints.CheckedCount)
	f.Streams().Printf("  triage: %s%s\n", result.Triage.State, triage.StaleInputsText(result.Triage.StaleInputs))
	if len(result.Problems) > 0 {
		f.Streams().Printf("problems:\n")
		for _, problem := range result.Problems {
			f.Streams().Printf("  - %s\n", problem)
		}
	}
	f.Streams().Printf("next: %s\n", result.Next)
}

type errVerifyFailed struct{}

func (errVerifyFailed) Error() string { return "run verification failed" }
