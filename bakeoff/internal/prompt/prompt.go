package prompt

import (
	"embed"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	providerpkg "github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var (
	//go:embed fixtures/*.txt
	fixtureFS embed.FS
)

var scopeInstructions = map[string]string{
	"codebase": "Search the current working directory and cite as `path/to/file.ext:line`. Do not invoke web search.",
	"web":      "Search the web and cite as full URLs. Do not assume the user's codebase is available.",
	"mixed":    "Use both the codebase and web search. Cite as `path:line` for code, full URLs for web.",
}

func BuildWorkerPrompt(wo *workorder.WorkOrder, provider workorder.Participant) (string, error) {
	return BuildWorkerPromptWithRepoLayout(wo, provider, "")
}

func BuildWorkerPromptWithRepoLayout(wo *workorder.WorkOrder, provider workorder.Participant, repoLayout string) (string, error) {
	base, err := fixturePrompt(fmt.Sprintf("worker-%s-%s.txt", wo.Type, workerFixtureBackend(provider)))
	if err != nil {
		return "", err
	}
	questionTag := "question"
	if wo.Type == "analyze" {
		questionTag = "subject"
	}
	scope, ok := scopeInstructions[provider.Scope]
	if !ok {
		return "", fmt.Errorf("unsupported scope: %s", provider.Scope)
	}
	text := base
	text = replaceTagInnerEscaped(text, questionTag, wo.Goal)
	text = replaceTagInnerEscaped(text, "context", wo.Background)
	text = insertAfterTag(text, "context", escapeTaggedPromptBlock(repoLayout, "repo_layout"))
	text = replaceTagInner(text, "scope", scope)
	text = replaceBlock(text, fixtureFacetBlock(), RenderFacetBlock(wo.Facet))
	text = strings.Replace(text, fixtureWorkerFacetRules(), renderWorkerFacetRules(wo.Facet, wo.Type), 1)
	text = replaceBlock(text, fixtureBuildSpecBlock(), RenderBuildSpecBlock(wo.Build))
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(wo.Budgets, "worker"))
	text = renderRunModeWorkerInstructions(text, wo)
	return text, nil
}

func renderRunModeWorkerInstructions(text string, wo *workorder.WorkOrder) string {
	if wo == nil || wo.RunMode != workorder.RunModeSingleProvider {
		return text
	}
	replacements := []struct {
		old string
		new string
	}{
		{"A separate judge will deduplicate your output against a peer worker's output later.", "This is a standalone single-provider run. Produce the best complete result you can; no peer worker or judge will merge, compare, or rescue the output."},
		{"A judge will later weigh your case against a peer worker who answered the same question independently.", "This is a standalone single-provider run. Produce the strongest complete answer you can; no peer worker or judge will compare or rescue the output."},
		{`A judge will later select your analysis or a peer's as the "spine" and overlay the loser's annotations onto the winner.`, "This is a standalone single-provider run. Produce the clearest complete analysis you can; no peer worker or judge will select, merge, or rescue the output."},
		{`A separate judge will compare your patch against another provider's patch later.`, "This is a standalone single-provider build. Produce the best complete patch you can; no competing provider or judge will compare or rescue the output."},
		{`A separate judge will compare your output against a peer worker's output later.`, "This is a standalone single-provider run. Produce the best complete result you can; no peer worker or judge will compare or rescue the output."},
		{`A judge will later compare your output against a peer worker's output.`, "This is a standalone single-provider run. Produce the best complete result you can; no peer worker or judge will compare or rescue the output."},
		{`that a peer could independently mark "agrees", "disagrees", or "adds nuance"`, `that a reader could independently mark "agrees", "disagrees", or "adds nuance"`},
		{"Low-confidence steps invite peer corrections.", "Low-confidence steps should state what would change your confidence."},
		{`a later merger may overlay annotations on each step independently.`, `a later reader may inspect each step independently.`},
		{"Hidden weaknesses cost you credibility with the judge.", "Hidden weaknesses make the answer less useful."},
		{"The judge handles synthesis.", "Do not add an uncited synthesis."},
	}
	for _, replacement := range replacements {
		text = strings.ReplaceAll(text, replacement.old, replacement.new)
	}
	return text
}

