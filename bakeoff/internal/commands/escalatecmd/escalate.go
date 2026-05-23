package escalatecmd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	triagecmd "github.com/mstefanko/claude-plugins/bakeoff/internal/commands/triagecmd"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/decision"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/repocontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/report"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/scope"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	triagepkg "github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

const (
	ModeIndependent = "independent"
	ModeWitness     = "witness"
	ModeDispute     = "dispute"
)

type EscalateOptions struct {
	SourceRunID  string
	Out          string
	RunID        string
	DryRun       bool
	Quiet        bool
	JSON         bool
	NoTriage     bool
	NoRepoLayout bool
	Mode         string
	Provider     string
	Scope        string
}

type sourceRun struct {
	ID              string
	Dir             string
	WorkOrder       *workorder.WorkOrder
	WorkOrderText   string
	Decision        map[string]any
	Meta            map[string]any
	ReportText      string
	WorkerResults   map[string]map[string]any
	ProviderFinals  map[string]any
	ProviderIDs     []string
	JudgeResults    map[string]any
	ReviewContextMD string
	ReviewContext   any
	TriageArtifacts map[string]any
}

type estimate struct {
	ProviderCalls int
	JudgePasses   int
	Triage        bool
	Details       string
}

func NewCmdEscalate(f commands.Factory, runF func(context.Context, *EscalateOptions) error) *cobra.Command {
	_ = f
	opts := &EscalateOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "escalate SOURCE_RUN_ID",
		Short:         "run one post-run provider escalation",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.SourceRunID = args[0]
			if runF == nil {
				return Run(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().StringVar(&opts.RunID, "run-id", "", "explicit escalation run id")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "validate and print the call envelope without creating a run")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a final JSON summary")
	cmd.Flags().BoolVar(&opts.NoTriage, "no-triage", false, "skip automatic triage for code-review escalation runs")
	cmd.Flags().BoolVar(&opts.NoRepoLayout, "no-repo-layout", false, "suppress generated repo layout context for independent mode")
	cmd.Flags().StringVar(&opts.Mode, "mode", "", "escalation mode: independent, witness, or dispute")
	cmd.Flags().StringVar(&opts.Provider, "provider", "", "added provider backend and optional model, e.g. gemini or gemini:pro")
	cmd.Flags().StringVar(&opts.Scope, "scope", "", "added-provider scope for independent mode: codebase, web, or mixed")
	return cmd
}

func Run(ctx context.Context, f commands.Factory, opts *EscalateOptions) error {
	humanOutput := !opts.JSON
	effectiveQuiet := opts.Quiet || opts.JSON
	if err := validateMode(opts.Mode); err != nil {
		return err
	}
	if strings.TrimSpace(opts.Provider) == "" {
		return &apperror.ValidationError{Message: "--provider is required"}
	}
	if err := ledger.ValidateLookupRunID(opts.SourceRunID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	sourceDir, err := ledger.ResolveRunDir(opts.Out, opts.SourceRunID)
	if err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	src, err := loadSourceRun(sourceDir, opts.SourceRunID)
	if err != nil {
		return err
	}
	scopeValue, err := resolveAddedScope(src.WorkOrder, opts.Mode, opts.Scope)
	if err != nil {
		return err
	}
	added, err := parseAddedProvider(opts.Provider, scopeValue, src)
	if err != nil {
		return err
	}
	if opts.Mode == ModeDispute && len(jsonutil.ListValue(buildDisputePacket(src)["points"])) == 0 {
		return &apperror.ValidationError{Message: "no focused dispute points could be extracted; use --mode witness or --mode independent instead"}
	}
	calls := estimateCalls(src.WorkOrder, opts.Mode, !opts.NoTriage)
	if opts.DryRun {
		if humanOutput {
			printDryRun(f, src, added, opts, calls)
		}
		if opts.JSON {
			value := summary.BuildEscalation("", "", opts.Out, src.ID, src.Dir, opts.Mode, added.ID, src.ProviderIDs, nil, nil, 0, true, estimateMap(calls), false, nil)
			if err := summary.Print(f.Streams().Out, value); err != nil {
				return &apperror.RuntimeError{Err: err}
			}
		}
		return nil
	}
	runID := opts.RunID
	if runID == "" {
		runID = ledger.MakeRunID(f.Now(), fsutil.RandomSuffix())
	}
	if err := ledger.ValidateRunID(runID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	runDir := ledger.RunDir(opts.Out, runID)
	if _, err := os.Stat(runDir); err == nil {
		return &apperror.ValidationError{Message: fmt.Sprintf("%s already exists", runDir)}
	} else if !os.IsNotExist(err) {
		return &apperror.RuntimeError{Err: err}
	}
	startedAt := artifact.UTCNow()
	if err := os.MkdirAll(runDir, 0o700); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := ledger.UpdateLatest(opts.Out, runID); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := writeEscalationScaffold(src, added, opts, runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		printRunHeader(f, src, added, opts, runID, runDir, calls)
	}
	result, err := runEscalationMode(ctx, f, src, added, opts, runID, runDir, effectiveQuiet, humanOutput)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return err
		}
		return commands.WrapValidation(err)
	}
	commands.AttachPromptTrim(result.Decision, result.PromptTrims)
	finalExitCode, err := finalizeEscalationRun(ctx, f, finalizeOptions{
		Source:             src,
		Added:              added,
		Out:                opts.Out,
		RunID:              runID,
		RunDir:             runDir,
		StartedAt:          startedAt,
		Decision:           result.Decision,
		AddedResult:        result.AddedResult,
		AddedFinal:         result.AddedFinal,
		AllProviderResults: result.AllProviderResults,
		DisputePacket:      result.DisputePacket,
		ExitCode:           result.ExitCode,
		NoTriage:           opts.NoTriage,
		JSON:               opts.JSON,
		Quiet:              effectiveQuiet,
		HumanOutput:        humanOutput,
	})
	if err != nil {
		return err
	}
	if finalExitCode == 3 {
		return &apperror.SilentError{Err: &apperror.JudgeDisagreementError{Message: "escalation unresolved"}}
	}
	if finalExitCode != 0 {
		return &apperror.SilentError{Err: fmt.Errorf("escalation failed")}
	}
	return nil
}

type modeResult struct {
	Decision           map[string]any
	AddedResult        map[string]any
	AddedFinal         map[string]any
	AllProviderResults map[string]map[string]any
	DisputePacket      map[string]any
	PromptTrims        []prompt.TrimRecord
	ExitCode           int
}

type finalizeOptions struct {
	Source             sourceRun
	Added              workorder.Participant
	Out                string
	RunID              string
	RunDir             string
	StartedAt          string
	Decision           map[string]any
	AddedResult        map[string]any
	AddedFinal         map[string]any
	AllProviderResults map[string]map[string]any
	DisputePacket      map[string]any
	ExitCode           int
	NoTriage           bool
	JSON               bool
	Quiet              bool
	HumanOutput        bool
}

func runEscalationMode(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, runID string, runDir string, quiet bool, humanOutput bool) (modeResult, error) {
	switch opts.Mode {
	case ModeWitness:
		return runWitness(ctx, f, src, added, opts, runDir, quiet, humanOutput)
	case ModeDispute:
		return runDispute(ctx, f, src, added, opts, runDir, quiet, humanOutput)
	default:
		return runIndependent(ctx, f, src, added, opts, runDir, quiet, humanOutput)
	}
}

func runWitness(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, runDir string, quiet bool, humanOutput bool) (modeResult, error) {
	payload := sourcePayload(src)
	witnessPrompt, err := prompt.BuildEscalationWitnessPrompt(payload, src.WorkOrder.Budgets)
	if err != nil {
		return modeResult{}, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "escalation", "witness-prompt.txt"), witnessPrompt); err != nil {
		return modeResult{}, err
	}
	result, trims, err := runAddedPrompt(ctx, f, src.WorkOrder, added, runDir, "witness", witnessPrompt, quiet, humanOutput, workorder.ValidateEscalationWitnessResult)
	if err != nil {
		return modeResult{}, err
	}
	allResults := mergeProviderResults(src.WorkerResults, added.ID, result)
	input := escalationBaseInput(src, added, ModeWitness, allProviderStatuses(src, added.ID, result))
	if !artifact.ProviderSucceeded(result) {
		return modeResult{
			Decision:           decision.EscalationFailedDecision(input, "added provider failed in witness mode"),
			AddedResult:        result,
			AllProviderResults: allResults,
			PromptTrims:        trims,
			ExitCode:           1,
		}, nil
	}
	final := jsonutil.FinalJSONMap(result)
	return modeResult{
		Decision:           decision.ResolveEscalationWitness(input, final),
		AddedResult:        result,
		AddedFinal:         final,
		AllProviderResults: allResults,
		PromptTrims:        trims,
		ExitCode:           0,
	}, nil
}

