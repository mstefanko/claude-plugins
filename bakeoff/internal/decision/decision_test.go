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
}
