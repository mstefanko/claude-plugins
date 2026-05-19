package researchcmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"golang.org/x/sync/errgroup"

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
	"github.com/mstefanko/claude-plugins/bakeoff/internal/report"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/reviewcontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runresult"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/scope"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	triagepkg "github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func RunResearch(ctx context.Context, f commands.Factory, opts *ResearchOptions) error {
	humanOutput := !opts.JSON
	effectiveQuiet := opts.Quiet || opts.JSON
	wo, err := workorder.Load(opts.WorkOrder)
	if err != nil {
		return commands.WrapValidation(err)
	}
	if wo.Type == "build" {
		return &apperror.ValidationError{Message: `type "build" work orders must be run with bakeoff build`}
	}
	sourceText, err := os.ReadFile(opts.WorkOrder)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	runID := opts.RunID
	if runID == "" {
		runID = ledger.MakeRunID(f.Now(), fsutil.RandomSuffix())
	}
	if err := ledger.ValidateRunID(runID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	runDir := ledger.RunDir(opts.Out, runID)
	replaceRunDir := false
	if _, err := os.Stat(runDir); err == nil {
		if !opts.Force {
			return &apperror.ValidationError{Message: fmt.Sprintf("%s already exists; use --force to replace", runDir)}
		}
		if err := ledger.EnsureChildPath(opts.Out, runDir); err != nil {
			return &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		replaceRunDir = true
	}
	startedAt := artifact.UTCNow()
	var reviewContext *reviewcontext.Context
	if reviewOptions(opts).Enabled() {
		cwd, _ := os.Getwd()
		reviewContext, err = reviewcontext.Build(ctx, reviewOptions(opts), cwd, startedAt)
		if err != nil {
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return err
			}
			return commands.WrapValidation(err)
		}
		if triagepkg.FacetID(wo.Raw) != triagepkg.CodeReviewFacetID {
			f.Streams().Errorf("note: generated review context was requested for a non-code-review facet\n")
		}
		wo, err = reviewcontext.Apply(wo, reviewContext)
		if err != nil {
			return commands.WrapValidation(err)
		}
	}
	if replaceRunDir {
		if err := os.RemoveAll(runDir); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	if err := os.MkdirAll(runDir, 0o700); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := ledger.UpdateLatest(opts.Out, runID); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if reviewContext != nil {
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, "source-work-order.json"), string(sourceText)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), wo.Raw); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, "review-context.md"), reviewcontext.RenderMarkdown(reviewContext)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "review-context.json"), reviewcontext.Metadata(reviewContext)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	} else {
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, "work-order.json"), string(sourceText)); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		if opts.ReplaySourceRunDir != "" {
			if err := copyReplayContextArtifacts(opts.ReplaySourceRunDir, runDir); err != nil {
				return &apperror.RuntimeError{Err: err}
			}
		}
	}
	if humanOutput {
		printRunHeader(f, wo, runDir, runID)
	}
	if reviewContext != nil && humanOutput {
		f.Streams().Printf("%s\n", reviewcontext.FormatSummary(reviewContext))
	} else if opts.ReplaySourceRunDir != "" && fsutil.FileExists(filepath.Join(runDir, "review-context.md")) && humanOutput {
		f.Streams().Printf("review context: replayed from %s\n", opts.ReplaySourceRunDir)
	}

	workerResults, err := runWorkers(ctx, f, wo, runDir, effectiveQuiet, humanOutput)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return err
		}
		return &apperror.RuntimeError{Err: err}
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}

	okResults := map[string]map[string]any{}
	for providerID, result := range workerResults {
		if artifact.ProviderSucceeded(result) {
			okResults[providerID] = result
		}
	}
	judgeResults := map[string]map[string]any{}
	exitCode := 0
	var decisionDoc map[string]any
	if len(okResults) == 0 {
		decisionDoc = decision.BothFailed(wo, workerResults)
		exitCode = 1
	} else if len(okResults) == 1 {
		survivor := ""
		for id := range okResults {
			survivor = id
		}
		decisionDoc = decision.SingleProviderOnly(wo, workerResults, survivor)
	} else {
		decisionDoc, judgeResults, exitCode, err = runJudgePhase(ctx, f, wo, workerResults, runDir, effectiveQuiet, humanOutput)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			return &apperror.RuntimeError{Err: err}
		}
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return finalizeResearchRun(ctx, f, researchFinalizeOptions{
		WorkOrder:      wo,
		Out:            opts.Out,
		RunID:          runID,
		RunDir:         runDir,
		StartedAt:      startedAt,
		WorkerResults:  workerResults,
		DecisionDoc:    decisionDoc,
		JudgeResults:   judgeResults,
		ExitCode:       exitCode,
		NoTriage:       opts.NoTriage,
		JSON:           opts.JSON,
		Quiet:          effectiveQuiet,
		HumanOutput:    humanOutput,
		LookupProvider: f.LookupProvider,
	})
}

