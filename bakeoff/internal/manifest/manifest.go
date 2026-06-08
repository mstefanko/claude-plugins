package manifest

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const (
	// SchemaVersion is the top-level manifest.json contract. It is independent
	// from the telemetry payload version nested under manifest.telemetry.
	SchemaVersion = 1

	// TelemetrySchemaVersion is the manifest.telemetry payload contract.
	TelemetrySchemaVersion = 2
)

var CoreFingerprintArtifacts = []string{
	"work-order.json",
	"source-run.json",
	"source-work-order.json",
	"review-context.md",
	"review-context.json",
	"decision.json",
	"meta.json",
	"report.md",
	"diagnostics.json",
	"escalation/mode.json",
	"escalation/dispute-packet.json",
	"escalation/synthesis-prompt.txt",
	"escalation/witness-prompt.txt",
	"escalation/dispute-prompt.txt",
	"triage/status.json",
	"triage/final.json",
	"triage/source_finding_filter.json",
	"triage/citation_checks.json",
	"triage/finding_index.json",
	"triage/prompt.txt",
	"triage/stdout.txt",
	"triage/stderr.txt",
	"triage/triage.md",
}

var RequiredArtifacts = []string{"work-order.json", "decision.json", "meta.json", "report.md"}
var ReviewContextArtifacts = []string{"source-work-order.json", "review-context.md", "review-context.json"}

func BuildRunManifest(runDir string) (map[string]any, error) {
	workOrder, err := readRequiredJSON(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return nil, err
	}
	decision, err := readRequiredJSON(filepath.Join(runDir, "decision.json"))
	if err != nil {
		return nil, err
	}
	meta, err := readRequiredJSON(filepath.Join(runDir, "meta.json"))
	if err != nil {
		return nil, err
	}
	if err := requireFile(filepath.Join(runDir, "report.md")); err != nil {
		return nil, err
	}

	// facet_id is the hoisted meta.facet.id/work-order facet.id for list views;
	// meta.facet remains the full facet object.
	facetID := ""
	if facet, ok := meta["facet"].(map[string]any); ok {
		facetID, _ = facet["id"].(string)
	}
	if facetID == "" {
		if facet, ok := workOrder["facet"].(map[string]any); ok {
			facetID, _ = facet["id"].(string)
		}
	}
	state, staleInputs := triage.DisplayStateDetail(runDir)
	triageSummary := triageSummary(runDir, state, staleInputs)
	runType := resolveRunType(workOrder, meta, decision)
	runMode := resolveRunMode(runType, workOrder, meta, decision)
	singleProvider := resolveSingleProvider(workOrder, decision, runMode)
	artifacts, err := artifactPathsForType(runDir, runType)
	if err != nil {
		return nil, err
	}
	out := map[string]any{
		"schema_version":          SchemaVersion,
		"run_id":                  filepath.Base(runDir),
		"bakeoff_version":         buildinfo.Current().Version,
		"type":                    nilIfEmpty(runType),
		"run_mode":                nilIfEmpty(runMode),
		"single_provider":         nilIfEmpty(singleProvider),
		"facet_id":                nilIfEmpty(facetID),
		"started_at":              meta["started_at"],
		"finished_at":             meta["finished_at"],
		"cwd":                     meta["cwd"],
		"decision_kind":           decision["decision_kind"],
		"canonical_winner":        decision["canonical_winner"],
		"selected_patch_provider": nilIfEmpty(jsonutil.StringValue(decision["selected_patch_provider"])),
		"judge_ran":               truthy(decision["judge_ran"]),
		"judge_attempted":         truthy(decision["judge_attempted"]),
		"judge_completed":         truthy(decision["judge_completed"]),
		"triage":                  triageSummary,
		"providers":               providerSummaries(meta, decision),
		"judge":                   judgeSummary(meta),
		"review_context":          reviewContextSummary(runDir),
		"artifacts":               artifacts,
		"artifact_fingerprints":   artifactFingerprintsForType(runDir, runType),
	}
	addExperimentManifestFields(out, meta)
	addRerunManifestFields(out, meta, decision)
	if isEscalationRun(meta, decision) {
		addEscalationManifestFields(out, meta, decision, workOrder)
	}
	out["telemetry"] = telemetrySummary(runDir, workOrder, meta, decision, out, triageSummary)
	return out, nil
}

func WriteRunManifest(runDir string) (map[string]any, error) {
	value, err := BuildRunManifest(runDir)
	if err != nil {
		return nil, err
	}
	return value, workorder.WriteJSONAtomic(filepath.Join(runDir, "manifest.json"), value)
}

