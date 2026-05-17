package triage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestShouldAutoTriageCodeReviewGather(t *testing.T) {
	workOrder := map[string]any{
		"type":  "gather",
		"facet": map[string]any{"id": CodeReviewFacetID},
	}
	decision := map[string]any{"decision_kind": "structured_union"}
	if reason := ShouldAutoTriage(workOrder, decision); reason == "" {
		t.Fatal("expected auto-triage reason")
	}
	decision["decision_kind"] = "tie"
	if reason := ShouldAutoTriage(workOrder, decision); reason != "" {
		t.Fatalf("tie should not auto-triage, got %q", reason)
	}
}

func TestSelectTriageSourceFindings(t *testing.T) {
	findings := []map[string]string{
		{"id": "F-001", "section": "Findings", "text": "bug in handler"},
		{"id": "F-002", "section": "Out-of-Facet Claims", "text": "style only"},
		{"id": "F-003", "section": "Primary Explanation", "text": "solid explanation"},
	}

	selected, skipped := SelectTriageSourceFindings(findings, CodeReviewFacetID)
	if len(selected) != 1 || selected[0]["id"] != "F-001" {
		t.Fatalf("selected = %#v", selected)
	}
	if len(skipped) != 2 || skipped[0]["skip_reason"] != "out_of_facet" {
		t.Fatalf("skipped = %#v", skipped)
	}
}

func TestCitationExtractionAndChecks(t *testing.T) {
	repo := t.TempDir()
	source := filepath.Join(repo, "src", "app.go")
	if err := os.MkdirAll(filepath.Dir(source), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(source, []byte("one\ntwo\nthree\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	text := "See src/app.go:2 and src/app.go:2-3, not https://example.com/app.go:1"
	citations := ExtractCitationsFromText(text)
	if len(citations) != 2 || citations[0] != "src/app.go:2" || citations[1] != "src/app.go:2-3" {
		t.Fatalf("citations = %#v", citations)
	}
	checks := CheckCitations([]string{"src/app.go:2", "src/missing.go:1", "../escape.go:1"}, repo)
	rawChecks := checks["checks"].([]any)
	statuses := []string{}
	for _, item := range rawChecks {
		statuses = append(statuses, item.(map[string]any)["status"].(string))
	}
	if strings.Join(statuses, ",") != "ok,missing_file,path_escape" {
		t.Fatalf("statuses = %#v", statuses)
	}
}

func TestRenderTriageMarkdownIncludesTypedSourceFilter(t *testing.T) {
	markdown := RenderTriageMarkdown(map[string]any{
		"run_id":                "run",
		"summary":               "checked",
		"source_finding_filter": map[string]int{"included": 1, "skipped_non_actionable": 2, "skipped_out_of_facet": 3},
		"items": []any{
			map[string]any{
				"id":                 "T-001",
				"source_finding":     "bug",
				"classification":     "real_issue",
				"recommended_action": "fix_now",
				"rationale":          "fix it",
			},
		},
		"unknowns": []any{},
	}, nil)
	if !strings.Contains(markdown, "## Source Findings") || !strings.Contains(markdown, "- Selected: `1`") {
		t.Fatalf("missing source filter section:\n%s", markdown)
	}
	if strings.Count(markdown, "[T-001]") != 1 {
		t.Fatalf("item rendered wrong number of times:\n%s", markdown)
	}
}
