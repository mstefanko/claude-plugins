package workorder

import (
	"bytes"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
)

const (
	DefaultOutputCapGraceSeconds = 10
)

var (
	//go:embed templates/*.work-order.json
	templateFS embed.FS

	modes               = []string{"gather", "compare", "analyze", "build"}
	initKinds           = []string{"gather", "compare", "analyze", "review", "build"}
	scopeEnforcements   = []string{"advisory", "best_effort", "required"}
	backends            = []string{"claude", "codex"}
	scopes              = []string{"codebase", "web", "mixed"}
	efforts             = []string{"low", "medium", "high", "xhigh"}
	workerStatuses      = []string{"complete", "complete_with_concerns", "needs_context", "blocked"}
	buildWorkerStatuses = []string{"complete", "blocked"}
	confidences         = []string{"high", "medium", "low"}
	compareScores       = []string{"evidence", "coherence", "tradeoff_honesty", "rebuttals"}
	analyzeScores       = []string{"step_atomicity", "citation_grounding", "assumption_transparency", "coherence"}
	buildScores         = []string{"correctness", "verifier_evidence", "comparative_evidence", "scope_control", "test_quality", "benchmark_quality", "maintainability"}
	verifierKinds       = []string{"gate", "metric"}
	metricDirections    = []string{"lower", "higher"}
	loserPositions      = []string{"agrees", "disagrees", "not_covered", "adds"}
	followupKinds       = []string{"bug", "risk", "doc_drift", "test_gap", "follow_up"}
	triageClasses       = []string{"real_issue", "false_positive", "plan_doc_drift", "product_decision", "needs_repro", "already_fixed", "evidence_gap"}
	triageActions       = []string{"fix_now", "document", "defer", "ignore", "reproduce"}
	triageSeverities    = []string{"high", "medium", "low", "none"}
	slugRE              = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)
	todoIDRE            = regexp.MustCompile(`(?i)^TODO[-_]`)
	facetControlRE      = regexp.MustCompile(`[\x00-\x1f\x7f]`)
)

var facetKeys = map[string]bool{
	"id": true, "kind": true, "focus": true, "include": true, "exclude": true, "notes": true,
}

var facetReservedIDs = map[string]bool{
	"judge": true, "provider": true, "providers": true, "worker": true, "workers": true,
}

type ValidationError struct {
	Message string
	Err     error
}

func (e *ValidationError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "validation error"
}

func (e *ValidationError) Unwrap() error {
	return e.Err
}

func Validationf(format string, args ...any) error {
	return &ValidationError{Message: fmt.Sprintf(format, args...)}
}

type Participant struct {
	ID      string         `json:"id,omitempty"`
	Backend string         `json:"backend"`
	Model   string         `json:"model"`
	Effort  string         `json:"effort"`
	Scope   string         `json:"scope,omitempty"`
	Raw     map[string]any `json:"-"`
}

type Facet struct {
	ID      string   `json:"id"`
	Kind    string   `json:"kind"`
	Focus   string   `json:"focus"`
	Include []string `json:"include"`
	Exclude []string `json:"exclude,omitempty"`
	Notes   string   `json:"notes,omitempty"`
}

type Budgets struct {
	WallClockSeconds      int `json:"wall_clock_seconds"`
	MaxOutputBytes        int `json:"max_output_bytes"`
	HeartbeatSeconds      int `json:"heartbeat_seconds"`
	OutputCapGraceSeconds int `json:"output_cap_grace_seconds"`
	MaxOutputOverrunBytes int `json:"max_output_overrun_bytes"`
}

type ScopePolicy struct {
	Enforcement string `json:"enforcement"`
}

type BuildSpec struct {
	BaseRef        string         `json:"base_ref"`
	ComparisonGoal string         `json:"comparison_goal,omitempty"`
	PatchMaxBytes  int            `json:"patch_max_bytes"`
	ProtectedPaths []string       `json:"protected_paths,omitempty"`
	Verify         []VerifierSpec `json:"verify"`
	Raw            map[string]any `json:"-"`
}

type VerifierSpec struct {
	ID               string         `json:"id"`
	Kind             string         `json:"kind"`
	Argv             []string       `json:"argv"`
	Metric           *MetricSpec    `json:"metric,omitempty"`
	WallClockSeconds int            `json:"wall_clock_seconds"`
	MaxOutputBytes   int            `json:"max_output_bytes"`
	Raw              map[string]any `json:"-"`
}

type MetricSpec struct {
	Name              string         `json:"name"`
	Direction         string         `json:"direction"`
	MinDeltaPercent   float64        `json:"min_delta_percent"`
	NoiseFloorPercent float64        `json:"noise_floor_percent,omitempty"`
	MinRuns           int            `json:"min_runs,omitempty"`
	Raw               map[string]any `json:"-"`
}

type WorkOrder struct {
	SchemaVersion int            `json:"schema_version"`
	ID            string         `json:"id"`
	Type          string         `json:"type"`
	Goal          string         `json:"goal"`
	Background    string         `json:"background"`
	Facet         *Facet         `json:"facet,omitempty"`
	Providers     []Participant  `json:"providers"`
	Judge         Participant    `json:"judge"`
	Budgets       Budgets        `json:"budgets"`
	ScopePolicy   ScopePolicy    `json:"scope_policy"`
	Build         *BuildSpec     `json:"build,omitempty"`
	Raw           map[string]any `json:"-"`
}

