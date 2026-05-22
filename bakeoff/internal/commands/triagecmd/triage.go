package triagecmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type TriageOptions struct {
	RunID  string
	Out    string
	Force  bool
	DryRun bool
	Quiet  bool
	JSON   bool

	RunDir       string
	DisplayRunID string
	HumanOutput  *bool
}

func NewCmdTriage(f commands.Factory, runF func(context.Context, *TriageOptions) error) *cobra.Command {
	_ = f
	opts := &TriageOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "triage RUN_ID",
		Short:         "triage a completed bakeoff report",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				exitCode, err := Run(cmd.Context(), f, opts)
				if err != nil {
					return err
				}
				if exitCode != 0 {
					return &apperror.SilentError{Err: fmt.Errorf("triage failed")}
				}
				return nil
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "replace an existing triage directory")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "build triage inputs without invoking a provider")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a final JSON summary")
	return cmd
}

func Run(ctx context.Context, f commands.Factory, opts *TriageOptions) (int, error) {
	humanOutput := !opts.JSON
	if opts.HumanOutput != nil {
		humanOutput = *opts.HumanOutput
	}
	effectiveQuiet := opts.Quiet || opts.JSON || !humanOutput
	runDir := opts.RunDir
	var err error
	if runDir == "" {
		if err := ledger.ValidateLookupRunID(opts.RunID); err != nil {
			return 0, &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		runDir, err = ledger.ResolveRunDir(opts.Out, opts.RunID)
		if err != nil {
			return 0, &apperror.ValidationError{Message: err.Error(), Err: err}
		}
	}
	commandRunID := opts.RunID
	if opts.DisplayRunID != "" {
		commandRunID = opts.DisplayRunID
	}
	if commandRunID == "" {
		commandRunID = filepath.Base(runDir)
	}
	displayOutDir := opts.Out
	if displayOutDir == "" {
		displayOutDir = filepath.Dir(runDir)
	}
	wo, err := workorder.Load(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return 0, commands.WrapValidation(err)
	}
	decisionDoc, err := workorder.ReadRequiredObject(filepath.Join(runDir, "decision.json"))
	if err != nil {
		return 0, &apperror.ValidationError{Message: fmt.Sprintf("%s has no valid decision.json", runDir), Err: err}
	}
	reportPath := filepath.Join(runDir, "report.md")
	reportData, err := os.ReadFile(reportPath)
	if err != nil {
		return 0, &apperror.ValidationError{Message: fmt.Sprintf("%s has no report.md", runDir), Err: err}
	}
	meta := map[string]any{}
	if value, err := workorder.ReadOptionalJSON(filepath.Join(runDir, "meta.json")); err == nil {
		if obj, ok := value.(map[string]any); ok {
			meta = obj
		}
	}
	reportText := string(reportData)
	inputHashes, err := triage.ComputeInputHashes(runDir)
	if err != nil {
		return 0, commands.WrapValidation(&workorder.ValidationError{Message: err.Error(), Err: err})
	}
	citationCWD, caveats := triage.ResolveCitationCWD(meta)
	targetTriageDir := filepath.Join(runDir, "triage")
	triageDir := targetTriageDir
	stagedTriageDir := ""
	if _, err := os.Stat(targetTriageDir); err == nil {
		if !opts.Force {
			return 0, &apperror.ValidationError{Message: fmt.Sprintf("%s already exists; run %s to replace", targetTriageDir, ledger.BakeoffTriageCommand(commandRunID, displayOutDir, true))}
		}
		if err := ledger.EnsureChildPath(runDir, targetTriageDir); err != nil {
			return 0, &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		stagedTriageDir, err = os.MkdirTemp(runDir, ".triage-")
		if err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
		triageDir = stagedTriageDir
		defer func() {
			if stagedTriageDir != "" {
				_ = os.RemoveAll(stagedTriageDir)
			}
		}()
	}
	if err := os.MkdirAll(triageDir, 0o700); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}

	findingIndex, synthesized := triage.BuildFindingIndex(reportText)
	sourceFindings, skippedFindings := triage.SelectTriageSourceFindings(findingIndex, triage.FacetID(wo.Raw))
	sourceFindingFilter := triage.SummarizeSourceFindingFilter(sourceFindings, skippedFindings)
	if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "source_finding_filter.json"), map[string]any{
		"schema_version": 1,
		"summary":        sourceFindingFilter,
		"selected":       sourceFindings,
		"skipped":        skippedFindings,
	}); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if synthesized {
		caveats = append(caveats, "source finding IDs were synthesized from report display order")
		if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "finding_index.json"), map[string]any{"schema_version": 1, "findings": findingIndex}); err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
	}
	citationText := triage.CollectCitationText(runDir, reportText, decisionDoc)
	citationChecks := triage.CheckCitations(triage.ExtractCitationsFromText(citationText), citationCWD)
	if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "citation_checks.json"), citationChecks); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	workOrderText, err := os.ReadFile(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	payload := map[string]any{
		"schema_version":        1,
		"run_id":                filepath.Base(runDir),
		"work_order_json":       string(workOrderText),
		"facet":                 wo.Raw["facet"],
		"meta":                  meta,
		"decision":              decisionDoc,
		"report_md":             reportText,
		"source_findings":       sourceFindings,
		"source_finding_filter": sourceFindingFilter,
		"citation_checks":       citationChecks,
		"caveats":               caveats,
		"input_hashes":          inputHashes,
	}
	triagePrompt, err := prompt.BuildTriagePrompt(payload, wo.Budgets)
	if err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if err := workorder.WriteTextAtomic(filepath.Join(triageDir, "prompt.txt"), triagePrompt); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	participant := triageParticipant(wo.Judge)
	if humanOutput {
		f.Streams().Printf("triage participant: %s %s (effort %s)\n", wo.Judge.Backend, wo.Judge.Model, wo.Judge.Effort)
		f.Streams().Errorf("note: triage invokes one provider call; use --dry-run to inspect inputs only\n")
		f.Streams().Printf("source findings: selected %d; skipped %d non-actionable; skipped %d out-of-facet\n", sourceFindingFilter["included"], sourceFindingFilter["skipped_non_actionable"], sourceFindingFilter["skipped_out_of_facet"])
		f.Streams().Printf("source filter: %s\n", filepath.Join(targetTriageDir, "source_finding_filter.json"))
	}
	if opts.DryRun {
		if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "status.json"), map[string]any{
			"status":                "dry_run",
			"triage_participant":    participant,
			"input_hashes":          inputHashes,
			"source_finding_filter": sourceFindingFilter,
		}); err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
		if stagedTriageDir != "" {
			if err := replaceDirAtomically(targetTriageDir, stagedTriageDir); err != nil {
				return 0, &apperror.RuntimeError{Err: err}
			}
			stagedTriageDir = ""
		}
		if _, err := manifest.WriteRunManifest(runDir); err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
		if humanOutput {
			f.Streams().Printf("triage dry run: %s\n", filepath.Join(targetTriageDir, "prompt.txt"))
			f.Streams().Printf("triage status:  %s\n", filepath.Join(targetTriageDir, "status.json"))
			f.Streams().Printf("next:           %s\n", ledger.BakeoffTriageCommand(commandRunID, displayOutDir, true))
		}
		if opts.JSON {
			if err := summary.Print(f.Streams().Out, summary.BuildTriage(runDir, commandRunID, displayOutDir, 0, true)); err != nil {
				return 0, &apperror.RuntimeError{Err: err}
			}
		}
		return 0, nil
	}

	selectedSourceIDs := map[string]bool{}
	for _, finding := range sourceFindings {
		selectedSourceIDs[finding["id"]] = true
	}
	citationCheckIDs := triage.CitationCheckIDs(citationChecks)
	finalMessagePath := ""
	outputLastMessage := commands.OutputLastMessageSupported(ctx, f, wo.Judge)
	if outputLastMessage {
		finalMessagePath = filepath.Join(triageDir, "last-message.txt")
	}
	argv, err := provider.BuildParticipantArgv(wo.Judge, citationCWD, nil, finalMessagePath, outputLastMessage)
	if err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           triagePrompt,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              citationCWD,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        triageValidator(selectedSourceIDs, citationCheckIDs, filepath.Base(runDir), inputHashes, participant, sourceFindingFilter),
		OnTick:           commands.MakeTickPrinter(f, "triage", effectiveQuiet),
		FinalMessagePath: finalMessagePath,
	}))
	if ctx.Err() != nil {
		return 0, ctx.Err()
	}
	if err := writeTriageResultArtifacts(triageDir, result, participant, inputHashes, sourceFindingFilter); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if !artifact.ProviderSucceeded(result) {
		if stagedTriageDir == "" {
			if _, err := manifest.WriteRunManifest(runDir); err != nil {
				return 0, &apperror.RuntimeError{Err: err}
			}
		}
		if humanOutput {
			status, _ := result["status"].(string)
			f.Streams().Printf("triage failed: %s\n", status)
			if stagedTriageDir != "" {
				f.Streams().Printf("previous triage preserved: %s\n", targetTriageDir)
			}
			f.Streams().Printf("retry:  %s\n", ledger.BakeoffTriageCommand(commandRunID, displayOutDir, true))
		}
		if opts.JSON {
			if err := summary.Print(f.Streams().Out, summary.BuildTriage(runDir, commandRunID, displayOutDir, 1, false)); err != nil {
				return 0, &apperror.RuntimeError{Err: err}
			}
		}
		return 1, nil
	}
	finalJSON, _ := result["final_json"].(map[string]any)
	if err := workorder.WriteJSONAtomic(filepath.Join(triageDir, "final.json"), finalJSON); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if err := workorder.WriteTextAtomic(filepath.Join(triageDir, "triage.md"), triage.RenderTriageMarkdown(finalJSON, caveats)); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if stagedTriageDir != "" {
		if err := replaceDirAtomically(targetTriageDir, stagedTriageDir); err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
		stagedTriageDir = ""
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		return 0, &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		f.Streams().Printf("triage: %s\n", filepath.Join(targetTriageDir, "triage.md"))
		items, fixNow := triageResultCounts(finalJSON)
		f.Streams().Printf("result: triage complete, items=%d, fix_now=%d\n", items, fixNow)
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(commandRunID, displayOutDir, "--triage"))
	}
	if opts.JSON {
		if err := summary.Print(f.Streams().Out, summary.BuildTriage(runDir, commandRunID, displayOutDir, 0, false)); err != nil {
			return 0, &apperror.RuntimeError{Err: err}
		}
	}
	return 0, nil
}