func runDispute(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, runDir string, quiet bool, humanOutput bool) (modeResult, error) {
	packet := buildDisputePacket(src)
	if len(jsonutil.ListValue(packet["points"])) == 0 {
		return modeResult{}, &workorder.ValidationError{Message: "no focused dispute points could be extracted; use --mode witness or --mode independent instead"}
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "escalation", "dispute-packet.json"), packet); err != nil {
		return modeResult{}, err
	}
	payload := sourcePayload(src)
	payload["dispute_packet"] = packet
	disputePrompt, err := prompt.BuildEscalationDisputePrompt(payload, src.WorkOrder.Budgets)
	if err != nil {
		return modeResult{}, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "escalation", "dispute-prompt.txt"), disputePrompt); err != nil {
		return modeResult{}, err
	}
	result, trims, err := runAddedPrompt(ctx, f, src.WorkOrder, added, runDir, "dispute", disputePrompt, quiet, humanOutput, workorder.ValidateEscalationDisputeResult)
	if err != nil {
		return modeResult{}, err
	}
	allResults := mergeProviderResults(src.WorkerResults, added.ID, result)
	input := escalationBaseInput(src, added, ModeDispute, allProviderStatuses(src, added.ID, result))
	if !artifact.ProviderSucceeded(result) {
		return modeResult{
			Decision:           decision.EscalationFailedDecision(input, "added provider failed in dispute mode"),
			AddedResult:        result,
			AllProviderResults: allResults,
			DisputePacket:      packet,
			PromptTrims:        trims,
			ExitCode:           1,
		}, nil
	}
	final := jsonutil.FinalJSONMap(result)
	return modeResult{
		Decision:           decision.ResolveEscalationDispute(input, final),
		AddedResult:        result,
		AddedFinal:         final,
		AllProviderResults: allResults,
		DisputePacket:      packet,
		PromptTrims:        trims,
		ExitCode:           0,
	}, nil
}

func runIndependent(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, runDir string, quiet bool, humanOutput bool) (modeResult, error) {
	repoLayoutBlock := ""
	if !opts.NoRepoLayout {
		if repocontext.ParticipantReceivesLayout(src.WorkOrder.ScopePolicy, added, opts.NoRepoLayout) {
			block, err := repocontext.BuildLayoutBlock(mustGetwd())
			if err != nil {
				return modeResult{}, err
			}
			repoLayoutBlock = block
		}
	}
	workerPrompt, err := prompt.BuildWorkerPromptWithRepoLayout(src.WorkOrder, added, repocontext.LayoutBlockForParticipant(src.WorkOrder.ScopePolicy, added, repoLayoutBlock, opts.NoRepoLayout))
	if err != nil {
		return modeResult{}, err
	}
	addedResult, workerTrims, err := runAddedPrompt(ctx, f, src.WorkOrder, added, runDir, "independent", workerPrompt, quiet, humanOutput, func(data any) (any, error) {
		return workorder.ValidateWorkerResult(data, src.WorkOrder.Type)
	})
	if err != nil {
		return modeResult{}, err
	}
	allResults := mergeProviderResults(src.WorkerResults, added.ID, addedResult)
	input := escalationBaseInput(src, added, ModeIndependent, allProviderStatuses(src, added.ID, addedResult))
	if !artifact.ProviderSucceeded(addedResult) {
		return modeResult{
			Decision:           decision.EscalationFailedDecision(input, "added provider failed in independent mode"),
			AddedResult:        addedResult,
			AllProviderResults: allResults,
			PromptTrims:        workerTrims,
			ExitCode:           1,
		}, nil
	}
	addedFinal := jsonutil.FinalJSONMap(addedResult)
	if src.WorkOrder.Type == "gather" {
		return runIndependentGather(ctx, f, src, added, input, addedResult, addedFinal, allResults, runDir, quiet, humanOutput, workerTrims)
	}
	return runIndependentSynthesis(ctx, f, src, added, input, addedResult, addedFinal, allResults, runDir, quiet, humanOutput, workerTrims)
}