func StripJSONCComments(text string) string {
	var out strings.Builder
	i := 0
	state := "normal"
	escaped := false
	for i < len(text) {
		char := text[i]
		var next byte
		if i+1 < len(text) {
			next = text[i+1]
		}

		switch state {
		case "line_comment":
			if char == '\n' {
				out.WriteByte(char)
				state = "normal"
			}
			i++
			continue
		case "block_comment":
			if char == '*' && next == '/' {
				out.WriteByte(' ')
				i += 2
				state = "normal"
				continue
			}
			if char == '\n' {
				out.WriteByte('\n')
			} else {
				out.WriteByte(' ')
			}
			i++
			continue
		case "string":
			out.WriteByte(char)
			if escaped {
				escaped = false
			} else if char == '\\' {
				escaped = true
			} else if char == '"' {
				state = "normal"
			}
			i++
			continue
		}

		if char == '"' {
			out.WriteByte(char)
			state = "string"
			i++
		} else if char == '/' && next == '/' {
			out.WriteByte(' ')
			i += 2
			state = "line_comment"
		} else if char == '/' && next == '*' {
			out.WriteByte(' ')
			i += 2
			state = "block_comment"
		} else {
			out.WriteByte(char)
			i++
		}
	}
	return out.String()
}

func Load(path string) (*WorkOrder, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, Validationf("%s: work order not found", path)
		}
		return nil, Validationf("%s: %v", path, err)
	}
	value, err := decodeJSON([]byte(StripJSONCComments(string(data))))
	if err != nil {
		return nil, Validationf("%s: invalid JSONC after comment stripping: %s", path, jsonMessage(err))
	}
	obj, ok := value.(map[string]any)
	if !ok {
		return nil, Validationf("work order must be a JSON object")
	}
	return Validate(obj)
}

func Validate(data map[string]any) (*WorkOrder, error) {
	for _, field := range []string{"schema_version", "id", "type", "goal", "background", "providers", "judge", "budgets"} {
		if _, ok := data[field]; !ok {
			return nil, Validationf("%s is required", field)
		}
	}

	schemaVersion, ok := asInt(data["schema_version"])
	if !ok || schemaVersion != 1 {
		return nil, Validationf("schema_version must equal 1 in v1 (got %s)", pyRepr(data["schema_version"]))
	}

	workID, ok := data["id"].(string)
	if !ok || strings.TrimSpace(workID) == "" {
		return nil, Validationf("id must be a non-empty slug")
	}
	if todoIDRE.MatchString(workID) {
		return nil, Validationf("id must not match the init placeholder rule '^TODO[-_]'")
	}
	if !slugRE.MatchString(workID) {
		return nil, Validationf("id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")
	}

	mode, ok := data["type"].(string)
	if !ok || !contains(modes, mode) {
		return nil, Validationf("type must be one of: %s (got %s)", strings.Join(modes, ", "), pyRepr(data["type"]))
	}

	goal, ok := data["goal"].(string)
	if !ok || strings.TrimSpace(goal) == "" {
		return nil, Validationf("goal must be a non-empty string")
	}
	background, ok := backgroundAsString(data["background"])
	if !ok {
		return nil, Validationf("background must be a string or an array of strings")
	}

	providers, err := validateProviders(data["providers"])
	if err != nil {
		return nil, err
	}
	for i, provider := range providers {
		if mode == "build" && provider.Scope == "web" {
			return nil, Validationf(`providers[%d].scope "web" is not supported for type "build"`, i)
		}
	}
	providerIDs := make(map[string]bool, len(providers))
	for _, provider := range providers {
		providerIDs[provider.ID] = true
	}
	facet, err := validateFacet(data["facet"], providerIDs)
	if err != nil {
		return nil, err
	}
	judge, err := validateJudge(data["judge"], providers)
	if err != nil {
		return nil, err
	}
	budgets, err := validateBudgets(data["budgets"])
	if err != nil {
		return nil, err
	}
	scopePolicy, err := validateScopePolicy(data["scope_policy"])
	if err != nil {
		return nil, err
	}
	var build *BuildSpec
	if mode == "build" {
		build, err = validateBuildSpec(data["build"])
		if err != nil {
			return nil, err
		}
	}

	return &WorkOrder{
		SchemaVersion: schemaVersion,
		ID:            workID,
		Type:          mode,
		Goal:          goal,
		Background:    background,
		Facet:         facet,
		Providers:     providers,
		Judge:         judge,
		Budgets:       budgets,
		ScopePolicy:   scopePolicy,
		Build:         build,
		Raw:           data,
	}, nil
}

func backgroundAsString(value any) (string, bool) {
	switch typed := value.(type) {
	case string:
		return typed, true
	case []any:
		parts := make([]string, 0, len(typed))
		for _, item := range typed {
			part, ok := item.(string)
			if !ok {
				return "", false
			}
			parts = append(parts, part)
		}
		return strings.Join(parts, "\n\n"), true
	default:
		return "", false
	}
}

func InitTemplate(kind string) (string, error) {
	if !contains(initKinds, kind) {
		return "", Validationf("type must be one of: %s (got %s)", strings.Join(initKinds, ", "), pyRepr(kind))
	}
	data, err := templateFS.ReadFile(filepath.ToSlash(filepath.Join("templates", kind+".work-order.json")))
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func ModeEffortDefaults(mode string) (worker string, judge string) {
	switch mode {
	case "gather", "compare", "analyze":
		return "high", "xhigh"
	default:
		return "high", "xhigh"
	}
}

func FormatBudgetSummary(b Budgets) string {
	return fmt.Sprintf("%ds wall, %d bytes out, %ds cap grace", b.WallClockSeconds, b.MaxOutputBytes, b.OutputCapGraceSeconds)
}

func validateProviders(value any) ([]Participant, error) {
	items, ok := value.([]any)
	if !ok || len(items) != 2 {
		return nil, Validationf("providers must have exactly 2 entries")
	}
	providers := make([]Participant, 0, len(items))
	ids := map[string]bool{}
	triples := map[string]bool{}
	for i, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			return nil, Validationf("providers[%d] must be an object", i)
		}
		if _, ok := obj["facet"]; ok {
			return nil, Validationf("providers[%d].facet is not supported in v1; use top-level facet", i)
		}
		participant, err := validateParticipant(obj, fmt.Sprintf("providers[%d]", i), true)
		if err != nil {
			return nil, err
		}
		if ids[participant.ID] {
			return nil, Validationf("providers[%d].id must be unique (duplicate %s)", i, pyRepr(participant.ID))
		}
		ids[participant.ID] = true
		triples[participant.Backend+"\x00"+participant.Model+"\x00"+participant.Scope] = true
		providers = append(providers, participant)
	}
	if len(triples) == 1 {
		return nil, Validationf("providers must differ on at least one of backend, model, or scope")
	}
	return providers, nil
}

