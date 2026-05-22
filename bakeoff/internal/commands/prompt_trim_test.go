package commands

import (
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
)

func TestAttachPromptTrimDeduplicatesDroppedRecords(t *testing.T) {
	decision := map[string]any{}
	records := []prompt.TrimRecord{
		{Prompt: "worker:claude", Sections: []string{"context"}, OriginalBytes: 100, FinalBytes: 20},
		{Prompt: "worker:claude", Sections: []string{"context"}, OriginalBytes: 100, FinalBytes: 20},
		{Prompt: "judge:pass1", Sections: []string{"background", "repo_layout"}, OriginalBytes: 200, FinalBytes: 30},
	}

	AttachPromptTrim(decision, records)

	trim, ok := decision["prompt_trim"].(map[string]any)
	if !ok {
		t.Fatalf("prompt_trim missing: %#v", decision)
	}
	dropped, ok := trim["dropped"].([]map[string]any)
	if !ok {
		t.Fatalf("dropped has unexpected shape: %#v", trim["dropped"])
	}
	if len(dropped) != 2 {
		t.Fatalf("dropped count = %d: %#v", len(dropped), dropped)
	}
	if dropped[0]["prompt"] != "worker:claude" || dropped[1]["prompt"] != "judge:pass1" {
		t.Fatalf("unexpected dropped records: %#v", dropped)
	}
}