func BuildJudgePrompt(wo *workorder.WorkOrder, workerA any, workerB any, mode string) (string, error) {
	return BuildJudgePromptWithEvidence(wo, nil, workerA, workerB, mode)
}

func BuildJudgePromptWithEvidence(wo *workorder.WorkOrder, sharedEvidence any, workerA any, workerB any, mode string) (string, error) {
	actualMode := mode
	if actualMode == "" {
		actualMode = wo.Type
	}
	base, err := fixturePrompt(fmt.Sprintf("judge-%s.txt", actualMode))
	if err != nil {
		return "", err
	}
	payloadA, err := sortedJSON(workerA)
	if err != nil {
		return "", err
	}
	payloadB, err := sortedJSON(workerB)
	if err != nil {
		return "", err
	}
	sharedPayload := "{}"
	if sharedEvidence != nil {
		sharedPayload, err = sortedJSON(sharedEvidence)
		if err != nil {
			return "", err
		}
	}
	text := base
	text = replaceBlock(text, fixtureFacetBlock(), RenderFacetBlock(wo.Facet))
	text = strings.Replace(text, fixtureJudgeFacetRules(actualMode), RenderJudgeFacetRules(wo.Facet, actualMode), 1)
	text = replaceTagInnerEscaped(text, "goal", wo.Goal)
	text = replaceTagInnerEscaped(text, "background", wo.Background)
	text = replaceBlock(text, fixtureBuildSpecBlock(), RenderBuildSpecBlock(wo.Build))
	text = replaceTagInnerEscaped(text, "shared_build_evidence", sharedPayload)
	text = replaceTagInnerEscaped(text, judgeATag(actualMode), payloadA)
	text = replaceTagInnerEscaped(text, judgeBTag(actualMode), payloadB)
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(wo.Budgets, "judge"))
	return text, nil
}

func BuildTriagePrompt(payload any, budgets workorder.Budgets) (string, error) {
	base, err := fixturePrompt("triage.txt")
	if err != nil {
		return "", err
	}
	payloadBlocks, err := renderTriagePayloadBlocks(payload)
	if err != nil {
		return "", err
	}
	text := base
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(budgets, "triage"))
	text = replaceBlock(text, fixtureTriageReviewContractBlock(), RenderTriageReviewContractRules(payload))
	text = replaceTagInner(text, "triage_payload_blocks", payloadBlocks)
	return text, nil
}

func BuildEscalationWitnessPrompt(payload any, budgets workorder.Budgets) (string, error) {
	return buildEscalationPrompt("escalation-witness.txt", payload, budgets)
}

func BuildEscalationDisputePrompt(payload any, budgets workorder.Budgets) (string, error) {
	return buildEscalationPrompt("escalation-dispute.txt", payload, budgets)
}

func BuildEscalationGatherUnionPrompt(payload any, budgets workorder.Budgets) (string, error) {
	return buildEscalationPrompt("escalation-gather-union.txt", payload, budgets)
}

func BuildEscalationSynthesisPrompt(payload any, budgets workorder.Budgets) (string, error) {
	return buildEscalationPrompt("escalation-synthesis.txt", payload, budgets)
}

func buildEscalationPrompt(fixture string, payload any, budgets workorder.Budgets) (string, error) {
	base, err := fixturePrompt(fixture)
	if err != nil {
		return "", err
	}
	payloadBlocks, err := renderEscalationPayloadBlocks(payload)
	if err != nil {
		return "", err
	}
	text := base
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(budgets, "judge"))
	text = replaceBlock(text, fixtureReviewWitnessRulesBlock(), RenderReviewWitnessRulesBlock(payload))
	text = replaceTagInner(text, "escalation_payload_blocks", payloadBlocks)
	return text, nil
}