func runIndependentGather(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, input decision.EscalationBaseInput, addedResult map[string]any, addedFinal map[string]any, allResults map[string]map[string]any, runDir string, quiet bool, humanOutput bool, trims []prompt.TrimRecord) (modeResult, error) {
	payload := sourcePayload(src)
	payload["added_provider_final"] = addedFinal
	unionPrompt, err := prompt.BuildEscalationGatherUnionPrompt(payload, src.WorkOrder.Budgets)
	if err != nil {
		return modeResult{}, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "escalation", "synthesis-prompt.txt"), unionPrompt); err != nil {
		return modeResult{}, err
	}
	sourceLabels := append(append([]string{}, src.ProviderIDs...), added.ID)
	judgeResult, judgeTrims, err := runJudgePrompt(ctx, f, src.WorkOrder, runDir, "synthesis", unionPrompt, quiet, humanOutput, func(data any) (any, error) {
		return workorder.ValidateEscalationGatherUnionResult(data, sourceLabels)
	})
	if err != nil {
		return modeResult{}, err
	}
	trims = append(trims, judgeTrims...)
	if !artifact.ProviderSucceeded(judgeResult) {
		return modeResult{
			Decision:           decision.EscalationFailedDecision(input, "escalation union judge failed"),
			AddedResult:        addedResult,
			AddedFinal:         addedFinal,
			AllProviderResults: allResults,
			PromptTrims:        trims,
			ExitCode:           1,
		}, nil
	}
	return modeResult{
		Decision:           decision.ResolveEscalationGatherUnion(input, jsonutil.FinalJSONMap(judgeResult)),
		AddedResult:        addedResult,
		AddedFinal:         addedFinal,
		AllProviderResults: allResults,
		PromptTrims:        trims,
		ExitCode:           0,
	}, nil
}

func runIndependentSynthesis(ctx context.Context, f commands.Factory, src sourceRun, added workorder.Participant, input decision.EscalationBaseInput, addedResult map[string]any, addedFinal map[string]any, allResults map[string]map[string]any, runDir string, quiet bool, humanOutput bool, trims []prompt.TrimRecord) (modeResult, error) {
	payload := sourcePayload(src)
	payload["added_provider_final"] = addedFinal
	synthesisPrompt, err := prompt.BuildEscalationSynthesisPrompt(payload, src.WorkOrder.Budgets)
	if err != nil {
		return modeResult{}, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "escalation", "synthesis-prompt.txt"), synthesisPrompt); err != nil {
		return modeResult{}, err
	}
	sourceLabels := append(append([]string{}, src.ProviderIDs...), added.ID)
	judgeResult, judgeTrims, err := runJudgePrompt(ctx, f, src.WorkOrder, runDir, "synthesis", synthesisPrompt, quiet, humanOutput, func(data any) (any, error) {
		return workorder.ValidateEscalationSynthesisResult(data, sourceLabels)
	})
	if err != nil {
		return modeResult{}, err
	}
	trims = append(trims, judgeTrims...)
	if !artifact.ProviderSucceeded(judgeResult) {
		return modeResult{
			Decision:           decision.EscalationFailedDecision(input, "escalation synthesis judge failed"),
			AddedResult:        addedResult,
			AddedFinal:         addedFinal,
			AllProviderResults: allResults,
			PromptTrims:        trims,
			ExitCode:           1,
		}, nil
	}
	decisionDoc := decision.ResolveEscalationSynthesis(input, jsonutil.FinalJSONMap(judgeResult))
	exitCode := 0
	if jsonutil.StringValue(decisionDoc["decision_kind"]) == decision.EscalationStillUnresolved {
		exitCode = 3
	}
	return modeResult{
		Decision:           decisionDoc,
		AddedResult:        addedResult,
		AddedFinal:         addedFinal,
		AllProviderResults: allResults,
		PromptTrims:        trims,
		ExitCode:           exitCode,
	}, nil
}

func runAddedPrompt(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, participant workorder.Participant, runDir string, label string, promptText string, quiet bool, humanOutput bool, validator func(any) (any, error)) (map[string]any, []prompt.TrimRecord, error) {
	providerDir := filepath.Join(runDir, "providers", participant.ID)
	if err := os.MkdirAll(providerDir, 0o700); err != nil {
		return nil, nil, err
	}
	trimResult := prompt.TrimContextToBudget(promptText, runner.MaxPromptBytes, "escalation:"+label+":"+participant.ID)
	commands.LogPromptTrim(f, trimResult)
	promptText = trimResult.Text
	trims := commands.TrimRecords(trimResult)
	if err := workorder.WriteTextAtomic(filepath.Join(providerDir, "prompt.txt"), promptText); err != nil {
		return nil, trims, err
	}
	cwd := mustGetwd()
	var caps *provider.ScopeCapabilities
	if wo.ScopePolicy.Enforcement != "advisory" {
		value := f.Capabilities().DetectScopeCapabilities(ctx, participant.Backend)
		caps = &value
	}
	finalMessagePath := ""
	outputLastMessage := false
	if caps != nil {
		outputLastMessage = commands.SupportsOutputLastMessage(participant, *caps)
	} else {
		outputLastMessage = commands.OutputLastMessageSupported(ctx, f, participant)
	}
	if outputLastMessage {
		finalMessagePath = filepath.Join(providerDir, "last-message.txt")
	}
	scopeExecution, err := scope.BuildExecution(ctx, f.Capabilities(), participant, wo.ScopePolicy, cwd, runDir, caps, finalMessagePath)
	if err != nil {
		result := scope.ScopeErrorResult(err, participant, wo.ScopePolicy, cwd)
		if writeErr := artifact.WriteProviderArtifacts(providerDir, result); writeErr != nil {
			return nil, trims, writeErr
		}
		return result, trims, nil
	}
	defer scope.Cleanup(scopeExecution.CleanupPaths)
	if humanOutput {
		f.Streams().Printf("[%s] running escalation %s...\n", participant.ID, label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             scopeExecution.Argv,
		Prompt:           promptText,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              scopeExecution.CWD,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        validator,
		OnTick:           commands.MakeTickPrinter(f, participant.ID, quiet),
		FinalMessagePath: finalMessagePath,
	}))
	result["scope_enforcement"] = scopeExecution.Metadata
	if err := artifact.WriteProviderArtifacts(providerDir, result); err != nil {
		return nil, trims, err
	}
	if humanOutput {
		f.Streams().Printf("[%s] %s %vs\n", participant.ID, result["status"], result["wall_seconds"])
	}
	return result, trims, nil
}