func RunResearchJudgeOnly(ctx context.Context, f commands.Factory, opts *ResearchJudgeOnlyOptions) error {
	workOrderPath := filepath.Join(opts.SourceRunDir, "work-order.json")
	wo, err := workorder.Load(workOrderPath)
	if err != nil {
		return commands.WrapValidation(err)
	}
	if wo.Type == "build" {
		return &apperror.ValidationError{Message: "--judge-only is currently supported only for research runs"}
	}
	if err := validateFailedJudgeAttempt(wo, opts.SourceRunDir); err != nil {
		return err
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
	if err := copyRequiredRunFile(opts.SourceRunDir, runDir, "work-order.json"); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := copyReplayContextArtifacts(opts.SourceRunDir, runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := copyProviderArtifactDirs(wo, opts.SourceRunDir, runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	workerResults, err := loadResearchWorkerResultsFromArtifacts(wo, runDir)
	if err != nil {
		return commands.WrapValidation(err)
	}
	humanOutput := true
	effectiveQuiet := opts.Quiet
	if humanOutput {
		printRunHeader(f, wo, runDir, runID)
		f.Streams().Printf("note: judge-only rerun reuses provider artifacts from %s\n", opts.SourceRunID)
		if fsutil.FileExists(filepath.Join(runDir, "review-context.md")) {
			f.Streams().Printf("review context: replayed from %s\n", opts.SourceRunDir)
		}
	}
	decisionDoc, judgeResults, exitCode, err := runJudgePhase(ctx, f, wo, workerResults, runDir, effectiveQuiet, humanOutput)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return err
		}
		return &apperror.RuntimeError{Err: err}
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	sourceRunID := opts.SourceRunID
	if sourceRunID == "" || sourceRunID == "latest" {
		sourceRunID = filepath.Base(opts.SourceRunDir)
	}
	return finalizeResearchRun(ctx, f, researchFinalizeOptions{
		WorkOrder:      wo,
		Out:            opts.Out,
		RunID:          runID,
		RunDir:         runDir,
		StartedAt:      startedAt,
		WorkerResults:  workerResults,
		DecisionDoc:    decisionDoc,
		JudgeResults:   judgeResults,
		ExitCode:       exitCode,
		NoTriage:       opts.NoTriage,
		Quiet:          effectiveQuiet,
		HumanOutput:    humanOutput,
		LookupProvider: f.LookupProvider,
		MetaExtra: map[string]any{
			"source_run_id":  sourceRunID,
			"source_run_dir": opts.SourceRunDir,
			"rerun_mode":     "judge_only",
		},
	})
}

type researchFinalizeOptions struct {
	WorkOrder      *workorder.WorkOrder
	Out            string
	RunID          string
	RunDir         string
	StartedAt      string
	WorkerResults  map[string]map[string]any
	DecisionDoc    map[string]any
	JudgeResults   map[string]map[string]any
	ExitCode       int
	NoTriage       bool
	JSON           bool
	Quiet          bool
	HumanOutput    bool
	LookupProvider provider.LookupFunc
	MetaExtra      map[string]any
}

func finalizeResearchRun(ctx context.Context, f commands.Factory, opts researchFinalizeOptions) error {
	exitCode := opts.ExitCode
	if err := workorder.WriteJSONAtomic(filepath.Join(opts.RunDir, "decision.json"), opts.DecisionDoc); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	reportText := report.Render(opts.WorkOrder, opts.DecisionDoc, opts.WorkerResults, opts.JudgeResults, report.RenderOptions{RunID: opts.RunID, OutDir: opts.Out, RunDir: opts.RunDir})
	if err := workorder.WriteTextAtomic(filepath.Join(opts.RunDir, "report.md"), reportText); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := artifact.WriteMetaWithExtra(ctx, opts.RunDir, opts.WorkOrder, opts.RunID, opts.StartedAt, artifact.MetaOptions{
		WorkerResults:  opts.WorkerResults,
		Decision:       opts.DecisionDoc,
		ExitCode:       exitCode,
		LookupProvider: opts.LookupProvider,
	}, opts.MetaExtra); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if _, err := manifest.WriteRunManifest(opts.RunDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if opts.HumanOutput {
		if fsutil.FileExists(filepath.Join(opts.RunDir, "review-context.md")) {
			f.Streams().Printf("context-md: %s\n", filepath.Join(opts.RunDir, "review-context.md"))
		}
		f.Streams().Printf("manifest: %s\n", filepath.Join(opts.RunDir, "manifest.json"))
		f.Streams().Printf("report: %s\n", filepath.Join(opts.RunDir, "report.md"))
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(opts.RunID, opts.Out, ""))
		f.Streams().Printf("result: %s\n", researchResultLine(opts.WorkOrder, opts.DecisionDoc, reportText))
	}
	autoTriageReason := ""
	autoTriageStarted := false
	var triageExitCode any
	if !opts.NoTriage && exitCode == 0 {
		autoTriageReason = triagepkg.ShouldAutoTriage(opts.WorkOrder.Raw, opts.DecisionDoc)
		if autoTriageReason != "" && opts.HumanOutput {
			f.Streams().Printf("auto-triage starting: %s\n", autoTriageReason)
		}
		if autoTriageReason != "" {
			autoTriageStarted = true
			triageOpts := &triagecmd.TriageOptions{
				RunID:        opts.RunID,
				Out:          opts.Out,
				Quiet:        opts.Quiet,
				RunDir:       opts.RunDir,
				DisplayRunID: opts.RunID,
				HumanOutput:  &opts.HumanOutput,
			}
			triageCode, err := triagecmd.Run(ctx, f, triageOpts)
			if err != nil {
				return err
			}
			triageExitCode = triageCode
			if triageCode != 0 {
				exitCode = 1
			}
		}
	}
	if !opts.NoTriage && !autoTriageStarted && opts.HumanOutput {
		if recommendation := triagepkg.ShouldRecommendTriage(opts.WorkOrder.Raw, opts.DecisionDoc, reportText); recommendation != "" {
			f.Streams().Printf("recommended: %s  (%s)\n", ledger.BakeoffTriageCommand(opts.RunID, opts.Out, false), recommendation)
		}
	}
	if autoTriageStarted {
		if err := artifact.WriteMetaWithExtra(ctx, opts.RunDir, opts.WorkOrder, opts.RunID, opts.StartedAt, artifact.MetaOptions{
			WorkerResults:  opts.WorkerResults,
			Decision:       opts.DecisionDoc,
			ExitCode:       exitCode,
			LookupProvider: opts.LookupProvider,
		}, opts.MetaExtra); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		if _, err := manifest.WriteRunManifest(opts.RunDir); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	if opts.JSON {
		value := summary.BuildResearch(opts.RunDir, opts.RunID, opts.Out, opts.DecisionDoc, opts.WorkerResults, exitCode, autoTriageStarted, triageExitCode)
		if err := summary.Print(f.Streams().Out, value); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	if exitCode == 3 {
		return &apperror.SilentError{Err: &apperror.JudgeDisagreementError{Message: "judge disagreement"}}
	}
	if exitCode == 4 {
		return &apperror.SilentError{Err: &apperror.DecisionIncompleteError{Message: "decision incomplete"}}
	}
	if exitCode != 0 {
		return &apperror.SilentError{Err: fmt.Errorf("research failed")}
	}
	return nil
}

func runWorkers(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, runDir string, quiet bool, humanOutput bool) (map[string]map[string]any, error) {
	capabilities := map[string]provider.ScopeCapabilities{}
	if wo.ScopePolicy.Enforcement != "advisory" {
		backendSet := map[string]bool{}
		for _, participant := range wo.Providers {
			backendSet[participant.Backend] = true
		}
		for backend := range backendSet {
			capabilities[backend] = f.Capabilities().DetectScopeCapabilities(ctx, backend)
		}
	}
	cwd, _ := os.Getwd()
	results := make(map[string]map[string]any, len(wo.Providers))
	group, groupCtx := errgroup.WithContext(ctx)
	type pair struct {
		id     string
		result map[string]any
	}
	pairs := make([]pair, len(wo.Providers))
	if humanOutput {
		for _, participant := range wo.Providers {
			f.Streams().Printf("[%s] launching...\n", participant.ID)
		}
	}
	for index, providerParticipant := range wo.Providers {
		index := index
		participant := providerParticipant
		group.Go(func() error {
			result, err := runOneWorker(groupCtx, f, wo, participant, runDir, cwd, capabilities, quiet)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return err
				}
				result = runresult.InternalError(err)
				providerDir := filepath.Join(runDir, "providers", participant.ID)
				if mkdirErr := os.MkdirAll(providerDir, 0o700); mkdirErr != nil {
					return mkdirErr
				}
				if writeErr := artifact.WriteProviderArtifacts(providerDir, result); writeErr != nil {
					return writeErr
				}
			}
			pairs[index] = pair{id: participant.ID, result: result}
			return nil
		})
	}
	if err := group.Wait(); err != nil {
		return nil, err
	}
	for _, item := range pairs {
		results[item.id] = item.result
	}
	if humanOutput {
		for _, item := range pairs {
			printWorkerResult(f, item.id, item.result)
		}
	}
	return results, nil
}

func runOneWorker(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, participant workorder.Participant, runDir string, cwd string, capabilities map[string]provider.ScopeCapabilities, quiet bool) (map[string]any, error) {
	providerDir := filepath.Join(runDir, "providers", participant.ID)
	if err := os.MkdirAll(providerDir, 0o700); err != nil {
		return nil, err
	}
	workerPrompt, err := prompt.BuildWorkerPrompt(wo, participant)
	if err != nil {
		return nil, err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(providerDir, "prompt.txt"), workerPrompt); err != nil {
		return nil, err
	}
	finalMessagePath := ""
	if participant.Backend == "codex" {
		finalMessagePath = filepath.Join(providerDir, "last-message.txt")
	}
	var caps *provider.ScopeCapabilities
	if value, ok := capabilities[participant.Backend]; ok {
		caps = &value
	}
	scopeExecution, err := scope.BuildExecution(ctx, f.Capabilities(), participant, wo.ScopePolicy, cwd, runDir, caps, finalMessagePath)
	if err != nil {
		result := scope.ScopeErrorResult(err, participant, wo.ScopePolicy, cwd)
		if writeErr := artifact.WriteProviderArtifacts(providerDir, result); writeErr != nil {
			return nil, writeErr
		}
		return result, nil
	}
	defer scope.Cleanup(scopeExecution.CleanupPaths)
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             scopeExecution.Argv,
		Prompt:           workerPrompt,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              scopeExecution.CWD,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        func(data any) (any, error) { return workorder.ValidateWorkerResult(data, wo.Type) },
		OnTick:           commands.MakeTickPrinter(f, participant.ID, quiet),
		FinalMessagePath: finalMessagePath,
	}))
	result["scope_enforcement"] = scopeExecution.Metadata
	if err := artifact.WriteProviderArtifacts(providerDir, result); err != nil {
		return nil, err
	}
	return result, nil
}