func renderEscalationPayloadBlocks(payload any) (string, error) {
	obj, ok := payload.(map[string]any)
	if !ok {
		payloadJSON, err := sortedJSON(payload)
		if err != nil {
			return "", err
		}
		return "<escalation_payload>\n" + escapePromptBlockBody(payloadJSON) + "\n</escalation_payload>", nil
	}
	blocks := []struct {
		tag string
		key string
	}{
		{tag: "source_run", key: "source_run"},
		{tag: "work_order_json", key: "work_order_json"},
		{tag: "source_report_md", key: "source_report_md"},
		{tag: "source_decision_json", key: "source_decision_json"},
		{tag: "source_meta_json", key: "source_meta_json"},
		{tag: "source_provider_finals", key: "source_provider_finals"},
		{tag: "source_judge_results", key: "source_judge_results"},
		{tag: "added_provider_final", key: "added_provider_final"},
		{tag: "dispute_packet", key: "dispute_packet"},
		{tag: "review_context_md", key: "review_context_md"},
		{tag: "review_context_json", key: "review_context_json"},
		{tag: "triage_artifacts", key: "triage_artifacts"},
		{tag: "review_claim_targets", key: "review_claim_targets"},
	}
	lines := []string{}
	for _, item := range blocks {
		value, exists := obj[item.key]
		if !exists || value == nil {
			continue
		}
		rendered, err := renderEscalationBlockValue(item.tag, value)
		if err != nil {
			return "", err
		}
		lines = append(lines, rendered)
	}
	if len(lines) == 0 {
		payloadJSON, err := sortedJSON(payload)
		if err != nil {
			return "", err
		}
		return "<escalation_payload>\n" + escapePromptBlockBody(payloadJSON) + "\n</escalation_payload>", nil
	}
	return strings.Join(lines, "\n\n"), nil
}

func renderEscalationBlockValue(tag string, value any) (string, error) {
	var body string
	if text, ok := value.(string); ok && (tag == "work_order_json" || strings.HasSuffix(tag, "_md")) {
		body = strings.TrimRight(text, "\n")
	} else {
		payloadJSON, err := sortedJSON(value)
		if err != nil {
			return "", err
		}
		body = payloadJSON
	}
	return "<" + tag + ">\n" + escapePromptBlockBody(body) + "\n</" + tag + ">", nil
}

func renderTriagePayloadBlocks(payload any) (string, error) {
	obj, ok := payload.(map[string]any)
	if !ok {
		payloadJSON, err := sortedJSON(payload)
		if err != nil {
			return "", err
		}
		return "<triage_payload>\n" + escapePromptBlockBody(payloadJSON) + "\n</triage_payload>", nil
	}
	type block struct {
		tag string
		key string
	}
	blocks := []block{
		{tag: "work_order_json", key: "work_order_json"},
		{tag: "report_md", key: "report_md"},
		{tag: "decision_json", key: "decision"},
		{tag: "source_findings", key: "source_findings"},
		{tag: "source_finding_filter", key: "source_finding_filter"},
		{tag: "provider_failures", key: "provider_failures"},
		{tag: "citation_checks", key: "citation_checks"},
		{tag: "meta", key: "meta"},
		{tag: "facet", key: "facet"},
		{tag: "caveats", key: "caveats"},
		{tag: "input_hashes", key: "input_hashes"},
	}
	lines := []string{}
	for _, item := range blocks {
		value, exists := obj[item.key]
		if !exists {
			continue
		}
		rendered, err := renderTriageBlockValue(item.tag, value)
		if err != nil {
			return "", err
		}
		lines = append(lines, rendered)
	}
	return strings.Join(lines, "\n\n"), nil
}

func renderTriageBlockValue(tag string, value any) (string, error) {
	var body string
	if text, ok := value.(string); ok && (tag == "work_order_json" || tag == "report_md") {
		body = strings.TrimRight(text, "\n")
	} else {
		payloadJSON, err := sortedJSON(value)
		if err != nil {
			return "", err
		}
		body = payloadJSON
	}
	return "<" + tag + ">\n" + escapePromptBlockBody(body) + "\n</" + tag + ">", nil
}

func escapePromptBlockBody(body string) string {
	return strings.ReplaceAll(body, "</", `<\/`)
}