func validateFacet(value any, providerIDs map[string]bool) (*Facet, error) {
	if value == nil {
		return nil, nil
	}
	obj, ok := value.(map[string]any)
	if !ok {
		return nil, Validationf("facet must be an object")
	}
	var unknown []string
	for key := range obj {
		if !facetKeys[key] {
			unknown = append(unknown, key)
		}
	}
	sort.Strings(unknown)
	if len(unknown) > 0 {
		return nil, Validationf("facet has unsupported keys: %s", strings.Join(unknown, ", "))
	}
	for _, field := range []string{"id", "focus", "include"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("facet.%s is required", field)
		}
	}
	id, ok := obj["id"].(string)
	if !ok || strings.TrimSpace(id) == "" {
		return nil, Validationf("facet.id must be a non-empty slug")
	}
	if !slugRE.MatchString(id) {
		return nil, Validationf("facet.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")
	}
	if providerIDs[id] {
		return nil, Validationf("facet.id must not duplicate a provider id")
	}
	if facetReservedIDs[strings.ToLower(id)] {
		return nil, Validationf("facet.id is reserved")
	}
	kind := "generic"
	if raw, ok := obj["kind"]; ok {
		kind, ok = raw.(string)
		if !ok || kind != "generic" {
			return nil, Validationf(`facet.kind must be "generic" when present`)
		}
	}
	focus, err := normalizeFacetText(obj["focus"], "facet.focus")
	if err != nil {
		return nil, err
	}
	include, err := validateFacetStringList(obj["include"], "facet.include", 1, 8)
	if err != nil {
		return nil, err
	}
	exclude, err := validateFacetStringList(valueOrDefault(obj, "exclude", []any{}), "facet.exclude", 0, 8)
	if err != nil {
		return nil, err
	}
	notes := ""
	if raw, ok := obj["notes"]; ok {
		notes, err = normalizeFacetText(raw, "facet.notes")
		if err != nil {
			return nil, err
		}
	}
	total := len(id) + len(kind) + len(focus) + sumStringLens(include) + sumStringLens(exclude) + len(notes)
	if total > 4096 {
		return nil, Validationf("facet text must be at most 4096 characters total")
	}
	return &Facet{ID: id, Kind: kind, Focus: focus, Include: include, Exclude: exclude, Notes: notes}, nil
}

func validateJudge(value any, providers []Participant) (Participant, error) {
	obj, ok := value.(map[string]any)
	if !ok {
		return Participant{}, Validationf("judge must be an object")
	}
	judge, err := validateParticipant(obj, "judge", false)
	if err != nil {
		return Participant{}, err
	}
	for i, provider := range providers {
		if judge.Backend == provider.Backend && judge.Model == provider.Model {
			return Participant{}, Validationf("judge.backend + judge.model must differ from providers[%d] backend + model", i)
		}
	}
	return judge, nil
}

func validateParticipant(value map[string]any, label string, requireScope bool) (Participant, error) {
	required := []string{"backend", "model"}
	if requireScope {
		required = []string{"id", "backend", "model"}
	}
	for _, field := range required {
		if _, ok := value[field]; !ok {
			return Participant{}, Validationf("%s.%s is required", label, field)
		}
	}

	normalized := cloneMap(value)
	if requireScope {
		if _, ok := normalized["scope"]; !ok {
			normalized["scope"] = "mixed"
		}
	}
	if _, ok := normalized["effort"]; !ok {
		normalized["effort"] = "high"
	}

	id := ""
	if requireScope {
		var ok bool
		id, ok = normalized["id"].(string)
		if !ok || strings.TrimSpace(id) == "" {
			return Participant{}, Validationf("%s.id must be a non-empty string", label)
		}
		if id == "." || id == ".." || !slugRE.MatchString(id) {
			return Participant{}, Validationf("%s.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$", label)
		}
	}

	backend, ok := normalized["backend"].(string)
	if !ok || !contains(backends, backend) {
		return Participant{}, Validationf("%s.backend must be one of: %s (got %s)", label, strings.Join(backends, ", "), pyRepr(normalized["backend"]))
	}
	model, ok := normalized["model"].(string)
	if !ok || strings.TrimSpace(model) == "" {
		return Participant{}, Validationf("%s.model must be a non-empty string", label)
	}
	effort, ok := normalized["effort"].(string)
	if !ok || !contains(efforts, effort) {
		return Participant{}, Validationf("%s.effort must be one of: %s (got %s)", label, strings.Join(efforts, ", "), pyRepr(normalized["effort"]))
	}
	scope := ""
	if requireScope {
		scope, ok = normalized["scope"].(string)
		if !ok || !contains(scopes, scope) {
			return Participant{}, Validationf("%s.scope must be one of: %s (got %s)", label, strings.Join(scopes, ", "), pyRepr(normalized["scope"]))
		}
	} else {
		delete(normalized, "scope")
		delete(normalized, "id")
	}
	return Participant{ID: id, Backend: backend, Model: model, Effort: effort, Scope: scope, Raw: normalized}, nil
}