func printWorkerResult(f commands.Factory, providerID string, result map[string]any) {
	f.Streams().Printf("[%s] %s %vs %v bytes\n", providerID, result["status"], result["wall_seconds"], result["output_bytes"])
}

func runJudgePhase(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, workerResults map[string]map[string]any, runDir string, quiet bool, humanOutput bool) (map[string]any, map[string]map[string]any, int, error) {
	mode := wo.Type
	providerIDs := []string{wo.Providers[0].ID, wo.Providers[1].ID}
	base := decision.Base(wo, workerResults)
	if mode == "gather" {
		order := map[string]string{"A": providerIDs[0], "B": providerIDs[1]}
		judgeResult, err := runSingleJudge(ctx, f, wo, workerResults, order, runDir, "gather", quiet, humanOutput)
		if err != nil {
			return nil, nil, 0, err
		}
		decisionDoc, judgeResults, exitCode := decision.GatherStructuredUnion(wo, workerResults, judgeResult)
		return decisionDoc, judgeResults, exitCode, nil
	}
	pass1Order := map[string]string{"A": providerIDs[0], "B": providerIDs[1]}
	pass2Order := map[string]string{"A": providerIDs[1], "B": providerIDs[0]}
	pass1, err := runSingleJudge(ctx, f, wo, workerResults, pass1Order, runDir, "pass1", quiet, humanOutput)
	if err != nil {
		return nil, nil, 0, err
	}
	pass2, err := runSingleJudge(ctx, f, wo, workerResults, pass2Order, runDir, "pass2", quiet, humanOutput)
	if err != nil {
		return nil, nil, 0, err
	}
	judgeResults := map[string]map[string]any{"pass1": jsonutil.FinalJSONMap(pass1), "pass2": jsonutil.FinalJSONMap(pass2)}
	if !artifact.ProviderSucceeded(pass1) || !artifact.ProviderSucceeded(pass2) {
		decisionDoc := cloneMap(base)
		decisionDoc["decision_kind"] = "judge_failed"
		decisionDoc["judge_ran"] = true
		decisionDoc["judge_attempted"] = true
		decisionDoc["judge_completed"] = false
		decisionDoc["order_maps"] = map[string]any{"pass1": pass1Order, "pass2": pass2Order}
		decisionDoc["canonical_winner"] = nil
		decisionDoc["judge_rationale"] = []string{}
		if kind := firstJudgeErrorKind(pass1, pass2); kind != "" {
			decisionDoc["judge_error_kind"] = kind
		}
		decisionDoc["caveats"] = []string{fmt.Sprintf("judge failed: pass1=%s, pass2=%s", pass1["status"], pass2["status"])}
		return decisionDoc, judgeResults, 4, nil
	}
	if mode == "compare" {
		decisionDoc := decision.ResolveCompare(base, judgeResults, pass1Order, pass2Order)
		exitCode := 0
		if decisionDoc["decision_kind"] == "tie" {
			exitCode = 3
		}
		return decisionDoc, judgeResults, exitCode, nil
	}
	return decision.ResolveAnalyze(base, workerResults, judgeResults, pass1Order, pass2Order, providerIDs), judgeResults, 0, nil
}

