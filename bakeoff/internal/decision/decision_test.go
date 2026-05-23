package decision

import (
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestSingleProviderOnlyHandlesUnexpectedSurvivor(t *testing.T) {
	wo := &workorder.WorkOrder{
		Type: "gather",
		Providers: []workorder.Participant{
			{ID: "claude"},
		},
	}
	out := SingleProviderOnly(wo, map[string]map[string]any{
		"claude": {"status": "ok"},
	}, "claude")

	caveats, ok := out["caveats"].([]string)
	if !ok || len(caveats) != 1 {
		t.Fatalf("caveats = %#v", out["caveats"])
	}
	if !strings.Contains(caveats[0], "missing_status") {
		t.Fatalf("caveat = %q, want missing_status", caveats[0])
	}
}

func TestGatherStructuredUnionClassifiesFailedJudgeAsProviderUnionOnly(t *testing.T) {
	wo := &workorder.WorkOrder{
		Type: "gather",
		Providers: []workorder.Participant{
			{ID: "claude"},
			{ID: "codex"},
		},
	}
	decision, _, exitCode := GatherStructuredUnion(wo, map[string]map[string]any{
		"claude": {"status": "ok"},
		"codex":  {"status": "ok"},
	}, map[string]any{"status": "exit_error", "judge_error_kind": "api_transient"})

	if exitCode != 4 || decision["decision_kind"] != "provider_union_only" || decision["judge_completed"] != false || decision["judge_error_kind"] != "api_transient" {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if decision["stalled_at"] != StalledAtJudge {
		t.Fatalf("stalled_at = %#v", decision["stalled_at"])
	}
}

func TestGatherStructuredUnionMarksSuccessfulJudgeComplete(t *testing.T) {
	wo := &workorder.WorkOrder{
		Type: "gather",
		Providers: []workorder.Participant{
			{ID: "claude"},
			{ID: "codex"},
		},
	}
	decision, _, exitCode := GatherStructuredUnion(wo, map[string]map[string]any{
		"claude": {"status": "ok"},
		"codex":  {"status": "ok"},
	}, map[string]any{"status": "ok", "final_json": map[string]any{"merged_claims": []any{}, "conflicts": []any{}, "unknowns_union": []any{}}})

	if exitCode != 0 || decision["decision_kind"] != "structured_union" || decision["judge_completed"] != true {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if _, ok := decision["stalled_at"]; ok {
		t.Fatalf("successful gather should not set stalled_at: %#v", decision)
	}
}

func TestResolveCompareTieSetsSelectionStall(t *testing.T) {
	base := map[string]any{"mode": "compare", "provider_statuses": map[string]any{}}
	decision := ResolveCompare(base, map[string]map[string]any{
		"pass1": {"winner": "A", "rationale": "A"},
		"pass2": {"winner": "A", "rationale": "A"},
	}, map[string]string{"A": "claude", "B": "codex"}, map[string]string{"A": "codex", "B": "claude"})
	if decision["decision_kind"] != "tie" || decision["stalled_at"] != StalledAtSelection {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestBothFailedSetsProvidersStall(t *testing.T) {
	wo := &workorder.WorkOrder{Type: "gather", Providers: []workorder.Participant{{ID: "claude"}, {ID: "codex"}}}
	decision := BothFailed(wo, map[string]map[string]any{"claude": {"status": "exit_error"}, "codex": {"status": "exit_error"}})
	if decision["stalled_at"] != StalledAtProviders {
		t.Fatalf("decision = %#v", decision)
	}
}

func TestBasePromotesDeduplicatedScopeFallbackCaveats(t *testing.T) {
	wo := &workorder.WorkOrder{
		Type: "gather",
		Providers: []workorder.Participant{
			{ID: "claude"},
			{ID: "codex"},
		},
	}
	decision := Base(wo, map[string]map[string]any{
		"claude": {"status": "ok", "scope_enforcement": map[string]any{"fallback_reason": "CLI scope controls are advisory"}},
		"codex":  {"status": "ok", "scope_enforcement": map[string]any{"fallback_reason": "CLI scope controls are advisory"}},
	})
	caveats := decision["caveats"].([]string)
	if len(caveats) != 1 || !strings.Contains(caveats[0], "providers claude, codex") {
		t.Fatalf("caveats = %#v", caveats)
	}
}

func TestResolveBuildSelectsGateWinner(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_failed"},
		},
	})
	if exitCode != 0 || decision["decision_kind"] != "pick_winner" || decision["selection_basis"] != "gate" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if _, ok := decision["stalled_at"]; ok {
		t.Fatalf("successful winner should not set stalled_at: %#v", decision)
	}
}

func TestResolveBuildPromotesScopeFallbackCaveats(t *testing.T) {
	decision, _ := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed", "scope_enforcement": map[string]any{"fallback_reason": "claude CLI did not advertise --disallowedTools"}},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_passed"},
		},
	})
	caveats := decision["caveats"].([]string)
	if !strings.Contains(strings.Join(caveats, "\n"), "scope degraded for provider claude") {
		t.Fatalf("missing scope caveat: %#v", caveats)
	}
}

func TestResolveBuildNoCapturedPatchSetsProvidersStall(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "provider_failed", "verify_state": "not_run"},
			"codex":  {"patch_state": "provider_failed", "verify_state": "not_run"},
		},
	})
	if exitCode != 1 || decision["decision_kind"] != "both_failed" || decision["stalled_at"] != StalledAtProviders {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
}

