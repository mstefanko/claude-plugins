package summary

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var okStatuses = map[string]bool{runner.StatusOK: true, runner.StatusOKAfterFormatRetry: true}

type ProviderSummary struct {
	Status      string `json:"status"`
	RawStatus   string `json:"raw_status,omitempty"`
	WallSeconds any    `json:"wall_seconds,omitempty"`
	OutputBytes any    `json:"output_bytes,omitempty"`
	StdoutBytes any    `json:"stdout_bytes,omitempty"`
	StderrBytes any    `json:"stderr_bytes,omitempty"`
}

type JudgeSummary struct {
	Status    string         `json:"status"`
	RawStatus string         `json:"raw_status"`
	Passes    map[string]any `json:"passes,omitempty"`
}

type ResearchTriageSummary struct {
	AutoStarted bool            `json:"auto_started"`
	State       string          `json:"state"`
	Status      any             `json:"status"`
	ExitCode    any             `json:"exit_code"`
	Artifacts   TriageArtifacts `json:"artifacts"`
	RawStatus   string          `json:"raw_status,omitempty"`
	StaleInputs []string        `json:"stale_inputs,omitempty"`
}

type ResearchSummary struct {
	SchemaVersion    int                        `json:"schema_version"`
	Command          string                     `json:"command"`
	Status           string                     `json:"status"`
	ExitCode         int                        `json:"exit_code"`
	Warnings         []string                   `json:"warnings"`
	RunID            string                     `json:"run_id"`
	RunDir           string                     `json:"run_dir"`
	DecisionKind     any                        `json:"decision_kind"`
	StalledAt        string                     `json:"stalled_at,omitempty"`
	CanonicalWinner  any                        `json:"canonical_winner"`
	JudgeRan         bool                       `json:"judge_ran"`
	Providers        map[string]ProviderSummary `json:"providers"`
	Judge            JudgeSummary               `json:"judge"`
	Triage           ResearchTriageSummary      `json:"triage"`
	Artifacts        ResearchArtifacts          `json:"artifacts"`
	Next             string                     `json:"next"`
	NextAlternatives []string                   `json:"next_alternatives,omitempty"`
}

type EscalationSummary struct {
	SchemaVersion   int                        `json:"schema_version"`
	Command         string                     `json:"command"`
	Status          string                     `json:"status"`
	ExitCode        int                        `json:"exit_code"`
	Warnings        []string                   `json:"warnings"`
	RunID           string                     `json:"run_id,omitempty"`
	RunDir          string                     `json:"run_dir,omitempty"`
	SourceRunID     string                     `json:"source_run_id"`
	SourceRunDir    string                     `json:"source_run_dir,omitempty"`
	Mode            string                     `json:"mode"`
	AddedProvider   string                     `json:"added_provider"`
	SourceProviders []string                   `json:"source_providers"`
	DecisionKind    any                        `json:"decision_kind,omitempty"`
	CanonicalWinner any                        `json:"canonical_winner,omitempty"`
	DryRun          bool                       `json:"dry_run"`
	EstimatedCalls  map[string]any             `json:"estimated_calls,omitempty"`
	Providers       map[string]ProviderSummary `json:"providers,omitempty"`
	Judge           JudgeSummary               `json:"judge,omitempty"`
	Triage          ResearchTriageSummary      `json:"triage,omitempty"`
	Artifacts       ResearchArtifacts          `json:"artifacts,omitempty"`
	Next            string                     `json:"next,omitempty"`
}

type ResearchArtifacts struct {
	WorkOrder         string `json:"work_order,omitempty"`
	Decision          string `json:"decision,omitempty"`
	Meta              string `json:"meta,omitempty"`
	Manifest          string `json:"manifest,omitempty"`
	Report            string `json:"report,omitempty"`
	SourceRun         string `json:"source_run,omitempty"`
	EscalationMode    string `json:"escalation_mode,omitempty"`
	DisputePacket     string `json:"dispute_packet,omitempty"`
	SourceWorkOrder   string `json:"source_work_order,omitempty"`
	ReviewContextMD   string `json:"review_context_md,omitempty"`
	ReviewContextJSON string `json:"review_context_json,omitempty"`
}