func RowForLS(runDir string) map[string]any {
	manifestPath := filepath.Join(runDir, "manifest.json")
	loaded, err := readLSManifest(manifestPath)
	if err != nil {
		if !os.IsNotExist(err) {
			row := legacyLSRow(runDir, "invalid")
			row["manifest_path"] = manifestPath
			row["manifest_error"] = shortError(err)
			return row
		}
		return legacyLSRow(runDir, "missing")
	}
	if loaded.SchemaVersion != SchemaVersion || loaded.RunID != filepath.Base(runDir) {
		row := legacyLSRow(runDir, "invalid")
		row["manifest_path"] = manifestPath
		row["manifest_error"] = "invalid manifest"
		return row
	}
	state := triageStateForLS(runDir, jsonutil.StringValue(loaded.Triage["state"]))
	triageRow := map[string]any{"state": state}
	if value, ok := loaded.Triage["item_count"]; ok {
		triageRow["item_count"] = jsonutil.IntLike(value)
	}
	if value, ok := loaded.Triage["highest_severity"]; ok {
		triageRow["highest_severity"] = value
	}
	row := map[string]any{
		"run_id":          filepath.Base(runDir),
		"manifest_state":  "present",
		"type":            loaded.Type,
		"run_mode":        nilIfEmpty(loaded.RunMode),
		"single_provider": nilIfEmpty(loaded.SingleProvider),
		"facet_id":        nilIfEmpty(stringPtrValue(loaded.FacetID)),
		"decision_kind":   loaded.DecisionKind,
		"triage_state":    state,
		"triage":          triageRow,
		"finished_at":     loaded.FinishedAt,
		"manifest_path":   manifestPath,
	}
	if loaded.ExperimentID != nil {
		row["experiment_id"] = stringPtrValue(loaded.ExperimentID)
		row["task_id"] = stringPtrValue(loaded.TaskID)
		row["condition_id"] = stringPtrValue(loaded.ConditionID)
		row["run_kind"] = stringPtrValue(loaded.RunKind)
		if loaded.RepetitionIndex != nil {
			row["repetition_index"] = *loaded.RepetitionIndex
		} else {
			row["repetition_index"] = nil
		}
		row["slot_id"] = nilIfEmpty(stringPtrValue(loaded.SlotID))
		if loaded.SlotAttempt != nil {
			row["slot_attempt"] = *loaded.SlotAttempt
		} else {
			row["slot_attempt"] = nil
		}
	}
	if report := loaded.Artifacts["report"]; report != "" {
		row["report_path"] = filepath.Join(runDir, report)
	} else if fsutil.FileExists(filepath.Join(runDir, "report.md")) {
		row["report_path"] = filepath.Join(runDir, "report.md")
	}
	if loaded.SourceRunID != "" {
		row["source_run_id"] = loaded.SourceRunID
	}
	if loaded.RerunMode != "" {
		row["rerun_mode"] = loaded.RerunMode
	}
	if loaded.SelectedPatchProvider != "" {
		row["selected_patch_provider"] = loaded.SelectedPatchProvider
	}
	if loaded.Type == "escalation" {
		if loaded.SourceType != "" {
			row["source_type"] = loaded.SourceType
		}
		if loaded.EscalationMode != "" {
			row["escalation_mode"] = loaded.EscalationMode
		}
		if loaded.AddedProvider != nil {
			row["added_provider"] = loaded.AddedProvider
		}
	}
	return row
}

type lsManifest struct {
	SchemaVersion         int               `json:"schema_version"`
	RunID                 string            `json:"run_id"`
	Type                  string            `json:"type"`
	RunMode               string            `json:"run_mode"`
	SingleProvider        string            `json:"single_provider"`
	FacetID               *string           `json:"facet_id"`
	DecisionKind          string            `json:"decision_kind"`
	FinishedAt            string            `json:"finished_at"`
	Artifacts             map[string]string `json:"artifacts"`
	ExperimentID          *string           `json:"experiment_id"`
	TaskID                *string           `json:"task_id"`
	ConditionID           *string           `json:"condition_id"`
	RunKind               *string           `json:"run_kind"`
	RepetitionIndex       *int              `json:"repetition_index"`
	SlotID                *string           `json:"slot_id"`
	SlotAttempt           *int              `json:"slot_attempt"`
	SourceRunID           string            `json:"source_run_id"`
	SourceType            string            `json:"source_type"`
	EscalationMode        string            `json:"escalation_mode"`
	AddedProvider         any               `json:"added_provider"`
	RerunMode             string            `json:"rerun_mode"`
	SelectedPatchProvider string            `json:"selected_patch_provider"`
	Triage                map[string]any    `json:"triage"`
}

func readLSManifest(path string) (lsManifest, error) {
	var out lsManifest
	data, err := os.ReadFile(path)
	if err != nil {
		return out, err
	}
	if err := json.Unmarshal(data, &out); err != nil {
		return out, err
	}
	if out.Artifacts == nil {
		out.Artifacts = map[string]string{}
	}
	if out.Triage == nil {
		out.Triage = map[string]any{}
	}
	return out, nil
}

func triageStateForLS(runDir string, manifestState string) string {
	if manifestState == "" {
		manifestState = "no"
	}
	info, err := os.Stat(filepath.Join(runDir, "triage"))
	if err != nil || !info.IsDir() {
		return manifestState
	}
	state, _ := triage.DisplayStateDetail(runDir)
	if state != "" {
		return state
	}
	return manifestState
}