func TestResolveBuildProviderGateFailureSetsProviderVerifyStall(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_failed"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_failed"},
		},
	})
	if exitCode != 1 || decision["decision_kind"] != "both_failed_verification" || decision["stalled_at"] != StalledAtProviderVerify {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
}

func TestResolveBuildUsesStableSwappedJudgeWinner(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_passed"},
		},
		JudgeResults: map[string]map[string]any{
			"pass1": {"winner": "A", "rationale": "A is better", "risks": []any{}},
			"pass2": {"winner": "B", "rationale": "B is better", "risks": []any{}},
		},
		Pass1Order: map[string]string{"A": "claude", "B": "codex"},
		Pass2Order: map[string]string{"A": "codex", "B": "claude"},
	})
	if exitCode != 0 || decision["selection_basis"] != "judge" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if decision["judge_ran"] != true || decision["judge_attempted"] != true || decision["judge_completed"] != true {
		t.Fatalf("judge trio not set on swap-winner path: %#v", decision)
	}
}

func TestResolveBuildSelectsMetricWinner(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_passed"},
		},
		MetricDecisions: []map[string]any{
			{"id": "latency", "winner": "codex", "conclusive": true},
		},
	})
	if exitCode != 0 || decision["decision_kind"] != "pick_winner" || decision["selection_basis"] != "metric" || decision["canonical_winner"] != "codex" || decision["judge_ran"] != false {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if _, ok := decision["judge_attempted"]; ok {
		t.Fatalf("judge_attempted should be absent when metric short-circuits judge: %#v", decision)
	}
	if _, ok := decision["judge_completed"]; ok {
		t.Fatalf("judge_completed should be absent when metric short-circuits judge: %#v", decision)
	}
}

func TestResolveBuildIdenticalPatchDigestTiesBeforeMetricsOrJudge(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed", "patch_digest": "same"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_passed", "patch_digest": "same"},
		},
		MetricDecisions: []map[string]any{
			{"id": "latency", "winner": "claude", "conclusive": true},
		},
		JudgeResults: map[string]map[string]any{
			"pass1": {"winner": "A", "rationale": "A", "risks": []any{}},
			"pass2": {"winner": "B", "rationale": "B", "risks": []any{}},
		},
		Pass1Order: map[string]string{"A": "claude", "B": "codex"},
		Pass2Order: map[string]string{"A": "codex", "B": "claude"},
	})
	if exitCode != 3 || decision["decision_kind"] != "tie" || decision["selection_basis"] != "identical_patch" || decision["canonical_winner"] != nil || decision["judge_ran"] != false {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if decision["stalled_at"] != StalledAtSelection {
		t.Fatalf("stalled_at = %#v", decision["stalled_at"])
	}
}

func TestResolveBuildProtectedPathIneligibleUsesExistingFailureKind(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "protected_path_changed", "verify_state": "not_run", "ineligible_reasons": []any{`patch changed protected path "scripts/bench-json"; revise the patch or remove that path from build.protected_paths if it is intentionally editable`}},
			"codex":  {"patch_state": "protected_path_changed", "verify_state": "not_run", "ineligible_reasons": []any{`patch changed protected path "scripts/bench-json"; revise the patch or remove that path from build.protected_paths if it is intentionally editable`}},
		},
	})
	if exitCode != 1 || decision["decision_kind"] != "both_failed" || decision["selection_basis"] != "none" {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	caveats := decision["caveats"].([]string)
	if !strings.Contains(strings.Join(caveats, "\n"), "protected path") {
		t.Fatalf("missing protected path caveat: %#v", decision)
	}
}

func TestResolveBuildSingleProviderOnly(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed"},
			"codex":  {"patch_state": "provider_failed", "verify_state": "not_run"},
		},
	})
	if exitCode != 0 || decision["decision_kind"] != "single_provider_only" || decision["selection_basis"] != "gate" || decision["canonical_winner"] != "claude" {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
}

func TestResolveBuildJudgeDisagreementTies(t *testing.T) {
	decision, exitCode := ResolveBuild(BuildResolutionInput{
		ProviderIDs: []string{"claude", "codex"},
		ProviderStatuses: map[string]map[string]any{
			"claude": {"patch_state": "patch_captured", "verify_state": "gate_passed"},
			"codex":  {"patch_state": "patch_captured", "verify_state": "gate_passed"},
		},
		JudgeResults: map[string]map[string]any{
			"pass1": {"winner": "A", "rationale": "A is better", "risks": []any{}},
			"pass2": {"winner": "A", "rationale": "A is better", "risks": []any{}},
		},
		Pass1Order: map[string]string{"A": "claude", "B": "codex"},
		Pass2Order: map[string]string{"A": "codex", "B": "claude"},
	})
	if exitCode != 3 || decision["decision_kind"] != "tie" || decision["canonical_winner"] != nil {
		t.Fatalf("decision=%#v exit=%d", decision, exitCode)
	}
	if decision["stalled_at"] != StalledAtSelection {
		t.Fatalf("stalled_at = %#v", decision["stalled_at"])
	}
	if decision["judge_ran"] != true || decision["judge_attempted"] != true || decision["judge_completed"] != true {
		t.Fatalf("judge trio must be true even on swap-disagreement tie: %#v", decision)
	}
}