func runSingleJudge(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, workerResults map[string]map[string]any, orderMap map[string]string, runDir string, label string, quiet bool, humanOutput bool) (map[string]any, error) {
	workerA := jsonutil.FinalJSONMap(workerResults[orderMap["A"]])
	workerB := jsonutil.FinalJSONMap(workerResults[orderMap["B"]])
	judgePrompt, err := prompt.BuildJudgePrompt(wo, workerA, workerB, "")
	if err != nil {
		return nil, err
	}
	judgeDir := filepath.Join(runDir, "judge")
	if err := os.MkdirAll(judgeDir, 0o700); err != nil {
		return nil, err
	}
	promptPath := filepath.Join(judgeDir, "prompt.txt")
	if label != "gather" {
		promptPath = filepath.Join(judgeDir, "prompt-"+label+".txt")
	}
	if err := workorder.WriteTextAtomic(promptPath, judgePrompt); err != nil {
		return nil, err
	}
	lastMessage := ""
	if wo.Judge.Backend == "codex" {
		name := "last-message.txt"
		if label != "gather" {
			name = "last-message-" + label + ".txt"
		}
		lastMessage = filepath.Join(judgeDir, name)
	}
	cwd, _ := os.Getwd()
	argv, err := provider.BuildParticipantArgv(wo.Judge, cwd, nil, lastMessage, commands.CodexOutputLastMessageSupported(ctx, f, wo.Judge))
	if err != nil {
		return nil, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] running...\n", label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           judgePrompt,
		Budgets:          commands.RunnerBudgets(wo.Budgets),
		CWD:              cwd,
		Env:              runnerenv.SafeEnv(os.Environ()),
		Validator:        judgeValidator(wo.Type),
		OnTick:           commands.MakeTickPrinter(f, "judge:"+label, quiet),
		FinalMessagePath: lastMessage,
	}))
	if !artifact.ProviderSucceeded(result) {
		status := jsonutil.StringValue(result["status"])
		exitCode, _ := result["exit_code"].(*int)
		result["judge_error_kind"] = runner.ClassifyJudgeError(status, exitCode, jsonutil.StringValue(result["stdout"]), jsonutil.StringValue(result["stderr"]))
	}
	if err := artifact.WriteJudgeArtifacts(judgeDir, label, result); err != nil {
		return nil, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] %s %vs\n", label, result["status"], result["wall_seconds"])
	}
	return result, nil
}

