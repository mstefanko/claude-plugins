package report

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var actionableSections = map[string]bool{
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

var skipBullets = map[string]bool{
	"None reported.":                      true,
	"No conflicts found.":                 true,
	"No provider completed successfully.": true,
}

type RenderOptions struct {
	RunID  string
	OutDir string
	RunDir string
}

type EscalationRenderOptions struct {
	RunID        string
	OutDir       string
	RunDir       string
	SourceRunID  string
	SourceRunDir string
}

func Render(wo *workorder.WorkOrder, decision map[string]any, workerResults map[string]map[string]any, judgeResults map[string]map[string]any, opts RenderOptions) string {
	mode, _ := decision["mode"].(string)
	lines := []string{
		"# Bakeoff Report: " + wo.ID,
		"",
	}
	lines = append(lines, reportGlossary()...)
	lines = append(lines, renderJudgeFailureStatus(decision, opts)...)
	lines = append(lines, renderOutcome(wo, decision, workerResults, opts)...)
	lines = append(lines, renderSelectorConfidence(decision)...)
	lines = append(lines, decisionAudit(decision)...)
	lines = append(lines, renderProviderStatusTable(decision)...)
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

func RenderEscalation(wo *workorder.WorkOrder, decision map[string]any, addedFinal map[string]any, disputePacket map[string]any, opts EscalationRenderOptions) string {
	lines := []string{
		"# Bakeoff Escalation Report: " + wo.ID,
		"",
	}
	lines = append(lines, reportGlossary()...)
	lines = append(lines, renderEscalationAnswer(decision, opts)...)
	lines = append(lines, "## Source Run", "")
	lines = append(lines, "- Run: `"+opts.SourceRunID+"`")
	if opts.SourceRunDir != "" {
		lines = append(lines, "- Directory: `"+opts.SourceRunDir+"`")
	}
	lines = append(lines, "- Source mode: `"+jsonutil.StringValue(decision["source_mode"])+"`")
	if sourceDecision, ok := decision["source_decision"].(map[string]any); ok {
		lines = append(lines, "- Source decision: `"+jsonutil.StringValue(sourceDecision["decision_kind"])+"`")
		if winner := jsonutil.StringValue(sourceDecision["canonical_winner"]); winner != "" {
			lines = append(lines, "- Source winner: `"+winner+"`")
		}
	}
	lines = append(lines, "")
	lines = append(lines, "## Escalation", "")
	lines = append(lines, "- Mode: `"+jsonutil.StringValue(decision["escalation_mode"])+"` ("+escalationModeLabel(jsonutil.StringValue(decision["escalation_mode"]))+")")
	lines = append(lines, "- Added provider: `"+jsonutil.StringValue(decision["added_provider"])+"`")
	lines = append(lines, "- Source providers: `"+joinList(decision["source_providers"], "`, `")+"`")
	lines = append(lines, escalationAdvisoryImpactLines(
		jsonutil.StringValue(decision["escalation_mode"]),
		jsonutil.StringValue(decision["selection_basis"]),
	)...)
	lines = append(lines, "")
	lines = append(lines, renderEscalationPayload(decision, addedFinal, disputePacket)...)
	lines = append(lines, caveats(decision)...)
	return addFindingIDs(strings.TrimRight(strings.Join(lines, "\n"), "\n")) + "\n"
}

func renderEscalationAnswer(decision map[string]any, opts EscalationRenderOptions) []string {
	kind := jsonutil.StringValue(decision["decision_kind"])
	headline := firstString(nestedString(decision, "synthesis", "headline"), nestedString(decision, "assessment", "headline"), nestedString(decision, "dispute", "headline"))
	if headline == "" {
		headline = kind
	}
	effect := firstString(nestedString(decision, "synthesis", "source_decision_effect"), nestedString(decision, "assessment", "source_decision_effect"), nestedString(decision, "dispute", "source_decision_effect"))
	confidence := firstString(nestedString(decision, "synthesis", "confidence"), nestedString(decision, "assessment", "confidence"), nestedString(decision, "dispute", "confidence"))
	lines := []string{
		"## Answer",
		"",
		"- Result: `" + kind + "` - " + headline,
	}
	if gloss := statusGloss(kind); gloss != "" {
		lines = append(lines, "- Result meaning: "+gloss)
	}
	if effect != "" {
		lines = append(lines, "- Source decision effect: `"+effect+"`")
	}
	if confidence != "" {
		lines = append(lines, selectorStrengthLine(confidence))
	}
	if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
		lines = append(lines, "- Escalation winner: `"+winner+"`")
	} else {
		lines = append(lines, "- Escalation winner: none")
	}
	lines = append(lines, "- What changed: "+firstNonEmptyListSummary(
		nestedList(decision, "synthesis", "what_changed"),
		nestedList(decision, "synthesis", "material_new_evidence"),
		nestedList(decision, "assessment", "missed_material"),
		nestedList(decision, "assessment", "material_errors"),
		nestedList(decision, "dispute", "new_evidence"),
		nestedList(decision, "union", "new_or_changed_material"),
	))
	lines = append(lines, "- Still unresolved: "+firstNonEmptyListSummary(
		nestedList(decision, "synthesis", "unresolved_questions"),
		nestedList(decision, "dispute", "unresolved_points"),
		nestedList(decision, "union", "unknowns_union"),
	))
	if action := firstString(nestedString(decision, "synthesis", "recommended_action"), nestedString(decision, "assessment", "recommended_action"), nestedString(decision, "dispute", "recommended_action")); action != "" {
		lines = append(lines, "- Recommended action: `"+action+"`")
	}
	if opts.RunID != "" {
		lines = append(lines, "- "+compactNextStep(opts.RunID, opts.OutDir))
	}
	lines = append(lines, "")
	return lines
}

func renderEscalationPayload(decision map[string]any, addedFinal map[string]any, disputePacket map[string]any) []string {
	mode := jsonutil.StringValue(decision["escalation_mode"])
	switch mode {
	case "witness":
		return renderWitnessAssessment(decision)
	case "dispute":
		return renderDisputeAssessment(decision, disputePacket)
	default:
		if jsonutil.StringValue(decision["source_mode"]) == "gather" {
			return renderEscalationUnion(decision)
		}
		return renderSynthesis(decision, addedFinal)
	}
}

func renderWitnessAssessment(decision map[string]any) []string {
	assessment, _ := decision["assessment"].(map[string]any)
	lines := []string{"## Witness Assessment", "", advisoryOnlyNote(), ""}
	lines = append(lines, "- Assessment: `"+jsonutil.StringValue(assessment["assessment"])+"`")
	lines = append(lines, "- Would change outcome: `"+strings.ToLower(fmt.Sprintf("%v", jsonutil.BoolValue(assessment["would_change_outcome"])))+"`")
	lines = append(lines, "", "### Material Errors", "")
	lines = append(lines, witnessAssessmentItemLines(jsonutil.ListValue(assessment["material_errors"]))...)
	lines = append(lines, "", "### Missed Material", "")
	lines = append(lines, witnessAssessmentItemLines(jsonutil.ListValue(assessment["missed_material"]))...)
	lines = append(lines, "", "### Triage Concerns", "")
	lines = append(lines, witnessAssessmentItemLines(jsonutil.ListValue(assessment["triage_concerns"]))...)
	lines = append(lines, "")
	return lines
}

func renderDisputeAssessment(decision map[string]any, packet map[string]any) []string {
	dispute, _ := decision["dispute"].(map[string]any)
	lines := []string{"## Dispute Assessment", "", advisoryOnlyNote(), ""}
	lines = append(lines, "- Outcome effect: `"+jsonutil.StringValue(dispute["outcome_effect"])+"`")
	if points := jsonutil.ListValue(packet["points"]); len(points) > 0 {
		lines = append(lines, "- Dispute points checked: `"+fmt.Sprintf("%d", len(points))+"`")
	}
	lines = append(lines, "", "### Resolved Points", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(dispute["resolved_points"]))...)
	lines = append(lines, "", "### Unresolved Points", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(dispute["unresolved_points"]))...)
	lines = append(lines, "", "### New Evidence", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(dispute["new_evidence"]))...)
	lines = append(lines, "")
	return lines
}

