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
