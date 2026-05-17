package triage

import "testing"

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