func triageSummary(runDir string, state string, staleInputs []string) map[string]any {
	triageDir := filepath.Join(runDir, "triage")
	status := readJSON(filepath.Join(triageDir, "status.json"))
	final := readJSON(filepath.Join(triageDir, "final.json"))
	summary := map[string]any{"state": state, "stale_inputs": staleInputs}
	if obj, ok := status.(map[string]any); ok {
		if statusText, ok := obj["status"].(string); ok {
			summary["attempt_status"] = statusText
		}
		if hashes, ok := obj["input_hashes"].(map[string]any); ok {
			summary["input_hashes"] = hashes
		}
	}
	if obj, ok := final.(map[string]any); ok {
		if _, ok := summary["input_hashes"]; !ok {
			if hashes, ok := obj["input_hashes"].(map[string]any); ok {
				summary["input_hashes"] = hashes
			}
		}
		items, _ := obj["items"].([]any)
		summary["item_count"] = len(items)
		summary["item_counts_by_classification"] = classificationCounts(items)
		summary["highest_severity"] = highestSeverity(items)
	}
	if filter, ok := triage.SourceFindingFilterSummary(runDir); ok {
		summary["source_finding_filter"] = filter
		if filter["included"] == 0 {
			summary["zero_selected"] = true
		}
	}
	return summary
}

func providerSummaries(meta map[string]any, decision map[string]any) map[string]any {
	resolved := nestedMap(meta, "resolved_models")
	resolvedProviders := nestedMap(resolved, "providers")
	statuses := nestedMap(decision, "provider_statuses")
	ids := map[string]bool{}
	for id := range resolvedProviders {
		ids[id] = true
	}
	for id := range statuses {
		ids[id] = true
	}
	keys := sortedKeys(ids)
	out := map[string]any{}
	for _, id := range keys {
		modelInfo, _ := resolvedProviders[id].(map[string]any)
		statusInfo, _ := statuses[id].(map[string]any)
		entry := map[string]any{
			"backend":        modelInfo["backend"],
			"model":          modelInfo["model"],
			"scope":          modelInfo["scope"],
			"effort":         modelInfo["effort"],
			"status":         statusInfo["status"],
			"compact_status": summary.CompactStatus(statusInfo["status"]),
			"wall_seconds":   statusInfo["wall_seconds"],
			"stdout_bytes":   jsonutil.FirstNonNil(statusInfo["stdout_bytes"], statusInfo["output_bytes"]),
			"stderr_bytes":   statusInfo["stderr_bytes"],
		}
		if value, ok := statusInfo["final_json_source"]; ok {
			entry["final_json_source"] = value
		}
		for _, key := range []string{"exit_code", "output_bytes", "stderr_truncated", "stdout_truncated", "stdout_observed_bytes", "stderr_observed_bytes", "failure_kind", "scope_enforcement", "stderr_path"} {
			if value, ok := statusInfo[key]; ok {
				entry[key] = value
			}
		}
		out[id] = compactNilMap(entry)
	}
	return out
}

func judgeSummary(meta map[string]any) map[string]any {
	judge := nestedMap(nestedMap(meta, "resolved_models"), "judge")
	out := map[string]any{}
	for _, key := range []string{"backend", "model", "effort"} {
		if value, ok := judge[key]; ok {
			out[key] = value
		}
	}
	return out
}

func reviewContextSummary(runDir string) map[string]any {
	context := readJSON(filepath.Join(runDir, "review-context.json"))
	if obj, ok := context.(map[string]any); ok {
		out := map[string]any{"present": true}
		for _, key := range []string{"base_ref", "base_commit", "head_commit", "git_root", "capture_cwd", "pathspec", "included_sections"} {
			if value, ok := obj[key]; ok {
				out[key] = value
			}
		}
		return out
	}
	return map[string]any{"present": false}
}

func isEscalationRun(meta map[string]any, decision map[string]any) bool {
	return jsonutil.StringValue(meta["type"]) == "escalation" || jsonutil.StringValue(decision["mode"]) == "escalation"
}

func addExperimentManifestFields(out map[string]any, meta map[string]any) {
	experiment, ok := meta["experiment"].(map[string]any)
	if !ok {
		return
	}
	if id := jsonutil.StringValue(experiment["id"]); id != "" {
		out["experiment_id"] = id
	}
	if taskID := jsonutil.StringValue(experiment["task_id"]); taskID != "" {
		out["task_id"] = taskID
	}
	if conditionID := jsonutil.StringValue(experiment["condition_id"]); conditionID != "" {
		out["condition_id"] = conditionID
	}
	if runKind := jsonutil.StringValue(experiment["run_kind"]); runKind != "" {
		out["run_kind"] = runKind
	}
	if repetitionIndex := jsonutil.IntValue(experiment["repetition_index"]); repetitionIndex > 0 {
		out["repetition_index"] = repetitionIndex
	}
	out["slot_id"] = nilIfEmpty(jsonutil.StringValue(experiment["slot_id"]))
	if slotAttempt := jsonutil.IntValue(experiment["slot_attempt"]); slotAttempt > 0 {
		out["slot_attempt"] = slotAttempt
	} else {
		out["slot_attempt"] = nil
	}
}

