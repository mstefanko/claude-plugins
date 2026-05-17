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
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(wo.Budgets, "worker"))
	return text, nil
}

func BuildJudgePrompt(wo *workorder.WorkOrder, workerA any, workerB any, mode string) (string, error) {
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
	text := base
	text = replaceBlock(text, fixtureFacetBlock(), RenderFacetBlock(wo.Facet))
	text = strings.Replace(text, fixtureJudgeFacetRules(actualMode), RenderJudgeFacetRules(wo.Facet, actualMode), 1)
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
	payloadJSON, err := sortedJSON(payload)
	if err != nil {
		return "", err
	}
	text := base
	text = replaceBlock(text, fixtureRuntimeBudgetBlock(), RenderRuntimeBudgetBlock(budgets, "triage"))
	text = replaceTagInner(text, "triage_payload", payloadJSON)
	return text, nil
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
