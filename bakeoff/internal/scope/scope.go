package scope

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runstatus"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const StatusScopeError = runstatus.ScopeError

type EnforcementError struct {
	Message string
}

func (e *EnforcementError) Error() string {
	return e.Message
}

type Execution struct {
	Argv         []string
	CWD          string
	CleanupPaths []string
	Metadata     map[string]any
}

func BuildExecution(ctx context.Context, registry *provider.CapabilityRegistry, participant workorder.Participant, policy workorder.ScopePolicy, workspaceCWD string, runDir string, caps *provider.ScopeCapabilities, finalMessagePath string) (Execution, error) {
	requestedScope := participant.Scope
	if requestedScope == "" {
		requestedScope = "mixed"
	}
	enforcement := policy.Enforcement
	if enforcement == "" {
		enforcement = "best_effort"
	}
	executionCWD := workspaceCWD
	mechanisms := []string{}
	fallbackReasons := []string{}
	extraArgs := []string{}
	cleanupPaths := []string{}

	if enforcement == "advisory" {
		return execution(ctx, registry, participant, executionCWD, extraArgs, cleanupPaths, finalMessagePath, enforcement, requestedScope, "advisory", "advisory", mechanisms, fallbackReasons, outputLastMessageSupport(ctx, registry, participant, nil))
	}

	actualCaps := provider.ScopeCapabilities{Backend: participant.Backend, Available: false, Supports: map[string]bool{}}
	if caps != nil {
		actualCaps = *caps
	} else if registry != nil {
		actualCaps = registry.DetectScopeCapabilities(ctx, participant.Backend)
	}
	supports := actualCaps.Supports
	if supports == nil {
		supports = map[string]bool{}
	}
	outputLastMessage := outputLastMessageSupport(ctx, registry, participant, supports)

	needsIsolatedCWD := requestedScope == "web"
	if requestedScope == "web" {
		mechanisms = append(mechanisms, "isolated_cwd")
	}

	switch {
	case requestedScope == "mixed":
		mechanisms = append(mechanisms, "mixed_scope_no_restriction")
	case participant.Backend == "claude" && requestedScope == "codebase":
		if supports["disallowed_tools"] {
			extraArgs = append(extraArgs, "--disallowedTools", "WebFetch", "WebSearch")
			mechanisms = append(mechanisms, "claude:disallowedTools=WebFetch,WebSearch")
		} else {
			fallbackReasons = append(fallbackReasons, "claude CLI did not advertise --disallowedTools")
		}
	case participant.Backend == "claude" && requestedScope == "web":
		if supports["allowed_tools"] {
			extraArgs = append(extraArgs, "--allowedTools", "WebFetch", "WebSearch")
			mechanisms = append(mechanisms, "claude:allowedTools=WebFetch,WebSearch")
		} else {
			fallbackReasons = append(fallbackReasons, "claude CLI did not advertise --allowedTools")
		}
	case participant.Backend == "codex":
		if requestedScope == "codebase" || requestedScope == "web" {
			if supports["sandbox"] {
				extraArgs = append(extraArgs, "--sandbox", "read-only")
				mechanisms = append(mechanisms, "codex:sandbox=read-only")
			} else {
				fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --sandbox")
			}
		}
		if requestedScope == "codebase" {
			if supports["disable_feature"] {
				extraArgs = append(extraArgs, "--disable", "web_search")
				mechanisms = append(mechanisms, "codex:disable=web_search")
			} else {
				fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --disable")
			}
		}
	case participant.Backend == "gemini" || participant.Backend == "copilot":
		if requestedScope == "codebase" || requestedScope == "web" {
			mechanisms = append(mechanisms, "prompt_scope_instruction")
			fallbackReasons = append(fallbackReasons, participant.Backend+" CLI scope controls are advisory for "+requestedScope+" scope")
		}
	}

	enforcementLevel := "partial"
	if requestedScope == "mixed" || (len(mechanisms) > 0 && len(fallbackReasons) == 0) {
		enforcementLevel = "enforced"
	}
	if len(mechanisms) == 0 {
		enforcementLevel = "advisory"
	}
	if len(fallbackReasons) > 0 && enforcement == "required" {
		return Execution{}, &EnforcementError{Message: joinReasons(fallbackReasons)}
	}

	if needsIsolatedCWD {
		path, err := makeScopeWorkspace(filepath.Base(runDir), participant.ID)
		if err != nil {
			return Execution{}, err
		}
		executionCWD = path
		cleanupPaths = append(cleanupPaths, path)
	}

	effectiveScope := requestedScope
	if enforcementLevel == "advisory" {
		effectiveScope = "advisory"
	}
	return execution(ctx, registry, participant, executionCWD, extraArgs, cleanupPaths, finalMessagePath, enforcement, requestedScope, effectiveScope, enforcementLevel, mechanisms, fallbackReasons, outputLastMessage)
}

