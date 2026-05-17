package summary

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
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
	AutoStarted bool              `json:"auto_started"`
	State       string            `json:"state"`
	Status      any               `json:"status"`
	ExitCode    any               `json:"exit_code"`
	Artifacts   map[string]string `json:"artifacts"`
	RawStatus   string            `json:"raw_status,omitempty"`
	StaleInputs []string          `json:"stale_inputs,omitempty"`
}

type ResearchSummary struct {
	SchemaVersion   int                        `json:"schema_version"`
	Command         string                     `json:"command"`
	Status          string                     `json:"status"`
	ExitCode        int                        `json:"exit_code"`
	Warnings        []string                   `json:"warnings"`
	RunID           string                     `json:"run_id"`
	RunDir          string                     `json:"run_dir"`
	DecisionKind    any                        `json:"decision_kind"`
	CanonicalWinner any                        `json:"canonical_winner"`
	JudgeRan        bool                       `json:"judge_ran"`
	Providers       map[string]ProviderSummary `json:"providers"`
	Judge           JudgeSummary               `json:"judge"`
	Triage          ResearchTriageSummary      `json:"triage"`
	Artifacts       ResearchArtifacts          `json:"artifacts"`
	Next            string                     `json:"next"`
}

type ResearchArtifacts struct {
	WorkOrder         string `json:"work_order,omitempty"`
	Decision          string `json:"decision,omitempty"`
	Meta              string `json:"meta,omitempty"`
	Manifest          string `json:"manifest,omitempty"`
	Report            string `json:"report,omitempty"`
	SourceWorkOrder   string `json:"source_work_order,omitempty"`
	ReviewContextMD   string `json:"review_context_md,omitempty"`
	ReviewContextJSON string `json:"review_context_json,omitempty"`
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
	return "failed"
}

func CompactStatus(raw any) string {
	text := "missing_status"
	if raw != nil {
		text = strings.TrimSpace(stringValue(raw))
	}
	if okStatuses[text] {
		return text
	}
	return "failed"
}

func ProviderStatusSummary(status map[string]any) ProviderSummary {
	raw := status["status"]
	rawText := ""
	if raw != nil {
		rawText = stringValue(raw)
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
	if !boolValue(decision["judge_ran"]) {
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
			raw = stringValue(obj["status"])
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
		if !okStatuses[raw] {
			status = "failed"
			break
		}
		if raw == runner.StatusOKAfterFormatRetry {
			status = runner.StatusOKAfterFormatRetry
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
	return ResearchSummary{
		SchemaVersion:   1,
		Command:         "research",
		Status:          CommandStatus(exitCode),
		ExitCode:        exitCode,
		Warnings:        []string{},
		RunID:           runID,
		RunDir:          runDir,
		DecisionKind:    decision["decision_kind"],
		CanonicalWinner: decision["canonical_winner"],
		JudgeRan:        boolValue(decision["judge_ran"]),
		Providers:       providers,
		Judge:           JudgeJSONSummary(runDir, decision),
		Triage:          ResearchTriage(runDir, autoTriageStarted, triageExitCode),
		Artifacts:       ResearchArtifactPaths(runDir),
		Next:            ledger.BakeoffShowCommand(runID, outDir, ""),
	}
}

func ResearchTriage(runDir string, autoStarted bool, triageExitCode any) ResearchTriageSummary {
	state, staleInputs := triage.StateDetail(runDir)
	statusData := readJSON(filepath.Join(runDir, "triage", "status.json"))
	rawStatus := ""
	if obj, ok := statusData.(map[string]any); ok {
		rawStatus = stringValue(obj["status"])
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
	if rawStatus != "" && rawStatus != stringValue(status) {
		out.RawStatus = rawStatus
	}
	if len(staleInputs) > 0 {
		out.StaleInputs = staleInputs
	}
	return out
}

func ResearchArtifactPaths(runDir string) ResearchArtifacts {
	out := ResearchArtifacts{}
	set := func(relative string) string {
		path := filepath.Join(runDir, relative)
		if fileExists(path) {
			return path
		}
		return ""
	}
	out.WorkOrder = set("work-order.json")
	out.Decision = set("decision.json")
	out.Meta = set("meta.json")
	out.Manifest = set("manifest.json")
	out.Report = set("report.md")
	out.SourceWorkOrder = set("source-work-order.json")
	out.ReviewContextMD = set("review-context.md")
	out.ReviewContextJSON = set("review-context.json")
	return out
}

func TriageArtifactPaths(runDir string) map[string]string {
	triageDir := filepath.Join(runDir, "triage")
	candidates := map[string]string{
		"prompt":                "prompt.txt",
		"status":                "status.json",
		"citation_checks":       "citation_checks.json",
		"source_finding_filter": "source_finding_filter.json",
		"finding_index":         "finding_index.json",
		"final":                 "final.json",
		"triage":                "triage.md",
	}
	out := map[string]string{}
	for key, relative := range candidates {
		path := filepath.Join(triageDir, relative)
		if fileExists(path) {
			out[key] = path
		}
	}
	return out
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

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func boolValue(value any) bool {
	v, _ := value.(bool)
	return v
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