func runJudgePrompt(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, runDir string, label string, promptText string, quiet bool, humanOutput bool, validator func(any) (any, error)) (map[string]any, []prompt.TrimRecord, error) {
	judgeDir := filepath.Join(runDir, "judge")
	if err := os.MkdirAll(judgeDir, 0o700); err != nil {
		return nil, nil, err
	}
	trimResult := prompt.TrimContextToBudget(promptText, runner.MaxPromptBytes, "judge:"+label)
	commands.LogPromptTrim(f, trimResult)
	promptText = trimResult.Text
	trims := commands.TrimRecords(trimResult)
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, label+"-prompt.txt"), promptText); err != nil {
		return nil, trims, err
	}
	cwd := mustGetwd()
	finalMessagePath := ""
	outputLastMessage := commands.OutputLastMessageSupported(ctx, f, wo.Judge)
	if outputLastMessage {
		finalMessagePath = filepath.Join(judgeDir, label+"-last-message.txt")
	}
	argv, err := provider.BuildParticipantArgv(wo.Judge, cwd, nil, finalMessagePath, outputLastMessage)
	if err != nil {
		return nil, trims, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] running...\n", label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           promptText,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              cwd,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        validator,
		OnTick:           commands.MakeTickPrinter(f, "judge:"+label, quiet),
		FinalMessagePath: finalMessagePath,
	}))
	artifact.PreserveJudgeErrorKind(result)
	if err := writeEscalationJudgeArtifacts(judgeDir, label, result); err != nil {
		return nil, trims, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] %s %vs\n", label, result["status"], result["wall_seconds"])
	}
	return result, trims, nil
}

func writeEscalationJudgeArtifacts(judgeDir string, label string, result map[string]any) error {
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, label+"-stdout.txt"), jsonutil.StringValue(result["stdout"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, label+"-stderr.txt"), jsonutil.StringValue(result["stderr"])); err != nil {
		return err
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(judgeDir, label+"-status.json"), artifact.StatusWithoutPayload(result)); err != nil {
		return err
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(judgeDir, "status-"+label+".json"), artifact.StatusWithoutPayload(result)); err != nil {
		return err
	}
	if artifact.ProviderSucceeded(result) {
		if err := workorder.WriteJSONAtomic(filepath.Join(judgeDir, label+"-result.json"), result["final_json"]); err != nil {
			return err
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(judgeDir, "result-"+label+".json"), result["final_json"]); err != nil {
			return err
		}
	}
	return nil
}

func finalizeEscalationRun(ctx context.Context, f commands.Factory, opts finalizeOptions) (int, error) {
	exitCode := opts.ExitCode
	if err := workorder.WriteJSONAtomic(filepath.Join(opts.RunDir, "decision.json"), opts.Decision); err != nil {
		return exitCode, &apperror.RuntimeError{Err: err}
	}
	reportText := report.RenderEscalation(opts.Source.WorkOrder, opts.Decision, opts.AddedFinal, opts.DisputePacket, report.EscalationRenderOptions{
		RunID:        opts.RunID,
		OutDir:       opts.Out,
		RunDir:       opts.RunDir,
		SourceRunID:  opts.Source.ID,
		SourceRunDir: opts.Source.Dir,
	})
	if err := workorder.WriteTextAtomic(filepath.Join(opts.RunDir, "report.md"), reportText); err != nil {
		return exitCode, &apperror.RuntimeError{Err: err}
	}
	if err := writeEscalationMeta(ctx, f, opts); err != nil {
		return exitCode, &apperror.RuntimeError{Err: err}
	}
	if _, err := manifest.WriteRunManifest(opts.RunDir); err != nil {
		return exitCode, &apperror.RuntimeError{Err: err}
	}
	if opts.HumanOutput {
		f.Streams().Printf("manifest: %s\n", filepath.Join(opts.RunDir, "manifest.json"))
		f.Streams().Printf("report: %s\n", filepath.Join(opts.RunDir, "report.md"))
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(opts.RunID, opts.Out, ""))
		f.Streams().Printf("result: %s\n", jsonutil.StringValue(opts.Decision["decision_kind"]))
	}
	autoTriageStarted := false
	var triageExitCode any
	if !opts.NoTriage && exitCode == 0 && triagepkg.FacetID(opts.Source.WorkOrder.Raw) == triagepkg.CodeReviewFacetID {
		autoTriageStarted = true
		if opts.HumanOutput {
			f.Streams().Printf("auto-triage starting: code-review escalation output\n")
		}
		humanOutput := opts.HumanOutput
		triageCode, err := triagecmd.Run(ctx, f, &triagecmd.TriageOptions{
			RunID:        opts.RunID,
			Out:          opts.Out,
			Quiet:        opts.Quiet,
			RunDir:       opts.RunDir,
			DisplayRunID: opts.RunID,
			HumanOutput:  &humanOutput,
		})
		if err != nil {
			return exitCode, err
		}
		triageExitCode = triageCode
		if triageCode != 0 {
			exitCode = 1
		}
		opts.ExitCode = exitCode
		if err := writeEscalationMeta(ctx, f, opts); err != nil {
			return exitCode, &apperror.RuntimeError{Err: err}
		}
		if _, err := manifest.WriteRunManifest(opts.RunDir); err != nil {
			return exitCode, &apperror.RuntimeError{Err: err}
		}
	}
	if opts.JSON {
		value := summary.BuildEscalation(opts.RunDir, opts.RunID, opts.Out, opts.Source.ID, opts.Source.Dir, jsonutil.StringValue(opts.Decision["escalation_mode"]), opts.Added.ID, opts.Source.ProviderIDs, opts.Decision, opts.AllProviderResults, exitCode, false, nil, autoTriageStarted, triageExitCode)
		if err := summary.Print(f.Streams().Out, value); err != nil {
			return exitCode, &apperror.RuntimeError{Err: err}
		}
	}
	return exitCode, nil
}

