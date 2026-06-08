package triage

import (
	"encoding/json"
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
	decision["decision_kind"] = "single_provider_result"
	if reason := ShouldAutoTriage(workOrder, decision); reason != "" {
		t.Fatalf("single-provider result should not auto-triage, got %q", reason)
	}
	reason := ShouldRecommendTriage(workOrder, decision, "# report\n\n## Findings\n\n- **F-001** claim\n")
	if reason != "single-provider baseline; inspect provider output and run triage explicitly if needed" {
		t.Fatalf("single-provider recommendation = %q", reason)
	}
}

func TestShouldRecommendTriageSuppressesNonGatherModes(t *testing.T) {
	workOrder := map[string]any{
		"type": "compare",
	}
	decision := map[string]any{"decision_kind": "consensus"}
	report := "# report\n\n## Findings\n\n- **F-001** fallback to empty map on invalid decision reads\n"
	if reason := ShouldRecommendTriage(workOrder, decision, report); reason != "" {
		t.Fatalf("compare run should not recommend triage, got %q", reason)
	}
}

func TestShouldRecommendTriageUsesProseNotFindingBodiesForActionWords(t *testing.T) {
	workOrder := map[string]any{
		"type":  "gather",
		"facet": map[string]any{"id": CodeReviewFacetID},
	}
	decision := map[string]any{"decision_kind": "structured_union"}
	findingOnly := "# report\n\n## Findings\n\n- **F-001** fallback to empty map on invalid decision reads\n"
	reason := ShouldRecommendTriage(workOrder, decision, findingOnly)
	if strings.Contains(reason, "invalid") {
		t.Fatalf("finding-body action word should not drive reason, got %q", reason)
	}
	findingContinuation := "# report\n\n## Findings\n\n- **F-001** fallback to empty map\n  Evidence: invalid decision reads\n"
	reason = ShouldRecommendTriage(workOrder, decision, findingContinuation)
	if strings.Contains(reason, "invalid") {
		t.Fatalf("finding continuation action word should not drive reason, got %q", reason)
	}

	prose := "# report\n\n## Findings\n\nThis looks invalid and needs verification.\n\n- **F-001** actionable claim\n"
	reason = ShouldRecommendTriage(workOrder, decision, prose)
	if !strings.Contains(reason, "report mentions invalid") {
		t.Fatalf("prose action word should drive reason, got %q", reason)
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

func TestBuildEscalationFindingIndexSelectsProviderFindings(t *testing.T) {
	decision := map[string]any{
		"mode":          "escalation",
		"decision_kind": "escalation_advisory_supported",
		"assessment": map[string]any{
			"missed_material": []any{map[string]any{
				"source_finding_id": "new-01",
				"claim":             "Manifest telemetry drops fallback providers.",
				"evidence":          []any{"internal/manifest/manifest.go:376"},
			}},
			"material_errors": []any{map[string]any{
				"source_finding_id": "F-002",
				"claim":             "Original finding overstates the evidence.",
			}},
		},
	}

	findings := BuildEscalationFindingIndex(decision)
	if len(findings) != 2 {
		t.Fatalf("findings = %#v", findings)
	}
	if findings[0]["id"] != "new-01" || findings[0]["source"] != "escalation_provider" || findings[0]["section"] != "Missed Material" {
		t.Fatalf("missed material finding = %#v", findings[0])
	}
	if findings[1]["id"] == "F-002" || findings[1]["source_finding_id"] != "F-002" || findings[1]["section"] != "Material Errors" {
		t.Fatalf("material error finding should avoid colliding with source finding IDs: %#v", findings[1])
	}
	selected, skipped := SelectTriageSourceFindings(findings, CodeReviewFacetID)
	if len(selected) != 2 || len(skipped) != 0 {
		t.Fatalf("selected=%#v skipped=%#v", selected, skipped)
	}
	streams := SummarizeFindingStreams(findings)
	if streams["escalation_provider"] != 2 {
		t.Fatalf("streams = %#v", streams)
	}
}

func TestBuildEscalationFindingIndexAvoidsGeneratedIDCollisions(t *testing.T) {
	decision := map[string]any{
		"mode":            "escalation",
		"missed_material": []any{map[string]any{"claim": "top missed"}},
		"assessment": map[string]any{
			"missed_material": []any{map[string]any{"claim": "assessment missed"}},
		},
	}
	findings := BuildEscalationFindingIndex(decision)
	if len(findings) != 2 {
		t.Fatalf("findings = %#v", findings)
	}
	if findings[0]["id"] == findings[1]["id"] {
		t.Fatalf("generated IDs collided: %#v", findings)
	}
	if findings[0]["id"] != "ESC-TOP-MISSED-001" || findings[1]["id"] != "ESC-ASSESSMENT-MISSED-001" {
		t.Fatalf("unexpected generated IDs: %#v", findings)
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

func TestComputeInputHashesIncludesCompleteReviewContextSet(t *testing.T) {
	runDir := t.TempDir()
	for name, text := range map[string]string{
		"decision.json":          "{}\n",
		"report.md":              "# report\n",
		"work-order.json":        "{}\n",
		"source-work-order.json": "{}\n",
		"review-context.md":      "context\n",
		"review-context.json":    "{}\n",
	} {
		if err := os.WriteFile(filepath.Join(runDir, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	hashes, err := ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	if hashes["provider_failures_sha256"] == "" {
		t.Fatalf("missing provider failure hash in %#v", hashes)
	}
	for _, key := range []string{"source_work_order_sha256", "review_context_md_sha256", "review_context_json_sha256"} {
		if hashes[key] == "" {
			t.Fatalf("missing %s in %#v", key, hashes)
		}
	}
}

func TestStateDetailMarksReviewContextHashChangesStale(t *testing.T) {
	runDir := t.TempDir()
	for name, text := range map[string]string{
		"decision.json":          "{}\n",
		"report.md":              "# report\n",
		"work-order.json":        "{}\n",
		"source-work-order.json": "{}\n",
		"review-context.md":      "context\n",
		"review-context.json":    "{}\n",
	} {
		if err := os.WriteFile(filepath.Join(runDir, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	hashes, err := ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	triageDir := filepath.Join(runDir, "triage")
	if err := os.MkdirAll(triageDir, 0o755); err != nil {
		t.Fatal(err)
	}
	final := `{"input_hashes":{"decision_sha256":"` + hashes["decision_sha256"] + `","report_sha256":"` + hashes["report_sha256"] + `","work_order_sha256":"` + hashes["work_order_sha256"] + `","source_work_order_sha256":"` + hashes["source_work_order_sha256"] + `","review_context_md_sha256":"` + hashes["review_context_md_sha256"] + `","review_context_json_sha256":"` + hashes["review_context_json_sha256"] + `"}}`
	if err := os.WriteFile(filepath.Join(triageDir, "final.json"), []byte(final), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(triageDir, "triage.md"), []byte("# triage\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "review-context.md"), []byte("changed\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	state, stale := StateDetail(runDir)
	if state != "stale" || !contains(stale, "review-context.md") {
		t.Fatalf("state=%s stale=%#v", state, stale)
	}
}

func TestStateDetailMarksProviderFailureHashChangesStale(t *testing.T) {
	runDir := t.TempDir()
	for name, text := range map[string]string{
		"decision.json":   "{}\n",
		"report.md":       "# report\n",
		"work-order.json": "{}\n",
	} {
		if err := os.WriteFile(filepath.Join(runDir, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(filepath.Join(runDir, "providers", "claude"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "providers", "claude", "failure.json"), []byte(`{"status":"exit_error"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	hashes, err := ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	triageDir := filepath.Join(runDir, "triage")
	if err := os.MkdirAll(triageDir, 0o755); err != nil {
		t.Fatal(err)
	}
	final := `{"input_hashes":{"decision_sha256":"` + hashes["decision_sha256"] + `","report_sha256":"` + hashes["report_sha256"] + `","work_order_sha256":"` + hashes["work_order_sha256"] + `","provider_failures_sha256":"` + hashes["provider_failures_sha256"] + `"}}`
	if err := os.WriteFile(filepath.Join(triageDir, "final.json"), []byte(final), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(triageDir, "triage.md"), []byte("# triage\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "providers", "claude", "failure.json"), []byte(`{"status":"timeout"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	state, stale := StateDetail(runDir)
	if state != "stale" || !contains(stale, "providers/*/failure.json") {
		t.Fatalf("state=%s stale=%#v", state, stale)
	}
}

func TestStateDetailMarksTriageInputArtifactsStale(t *testing.T) {
	tests := []struct {
		name     string
		file     string
		wantPath string
	}{
		{name: "source finding filter", file: "source_finding_filter.json", wantPath: "triage/source_finding_filter.json"},
		{name: "citation checks", file: "citation_checks.json", wantPath: "triage/citation_checks.json"},
		{name: "finding index", file: "finding_index.json", wantPath: "triage/finding_index.json"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := t.TempDir()
			for name, text := range map[string]string{
				"decision.json":   "{}\n",
				"report.md":       "# report\n",
				"work-order.json": "{}\n",
			} {
				if err := os.WriteFile(filepath.Join(runDir, name), []byte(text), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			triageDir := filepath.Join(runDir, "triage")
			if err := os.MkdirAll(triageDir, 0o755); err != nil {
				t.Fatal(err)
			}
			for _, name := range []string{"source_finding_filter.json", "citation_checks.json", "finding_index.json"} {
				if err := os.WriteFile(filepath.Join(triageDir, name), []byte(`{"version":1}`), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			hashes, err := ComputeInputHashes(runDir)
			if err != nil {
				t.Fatal(err)
			}
			final := map[string]any{"input_hashes": hashes, "items": []any{}}
			data, err := json.Marshal(final)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(triageDir, "final.json"), data, 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(triageDir, "triage.md"), []byte("# triage\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(triageDir, tt.file), []byte(`{"version":2}`), 0o644); err != nil {
				t.Fatal(err)
			}

			state, stale := StateDetail(runDir)
			if state != "stale" || !contains(stale, tt.wantPath) {
				t.Fatalf("state=%s stale=%#v", state, stale)
			}
		})
	}
}

func contains(items []string, value string) bool {
	for _, item := range items {
		if item == value {
			return true
		}
	}
	return false
}
