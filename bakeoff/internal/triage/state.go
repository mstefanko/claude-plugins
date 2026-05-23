package triage

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
)

const CodeReviewFacetID = "code-review"

var Classifications = []string{
	"real_issue",
	"false_positive",
	"plan_doc_drift",
	"product_decision",
	"needs_repro",
	"already_fixed",
	"evidence_gap",
}

func ComputeInputHashes(runDir string) (map[string]string, error) {
	decision, err := sha256File(filepath.Join(runDir, "decision.json"))
	if err != nil {
		return nil, err
	}
	report, err := sha256File(filepath.Join(runDir, "report.md"))
	if err != nil {
		return nil, err
	}
	workOrder, err := sha256File(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return nil, err
	}
	providerFailures, err := providerFailureArtifactsHash(runDir)
	if err != nil {
		return nil, err
	}
	out := map[string]string{
		"decision_sha256":          decision,
		"report_sha256":            report,
		"work_order_sha256":        workOrder,
		"provider_failures_sha256": providerFailures,
	}
	reviewArtifacts := map[string]string{
		"source_work_order_sha256":   "source-work-order.json",
		"review_context_md_sha256":   "review-context.md",
		"review_context_json_sha256": "review-context.json",
	}
	present := 0
	for _, relative := range reviewArtifacts {
		if fsutil.FileExists(filepath.Join(runDir, relative)) {
			present++
		}
	}
	if present > 0 {
		if present != len(reviewArtifacts) {
			return nil, fmt.Errorf("review context artifacts must be all-or-none")
		}
		for key, relative := range reviewArtifacts {
			sha, err := sha256File(filepath.Join(runDir, relative))
			if err != nil {
				return nil, err
			}
			out[key] = sha
		}
	}
	return out, nil
}

func State(runDir string) string {
	state, _ := StateDetail(runDir)
	return state
}

const ZeroSelectedMessage = "triage completed; no triageable report findings were selected."

func StateDetail(runDir string) (string, []string) {
	final := readJSON(filepath.Join(runDir, "triage", "final.json"))
	if final == nil || !fsutil.FileExists(filepath.Join(runDir, "triage", "triage.md")) {
		status := readJSON(filepath.Join(runDir, "triage", "status.json"))
		if obj, ok := status.(map[string]any); ok && obj["status"] == "dry_run" {
			return "dry_run", []string{}
		}
		return "no", []string{}
	}
	obj, ok := final.(map[string]any)
	if !ok {
		return "stale", []string{"input_hashes"}
	}
	hashes, ok := obj["input_hashes"].(map[string]any)
	if !ok {
		return "stale", []string{"input_hashes"}
	}
	current, err := ComputeInputHashes(runDir)
	if err != nil {
		return "stale", []string{"current inputs"}
	}
	changed := []string{}
	if jsonutil.StringValue(hashes["decision_sha256"]) != current["decision_sha256"] {
		changed = append(changed, "decision.json")
	}
	if jsonutil.StringValue(hashes["report_sha256"]) != current["report_sha256"] {
		changed = append(changed, "report.md")
	}
	if _, ok := hashes["work_order_sha256"]; ok && jsonutil.StringValue(hashes["work_order_sha256"]) != current["work_order_sha256"] {
		changed = append(changed, "work-order.json")
	}
	if _, ok := hashes["provider_failures_sha256"]; ok && jsonutil.StringValue(hashes["provider_failures_sha256"]) != current["provider_failures_sha256"] {
		changed = append(changed, "providers/*/failure.json")
	}
	for key, relative := range map[string]string{
		"source_work_order_sha256":   "source-work-order.json",
		"review_context_md_sha256":   "review-context.md",
		"review_context_json_sha256": "review-context.json",
	} {
		if _, ok := hashes[key]; ok && jsonutil.StringValue(hashes[key]) != current[key] {
			changed = append(changed, relative)
		}
	}
	if len(changed) > 0 {
		return "stale", changed
	}
	return "yes", []string{}
}

