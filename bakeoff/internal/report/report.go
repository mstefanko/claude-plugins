package report

import (
	"fmt"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var actionableSections = map[string]bool{
	"Actionable Follow-ups":   true,
	"Findings":                true,
	"Comparison":              true,
	"Strongest Material":      true,
	"Consensus Disagreements": true,
	"Kept From Nonwinner":     true,
	"Additions From Loser":    true,
	"Conflicts":               true,
	"Unknowns":                true,
}

var skipBullets = map[string]bool{
	"None reported.":                      true,
	"No conflicts found.":                 true,
	"No provider completed successfully.": true,
}

func Render(wo *workorder.WorkOrder, decision map[string]any, workerResults map[string]map[string]any, judgeResults map[string]map[string]any) string {
	mode, _ := decision["mode"].(string)
	lines := []string{
		"# Bakeoff Report: " + wo.ID,
		"",
		"Mode: `" + mode + "`",
		"Decision: `" + stringValue(decision["decision_kind"]) + "`",
	}
	if wo.Facet != nil && strings.TrimSpace(wo.Facet.ID) != "" {
		lines = append(lines, "Facet: `"+wo.Facet.ID+"`")
		if wo.Facet.Focus != "" {
			lines = append(lines, "Facet Focus: "+wo.Facet.Focus)
		}
	}
	lines = append(lines, "")
	lines = append(lines, decisionAudit(decision)...)
	switch mode {
	case "gather":
		lines = append(lines, renderGather(wo, decision, workerResults, judgeResults)...)
	case "compare":
		lines = append(lines, renderCompare(decision, workerResults)...)
	case "analyze":
		lines = append(lines, renderAnalyze(decision, workerResults)...)
	default:
		lines = append(lines, "Unsupported mode.")
	}
	lines = append(lines, caveats(decision)...)
	return addFindingIDs(strings.TrimRight(strings.Join(lines, "\n"), "\n")) + "\n"
}

func decisionAudit(decision map[string]any) []string {
	lines := []string{"## Decision Audit", "", "- Judge ran: `" + strings.ToLower(fmt.Sprintf("%v", boolValue(decision["judge_ran"]))) + "`"}
	if winner := stringValue(decision["canonical_winner"]); winner != "" {
		lines = append(lines, "- Canonical winner: `"+winner+"`")
	}
	if tiebreak := stringValue(decision["spine_tiebreak"]); tiebreak != "" {
		lines = append(lines, "- Spine tiebreak: `"+tiebreak+"`")
	}
	if maps, ok := decision["order_maps"].(map[string]any); ok {
		keys := sortedMapKeys(maps)
		for _, name := range keys {
			mapping, _ := maps[name].(map[string]string)
			if mapping == nil {
				if raw, ok := maps[name].(map[string]any); ok {
					mapping = map[string]string{"A": stringValue(raw["A"]), "B": stringValue(raw["B"])}
				}
			}
			lines = append(lines, fmt.Sprintf("- %s: A=`%s`, B=`%s`", name, mapping["A"], mapping["B"]))
		}
	}
	if passes, ok := decision["judge_passes"].(map[string]any); ok && len(passes) > 0 {
		lines = append(lines, "- Judge passes:")
		for _, name := range sortedMapKeys(passes) {
			summary, _ := passes[name].(map[string]any)
			verdict := stringValue(summary["canonical_winner"])
			if verdict == "" {
				verdict = stringValue(summary["positional_winner"])
			}
			if verdict == "" {
				verdict = "none"
			}
			positional := stringValue(summary["positional_winner"])
			relation := ""
			if summary["relation"] != nil {
				relation = ", relation=`" + stringValue(summary["relation"]) + "`"
			}
			lines = append(lines, fmt.Sprintf("  - %s: A=`%s`, B=`%s`, winner=`%s` (positional `%s`%s)", name, stringValue(summary["A"]), stringValue(summary["B"]), verdict, positional, relation))
		}
	}
	if rationale := listValue(decision["judge_rationale"]); len(rationale) > 0 {
		lines = append(lines, "- Judge rationale:")
		passNames := []string{}
		if passes, ok := decision["judge_passes"].(map[string]any); ok {
			passNames = sortedMapKeys(passes)
		} else if maps, ok := decision["order_maps"].(map[string]any); ok {
			passNames = sortedMapKeys(maps)
		}
		for i, item := range rationale {
			prefix := ""
			if i < len(passNames) {
				prefix = passNames[i] + ": "
			}
			lines = append(lines, "  - "+prefix+fmt.Sprint(item))
		}
	}
	lines = append(lines, "", "## Provider Status", "")
	statuses, _ := decision["provider_statuses"].(map[string]any)
	for _, providerID := range sortedMapKeys(statuses) {
		status, _ := statuses[providerID].(map[string]any)
		stdoutBytes := firstNonNil(status["stdout_bytes"], status["output_bytes"], 0)
		detail := fmt.Sprintf("%vs, stdout %v bytes, stderr %v bytes", firstNonNil(status["wall_seconds"], 0), stdoutBytes, firstNonNil(status["stderr_bytes"], 0))
		if observed := numberValue(status["stdout_observed_bytes"]); observed != 0 && observed != numberValue(stdoutBytes) {
			detail += fmt.Sprintf(", stdout observed %v bytes", observed)
		}
		if observed := numberValue(status["stderr_observed_bytes"]); observed != 0 && observed != numberValue(status["stderr_bytes"]) {
			detail += fmt.Sprintf(", stderr observed %v bytes", observed)
		}
		if boolValue(status["stdout_truncated"]) {
			detail += ", stdout truncated"
		}
		if boolValue(status["stderr_truncated"]) {
			detail += ", stderr truncated"
		}
		suffix := ""
		if path := stringValue(status["stderr_path"]); path != "" {
			suffix = ", stderr: `" + path + "`"
		}
		lines = append(lines, fmt.Sprintf("- `%s`: `%s` (%s%s)", providerID, stringValue(status["status"]), detail, suffix))
		if scope, ok := status["scope_enforcement"].(map[string]any); ok {
			level := defaultString(scope["enforcement_level"], "unknown")
			requested := defaultString(scope["requested_scope"], "unknown")
			effective := defaultString(scope["effective_scope"], "unknown")
			fallback := ""
			if reason := stringValue(scope["fallback_reason"]); reason != "" {
				fallback = ", fallback: " + reason
			}
			lines = append(lines, fmt.Sprintf("  Scope: `%s` -> `%s` (%s%s)", requested, effective, level, fallback))
		}
	}
	lines = append(lines, "")
	return lines
}

func renderGather(wo *workorder.WorkOrder, decision map[string]any, workerResults map[string]map[string]any, judgeResults map[string]map[string]any) []string {
	switch decision["decision_kind"] {
	case "both_failed":
		return []string{"## Findings", "", "No provider completed successfully.", ""}
	case "single_provider_only":
		providerID := stringValue(decision["canonical_winner"])
		worker := finalJSONMap(workerResults[providerID])
		return append(append([]string{"## Findings", ""}, claimLines(listValue(worker["claims"]), providerID, false)...), unknowns(worker)...)
	}
	judge := judgeResults["pass1"]
	if judge == nil {
		judge = judgeResults["gather"]
	}
	merged := listValue(judge["merged_claims"])
	orderMap := map[string]string{}
	if maps, ok := decision["order_maps"].(map[string]any); ok {
		if raw, ok := maps["pass1"].(map[string]string); ok {
			orderMap = raw
		} else if raw, ok := maps["pass1"].(map[string]any); ok {
			orderMap = map[string]string{"A": stringValue(raw["A"]), "B": stringValue(raw["B"])}
		}
	}
	grouped := map[string][]any{}
	for _, item := range merged {
		claim, _ := item.(map[string]any)
		sources := []string{}
		for _, rawSource := range listValue(claim["sources"]) {
			source := fmt.Sprint(rawSource)
			if mapped := orderMap[source]; mapped != "" {
				source = mapped
			}
			sources = append(sources, source)
		}
		sort.Strings(sources)
		key := "unknown"
		if len(sources) > 0 {
			key = strings.Join(sources, "+")
		}
		copy := cloneMap(claim)
		sourceValues := make([]any, len(sources))
		for i, source := range sources {
			sourceValues[i] = source
		}
		copy["_source_providers"] = sourceValues
		grouped[key] = append(grouped[key], copy)
	}
	lines := []string{"## Findings", "", "Provider-set headings name the worker set that surfaced each claim. `single-source` means one worker surfaced it; `multi-source` means both workers surfaced materially similar claims.", ""}
	if wo.Facet != nil {
		lines = append(lines, "Corroboration describes worker overlap within the shared `"+wo.Facet.ID+"` facet; it is not proof of correctness.", "")
	}
	for _, key := range sortedGroupKeys(grouped) {
		lines = append(lines, "### "+key)
		lines = append(lines, claimLines(grouped[key], "", true)...)
		lines = append(lines, "")
	}
	lines = append(lines, "## Conflicts", "")
	lines = append(lines, conflictLines(listValue(judge["conflicts"]))...)
	lines = append(lines, "", "## Unknowns", "")
	unknownsUnion := listValue(judge["unknowns_union"])
	if len(unknownsUnion) == 0 {
		lines = append(lines, "- None reported.")
	} else {
		for _, item := range unknownsUnion {
			lines = append(lines, "- "+fmt.Sprint(item))
		}
	}
	lines = append(lines, "")
	if outOfFacet := listValue(judge["out_of_facet_claims"]); len(outOfFacet) > 0 {
		lines = append(lines, "## Out-of-Facet Claims", "", "These claims are observability-only and are excluded from triage source selection.", "")
		lines = append(lines, outOfFacetLines(outOfFacet)...)
		lines = append(lines, "")
	}
	return lines
}

func renderCompare(decision map[string]any, workerResults map[string]map[string]any) []string {
	lines := []string{"## Comparison", ""}
	kind := stringValue(decision["decision_kind"])
	winner := stringValue(decision["canonical_winner"])
	switch {
	case kind == "pick_winner" && winner != "":
		final := finalJSONMap(workerResults[winner])
		lines = append(lines, "Winner: `"+winner+"`")
		if position := stringValue(final["position"]); position != "" {
			lines = append(lines, "Position: "+position)
		}
		lines = append(lines, "")
		lines = append(lines, claimLines(listValue(final["claims"]), winner, false)...)
	case kind == "consensus":
		lines = append(lines, "The judge found both providers reached the same position.", "", "### Strongest Material", "")
		lines = append(lines, genericItemLines(listValue(decision["consensus_strongest"]))...)
		lines = append(lines, "", "### Consensus Disagreements", "")
		lines = append(lines, genericItemLines(listValue(decision["consensus_disagreements"]))...)
	case kind == "single_provider_only" && winner != "":
		final := finalJSONMap(workerResults[winner])
		lines = append(lines, "No comparison possible - surfacing the single completed result.")
		if position := stringValue(final["position"]); position != "" {
			lines = append(lines, "Position: "+position)
		}
		lines = append(lines, "")
		lines = append(lines, claimLines(listValue(final["claims"]), winner, false)...)
	case kind == "both_failed":
		lines = append(lines, "No provider completed successfully.")
	default:
		lines = append(lines, "No stable winner after position swap. Human decision required.")
	}
	if kept := listValue(decision["kept_from_nonwinner"]); len(kept) > 0 {
		lines = append(lines, "", "## Kept From Nonwinner", "")
		lines = append(lines, genericItemLines(kept)...)
	}
	lines = append(lines, "")
	return lines
}

func renderAnalyze(decision map[string]any, workerResults map[string]map[string]any) []string {
	lines := []string{"## Primary Explanation", ""}
	winner := stringValue(decision["canonical_winner"])
	if decision["decision_kind"] == "both_failed" {
		return append(lines, "No provider completed successfully.", "")
	}
	if winner == "" {
		return append(lines, "No stable spine was selected. Human decision required.", "")
	}
	final := finalJSONMap(workerResults[winner])
	verdicts := map[string]map[string]any{}
	for _, item := range listValue(decision["claim_verdicts"]) {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		verdicts[stringValue(obj["claim_id"])] = obj
	}
	claims := listValue(final["claims"])
	for _, item := range claims {
		claim, _ := item.(map[string]any)
		verdict := verdicts[stringValue(claim["id"])]
		marker := stringValue(verdict["loser_position"])
		note := ""
		if marker != "" {
			note = " [" + marker + ": " + stringValue(verdict["loser_note"]) + "]"
		}
		evidence := joinList(claim["evidence"], ", ")
		lines = append(lines, fmt.Sprintf("- **%s** %s%s", defaultString(claim["id"], "?"), stringValue(claim["claim"]), note))
		if evidence != "" {
			lines = append(lines, "  Evidence: "+evidence)
		}
	}
	if len(claims) == 0 {
		lines = append(lines, "No claims were available to render.")
	}
	if followups := listValue(decision["actionable_followups"]); len(followups) > 0 {
		lines = append(lines, "", "## Actionable Follow-ups", "")
		lines = append(lines, genericItemLines(followups)...)
	}
	if additions := listValue(decision["additions_from_loser"]); len(additions) > 0 {
		lines = append(lines, "", "## Additions From Loser", "")
		lines = append(lines, genericItemLines(additions)...)
	}
	lines = append(lines, "")
	return lines
}

func claimLines(claims []any, source string, showCorroboration bool) []string {
	if len(claims) == 0 {
		return []string{"- None reported."}
	}
	lines := []string{}
	for _, item := range claims {
		claim, _ := item.(map[string]any)
		confidence := defaultString(claim["confidence"], "unknown")
		details := []string{}
		if source != "" {
			details = append(details, "source `"+source+"`")
		}
		details = append(details, "model confidence `"+confidence+"`")
		if showCorroboration {
			sourceProviders := []string{}
			for _, raw := range listValue(claim["_source_providers"]) {
				sourceProviders = append(sourceProviders, fmt.Sprint(raw))
			}
			sort.Strings(sourceProviders)
			if len(sourceProviders) > 0 {
				corroboration := "single-source"
				if len(unique(sourceProviders)) > 1 {
					corroboration = "multi-source"
				}
				details = append(details, "corroboration `"+corroboration+"`", "sources `"+strings.Join(unique(sourceProviders), "+")+"`")
			} else {
				details = append(details, "corroboration `unknown`")
			}
		}
		lines = append(lines, fmt.Sprintf("- %s (%s)", stringValue(claim["claim"]), strings.Join(details, ", ")))
		if evidence := joinList(claim["evidence"], ", "); evidence != "" {
			lines = append(lines, "  Evidence: "+evidence)
		}
	}
	return lines
}

func conflictLines(conflicts []any) []string {
	if len(conflicts) == 0 {
		return []string{"- No conflicts found."}
	}
	return genericItemLines(conflicts)
}

func unknowns(worker map[string]any) []string {
	lines := []string{"", "## Unknowns", ""}
	items := listValue(worker["unknowns"])
	if len(items) == 0 {
		lines = append(lines, "- None reported.")
	} else {
		for _, item := range items {
			lines = append(lines, "- "+fmt.Sprint(item))
		}
	}
	lines = append(lines, "")
	return lines
}

func genericItemLines(items []any) []string {
	if len(items) == 0 {
		return []string{"- None reported."}
	}
	lines := []string{}
	for _, item := range items {
		if text, ok := item.(string); ok {
			lines = append(lines, "- "+text)
			continue
		}
		if obj, ok := item.(map[string]any); ok {
			claim := firstString(obj["claim"], obj["description"], obj["loser_note"], fmt.Sprint(obj))
			lines = append(lines, "- "+claim)
			if evidence := joinList(obj["evidence"], ", "); evidence != "" {
				lines = append(lines, "  Evidence: "+evidence)
			}
			if source := stringValue(obj["source_provider"]); source != "" {
				lines = append(lines, "  Source: `"+source+"`")
			}
			continue
		}
		lines = append(lines, "- "+fmt.Sprint(item))
	}
	return lines
}

func outOfFacetLines(items []any) []string {
	if len(items) == 0 {
		return []string{"- None reported."}
	}
	lines := []string{}
	for _, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			lines = append(lines, "- "+fmt.Sprint(item))
			continue
		}
		claim := firstString(obj["claim"], obj["description"], fmt.Sprint(obj))
		details := []string{}
		if sources := listValue(firstNonNil(obj["sources"], obj["source_labels"])); len(sources) > 0 {
			parts := []string{}
			for _, source := range sources {
				parts = append(parts, fmt.Sprint(source))
			}
			details = append(details, "sources `"+strings.Join(parts, "+")+"`")
		}
		if reason := stringValue(obj["reason"]); reason != "" {
			details = append(details, "reason `"+reason+"`")
		}
		suffix := ""
		if len(details) > 0 {
			suffix = " (" + strings.Join(details, ", ") + ")"
		}
		lines = append(lines, "- "+claim+suffix)
		if evidence := joinList(obj["evidence"], ", "); evidence != "" {
			lines = append(lines, "  Evidence: "+evidence)
		}
	}
	return lines
}

