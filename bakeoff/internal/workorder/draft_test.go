package workorder

import (
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/modeldefaults"
)

func TestDraftBuildMinimalEmitsValidBuildJSON(t *testing.T) {
	obj := draftBuildObject(t, BuildDraftOptions{
		ID:         "lscmd-finished-at-ordering",
		Goal:       "Order ls output by finished_at descending.",
		Acceptance: []string{"Rows are sorted by finished_at descending."},
		Scopes:     []string{"internal/commands/lscmd"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./internal/commands/lscmd -run TestLsOrder -count=1"}},
	})

	wo, err := Validate(obj)
	if err != nil {
		t.Fatal(err)
	}
	if wo.Type != "build" || wo.Build == nil {
		t.Fatalf("draft type/build = %q/%#v", wo.Type, wo.Build)
	}
	if obj["type"] != "build" {
		t.Fatalf("type = %#v", obj["type"])
	}
	build := obj["build"].(map[string]any)
	if _, ok := build["patch_max_bytes"]; ok {
		t.Fatalf("draft output should omit build.patch_max_bytes: %#v", build)
	}
}

func TestDraftBuildDefaults(t *testing.T) {
	obj := draftBuildObject(t, BuildDraftOptions{
		ID:         "default-build",
		Goal:       "Implement defaults.",
		Acceptance: []string{"The generated work order validates."},
		Scopes:     []string{"internal/workorder"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./internal/workorder"}},
	})

	providers := obj["providers"].([]any)
	claude := providers[0].(map[string]any)
	codex := providers[1].(map[string]any)
	if claude["model"] != modeldefaults.ClaudeSonnet || codex["model"] != modeldefaults.CodexDefault {
		t.Fatalf("provider defaults = %#v", providers)
	}
	judge := obj["judge"].(map[string]any)
	if judge["model"] != modeldefaults.ClaudeOpus {
		t.Fatalf("judge model = %#v", judge["model"])
	}
	budgets := obj["budgets"].(map[string]any)
	assertJSONInt(t, budgets["wall_clock_seconds"], DefaultBuildDraftBudgetWallSeconds)
	assertJSONInt(t, budgets["max_output_bytes"], DefaultBuildDraftBudgetMaxOutputBytes)
	assertJSONInt(t, budgets["max_output_overrun_bytes"], DefaultBuildDraftBudgetMaxOutputBytes)
	build := obj["build"].(map[string]any)
	verify := build["verify"].([]any)
	gate := verify[0].(map[string]any)
	assertJSONInt(t, gate["wall_clock_seconds"], DefaultBuildDraftGateWallSeconds)
	assertJSONInt(t, gate["max_output_bytes"], DefaultBuildDraftGateMaxOutputBytes)
}

func TestDraftBuildSingleProviderDefaultsToClaudeOnly(t *testing.T) {
	obj := draftBuildObject(t, BuildDraftOptions{
		ID:         "single-build",
		RunMode:    RunModeSingleProvider,
		Goal:       "Implement a baseline patch.",
		Acceptance: []string{"The generated single-provider work order validates."},
		Scopes:     []string{"internal/workorder"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./internal/workorder"}},
	})

	if obj["run_mode"] != RunModeSingleProvider {
		t.Fatalf("run_mode = %#v", obj["run_mode"])
	}
	providers := obj["providers"].([]any)
	if len(providers) != 1 {
		t.Fatalf("providers = %#v", providers)
	}
	claude := providers[0].(map[string]any)
	if claude["id"] != "claude" || claude["model"] != modeldefaults.ClaudeSonnet {
		t.Fatalf("single provider default = %#v", claude)
	}
}

func TestDraftBuildSingleProviderRejectsTwoExplicitProviders(t *testing.T) {
	_, err := DraftBuild(BuildDraftOptions{
		ID:         "single-build",
		RunMode:    RunModeSingleProvider,
		Goal:       "Implement a baseline patch.",
		Acceptance: []string{"The generated single-provider work order validates."},
		Scopes:     []string{"internal/workorder"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./internal/workorder"}},
		Providers: []Participant{
			{ID: "claude", Backend: "claude", Model: modeldefaults.ClaudeSonnet, Scope: "codebase"},
			{ID: "codex", Backend: "codex", Model: modeldefaults.CodexDefault, Scope: "codebase"},
		},
	})
	if err == nil || !strings.Contains(err.Error(), "exactly 1 entry") {
		t.Fatalf("expected single-provider count error, got %v", err)
	}
}

func TestDraftBuildPreservesRepeatedValueOrder(t *testing.T) {
	obj := draftBuildObject(t, BuildDraftOptions{
		ID:         "ordered-draft",
		Goal:       "Preserve supplied draft order.",
		Acceptance: []string{"First behavior.", "Second behavior."},
		Scopes:     []string{"internal/a", "internal/b"},
		Background: []string{"First context.", "Second context."},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./..."}},
	})

	background := obj["background"].([]any)
	want := []string{
		"Acceptance criteria:\n- First behavior.\n- Second behavior.",
		"Edit boundary:\n- internal/a\n- internal/b",
		"First context.",
		"Second context.",
		"Bakeoff will capture candidate patches from isolated worktrees and will not apply them to this checkout.",
	}
	if len(background) != len(want) {
		t.Fatalf("background len = %d, want %d: %#v", len(background), len(want), background)
	}
	for i, wantItem := range want {
		if background[i] != wantItem {
			t.Fatalf("background[%d] = %#v, want %#v", i, background[i], wantItem)
		}
	}
}

func TestDraftBuildGateUsesShellCommand(t *testing.T) {
	obj := draftBuildObject(t, BuildDraftOptions{
		ID:         "gate-command",
		Goal:       "Preserve gate command text.",
		Acceptance: []string{"The gate argv wraps the command with sh -c."},
		Scopes:     []string{"internal/workorder"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./..., -run TestDraft"}},
	})

	build := obj["build"].(map[string]any)
	gate := build["verify"].([]any)[0].(map[string]any)
	argv := gate["argv"].([]any)
	want := []string{"sh", "-c", "go test ./..., -run TestDraft"}
	for i, wantItem := range want {
		if argv[i] != wantItem {
			t.Fatalf("argv[%d] = %#v, want %#v", i, argv[i], wantItem)
		}
	}
}

func TestDraftBuildRejectsMissingRequiredInputs(t *testing.T) {
	valid := BuildDraftOptions{
		ID:         "required-inputs",
		Goal:       "Check required inputs.",
		Acceptance: []string{"Required values are enforced."},
		Scopes:     []string{"internal/workorder"},
		Gates:      []GateDraft{{ID: "tests", Command: "go test ./internal/workorder"}},
	}
	cases := []struct {
		name string
		edit func(*BuildDraftOptions)
		want string
	}{
		{name: "id placeholder", edit: func(opts *BuildDraftOptions) { opts.ID = "TODO" }, want: "id"},
		{name: "goal placeholder", edit: func(opts *BuildDraftOptions) { opts.Goal = "ONE SENTENCE: fill me" }, want: "goal"},
		{name: "missing acceptance", edit: func(opts *BuildDraftOptions) { opts.Acceptance = nil }, want: "acceptance"},
		{name: "scope placeholder", edit: func(opts *BuildDraftOptions) { opts.Scopes = []string{"<scope>"} }, want: "scope"},
		{name: "missing gate", edit: func(opts *BuildDraftOptions) { opts.Gates = nil }, want: "gate"},
		{name: "gate command placeholder", edit: func(opts *BuildDraftOptions) { opts.Gates = []GateDraft{{ID: "tests", Command: "<verifier-command>"}} }, want: "gate[0].command"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			opts := valid
			tc.edit(&opts)
			_, err := DraftBuild(opts)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected %q validation error, got %v", tc.want, err)
			}
		})
	}
}

func TestDraftBuildProtectedPathValidationUsesWorkOrderValidator(t *testing.T) {
	_, err := DraftBuild(BuildDraftOptions{
		ID:             "protected-paths",
		Goal:           "Reject unsafe protected paths.",
		Acceptance:     []string{"Unsafe protected paths are rejected."},
		Scopes:         []string{"internal/workorder"},
		Gates:          []GateDraft{{ID: "tests", Command: "go test ./internal/workorder"}},
		ProtectedPaths: []string{"/absolute/path"},
	})
	if err == nil || !strings.Contains(err.Error(), "build.protected_paths[0] must be relative") {
		t.Fatalf("expected protected path validation error, got %v", err)
	}
}

func draftBuildObject(t *testing.T, opts BuildDraftOptions) map[string]any {
	t.Helper()
	doc, err := DraftBuild(opts)
	if err != nil {
		t.Fatal(err)
	}
	text, err := JSONText(doc)
	if err != nil {
		t.Fatal(err)
	}
	value, err := decodeJSON([]byte(text))
	if err != nil {
		t.Fatal(err)
	}
	obj, ok := value.(map[string]any)
	if !ok {
		t.Fatalf("draft decoded as %T, want object", value)
	}
	return obj
}

func assertJSONInt(t *testing.T, value any, want int) {
	t.Helper()
	got, ok := asInt(value)
	if !ok || got != want {
		t.Fatalf("integer = %#v, want %d", value, want)
	}
}