func RenderTriageReviewContractRules(payload any) string {
	obj, _ := payload.(map[string]any)
	facet, _ := obj["facet"].(map[string]any)
	id, _ := facet["id"].(string)
	if id != "code-review" {
		return ""
	}
	return `<review_contract_rules>
For code-review facets:
- Verify each selected finding against the work-order goal/background, generated review context, acceptance criteria when present, and changed behavior.
- Require file:line evidence for actionable defects.
- Use classification, severity, confidence, and recommended_action to distinguish real defects from warnings, product decisions, evidence gaps, and style-only findings.
</review_contract_rules>
`
}

func RenderReviewWitnessRulesBlock(payload any) string {
	if !isCodeReviewWitnessPayload(payload) {
		return ""
	}
	return `<review_witness_rules>
This is a code-review witness pass. Treat report findings and triage items as
hypotheses to falsify, not as conclusions to summarize. Your job is to test
the report, not defend it.

Assume the source report contains some real findings, some false positives,
some stale comments, and some missed defects. For each target in
<review_claim_targets>, ask:
1. Is the issue introduced or exposed by the reviewed change?
2. Do the cited files and lines semantically support the claim?
3. Is there counterevidence in code, tests, docs, or triage artifacts?
4. Is this out of the source facet or acceptance criteria?
5. Is the severity, confidence, or recommended action overstated?
6. For behavioral or security claims, can you produce a concrete
   counterexample, call trace, failing scenario, or static proof where
   applicable?
7. Did the source report miss a defect adjacent to a target?

Challenge a report finding when it is unsupported by its cited file:line
evidence, stale or already fixed, not introduced or exposed by the reviewed
change, out of facet or acceptance criteria, duplicated, severity- or
confidence-overstated, missing a reproducer for a behavioral claim, or
contradicted by code, tests, docs, or triage artifacts.

Put challenged source findings in material_errors. Put likely real defects the
source report missed in missed_material. Put bad classifications, severities,
confidences, or recommended actions in triage_concerns.

Prefer object items in material_errors, missed_material, and triage_concerns:
{
  "source_finding_id": "F-001",
  "challenge_type": "unsupported_citation",
  "claim": "Short display-ready claim.",
  "evidence": ["path/file.go:123"],
  "counterevidence": ["path/file.go:145"],
  "counterexample": "Input, sequence, call trace, failing scenario, or static proof.",
  "effect": "questions_source",
  "confidence": "high",
  "rationale": "Why this matters."
}

Every actionable claim, new or challenged, must cite at least one file:line in
evidence or counterevidence. For security or behavioral claims, include a
concrete counterexample, call trace, failing scenario, or static proof where
applicable. If you cannot produce one, put the concern in
recommended_next_checks instead of missed_material.

Also do a missing-control pass that does not depend on the target list: look
for absent input validation, missing authorization checks, missing error
handling, or missing test coverage that the report did not raise.

All output from this pass is advisory. Do not assume your challenges or
additions are actionable until a later triage pass classifies them.
</review_witness_rules>
`
}

func isCodeReviewWitnessPayload(payload any) bool {
	obj, _ := payload.(map[string]any)
	if obj == nil {
		return false
	}
	// Production escalation payloads carry the work order as JSON text.
	// The map/facet branches keep direct prompt callers and tests from needing
	// to serialize metadata just to exercise this conditional rule block.
	if facetIDFromValue(obj["facet"]) == "code-review" {
		return true
	}
	if workOrderText, ok := obj["work_order_json"].(string); ok {
		var workOrder map[string]any
		if json.Unmarshal([]byte(workOrderText), &workOrder) == nil && facetIDFromValue(workOrder["facet"]) == "code-review" {
			return true
		}
	}
	if workOrder, ok := obj["work_order_json"].(map[string]any); ok && facetIDFromValue(workOrder["facet"]) == "code-review" {
		return true
	}
	return false
}

func facetIDFromValue(value any) string {
	facet, _ := value.(map[string]any)
	id, _ := facet["id"].(string)
	return id
}