func validateBudgets(value any) (Budgets, error) {
	obj, ok := value.(map[string]any)
	if !ok {
		return Budgets{}, Validationf("budgets must be an object")
	}
	wall, err := requiredPositiveInt(obj, "budgets.wall_clock_seconds", "wall_clock_seconds")
	if err != nil {
		return Budgets{}, err
	}
	maxOutput, err := requiredPositiveInt(obj, "budgets.max_output_bytes", "max_output_bytes")
	if err != nil {
		return Budgets{}, err
	}
	heartbeat := 60
	if raw, ok := obj["heartbeat_seconds"]; ok {
		value, ok := asInt(raw)
		if !ok || value < 0 {
			return Budgets{}, Validationf("budgets.heartbeat_seconds must be a non-negative integer")
		}
		heartbeat = value
	}
	grace := DefaultOutputCapGraceSeconds
	if raw, ok := obj["output_cap_grace_seconds"]; ok {
		value, ok := asInt(raw)
		if !ok || value < 0 {
			return Budgets{}, Validationf("budgets.output_cap_grace_seconds must be a non-negative integer")
		}
		grace = value
	}
	overrun := maxOutput
	if raw, ok := obj["max_output_overrun_bytes"]; ok {
		value, ok := asInt(raw)
		if !ok || value < 0 {
			return Budgets{}, Validationf("budgets.max_output_overrun_bytes must be a non-negative integer")
		}
		overrun = value
	}
	return Budgets{
		WallClockSeconds:      wall,
		MaxOutputBytes:        maxOutput,
		HeartbeatSeconds:      heartbeat,
		OutputCapGraceSeconds: grace,
		MaxOutputOverrunBytes: overrun,
	}, nil
}

func validateScopePolicy(value any) (ScopePolicy, error) {
	if value == nil {
		return ScopePolicy{Enforcement: "best_effort"}, nil
	}
	enforcement := ""
	switch typed := value.(type) {
	case string:
		enforcement = typed
	case map[string]any:
		enforcement = "best_effort"
		if raw, ok := typed["enforcement"]; ok {
			if s, ok := raw.(string); ok {
				enforcement = s
			} else {
				enforcement = fmt.Sprint(raw)
			}
		}
	default:
		return ScopePolicy{}, Validationf("scope_policy must be an object or one of: advisory, best_effort, required")
	}
	if !contains(scopeEnforcements, enforcement) {
		return ScopePolicy{}, Validationf("scope_policy.enforcement must be one of: %s (got %s)", strings.Join(scopeEnforcements, ", "), pyRepr(enforcement))
	}
	return ScopePolicy{Enforcement: enforcement}, nil
}

func validateBuildSpec(value any) (*BuildSpec, error) {
	obj, ok := value.(map[string]any)
	if !ok {
		return nil, Validationf(`build is required when type is "build"`)
	}
	baseRef := "HEAD"
	if raw, ok := obj["base_ref"]; ok {
		value, ok := raw.(string)
		if !ok || strings.TrimSpace(value) == "" {
			return nil, Validationf("build.base_ref must be a non-empty string")
		}
		baseRef = strings.TrimSpace(value)
	}
	comparisonGoal := ""
	if raw, ok := obj["comparison_goal"]; ok {
		value, ok := raw.(string)
		if !ok {
			return nil, Validationf("build.comparison_goal must be a string")
		}
		comparisonGoal = strings.TrimSpace(value)
	}
	patchMaxBytes := 100000
	if raw, ok := obj["patch_max_bytes"]; ok {
		value, ok := asInt(raw)
		if !ok || value <= 0 || value > 5000000 {
			return nil, Validationf("build.patch_max_bytes must be a positive integer no greater than 5000000")
		}
		patchMaxBytes = value
	}
	protectedPaths, err := validateProtectedPaths(obj["protected_paths"], "build.protected_paths")
	if err != nil {
		return nil, err
	}
	verify, err := validateVerifierSpecs(obj["verify"])
	if err != nil {
		return nil, err
	}
	return &BuildSpec{
		BaseRef:        baseRef,
		ComparisonGoal: comparisonGoal,
		PatchMaxBytes:  patchMaxBytes,
		ProtectedPaths: protectedPaths,
		Verify:         verify,
		Raw:            obj,
	}, nil
}

func validateProtectedPaths(value any, label string) ([]string, error) {
	if value == nil {
		return nil, nil
	}
	items, ok := value.([]any)
	if !ok {
		return nil, Validationf("%s must be an array of repository-relative paths", label)
	}
	seen := map[string]bool{}
	out := make([]string, 0, len(items))
	for i, item := range items {
		raw, ok := item.(string)
		if !ok || strings.TrimSpace(raw) == "" {
			return nil, Validationf("%s[%d] must be a non-empty repository-relative path", label, i)
		}
		normalized, err := normalizeProtectedPath(raw)
		if err != nil {
			return nil, Validationf("%s[%d] %s", label, i, err.Error())
		}
		if seen[normalized] {
			return nil, Validationf("%s[%d] duplicates protected path %s", label, i, pyRepr(normalized))
		}
		seen[normalized] = true
		out = append(out, normalized)
	}
	return out, nil
}

func normalizeProtectedPath(raw string) (string, error) {
	text := strings.TrimSpace(raw)
	if strings.Contains(text, "\\") {
		return "", fmt.Errorf("must use slash-separated repository-relative paths")
	}
	if filepath.IsAbs(text) || path.IsAbs(text) {
		return "", fmt.Errorf("must be relative to the repository root")
	}
	if strings.ContainsAny(text, "*?[") {
		return "", fmt.Errorf("must not use glob syntax")
	}
	parts := strings.Split(text, "/")
	for _, part := range parts {
		if part == ".." {
			return "", fmt.Errorf("must not contain .. path traversal")
		}
	}
	normalized := path.Clean(text)
	if normalized == "." || strings.HasPrefix(normalized, "../") || normalized == ".." {
		return "", fmt.Errorf("must be a repository-relative file or directory path")
	}
	return normalized, nil
}

func validateVerifierSpecs(value any) ([]VerifierSpec, error) {
	items, ok := value.([]any)
	if !ok || len(items) == 0 {
		return nil, Validationf("build.verify must be a non-empty array")
	}
	seenIDs := map[string]bool{}
	hasGate := false
	out := make([]VerifierSpec, 0, len(items))
	for i, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			return nil, Validationf("build.verify[%d] must be an object", i)
		}
		verifier, err := validateVerifierSpec(obj, i)
		if err != nil {
			return nil, err
		}
		if seenIDs[verifier.ID] {
			return nil, Validationf("build.verify[%d].id must be unique (duplicate %s)", i, pyRepr(verifier.ID))
		}
		seenIDs[verifier.ID] = true
		if verifier.Kind == "gate" {
			hasGate = true
		}
		out = append(out, verifier)
	}
	if !hasGate {
		return nil, Validationf("build.verify must include at least one gate verifier")
	}
	return out, nil
}

