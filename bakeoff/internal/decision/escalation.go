package decision

import "github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"

const (
	EscalationSupportsSource     = "escalation_supports_source"
	EscalationChangedWinner      = "escalation_changed_winner"
	EscalationRecommendsWinner   = "escalation_recommends_winner"
	EscalationStillUnresolved    = "escalation_still_unresolved"
	EscalationAdvisorySupported  = "escalation_advisory_supported"
	EscalationAdvisoryChallenged = "escalation_advisory_challenged"
	EscalationFailed             = "escalation_failed"

	SelectionBasisEscalationSynthesis = "escalation_synthesis"
)

type EscalationBaseInput struct {
	SourceMode       string
	EscalationMode   string
	SourceRunID      string
	AddedProvider    string
	SourceProviders  []string
	SourceDecision   map[string]any
	ProviderStatuses map[string]any
}

func SourceDecisionSummary(sourceDecision map[string]any) map[string]any {
	out := map[string]any{
		"decision_kind":    sourceDecision["decision_kind"],
		"canonical_winner": sourceDecision["canonical_winner"],
	}
	for _, key := range []string{"selection_basis", "stalled_at", "spine_tiebreak", "judge_error_kind"} {
		if value, ok := sourceDecision[key]; ok {
			out[key] = value
		}
	}
	return out
}

func EscalationBase(input EscalationBaseInput) map[string]any {
	return map[string]any{
		"mode":              "escalation",
		"source_mode":       input.SourceMode,
		"escalation_mode":   input.EscalationMode,
		"source_run_id":     input.SourceRunID,
		"added_provider":    input.AddedProvider,
		"source_providers":  append([]string(nil), input.SourceProviders...),
		"source_decision":   SourceDecisionSummary(input.SourceDecision),
		"provider_statuses": cloneAnyMap(input.ProviderStatuses),
		"canonical_winner":  nil,
		"judge_rationale":   []string{},
		"caveats":           []string{},
	}
}

func EscalationFailedDecision(input EscalationBaseInput, reason string) map[string]any {
	out := EscalationBase(input)
	out["decision_kind"] = EscalationFailed
	out["judge_ran"] = false
	out["canonical_winner"] = nil
	if reason != "" {
		out["caveats"] = []string{reason}
	}
	SetStalledAt(out, StalledAtJudge)
	return out
}

func ResolveEscalationWitness(input EscalationBaseInput, witness map[string]any) map[string]any {
	out := EscalationBase(input)
	out["judge_ran"] = false
	out["canonical_winner"] = nil
	out["assessment"] = witness
	if jsonutil.StringValue(witness["assessment"]) == "supported" && jsonutil.StringValue(witness["source_decision_effect"]) == "supports_source" {
		out["decision_kind"] = EscalationAdvisorySupported
		return out
	}
	out["decision_kind"] = EscalationAdvisoryChallenged
	return out
}

func ResolveEscalationDispute(input EscalationBaseInput, dispute map[string]any) map[string]any {
	out := EscalationBase(input)
	out["judge_ran"] = false
	out["canonical_winner"] = nil
	out["dispute"] = dispute
	effect := jsonutil.StringValue(dispute["source_decision_effect"])
	outcome := jsonutil.StringValue(dispute["outcome_effect"])
	if effect == "supports_source" || outcome == "supports_existing" || outcome == "no_material_change" {
		out["decision_kind"] = EscalationAdvisorySupported
		return out
	}
	out["decision_kind"] = EscalationAdvisoryChallenged
	return out
}

func ResolveEscalationGatherUnion(input EscalationBaseInput, union map[string]any) map[string]any {
	out := EscalationBase(input)
	out["decision_kind"] = EscalationSupportsSource
	out["judge_ran"] = true
	out["judge_attempted"] = true
	out["judge_completed"] = true
	out["canonical_winner"] = nil
	out["selection_basis"] = "escalation_union"
	out["union"] = union
	return out
}

func ResolveEscalationSynthesis(input EscalationBaseInput, synthesis map[string]any) map[string]any {
	out := EscalationBase(input)
	out["judge_ran"] = true
	out["judge_attempted"] = true
	out["judge_completed"] = true
	out["selection_basis"] = SelectionBasisEscalationSynthesis
	out["synthesis"] = synthesis
	sourceWinner := jsonutil.StringValue(input.SourceDecision["canonical_winner"])
	recommended := jsonutil.StringValue(synthesis["recommended_winner"])
	switch jsonutil.StringValue(synthesis["source_decision_effect"]) {
	case "supports_source":
		out["decision_kind"] = EscalationSupportsSource
		if sourceWinner != "" {
			out["canonical_winner"] = sourceWinner
			out["caveats"] = []string{"synthesis_judge_not_position_swapped"}
		}
	case "changes_winner":
		if recommended != "" {
			out["decision_kind"] = EscalationChangedWinner
			out["canonical_winner"] = recommended
			out["caveats"] = []string{"synthesis_judge_not_position_swapped"}
		} else {
			out["decision_kind"] = EscalationStillUnresolved
		}
	case "recommends_winner":
		if sourceWinner == "" && recommended != "" {
			out["decision_kind"] = EscalationRecommendsWinner
			out["canonical_winner"] = recommended
			out["caveats"] = []string{"synthesis_judge_not_position_swapped"}
		} else if sourceWinner != "" && recommended != "" && recommended != sourceWinner {
			out["decision_kind"] = EscalationChangedWinner
			out["canonical_winner"] = recommended
			out["caveats"] = []string{"synthesis_judge_not_position_swapped"}
		} else {
			out["decision_kind"] = EscalationStillUnresolved
		}
	default:
		out["decision_kind"] = EscalationStillUnresolved
	}
	return out
}

func cloneAnyMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}
