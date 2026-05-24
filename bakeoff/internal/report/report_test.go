package report

import (
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestRenderIncludesDecisionAuditAndProviderStatus(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "gather"},
		map[string]any{
			"mode":              "gather",
			"decision_kind":     "both_failed",
			"judge_ran":         false,
			"stalled_at":        "providers",
			"provider_statuses": map[string]any{"claude": map[string]any{"status": "exit_error", "stderr_path": "providers/claude/stderr.txt"}},
			"caveats":           []string{"both providers failed; judge skipped"},
		},
		map[string]map[string]any{},
		map[string]map[string]any{},
		RenderOptions{RunID: "run-1", OutDir: "runs"},
	)

	for _, want := range []string{
		"# Bakeoff Report: sample",
		"## Outcome",
		"Decision: `both_failed`",
		"Stalled at: `providers`",
		"Result: `both_failed`",
		"Next: `bakeoff show run-1`",
		"- Stalled at: `providers`",
		"| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |",
		"| `claude` | `exit_error` |",
		"both providers failed; judge skipped",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	if strings.Index(text, "## Outcome") > strings.Index(text, "## Decision Audit") {
		t.Fatalf("Outcome should precede Decision Audit:\n%s", text)
	}
	if strings.Contains(text, "- `claude`: `exit_error`") {
		t.Fatalf("provider status still rendered in bullet form:\n%s", text)
	}
}

func TestRenderOutcomeByMode(t *testing.T) {
	cases := []struct {
		name     string
		wo       *workorder.WorkOrder
		decision map[string]any
		want     string
	}{
		{
			name: "gather",
			wo:   &workorder.WorkOrder{ID: "gather-sample", Type: "gather"},
			decision: map[string]any{
				"mode":              "gather",
				"decision_kind":     "structured_union",
				"judge_ran":         true,
				"provider_statuses": map[string]any{},
			},
			want: "Result: `structured_union`",
		},
		{
			name: "compare",
			wo:   &workorder.WorkOrder{ID: "compare-sample", Type: "compare"},
			decision: map[string]any{
				"mode":              "compare",
				"decision_kind":     "pick_winner",
				"canonical_winner":  "claude",
				"judge_ran":         true,
				"provider_statuses": map[string]any{},
			},
			want: "Winner: `claude`",
		},
		{
			name: "compare consensus",
			wo:   &workorder.WorkOrder{ID: "compare-consensus", Type: "compare"},
			decision: map[string]any{
				"mode":              "compare",
				"decision_kind":     "consensus",
				"canonical_winner":  nil,
				"judge_ran":         true,
				"provider_statuses": map[string]any{},
			},
			want: "Result: both providers agreed",
		},
		{
			name: "analyze",
			wo:   &workorder.WorkOrder{ID: "analyze-sample", Type: "analyze"},
			decision: map[string]any{
				"mode":              "analyze",
				"decision_kind":     "pick_winner",
				"canonical_winner":  "codex",
				"judge_ran":         true,
				"provider_statuses": map[string]any{},
			},
			want: "Winner: `codex`",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			text := Render(tc.wo, tc.decision, map[string]map[string]any{}, map[string]map[string]any{}, RenderOptions{RunID: "run-1", OutDir: "runs"})
			if !strings.Contains(text, tc.want) {
				t.Fatalf("report missing %q:\n%s", tc.want, text)
			}
			if strings.Index(text, "## Outcome") > strings.Index(text, "## Decision Audit") {
				t.Fatalf("Outcome should precede Decision Audit:\n%s", text)
			}
		})
	}
}

func TestRenderConsensusUsesClearAuditAndDivergenceHeading(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "compare"},
		map[string]any{
			"mode":              "compare",
			"decision_kind":     "consensus",
			"judge_ran":         true,
			"provider_statuses": map[string]any{},
			"judge_passes": map[string]any{
				"pass1": map[string]any{"A": "claude", "B": "codex", "canonical_winner": nil, "positional_winner": "", "relation": "consensus"},
			},
			"consensus_strongest":     []any{"same answer"},
			"consensus_disagreements": []any{"different caveat"},
		},
		map[string]map[string]any{},
		map[string]map[string]any{},
		RenderOptions{},
	)
	for _, want := range []string{
		"Result: both providers agreed",
		"relation=consensus, no positional winner",
		"### Sub-Claim Divergences",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	for _, unwanted := range []string{"positional ``", "### Consensus Disagreements", "Result: `consensus`"} {
		if strings.Contains(text, unwanted) {
			t.Fatalf("report contains unwanted %q:\n%s", unwanted, text)
		}
	}
}

func TestRenderProviderStatusShowsStderrKind(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "gather"},
		map[string]any{
			"mode":          "gather",
			"decision_kind": "single_provider_only",
			"judge_ran":     false,
			"provider_statuses": map[string]any{
				"codex": map[string]any{"status": "ok", "stderr_bytes": 1024, "stderr_kind": "transport_noise", "stderr_path": "providers/codex/stderr.txt"},
			},
			"canonical_winner": "codex",
		},
		map[string]map[string]any{"codex": {"final_json": map[string]any{"claims": []any{}, "unknowns": []any{}}}},
		map[string]map[string]any{},
		RenderOptions{},
	)
	if !strings.Contains(text, "stderr kind: transport_noise") {
		t.Fatalf("report missing stderr kind:\n%s", text)
	}
}