type TriageArtifacts struct {
	Prompt              string `json:"prompt,omitempty"`
	Status              string `json:"status,omitempty"`
	CitationChecks      string `json:"citation_checks,omitempty"`
	SourceFindingFilter string `json:"source_finding_filter,omitempty"`
	FindingIndex        string `json:"finding_index,omitempty"`
	Final               string `json:"final,omitempty"`
	Triage              string `json:"triage,omitempty"`
}

type TriageDetails struct {
	State                string `json:"state"`
	Status               any    `json:"status"`
	RawStatus            any    `json:"raw_status"`
	SelectedFindings     any    `json:"selected_findings"`
	SkippedNonActionable any    `json:"skipped_non_actionable"`
	SkippedOutOfFacet    any    `json:"skipped_out_of_facet"`
}

type TriageSummary struct {
	SchemaVersion int             `json:"schema_version"`
	Command       string          `json:"command"`
	Status        string          `json:"status"`
	ExitCode      int             `json:"exit_code"`
	Warnings      []string        `json:"warnings"`
	RunID         string          `json:"run_id"`
	RunDir        string          `json:"run_dir"`
	DryRun        bool            `json:"dry_run"`
	Triage        TriageDetails   `json:"triage"`
	Artifacts     TriageArtifacts `json:"artifacts"`
	Next          string          `json:"next"`
}