func writeEscalationMeta(ctx context.Context, f commands.Factory, opts finalizeOptions) error {
	extra := map[string]any{
		"type":             "escalation",
		"source_type":      opts.Source.WorkOrder.Type,
		"source_run_id":    opts.Source.ID,
		"source_run_dir":   opts.Source.Dir,
		"escalation_mode":  jsonutil.StringValue(opts.Decision["escalation_mode"]),
		"added_provider":   opts.Added.ID,
		"source_providers": append([]string(nil), opts.Source.ProviderIDs...),
		"escalation": map[string]any{
			"mode":             jsonutil.StringValue(opts.Decision["escalation_mode"]),
			"added_provider":   opts.Added.ID,
			"source_run_id":    opts.Source.ID,
			"source_providers": append([]string(nil), opts.Source.ProviderIDs...),
		},
	}
	if err := artifact.WriteMetaWithExtra(ctx, opts.RunDir, opts.Source.WorkOrder, opts.RunID, opts.StartedAt, artifact.MetaOptions{
		WorkerResults:  opts.AllProviderResults,
		Decision:       opts.Decision,
		ExitCode:       opts.ExitCode,
		LookupProvider: f.LookupProvider,
	}, extra); err != nil {
		return err
	}
	meta, err := workorder.ReadRequiredObject(filepath.Join(opts.RunDir, "meta.json"))
	if err != nil {
		return err
	}
	resolved, _ := meta["resolved_models"].(map[string]any)
	if resolved == nil {
		resolved = map[string]any{}
		meta["resolved_models"] = resolved
	}
	providersMap, _ := resolved["providers"].(map[string]any)
	if providersMap == nil {
		providersMap = map[string]any{}
		resolved["providers"] = providersMap
	}
	addedEntry := map[string]any{
		"backend": opts.Added.Backend,
		"model":   opts.Added.Model,
		"scope":   opts.Added.Scope,
		"effort":  opts.Added.Effort,
	}
	if opts.AddedResult != nil {
		if scopeMetadata, ok := opts.AddedResult["scope_enforcement"]; ok {
			addedEntry["scope_enforcement"] = scopeMetadata
		}
	}
	providersMap[opts.Added.ID] = addedEntry
	versions, _ := meta["provider_cli_versions"].(map[string]any)
	if versions == nil {
		versions = map[string]any{}
		meta["provider_cli_versions"] = versions
	}
	versions[opts.Added.Backend] = artifact.ToolVersion(ctx, opts.Added.Backend, f.LookupProvider)
	return workorder.WriteJSONAtomic(filepath.Join(opts.RunDir, "meta.json"), meta)
}

func loadSourceRun(sourceDir string, requestedRunID string) (sourceRun, error) {
	if manifestObj, err := workorder.ReadOptionalJSON(filepath.Join(sourceDir, "manifest.json")); err == nil && manifestObj != nil {
		obj, ok := manifestObj.(map[string]any)
		if !ok {
			return sourceRun{}, &apperror.ValidationError{Message: filepath.Join(sourceDir, "manifest.json") + " must be a JSON object"}
		}
		if version := jsonutil.IntValue(obj["schema_version"]); version > manifest.SchemaVersion {
			return sourceRun{}, &apperror.ValidationError{Message: fmt.Sprintf("%s has future manifest.schema_version %d", sourceDir, version)}
		}
	} else if err != nil {
		return sourceRun{}, &apperror.ValidationError{Message: filepath.Join(sourceDir, "manifest.json") + " is invalid", Err: err}
	}
	workOrderPath := filepath.Join(sourceDir, "work-order.json")
	wo, err := workorder.Load(workOrderPath)
	if err != nil {
		return sourceRun{}, commands.WrapValidation(err)
	}
	if wo.Type == "build" {
		return sourceRun{}, &apperror.ValidationError{Message: "build source runs cannot be escalated"}
	}
	workOrderText, err := os.ReadFile(workOrderPath)
	if err != nil {
		return sourceRun{}, &apperror.ValidationError{Message: sourceDir + " has no readable work-order.json", Err: err}
	}
	decisionDoc, err := workorder.ReadRequiredObject(filepath.Join(sourceDir, "decision.json"))
	if err != nil {
		return sourceRun{}, &apperror.ValidationError{Message: sourceDir + " has no valid decision.json", Err: err}
	}
	meta, err := workorder.ReadRequiredObject(filepath.Join(sourceDir, "meta.json"))
	if err != nil {
		return sourceRun{}, &apperror.ValidationError{Message: sourceDir + " has no valid meta.json", Err: err}
	}
	reportData, err := os.ReadFile(filepath.Join(sourceDir, "report.md"))
	if err != nil {
		return sourceRun{}, &apperror.ValidationError{Message: sourceDir + " has no readable report.md", Err: err}
	}
	workerResults, providerFinals, err := loadSourceProviderResults(wo, sourceDir)
	if err != nil {
		return sourceRun{}, commands.WrapValidation(err)
	}
	runID := requestedRunID
	if runID == "" || runID == "latest" || ledger.IsPathLikeRunID(runID) {
		runID = filepath.Base(sourceDir)
	}
	ids := []string{}
	for _, participant := range wo.Providers {
		ids = append(ids, participant.ID)
	}
	reviewMD := readOptionalText(filepath.Join(sourceDir, "review-context.md"))
	reviewContext, _ := workorder.ReadOptionalJSON(filepath.Join(sourceDir, "review-context.json"))
	return sourceRun{
		ID:              runID,
		Dir:             sourceDir,
		WorkOrder:       wo,
		WorkOrderText:   string(workOrderText),
		Decision:        decisionDoc,
		Meta:            meta,
		ReportText:      string(reportData),
		WorkerResults:   workerResults,
		ProviderFinals:  providerFinals,
		ProviderIDs:     ids,
		JudgeResults:    readJudgeResults(sourceDir),
		ReviewContextMD: reviewMD,
		ReviewContext:   reviewContext,
		TriageArtifacts: readTriageArtifacts(sourceDir),
	}, nil
}

func loadSourceProviderResults(wo *workorder.WorkOrder, runDir string) (map[string]map[string]any, map[string]any, error) {
	results := map[string]map[string]any{}
	finals := map[string]any{}
	for _, participant := range wo.Providers {
		providerDir := filepath.Join(runDir, "providers", participant.ID)
		status, err := workorder.ReadRequiredObject(filepath.Join(providerDir, "status.json"))
		if err != nil {
			return nil, nil, fmt.Errorf("provider %s status.json is required and must be a JSON object: %w", participant.ID, err)
		}
		final, err := workorder.ReadRequiredObject(filepath.Join(providerDir, "final.json"))
		if err != nil {
			return nil, nil, fmt.Errorf("provider %s final.json is required and must be a JSON object: %w", participant.ID, err)
		}
		validated, err := workorder.ValidateWorkerResult(final, wo.Type)
		if err != nil {
			return nil, nil, fmt.Errorf("provider %s final.json is invalid: %w", participant.ID, err)
		}
		status["final_json"] = validated
		results[participant.ID] = status
		finals[participant.ID] = validated
	}
	return results, finals, nil
}

func validateMode(mode string) error {
	if mode == "" {
		return &apperror.ValidationError{Message: "--mode is required"}
	}
	if mode != ModeIndependent && mode != ModeWitness && mode != ModeDispute {
		return &apperror.ValidationError{Message: "--mode must be one of: independent, witness, dispute"}
	}
	return nil
}