func TestRenderProviderStatusShowsFailureKind(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "gather"},
		map[string]any{
			"mode":          "gather",
			"decision_kind": "both_failed",
			"judge_ran":     false,
			"provider_statuses": map[string]any{
				"claude": map[string]any{"status": "exit_error", "failure_kind": "auth_or_permission", "stderr_path": "providers/claude/stderr.txt"},
			},
		},
		map[string]map[string]any{},
		map[string]map[string]any{},
		RenderOptions{},
	)
	if !strings.Contains(text, "failure kind: auth_or_permission") {
		t.Fatalf("report missing failure kind:\n%s", text)
	}
}

func TestRenderSingleProviderOnlyNotesTimedOutOrSalvagedPeer(t *testing.T) {
	cases := []struct {
		name       string
		peerStatus map[string]any
		want       string
	}{
		{
			name:       "timeout",
			peerStatus: map[string]any{"status": "timeout", "failure_kind": "quiet_stdout"},
			want:       "Partial result: `codex` timed out (`quiet_stdout`), so this lens is single-provider-only and surfaces only `claude`.",
		},
		{
			name:       "salvaged",
			peerStatus: map[string]any{"status": "salvaged", "salvage": map[string]any{"source": "last-message.txt"}},
			want:       "Partial result: `codex` was salvaged from `last-message.txt` but did not complete successfully, so this lens is single-provider-only and surfaces only `claude`.",
		},
	}
	for _, tc := range cases {
		for _, mode := range []string{"gather", "compare", "analyze"} {
			t.Run(tc.name+"/"+mode, func(t *testing.T) {
				text := Render(
					&workorder.WorkOrder{ID: "sample", Type: mode},
					map[string]any{
						"mode":          mode,
						"decision_kind": "single_provider_only",
						"judge_ran":     false,
						"provider_statuses": map[string]any{
							"claude": map[string]any{"status": "ok"},
							"codex":  tc.peerStatus,
						},
						"canonical_winner": "claude",
					},
					map[string]map[string]any{"claude": {"final_json": map[string]any{"claims": []any{}, "unknowns": []any{}}}},
					map[string]map[string]any{},
					RenderOptions{},
				)
				if !strings.Contains(text, tc.want) {
					t.Fatalf("report missing partial note %q:\n%s", tc.want, text)
				}
			})
		}
	}
}

func TestRenderFailedJudgeShowsStatusAndProviderClaims(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{
			ID:   "sample",
			Type: "gather",
			Providers: []workorder.Participant{
				{ID: "claude"},
				{ID: "codex"},
			},
		},
		map[string]any{
			"mode":              "gather",
			"decision_kind":     "provider_union_only",
			"judge_ran":         true,
			"judge_attempted":   true,
			"judge_completed":   false,
			"judge_error_kind":  "api_transient",
			"provider_statuses": map[string]any{},
			"caveats":           []any{"gather judge failed with exit_error"},
		},
		map[string]map[string]any{
			"claude": {"final_json": map[string]any{"claims": []any{map[string]any{"claim": "Claude claim", "confidence": "high"}}, "unknowns": []any{"claude unknown"}}},
			"codex":  {"final_json": map[string]any{"claims": []any{map[string]any{"claim": "Codex claim", "confidence": "medium"}}, "unknowns": []any{"codex unknown"}}},
		},
		map[string]map[string]any{"pass1": {}},
		RenderOptions{RunID: "run-1", OutDir: "runs"},
	)
	for _, want := range []string{
		"## Status",
		"Action: judge failed; provider claims below; consider `bakeoff rerun run-1 --judge-only`.",
		"### claude",
		"Claude claim",
		"### codex",
		"Codex claim",
		"Judge error kind: `api_transient`",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	if strings.Index(text, "## Status") > strings.Index(text, "## Outcome") {
		t.Fatalf("Status should precede Outcome:\n%s", text)
	}
	if strings.Contains(text, "## Conflicts") {
		t.Fatalf("failed judge report should not render judge conflicts:\n%s", text)
	}
}

func TestRenderProviderStatusInlinesObservedBytesWhenTruncated(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "gather"},
		map[string]any{
			"mode":          "gather",
			"decision_kind": "both_failed",
			"judge_ran":     false,
			"provider_statuses": map[string]any{
				"claude": map[string]any{
					"status":                "exit_error",
					"stdout_bytes":          4096,
					"stdout_observed_bytes": 18637,
					"stdout_truncated":      true,
					"stderr_bytes":          4096,
					"stderr_observed_bytes": 18637,
					"stderr_truncated":      true,
				},
			},
		},
		map[string]map[string]any{},
		map[string]map[string]any{},
		RenderOptions{},
	)
	if !strings.Contains(text, "4.0 KB (trunc, +14.2 KB)") {
		t.Fatalf("report missing observed byte cell:\n%s", text)
	}
	if strings.Contains(text, "stdout observed") || strings.Contains(text, "stderr observed") {
		t.Fatalf("observed bytes duplicated in notes:\n%s", text)
	}
}