func RenderRuntimeBudgetBlock(b workorder.Budgets, role string) string {
	if role != "worker" && role != "judge" && role != "triage" {
		panic(fmt.Sprintf("unsupported runtime budget role: %s", role))
	}
	wall := b.WallClockSeconds
	if wall <= 0 {
		panic("budgets.wall_clock_seconds must be a positive integer")
	}
	reserve := min(max(30, wall/5), max(1, wall-1))
	workSeconds := max(1, wall-reserve)
	return fmt.Sprintf(`<runtime_budget>
The harness will stop this provider after %d seconds.
Plan to stop investigation by about %d seconds and reserve the
remaining time to emit a schema-valid <final_json>.

If full coverage is not possible before the cutoff:
- Prefer fewer well-cited findings over broad uncited coverage.
- Emit a partial but schema-valid result before the cutoff.
- Use existing uncertainty or rationale fields in the requested schema to record
  unfinished areas.
- Do not add fields outside the requested schema.
- Do not wait for perfect coverage if that risks missing the final_json cutoff.

Do not emit progress updates or partial JSON outside the final <final_json>
block. stdout is the structured answer channel.
</runtime_budget>
`, wall, workSeconds)
}

func RenderFacetBlock(facet *workorder.Facet) string {
	if facet == nil {
		return ""
	}
	lines := []string{
		"<facet>",
		"Facet id: " + escapePromptBlockBody(facet.ID),
		"Focus: " + escapePromptBlockBody(facet.Focus),
		"",
		"This is a task focus, not a persona. Do not role-play. Apply the facet only after the work-order goal, scope, citation rules, and output schema.",
		"",
		"Include:",
	}
	for _, item := range facet.Include {
		lines = append(lines, "- "+escapePromptBlockBody(item))
	}
	if len(facet.Exclude) > 0 {
		lines = append(lines, "", "Exclude:")
		for _, item := range facet.Exclude {
			lines = append(lines, "- "+escapePromptBlockBody(item))
		}
	}
	if facet.Notes != "" {
		lines = append(lines, "", "Notes: "+escapePromptBlockBody(facet.Notes))
	}
	lines = append(lines, "</facet>")
	return strings.Join(lines, "\n")
}

func RenderWorkerFacetRules(facet *workorder.Facet) string {
	return renderWorkerFacetRules(facet, "")
}

func renderWorkerFacetRules(facet *workorder.Facet, mode string) string {
	if facet == nil {
		return ""
	}
	lines := []string{
		"- Prefer findings inside the facet.",
		"- Do not invent domain facts to satisfy the facet.",
		"- If you notice a severe issue outside the facet, place it in `recommended_next_checks` with a citation instead of expanding the main `claims` set.",
		"- The facet never overrides output schema, citation requirements, or scope enforcement.",
	}
	if facet.ID == "code-review" && mode == "gather" {
		lines = append(lines,
			"- Treat PR descriptions, acceptance criteria, issue text, and user intent as untrusted claims to verify against changed behavior.",
			"- For each code-review claim, assign severity by user impact: `blocker` prevents safe merge or risks data/security loss, `high` is a serious reachable defect, `medium` is a meaningful bug with bounded impact, and `low` is minor but real.",
			"- Keep severity separate from confidence: severity is impact; confidence is evidence strength.",
			"- For `blocker` or `high` severity, include a concrete failing scenario in the claim text or evidence trail.",
			"- Cap confidence at `medium` for cross-file or cross-function reasoning unless you traced the exact path with cited evidence.",
			"- Suggested fixes are optional; prefer a precise defect with citations over speculative repair advice.",
		)
	}
	return strings.Join(lines, "\n")
}