func addRerunManifestFields(out map[string]any, meta map[string]any, decision map[string]any) {
	if sourceRunID := jsonutil.StringValue(jsonutil.FirstNonNil(meta["source_run_id"], decision["source_run_id"])); sourceRunID != "" {
		out["source_run_id"] = sourceRunID
	}
	if rerunMode := jsonutil.StringValue(jsonutil.FirstNonNil(meta["rerun_mode"], decision["rerun_mode"])); rerunMode != "" {
		out["rerun_mode"] = rerunMode
	}
}

func addEscalationManifestFields(out map[string]any, meta map[string]any, decision map[string]any, workOrder map[string]any) {
	out["type"] = "escalation"
	out["source_type"] = jsonutil.FirstNonNil(meta["source_type"], decision["source_mode"], workOrder["type"])
	out["source_run_id"] = jsonutil.FirstNonNil(meta["source_run_id"], decision["source_run_id"])
	out["escalation_mode"] = jsonutil.FirstNonNil(meta["escalation_mode"], decision["escalation_mode"])
	out["added_provider"] = jsonutil.FirstNonNil(meta["added_provider"], decision["added_provider"])
	if sourceProviders, ok := decision["source_providers"]; ok {
		out["source_providers"] = sourceProviders
	}
	if escalation, ok := meta["escalation"].(map[string]any); ok {
		out["escalation"] = escalation
	}
}

func telemetrySummary(runDir string, workOrder map[string]any, meta map[string]any, decision map[string]any, manifest map[string]any, triageSummary map[string]any) map[string]any {
	runType := resolveRunType(workOrder, meta, decision)
	providerBackends := telemetryProviderBackends(workOrder, meta)
	families, diversity := telemetryProviderFamilies(providerBackends)
	judgeBackend := telemetryJudgeBackend(workOrder, meta)
	var judgeFamily any
	var judgeFamilyRelation any
	if judgeBackend != "" {
		judgeFamily = provider.FamilyForBackend(judgeBackend)
		judgeFamilyRelation = provider.JudgeFamilyRelation(judgeBackend, providerBackends)
	}
	winnerBackend := telemetryWinnerBackend(workOrder, meta, decision)
	var winnerFamily any
	if winnerBackend != "" {
		winnerFamily = provider.FamilyForBackend(winnerBackend)
	}
	orderMaps := decision["order_maps"]
	return map[string]any{
		"schema_version": TelemetrySchemaVersion,
		"source_run_id":  nilIfEmpty(jsonutil.StringValue(manifest["source_run_id"])),
		"rerun_mode":     nilIfEmpty(jsonutil.StringValue(manifest["rerun_mode"])),
		"route": map[string]any{
			"type":            nilIfEmpty(runType),
			"run_mode":        nilIfEmpty(resolveRunMode(runType, workOrder, meta, decision)),
			"facet_id":        manifest["facet_id"],
			"escalation_mode": nilIfEmpty(jsonutil.StringValue(manifest["escalation_mode"])),
			"source_type":     nilIfEmpty(jsonutil.StringValue(manifest["source_type"])),
		},
		"providers": map[string]any{
			"count":            len(providerBackends),
			"backends":         providerBackends,
			"families":         families,
			"family_diversity": diversity,
		},
		"judge": map[string]any{
			"backend":            nilIfEmpty(judgeBackend),
			"family":             judgeFamily,
			"family_relation":    judgeFamilyRelation,
			"ran":                truthy(decision["judge_ran"]),
			"completed":          truthy(decision["judge_completed"]),
			"selection_basis":    nilIfEmpty(jsonutil.StringValue(decision["selection_basis"])),
			"winner_backend":     nilIfEmpty(winnerBackend),
			"winner_family":      winnerFamily,
			"order_maps":         orderMaps,
			"judge_passes":       decision["judge_passes"],
			"position_swap_used": positionSwapUsed(orderMaps),
		},
		"artifacts": map[string]any{
			"prompt_trim_count":       promptTrimCount(decision),
			"output_truncation_count": outputTruncationCount(runDir, runType, decision),
		},
		"triage": telemetryTriageSummary(triageSummary),
	}
}

func telemetryProviderBackends(workOrder map[string]any, meta map[string]any) []string {
	fallback := workOrderProviderBackendsByID(workOrder)
	resolved := nestedMap(nestedMap(meta, "resolved_models"), "providers")
	if len(resolved) == 0 {
		return orderedWorkOrderProviderBackends(workOrder)
	}
	out := []string{}
	seen := map[string]bool{}
	for _, item := range jsonutil.ListValue(workOrder["providers"]) {
		obj, _ := item.(map[string]any)
		id := jsonutil.StringValue(obj["id"])
		if id == "" {
			continue
		}
		seen[id] = true
		modelInfo, _ := resolved[id].(map[string]any)
		backend := jsonutil.StringValue(modelInfo["backend"])
		if backend == "" {
			backend = fallback[id]
		}
		if backend != "" {
			out = append(out, backend)
		}
	}
	extraIDs := map[string]bool{}
	for id := range resolved {
		if !seen[id] {
			extraIDs[id] = true
		}
	}
	for _, id := range sortedKeys(extraIDs) {
		modelInfo, _ := resolved[id].(map[string]any)
		if backend := jsonutil.StringValue(modelInfo["backend"]); backend != "" {
			out = append(out, backend)
		}
	}
	return out
}