func resolveAddedScope(wo *workorder.WorkOrder, mode string, raw string) (string, error) {
	if raw != "" {
		if mode != ModeIndependent {
			return "", &apperror.ValidationError{Message: "--scope is only supported for --mode independent"}
		}
		if !validScope(raw) {
			return "", &apperror.ValidationError{Message: "--scope must be one of: codebase, web, mixed"}
		}
		return raw, nil
	}
	common, allShare := commonProviderScope(wo)
	if allShare && common != "" {
		return common, nil
	}
	if triagepkg.FacetID(wo.Raw) == triagepkg.CodeReviewFacetID || mode != ModeIndependent {
		return "codebase", nil
	}
	if common == "" {
		return "", &apperror.ValidationError{Message: "--scope is required because source provider scope could not be inferred"}
	}
	return "", &apperror.ValidationError{Message: "--scope is required because source providers used different scopes"}
}

func validScope(value string) bool {
	return value == "codebase" || value == "web" || value == "mixed"
}

func commonProviderScope(wo *workorder.WorkOrder) (string, bool) {
	common := ""
	for _, participant := range wo.Providers {
		if common == "" {
			common = participant.Scope
			continue
		}
		if common != participant.Scope {
			return common, false
		}
	}
	return common, common != ""
}

func parseAddedProvider(raw string, scopeValue string, src sourceRun) (workorder.Participant, error) {
	backend, model, hasModel := strings.Cut(raw, ":")
	backend = strings.TrimSpace(backend)
	model = strings.TrimSpace(model)
	if backend == "" {
		return workorder.Participant{}, &apperror.ValidationError{Message: "--provider must name a backend"}
	}
	if !provider.ValidBackend(backend) {
		return workorder.Participant{}, &apperror.ValidationError{Message: fmt.Sprintf("unknown provider backend %q", backend)}
	}
	if hasModel && model == "" {
		return workorder.Participant{}, &apperror.ValidationError{Message: "--provider model must not be empty"}
	}
	if !hasModel {
		model = provider.DefaultModel(backend)
	}
	for _, id := range src.ProviderIDs {
		if id == backend {
			return workorder.Participant{}, &apperror.ValidationError{Message: fmt.Sprintf("source run already has provider id %q", backend)}
		}
	}
	workerEffort, _ := workorder.ModeEffortDefaults(src.WorkOrder.Type)
	return workorder.Participant{ID: backend, Backend: backend, Model: model, Effort: workerEffort, Scope: scopeValue}, nil
}

func estimateCalls(wo *workorder.WorkOrder, mode string, triageEnabled bool) estimate {
	out := estimate{ProviderCalls: 1}
	if mode == ModeIndependent {
		out.JudgePasses = 1
		if wo.Type == "gather" {
			out.Details = "run added provider independently, then merge source and added provider claims with one escalation union judge"
		} else {
			out.Details = "run added provider independently, then synthesize source decision and all provider outputs with one escalation judge"
		}
	}
	if triageEnabled && triagepkg.FacetID(wo.Raw) == triagepkg.CodeReviewFacetID {
		out.Triage = true
	}
	return out
}

func printDryRun(f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, calls estimate) {
	f.Streams().Printf("mode: %s\n", opts.Mode)
	f.Streams().Printf("added provider: %s/%s\n", added.Backend, added.Model)
	f.Streams().Printf("source mode: %s\n", src.WorkOrder.Type)
	f.Streams().Printf("source providers: %s\n", strings.Join(src.ProviderIDs, ", "))
	f.Streams().Printf("estimated calls: %d provider call, %d judge passes, triage=%s\n", calls.ProviderCalls, calls.JudgePasses, yesNo(calls.Triage))
	if calls.Details != "" {
		f.Streams().Printf("details: %s\n", calls.Details)
	}
}

func printRunHeader(f commands.Factory, src sourceRun, added workorder.Participant, opts *EscalateOptions, runID string, runDir string, calls estimate) {
	f.Streams().Printf("bakeoff escalate  run-id: %s\n", runID)
	f.Streams().Printf("  source run:     %s\n", src.ID)
	f.Streams().Printf("  source mode:    %s\n", src.WorkOrder.Type)
	f.Streams().Printf("  mode:           %s (%s)\n", opts.Mode, modeLabel(opts.Mode))
	f.Streams().Printf("  run dir:        %s/\n", runDir)
	f.Streams().Printf("  added provider: %s (%s, %s)\n", added.ID, added.Model, added.Scope)
	f.Streams().Printf("  source providers: %s\n", strings.Join(src.ProviderIDs, ", "))
	f.Streams().Printf("  estimated calls: %d provider, %d judge, triage=%s\n", calls.ProviderCalls, calls.JudgePasses, yesNo(calls.Triage))
}

func modeLabel(mode string) string {
	switch mode {
	case ModeIndependent:
		return "fresh third answer"
	case ModeWitness:
		return "audit the current result"
	case ModeDispute:
		return "focus only on contested points"
	default:
		return "unknown"
	}
}

func writeEscalationScaffold(src sourceRun, added workorder.Participant, opts *EscalateOptions, runDir string) error {
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), src.WorkOrderText); err != nil {
		return err
	}
	if err := copyReviewContextArtifacts(src.Dir, runDir); err != nil {
		return err
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "source-run.json"), sourceRunIdentity(src)); err != nil {
		return err
	}
	return workorder.WriteJSONAtomic(filepath.Join(runDir, "escalation", "mode.json"), map[string]any{
		"schema_version":   1,
		"mode":             opts.Mode,
		"mode_label":       modeLabel(opts.Mode),
		"source_run_id":    src.ID,
		"source_run_dir":   src.Dir,
		"source_mode":      src.WorkOrder.Type,
		"source_providers": append([]string(nil), src.ProviderIDs...),
		"added_provider": map[string]any{
			"id":      added.ID,
			"backend": added.Backend,
			"model":   added.Model,
			"effort":  added.Effort,
			"scope":   added.Scope,
		},
		"no_repo_layout": opts.NoRepoLayout,
	})
}