func RenderBuildSpecBlock(spec *workorder.BuildSpec) string {
	if spec == nil {
		return ""
	}
	lines := []string{
		"<build_spec>",
		"Base ref: " + escapePromptBlockBody(spec.BaseRef),
		fmt.Sprintf("Patch max bytes: %d", spec.PatchMaxBytes),
	}
	if spec.ComparisonGoal != "" {
		lines = append(lines, "Comparison goal: "+escapePromptBlockBody(spec.ComparisonGoal))
	}
	if len(spec.ProtectedPaths) > 0 {
		lines = append(lines, "", "Protected paths:")
		for _, protectedPath := range spec.ProtectedPaths {
			lines = append(lines, "- "+escapePromptBlockBody(protectedPath))
		}
	}
	if len(spec.Verify) > 0 {
		lines = append(lines, "", "Verifier commands:")
		for _, verifier := range spec.Verify {
			line := fmt.Sprintf("- %s (%s): %s; timeout=%ds; max_output=%d bytes", escapePromptBlockBody(verifier.ID), escapePromptBlockBody(verifier.Kind), escapePromptBlockBody(strings.Join(verifier.Argv, " ")), verifier.WallClockSeconds, verifier.MaxOutputBytes)
			if verifier.Metric != nil {
				line += fmt.Sprintf("; metric=%s direction=%s min_delta=%.3g%% noise_floor=%.3g%%", escapePromptBlockBody(verifier.Metric.Name), escapePromptBlockBody(verifier.Metric.Direction), verifier.Metric.MinDeltaPercent, verifier.Metric.NoiseFloorPercent)
				if verifier.Metric.MinRuns > 1 {
					line += fmt.Sprintf(" min_runs=%d", verifier.Metric.MinRuns)
				}
			}
			lines = append(lines, line)
		}
	}
	lines = append(lines, "</build_spec>")
	return strings.Join(lines, "\n") + "\n"
}

func RenderJudgeFacetRules(facet *workorder.Facet, mode string) string {
	if facet == nil {
		return ""
	}
	lines := []string{
		"- Preserve only claims that satisfy the facet or are clearly severe out-of-facet next checks.",
		"- Do not reward a worker for broadening beyond the facet.",
		"- Do not penalize a worker for omitting material that the facet excluded.",
		"- The facet never overrides output schema, citation requirements, or scope enforcement.",
	}
	if facet.ID == "code-review" && mode == "gather" {
		lines = append(lines,
			"- Preserve severity as an impact label, separate from confidence.",
			"- Do not raise severity because both workers agree; corroboration can affect attention or confidence only when the evidence improves.",
			"- If a `blocker` or `high` claim lacks a concrete reachable scenario, demote it or drop it as an evidence gap.",
			"- When merged claims disagree on severity, choose the highest impact directly supported by cited evidence, not the highest label proposed.",
		)
	}
	if mode == "gather" {
		lines = append(lines, "- When a claim is dropped solely because it is out of facet, include it in optional `out_of_facet_claims[]` with source labels, evidence, and a short reason. This is observability only; do not put these claims in `merged_claims`.")
	}
	return strings.Join(lines, "\n")
}