func workOrderProviderBackendsByID(workOrder map[string]any) map[string]string {
	out := map[string]string{}
	for _, item := range jsonutil.ListValue(workOrder["providers"]) {
		obj, _ := item.(map[string]any)
		id := jsonutil.StringValue(obj["id"])
		backend := jsonutil.StringValue(obj["backend"])
		if id != "" && backend != "" {
			out[id] = backend
		}
	}
	return out
}

func orderedWorkOrderProviderBackends(workOrder map[string]any) []string {
	out := []string{}
	for _, item := range jsonutil.ListValue(workOrder["providers"]) {
		obj, _ := item.(map[string]any)
		if backend := jsonutil.StringValue(obj["backend"]); backend != "" {
			out = append(out, backend)
		}
	}
	return out
}

func telemetryProviderFamilies(backends []string) ([]string, string) {
	if len(backends) == 0 {
		return []string{}, "unknown"
	}
	seen := map[string]bool{}
	unknown := false
	for _, backend := range backends {
		family := provider.FamilyForBackend(backend)
		if family == provider.ProviderFamilyUnknown {
			unknown = true
			continue
		}
		seen[family] = true
	}
	families := sortedKeys(seen)
	if unknown {
		return families, "unknown"
	}
	if len(families) == 1 {
		return families, "single"
	}
	return families, "mixed"
}

func telemetryJudgeBackend(workOrder map[string]any, meta map[string]any) string {
	judge := nestedMap(nestedMap(meta, "resolved_models"), "judge")
	if backend := jsonutil.StringValue(judge["backend"]); backend != "" {
		return backend
	}
	if judge, ok := workOrder["judge"].(map[string]any); ok {
		return jsonutil.StringValue(judge["backend"])
	}
	return ""
}

func telemetryWinnerBackend(workOrder map[string]any, meta map[string]any, decision map[string]any) string {
	winner := jsonutil.StringValue(decision["canonical_winner"])
	if winner == "" {
		return ""
	}
	return telemetryProviderBackendByID(workOrder, meta, winner)
}

func telemetryProviderBackendByID(workOrder map[string]any, meta map[string]any, providerID string) string {
	resolved := nestedMap(nestedMap(meta, "resolved_models"), "providers")
	if modelInfo, ok := resolved[providerID].(map[string]any); ok {
		if backend := jsonutil.StringValue(modelInfo["backend"]); backend != "" {
			return backend
		}
	}
	return workOrderProviderBackendsByID(workOrder)[providerID]
}

func positionSwapUsed(orderMaps any) bool {
	pass1 := orderMapStrings(orderMaps, "pass1")
	pass2 := orderMapStrings(orderMaps, "pass2")
	if len(pass1) == 0 || len(pass2) == 0 {
		return false
	}
	if len(pass1) != len(pass2) {
		return true
	}
	for key, value := range pass1 {
		if pass2[key] != value {
			return true
		}
	}
	return false
}

func orderMapStrings(orderMaps any, pass string) map[string]string {
	obj, ok := orderMaps.(map[string]any)
	if !ok {
		return nil
	}
	raw, ok := obj[pass]
	if !ok {
		return nil
	}
	switch typed := raw.(type) {
	case map[string]string:
		out := map[string]string{}
		for key, value := range typed {
			out[key] = value
		}
		return out
	case map[string]any:
		out := map[string]string{}
		for key, value := range typed {
			if text := jsonutil.StringValue(value); text != "" {
				out[key] = text
			}
		}
		return out
	default:
		return nil
	}
}

func promptTrimCount(decision map[string]any) int {
	promptTrim, _ := decision["prompt_trim"].(map[string]any)
	return len(jsonutil.ListValue(promptTrim["dropped"]))
}

func outputTruncationCount(runDir string, runType string, decision map[string]any) int {
	if runType == "build" {
		if count, ok := buildDiagnosticsOutputTruncationCount(runDir); ok {
			return count
		}
	}
	count := 0
	for _, status := range nestedMap(decision, "provider_statuses") {
		obj, _ := status.(map[string]any)
		if jsonutil.BoolValue(obj["stdout_truncated"]) {
			count++
		}
		if jsonutil.BoolValue(obj["stderr_truncated"]) {
			count++
		}
	}
	return count
}

func buildDiagnosticsOutputTruncationCount(runDir string) (int, bool) {
	obj, ok := readJSON(filepath.Join(runDir, "diagnostics.json")).(map[string]any)
	if !ok {
		return 0, false
	}
	if _, ok := obj["output_truncation"]; !ok {
		return 0, false
	}
	return len(jsonutil.ListValue(obj["output_truncation"])), true
}

func telemetryTriageSummary(triageSummary map[string]any) map[string]any {
	return map[string]any{
		"state":            triageSummary["state"],
		"item_count":       triageSummary["item_count"],
		"highest_severity": triageSummary["highest_severity"],
	}
}