func triageValidator(selectedSourceIDs map[string]bool, citationCheckIDs map[string]bool, runID string, inputHashes map[string]string, participant map[string]any, sourceFindingFilter map[string]int) func(any) (any, error) {
	return func(data any) (any, error) {
		validated, err := workorder.ValidateTriageResult(data)
		if err != nil {
			return nil, err
		}
		final, ok := validated.(map[string]any)
		if !ok {
			return nil, workorder.Validationf("triage final_json must be an object")
		}
		unknownIDs := []string{}
		unknownCitationIDs := []string{}
		items, _ := final["items"].([]any)
		for _, item := range items {
			obj, ok := item.(map[string]any)
			if !ok {
				continue
			}
			sourceID, _ := obj["source_finding_id"].(string)
			if !selectedSourceIDs[sourceID] {
				unknownIDs = append(unknownIDs, sourceID)
			}
			for _, citationID := range stringList(obj["citation_check_ids"]) {
				if !citationCheckIDs[citationID] {
					unknownCitationIDs = append(unknownCitationIDs, citationID)
				}
			}
		}
		sort.Strings(unknownIDs)
		if len(unknownIDs) > 0 {
			return nil, workorder.Validationf("triage final_json.items source_finding_id must reference selected source_findings (unknown: %s)", strings.Join(unknownIDs, ", "))
		}
		sort.Strings(unknownCitationIDs)
		if len(unknownCitationIDs) > 0 {
			return nil, workorder.Validationf("triage final_json.items citation_check_ids must reference citation_checks (unknown: %s)", strings.Join(unknownCitationIDs, ", "))
		}
		final["run_id"] = runID
		final["input_hashes"] = inputHashes
		final["triage_participant"] = participant
		final["source_finding_filter"] = sourceFindingFilter
		return final, nil
	}
}

