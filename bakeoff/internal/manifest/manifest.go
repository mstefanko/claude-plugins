package manifest

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const SchemaVersion = 1

var CoreFingerprintArtifacts = []string{
	"work-order.json",
	"source-work-order.json",
	"review-context.md",
	"review-context.json",
	"decision.json",
	"meta.json",
	"report.md",
	"triage/status.json",
	"triage/final.json",
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

	facetID := ""
	if facet, ok := meta["facet"].(map[string]any); ok {
		facetID, _ = facet["id"].(string)
	}
	if facetID == "" {
		if facet, ok := workOrder["facet"].(map[string]any); ok {
			facetID, _ = facet["id"].(string)
		}
	}
	state, staleInputs := triage.StateDetail(runDir)
	triageSummary := triageSummary(runDir, state, staleInputs)
	artifacts, err := artifactPaths(runDir)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"schema_version":        SchemaVersion,
		"run_id":                filepath.Base(runDir),
		"bakeoff_version":       buildinfo.Current().Version,
		"type":                  firstNonNil(meta["type"], workOrder["type"]),
		"facet_id":              nilIfEmpty(facetID),
		"started_at":            meta["started_at"],
		"finished_at":           meta["finished_at"],
		"cwd":                   meta["cwd"],
		"decision_kind":         decision["decision_kind"],
		"canonical_winner":      decision["canonical_winner"],
		"judge_ran":             truthy(decision["judge_ran"]),
		"triage":                triageSummary,
		"providers":             providerSummaries(meta, decision),
		"judge":                 judgeSummary(meta),
		"review_context":        reviewContextSummary(runDir),
		"artifacts":             artifacts,
		"artifact_fingerprints": artifactFingerprints(runDir),
	}, nil
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
	if _, err := os.Stat(manifestPath); err != nil {
		return legacyLSRow(runDir, "missing")
	}
	loaded, err := readRequiredJSON(manifestPath)
	if err != nil || intValue(loaded["schema_version"]) != SchemaVersion || loaded["run_id"] != filepath.Base(runDir) {
		row := legacyLSRow(runDir, "invalid")
		row["manifest_path"] = manifestPath
		if err != nil {
			row["manifest_error"] = shortError(err)
		} else {
			row["manifest_error"] = "invalid manifest"
		}
		return row
	}
	artifacts, _ := loaded["artifacts"].(map[string]any)
	state, _ := triage.StateDetail(runDir)
	if state == "" {
		state = manifestTriageState(loaded)
	}
	row := map[string]any{
		"run_id":         filepath.Base(runDir),
		"manifest_state": "present",
		"type":           loaded["type"],
		"facet_id":       loaded["facet_id"],
		"decision_kind":  loaded["decision_kind"],
		"triage_state":   state,
		"finished_at":    loaded["finished_at"],
		"manifest_path":  manifestPath,
	}
	if report, ok := stringFromMap(artifacts, "report"); ok {
		row["report_path"] = filepath.Join(runDir, report)
	} else if fileExists(filepath.Join(runDir, "report.md")) {
		row["report_path"] = filepath.Join(runDir, "report.md")
	}
	return row
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
		summary := map[string]any{
			"backend":      modelInfo["backend"],
			"model":        modelInfo["model"],
			"scope":        modelInfo["scope"],
			"effort":       modelInfo["effort"],
			"status":       statusInfo["status"],
			"wall_seconds": statusInfo["wall_seconds"],
			"stdout_bytes": firstNonNil(statusInfo["stdout_bytes"], statusInfo["output_bytes"]),
			"stderr_bytes": statusInfo["stderr_bytes"],
		}
		if value, ok := statusInfo["final_json_source"]; ok {
			summary["final_json_source"] = value
		}
		out[id] = compactNilMap(summary)
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

func artifactPaths(runDir string) (map[string]any, error) {
	for _, relative := range RequiredArtifacts {
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
	optional := map[string]string{
		"triage": "triage/triage.md",
	}
	for key, relative := range optional {
		if fileExists(filepath.Join(runDir, relative)) {
			artifacts[key] = relative
		}
	}
	return artifacts, nil
}

func FingerprintArtifactPaths(runDir string) []string {
	seen := map[string]bool{}
	paths := []string{}
	add := func(relative string) {
		if relative == "" || seen[relative] {
			return
		}
		if !fileExists(filepath.Join(runDir, relative)) {
			return
		}
		seen[relative] = true
		paths = append(paths, relative)
	}
	for _, relative := range CoreFingerprintArtifacts {
		add(relative)
	}
	for _, pattern := range []string{
		"providers/*/prompt.txt",
		"providers/*/status.json",
		"providers/*/final.json",
		"providers/*/last-message.txt",
		"judge/prompt*.txt",
		"judge/status*.json",
		"judge/result*.json",
		"judge/last-message*.txt",
	} {
		matches, _ := filepath.Glob(filepath.Join(runDir, pattern))
		sort.Strings(matches)
		for _, path := range matches {
			relative, err := filepath.Rel(runDir, path)
			if err == nil {
				add(relative)
			}
		}
	}
	sort.Strings(paths)
	return paths
}

func artifactFingerprints(runDir string) map[string]any {
	out := map[string]any{}
	for _, relative := range FingerprintArtifactPaths(runDir) {
		path := filepath.Join(runDir, relative)
		size, sha, err := workorder.FileFingerprint(path)
		if err != nil {
			continue
		}
		info, _ := os.Stat(path)
		mtime := int64(0)
		if info != nil {
			mtime = info.ModTime().UnixNano()
		}
		out[relative] = map[string]any{"sha256": sha, "size_bytes": size, "mtime_ns": mtime}
	}
	return out
}

func reviewContextSetStatus(runDir string) (bool, []string) {
	presentCount := 0
	missing := []string{}
	for _, relative := range ReviewContextArtifacts {
		if fileExists(filepath.Join(runDir, relative)) {
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
	state, _ := triage.StateDetail(runDir)
	row := map[string]any{
		"run_id":         filepath.Base(runDir),
		"manifest_state": manifestState,
		"type":           metaObj["type"],
		"facet_id":       nilIfEmpty(facetID),
		"decision_kind":  decisionObj["decision_kind"],
		"triage_state":   state,
		"finished_at":    metaObj["finished_at"],
	}
	if fileExists(filepath.Join(runDir, "report.md")) {
		row["report_path"] = filepath.Join(runDir, "report.md")
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

func manifestTriageState(manifest map[string]any) string {
	triageObj, ok := manifest["triage"].(map[string]any)
	if !ok {
		return ""
	}
	state, _ := triageObj["state"].(string)
	return state
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

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
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

func stringFromMap(obj map[string]any, key string) (string, bool) {
	if obj == nil {
		return "", false
	}
	value, ok := obj[key].(string)
	return value, ok
}

func intValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case float64:
		return int(typed)
	default:
		return 0
	}
}

func truthy(value any) bool {
	v, _ := value.(bool)
	return v
}

func firstNonNil(left any, right any) any {
	if left != nil {
		return left
	}
	return right
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