func providerFailureArtifactsHash(runDir string) (string, error) {
	paths, err := filepath.Glob(filepath.Join(runDir, "providers", "*", "failure.json"))
	if err != nil {
		return "", err
	}
	sort.Strings(paths)
	hash := sha256.New()
	for _, path := range paths {
		relative, err := filepath.Rel(runDir, path)
		if err != nil {
			return "", err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return "", err
		}
		hash.Write([]byte(filepath.ToSlash(relative)))
		hash.Write([]byte{0})
		hash.Write(data)
		hash.Write([]byte{0})
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func DisplayStateDetail(runDir string) (string, []string) {
	state, staleInputs := StateDetail(runDir)
	if state != "no" {
		return state, staleInputs
	}
	status := AttemptStatus(runDir)
	if status != "" && status != "ok" && status != "dry_run" {
		return "failed", []string{}
	}
	return state, staleInputs
}

func AttemptStatus(runDir string) string {
	status := readJSON(filepath.Join(runDir, "triage", "status.json"))
	if obj, ok := status.(map[string]any); ok {
		return jsonutil.StringValue(obj["status"])
	}
	return ""
}

func SourceFindingFilterSummary(runDir string) (map[string]int, bool) {
	triageDir := filepath.Join(runDir, "triage")
	for _, value := range []any{
		nestedValue(readJSON(filepath.Join(triageDir, "status.json")), "source_finding_filter"),
		nestedValue(readJSON(filepath.Join(triageDir, "final.json")), "source_finding_filter"),
		nestedValue(readJSON(filepath.Join(triageDir, "source_finding_filter.json")), "summary"),
	} {
		obj, ok := value.(map[string]any)
		if !ok || len(obj) == 0 {
			continue
		}
		return map[string]int{
			"included":               jsonutil.IntValue(obj["included"]),
			"skipped_non_actionable": jsonutil.IntValue(obj["skipped_non_actionable"]),
			"skipped_out_of_facet":   jsonutil.IntValue(obj["skipped_out_of_facet"]),
		}, true
	}
	return nil, false
}

func ZeroSelected(runDir string) bool {
	state, _ := StateDetail(runDir)
	if state != "yes" {
		return false
	}
	filter, ok := SourceFindingFilterSummary(runDir)
	return ok && filter["included"] == 0
}

func FacetID(workOrder map[string]any) string {
	facet, ok := workOrder["facet"].(map[string]any)
	if !ok {
		return ""
	}
	id, _ := facet["id"].(string)
	return id
}

func ShouldAutoTriage(workOrder map[string]any, decision map[string]any) string {
	if workOrder["type"] != "gather" || FacetID(workOrder) != CodeReviewFacetID {
		return ""
	}
	switch decision["decision_kind"] {
	case "both_failed", "single_provider_only", "tie":
		return ""
	default:
		return "code-review facet - verify actionable findings before fixing"
	}
}

func ShouldRecommendTriage(workOrder map[string]any, decision map[string]any, reportText string) string {
	if workOrder["type"] != "gather" || FacetID(workOrder) != CodeReviewFacetID {
		return ""
	}
	findings, _ := BuildFindingIndex(reportText)
	switch decision["decision_kind"] {
	case "single_provider_only":
		return "only one provider completed; inspect decision.json and verify before fixing"
	case "both_failed":
		return "both providers failed; inspect decision.json before acting"
	case "tie":
		return "no stable winner after judging; inspect decision.json and verify before fixing"
	}
	if len(findings) >= 5 {
		return fmt.Sprintf("gather report with %d findings - verify before fixing", len(findings))
	}
	if match := triageActionRE.FindString(triageRecommendationProse(reportText)); match != "" {
		return "report mentions " + strings.ToLower(match) + " - verify before fixing"
	}
	sourceFindings, _ := SelectTriageSourceFindings(findings, "")
	for _, finding := range sourceFindings {
		if finding["section"] == "Conflicts" {
			return "report contains conflicts - verify before fixing"
		}
	}
	return "code-review facet - verify actionable findings before fixing"
}

var findingIDRE = regexp.MustCompile(`^\s*-\s+\*\*(F-\d{3})\*\*\s+(.*)$`)

var actionableReportSections = map[string]bool{
	"Actionable Follow-ups":   true,
	"Findings":                true,
	"Comparison":              true,
	"Consensus Disagreements": true,
	"Strongest Material":      true,
	"Sub-Claim Divergences":   true,
	"Kept From Nonwinner":     true,
	"Additions From Loser":    true,
	"Conflicts":               true,
	"Unknowns":                true,
}

var skipReportBullets = map[string]bool{
	"None reported.":                      true,
	"No conflicts found.":                 true,
	"No provider completed successfully.": true,
}

func BuildFindingIndex(reportText string) ([]map[string]string, bool) {
	entries := []map[string]string{}
	section := ""
	for _, line := range strings.Split(reportText, "\n") {
		if strings.HasPrefix(line, "## ") {
			section = strings.TrimSpace(strings.TrimPrefix(line, "## "))
			continue
		}
		if strings.HasPrefix(line, "### ") {
			continue
		}
		match := findingIDRE.FindStringSubmatch(line)
		if len(match) == 3 {
			entry := map[string]string{"id": match[1], "text": strings.TrimSpace(match[2])}
			if section != "" {
				entry["section"] = section
			}
			entries = append(entries, entry)
		}
	}
	if len(entries) > 0 {
		return entries, false
	}
	section = ""
	for _, line := range strings.Split(reportText, "\n") {
		if strings.HasPrefix(line, "## ") {
			section = strings.TrimSpace(strings.TrimPrefix(line, "## "))
			continue
		}
		if strings.HasPrefix(line, "### ") || !actionableReportSections[section] || !strings.HasPrefix(line, "- ") {
			continue
		}
		text := strings.TrimSpace(strings.TrimPrefix(line, "- "))
		if !skipReportBullets[text] {
			entries = append(entries, map[string]string{"id": fmt.Sprintf("LEGACY-F-%03d", len(entries)+1), "text": text, "section": section})
		}
	}
	return entries, len(entries) > 0
}

var triageActionRE = regexp.MustCompile(`(?i)\b(?:bug|bugs|fix|fixes|fixed|gap|gaps|missing|invalid|schema_error|drift|incorrect|mismatch|misleading|ambiguous|unclear|incomplete|omits?|lacks?|stale|contradicts?|contradiction|confusing|unrecoverable)\b`)
var primaryExplanationActionRE = regexp.MustCompile(`(?i)\b(?:bug|bugs|fix|fixes|gap|gaps|missing coverage|missing test|missing tests|no test|no tests|untested|incorrect|mismatch|drift|risk|risks|risky|omits?|should)\b`)
var primaryExplanationDocDriftRE = regexp.MustCompile(`(?i)\b(?:README|docs?|documentation)\b.*\b(?:but|omits?|missing|drift|mismatch|incorrect)\b`)

func triageRecommendationProse(reportText string) string {
	lines := []string{}
	section := ""
	inFence := false
	inFindingBlock := false
	for _, line := range strings.Split(reportText, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "```") {
			inFence = !inFence
			continue
		}
		if inFence {
			continue
		}
		if strings.HasPrefix(line, "## ") {
			section = strings.TrimSpace(strings.TrimPrefix(line, "## "))
			inFindingBlock = false
			continue
		}
		if strings.HasPrefix(line, "### ") {
			inFindingBlock = false
			continue
		}
		if strings.HasPrefix(trimmed, "- **F-") || strings.HasPrefix(trimmed, "**F-") {
			inFindingBlock = true
			continue
		}
		if inFindingBlock {
			if trimmed == "" {
				inFindingBlock = false
				continue
			}
			if strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t") {
				continue
			}
			inFindingBlock = false
		}
		if section == "Strongest Material" || section == "Sub-Claim Divergences" || section == "Consensus Disagreements" {
			continue
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

func SelectTriageSourceFindings(findings []map[string]string, facetID string) ([]map[string]string, []map[string]string) {
	selected := []map[string]string{}
	skipped := []map[string]string{}
	for _, finding := range findings {
		section := finding["section"]
		text := finding["text"]
		switch {
		case section == "Out-of-Facet Claims":
			skipped = append(skipped, withSkipReason(finding, "out_of_facet"))
		case facetID != "" && section == "Findings":
			selected = append(selected, finding)
		case section == "Actionable Follow-ups" || section == "Conflicts" || section == "Unknowns":
			selected = append(selected, finding)
		case section == "Primary Explanation":
			if primaryExplanationActionRE.MatchString(text) || primaryExplanationDocDriftRE.MatchString(text) {
				selected = append(selected, finding)
			} else {
				skipped = append(skipped, withSkipReason(finding, "non_actionable"))
			}
		case triageActionRE.MatchString(text):
			selected = append(selected, finding)
		default:
			skipped = append(skipped, withSkipReason(finding, "non_actionable"))
		}
	}
	return selected, skipped
}

func SummarizeSourceFindingFilter(sourceFindings []map[string]string, skippedFindings []map[string]string) map[string]int {
	outOfFacet := 0
	for _, finding := range skippedFindings {
		if finding["skip_reason"] == "out_of_facet" {
			outOfFacet++
		}
	}
	return map[string]int{
		"included":               len(sourceFindings),
		"skipped_non_actionable": len(skippedFindings) - outOfFacet,
		"skipped_out_of_facet":   outOfFacet,
	}
}

func StaleInputsText(items []string) string {
	if len(items) == 0 {
		return ""
	}
	return " (" + strings.Join(items, ", ") + " changed)"
}

func sha256File(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("%s is required for triage", path)
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
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

func nestedValue(value any, key string) any {
	obj, ok := value.(map[string]any)
	if !ok {
		return nil
	}
	return obj[key]
}

func withSkipReason(finding map[string]string, reason string) map[string]string {
	copy := map[string]string{}
	for key, value := range finding {
		copy[key] = value
	}
	copy["skip_reason"] = reason
	return copy
}