func caveats(decision map[string]any) []string {
	items := listValue(decision["caveats"])
	if len(items) == 0 {
		return nil
	}
	lines := []string{"## Caveats", ""}
	for _, item := range items {
		lines = append(lines, "- "+fmt.Sprint(item))
	}
	lines = append(lines, "")
	return lines
}

func addFindingIDs(text string) string {
	lines := []string{}
	section := ""
	nextID := 1
	for _, line := range strings.Split(text, "\n") {
		if strings.HasPrefix(line, "## ") {
			section = strings.TrimSpace(strings.TrimPrefix(line, "## "))
			lines = append(lines, line)
			continue
		}
		if actionableSections[section] && strings.HasPrefix(line, "- ") && !strings.HasPrefix(line, "- **F-") {
			body := strings.TrimSpace(strings.TrimPrefix(line, "- "))
			if !skipBullets[body] {
				line = fmt.Sprintf("- **F-%03d** %s", nextID, body)
				nextID++
			}
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

func finalJSONMap(result map[string]any) map[string]any {
	final, _ := result["final_json"].(map[string]any)
	if final == nil {
		return map[string]any{}
	}
	return final
}

func sortedMapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func sortedGroupKeys(m map[string][]any) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func cloneMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}

func listValue(value any) []any {
	items, ok := value.([]any)
	if ok {
		return items
	}
	stringsValue, ok := value.([]string)
	if ok {
		out := make([]any, len(stringsValue))
		for i, item := range stringsValue {
			out[i] = item
		}
		return out
	}
	return nil
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	text, ok := value.(string)
	if ok {
		return text
	}
	return fmt.Sprint(value)
}

func defaultString(value any, fallback string) string {
	if text := stringValue(value); text != "" {
		return text
	}
	return fallback
}

func boolValue(value any) bool {
	v, _ := value.(bool)
	return v
}

func firstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func numberValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	default:
		return 0
	}
}

func joinList(value any, sep string) string {
	items := listValue(value)
	parts := []string{}
	for _, item := range items {
		parts = append(parts, fmt.Sprint(item))
	}
	return strings.Join(parts, sep)
}

func firstString(values ...any) string {
	for _, value := range values {
		if text := stringValue(value); text != "" {
			return text
		}
	}
	return ""
}

func unique(items []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, item := range items {
		if !seen[item] {
			seen[item] = true
			out = append(out, item)
		}
	}
	return out
}
