package workorder

import (
	"fmt"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/modeldefaults"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
)

const (
	DefaultBuildDraftBaseRef              = "HEAD"
	DefaultBuildDraftComparisonGoal       = "Prefer the patch that satisfies the acceptance criteria with the smallest maintainable change."
	DefaultBuildDraftBudgetWallSeconds    = 1200
	DefaultBuildDraftBudgetMaxOutputBytes = 80000
	DefaultBuildDraftGateWallSeconds      = 300
	DefaultBuildDraftGateMaxOutputBytes   = 60000
)

type BuildDraftOptions struct {
	ID                   string
	Goal                 string
	RunMode              string
	Acceptance           []string
	Scopes               []string
	Background           []string
	Gates                []GateDraft
	ProtectedPaths       []string
	BaseRef              string
	ComparisonGoal       string
	BudgetWallSeconds    int
	BudgetMaxOutputBytes int
	GateWallSeconds      int
	GateMaxOutputBytes   int
	Providers            []Participant
}

type GateDraft struct {
	ID      string
	Command string
}

type buildDraftDocument struct {
	SchemaVersion int            `json:"schema_version"`
	ID            string         `json:"id"`
	Type          string         `json:"type"`
	RunMode       string         `json:"run_mode"`
	Goal          string         `json:"goal"`
	Background    []string       `json:"background"`
	Providers     []Participant  `json:"providers"`
	ScopePolicy   ScopePolicy    `json:"scope_policy"`
	Judge         Participant    `json:"judge"`
	Build         buildDraftSpec `json:"build"`
	Budgets       Budgets        `json:"budgets"`
}

type buildDraftSpec struct {
	BaseRef        string         `json:"base_ref"`
	ComparisonGoal string         `json:"comparison_goal,omitempty"`
	ProtectedPaths []string       `json:"protected_paths,omitempty"`
	Verify         []VerifierSpec `json:"verify"`
}

func DraftBuild(opts BuildDraftOptions) (any, error) {
	id, err := requiredDraftText("id", opts.ID)
	if err != nil {
		return nil, err
	}
	goal, err := requiredDraftText("goal", opts.Goal)
	if err != nil {
		return nil, err
	}
	acceptance, err := requiredDraftTextList("acceptance", opts.Acceptance)
	if err != nil {
		return nil, err
	}
	scopes, err := requiredDraftTextList("scope", opts.Scopes)
	if err != nil {
		return nil, err
	}
	gates, err := requiredDraftGates(opts.Gates)
	if err != nil {
		return nil, err
	}
	runMode, err := validateRunMode(emptyStringNil(opts.RunMode))
	if err != nil {
		return nil, err
	}

	baseRef := strings.TrimSpace(opts.BaseRef)
	if baseRef == "" {
		baseRef = DefaultBuildDraftBaseRef
	}
	comparisonGoal := strings.TrimSpace(opts.ComparisonGoal)
	if comparisonGoal == "" {
		comparisonGoal = DefaultBuildDraftComparisonGoal
	}
	budgetWallSeconds := opts.BudgetWallSeconds
	if budgetWallSeconds == 0 {
		budgetWallSeconds = DefaultBuildDraftBudgetWallSeconds
	}
	budgetMaxOutputBytes := opts.BudgetMaxOutputBytes
	if budgetMaxOutputBytes == 0 {
		budgetMaxOutputBytes = DefaultBuildDraftBudgetMaxOutputBytes
	}
	gateWallSeconds := opts.GateWallSeconds
	if gateWallSeconds == 0 {
		gateWallSeconds = DefaultBuildDraftGateWallSeconds
	}
	gateMaxOutputBytes := opts.GateMaxOutputBytes
	if gateMaxOutputBytes == 0 {
		gateMaxOutputBytes = DefaultBuildDraftGateMaxOutputBytes
	}

	background := []string{
		"Acceptance criteria:\n- " + strings.Join(acceptance, "\n- "),
		"Edit boundary:\n- " + strings.Join(scopes, "\n- "),
	}
	for _, item := range opts.Background {
		if text := strings.TrimSpace(item); text != "" {
			background = append(background, text)
		}
	}
	background = append(background, "Bakeoff will capture candidate patches from isolated worktrees and will not apply them to this checkout.")

	verify := make([]VerifierSpec, 0, len(gates))
	for _, gate := range gates {
		verify = append(verify, VerifierSpec{
			ID:               gate.ID,
			Kind:             "gate",
			Argv:             []string{"sh", "-c", gate.Command},
			WallClockSeconds: gateWallSeconds,
			MaxOutputBytes:   gateMaxOutputBytes,
		})
	}

	providers := opts.Providers
	if len(providers) == 0 {
		if runMode == RunModeSingleProvider {
			providers = []Participant{
				{ID: "claude", Backend: "claude", Model: modeldefaults.ClaudeSonnet, Scope: "codebase", Effort: "high"},
			}
		} else {
			providers = []Participant{
				{ID: "claude", Backend: "claude", Model: modeldefaults.ClaudeSonnet, Scope: "codebase", Effort: "high"},
				{ID: "codex", Backend: "codex", Model: modeldefaults.CodexDefault, Scope: "codebase", Effort: "high"},
			}
		}
	} else if runMode == RunModeSingleProvider && len(providers) != 1 {
		return nil, Validationf("providers must have exactly 1 entry for run_mode %s", runMode)
	} else if runMode == RunModePairwise && len(providers) != 2 {
		return nil, Validationf("providers must have exactly 2 entries for run_mode %s", runMode)
	}
	for i := range providers {
		if providers[i].ID == "" {
			providers[i].ID = providers[i].Backend
		}
		if providers[i].Model == "" {
			providers[i].Model = provider.DefaultModel(providers[i].Backend)
		}
		if providers[i].Scope == "" {
			providers[i].Scope = "codebase"
		}
		if providers[i].Effort == "" {
			providers[i].Effort = "high"
		}
	}

	doc := buildDraftDocument{
		SchemaVersion: 1,
		ID:            id,
		Type:          "build",
		RunMode:       runMode,
		Goal:          goal,
		Background:    background,
		Providers:     providers,
		ScopePolicy:   ScopePolicy{Enforcement: "best_effort"},
		Judge:         Participant{Backend: "claude", Model: modeldefaults.ClaudeOpus, Effort: "xhigh"},
		Build: buildDraftSpec{
			BaseRef:        baseRef,
			ComparisonGoal: comparisonGoal,
			ProtectedPaths: normalizeOptionalDraftStrings(opts.ProtectedPaths),
			Verify:         verify,
		},
		Budgets: Budgets{
			WallClockSeconds:      budgetWallSeconds,
			MaxOutputBytes:        budgetMaxOutputBytes,
			HeartbeatSeconds:      60,
			OutputCapGraceSeconds: DefaultOutputCapGraceSeconds,
			MaxOutputOverrunBytes: budgetMaxOutputBytes,
		},
	}

	text, err := JSONText(doc)
	if err != nil {
		return nil, err
	}
	value, err := decodeJSON([]byte(text))
	if err != nil {
		return nil, err
	}
	data, ok := value.(map[string]any)
	if !ok {
		return nil, Validationf("draft build output must be a JSON object")
	}
	if _, err := Validate(data); err != nil {
		return nil, err
	}
	return doc, nil
}