func Print(w io.Writer, value any) error {
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func CommandStatus(exitCode int) string {
	if exitCode == 0 {
		return "ok"
	}
	if exitCode == 3 {
		return "judge_disagreement"
	}
	if exitCode == 4 {
		return "decision_incomplete"
	}
	return "failed"
}

func CompactStatus(raw any) string {
	text := "missing_status"
	if raw != nil {
		text = strings.TrimSpace(jsonutil.StringValue(raw))
	}
	if okStatuses[text] {
		return runner.StatusOK
	}
	if text == runner.StatusSalvaged {
		return "warn"
	}
	return "failed"
}

func ProviderStatusSummary(status map[string]any) ProviderSummary {
	raw := status["status"]
	rawText := ""
	if raw != nil {
		rawText = jsonutil.StringValue(raw)
	}
	out := ProviderSummary{Status: CompactStatus(raw)}
	if rawText != "" {
		out.RawStatus = rawText
	}
	out.WallSeconds = status["wall_seconds"]
	out.OutputBytes = status["output_bytes"]
	out.StdoutBytes = status["stdout_bytes"]
	out.StderrBytes = status["stderr_bytes"]
	return out
}

func JudgeJSONSummary(runDir string, decision map[string]any) JudgeSummary {
	if !jsonutil.BoolValue(decision["judge_ran"]) {
		return JudgeSummary{Status: "not_run", RawStatus: "not_run"}
	}
	judgeDir := filepath.Join(runDir, "judge")
	entries, _ := os.ReadDir(judgeDir)
	statusPaths := []string{}
	for _, entry := range entries {
		name := entry.Name()
		if !entry.IsDir() && strings.HasPrefix(name, "status") && strings.HasSuffix(name, ".json") {
			statusPaths = append(statusPaths, filepath.Join(judgeDir, name))
		}
	}
	sort.Strings(statusPaths)
	if len(statusPaths) == 0 {
		return JudgeSummary{Status: "failed", RawStatus: "missing_status"}
	}
	passes := map[string]any{}
	rawStatuses := []string{}
	for _, path := range statusPaths {
		status := readJSON(path)
		raw := "invalid_status"
		if obj, ok := status.(map[string]any); ok {
			raw = jsonutil.StringValue(obj["status"])
		}
		label := strings.TrimSuffix(filepath.Base(path), ".json")
		label = strings.TrimPrefix(label, "status-")
		if label == "status" {
			label = "gather"
		}
		passes[label] = raw
		rawStatuses = append(rawStatuses, raw)
	}
	status := "ok"
	for _, raw := range rawStatuses {
		compact := CompactStatus(raw)
		if compact == "failed" {
			status = "failed"
			break
		}
		if compact == "warn" {
			status = "warn"
			continue
		}
	}
	rawStatus := rawStatuses[0]
	if !allSame(rawStatuses) {
		rawStatus = strings.Join(rawStatuses, ", ")
	}
	out := JudgeSummary{Status: status, RawStatus: rawStatus}
	if len(passes) > 1 {
		out.Passes = passes
	}
	return out
}

func BuildResearch(runDir string, runID string, outDir string, decision map[string]any, workerResults map[string]map[string]any, exitCode int, autoTriageStarted bool, triageExitCode any) ResearchSummary {
	providers := map[string]ProviderSummary{}
	for providerID, result := range workerResults {
		providers[providerID] = ProviderStatusSummary(result)
	}
	judge := JudgeJSONSummary(runDir, decision)
	next, alternatives := ResearchNextCommands(runDir, runID, outDir, decision, exitCode)
	return ResearchSummary{
		SchemaVersion:    1,
		Command:          "research",
		Status:           CommandStatus(exitCode),
		ExitCode:         exitCode,
		Warnings:         []string{},
		RunID:            runID,
		RunDir:           runDir,
		DecisionKind:     decision["decision_kind"],
		StalledAt:        jsonutil.StringValue(decision["stalled_at"]),
		CanonicalWinner:  decision["canonical_winner"],
		JudgeRan:         jsonutil.BoolValue(decision["judge_ran"]),
		Providers:        providers,
		Judge:            judge,
		Triage:           ResearchTriage(runDir, autoTriageStarted, triageExitCode),
		Artifacts:        ResearchArtifactPaths(runDir),
		Next:             next,
		NextAlternatives: alternatives,
	}
}

func ResearchNextCommands(runDir string, runID string, outDir string, decision map[string]any, exitCode int) (string, []string) {
	if shouldRecommendJudgeOnlyRerun(runDir, decision, exitCode) {
		return ledger.BakeoffJudgeOnlyRerunCommand(runID, outDir), []string{ledger.BakeoffRerunCommand(runID, outDir)}
	}
	return ledger.BakeoffShowCommand(runID, outDir, ""), nil
}

func shouldRecommendJudgeOnlyRerun(runDir string, decision map[string]any, exitCode int) bool {
	if exitCode != 4 {
		return false
	}
	if !isResearchMode(jsonutil.StringValue(valueFromMap(decision, "mode"))) {
		return false
	}
	if !allProviderStatusesSucceeded(runDir, decision) {
		return false
	}
	judge := JudgeJSONSummary(runDir, decision)
	return judgeStatusFailedOrIncomplete(judge)
}

func isResearchMode(mode string) bool {
	switch mode {
	case "gather", "compare", "analyze":
		return true
	default:
		return false
	}
}

func allProviderStatusesSucceeded(runDir string, decision map[string]any) bool {
	statuses := providerStatusMapFromDecision(decision)
	if len(statuses) == 0 {
		statuses = providerStatusMapFromArtifacts(runDir)
	}
	providerIDs := declaredProviderIDs(runDir)
	if len(providerIDs) > 0 {
		if len(statuses) != len(providerIDs) {
			return false
		}
		for _, providerID := range providerIDs {
			status, ok := statuses[providerID]
			if !ok || !rawStatusSucceeded(status["status"]) {
				return false
			}
		}
		return true
	}
	if len(statuses) < 2 {
		return false
	}
	for _, status := range statuses {
		if !rawStatusSucceeded(status["status"]) {
			return false
		}
	}
	return true
}

func providerStatusMapFromDecision(decision map[string]any) map[string]map[string]any {
	raw, _ := valueFromMap(decision, "provider_statuses").(map[string]any)
	if len(raw) == 0 {
		return nil
	}
	statuses := make(map[string]map[string]any, len(raw))
	for providerID, value := range raw {
		if status, ok := value.(map[string]any); ok {
			statuses[providerID] = status
		}
	}
	return statuses
}

func providerStatusMapFromArtifacts(runDir string) map[string]map[string]any {
	entries, err := os.ReadDir(filepath.Join(runDir, "providers"))
	if err != nil {
		return nil
	}
	statuses := map[string]map[string]any{}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		status, _ := readJSON(filepath.Join(runDir, "providers", entry.Name(), "status.json")).(map[string]any)
		if status != nil {
			statuses[entry.Name()] = status
		}
	}
	return statuses
}