func validateVerifierSpec(obj map[string]any, index int) (VerifierSpec, error) {
	label := fmt.Sprintf("build.verify[%d]", index)
	id, ok := obj["id"].(string)
	if !ok || strings.TrimSpace(id) == "" {
		return VerifierSpec{}, Validationf("%s.id must be a non-empty slug", label)
	}
	id = strings.TrimSpace(id)
	if !slugRE.MatchString(id) {
		return VerifierSpec{}, Validationf("%s.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$", label)
	}
	kind := "gate"
	if raw, ok := obj["kind"]; ok {
		value, ok := raw.(string)
		if !ok || !contains(verifierKinds, value) {
			return VerifierSpec{}, Validationf("%s.kind must be one of: %s", label, strings.Join(verifierKinds, ", "))
		}
		kind = value
	}
	argv, err := validateVerifierArgv(obj["argv"], label+".argv")
	if err != nil {
		return VerifierSpec{}, err
	}
	wall, err := requiredPositiveInt(obj, label+".wall_clock_seconds", "wall_clock_seconds")
	if err != nil {
		return VerifierSpec{}, err
	}
	maxOutput, err := requiredPositiveInt(obj, label+".max_output_bytes", "max_output_bytes")
	if err != nil {
		return VerifierSpec{}, err
	}
	var metric *MetricSpec
	if kind == "metric" {
		metric, err = validateMetricSpec(obj["metric"], label+".metric")
		if err != nil {
			return VerifierSpec{}, err
		}
	} else if _, ok := obj["metric"]; ok {
		return VerifierSpec{}, Validationf("%s.metric is only valid when kind is metric", label)
	}
	return VerifierSpec{
		ID:               id,
		Kind:             kind,
		Argv:             argv,
		Metric:           metric,
		WallClockSeconds: wall,
		MaxOutputBytes:   maxOutput,
		Raw:              obj,
	}, nil
}

func validateVerifierArgv(value any, label string) ([]string, error) {
	items, ok := value.([]any)
	if !ok || len(items) == 0 {
		return nil, Validationf("%s must be a non-empty array of strings", label)
	}
	out := make([]string, 0, len(items))
	for i, item := range items {
		text, ok := item.(string)
		if !ok || text == "" {
			return nil, Validationf("%s[%d] must be a non-empty string", label, i)
		}
		if strings.ContainsRune(text, '\x00') || strings.ContainsAny(text, "\r\n") {
			return nil, Validationf("%s[%d] must not contain control characters", label, i)
		}
		if i == 0 && strings.ContainsAny(text, " \t") {
			return nil, Validationf("%s[0] must be a command path without whitespace; pass command arguments as separate argv entries", label)
		}
		out = append(out, text)
	}
	return out, nil
}

func validateMetricSpec(value any, label string) (*MetricSpec, error) {
	obj, ok := value.(map[string]any)
	if !ok {
		return nil, Validationf("%s is required for metric verifiers", label)
	}
	name, ok := obj["name"].(string)
	if !ok || strings.TrimSpace(name) == "" {
		return nil, Validationf("%s.name must be a non-empty string", label)
	}
	direction, ok := obj["direction"].(string)
	if !ok || !contains(metricDirections, direction) {
		return nil, Validationf("%s.direction must be one of: %s", label, strings.Join(metricDirections, ", "))
	}
	minDelta, err := requiredPositiveFloat(obj, label+".min_delta_percent", "min_delta_percent")
	if err != nil {
		return nil, err
	}
	noiseFloor := 0.0
	if raw, ok := obj["noise_floor_percent"]; ok {
		value, ok := asFloat(raw)
		if !ok || value < 0 || math.IsNaN(value) || math.IsInf(value, 0) {
			return nil, Validationf("%s.noise_floor_percent must be a non-negative finite number", label)
		}
		noiseFloor = value
	}
	minRuns := 1
	if raw, ok := obj["min_runs"]; ok {
		value, ok := asInt(raw)
		if !ok || value <= 0 {
			return nil, Validationf("%s.min_runs must be a positive integer", label)
		}
		minRuns = value
	}
	return &MetricSpec{
		Name:              strings.TrimSpace(name),
		Direction:         direction,
		MinDeltaPercent:   minDelta,
		NoiseFloorPercent: noiseFloor,
		MinRuns:           minRuns,
		Raw:               obj,
	}, nil
}

func ValidateWorkerResult(data any, mode string) (any, error) {
	if mode == "build" {
		return ValidateBuildWorkerResult(data)
	}
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("worker final_json must be an object")
	}
	for _, field := range []string{"status", "claims", "conflicts", "unknowns", "recommended_next_checks"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("worker final_json.%s is required", field)
		}
	}
	if status, _ := obj["status"].(string); !contains(workerStatuses, status) {
		return nil, Validationf("worker final_json.status must be one of: %s", strings.Join(workerStatuses, ", "))
	}
	if mode == "compare" {
		if _, ok := obj["position"].(string); !ok {
			return nil, Validationf("worker final_json.position is required for compare mode")
		}
	}
	if err := validateClaims(obj["claims"], "worker final_json.claims"); err != nil {
		return nil, err
	}
	if err := validateStringList(obj["unknowns"], "worker final_json.unknowns"); err != nil {
		return nil, err
	}
	if err := validateStringList(obj["recommended_next_checks"], "worker final_json.recommended_next_checks"); err != nil {
		return nil, err
	}
	if _, ok := obj["conflicts"].([]any); !ok {
		return nil, Validationf("worker final_json.conflicts must be an array")
	}
	return data, nil
}

func ValidateGatherJudgeResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("gather judge final_json must be an object")
	}
	for _, field := range []string{"merged_claims", "conflicts", "unknowns_union"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("gather judge final_json.%s is required", field)
		}
	}
	claims, ok := obj["merged_claims"].([]any)
	if !ok {
		return nil, Validationf("gather judge final_json.merged_claims must be an array")
	}
	for i, claim := range claims {
		if err := validateMappingClaim(claim, fmt.Sprintf("gather judge final_json.merged_claims[%d]", i), true); err != nil {
			return nil, err
		}
	}
	if _, ok := obj["conflicts"].([]any); !ok {
		return nil, Validationf("gather judge final_json.conflicts must be an array")
	}
	if err := validateStringList(obj["unknowns_union"], "gather judge final_json.unknowns_union"); err != nil {
		return nil, err
	}
	if raw, ok := obj["out_of_facet_claims"]; ok {
		items, ok := raw.([]any)
		if !ok {
			return nil, Validationf("gather judge final_json.out_of_facet_claims must be an array")
		}
		for i, item := range items {
			if err := validateOutOfFacetClaim(item, fmt.Sprintf("gather judge final_json.out_of_facet_claims[%d]", i)); err != nil {
				return nil, err
			}
		}
	}
	return data, nil
}

func ValidateCompareJudgeResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("compare judge final_json must be an object")
	}
	for _, field := range []string{"relation", "scores_a", "scores_b", "winner", "rationale", "kept_from_nonwinner", "consensus_strongest", "consensus_disagreements"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("compare judge final_json.%s is required", field)
		}
	}
	if relation, _ := obj["relation"].(string); relation != "consensus" && relation != "compare" {
		return nil, Validationf(`compare judge final_json.relation must be one of: "consensus", "compare"`)
	}
	if winner := obj["winner"]; winner != nil {
		if s, ok := winner.(string); !ok || (s != "A" && s != "B" && s != "tie") {
			return nil, Validationf(`compare judge final_json.winner must be one of: "A", "B", "tie", null`)
		}
	}
	if err := validateScoreMap(obj["scores_a"], "compare judge final_json.scores_a", compareScores); err != nil {
		return nil, err
	}
	if err := validateScoreMap(obj["scores_b"], "compare judge final_json.scores_b", compareScores); err != nil {
		return nil, err
	}
	if err := validateStringOrList(obj["rationale"], "compare judge final_json.rationale"); err != nil {
		return nil, err
	}
	for _, field := range []string{"kept_from_nonwinner", "consensus_strongest", "consensus_disagreements"} {
		if _, ok := obj[field].([]any); !ok {
			return nil, Validationf("compare judge final_json.%s must be an array", field)
		}
	}
	return data, nil
}

func ValidateAnalyzeJudgeResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("analyze judge final_json must be an object")
	}
	for _, field := range []string{"scores_a", "scores_b", "spine_winner", "spine_rationale", "claim_verdicts", "additions_from_loser"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("analyze judge final_json.%s is required", field)
		}
	}
	if winner, _ := obj["spine_winner"].(string); winner != "A" && winner != "B" {
		return nil, Validationf(`analyze judge final_json.spine_winner must be one of: "A", "B"`)
	}
	if err := validateScoreMap(obj["scores_a"], "analyze judge final_json.scores_a", analyzeScores); err != nil {
		return nil, err
	}
	if err := validateScoreMap(obj["scores_b"], "analyze judge final_json.scores_b", analyzeScores); err != nil {
		return nil, err
	}
	verdicts, ok := obj["claim_verdicts"].([]any)
	if !ok {
		return nil, Validationf("analyze judge final_json.claim_verdicts must be an array")
	}
	for i, verdict := range verdicts {
		if err := validateClaimVerdict(verdict, fmt.Sprintf("analyze judge final_json.claim_verdicts[%d]", i)); err != nil {
			return nil, err
		}
	}
	additions, ok := obj["additions_from_loser"].([]any)
	if !ok {
		return nil, Validationf("analyze judge final_json.additions_from_loser must be an array")
	}
	for i, addition := range additions {
		if err := validateLoserAddition(addition, fmt.Sprintf("analyze judge final_json.additions_from_loser[%d]", i)); err != nil {
			return nil, err
		}
	}
	if raw, ok := obj["actionable_followups"]; ok {
		items, ok := raw.([]any)
		if !ok {
			return nil, Validationf("analyze judge final_json.actionable_followups must be an array")
		}
		for i, item := range items {
			if err := validateAnalyzeFollowup(item, fmt.Sprintf("analyze judge final_json.actionable_followups[%d]", i)); err != nil {
				return nil, err
			}
		}
	}
	return data, nil
}

func ValidateBuildWorkerResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("build worker final_json must be an object")
	}
	for _, field := range []string{"status", "summary", "files_touched", "tests_added_or_changed", "risks", "manual_checks"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("build worker final_json.%s is required", field)
		}
	}
	if status, _ := obj["status"].(string); !contains(buildWorkerStatuses, status) {
		return nil, Validationf("build worker final_json.status must be one of: %s", strings.Join(buildWorkerStatuses, ", "))
	}
	if summary, ok := obj["summary"].(string); !ok || strings.TrimSpace(summary) == "" {
		return nil, Validationf("build worker final_json.summary must be a non-empty string")
	}
	for _, field := range []string{"files_touched", "tests_added_or_changed", "risks", "manual_checks"} {
		if err := validateStringList(obj[field], "build worker final_json."+field); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func ValidateBuildJudgeResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("build judge final_json must be an object")
	}
	for _, field := range []string{"relation", "scores_a", "scores_b", "winner", "rationale", "risks"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("build judge final_json.%s is required", field)
		}
	}
	if relation, _ := obj["relation"].(string); relation != "compare" {
		return nil, Validationf(`build judge final_json.relation must equal "compare"`)
	}
	if winner := obj["winner"]; winner != nil {
		if s, ok := winner.(string); !ok || (s != "A" && s != "B" && s != "tie") {
			return nil, Validationf(`build judge final_json.winner must be one of: "A", "B", "tie", null`)
		}
	}
	if err := validateScoreMap(obj["scores_a"], "build judge final_json.scores_a", buildScores); err != nil {
		return nil, err
	}
	if err := validateScoreMap(obj["scores_b"], "build judge final_json.scores_b", buildScores); err != nil {
		return nil, err
	}
	if err := validateStringOrList(obj["rationale"], "build judge final_json.rationale"); err != nil {
		return nil, err
	}
	if err := validateStringList(obj["risks"], "build judge final_json.risks"); err != nil {
		return nil, err
	}
	return data, nil
}