func renderEscalationUnion(decision map[string]any) []string {
	union, _ := decision["union"].(map[string]any)
	lines := []string{"## Added Union", ""}
	lines = append(lines, claimLines(withEscalationSources(jsonutil.ListValue(union["merged_claims"])), "", true)...)
	lines = append(lines, "", "## Conflicts", "")
	lines = append(lines, conflictLines(jsonutil.ListValue(union["conflicts"]))...)
	lines = append(lines, "", "## Unknowns", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(union["unknowns_union"]))...)
	lines = append(lines, "", "## New Or Changed Material", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(union["new_or_changed_material"]))...)
	lines = append(lines, "")
	return lines
}

func withEscalationSources(claims []any) []any {
	out := []any{}
	for _, item := range claims {
		claim, ok := item.(map[string]any)
		if !ok {
			out = append(out, item)
			continue
		}
		copy := cloneMap(claim)
		if _, ok := copy["_source_providers"]; !ok {
			copy["_source_providers"] = copy["sources"]
		}
		out = append(out, copy)
	}
	return out
}

func renderSynthesis(decision map[string]any, addedFinal map[string]any) []string {
	synthesis, _ := decision["synthesis"].(map[string]any)
	lines := []string{"## Synthesis", ""}
	lines = append(lines, "- Effect: `"+jsonutil.StringValue(synthesis["source_decision_effect"])+"`")
	if winner := jsonutil.StringValue(synthesis["recommended_winner"]); winner != "" {
		lines = append(lines, "- Recommended provider: `"+winner+"`")
	}
	lines = append(lines, "", "### What Changed", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(synthesis["what_changed"]))...)
	lines = append(lines, "", "### Material New Evidence", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(synthesis["material_new_evidence"]))...)
	lines = append(lines, "", "### Unresolved Questions", "")
	lines = append(lines, genericItemLines(jsonutil.ListValue(synthesis["unresolved_questions"]))...)
	if len(addedFinal) > 0 {
		lines = append(lines, "", "## Added Provider Output", "")
		if position := jsonutil.StringValue(addedFinal["position"]); position != "" {
			lines = append(lines, "Position: "+position, "")
		}
		lines = append(lines, claimLines(jsonutil.ListValue(addedFinal["claims"]), jsonutil.StringValue(decision["added_provider"]), false)...)
	}
	lines = append(lines, "")
	return lines
}

