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
		"Result: `both_failed`",
		"Next: `bakeoff show run-1`",
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
	if !strings.Contains(text, "4.0 KB (obs 18.2 KB)") {
		t.Fatalf("report missing observed byte cell:\n%s", text)
	}
	if strings.Contains(text, "stdout observed") || strings.Contains(text, "stderr observed") {
		t.Fatalf("observed bytes duplicated in notes:\n%s", text)
	}
}