func declaredProviderIDs(runDir string) []string {
	wo, err := workorder.Load(filepath.Join(runDir, "work-order.json"))
	if err != nil || wo == nil {
		return nil
	}
	ids := make([]string, 0, len(wo.Providers))
	for _, provider := range wo.Providers {
		if provider.ID != "" {
			ids = append(ids, provider.ID)
		}
	}
	return ids
}

func rawStatusSucceeded(raw any) bool {
	return okStatuses[strings.TrimSpace(jsonutil.StringValue(raw))]
}

func judgeStatusFailedOrIncomplete(judge JudgeSummary) bool {
	if judge.Status == runner.StatusOK || judge.Status == "not_run" {
		return false
	}
	return judge.Status == "failed" || judge.Status == "warn"
}

func BuildEscalation(runDir string, runID string, outDir string, sourceRunID string, sourceRunDir string, mode string, addedProvider string, sourceProviders []string, decision map[string]any, providerResults map[string]map[string]any, exitCode int, dryRun bool, estimatedCalls map[string]any, autoTriageStarted bool, triageExitCode any) EscalationSummary {
	providers := map[string]ProviderSummary{}
	for providerID, result := range providerResults {
		providers[providerID] = ProviderStatusSummary(result)
	}
	return EscalationSummary{
		SchemaVersion:   1,
		Command:         "escalate",
		Status:          CommandStatus(exitCode),
		ExitCode:        exitCode,
		Warnings:        []string{},
		RunID:           runID,
		RunDir:          runDir,
		SourceRunID:     sourceRunID,
		SourceRunDir:    sourceRunDir,
		Mode:            mode,
		AddedProvider:   addedProvider,
		SourceProviders: append([]string(nil), sourceProviders...),
		DecisionKind:    valueFromMap(decision, "decision_kind"),
		CanonicalWinner: valueFromMap(decision, "canonical_winner"),
		DryRun:          dryRun,
		EstimatedCalls:  estimatedCalls,
		Providers:       providers,
		Judge:           JudgeJSONSummary(runDir, decision),
		Triage:          ResearchTriage(runDir, autoTriageStarted, triageExitCode),
		Artifacts:       ResearchArtifactPaths(runDir),
		Next:            ledger.BakeoffShowCommand(runID, outDir, ""),
	}
}

func ResearchTriage(runDir string, autoStarted bool, triageExitCode any) ResearchTriageSummary {
	state, staleInputs := triage.DisplayStateDetail(runDir)
	statusData := readJSON(filepath.Join(runDir, "triage", "status.json"))
	rawStatus := ""
	if obj, ok := statusData.(map[string]any); ok {
		rawStatus = jsonutil.StringValue(obj["status"])
	}
	var status any
	if rawStatus == "" {
		status = nil
	} else if rawStatus == "dry_run" {
		status = "dry_run"
	} else {
		status = CompactStatus(rawStatus)
	}
	out := ResearchTriageSummary{
		AutoStarted: autoStarted,
		State:       state,
		Status:      status,
		ExitCode:    triageExitCode,
		Artifacts:   TriageArtifactPaths(runDir),
	}
	if rawStatus != "" && rawStatus != jsonutil.StringValue(status) {
		out.RawStatus = rawStatus
	}
	if len(staleInputs) > 0 {
		out.StaleInputs = staleInputs
	}
	return out
}

func valueFromMap(obj map[string]any, key string) any {
	if obj == nil {
		return nil
	}
	return obj[key]
}