func artifactPathsForType(runDir string, runType string) (map[string]any, error) {
	for _, relative := range RequiredArtifactsForType(runType) {
		if err := requireFile(filepath.Join(runDir, relative)); err != nil {
			return nil, err
		}
	}
	artifacts := map[string]any{
		"work_order": "work-order.json",
		"decision":   "decision.json",
		"report":     "report.md",
		"meta":       "meta.json",
	}
	if reviewPresent, missing := reviewContextSetStatus(runDir); reviewPresent {
		if len(missing) > 0 {
			return nil, fmt.Errorf("review context artifacts must be all-or-none; missing: %s", strings.Join(missing, ", "))
		}
		artifacts["source_work_order"] = "source-work-order.json"
		artifacts["review_context_md"] = "review-context.md"
		artifacts["review_context_json"] = "review-context.json"
	}
	if runType == "build" {
		artifacts["build_context"] = "build-context.json"
	}
	if fsutil.FileExists(filepath.Join(runDir, "source-run.json")) {
		artifacts["source_run"] = "source-run.json"
	}
	if fsutil.FileExists(filepath.Join(runDir, "escalation", "mode.json")) {
		artifacts["escalation_mode"] = "escalation/mode.json"
	}
	if fsutil.FileExists(filepath.Join(runDir, "escalation", "dispute-packet.json")) {
		artifacts["dispute_packet"] = "escalation/dispute-packet.json"
	}
	optional := map[string]string{
		"triage": "triage/triage.md",
	}
	for key, relative := range optional {
		if fsutil.FileExists(filepath.Join(runDir, relative)) {
			artifacts[key] = relative
		}
	}
	return artifacts, nil
}

func RequiredArtifactsForRun(runDir string) []string {
	runType, _ := RunTypeForRun(runDir)
	return RequiredArtifactsForType(runType)
}

func RequiredArtifactsForType(runType string) []string {
	required := append([]string(nil), RequiredArtifacts...)
	if runType == "build" {
		required = append(required, "build-context.json")
	}
	if runType == "escalation" {
		required = append(required, "source-run.json", "escalation/mode.json")
	}
	return required
}

func FingerprintArtifactPaths(runDir string) []string {
	return fingerprintArtifactPathsForType(runDir, runType(runDir))
}

func fingerprintArtifactPathsForType(runDir string, runType string) []string {
	seen := map[string]bool{}
	paths := []string{}
	add := func(relative string) {
		if relative == "" || seen[relative] {
			return
		}
		if !fsutil.FileExists(filepath.Join(runDir, relative)) {
			return
		}
		seen[relative] = true
		paths = append(paths, relative)
	}
	addFound := func(relative string) {
		if relative == "" || seen[relative] {
			return
		}
		seen[relative] = true
		paths = append(paths, relative)
	}
	for _, relative := range CoreFingerprintArtifacts {
		add(relative)
	}
	if runType == "build" {
		add("build-context.json")
	}
	addProviderEvidencePaths(runDir, addFound)
	addJudgeEvidencePaths(runDir, addFound)
	addEscalationEvidencePaths(runDir, addFound)
	if runType == "build" {
		addVerifyEvidencePaths(runDir, filepath.Join("baseline", "verify"), addFound)
		addBuildProviderEvidencePaths(runDir, addFound)
	}
	sort.Strings(paths)
	return paths
}

func artifactFingerprintsForType(runDir string, runType string) map[string]any {
	out := map[string]any{}
	for _, relative := range fingerprintArtifactPathsForType(runDir, runType) {
		path := filepath.Join(runDir, relative)
		size, sha, mtime, err := fingerprintFile(path)
		if err != nil {
			continue
		}
		out[relative] = map[string]any{"sha256": sha, "size_bytes": size, "mtime_ns": mtime}
	}
	return out
}

var providerEvidenceArtifactNames = []string{"prompt.txt", "status.json", "final.json", "failure.json", "last-message.txt", "stdout.txt", "stderr.txt"}
var buildProviderArtifactNames = []string{"workspace.json", "capture.json", "scope.json", "ineligible.json", "protected-paths.json", "changed-files.txt", "diff.patch", "diffstat.txt", "test-files.json", "benchmark-files.json"}
var verifyArtifactNames = []string{"status.json", "stdout.txt", "stderr.txt", "metric.json", "result.json"}

func addProviderEvidencePaths(runDir string, add func(string)) {
	providers, err := os.ReadDir(filepath.Join(runDir, "providers"))
	if err != nil {
		return
	}
	for _, provider := range providers {
		if !provider.IsDir() {
			continue
		}
		providerRel := filepath.Join("providers", provider.Name())
		addNamedFiles(runDir, providerRel, providerEvidenceArtifactNames, add)
	}
}

func addJudgeEvidencePaths(runDir string, add func(string)) {
	entries, err := os.ReadDir(filepath.Join(runDir, "judge"))
	if err != nil {
		return
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if matchesAny(name, "prompt*.txt", "status*.json", "*-status.json", "result*.json", "*-result.json", "last-message*.txt", "*-last-message.txt", "stdout*.txt", "*-stdout.txt", "stderr*.txt", "*-stderr.txt") {
			addDirEntryFile(runDir, "judge", entry, add)
		}
	}
}

func addEscalationEvidencePaths(runDir string, add func(string)) {
	entries, err := os.ReadDir(filepath.Join(runDir, "escalation"))
	if err != nil {
		return
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if matchesAny(name, "*.txt", "*.json") {
			addDirEntryFile(runDir, "escalation", entry, add)
		}
	}
}

