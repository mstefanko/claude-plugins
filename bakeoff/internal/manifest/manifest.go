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
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
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
	state, staleInputs := triage.StateDetail(runDir)
	triageSummary := triageSummary(runDir, state, staleInputs)
	runType := runTypeFromWorkOrder(workOrder)
	artifacts, err := artifactPathsForType(runDir, runType)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"schema_version":        SchemaVersion,
		"run_id":                filepath.Base(runDir),
		"bakeoff_version":       buildinfo.Current().Version,
		"type":                  jsonutil.FirstNonNil(meta["type"], workOrder["type"]),
		"facet_id":              nilIfEmpty(facetID),
		"started_at":            meta["started_at"],
		"finished_at":           meta["finished_at"],
		"cwd":                   meta["cwd"],
		"decision_kind":         decision["decision_kind"],
		"canonical_winner":      decision["canonical_winner"],
		"judge_ran":             truthy(decision["judge_ran"]),
		"judge_attempted":       truthy(decision["judge_attempted"]),
		"judge_completed":       truthy(decision["judge_completed"]),
		"triage":                triageSummary,
		"providers":             providerSummaries(meta, decision),
		"judge":                 judgeSummary(meta),
		"review_context":        reviewContextSummary(runDir),
		"artifacts":             artifacts,
		"artifact_fingerprints": artifactFingerprintsForType(runDir, runType),
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
	state := triageStateForLS(runDir, loaded.Triage.State)
	row := map[string]any{
		"run_id":         filepath.Base(runDir),
		"manifest_state": "present",
		"type":           loaded.Type,
		"facet_id":       nilIfEmpty(stringPtrValue(loaded.FacetID)),
		"decision_kind":  loaded.DecisionKind,
		"triage_state":   state,
		"finished_at":    loaded.FinishedAt,
		"manifest_path":  manifestPath,
	}
	if report := loaded.Artifacts["report"]; report != "" {
		row["report_path"] = filepath.Join(runDir, report)
	} else if fsutil.FileExists(filepath.Join(runDir, "report.md")) {
		row["report_path"] = filepath.Join(runDir, "report.md")
	}
	return row
}

type lsManifest struct {
	SchemaVersion int               `json:"schema_version"`
	RunID         string            `json:"run_id"`
	Type          string            `json:"type"`
	FacetID       *string           `json:"facet_id"`
	DecisionKind  string            `json:"decision_kind"`
	FinishedAt    string            `json:"finished_at"`
	Artifacts     map[string]string `json:"artifacts"`
	Triage        struct {
		State string `json:"state"`
	} `json:"triage"`
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
	return out, nil
}

func triageStateForLS(runDir string, manifestState string) string {
	if manifestState == "" {
		manifestState = "no"
	}
	if manifestState == "no" {
		info, err := os.Stat(filepath.Join(runDir, "triage"))
		if err != nil || !info.IsDir() {
			return manifestState
		}
	}
	state, _ := triage.StateDetail(runDir)
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

var providerEvidenceArtifactNames = []string{"prompt.txt", "status.json", "final.json", "last-message.txt"}
var buildProviderArtifactNames = []string{"workspace.json", "capture.json", "ineligible.json", "changed-files.txt", "diff.patch", "diffstat.txt", "test-files.json", "benchmark-files.json"}
var verifyArtifactNames = []string{"status.json", "stdout.txt", "stderr.txt", "metric.json"}

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
		if matchesAny(name, "prompt*.txt", "status*.json", "result*.json", "last-message*.txt") {
			addDirEntryFile(runDir, "judge", entry, add)
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
	if fsutil.FileExists(filepath.Join(runDir, "report.md")) {
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

func RunTypeForRun(runDir string) (string, error) {
	for _, relative := range []string{"work-order.json", "meta.json", "manifest.json"} {
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
		value, ok := obj["type"]
		if !ok {
			if relative == "work-order.json" || relative == "manifest.json" {
				return "", fmt.Errorf("%s run type source is missing type", path)
			}
			continue
		}
		runType, ok := value.(string)
		if !ok || runType == "" {
			return "", fmt.Errorf("%s run type source has non-string type", path)
		}
		return runType, nil
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