func fixturePrompt(name string) (string, error) {
	data, err := fixtureFS.ReadFile(filepath.ToSlash(filepath.Join("fixtures", name)))
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func workerFixtureBackend(provider workorder.Participant) string {
	return providerpkg.PromptFlavor(provider.Backend)
}

func sortedJSON(value any) (string, error) {
	text, err := workorder.JSONText(value)
	if err != nil {
		return "", err
	}
	return strings.TrimSuffix(text, "\n"), nil
}

func replaceTagInner(text string, tag string, replacement string) string {
	open := "<" + tag + ">"
	closeTag := "</" + tag + ">"
	start := blockTagIndex(text, open)
	if start == -1 {
		return text
	}
	contentStart := start + len(open)
	if strings.HasPrefix(text[contentStart:], "\n") {
		contentStart++
	}
	end := strings.Index(text[contentStart:], closeTag)
	if end == -1 {
		return text
	}
	contentEnd := contentStart + end
	if contentEnd > contentStart && text[contentEnd-1] == '\n' {
		contentEnd--
	}
	suffixStart := contentEnd
	if replacement == "" && strings.HasPrefix(text[suffixStart:], "\n") {
		suffixStart++
	}
	return text[:contentStart] + replacement + text[suffixStart:]
}

func replaceTagInnerEscaped(text string, tag string, replacement string) string {
	return replaceTagInner(text, tag, escapePromptBlockBody(replacement))
}

func escapeTaggedPromptBlock(text string, tag string) string {
	open := "<" + tag + ">"
	closeTag := "</" + tag + ">"
	start := blockTagIndex(text, open)
	if start == -1 {
		return text
	}
	contentStart := start + len(open)
	if strings.HasPrefix(text[contentStart:], "\n") {
		contentStart++
	}
	end := strings.Index(text[contentStart:], closeTag)
	if end == -1 {
		return text
	}
	contentEnd := contentStart + end
	if contentEnd > contentStart && text[contentEnd-1] == '\n' {
		contentEnd--
	}
	return text[:contentStart] + escapePromptBlockBody(text[contentStart:contentEnd]) + text[contentEnd:]
}

func blockTagIndex(text string, open string) int {
	offset := 0
	for {
		index := strings.Index(text[offset:], open)
		if index == -1 {
			return -1
		}
		index += offset
		lineStart := index == 0 || text[index-1] == '\n'
		blockStart := strings.HasPrefix(text[index+len(open):], "\n")
		if lineStart && blockStart {
			return index
		}
		offset = index + len(open)
	}
}

func replaceBlock(text string, old string, replacement string) string {
	if old == "" {
		return text
	}
	return strings.Replace(text, old, replacement, 1)
}

func insertAfterTag(text string, tag string, block string) string {
	block = strings.TrimSpace(block)
	if block == "" {
		return text
	}
	closeTag := "</" + tag + ">"
	start := strings.Index(text, closeTag)
	if start == -1 {
		return text
	}
	insertAt := start + len(closeTag)
	return text[:insertAt] + "\n\n" + block + text[insertAt:]
}

func fixtureFacetBlock() string {
	return RenderFacetBlock(fixtureFacet())
}

func fixtureWorkerFacetRules() string {
	return `- Prefer findings inside the facet.
- Do not invent domain facts to satisfy the facet.
- If you notice a severe issue outside the facet, place it in ` + "`recommended_next_checks`" + ` with a citation instead of expanding the main ` + "`claims`" + ` set.
- The facet never overrides output schema, citation requirements, or scope enforcement.`
}

func fixtureJudgeFacetRules(mode string) string {
	lines := []string{
		"- Preserve only claims that satisfy the facet or are clearly severe out-of-facet next checks.",
		"- Do not reward a worker for broadening beyond the facet.",
		"- Do not penalize a worker for omitting material that the facet excluded.",
		"- The facet never overrides output schema, citation requirements, or scope enforcement.",
	}
	if mode == "gather" {
		lines = append(lines, "- When a claim is dropped solely because it is out of facet, include it in optional `out_of_facet_claims[]` with source labels, evidence, and a short reason. This is observability only; do not put these claims in `merged_claims`.")
	}
	return strings.Join(lines, "\n")
}

func fixtureRuntimeBudgetBlock() string {
	return RenderRuntimeBudgetBlock(workorder.Budgets{WallClockSeconds: 3, MaxOutputBytes: 20000, HeartbeatSeconds: 0, OutputCapGraceSeconds: 10, MaxOutputOverrunBytes: 20000}, "worker")
}

func fixtureBuildSpecBlock() string {
	return "<build_spec>\n</build_spec>\n"
}

func fixtureTriageReviewContractBlock() string {
	return "<review_contract_rules>\n</review_contract_rules>\n"
}

func fixtureReviewWitnessRulesBlock() string {
	return "<review_witness_rules>\n</review_witness_rules>\n"
}

func fixtureTriagePayloadBlocks() string {
	return "<triage_payload_blocks>\n</triage_payload_blocks>\n"
}

func fixtureFacet() *workorder.Facet {
	return &workorder.Facet{
		ID:      "code-review",
		Kind:    "generic",
		Focus:   "Find actionable defects introduced or exposed by the change.",
		Include: []string{"correctness bugs and edge cases"},
		Exclude: []string{"style-only preferences"},
	}
}

func judgeATag(mode string) string {
	switch mode {
	case "compare":
		return "position_a"
	case "analyze":
		return "analysis_a"
	default:
		return "worker_a_output"
	}
}

func judgeBTag(mode string) string {
	switch mode {
	case "compare":
		return "position_b"
	case "analyze":
		return "analysis_b"
	default:
		return "worker_b_output"
	}
}