func emptyStringNil(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func requiredDraftTextList(label string, values []string) ([]string, error) {
	if len(values) == 0 {
		return nil, Validationf("%s must include at least one non-placeholder value", label)
	}
	out := make([]string, 0, len(values))
	for i, value := range values {
		text, err := requiredDraftText(fmt.Sprintf("%s[%d]", label, i), value)
		if err != nil {
			return nil, err
		}
		out = append(out, text)
	}
	return out, nil
}

func requiredDraftGates(values []GateDraft) ([]GateDraft, error) {
	if len(values) == 0 {
		return nil, Validationf("gate must include at least one verifier")
	}
	out := make([]GateDraft, 0, len(values))
	for i, value := range values {
		id, err := requiredDraftText(fmt.Sprintf("gate[%d].id", i), value.ID)
		if err != nil {
			return nil, err
		}
		command, err := requiredDraftText(fmt.Sprintf("gate[%d].command", i), value.Command)
		if err != nil {
			return nil, err
		}
		out = append(out, GateDraft{ID: id, Command: command})
	}
	return out, nil
}

func requiredDraftText(label string, value string) (string, error) {
	text := strings.TrimSpace(value)
	if isDraftPlaceholder(text) {
		return "", Validationf("%s must be a non-empty non-placeholder value", label)
	}
	return text, nil
}

func isDraftPlaceholder(text string) bool {
	if text == "" {
		return true
	}
	upper := strings.ToUpper(text)
	switch upper {
	case "TODO", "TBD", "FIXME":
		return true
	}
	for _, prefix := range []string{"TODO:", "TODO -", "TODO_", "TODO-", "TBD:", "FIXME:", "ONE SENTENCE:", "MULTI-LINE:"} {
		if strings.HasPrefix(upper, prefix) {
			return true
		}
	}
	return strings.HasPrefix(text, "<") && strings.HasSuffix(text, ">") && len(text) > 2
}

func normalizeOptionalDraftStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, 0, len(values))
	for _, value := range values {
		out = append(out, strings.TrimSpace(value))
	}
	return out
}
