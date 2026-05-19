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