func firstJudgeErrorKind(results ...map[string]any) string {
	for _, result := range results {
		if artifact.ProviderSucceeded(result) {
			continue
		}
		if kind := jsonutil.StringValue(result["judge_error_kind"]); kind != "" {
			return kind
		}
	}
	return ""
}

func judgeValidator(mode string) func(any) (any, error) {
	switch mode {
	case "gather":
		return workorder.ValidateGatherJudgeResult
	case "compare":
		return workorder.ValidateCompareJudgeResult
	case "build":
		return workorder.ValidateBuildJudgeResult
	default:
		return workorder.ValidateAnalyzeJudgeResult
	}
}

func printRunHeader(f commands.Factory, wo *workorder.WorkOrder, runDir string, runID string) {
	providers := []string{}
	for _, participant := range wo.Providers {
		providers = append(providers, fmt.Sprintf("%s (%s, %s)", participant.ID, participant.Model, participant.Scope))
	}
	f.Streams().Printf("bakeoff research  run-id: %s\n", runID)
	f.Streams().Printf("  mode:           %s\n", wo.Type)
	if wo.Facet != nil {
		f.Streams().Printf("  facet:          %s\n", wo.Facet.ID)
	}
	f.Streams().Printf("  run dir:        %s/\n", runDir)
	f.Streams().Printf("  providers:      %s\n", strings.Join(providers, ", "))
	f.Streams().Printf("  budgets:        %s\n", workorder.FormatBudgetSummary(wo.Budgets))
	f.Streams().Printf("  scope policy:   %s\n", wo.ScopePolicy.Enforcement)
	f.Streams().Printf("  judge:          %s %s\n", wo.Judge.Backend, wo.Judge.Model)
}