func sourceRunIdentity(src sourceRun) map[string]any {
	artifacts := map[string]any{}
	add := func(name string, path string) {
		if !fsutil.FileExists(path) {
			return
		}
		size, sha, err := workorder.FileFingerprint(path)
		if err != nil {
			return
		}
		artifacts[name] = map[string]any{"path": path, "sha256": sha, "size_bytes": size}
	}
	for _, name := range []string{"work-order.json", "decision.json", "report.md", "meta.json", "manifest.json"} {
		add(name, filepath.Join(src.Dir, name))
	}
	for _, id := range src.ProviderIDs {
		add("providers/"+id+"/status.json", filepath.Join(src.Dir, "providers", id, "status.json"))
		add("providers/"+id+"/final.json", filepath.Join(src.Dir, "providers", id, "final.json"))
	}
	return map[string]any{
		"schema_version":  1,
		"source_run_id":   src.ID,
		"source_run_dir":  src.Dir,
		"source_mode":     src.WorkOrder.Type,
		"source_decision": decision.SourceDecisionSummary(src.Decision),
		"source_triage":   sourceTriageSnapshot(src.Dir),
		"artifacts":       artifacts,
	}
}

func sourceTriageSnapshot(runDir string) map[string]any {
	triageDir := filepath.Join(runDir, "triage")
	state, staleInputs := triagepkg.DisplayStateDetail(runDir)
	present := false
	out := map[string]any{
		"state":        state,
		"stale_inputs": staleInputs,
	}
	artifacts := map[string]any{}
	add := func(key string, relative string) {
		path := filepath.Join(runDir, relative)
		if !fsutil.FileExists(path) {
			return
		}
		present = true
		size, sha, err := workorder.FileFingerprint(path)
		if err != nil {
			return
		}
		artifacts[relative] = map[string]any{"path": path, "sha256": sha, "size_bytes": size}
		out[key+"_path"] = path
		out[key+"_sha256"] = sha
	}
	add("status", filepath.Join("triage", "status.json"))
	add("final", filepath.Join("triage", "final.json"))
	add("triage_md", filepath.Join("triage", "triage.md"))
	if !present {
		if info, err := os.Stat(triageDir); err != nil || !info.IsDir() {
			out["state"] = "absent"
		}
	}
	if len(artifacts) > 0 {
		out["artifacts"] = artifacts
	}
	if final, err := workorder.ReadRequiredObject(filepath.Join(triageDir, "final.json")); err == nil {
		items := jsonutil.ListValue(final["items"])
		out["item_count"] = len(items)
		out["item_counts_by_classification"] = triageClassificationCounts(items)
	}
	if filter, ok := triagepkg.SourceFindingFilterSummary(runDir); ok {
		out["source_finding_filter"] = filter
		if filter["included"] == 0 && state == "yes" {
			out["zero_selected"] = true
		}
	}
	return out
}

func triageClassificationCounts(items []any) map[string]int {
	counts := map[string]int{}
	for _, name := range triagepkg.Classifications {
		counts[name] = 0
	}
	for _, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		classification := jsonutil.StringValue(obj["classification"])
		if _, ok := counts[classification]; ok {
			counts[classification]++
		}
	}
	return counts
}

func copyReviewContextArtifacts(sourceRunDir string, runDir string) error {
	names := []string{"source-work-order.json", "review-context.md", "review-context.json"}
	present := []string{}
	missing := []string{}
	for _, name := range names {
		path := filepath.Join(sourceRunDir, name)
		if fsutil.FileExists(path) {
			present = append(present, name)
		} else {
			missing = append(missing, name)
		}
	}
	if len(present) == 0 {
		return nil
	}
	if len(missing) > 0 {
		return fmt.Errorf("source run has partial review-context artifact set; missing: %s", strings.Join(missing, ", "))
	}
	for _, name := range names {
		data, err := os.ReadFile(filepath.Join(sourceRunDir, name))
		if err != nil {
			return err
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, name), string(data)); err != nil {
			return err
		}
	}
	return nil
}

func sourcePayload(src sourceRun) map[string]any {
	payload := map[string]any{
		"source_run": map[string]any{
			"run_id":           src.ID,
			"run_dir":          src.Dir,
			"mode":             src.WorkOrder.Type,
			"source_providers": src.ProviderIDs,
		},
		"work_order_json":        src.WorkOrderText,
		"source_report_md":       src.ReportText,
		"source_decision_json":   src.Decision,
		"source_meta_json":       src.Meta,
		"source_provider_finals": src.ProviderFinals,
		"source_judge_results":   src.JudgeResults,
	}
	if src.ReviewContextMD != "" {
		payload["review_context_md"] = src.ReviewContextMD
	}
	if src.ReviewContext != nil {
		payload["review_context_json"] = src.ReviewContext
	}
	if len(src.TriageArtifacts) > 0 {
		payload["triage_artifacts"] = src.TriageArtifacts
	}
	return payload
}

func escalationBaseInput(src sourceRun, added workorder.Participant, mode string, statuses map[string]any) decision.EscalationBaseInput {
	return decision.EscalationBaseInput{
		SourceMode:       src.WorkOrder.Type,
		EscalationMode:   mode,
		SourceRunID:      src.ID,
		AddedProvider:    added.ID,
		SourceProviders:  src.ProviderIDs,
		SourceDecision:   src.Decision,
		ProviderStatuses: statuses,
	}
}

func allProviderStatuses(src sourceRun, addedID string, addedResult map[string]any) map[string]any {
	statuses := map[string]any{}
	if existing, ok := src.Decision["provider_statuses"].(map[string]any); ok {
		for key, value := range existing {
			statuses[key] = value
		}
	} else {
		for id, result := range src.WorkerResults {
			statuses[id] = artifact.StatusWithoutPayload(result)
		}
	}
	if addedResult != nil {
		status := artifact.StatusWithoutPayload(addedResult)
		status["stderr_path"] = "providers/" + addedID + "/stderr.txt"
		statuses[addedID] = status
	}
	return statuses
}

func mergeProviderResults(source map[string]map[string]any, addedID string, addedResult map[string]any) map[string]map[string]any {
	out := map[string]map[string]any{}
	for key, value := range source {
		out[key] = value
	}
	if addedResult != nil {
		out[addedID] = addedResult
	}
	return out
}

