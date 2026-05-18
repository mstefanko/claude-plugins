package triage

import (
	"strings"
	"testing"
)

func TestRenderTriageMarkdownFormatsRichItems(t *testing.T) {
	text := RenderTriageMarkdown(map[string]any{
		"run_id":  "run-1",
		"summary": "Review complete.",
		"source_finding_filter": map[string]any{
			"included":               2,
			"skipped_non_actionable": 1,
			"skipped_out_of_facet":   0,
		},
		"items": []any{
			map[string]any{
				"id":                 "T-001",
				"source_finding_id":  "F-001",
				"source_finding":     "Report line\nwith   spaces",
				"classification":     "real_issue",
				"severity":           "high",
				"confidence":         "medium",
				"recommended_action": "fix_now",
				"supporting_evidence": []any{
					"internal/a.go:10",
				},
				"counterevidence":    []any{"tests/a_test.go:42"},
				"citation_check_ids": []any{"C-001", "C-002"},
				"rationale":          "Line one\n\nline two.",
			},
			map[string]any{
				"id":                 "T-002",
				"source_finding_id":  "F-002",
				"classification":     "false_positive",
				"recommended_action": "ignore",
				"rationale":          "Not actionable.",
			},
		},
		"unknowns": []any{},
	}, []string{"caveat"})

	for _, want := range []string{
		"- [T-001] **real_issue** · severity=high · confidence=medium · action=fix_now",
		"  Source: Report line with spaces",
		"  Rationale: Line one line two.",
		"  Supporting evidence: internal/a.go:10",
		"  Counter-evidence: tests/a_test.go:42",
		"  Citation checks: C-001, C-002",
		"- [T-002] **false_positive** · action=ignore",
		"  Source: F-002",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("triage markdown missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "severity= ·") || strings.Contains(text, "confidence= ·") {
		t.Fatalf("empty tokens should be suppressed:\n%s", text)
	}
}
