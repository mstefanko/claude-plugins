package prompt

import (
	"embed"
	"fmt"
	"path/filepath"
	"strings"

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
	text = replaceTagInner(text, questionTag, wo.Goal)
	text = replaceTagInner(text, "context", wo.Background)
	text = replaceTagInner(text, "scope", scope)
	text = replaceBlock(text, fixtureFacetBlock(), RenderFacetBlock(wo.Facet))
	text = strings.Replace(text, fixtureWorkerFacetRules(), RenderWorkerFacetRules(wo.Facet), 1)
	text = replaceBlock(text, fixtureBuildSpecBlock(), RenderBuildSpecBlock(wo.Build))
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(wo.Budgets, "worker"))
	return text, nil
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
	text = replaceTagInner(text, "goal", wo.Goal)
	text = replaceTagInner(text, "background", wo.Background)
	text = replaceBlock(text, fixtureBuildSpecBlock(), RenderBuildSpecBlock(wo.Build))
	text = replaceTagInner(text, "shared_build_evidence", sharedPayload)
	text = replaceTagInner(text, judgeATag(actualMode), payloadA)
	text = replaceTagInner(text, judgeBTag(actualMode), payloadB)
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
		"Facet id: " + facet.ID,
		"Focus: " + facet.Focus,
		"",
		"This is a task focus, not a persona. Do not role-play. Apply the facet only after the work-order goal, scope, citation rules, and output schema.",
		"",
		"Include:",
	}
	for _, item := range facet.Include {
		lines = append(lines, "- "+item)
	}
	if len(facet.Exclude) > 0 {
		lines = append(lines, "", "Exclude:")
		for _, item := range facet.Exclude {
			lines = append(lines, "- "+item)
		}
	}
	if facet.Notes != "" {
		lines = append(lines, "", "Notes: "+facet.Notes)
	}
	lines = append(lines, "</facet>")
	return strings.Join(lines, "\n")
}

func RenderWorkerFacetRules(facet *workorder.Facet) string {
	if facet == nil {
		return ""
	}
	return `- Prefer findings inside the facet.
- Do not invent domain facts to satisfy the facet.
- If you notice a severe issue outside the facet, place it in ` + "`recommended_next_checks`" + ` with a citation instead of expanding the main ` + "`claims`" + ` set.
- The facet never overrides output schema, citation requirements, or scope enforcement.`
}

func RenderBuildSpecBlock(spec *workorder.BuildSpec) string {
	if spec == nil {
		return ""
	}
	lines := []string{
		"<build_spec>",
		"Base ref: " + spec.BaseRef,
		fmt.Sprintf("Patch max bytes: %d", spec.PatchMaxBytes),
	}
	if spec.ComparisonGoal != "" {
		lines = append(lines, "Comparison goal: "+spec.ComparisonGoal)
	}
	if len(spec.ProtectedPaths) > 0 {
		lines = append(lines, "", "Protected paths:")
		for _, protectedPath := range spec.ProtectedPaths {
			lines = append(lines, "- "+protectedPath)
		}
	}
	if len(spec.Verify) > 0 {
		lines = append(lines, "", "Verifier commands:")
		for _, verifier := range spec.Verify {
			line := fmt.Sprintf("- %s (%s): %s; timeout=%ds; max_output=%d bytes", verifier.ID, verifier.Kind, strings.Join(verifier.Argv, " "), verifier.WallClockSeconds, verifier.MaxOutputBytes)
			if verifier.Metric != nil {
				line += fmt.Sprintf("; metric=%s direction=%s min_delta=%.3g%% noise_floor=%.3g%%", verifier.Metric.Name, verifier.Metric.Direction, verifier.Metric.MinDeltaPercent, verifier.Metric.NoiseFloorPercent)
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
	if provider.Backend == "codex" {
		return "codex"
	}
	return "claude"
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
	start := strings.Index(text, open)
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
	return text[:contentStart] + replacement + text[contentEnd:]
}

func replaceBlock(text string, old string, replacement string) string {
	if old == "" {
		return text
	}
	return strings.Replace(text, old, replacement, 1)
}

func fixtureFacetBlock() string {
	return RenderFacetBlock(fixtureFacet())
}

func fixtureWorkerFacetRules() string {
	return RenderWorkerFacetRules(fixtureFacet())
}

func fixtureJudgeFacetRules(mode string) string {
	return RenderJudgeFacetRules(fixtureFacet(), mode)
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