func ValidateTriageResult(data any) (any, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, Validationf("triage final_json must be an object")
	}
	for _, field := range []string{"schema_version", "status", "summary", "items", "unknowns"} {
		if _, ok := obj[field]; !ok {
			return nil, Validationf("triage final_json.%s is required", field)
		}
	}
	version, _ := asInt(obj["schema_version"])
	status, _ := obj["status"].(string)
	if version != 1 || status != "complete" {
		return nil, Validationf(`triage final_json.status must equal "complete" and schema_version must equal 1`)
	}
	items, ok := obj["items"].([]any)
	if !ok {
		return nil, Validationf("triage final_json.items must be an array")
	}
	for i, item := range items {
		if err := validateTriageItem(item, fmt.Sprintf("triage final_json.items[%d]", i)); err != nil {
			return nil, err
		}
	}
	if err := validateStringList(obj["unknowns"], "triage final_json.unknowns"); err != nil {
		return nil, err
	}
	return data, nil
}

func decodeJSON(data []byte) (any, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	return value, nil
}

func jsonMessage(err error) string {
	var syntax *json.SyntaxError
	if errors.As(err, &syntax) {
		return err.Error()
	}
	return err.Error()
}

func requiredPositiveInt(obj map[string]any, label string, field string) (int, error) {
	raw, ok := obj[field]
	if !ok {
		return 0, Validationf("%s is required", label)
	}
	value, ok := asInt(raw)
	if !ok || value <= 0 {
		return 0, Validationf("%s must be a positive integer", label)
	}
	return value, nil
}

func requiredPositiveFloat(obj map[string]any, label string, field string) (float64, error) {
	raw, ok := obj[field]
	if !ok {
		return 0, Validationf("%s is required", label)
	}
	value, ok := asFloat(raw)
	if !ok || value <= 0 || math.IsNaN(value) || math.IsInf(value, 0) {
		return 0, Validationf("%s must be a positive finite number", label)
	}
	return value, nil
}

func asInt(value any) (int, bool) {
	switch typed := value.(type) {
	case json.Number:
		i, err := typed.Int64()
		if err != nil {
			return 0, false
		}
		return int(i), true
	case int:
		return typed, true
	case int64:
		return int(typed), true
	case float64:
		if typed == float64(int(typed)) {
			return int(typed), true
		}
	}
	return 0, false
}

func asFloat(value any) (float64, bool) {
	switch typed := value.(type) {
	case json.Number:
		f, err := typed.Float64()
		if err != nil {
			return 0, false
		}
		return f, true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case float64:
		return typed, true
	}
	return 0, false
}

func validateFacetStringList(value any, label string, minItems int, maxItems int) ([]string, error) {
	items, ok := value.([]any)
	if !ok {
		return nil, Validationf("%s must be an array of strings", label)
	}
	if len(items) < minItems || len(items) > maxItems {
		return nil, Validationf("%s must contain %d-%d items", label, minItems, maxItems)
	}
	out := make([]string, 0, len(items))
	for i, item := range items {
		normalized, err := normalizeFacetText(item, fmt.Sprintf("%s[%d]", label, i))
		if err != nil {
			return nil, err
		}
		out = append(out, normalized)
	}
	return out, nil
}

func normalizeFacetText(value any, label string) (string, error) {
	text, ok := value.(string)
	if !ok {
		return "", Validationf("%s must be a string", label)
	}
	normalized := strings.TrimSpace(facetControlRE.ReplaceAllString(text, " "))
	if normalized == "" {
		return "", Validationf("%s must be a non-empty string", label)
	}
	if strings.Contains(strings.ToLower(normalized), "</facet>") {
		return "", Validationf("%s must not contain </facet>", label)
	}
	if strings.ContainsAny(normalized, "<>") {
		return "", Validationf("%s must not contain angle brackets", label)
	}
	if strings.Contains(normalized, "`") {
		return "", Validationf("%s must not contain backticks", label)
	}
	if len(normalized) > 500 {
		return "", Validationf("%s must be at most 500 characters", label)
	}
	return normalized, nil
}

func validateClaims(value any, label string) error {
	items, ok := value.([]any)
	if !ok {
		return Validationf("%s must be an array", label)
	}
	for i, item := range items {
		if err := validateMappingClaim(item, fmt.Sprintf("%s[%d]", label, i), false); err != nil {
			return err
		}
	}
	return nil
}

func validateMappingClaim(value any, label string, requireSources bool) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	for _, field := range []string{"claim", "evidence", "confidence"} {
		if _, ok := obj[field]; !ok {
			return Validationf("%s.%s is required", label, field)
		}
	}
	if _, ok := obj["claim"].(string); !ok {
		return Validationf("%s.claim must be a string", label)
	}
	if err := validateStringList(obj["evidence"], label+".evidence"); err != nil {
		return err
	}
	if confidence, _ := obj["confidence"].(string); !contains(confidences, confidence) {
		return Validationf("%s.confidence must be one of: %s", label, strings.Join(confidences, ", "))
	}
	if requireSources {
		raw, ok := obj["sources"]
		if !ok {
			return Validationf("%s.sources is required", label)
		}
		sources, ok := raw.([]any)
		if !ok || len(sources) == 0 {
			return Validationf(`%s.sources must contain only "A" and "B"`, label)
		}
		for _, source := range sources {
			if source != "A" && source != "B" {
				return Validationf(`%s.sources must contain only "A" and "B"`, label)
			}
		}
	} else if _, ok := obj["id"].(string); !ok {
		return Validationf("%s.id must be a string", label)
	}
	return nil
}