func researchResultLine(wo *workorder.WorkOrder, decisionDoc map[string]any, reportText string) string {
	mode, _ := decisionDoc["mode"].(string)
	if mode == "" {
		mode = wo.Type
	}
	kind := fmt.Sprint(decisionDoc["decision_kind"])
	switch mode {
	case "gather":
		judge := "no"
		if ran, _ := decisionDoc["judge_ran"].(bool); ran {
			judge = "yes"
		}
		line := fmt.Sprintf("%s, judge=%s", kind, judge)
		if triagepkg.ShouldRecommendTriage(wo.Raw, decisionDoc, reportText) != "" {
			line += ", recommended: triage"
		}
		return line
	default:
		if kind == "consensus" {
			return "consensus (both providers agree)"
		}
		winner, _ := decisionDoc["canonical_winner"].(string)
		basis := "n/a"
		if tiebreak, _ := decisionDoc["spine_tiebreak"].(string); tiebreak != "" {
			basis = tiebreak
		} else if ran, _ := decisionDoc["judge_ran"].(bool); ran {
			basis = "judge"
		}
		if winner == "" {
			if ran, _ := decisionDoc["judge_ran"].(bool); ran {
				return fmt.Sprintf("no winner (unresolved disagreement, basis=%s)", basis)
			}
			winner = "none"
		}
		return fmt.Sprintf("winner=%s, basis=%s", winner, basis)
	}
}

func cloneMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}