func TestRenderEscalationDisputeItemsAvoidRawMapLiterals(t *testing.T) {
	text := RenderEscalation(
		&workorder.WorkOrder{ID: "sample", Type: "compare"},
		map[string]any{
			"decision_kind":    "escalation_advisory_supported",
			"escalation_mode":  "dispute",
			"added_provider":   "gemini",
			"source_providers": []any{"claude", "codex"},
			"source_mode":      "compare",
			"source_decision":  map[string]any{"decision_kind": "tie"},
			"canonical_winner": nil,
			"selection_basis":  "",
			"dispute": map[string]any{
				"outcome_effect": "no_material_change",
				"resolved_points": []any{map[string]any{
					"id":         "D-001",
					"resolution": "The existing evidence is sufficient.",
					"evidence":   []any{"report.md:42"},
				}},
				"unresolved_points": []any{map[string]any{
					"id":     "D-002",
					"answer": "The follow-up remains open.",
				}},
				"new_evidence": []any{
					map[string]any{"point_id": "D-003", "evidence": []any{"packet:9"}},
					map[string]any{"z": "last", "a": "first"},
				},
			},
		},
		nil,
		map[string]any{"points": []any{map[string]any{"id": "D-001"}}},
		EscalationRenderOptions{RunID: "run-1", OutDir: "runs", SourceRunID: "source"},
	)
	for _, want := range []string{
		"- **D-001** The existing evidence is sufficient.",
		"Evidence: report.md:42",
		"- **D-002** The follow-up remains open.",
		"- **D-003**",
		"Evidence: packet:9",
		`- {"a":"first","z":"last"}`,
		"advisory escalation supports the source decision",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "map[") {
		t.Fatalf("report leaked map literal:\n%s", text)
	}
}

func TestRenderEscalationWitnessStructuredItems(t *testing.T) {
	text := RenderEscalation(
		&workorder.WorkOrder{ID: "sample", Type: "gather"},
		map[string]any{
			"decision_kind":    "escalation_advisory_challenged",
			"escalation_mode":  "witness",
			"added_provider":   "gemini",
			"source_providers": []any{"claude", "codex"},
			"source_mode":      "gather",
			"source_decision":  map[string]any{"decision_kind": "structured_union"},
			"canonical_winner": nil,
			"selection_basis":  "",
			"assessment": map[string]any{
				"assessment":             "questionable",
				"source_decision_effect": "questions_source",
				"confidence":             "medium",
				"would_change_outcome":   false,
				"recommended_action":     "inspect",
				"material_errors": []any{map[string]any{
					"source_finding_id": "F-001",
					"challenge_type":    "unsupported_citation",
					"claim":             "The cited code does not support the source claim.",
					"evidence":          []any{"internal/example.go:12"},
					"counterevidence":   []any{"internal/example.go:18"},
					"counterexample":    "Request with an empty body returns before mutation.",
					"effect":            "questions_source",
					"confidence":        "high",
				}},
				"missed_material": []any{map[string]any{
					"claim":      "A validation gap was missed.",
					"evidence":   []any{"internal/example.go:22"},
					"confidence": "medium",
					"effect":     "questions_source",
				}},
				"triage_concerns": []any{map[string]any{
					"source_finding_id": "F-002",
					"claim":             "Recommended action should be reproduce, not fix_now.",
					"evidence":          []any{"triage/final.json"},
				}},
			},
		},
		nil,
		nil,
		EscalationRenderOptions{RunID: "run-1", OutDir: "runs", SourceRunID: "source"},
	)
	for _, want := range []string{
		"- **F-001** `unsupported_citation`: The cited code does not support the source claim.",
		"Evidence: internal/example.go:12",
		"Counter-evidence: internal/example.go:18",
		"Counterexample: Request with an empty body returns before mutation.",
		"effect `questions_source`, confidence `high`",
		"- A validation gap was missed.",
		"- **F-002** Recommended action should be reproduce, not fix_now.",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "map[") {
		t.Fatalf("report leaked map literal:\n%s", text)
	}
}

func TestRenderKnownGenericItemsPreserveNonEscalationOutput(t *testing.T) {
	text := Render(
		&workorder.WorkOrder{ID: "sample", Type: "compare"},
		map[string]any{
			"mode":              "compare",
			"decision_kind":     "consensus",
			"judge_ran":         true,
			"provider_statuses": map[string]any{},
			"consensus_strongest": []any{map[string]any{
				"claim":           "Same strongest point",
				"evidence":        []any{"report.md:7"},
				"source_provider": "claude",
			}},
			"consensus_disagreements": []any{},
		},
		map[string]map[string]any{},
		map[string]map[string]any{},
		RenderOptions{},
	)
	for _, want := range []string{
		"- **F-001** Same strongest point",
		"Evidence: report.md:7",
		"Source: `claude`",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "map[") {
		t.Fatalf("known generic item leaked map literal:\n%s", text)
	}
}