func addBuildProviderEvidencePaths(runDir string, add func(string)) {
	providers, err := os.ReadDir(filepath.Join(runDir, "providers"))
	if err != nil {
		return
	}
	for _, provider := range providers {
		if !provider.IsDir() {
			continue
		}
		buildRel := filepath.Join("providers", provider.Name(), "build")
		addNamedFiles(runDir, buildRel, buildProviderArtifactNames, add)
		addVerifyEvidencePaths(runDir, filepath.Join(buildRel, "verify"), add)
	}
}

func addVerifyEvidencePaths(runDir string, verifyRel string, add func(string)) {
	resultRel := filepath.Join(verifyRel, "result.json")
	if fsutil.FileExists(filepath.Join(runDir, resultRel)) {
		add(resultRel)
	}
	verifiers, err := os.ReadDir(filepath.Join(runDir, verifyRel))
	if err != nil {
		return
	}
	for _, verifier := range verifiers {
		if !verifier.IsDir() {
			continue
		}
		addNamedFiles(runDir, filepath.Join(verifyRel, verifier.Name()), verifyArtifactNames, add)
	}
}

func addNamedFiles(runDir string, dirRel string, names []string, add func(string)) {
	entries, err := os.ReadDir(filepath.Join(runDir, dirRel))
	if err != nil {
		return
	}
	byName := map[string]os.DirEntry{}
	for _, entry := range entries {
		byName[entry.Name()] = entry
	}
	for _, name := range names {
		if entry, ok := byName[name]; ok && !entry.IsDir() {
			addDirEntryFile(runDir, dirRel, entry, add)
		}
	}
}

func addDirEntryFile(runDir string, dirRel string, entry os.DirEntry, add func(string)) {
	relative := filepath.Join(dirRel, entry.Name())
	if entry.Type()&os.ModeSymlink != 0 {
		if fsutil.FileExists(filepath.Join(runDir, relative)) {
			add(relative)
		}
		return
	}
	add(relative)
}

func matchesAny(name string, patterns ...string) bool {
	for _, pattern := range patterns {
		if ok, _ := filepath.Match(pattern, name); ok {
			return true
		}
	}
	return false
}

func fingerprintFile(path string) (int64, string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, "", 0, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return 0, "", 0, err
	}
	if info.IsDir() {
		return 0, "", 0, fmt.Errorf("%s is a directory", path)
	}
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil {
		return 0, "", 0, err
	}
	return size, hex.EncodeToString(hash.Sum(nil)), info.ModTime().UnixNano(), nil
}

func reviewContextSetStatus(runDir string) (bool, []string) {
	presentCount := 0
	missing := []string{}
	for _, relative := range ReviewContextArtifacts {
		if fsutil.FileExists(filepath.Join(runDir, relative)) {
			presentCount++
		} else {
			missing = append(missing, relative)
		}
	}
	if presentCount == 0 {
		return false, nil
	}
	if presentCount == len(ReviewContextArtifacts) {
		return true, nil
	}
	return true, missing
}

func legacyLSRow(runDir string, manifestState string) map[string]any {
	meta := readJSON(filepath.Join(runDir, "meta.json"))
	decision := readJSON(filepath.Join(runDir, "decision.json"))
	metaObj, _ := meta.(map[string]any)
	decisionObj, _ := decision.(map[string]any)
	facetID := ""
	if facet, ok := metaObj["facet"].(map[string]any); ok {
		facetID, _ = facet["id"].(string)
	}
	state := "no"
	if info, err := os.Stat(filepath.Join(runDir, "triage")); err == nil && info.IsDir() {
		state, _ = triage.DisplayStateDetail(runDir)
	}
	row := map[string]any{
		"run_id":          filepath.Base(runDir),
		"manifest_state":  manifestState,
		"type":            metaObj["type"],
		"run_mode":        nilIfEmpty(jsonutil.StringValue(decisionObj["run_mode"])),
		"single_provider": nilIfEmpty(jsonutil.StringValue(decisionObj["single_provider"])),
		"facet_id":        nilIfEmpty(facetID),
		"decision_kind":   decisionObj["decision_kind"],
		"triage_state":    state,
		"finished_at":     metaObj["finished_at"],
	}
	if fsutil.FileExists(filepath.Join(runDir, "report.md")) {
		row["report_path"] = filepath.Join(runDir, "report.md")
	}
	if value := jsonutil.StringValue(jsonutil.FirstNonNil(metaObj["source_run_id"], decisionObj["source_run_id"])); value != "" {
		row["source_run_id"] = value
	}
	if value := jsonutil.StringValue(jsonutil.FirstNonNil(metaObj["rerun_mode"], decisionObj["rerun_mode"])); value != "" {
		row["rerun_mode"] = value
	}
	if value := jsonutil.StringValue(decisionObj["selected_patch_provider"]); value != "" {
		row["selected_patch_provider"] = value
	}
	if jsonutil.StringValue(row["type"]) == "escalation" {
		if value := jsonutil.StringValue(jsonutil.FirstNonNil(metaObj["source_type"], decisionObj["source_mode"])); value != "" {
			row["source_type"] = value
		}
		if value := jsonutil.StringValue(jsonutil.FirstNonNil(metaObj["escalation_mode"], decisionObj["escalation_mode"])); value != "" {
			row["escalation_mode"] = value
		}
		if value := jsonutil.FirstNonNil(metaObj["added_provider"], decisionObj["added_provider"]); value != nil {
			row["added_provider"] = value
		}
	}
	return row
}