func sortedProviderIDs(results map[string]map[string]any) []string {
	ids := make([]string, 0, len(results))
	for id := range results {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func reviewOptions(opts *ResearchOptions) reviewcontext.Options {
	return reviewcontext.Options{
		BaseRef:             opts.Base,
		IncludePatch:        opts.Diff,
		IncludeChangedFiles: opts.ChangedFiles,
	}
}

func validateFailedJudgeAttempt(wo *workorder.WorkOrder, sourceRunDir string) error {
	decisionDoc := readOptionalJSONObject(filepath.Join(sourceRunDir, "decision.json"))
	if decisionDoc != nil {
		if jsonutil.BoolValue(decisionDoc["judge_completed"]) {
			return &apperror.ValidationError{Message: "--judge-only cannot retry a run whose judge already completed successfully"}
		}
		if ran, ok := decisionDoc["judge_ran"].(bool); ok && !ran {
			return &apperror.ValidationError{Message: "--judge-only requires a source run where the judge ran and failed"}
		}
	}
	statuses := judgeStatusPaths(wo.Type, sourceRunDir)
	statusPresent := false
	statusFailed := false
	for _, path := range statuses {
		status, err := readJSONObject(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		statusPresent = true
		if !artifact.ProviderSucceeded(status) {
			statusFailed = true
		}
	}
	decisionFailed := failedJudgeDecision(decisionDoc)
	if statusPresent && !statusFailed {
		return &apperror.ValidationError{Message: "--judge-only cannot retry a run whose judge already completed successfully"}
	}
	if !statusPresent && !decisionFailed {
		return &apperror.ValidationError{Message: "--judge-only requires durable evidence of a failed judge attempt"}
	}
	if !statusFailed && !decisionFailed {
		return &apperror.ValidationError{Message: "--judge-only requires a failed judge attempt"}
	}
	return nil
}

func failedJudgeDecision(decisionDoc map[string]any) bool {
	if decisionDoc == nil {
		return false
	}
	kind := jsonutil.StringValue(decisionDoc["decision_kind"])
	if kind == "provider_union_only" || kind == "judge_failed" {
		return true
	}
	if completed, ok := decisionDoc["judge_completed"].(bool); ok && !completed {
		if jsonutil.BoolValue(decisionDoc["judge_ran"]) || jsonutil.BoolValue(decisionDoc["judge_attempted"]) {
			return true
		}
	}
	for _, item := range jsonutil.ListValue(decisionDoc["caveats"]) {
		text := strings.ToLower(fmt.Sprint(item))
		if strings.Contains(text, "judge failed") || strings.Contains(text, "judge crashed") {
			return true
		}
	}
	return false
}

func judgeStatusPaths(mode string, runDir string) []string {
	if mode == "gather" {
		return []string{filepath.Join(runDir, "judge", "status.json")}
	}
	return []string{
		filepath.Join(runDir, "judge", "status-pass1.json"),
		filepath.Join(runDir, "judge", "status-pass2.json"),
	}
}

func copyRequiredRunFile(sourceRunDir string, runDir string, name string) error {
	return copyFile(filepath.Join(sourceRunDir, name), filepath.Join(runDir, name))
}

func copyProviderArtifactDirs(wo *workorder.WorkOrder, sourceRunDir string, runDir string) error {
	for _, participant := range wo.Providers {
		source := filepath.Join(sourceRunDir, "providers", participant.ID)
		target := filepath.Join(runDir, "providers", participant.ID)
		if err := requireProviderReplayArtifacts(source, participant.ID); err != nil {
			return err
		}
		if err := copyDirectoryTree(source, target); err != nil {
			return err
		}
	}
	return nil
}

func requireProviderReplayArtifacts(providerDir string, providerID string) error {
	info, err := os.Stat(providerDir)
	if err != nil {
		return fmt.Errorf("provider %s artifact directory is required: %w", providerID, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("provider %s artifact path is not a directory", providerID)
	}
	for _, name := range []string{"status.json", "final.json"} {
		path := filepath.Join(providerDir, name)
		info, err := os.Stat(path)
		if err != nil {
			return fmt.Errorf("provider %s %s is required: %w", providerID, name, err)
		}
		if info.IsDir() {
			return fmt.Errorf("provider %s %s must be a file", providerID, name)
		}
	}
	return nil
}

func copyDirectoryTree(sourceDir string, targetDir string) error {
	sourceRoot, err := filepath.Abs(sourceDir)
	if err != nil {
		return err
	}
	return filepath.WalkDir(sourceDir, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(sourceDir, path)
		if err != nil {
			return err
		}
		target := filepath.Join(targetDir, relative)
		if entry.Type()&os.ModeSymlink != 0 {
			resolved, err := filepath.EvalSymlinks(path)
			if err != nil {
				return err
			}
			resolvedAbs, err := filepath.Abs(resolved)
			if err != nil {
				return err
			}
			inside, err := pathInside(sourceRoot, resolvedAbs)
			if err != nil {
				return err
			}
			if !inside {
				return fmt.Errorf("refusing to copy symlink outside source run: %s", path)
			}
			return copyFile(resolvedAbs, target)
		}
		if entry.IsDir() {
			return os.MkdirAll(target, 0o700)
		}
		return copyFile(path, target)
	})
}

func pathInside(parent string, child string) (bool, error) {
	rel, err := filepath.Rel(parent, child)
	if err != nil {
		return false, err
	}
	return rel == "." || (!strings.HasPrefix(rel, ".."+string(os.PathSeparator)) && rel != ".."), nil
}

func copyFile(source string, target string) error {
	info, err := os.Stat(source)
	if err != nil {
		return err
	}
	if info.IsDir() {
		return fmt.Errorf("%s is a directory", source)
	}
	data, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
		return err
	}
	return os.WriteFile(target, data, 0o600)
}

func loadResearchWorkerResultsFromArtifacts(wo *workorder.WorkOrder, runDir string) (map[string]map[string]any, error) {
	results := map[string]map[string]any{}
	for _, participant := range wo.Providers {
		providerDir := filepath.Join(runDir, "providers", participant.ID)
		status, err := readJSONObject(filepath.Join(providerDir, "status.json"))
		if err != nil {
			return nil, fmt.Errorf("provider %s status.json is required and must be a JSON object: %w", participant.ID, err)
		}
		if !artifact.ProviderSucceeded(status) {
			return nil, fmt.Errorf("provider %s status is not successful: %s", participant.ID, jsonutil.StringValue(status["status"]))
		}
		final, err := readJSONObject(filepath.Join(providerDir, "final.json"))
		if err != nil {
			return nil, fmt.Errorf("provider %s final.json is required and must be a JSON object: %w", participant.ID, err)
		}
		validated, err := workorder.ValidateWorkerResult(final, wo.Type)
		if err != nil {
			return nil, fmt.Errorf("provider %s final.json is invalid: %w", participant.ID, err)
		}
		result := cloneMap(status)
		result["final_json"] = validated
		results[participant.ID] = result
	}
	return results, nil
}

func readOptionalJSONObject(path string) map[string]any {
	obj, err := readJSONObject(path)
	if err != nil {
		return nil
	}
	return obj
}

func readJSONObject(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var obj map[string]any
	if err := json.Unmarshal(data, &obj); err != nil {
		return nil, err
	}
	if obj == nil {
		return nil, fmt.Errorf("%s must be a JSON object", path)
	}
	return obj, nil
}

func copyReplayContextArtifacts(sourceRunDir string, runDir string) error {
	names := []string{"source-work-order.json", "review-context.md", "review-context.json"}
	present := []string{}
	missing := []string{}
	for _, name := range names {
		source := filepath.Join(sourceRunDir, name)
		info, err := os.Stat(source)
		if err != nil || info.IsDir() {
			if err != nil && !os.IsNotExist(err) {
				return err
			}
			missing = append(missing, name)
			continue
		}
		present = append(present, name)
	}
	if len(present) == 0 {
		return nil
	}
	if len(missing) > 0 {
		return fmt.Errorf("source run has partial review-context artifact set; missing: %s", strings.Join(missing, ", "))
	}
	for _, name := range names {
		source := filepath.Join(sourceRunDir, name)
		data, err := os.ReadFile(source)
		if err != nil {
			return err
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, name), string(data)); err != nil {
			return err
		}
	}
	return nil
}
