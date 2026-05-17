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
	)

	for _, want := range []string{
		"# Bakeoff Report: sample",
		"Decision: `both_failed`",
		"- `claude`: `exit_error`",
		"both providers failed; judge skipped",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("report missing %q:\n%s", want, text)
		}
	}
}