func writeTriageResultArtifacts(triageDir string, result map[string]any, participant map[string]any, inputHashes map[string]string, sourceFindingFilter map[string]int) error {
	if err := workorder.WriteTextAtomic(filepath.Join(triageDir, "stdout.txt"), jsonutil.StringValue(result["stdout"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(triageDir, "stderr.txt"), jsonutil.StringValue(result["stderr"])); err != nil {
		return err
	}
	if err := artifact.WriteFormatRetryArtifacts(triageDir, result, ""); err != nil {
		return err
	}
	status := artifact.StatusWithoutPayload(result)
	status["triage_participant"] = participant
	status["input_hashes"] = inputHashes
	status["source_finding_filter"] = sourceFindingFilter
	return workorder.WriteJSONAtomic(filepath.Join(triageDir, "status.json"), status)
}

func triageParticipant(participant workorder.Participant) map[string]any {
	return map[string]any{
		"backend": participant.Backend,
		"model":   participant.Model,
		"effort":  participant.Effort,
	}
}

func triageResultCounts(final map[string]any) (int, int) {
	items, _ := final["items"].([]any)
	fixNow := 0
	for _, item := range items {
		obj, _ := item.(map[string]any)
		if obj["recommended_action"] == "fix_now" {
			fixNow++
		}
	}
	return len(items), fixNow
}

func stringList(value any) []string {
	items, _ := value.([]any)
	out := []string{}
	for _, item := range items {
		if text, ok := item.(string); ok {
			out = append(out, text)
		}
	}
	return out
}

func replaceDirAtomically(target string, replacement string) error {
	if _, err := os.Stat(target); err != nil {
		if os.IsNotExist(err) {
			return os.Rename(replacement, target)
		}
		return err
	}
	backup, err := os.MkdirTemp(filepath.Dir(target), ".triage-backup-")
	if err != nil {
		return err
	}
	if err := os.RemoveAll(backup); err != nil {
		return err
	}
	if err := os.Rename(target, backup); err != nil {
		return err
	}
	if err := os.Rename(replacement, target); err != nil {
		_ = os.Rename(backup, target)
		return err
	}
	return os.RemoveAll(backup)
}