func validateOutOfFacetClaim(value any, label string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	for _, field := range []string{"claim", "evidence", "sources", "reason"} {
		if _, ok := obj[field]; !ok {
			return Validationf("%s.%s is required", label, field)
		}
	}
	if _, ok := obj["claim"].(string); !ok {
		return Validationf("%s.claim must be a string", label)
	}
	if _, ok := obj["reason"].(string); !ok {
		return Validationf("%s.reason must be a string", label)
	}
	if err := validateStringList(obj["evidence"], label+".evidence"); err != nil {
		return err
	}
	sources, ok := obj["sources"].([]any)
	if !ok || len(sources) == 0 {
		return Validationf(`%s.sources must contain only "A" and "B"`, label)
	}
	for _, source := range sources {
		if source != "A" && source != "B" {
			return Validationf(`%s.sources must contain only "A" and "B"`, label)
		}
	}
	return nil
}

func validateScoreMap(value any, label string, fields []string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	for _, field := range fields {
		raw, ok := obj[field]
		if !ok {
			return Validationf("%s.%s is required", label, field)
		}
		score, ok := asInt(raw)
		if !ok || score < 1 || score > 5 {
			return Validationf("%s.%s must be an integer from 1 to 5", label, field)
		}
	}
	return nil
}

func validateClaimVerdict(value any, label string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	if _, ok := obj["claim_id"].(string); !ok {
		return Validationf("%s.claim_id must be a string", label)
	}
	if position, _ := obj["loser_position"].(string); !contains(loserPositions, position) {
		return Validationf("%s.loser_position must be one of: %s", label, strings.Join(loserPositions, ", "))
	}
	if raw, ok := obj["loser_note"]; ok {
		if _, ok := raw.(string); !ok {
			return Validationf("%s.loser_note must be a string", label)
		}
	}
	return nil
}

func validateLoserAddition(value any, label string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	if _, ok := obj["claim"].(string); !ok {
		return Validationf("%s.claim must be a string", label)
	}
	return validateStringList(obj["evidence"], label+".evidence")
}

func validateAnalyzeFollowup(value any, label string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	for _, field := range []string{"claim", "kind", "severity", "evidence", "recommended_action"} {
		if _, ok := obj[field]; !ok {
			return Validationf("%s.%s is required", label, field)
		}
	}
	if _, ok := obj["claim"].(string); !ok {
		return Validationf("%s.claim must be a string", label)
	}
	if kind, _ := obj["kind"].(string); !contains(followupKinds, kind) {
		return Validationf("%s.kind must be one of: %s", label, strings.Join(followupKinds, ", "))
	}
	if severity, _ := obj["severity"].(string); !contains(triageSeverities, severity) {
		return Validationf("%s.severity must be one of: %s", label, strings.Join(triageSeverities, ", "))
	}
	if action, _ := obj["recommended_action"].(string); !contains(triageActions, action) {
		return Validationf("%s.recommended_action must be one of: %s", label, strings.Join(triageActions, ", "))
	}
	return validateStringList(obj["evidence"], label+".evidence")
}

func validateTriageItem(value any, label string) error {
	obj, ok := value.(map[string]any)
	if !ok {
		return Validationf("%s must be an object", label)
	}
	fields := []string{"id", "source_finding_id", "source_finding", "classification", "severity", "confidence", "supporting_evidence", "counterevidence", "citation_check_ids", "recommended_action", "rationale"}
	for _, field := range fields {
		if _, ok := obj[field]; !ok {
			return Validationf("%s.%s is required", label, field)
		}
	}
	if classification, _ := obj["classification"].(string); !contains(triageClasses, classification) {
		return Validationf("%s.classification must be one of: %s", label, strings.Join(triageClasses, ", "))
	}
	if severity, _ := obj["severity"].(string); !contains(triageSeverities, severity) {
		return Validationf("%s.severity must be one of: %s", label, strings.Join(triageSeverities, ", "))
	}
	if confidence, _ := obj["confidence"].(string); !contains(confidences, confidence) {
		return Validationf("%s.confidence must be one of: %s", label, strings.Join(confidences, ", "))
	}
	if action, _ := obj["recommended_action"].(string); !contains(triageActions, action) {
		return Validationf("%s.recommended_action must be one of: %s", label, strings.Join(triageActions, ", "))
	}
	for _, field := range []string{"supporting_evidence", "counterevidence", "citation_check_ids"} {
		if err := validateStringList(obj[field], label+"."+field); err != nil {
			return err
		}
	}
	return nil
}

func validateStringList(value any, label string) error {
	items, ok := value.([]any)
	if !ok {
		return Validationf("%s must be an array of strings", label)
	}
	for _, item := range items {
		if _, ok := item.(string); !ok {
			return Validationf("%s must be an array of strings", label)
		}
	}
	return nil
}

func validateStringOrList(value any, label string) error {
	if _, ok := value.(string); ok {
		return nil
	}
	return validateStringList(value, label)
}

func contains(values []string, value string) bool {
	return slices.Contains(values, value)
}

func cloneMap(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func valueOrDefault(obj map[string]any, key string, fallback any) any {
	if value, ok := obj[key]; ok {
		return value
	}
	return fallback
}

func sumStringLens(values []string) int {
	total := 0
	for _, value := range values {
		total += len(value)
	}
	return total
}

func pyRepr(value any) string {
	switch typed := value.(type) {
	case string:
		return "'" + strings.ReplaceAll(typed, "'", "\\'") + "'"
	case nil:
		return "None"
	case bool:
		if typed {
			return "True"
		}
		return "False"
	default:
		return fmt.Sprintf("%v", value)
	}
}
