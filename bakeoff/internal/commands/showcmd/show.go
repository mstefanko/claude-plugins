package showcmd

import (
	"context"
	"os"
	"path/filepath"
	"sort"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type ShowOptions struct {
	RunID       string
	Out         string
	Judge       bool
	JudgePrompt bool
	Triage      bool
}

func NewCmdShow(f commands.Factory, runF func(context.Context, *ShowOptions) error) *cobra.Command {
	_ = f
	opts := &ShowOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "show RUN_ID",
		Short:         "print a run report",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return runShow(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.Judge, "judge", false, "show judge output")
	cmd.Flags().BoolVar(&opts.JudgePrompt, "judge-prompt", false, "show judge prompt")
	cmd.Flags().BoolVar(&opts.Triage, "triage", false, "show triage output")
	return cmd
}

func runShow(_ context.Context, f commands.Factory, opts *ShowOptions) error {
	if boolCount(opts.Judge, opts.JudgePrompt, opts.Triage) > 1 {
		return &apperror.ValidationError{Message: "show artifact flags are mutually exclusive: --judge, --judge-prompt, --triage"}
	}
	runDir, err := ledger.ResolveRunDir(opts.Out, opts.RunID)
	if err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	if opts.Triage {
		return showTriage(f, opts, runDir)
	}
	if opts.JudgePrompt {
		return showGlob(f, runDir, filepath.Join(runDir, "judge", "prompt*.txt"), "judge prompt")
	}
	if opts.Judge {
		return showGlob(f, runDir, filepath.Join(runDir, "judge", "result*.json"), "judge result")
	}
	reportPath := filepath.Join(runDir, "report.md")
	data, err := os.ReadFile(reportPath)
	if err != nil {
		return &apperror.ValidationError{Message: runDir + " has no report.md", Err: err}
	}
	f.Streams().Printf("%s", string(data))
	state, staleInputs := triage.StateDetail(runDir)
	switch state {
	case "yes":
		f.Streams().Printf("\ntriage available: %s\n", ledger.BakeoffShowCommand(opts.RunID, opts.Out, "--triage"))
	case "stale":
		f.Streams().Printf("\ntriage stale%s: %s\n", triage.StaleInputsText(staleInputs), ledger.BakeoffTriageCommand(opts.RunID, opts.Out, true))
	case "dry_run":
		f.Streams().Printf("\ntriage dry run only: %s\n", ledger.BakeoffTriageCommand(opts.RunID, opts.Out, true))
	default:
		woMap := map[string]any{}
		if wo, err := workorder.Load(filepath.Join(runDir, "work-order.json")); err == nil {
			woMap = wo.Raw
		}
		decisionDoc := readJSON(filepath.Join(runDir, "decision.json"))
		if recommendation := triage.ShouldRecommendTriage(woMap, decisionDoc, string(data)); recommendation != "" {
			f.Streams().Printf("\ntriage not yet run: %s\n", ledger.BakeoffTriageCommand(opts.RunID, opts.Out, false))
		}
	}
	return nil
}

func showTriage(f commands.Factory, opts *ShowOptions, runDir string) error {
	triageReport := filepath.Join(runDir, "triage", "triage.md")
	state, staleInputs := triage.StateDetail(runDir)
	if state == "stale" {
		return &apperror.ValidationError{Message: "triage is stale for " + filepath.Base(runDir) + triage.StaleInputsText(staleInputs) + "; run " + ledger.BakeoffTriageCommand(opts.RunID, opts.Out, true)}
	}
	if state == "dry_run" {
		return &apperror.ValidationError{Message: "triage has only a dry run for " + filepath.Base(runDir) + "; run " + ledger.BakeoffTriageCommand(opts.RunID, opts.Out, true)}
	}
	if state != "yes" {
		return &apperror.ValidationError{Message: "triage has not been run for " + filepath.Base(runDir) + "; run " + ledger.BakeoffTriageCommand(opts.RunID, opts.Out, false)}
	}
	data, err := os.ReadFile(triageReport)
	if err != nil {
		return &apperror.ValidationError{Message: "triage has not been run for " + filepath.Base(runDir) + "; run " + ledger.BakeoffTriageCommand(opts.RunID, opts.Out, false), Err: err}
	}
	f.Streams().Printf("%s", string(data))
	return nil
}

func showGlob(f commands.Factory, runDir string, pattern string, label string) error {
	paths, _ := filepath.Glob(pattern)
	sort.Strings(paths)
	if len(paths) == 0 {
		printMissingJudgeArtifacts(f, runDir, label)
		return nil
	}
	for _, path := range paths {
		rel, _ := filepath.Rel(runDir, path)
		f.Streams().Printf("===== %s =====\n", filepath.ToSlash(rel))
		data, err := os.ReadFile(path)
		if err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		f.Streams().Printf("%s\n", string(data))
	}
	return nil
}

func printMissingJudgeArtifacts(f commands.Factory, runDir string, label string) {
	f.Streams().Printf("no %s artifacts found for %s\n", label, filepath.Base(runDir))
}

func boolCount(values ...bool) int {
	count := 0
	for _, value := range values {
		if value {
			count++
		}
	}
	return count
}

func readJSON(path string) map[string]any {
	value, err := workorder.ReadOptionalJSON(path)
	if err != nil {
		return map[string]any{}
	}
	obj, _ := value.(map[string]any)
	if obj == nil {
		return map[string]any{}
	}
	return obj
}