func execution(_ context.Context, _ *provider.CapabilityRegistry, participant workorder.Participant, executionCWD string, extraArgs []string, cleanupPaths []string, finalMessagePath string, policy string, requestedScope string, effectiveScope string, enforcementLevel string, mechanisms []string, fallbackReasons []string, outputLastMessage bool) (Execution, error) {
	argv, err := provider.BuildParticipantArgv(participant, executionCWD, extraArgs, finalMessagePath, outputLastMessage)
	if err != nil {
		return Execution{}, err
	}
	metadata := map[string]any{
		"requested_scope":   requestedScope,
		"policy":            policy,
		"effective_scope":   effectiveScope,
		"enforcement_level": enforcementLevel,
		"mechanisms":        mechanisms,
		"fallback_reason":   nil,
		"cwd":               executionCWD,
		"temporary_cwd":     len(cleanupPaths) > 0,
	}
	if len(fallbackReasons) > 0 {
		metadata["fallback_reason"] = joinReasons(fallbackReasons)
	}
	return Execution{Argv: argv, CWD: executionCWD, CleanupPaths: cleanupPaths, Metadata: metadata}, nil
}

func ScopeErrorResult(err error, provider workorder.Participant, policy workorder.ScopePolicy, cwd string) map[string]any {
	requestedScope := provider.Scope
	if requestedScope == "" {
		requestedScope = "mixed"
	}
	enforcement := policy.Enforcement
	if enforcement == "" {
		enforcement = "best_effort"
	}
	message := err.Error()
	stderrBytes := len([]byte(message))
	return map[string]any{
		"status":                StatusScopeError,
		"exit_code":             nil,
		"wall_seconds":          0,
		"output_bytes":          0,
		"stdout_bytes":          0,
		"stderr_bytes":          stderrBytes,
		"stdout_observed_bytes": 0,
		"stderr_observed_bytes": stderrBytes,
		"stdout_truncated":      false,
		"stderr_truncated":      false,
		"io":                    map[string]any{"stdout_bytes": 0, "stderr_bytes": stderrBytes, "stdout_observed_bytes": 0, "stderr_observed_bytes": stderrBytes, "total_observed_bytes": stderrBytes},
		"stdout":                "",
		"stderr":                message,
		"final_json":            nil,
		"scope_enforcement": map[string]any{
			"requested_scope":   requestedScope,
			"policy":            enforcement,
			"effective_scope":   "advisory",
			"enforcement_level": "failed",
			"mechanisms":        []string{},
			"fallback_reason":   message,
			"cwd":               cwd,
			"temporary_cwd":     false,
		},
	}
}

func outputLastMessageSupport(ctx context.Context, registry *provider.CapabilityRegistry, participant workorder.Participant, supports map[string]bool) bool {
	if supports != nil {
		return supports["output_last_message"]
	}
	if registry == nil {
		return false
	}
	caps := registry.DetectScopeCapabilities(ctx, participant.Backend)
	return caps.Supports["output_last_message"]
}

func Cleanup(paths []string) {
	for _, path := range paths {
		_ = os.RemoveAll(path)
	}
}

var unsafePrefixRE = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func makeScopeWorkspace(runID string, providerID string) (string, error) {
	prefix := fmt.Sprintf("bakeoff-%s-%s-", safeTempPrefix(runID), safeTempPrefix(providerID))
	path, err := os.MkdirTemp("", prefix)
	if err != nil {
		return "", err
	}
	if err := os.Chmod(path, 0o700); err != nil {
		_ = os.RemoveAll(path)
		return "", err
	}
	return path, nil
}

func safeTempPrefix(value string) string {
	out := unsafePrefixRE.ReplaceAllString(value, "-")
	if len(out) > 80 {
		out = out[:80]
	}
	if out == "" {
		return "scope"
	}
	return out
}

func joinReasons(reasons []string) string {
	if len(reasons) == 0 {
		return ""
	}
	out := reasons[0]
	for _, reason := range reasons[1:] {
		out += "; " + reason
	}
	return out
}