func buildDisputePacket(src sourceRun) map[string]any {
	points := []any{}
	addPoint := func(kind string, title string, question string, refs []any, claims []any, judgeContext any, triageContext any, notes []any) {
		id := fmt.Sprintf("D-%03d", len(points)+1)
		points = append(points, map[string]any{
			"id":              id,
			"kind":            kind,
			"title":           title,
			"question":        question,
			"source_refs":     refs,
			"provider_claims": claims,
			"judge_context":   judgeContext,
			"triage_context":  triageContext,
			"notes":           notes,
		})
	}
	kind := jsonutil.StringValue(src.Decision["decision_kind"])
	if (src.WorkOrder.Type == "compare" || src.WorkOrder.Type == "analyze") && (kind == "tie" || hasSwapDisagreement(src.Decision)) {
		addPoint(
			"judge_disagreement",
			"Source judge passes did not produce a stable decision",
			"Does the added evidence resolve the source judge disagreement, and if so why?",
			[]any{jsonRef("decision.json", "/judge_passes")},
			nil,
			src.Decision["judge_passes"],
			nil,
			jsonutil.ListValue(src.Decision["caveats"]),
		)
	}
	for providerID, finalRaw := range src.ProviderFinals {
		final, _ := finalRaw.(map[string]any)
		for _, conflict := range jsonutil.ListValue(final["conflicts"]) {
			addPoint(
				"provider_conflict",
				"Provider conflict from "+providerID,
				"Is this conflict material to the source result?",
				[]any{jsonRef("providers/"+providerID+"/final.json", "/conflicts")},
				providerClaims(providerID, nil, []any{conflict}),
				nil,
				nil,
				nil,
			)
		}
		for _, unknown := range jsonutil.ListValue(final["unknowns"]) {
			addPoint(
				"unknown",
				"Provider unknown from "+providerID,
				"Can this unknown be resolved from the available evidence?",
				[]any{jsonRef("providers/"+providerID+"/final.json", "/unknowns")},
				providerClaims(providerID, nil, []any{unknown}),
				nil,
				nil,
				nil,
			)
		}
	}
	for _, item := range jsonutil.ListValue(src.Decision["kept_from_nonwinner"]) {
		addPoint(
			"kept_from_nonwinner",
			"Material preserved from nonwinner",
			"Does this preserved material challenge or clarify the source decision?",
			[]any{jsonRef("decision.json", "/kept_from_nonwinner")},
			providerClaims(jsonutil.StringValue(mapValue(item, "source_provider")), nil, []any{item}),
			nil,
			nil,
			nil,
		)
	}
	for _, item := range triageGapItems(src.TriageArtifacts) {
		addPoint(
			"triage_gap",
			"Review triage gap",
			"Does this triage concern change how the review result should be treated?",
			[]any{jsonRef("triage/final.json", "/items")},
			nil,
			nil,
			item,
			nil,
		)
	}
	if len(points) > 12 {
		points = points[:12]
	}
	return map[string]any{
		"schema_version": 1,
		"source_run_id":  src.ID,
		"source_mode":    src.WorkOrder.Type,
		"source_decision": map[string]any{
			"decision_kind":    src.Decision["decision_kind"],
			"canonical_winner": src.Decision["canonical_winner"],
		},
		"facet":               src.WorkOrder.Raw["facet"],
		"review_triage_state": triageState(src.TriageArtifacts),
		"points":              points,
		"limits":              map[string]any{"max_points": 12, "max_bytes": 60000},
	}
}

func hasSwapDisagreement(decisionDoc map[string]any) bool {
	for _, item := range jsonutil.ListValue(decisionDoc["caveats"]) {
		if strings.Contains(strings.ToLower(fmt.Sprint(item)), "swap disagreement") || strings.Contains(strings.ToLower(fmt.Sprint(item)), "position swap") {
			return true
		}
	}
	return false
}

func jsonRef(artifactName string, pointer string) map[string]any {
	return map[string]any{"artifact": artifactName, "json_pointer": pointer}
}

func providerClaims(providerID string, claims []any, fallback []any) []any {
	if providerID == "" {
		providerID = "unknown"
	}
	items := claims
	if len(items) == 0 {
		items = fallback
	}
	out := []any{}
	for i, item := range items {
		obj, _ := item.(map[string]any)
		claim := fmt.Sprint(item)
		evidence := []any{}
		if obj != nil {
			claim = firstStringValue(obj["claim"], obj["description"], obj["loser_note"], fmt.Sprint(item))
			evidence = jsonutil.ListValue(obj["evidence"])
		}
		out = append(out, map[string]any{
			"provider_id": providerID,
			"claim_id":    fmt.Sprintf("%s-%03d", providerID, i+1),
			"claim":       claim,
			"evidence":    evidence,
		})
	}
	return out
}

func triageGapItems(artifacts map[string]any) []any {
	final, _ := artifacts["final"].(map[string]any)
	if final == nil {
		return nil
	}
	out := []any{}
	for _, item := range jsonutil.ListValue(final["items"]) {
		obj, _ := item.(map[string]any)
		classification := jsonutil.StringValue(obj["classification"])
		if classification == "needs_repro" || classification == "evidence_gap" {
			out = append(out, obj)
		}
	}
	return out
}

func triageState(artifacts map[string]any) any {
	if len(artifacts) == 0 {
		return nil
	}
	if state := artifacts["state"]; state != nil {
		return state
	}
	return nil
}

func readJudgeResults(runDir string) map[string]any {
	out := map[string]any{}
	entries, err := os.ReadDir(filepath.Join(runDir, "judge"))
	if err != nil {
		return out
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") || !strings.HasPrefix(entry.Name(), "result") {
			continue
		}
		obj, err := workorder.ReadRequiredObject(filepath.Join(runDir, "judge", entry.Name()))
		if err == nil {
			out[strings.TrimSuffix(entry.Name(), ".json")] = obj
		}
	}
	return out
}

func readTriageArtifacts(runDir string) map[string]any {
	triageDir := filepath.Join(runDir, "triage")
	state, staleInputs := triagepkg.StateDetail(runDir)
	out := map[string]any{}
	if state != "" && state != "no" {
		out["state"] = state
	}
	if len(staleInputs) > 0 {
		out["stale_inputs"] = staleInputs
	}
	for _, name := range []string{"status", "final", "source_finding_filter", "citation_checks"} {
		obj, err := workorder.ReadRequiredObject(filepath.Join(triageDir, name+".json"))
		if err == nil {
			out[name] = obj
		}
	}
	return out
}

func estimateMap(calls estimate) map[string]any {
	return map[string]any{
		"provider_calls": calls.ProviderCalls,
		"judge_passes":   calls.JudgePasses,
		"triage":         calls.Triage,
		"details":        calls.Details,
	}
}

func readOptionalText(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(data)
}

func mapValue(value any, key string) any {
	obj, _ := value.(map[string]any)
	if obj == nil {
		return nil
	}
	return obj[key]
}

func firstStringValue(values ...any) string {
	for _, value := range values {
		if text := jsonutil.StringValue(value); text != "" {
			return text
		}
	}
	return ""
}

func yesNo(value bool) string {
	if value {
		return "yes"
	}
	return "no"
}

func mustGetwd() string {
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	return cwd
}