func classificationCounts(items []any) map[string]int {
	counts := map[string]int{}
	for _, name := range triage.Classifications {
		counts[name] = 0
	}
	for _, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		classification, _ := obj["classification"].(string)
		if _, ok := counts[classification]; ok {
			counts[classification]++
		}
	}
	return counts
}

func highestSeverity(items []any) any {
	if len(items) == 0 {
		return nil
	}
	seen := map[string]bool{}
	for _, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		classification, _ := obj["classification"].(string)
		if !actionableSeverityClassification(classification) {
			continue
		}
		severity, _ := obj["severity"].(string)
		seen[severity] = true
	}
	for _, severity := range []string{"high", "medium", "low", "none"} {
		if seen[severity] {
			return severity
		}
	}
	return nil
}

func actionableSeverityClassification(classification string) bool {
	return classification == "real_issue"
}

func runType(runDir string) string {
	runType, _ := RunTypeForRun(runDir)
	return runType
}

func runTypeFromWorkOrder(workOrder map[string]any) string {
	if _, ok := workOrder["type"]; !ok {
		return ""
	}
	return jsonutil.StringValue(workOrder["type"])
}

func resolveRunType(workOrder map[string]any, meta map[string]any, decision map[string]any) string {
	if isEscalationRun(meta, decision) {
		return "escalation"
	}
	if runType := runTypeFromWorkOrder(workOrder); runType != "" {
		return runType
	}
	return jsonutil.StringValue(meta["type"])
}

func resolveRunMode(runType string, workOrder map[string]any, meta map[string]any, decision map[string]any) string {
	if runType == "escalation" {
		return ""
	}
	for _, value := range []any{decision["run_mode"], meta["run_mode"], workOrder["run_mode"]} {
		if runMode := jsonutil.StringValue(value); runMode != "" {
			return runMode
		}
	}
	return workorder.RunModePairwise
}

func resolveSingleProvider(workOrder map[string]any, decision map[string]any, runMode string) string {
	if runMode != workorder.RunModeSingleProvider {
		return ""
	}
	if providerID := jsonutil.StringValue(decision["single_provider"]); providerID != "" {
		return providerID
	}
	providers := jsonutil.ListValue(workOrder["providers"])
	if len(providers) != 1 {
		return ""
	}
	providerObj, _ := providers[0].(map[string]any)
	return jsonutil.StringValue(providerObj["id"])
}

func RunTypeForRun(runDir string) (string, error) {
	values := map[string]string{}
	for _, relative := range []string{"work-order.json", "meta.json", "manifest.json", "decision.json"} {
		path := filepath.Join(runDir, relative)
		data, err := os.ReadFile(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return "", fmt.Errorf("%s run type source is unreadable: %w", path, err)
		}
		var obj map[string]any
		if err := json.Unmarshal(data, &obj); err != nil {
			return "", fmt.Errorf("%s run type source is invalid JSON: %w", path, err)
		}
		field := "type"
		value, ok := obj[field]
		if !ok && relative == "decision.json" {
			field = "mode"
			value, ok = obj[field]
		}
		if !ok {
			if relative == "work-order.json" || relative == "manifest.json" {
				return "", fmt.Errorf("%s run type source is missing type", path)
			}
			continue
		}
		runType, ok := value.(string)
		if !ok || runType == "" {
			return "", fmt.Errorf("%s run type source has non-string %s", path, field)
		}
		values[relative] = runType
		if runType == "escalation" {
			return runType, nil
		}
	}
	if runType := values["work-order.json"]; runType != "" {
		return runType, nil
	}
	for _, relative := range []string{"meta.json", "manifest.json", "decision.json"} {
		if runType := values[relative]; runType != "" {
			return runType, nil
		}
	}
	return "", nil
}

func readRequiredJSON(path string) (map[string]any, error) {
	value := readJSON(path)
	obj, ok := value.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("%s is required and must be a JSON object", path)
	}
	return obj, nil
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

func requireFile(path string) error {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return fmt.Errorf("%s is required for manifest", path)
	}
	return nil
}

func nestedMap(obj map[string]any, key string) map[string]any {
	if obj == nil {
		return map[string]any{}
	}
	nested, ok := obj[key].(map[string]any)
	if !ok {
		return map[string]any{}
	}
	return nested
}

func compactNilMap(obj map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range obj {
		if value != nil {
			out[key] = value
		}
	}
	return out
}

func sortedKeys(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func stringPtrValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func truthy(value any) bool {
	v, _ := value.(bool)
	return v
}

func nilIfEmpty(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func shortError(err error) string {
	text := err.Error()
	if len(text) > 240 {
		return text[:240]
	}
	return text
}