func renderOutcome(wo *workorder.WorkOrder, decision map[string]any, workerResults map[string]map[string]any, opts RenderOptions) []string {
	_ = workerResults
	mode := jsonutil.StringValue(decision["mode"])
	if mode == "" {
		mode = wo.Type
	}
	kind := jsonutil.StringValue(decision["decision_kind"])
	winner := jsonutil.StringValue(decision["canonical_winner"])
	lines := []string{
		"## Outcome",
		"",
		"Mode: `" + mode + "`",
		"Decision: `" + kind + "`",
	}
	if gloss := statusGloss(kind); gloss != "" {
		lines = append(lines, "Decision meaning: "+gloss)
	}
	if stalledAt := jsonutil.StringValue(decision["stalled_at"]); stalledAt != "" {
		lines = append(lines, "Stalled at: `"+stalledAt+"`")
	}
	if wo.Facet != nil && strings.TrimSpace(wo.Facet.ID) != "" {
		lines = append(lines, "Facet: `"+wo.Facet.ID+"`")
		if wo.Facet.Focus != "" {
			lines = append(lines, "Facet Focus: "+wo.Facet.Focus)
		}
	}
	if winner != "" && mode != "gather" {
		lines = append(lines, "Winner: `"+winner+"`")
	} else if winner != "" && kind == "single_provider_only" {
		lines = append(lines, "Winner: `"+winner+"`")
	} else {
		if (mode == "compare" || mode == "analyze") && kind == "consensus" {
			lines = append(lines, "Result: both providers agreed")
		} else if (mode == "compare" || mode == "analyze") && kind == "tie" {
			lines = append(lines, "Result: no stable winner")
		} else {
			result := kind
			if result == "" {
				result = "unknown"
			}
			lines = append(lines, "Result: `"+result+"`")
		}
	}
	if opts.RunID != "" {
		lines = append(lines, compactNextStep(opts.RunID, opts.OutDir))
	}
	lines = append(lines, "")
	return lines
}

func renderSelectorConfidence(decision map[string]any) []string {
	label := researchSelectorLabel(decision)
	if label == "" {
		return nil
	}
	return []string{
		"## Selector Confidence",
		"",
		selectorLabelLine(label),
		"- Evidence: " + researchSelectorEvidence(decision, label),
		"- Decision effect: " + researchSelectorEffect(decision, label),
		"",
	}
}

func researchSelectorLabel(decision map[string]any) string {
	mode := jsonutil.StringValue(decision["mode"])
	kind := jsonutil.StringValue(decision["decision_kind"])
	switch mode {
	case "gather":
		if kind == "structured_union" {
			return "union/dedupe"
		}
	case "compare", "analyze":
		if (kind == "pick_winner" || kind == "consensus") && jsonutil.BoolValue(decision["judge_completed"]) {
			return "swapped judge"
		}
	}
	switch kind {
	case "single_provider_only", "both_failed", "provider_union_only", "judge_failed", "tie":
		return "unresolved"
	default:
		if jsonutil.StringValue(decision["stalled_at"]) != "" {
			return "unresolved"
		}
	}
	return ""
}

func researchSelectorEvidence(decision map[string]any, label string) string {
	mode := jsonutil.StringValue(decision["mode"])
	kind := jsonutil.StringValue(decision["decision_kind"])
	switch label {
	case "union/dedupe":
		return "gather merged and deduped provider findings without selecting a winner."
	case "swapped judge":
		if kind == "consensus" {
			return "position-swapped judge passes found agreement rather than a winner."
		}
		return "position-swapped judge passes produced a stable decision."
	case "unresolved":
		if kind == "single_provider_only" {
			if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
				return "only `" + winner + "` completed successfully; no two-provider selector ran."
			}
			return "only one provider completed successfully; no two-provider selector ran."
		}
		if stalledAt := jsonutil.StringValue(decision["stalled_at"]); stalledAt != "" {
			return "the selector stopped at `" + stalledAt + "`."
		}
		if mode != "" {
			return "the `" + mode + "` selector did not produce a stable two-provider result."
		}
	}
	return "the selector path did not produce a stable two-provider result."
}

func researchSelectorEffect(decision map[string]any, label string) string {
	kind := jsonutil.StringValue(decision["decision_kind"])
	switch label {
	case "union/dedupe":
		return "no canonical winner; report claims are grouped by source overlap."
	case "swapped judge":
		if kind == "consensus" {
			return "no winner; the report carries consensus material and sub-claim divergences."
		}
		if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
			return "selected `" + winner + "` as the canonical winner."
		}
	case "unresolved":
		if kind == "single_provider_only" {
			return "partial result only; treat the surfaced provider output as incomplete competitive evidence."
		}
		return "no canonical winner; inspect status, caveats, and provider artifacts."
	}
	return "inspect the decision audit and caveats."
}

func renderJudgeFailureStatus(decision map[string]any, opts RenderOptions) []string {
	if !judgeIncomplete(decision) {
		return nil
	}
	lines := []string{"## Status", ""}
	caveatItems := jsonutil.ListValue(decision["caveats"])
	if len(caveatItems) == 0 {
		lines = append(lines, "- Judge did not complete.")
	} else {
		for _, item := range caveatItems {
			lines = append(lines, "- "+fmt.Sprint(item))
		}
	}
	if kind := jsonutil.StringValue(decision["judge_error_kind"]); kind != "" {
		lines = append(lines, "- Judge error kind: `"+kind+"`")
	}
	action := "bakeoff rerun <run-id> --judge-only"
	if opts.RunID != "" {
		action = ledger.BakeoffJudgeOnlyRerunCommand(opts.RunID, opts.OutDir)
	}
	lines = append(lines, "Action: judge failed; provider claims below; consider `"+action+"`.", "")
	return lines
}