func ResearchArtifactPaths(runDir string) ResearchArtifacts {
	out := ResearchArtifacts{}
	set := func(relative string) string {
		path := filepath.Join(runDir, relative)
		if fsutil.FileExists(path) {
			return path
		}
		return ""
	}
	out.WorkOrder = set("work-order.json")
	out.Decision = set("decision.json")
	out.Meta = set("meta.json")
	out.Manifest = set("manifest.json")
	out.Report = set("report.md")
	out.SourceRun = set("source-run.json")
	out.EscalationMode = set("escalation/mode.json")
	out.DisputePacket = set("escalation/dispute-packet.json")
	out.SourceWorkOrder = set("source-work-order.json")
	out.ReviewContextMD = set("review-context.md")
	out.ReviewContextJSON = set("review-context.json")
	return out
}

func TriageArtifactPaths(runDir string) TriageArtifacts {
	triageDir := filepath.Join(runDir, "triage")
	out := TriageArtifacts{}
	set := func(relative string) string {
		path := filepath.Join(triageDir, relative)
		if fsutil.FileExists(path) {
			return path
		}
		return ""
	}
	out.Prompt = set("prompt.txt")
	out.Status = set("status.json")
	out.CitationChecks = set("citation_checks.json")
	out.SourceFindingFilter = set("source_finding_filter.json")
	out.FindingIndex = set("finding_index.json")
	out.Final = set("final.json")
	out.Triage = set("triage.md")
	return out
}

func BuildTriage(runDir string, runID string, outDir string, exitCode int, dryRun bool) TriageSummary {
	triageDir := filepath.Join(runDir, "triage")
	statusData := readJSON(filepath.Join(triageDir, "status.json"))
	statusObj, _ := statusData.(map[string]any)
	if statusObj == nil {
		statusObj = map[string]any{}
	}
	rawStatus := statusObj["status"]
	filterSummary, _ := statusObj["source_finding_filter"].(map[string]any)
	if filterSummary == nil {
		final, _ := readJSON(filepath.Join(triageDir, "final.json")).(map[string]any)
		if final != nil {
			filterSummary, _ = final["source_finding_filter"].(map[string]any)
		}
	}
	if filterSummary == nil {
		filterSummary = map[string]any{}
	}
	triageStatus := any(CompactStatus(rawStatus))
	if jsonutil.StringValue(rawStatus) == "dry_run" {
		triageStatus = "dry_run"
	}
	next := ledger.BakeoffTriageCommand(runID, outDir, true)
	if !dryRun && exitCode == 0 {
		next = ledger.BakeoffShowCommand(runID, outDir, "--triage")
	}
	return TriageSummary{
		SchemaVersion: 1,
		Command:       "triage",
		Status:        CommandStatus(exitCode),
		ExitCode:      exitCode,
		Warnings:      []string{},
		RunID:         runID,
		RunDir:        runDir,
		DryRun:        dryRun,
		Triage: TriageDetails{
			State:                triage.State(runDir),
			Status:               triageStatus,
			RawStatus:            rawStatus,
			SelectedFindings:     defaultNumber(filterSummary["included"]),
			SkippedNonActionable: defaultNumber(filterSummary["skipped_non_actionable"]),
			SkippedOutOfFacet:    defaultNumber(filterSummary["skipped_out_of_facet"]),
		},
		Artifacts: TriageArtifactPaths(runDir),
		Next:      next,
	}
}

func StatusMap(result map[string]map[string]any, providerID string) map[string]any {
	if value, ok := result[providerID]; ok {
		return artifact.StatusWithoutPayload(value)
	}
	return map[string]any{}
}

func readJSON(path string) any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return nil
	}
	return value
}

func defaultNumber(value any) any {
	if value == nil {
		return 0
	}
	return value
}

func allSame(items []string) bool {
	if len(items) < 2 {
		return true
	}
	first := items[0]
	for _, item := range items[1:] {
		if item != first {
			return false
		}
	}
	return true
}
