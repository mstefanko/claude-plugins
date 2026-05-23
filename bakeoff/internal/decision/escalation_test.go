package decision

import "testing"

func TestResolveEscalationSynthesisClassifiesOutcomes(t *testing.T) {
	tests := []struct {
		name         string
		sourceWinner string
		effect       string
		recommended  any
		wantKind     string
		wantWinner   any
	}{
		{
			name:         "supports source winner",
			sourceWinner: "claude",
			effect:       "supports_source",
			recommended:  nil,
			wantKind:     EscalationSupportsSource,
			wantWinner:   "claude",
		},
		{
			name:         "changes source winner",
			sourceWinner: "claude",
			effect:       "changes_winner",
			recommended:  "gemini",
			wantKind:     EscalationChangedWinner,
			wantWinner:   "gemini",
		},
		{
			name:         "recommends winner for unresolved source",
			sourceWinner: "",
			effect:       "recommends_winner",
			recommended:  "gemini",
			wantKind:     EscalationRecommendsWinner,
			wantWinner:   "gemini",
		},
		{
			name:         "recommends existing source winner supports source",
			sourceWinner: "claude",
			effect:       "recommends_winner",
			recommended:  "claude",
			wantKind:     EscalationSupportsSource,
			wantWinner:   "claude",
		},
		{
			name:         "recommends different winner changes source",
			sourceWinner: "claude",
			effect:       "recommends_winner",
			recommended:  "gemini",
			wantKind:     EscalationChangedWinner,
			wantWinner:   "gemini",
		},
		{
			name:         "thin evidence stays unresolved",
			sourceWinner: "claude",
			effect:       "still_unresolved",
			recommended:  nil,
			wantKind:     EscalationStillUnresolved,
			wantWinner:   nil,
		},
		{
			name:         "changes winner without recommendation stays unresolved",
			sourceWinner: "claude",
			effect:       "changes_winner",
			recommended:  nil,
			wantKind:     EscalationStillUnresolved,
			wantWinner:   nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			input := escalationInput(tt.sourceWinner)
			decision := ResolveEscalationSynthesis(input, map[string]any{
				"source_decision_effect": tt.effect,
				"recommended_winner":     tt.recommended,
			})
			if decision["decision_kind"] != tt.wantKind || decision["canonical_winner"] != tt.wantWinner {
				t.Fatalf("decision=%#v, want kind=%s winner=%#v", decision, tt.wantKind, tt.wantWinner)
			}
			if tt.wantWinner != nil && decision["selection_basis"] != SelectionBasisEscalationSynthesis {
				t.Fatalf("selection basis missing on winner path: %#v", decision)
			}
		})
	}
}

func TestResolveEscalationAdvisoryModes(t *testing.T) {
	input := escalationInput("claude")
	witness := ResolveEscalationWitness(input, map[string]any{"assessment": "supported", "source_decision_effect": "supports_source"})
	if witness["decision_kind"] != EscalationAdvisorySupported || witness["canonical_winner"] != nil {
		t.Fatalf("supported witness decision=%#v", witness)
	}
	challengedWitness := ResolveEscalationWitness(input, map[string]any{"assessment": "unsupported", "source_decision_effect": "challenges_source"})
	if challengedWitness["decision_kind"] != EscalationAdvisoryChallenged || challengedWitness["canonical_winner"] != nil {
		t.Fatalf("challenged witness decision=%#v", challengedWitness)
	}
	dispute := ResolveEscalationDispute(input, map[string]any{"outcome_effect": "no_material_change", "source_decision_effect": "questions_source"})
	if dispute["decision_kind"] != EscalationAdvisorySupported || dispute["canonical_winner"] != nil {
		t.Fatalf("supported dispute decision=%#v", dispute)
	}
	challengedDispute := ResolveEscalationDispute(input, map[string]any{"outcome_effect": "challenges_existing", "source_decision_effect": "challenges_source"})
	if challengedDispute["decision_kind"] != EscalationAdvisoryChallenged || challengedDispute["canonical_winner"] != nil {
		t.Fatalf("challenged dispute decision=%#v", challengedDispute)
	}
}

func TestEscalationGatherUnionAndFailedDecision(t *testing.T) {
	input := escalationInput("")
	union := ResolveEscalationGatherUnion(input, map[string]any{"merged_claims": []any{}})
	if union["decision_kind"] != EscalationSupportsSource || union["selection_basis"] != "escalation_union" || union["judge_completed"] != true {
		t.Fatalf("union decision=%#v", union)
	}
	if union["canonical_winner"] != nil {
		t.Fatalf("union should not set winner: %#v", union)
	}
	failed := EscalationFailedDecision(input, "judge failed")
	if failed["decision_kind"] != EscalationFailed || failed["stalled_at"] != StalledAtJudge || failed["canonical_winner"] != nil {
		t.Fatalf("failed decision=%#v", failed)
	}
}

func TestEscalationBaseDeepClonesProviderStatuses(t *testing.T) {
	input := escalationInput("claude")
	nested := map[string]any{"status": "ok", "scope_enforcement": map[string]any{"effective_scope": "codebase"}, "warnings": []any{map[string]any{"text": "before"}}}
	input.ProviderStatuses["claude"] = nested
	out := EscalationBase(input)

	nested["status"] = "mutated"
	nested["scope_enforcement"].(map[string]any)["effective_scope"] = "web"
	nested["warnings"].([]any)[0].(map[string]any)["text"] = "after"

	statuses := out["provider_statuses"].(map[string]any)
	clone := statuses["claude"].(map[string]any)
	if clone["status"] != "ok" {
		t.Fatalf("top-level status was mutated through source map: %#v", clone)
	}
	if clone["scope_enforcement"].(map[string]any)["effective_scope"] != "codebase" {
		t.Fatalf("nested map was not deep-cloned: %#v", clone)
	}
	if clone["warnings"].([]any)[0].(map[string]any)["text"] != "before" {
		t.Fatalf("nested slice was not deep-cloned: %#v", clone)
	}
}

func escalationInput(sourceWinner string) EscalationBaseInput {
	var winner any
	if sourceWinner != "" {
		winner = sourceWinner
	}
	return EscalationBaseInput{
		SourceMode:      "compare",
		EscalationMode:  "independent",
		SourceRunID:     "source",
		AddedProvider:   "gemini",
		SourceProviders: []string{"claude", "codex"},
		SourceDecision: map[string]any{
			"decision_kind":    "pick_winner",
			"canonical_winner": winner,
		},
		ProviderStatuses: map[string]any{
			"codex": map[string]any{"status": "ok"},
		},
	}
}