func decisionAudit(decision map[string]any) []string {
	lines := []string{"## Decision Audit", "", "- Judge ran: `" + strings.ToLower(fmt.Sprintf("%v", jsonutil.BoolValue(decision["judge_ran"]))) + "`"}
	if _, ok := decision["judge_completed"]; ok {
		lines = append(lines, "- Judge completed: `"+strings.ToLower(fmt.Sprintf("%v", jsonutil.BoolValue(decision["judge_completed"])))+"`")
	}
	if kind := jsonutil.StringValue(decision["judge_error_kind"]); kind != "" {
		lines = append(lines, "- Judge error kind: `"+kind+"`")
	}
	if stalledAt := jsonutil.StringValue(decision["stalled_at"]); stalledAt != "" {
		lines = append(lines, "- Stalled at: `"+stalledAt+"`")
	}
	if winner := jsonutil.StringValue(decision["canonical_winner"]); winner != "" {
		lines = append(lines, "- Canonical winner: `"+winner+"`")
	}
	if tiebreak := jsonutil.StringValue(decision["spine_tiebreak"]); tiebreak != "" {
		lines = append(lines, "- Spine tiebreak: `"+tiebreak+"`")
	}
	if maps, ok := decision["order_maps"].(map[string]any); ok {
		keys := sortedMapKeys(maps)
		for _, name := range keys {
			mapping, _ := maps[name].(map[string]string)
			if mapping == nil {
				if raw, ok := maps[name].(map[string]any); ok {
					mapping = map[string]string{"A": jsonutil.StringValue(raw["A"]), "B": jsonutil.StringValue(raw["B"])}
				}
			}
			lines = append(lines, fmt.Sprintf("- %s: A=`%s`, B=`%s`", name, mapping["A"], mapping["B"]))
		}
	}
	if passes, ok := decision["judge_passes"].(map[string]any); ok && len(passes) > 0 {
		lines = append(lines, "- Judge passes:")
		for _, name := range sortedMapKeys(passes) {
			summary, _ := passes[name].(map[string]any)
			verdict := jsonutil.StringValue(summary["canonical_winner"])
			if verdict == "" {
				verdict = jsonutil.StringValue(summary["positional_winner"])
			}
			if verdict == "" {
				verdict = "none"
			}
			positional := jsonutil.StringValue(summary["positional_winner"])
			relation := jsonutil.StringValue(summary["relation"])
			lines = append(lines, fmt.Sprintf("  - %s: A=`%s`, B=`%s`, winner=`%s` (%s)", name, jsonutil.StringValue(summary["A"]), jsonutil.StringValue(summary["B"]), verdict, judgePassParenthetical(positional, relation)))
		}
	}
	if rationale := jsonutil.ListValue(decision["judge_rationale"]); len(rationale) > 0 {
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
	lines = append(lines, "")
	return lines
}

func judgeIncomplete(decision map[string]any) bool {
	kind := jsonutil.StringValue(decision["decision_kind"])
	if kind == "provider_union_only" || kind == "judge_failed" {
		return true
	}
	if completed, ok := decision["judge_completed"].(bool); ok && !completed {
		return jsonutil.BoolValue(decision["judge_ran"]) || jsonutil.BoolValue(decision["judge_attempted"])
	}
	for _, item := range jsonutil.ListValue(decision["caveats"]) {
		text := strings.ToLower(fmt.Sprint(item))
		if strings.Contains(text, "judge failed") || strings.Contains(text, "judge crashed") {
			return true
		}
	}
	return false
}

func judgePassParenthetical(positional string, relation string) string {
	parts := []string{}
	if positional != "" {
		parts = append(parts, "positional=`"+positional+"`")
	}
	if relation != "" {
		parts = append(parts, "relation="+relation)
	}
	if relation == "consensus" && positional == "" {
		parts = append(parts, "no positional winner")
	}
	if len(parts) == 0 {
		return "no positional winner"
	}
	return strings.Join(parts, ", ")
}

func renderProviderStatusTable(decision map[string]any) []string {
	statuses, _ := decision["provider_statuses"].(map[string]any)
	if len(statuses) == 0 {
		return nil
	}
	lines := []string{
		"## Provider Status",
		"",
		"| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |",
		"|----------|--------|------|--------|--------|-------|-------|",
	}
	for _, providerID := range sortedMapKeys(statuses) {
		status, _ := statuses[providerID].(map[string]any)
		stdoutBytes := jsonutil.IntValue(jsonutil.FirstNonNil(status["stdout_bytes"], status["output_bytes"], 0))
		stderrBytes := jsonutil.IntValue(jsonutil.FirstNonNil(status["stderr_bytes"], 0))
		stdoutObserved := jsonutil.IntValue(status["stdout_observed_bytes"])
		stderrObserved := jsonutil.IntValue(status["stderr_observed_bytes"])
		stdoutCell := byteCell(stdoutBytes, stdoutObserved, jsonutil.BoolValue(status["stdout_truncated"]))
		stderrCell := byteCell(stderrBytes, stderrObserved, jsonutil.BoolValue(status["stderr_truncated"]))
		notes := []string{}
		if jsonutil.BoolValue(status["stdout_truncated"]) && stdoutCell == humanBytes(stdoutBytes) {
			notes = append(notes, "stdout truncated")
		}
		if jsonutil.BoolValue(status["stderr_truncated"]) && stderrCell == humanBytes(stderrBytes) {
			notes = append(notes, "stderr truncated")
		}
		if kind := jsonutil.StringValue(status["stderr_kind"]); kind != "" && kind != "none" {
			notes = append(notes, "stderr kind: "+kind)
		}
		if jsonutil.BoolValue(status["stderr_filtered"]) {
			notes = append(notes, "stderr filtered")
		}
		if gloss := statusGloss(jsonutil.StringValue(status["status"])); gloss != "" {
			notes = append(notes, "status: "+gloss)
		}
		if kind := jsonutil.StringValue(status["failure_kind"]); kind != "" {
			notes = append(notes, "failure kind: "+kind)
		}
		if jsonutil.StringValue(status["status"]) == runner.StatusSalvaged {
			note := "salvaged output"
			if source := salvageSource(status); source != "" {
				note += " from " + source
			}
			notes = append(notes, note)
		}
		if path := jsonutil.StringValue(status["stderr_path"]); path != "" {
			notes = append(notes, "stderr: `"+path+"`")
		}
		scopeText := ""
		if scope, ok := status["scope_enforcement"].(map[string]any); ok {
			level := defaultString(scope["enforcement_level"], "unknown")
			requested := defaultString(scope["requested_scope"], "unknown")
			effective := defaultString(scope["effective_scope"], "unknown")
			if reason := jsonutil.StringValue(scope["fallback_reason"]); reason != "" {
				notes = append(notes, "fallback: "+reason)
			}
			scopeText = requested + " -> " + effective + " (" + level + ")"
		}
		lines = append(lines, fmt.Sprintf("| `%s` | `%s` | %vs | %s | %s | %s | %s |",
			providerID,
			jsonutil.StringValue(status["status"]),
			jsonutil.FirstNonNil(status["wall_seconds"], 0),
			stdoutCell,
			stderrCell,
			escapeTableCell(scopeText),
			escapeTableCell(strings.Join(notes, "; ")),
		))
	}
	lines = append(lines, "")
	return lines
}

func byteCell(captured int, observed int, truncated bool) string {
	text := humanBytes(captured)
	if truncated && observed != 0 && observed != captured {
		excess := observed - captured
		if excess < 0 {
			excess = 0
		}
		text += " (trunc, +" + humanBytes(excess) + ")"
	}
	return text
}

func humanBytes(size int) string {
	if size >= 1024*1024 {
		return fmt.Sprintf("%.1f MB", float64(size)/(1024*1024))
	}
	if size >= 1024 {
		return fmt.Sprintf("%.1f KB", float64(size)/1024)
	}
	return fmt.Sprintf("%d B", size)
}

func escapeTableCell(text string) string {
	return strings.ReplaceAll(text, "|", `\|`)
}

func salvageSource(status map[string]any) string {
	switch salvage := status["salvage"].(type) {
	case *runner.SalvageMetadata:
		return salvage.Source
	case runner.SalvageMetadata:
		return salvage.Source
	case map[string]any:
		return jsonutil.StringValue(salvage["source"])
	default:
		return ""
	}
}

func renderGather(wo *workorder.WorkOrder, decision map[string]any, workerResults map[string]map[string]any, judgeResults map[string]map[string]any) []string {
	switch decision["decision_kind"] {
	case "both_failed":
		return []string{"## Findings", "", "No provider completed successfully.", ""}
	case "single_provider_only":
		providerID := jsonutil.StringValue(decision["canonical_winner"])
		worker := jsonutil.FinalJSONMap(workerResults[providerID])
		lines := []string{"## Findings", ""}
		if note := singleProviderPartialNote(decision); note != "" {
			lines = append(lines, note, "")
		}
		lines = append(lines, claimLines(jsonutil.ListValue(worker["claims"]), providerID, false)...)
		return append(lines, unknowns(worker)...)
	case "provider_union_only", "judge_failed":
		return renderPerProviderResearch(wo, workerResults, "## Findings")
	}
	if judgeIncomplete(decision) {
		return renderPerProviderResearch(wo, workerResults, "## Findings")
	}
	judge := judgeResults["pass1"]
	if judge == nil {
		judge = judgeResults["gather"]
	}
	merged := jsonutil.ListValue(judge["merged_claims"])
	orderMap := map[string]string{}
	if maps, ok := decision["order_maps"].(map[string]any); ok {
		if raw, ok := maps["pass1"].(map[string]string); ok {
			orderMap = raw
		} else if raw, ok := maps["pass1"].(map[string]any); ok {
			orderMap = map[string]string{"A": jsonutil.StringValue(raw["A"]), "B": jsonutil.StringValue(raw["B"])}
		}
	}
	grouped := map[string][]any{}
	for _, item := range merged {
		claim, _ := item.(map[string]any)
		sources := []string{}
		for _, rawSource := range jsonutil.ListValue(claim["sources"]) {
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
	lines = append(lines, conflictLines(jsonutil.ListValue(judge["conflicts"]))...)
	lines = append(lines, "", "## Unknowns", "")
	unknownsUnion := jsonutil.ListValue(judge["unknowns_union"])
	if len(unknownsUnion) == 0 {
		lines = append(lines, "- None reported.")
	} else {
		for _, item := range unknownsUnion {
			lines = append(lines, "- "+fmt.Sprint(item))
		}
	}
	lines = append(lines, "")
	if outOfFacet := jsonutil.ListValue(judge["out_of_facet_claims"]); len(outOfFacet) > 0 {
		lines = append(lines, "## Out-of-Facet Claims", "", "These claims are observability-only and are excluded from triage source selection.", "")
		lines = append(lines, outOfFacetLines(outOfFacet)...)
		lines = append(lines, "")
	}
	return lines
}

func renderPerProviderResearch(wo *workorder.WorkOrder, workerResults map[string]map[string]any, heading string) []string {
	lines := []string{heading, ""}
	for _, providerID := range orderedProviderIDs(wo, workerResults) {
		worker := jsonutil.FinalJSONMap(workerResults[providerID])
		lines = append(lines, "### "+providerID)
		lines = append(lines, claimLines(jsonutil.ListValue(worker["claims"]), providerID, false)...)
		lines = append(lines, "")
	}
	lines = append(lines, "## Unknowns", "")
	for _, providerID := range orderedProviderIDs(wo, workerResults) {
		worker := jsonutil.FinalJSONMap(workerResults[providerID])
		lines = append(lines, "### "+providerID)
		items := jsonutil.ListValue(worker["unknowns"])
		if len(items) == 0 {
			lines = append(lines, "- None reported.")
		} else {
			for _, item := range items {
				lines = append(lines, "- "+fmt.Sprint(item))
			}
		}
		lines = append(lines, "")
	}
	return lines
}

func renderPerProviderComparison(workerResults map[string]map[string]any, heading string) []string {
	lines := []string{heading, "", "Judge failed; surfacing each provider result without selecting a winner.", ""}
	for _, providerID := range sortedProviderIDs(workerResults) {
		worker := jsonutil.FinalJSONMap(workerResults[providerID])
		lines = append(lines, "### "+providerID)
		if position := jsonutil.StringValue(worker["position"]); position != "" {
			lines = append(lines, "Position: "+position, "")
		}
		lines = append(lines, claimLines(jsonutil.ListValue(worker["claims"]), providerID, false)...)
		lines = append(lines, "")
	}
	return lines
}

func singleProviderPartialNote(decision map[string]any) string {
	if jsonutil.StringValue(decision["decision_kind"]) != "single_provider_only" {
		return ""
	}
	winner := jsonutil.StringValue(decision["canonical_winner"])
	statuses, _ := decision["provider_statuses"].(map[string]any)
	for _, providerID := range sortedMapKeys(statuses) {
		if providerID == winner {
			continue
		}
		status, _ := statuses[providerID].(map[string]any)
		reason := partialPeerReason(status)
		if reason == "" {
			continue
		}
		if winner == "" {
			return fmt.Sprintf("Partial result: `%s` %s, so this lens is single-provider-only.", providerID, reason)
		}
		return fmt.Sprintf("Partial result: `%s` %s, so this lens is single-provider-only and surfaces only `%s`.", providerID, reason, winner)
	}
	return ""
}

func partialPeerReason(status map[string]any) string {
	switch jsonutil.StringValue(status["status"]) {
	case runner.StatusTimeout:
		if kind := jsonutil.StringValue(status["failure_kind"]); kind != "" {
			return "timed out (`" + kind + "`)"
		}
		return "timed out"
	case runner.StatusSalvaged:
		if source := salvageSource(status); source != "" {
			return "was salvaged from `" + source + "` but did not complete successfully"
		}
		return "was salvaged but did not complete successfully"
	default:
		return ""
	}
}

func renderCompare(decision map[string]any, workerResults map[string]map[string]any) []string {
	lines := []string{"## Comparison", ""}
	kind := jsonutil.StringValue(decision["decision_kind"])
	winner := jsonutil.StringValue(decision["canonical_winner"])
	if kind == "judge_failed" || judgeIncomplete(decision) {
		return renderPerProviderComparison(workerResults, "## Comparison")
	}
	switch {
	case kind == "pick_winner" && winner != "":
		final := jsonutil.FinalJSONMap(workerResults[winner])
		lines = append(lines, "Winner: `"+winner+"`")
		if position := jsonutil.StringValue(final["position"]); position != "" {
			lines = append(lines, "Position: "+position)
		}
		lines = append(lines, "")
		lines = append(lines, claimLines(jsonutil.ListValue(final["claims"]), winner, false)...)
	case kind == "consensus":
		lines = append(lines, "The judge found both providers reached the same position.", "", "### Strongest Material", "")
		lines = append(lines, genericItemLines(jsonutil.ListValue(decision["consensus_strongest"]))...)
		lines = append(lines, "", "### Sub-Claim Divergences", "")
		lines = append(lines, genericItemLines(jsonutil.ListValue(decision["consensus_disagreements"]))...)
	case kind == "single_provider_only" && winner != "":
		final := jsonutil.FinalJSONMap(workerResults[winner])
		lines = append(lines, "No comparison possible - surfacing the single completed result.")
		if note := singleProviderPartialNote(decision); note != "" {
			lines = append(lines, note)
		}
		if position := jsonutil.StringValue(final["position"]); position != "" {
			lines = append(lines, "Position: "+position)
		}
		lines = append(lines, "")
		lines = append(lines, claimLines(jsonutil.ListValue(final["claims"]), winner, false)...)
	case kind == "both_failed":
		lines = append(lines, "No provider completed successfully.")
	default:
		lines = append(lines, "No stable winner after position swap. Human decision required.")
	}
	if kept := jsonutil.ListValue(decision["kept_from_nonwinner"]); len(kept) > 0 {
		lines = append(lines, "", "## Kept From Nonwinner", "")
		lines = append(lines, genericItemLines(kept)...)
	}
	lines = append(lines, "")
	return lines
}

func renderAnalyze(decision map[string]any, workerResults map[string]map[string]any) []string {
	lines := []string{"## Primary Explanation", ""}
	winner := jsonutil.StringValue(decision["canonical_winner"])
	if decision["decision_kind"] == "both_failed" {
		return append(lines, "No provider completed successfully.", "")
	}
	if decision["decision_kind"] == "judge_failed" || judgeIncomplete(decision) {
		return renderPerProviderComparison(workerResults, "## Primary Explanation")
	}
	if winner == "" {
		return append(lines, "No stable spine was selected. Human decision required.", "")
	}
	if jsonutil.StringValue(decision["decision_kind"]) == "single_provider_only" {
		if note := singleProviderPartialNote(decision); note != "" {
			lines = append(lines, note, "")
		}
	}
	final := jsonutil.FinalJSONMap(workerResults[winner])
	verdicts := map[string]map[string]any{}
	for _, item := range jsonutil.ListValue(decision["claim_verdicts"]) {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		verdicts[jsonutil.StringValue(obj["claim_id"])] = obj
	}
	claims := jsonutil.ListValue(final["claims"])
	for _, item := range claims {
		claim, _ := item.(map[string]any)
		verdict := verdicts[jsonutil.StringValue(claim["id"])]
		marker := jsonutil.StringValue(verdict["loser_position"])
		note := ""
		if marker != "" {
			note = " [" + marker + ": " + jsonutil.StringValue(verdict["loser_note"]) + "]"
		}
		evidence := joinList(claim["evidence"], ", ")
		lines = append(lines, fmt.Sprintf("- **%s** %s%s", defaultString(claim["id"], "?"), jsonutil.StringValue(claim["claim"]), note))
		if evidence != "" {
			lines = append(lines, "  Evidence: "+evidence)
		}
	}
	if len(claims) == 0 {
		lines = append(lines, "No claims were available to render.")
	}
	if followups := jsonutil.ListValue(decision["actionable_followups"]); len(followups) > 0 {
		lines = append(lines, "", "## Actionable Follow-ups", "")
		lines = append(lines, genericItemLines(followups)...)
	}
	if additions := jsonutil.ListValue(decision["additions_from_loser"]); len(additions) > 0 {
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
			for _, raw := range jsonutil.ListValue(claim["_source_providers"]) {
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
		lines = append(lines, fmt.Sprintf("- %s (%s)", jsonutil.StringValue(claim["claim"]), strings.Join(details, ", ")))
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
	items := jsonutil.ListValue(worker["unknowns"])
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
			if disputeLines, ok := disputeItemLines(obj); ok {
				lines = append(lines, disputeLines...)
				continue
			}
			claim := firstString(obj["claim"], obj["description"], obj["loser_note"])
			if claim == "" {
				claim = deterministicItemText(obj)
			}
			lines = append(lines, "- "+claim)
			if evidence := joinList(obj["evidence"], ", "); evidence != "" {
				lines = append(lines, "  Evidence: "+evidence)
			}
			if source := jsonutil.StringValue(obj["source_provider"]); source != "" {
				lines = append(lines, "  Source: `"+source+"`")
			}
			continue
		}
		lines = append(lines, "- "+deterministicItemText(item))
	}
	return lines
}

func witnessAssessmentItemLines(items []any) []string {
	if len(items) == 0 {
		return []string{"- None reported."}
	}
	lines := []string{}
	for _, item := range items {
		if obj, ok := item.(map[string]any); ok {
			if witnessLines, ok := witnessItemLines(obj); ok {
				lines = append(lines, witnessLines...)
				continue
			}
		}
		lines = append(lines, genericItemLines([]any{item})...)
	}
	return lines
}

func witnessItemLines(obj map[string]any) ([]string, bool) {
	hasWitnessShape := firstString(obj["source_finding_id"], obj["challenge_type"], obj["counterexample"], obj["effect"]) != ""
	if !hasWitnessShape {
		return nil, false
	}
	claim := firstString(obj["claim"], obj["description"], obj["rationale"])
	if claim == "" {
		return nil, false
	}
	prefix := "- "
	if sourceID := jsonutil.StringValue(obj["source_finding_id"]); sourceID != "" {
		prefix += "**" + sourceID + "** "
	}
	if challengeType := jsonutil.StringValue(obj["challenge_type"]); challengeType != "" {
		prefix += "`" + challengeType + "`: "
	}
	lines := []string{prefix + claim}
	if evidence := joinList(obj["evidence"], ", "); evidence != "" {
		lines = append(lines, "  Evidence: "+evidence)
	}
	if counterevidence := joinList(obj["counterevidence"], ", "); counterevidence != "" {
		lines = append(lines, "  Counter-evidence: "+counterevidence)
	}
	if counterexample := jsonutil.StringValue(obj["counterexample"]); counterexample != "" {
		lines = append(lines, "  Counterexample: "+counterexample)
	}
	details := []string{}
	if effect := jsonutil.StringValue(obj["effect"]); effect != "" {
		details = append(details, "effect `"+effect+"`")
	}
	if confidence := jsonutil.StringValue(obj["confidence"]); confidence != "" {
		details = append(details, "confidence `"+confidence+"`")
	}
	if len(details) > 0 {
		lines = append(lines, "  "+strings.Join(details, ", "))
	}
	return lines, true
}

func disputeItemLines(obj map[string]any) ([]string, bool) {
	id := firstString(obj["id"], obj["point_id"])
	resolution := firstString(obj["resolution"], obj["assessment"], obj["summary"], obj["answer"], obj["verdict"], obj["rationale"], obj["description"], obj["claim"])
	evidence := joinList(obj["evidence"], ", ")
	if id == "" || (resolution == "" && evidence == "") {
		return nil, false
	}
	prefix := "**" + id + "**"
	if materiality := jsonutil.StringValue(obj["materiality"]); materiality != "" {
		prefix += " " + materiality + "."
	}
	line := "- " + prefix
	if resolution != "" {
		line += " " + resolution
	}
	lines := []string{line}
	if evidence != "" {
		lines = append(lines, "  Evidence: "+evidence)
	}
	if source := jsonutil.StringValue(obj["source_provider"]); source != "" {
		lines = append(lines, "  Source: `"+source+"`")
	}
	return lines, true
}

func reportGlossary() []string {
	return []string{
		"## Glossary",
		"",
		"- `F-NNN`: report finding; `R-NNN`: judge rationale; `D-NNN`: escalation dispute point.",
		"- Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved.",
		"",
	}
}

func statusGloss(status string) string {
	switch status {
	case runner.StatusOKAfterFormatRetry:
		return "completed after a format-only retry repaired the provider JSON"
	case runner.StatusSalvaged:
		return "usable evidence was recovered, but the provider did not complete cleanly"
	case "consensus":
		return "both providers reached the same position; sub-claim divergences may still matter"
	case "escalation_advisory_supported":
		return "advisory escalation supports the source decision and does not replace the source winner"
	case "escalation_advisory_challenged":
		return "advisory escalation questions the source decision and does not replace the source winner"
	case "consensus_disagreements":
		return "sub-claim differences preserved even though the top-level result is consensus"
	default:
		return ""
	}
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
		if sources := jsonutil.ListValue(jsonutil.FirstNonNil(obj["sources"], obj["source_labels"])); len(sources) > 0 {
			parts := []string{}
			for _, source := range sources {
				parts = append(parts, fmt.Sprint(source))
			}
			details = append(details, "sources `"+strings.Join(parts, "+")+"`")
		}
		if reason := jsonutil.StringValue(obj["reason"]); reason != "" {
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
	items := jsonutil.ListValue(decision["caveats"])
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

func nestedString(obj map[string]any, key string, nestedKey string) string {
	nested, _ := obj[key].(map[string]any)
	if nested == nil {
		return ""
	}
	return jsonutil.StringValue(nested[nestedKey])
}

func nestedList(obj map[string]any, key string, nestedKey string) []any {
	nested, _ := obj[key].(map[string]any)
	if nested == nil {
		return nil
	}
	return jsonutil.ListValue(nested[nestedKey])
}

func firstNonEmptyListSummary(groups ...[]any) string {
	for _, group := range groups {
		if len(group) == 0 {
			continue
		}
		if len(group) == 1 {
			return deterministicItemText(group[0])
		}
		return fmt.Sprintf("%s (+%d more)", deterministicItemText(group[0]), len(group)-1)
	}
	return "none reported"
}

// advisoryOnlyNote is the standard opening phrase for advisory-mode assessment sections.
func advisoryOnlyNote() string {
	return "This result is advisory and does not select a new winner."
}

// compactNextStep returns the formatted next-step run command line (no bullet prefix).
func compactNextStep(runID, outDir string) string {
	return "Next: `" + ledger.BakeoffShowCommand(runID, outDir, "") + "`"
}

// selectorStrengthLine returns the confidence bullet for an advisory escalation answer.
func selectorStrengthLine(confidence string) string {
	return "- Confidence: `" + confidence + "`"
}

func selectorLabelLine(label string) string {
	return "- Selector label: `" + label + "`"
}

// escalationAdvisoryImpactLines returns advisory decision-impact bullet lines for non-independent escalation modes.
func escalationAdvisoryImpactLines(mode, selectionBasis string) []string {
	var lines []string
	if label := escalationSelectorLabel(mode, selectionBasis); label != "" {
		lines = append(lines, selectorLabelLine(label))
	}
	if mode != "independent" {
		lines = append(lines, "- Decision impact: advisory only; this mode does not replace the source winner.")
	}
	if selectionBasis == "escalation_synthesis" {
		lines = append(lines, "- Selection basis: `escalation_synthesis`; this is one synthesis pass, not position-swapped judging.")
	}
	return lines
}

func escalationSelectorLabel(mode, selectionBasis string) string {
	switch mode {
	case "witness":
		return "advisory witness"
	case "dispute":
		return "focused dispute"
	case "independent":
		if selectionBasis == "escalation_synthesis" {
			return "fresh third answer"
		}
	}
	return ""
}

func escalationModeLabel(mode string) string {
	switch mode {
	case "independent":
		return "fresh third answer"
	case "witness":
		return "audit the current result"
	case "dispute":
		return "focus only on contested points"
	default:
		return "unknown"
	}
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

func orderedProviderIDs(wo *workorder.WorkOrder, results map[string]map[string]any) []string {
	seen := map[string]bool{}
	ids := []string{}
	if wo != nil {
		for _, participant := range wo.Providers {
			if participant.ID != "" {
				ids = append(ids, participant.ID)
				seen[participant.ID] = true
			}
		}
	}
	for _, id := range sortedProviderIDs(results) {
		if !seen[id] {
			ids = append(ids, id)
		}
	}
	return ids
}

func sortedProviderIDs(results map[string]map[string]any) []string {
	ids := make([]string, 0, len(results))
	for id := range results {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func cloneMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}

func defaultString(value any, fallback string) string {
	if text := jsonutil.StringValue(value); text != "" {
		return text
	}
	return fallback
}

func joinList(value any, sep string) string {
	items := jsonutil.ListValue(value)
	parts := []string{}
	for _, item := range items {
		parts = append(parts, deterministicItemText(item))
	}
	return strings.Join(parts, sep)
}

func firstString(values ...any) string {
	for _, value := range values {
		if text := jsonutil.StringValue(value); text != "" {
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

func deterministicItemText(value any) string {
	switch value.(type) {
	case map[string]any, []any:
		data, err := json.Marshal(value)
		if err == nil {
			return string(data)
		}
	}
	return fmt.Sprint(value)
}
