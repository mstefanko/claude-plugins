package researchcmd

import (
	"context"
	"crypto/rand"
	"encoding/hex"
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
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/report"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/reviewcontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
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
	sourceText, err := os.ReadFile(opts.WorkOrder)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	runID := opts.RunID
	if runID == "" {
		runID = ledger.MakeRunID(f.Now(), randomSuffix())
	}
	if err := ledger.ValidateRunID(runID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	runDir := ledger.RunDir(opts.Out, runID)
	if _, err := os.Stat(runDir); err == nil {
		if !opts.Force {
			return &apperror.ValidationError{Message: fmt.Sprintf("%s already exists; use --force to replace", runDir)}
		}
		if err := ledger.EnsureChildPath(opts.Out, runDir); err != nil {
			return &apperror.ValidationError{Message: err.Error(), Err: err}
		}
		if err := os.RemoveAll(runDir); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	startedAt := artifact.UTCNow()
	var reviewContext *reviewcontext.Context
	if reviewOptions(opts).Enabled() {
		cwd, _ := os.Getwd()
		reviewContext, err = reviewcontext.Build(reviewOptions(opts), cwd, startedAt)
		if err != nil {
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
	if err := os.MkdirAll(runDir, 0o755); err != nil {
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
	} else if opts.ReplaySourceRunDir != "" && fileExists(filepath.Join(runDir, "review-context.md")) && humanOutput {
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
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), decisionDoc); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	reportText := report.Render(wo, decisionDoc, workerResults, judgeResults)
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), reportText); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if err := artifact.WriteMeta(ctx, runDir, wo, runID, startedAt, workerResults, f.LookupProvider); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	if humanOutput {
		if fileExists(filepath.Join(runDir, "review-context.md")) {
			f.Streams().Printf("context-md: %s\n", filepath.Join(runDir, "review-context.md"))
		}
		f.Streams().Printf("manifest: %s\n", filepath.Join(runDir, "manifest.json"))
		f.Streams().Printf("report: %s\n", filepath.Join(runDir, "report.md"))
		f.Streams().Printf("next:   %s\n", ledger.BakeoffShowCommand(runID, opts.Out, ""))
	}
	autoTriageReason := ""
	autoTriageStarted := false
	var triageExitCode any
	if !opts.NoTriage && exitCode == 0 {
		autoTriageReason = triagepkg.ShouldAutoTriage(wo.Raw, decisionDoc)
		if autoTriageReason != "" && humanOutput {
			f.Streams().Printf("auto-triage starting: %s\n", autoTriageReason)
		}
		if autoTriageReason != "" {
			autoTriageStarted = true
			triageOpts := &triagecmd.TriageOptions{
				RunID:        runID,
				Out:          opts.Out,
				Quiet:        effectiveQuiet,
				RunDir:       runDir,
				DisplayRunID: runID,
				HumanOutput:  &humanOutput,
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
	if !opts.NoTriage && !autoTriageStarted && humanOutput {
		if recommendation := triagepkg.ShouldRecommendTriage(wo.Raw, decisionDoc, reportText); recommendation != "" {
			f.Streams().Printf("recommended: %s  (%s)\n", ledger.BakeoffTriageCommand(runID, opts.Out, false), recommendation)
		}
	}
	if opts.JSON {
		value := summary.BuildResearch(runDir, runID, opts.Out, decisionDoc, workerResults, exitCode, autoTriageStarted, triageExitCode)
		if err := summary.Print(f.Streams().Out, value); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	if exitCode == 3 {
		return &apperror.SilentError{Err: &apperror.JudgeDisagreementError{Message: "judge disagreement"}}
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
	for index, providerParticipant := range wo.Providers {
		index := index
		participant := providerParticipant
		group.Go(func() error {
			result, err := runOneWorker(groupCtx, f, wo, participant, runDir, cwd, capabilities, quiet, humanOutput)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return err
				}
				result = internalErrorResult(err)
				providerDir := filepath.Join(runDir, "providers", participant.ID)
				_ = os.MkdirAll(providerDir, 0o755)
				_ = artifact.WriteProviderArtifacts(providerDir, result)
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
	return results, nil
}

func runOneWorker(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder, participant workorder.Participant, runDir string, cwd string, capabilities map[string]provider.ScopeCapabilities, quiet bool, humanOutput bool) (map[string]any, error) {
	providerDir := filepath.Join(runDir, "providers", participant.ID)
	if err := os.MkdirAll(providerDir, 0o755); err != nil {
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
		if humanOutput {
			f.Streams().Printf("[%s] %s %vs %v bytes\n", participant.ID, result["status"], result["wall_seconds"], result["output_bytes"])
		}
		return result, nil
	}
	defer scope.Cleanup(scopeExecution.CleanupPaths)
	if humanOutput {
		f.Streams().Printf("[%s] launching...\n", participant.ID)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             scopeExecution.Argv,
		Prompt:           workerPrompt,
		Budgets:          runnerBudgets(wo.Budgets),
		CWD:              scopeExecution.CWD,
		Env:              os.Environ(),
		Validator:        func(data any) (any, error) { return workorder.ValidateWorkerResult(data, wo.Type) },
		OnTick:           commands.MakeTickPrinter(f, participant.ID, quiet),
		FinalMessagePath: finalMessagePath,
	}))
	result["scope_enforcement"] = scopeExecution.Metadata
	if err := artifact.WriteProviderArtifacts(providerDir, result); err != nil {
		return nil, err
	}
	if humanOutput {
		f.Streams().Printf("[%s] %s %vs %v bytes\n", participant.ID, result["status"], result["wall_seconds"], result["output_bytes"])
	}
	return result, nil
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
	judgeResults := map[string]map[string]any{"pass1": finalJSONMap(pass1), "pass2": finalJSONMap(pass2)}
	if !artifact.ProviderSucceeded(pass1) || !artifact.ProviderSucceeded(pass2) {
		decisionDoc := cloneMap(base)
		decisionDoc["decision_kind"] = "tie"
		decisionDoc["judge_ran"] = true
		decisionDoc["order_maps"] = map[string]any{"pass1": pass1Order, "pass2": pass2Order}
		decisionDoc["canonical_winner"] = nil
		decisionDoc["judge_rationale"] = []string{}
		decisionDoc["caveats"] = []string{fmt.Sprintf("judge failed: pass1=%s, pass2=%s", pass1["status"], pass2["status"])}
		return decisionDoc, judgeResults, 1, nil
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
	workerA := finalJSONMap(workerResults[orderMap["A"]])
	workerB := finalJSONMap(workerResults[orderMap["B"]])
	judgePrompt, err := prompt.BuildJudgePrompt(wo, workerA, workerB, "")
	if err != nil {
		return nil, err
	}
	judgeDir := filepath.Join(runDir, "judge")
	if err := os.MkdirAll(judgeDir, 0o755); err != nil {
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
	argv, err := provider.BuildParticipantArgv(wo.Judge, cwd, nil, lastMessage, f.Capabilities().CodexExecSupportsOutputLastMessage(ctx))
	if err != nil {
		return nil, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] running...\n", label)
	}
	result := artifact.ResultMap(runner.RunProviderWithFormatRetry(ctx, runner.Options{
		Argv:             argv,
		Prompt:           judgePrompt,
		Budgets:          runnerBudgets(wo.Budgets),
		CWD:              cwd,
		Env:              os.Environ(),
		Validator:        judgeValidator(wo.Type),
		OnTick:           commands.MakeTickPrinter(f, "judge:"+label, quiet),
		FinalMessagePath: lastMessage,
	}))
	if err := artifact.WriteJudgeArtifacts(judgeDir, label, result); err != nil {
		return nil, err
	}
	if humanOutput {
		f.Streams().Printf("[judge:%s] %s %vs\n", label, result["status"], result["wall_seconds"])
	}
	return result, nil
}

func runnerBudgets(b workorder.Budgets) runner.Budgets {
	return runner.Budgets{
		WallClockSeconds:      b.WallClockSeconds,
		MaxOutputBytes:        b.MaxOutputBytes,
		HeartbeatSeconds:      b.HeartbeatSeconds,
		OutputCapGraceSeconds: b.OutputCapGraceSeconds,
		MaxOutputOverrunBytes: b.MaxOutputOverrunBytes,
	}
}

func judgeValidator(mode string) func(any) (any, error) {
	switch mode {
	case "gather":
		return workorder.ValidateGatherJudgeResult
	case "compare":
		return workorder.ValidateCompareJudgeResult
	default:
		return workorder.ValidateAnalyzeJudgeResult
	}
}

func makeTickPrinter(f commands.Factory, label string, quiet bool) func(runner.Tick) {
	if quiet {
		return nil
	}
	return func(tick runner.Tick) {
		elapsed := int(tick.Elapsed)
		wallSeconds := tick.WallSeconds
		lastOutputAge := int(tick.LastOutputAge)
		f.Streams().Errorf("[%s] %s t=%ds/%ds out=%.1fKB err=%.1fKB last=%ds\n", label, tick.Phase, elapsed, wallSeconds, float64(tick.StdoutBytes)/1024, float64(tick.StderrBytes)/1024, lastOutputAge)
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

func finalJSONMap(result map[string]any) map[string]any {
	final, _ := result["final_json"].(map[string]any)
	if final == nil {
		return map[string]any{}
	}
	return final
}

func internalErrorResult(err error) map[string]any {
	return map[string]any{
		"status":       runner.StatusExitError,
		"exit_code":    nil,
		"wall_seconds": 0,
		"output_bytes": 0,
		"stdout":       "",
		"stderr":       fmt.Sprintf("internal provider task error: %T: %v", err, err),
		"final_json":   nil,
	}
}

func cloneMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}

func randomSuffix() string {
	var data [2]byte
	if _, err := rand.Read(data[:]); err != nil {
		return "0000"
	}
	return hex.EncodeToString(data[:])
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

func copyReplayContextArtifacts(sourceRunDir string, runDir string) error {
	for _, name := range []string{"source-work-order.json", "review-context.md", "review-context.json"} {
		source := filepath.Join(sourceRunDir, name)
		data, err := os.ReadFile(source)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}
		if err := workorder.WriteTextAtomic(filepath.Join(runDir, name), string(data)); err != nil {
			return err
		}
	}
	return nil
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
