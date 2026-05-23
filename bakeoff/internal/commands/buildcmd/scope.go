package buildcmd

import (
	"context"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/scope"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type buildScopeDiagnostics struct {
	IntendedPrefix        string                       `json:"intended_prefix"`
	OutOfInvocationFiles  []buildworkspace.ChangedFile `json:"out_of_invocation_files,omitempty"`
	AgentInstructionFiles []buildworkspace.ChangedFile `json:"agent_instruction_files,omitempty"`
	Warnings              []string                     `json:"warnings,omitempty"`
}

func buildParticipantArgv(participant workorder.Participant, policy workorder.ScopePolicy, worktreePath string, caps provider.ScopeCapabilities, finalMessagePath string) ([]string, map[string]any, error) {
	requestedScope := participant.Scope
	if requestedScope == "" {
		requestedScope = "mixed"
	}
	enforcement := policy.Enforcement
	if enforcement == "" {
		enforcement = "best_effort"
	}
	supports := caps.Supports
	if supports == nil {
		supports = map[string]bool{}
	}
	extraArgs := []string{}
	mechanisms := []string{"worktree_cwd"}
	fallbackReasons := []string{}
	switch participant.Backend {
	case "claude":
		if requestedScope == "codebase" {
			if supports["disallowed_tools"] {
				extraArgs = append(extraArgs, "--disallowedTools", "WebFetch", "WebSearch")
				mechanisms = append(mechanisms, "claude:disallowedTools=WebFetch,WebSearch")
			} else {
				fallbackReasons = append(fallbackReasons, "claude CLI did not advertise --disallowedTools")
			}
		}
	case "codex":
		if supports["sandbox_workspace_write"] {
			extraArgs = append(extraArgs, "--sandbox", "workspace-write")
			mechanisms = append(mechanisms, "codex:sandbox=workspace-write")
		} else {
			fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --sandbox workspace-write")
		}
		if requestedScope == "codebase" {
			if supports["disable_feature"] {
				extraArgs = append(extraArgs, "--disable", "web_search")
				mechanisms = append(mechanisms, "codex:disable=web_search")
			} else {
				fallbackReasons = append(fallbackReasons, "codex CLI did not advertise --disable")
			}
		}
	case "gemini":
		if supports["approval_auto_edit"] {
			extraArgs = append(extraArgs, "--approval-mode", "auto_edit")
			mechanisms = append(mechanisms, "gemini:approval-mode=auto_edit")
		} else if supports["approval_yolo"] {
			extraArgs = append(extraArgs, "--approval-mode", "yolo")
			mechanisms = append(mechanisms, "gemini:approval-mode=yolo")
		} else if supports["yolo_flag"] {
			extraArgs = append(extraArgs, "--yolo")
			mechanisms = append(mechanisms, "gemini:yolo")
		} else {
			fallbackReasons = append(fallbackReasons, "gemini --help did not advertise non-interactive edit mode; configure --approval-mode auto_edit or --yolo")
		}
		if requestedScope == "codebase" {
			fallbackReasons = append(fallbackReasons, "gemini CLI scope controls are advisory for codebase scope")
		}
	case "copilot":
		if supports["no_ask_user"] {
			mechanisms = append(mechanisms, "copilot:no-ask-user")
		} else {
			fallbackReasons = append(fallbackReasons, "copilot --help did not advertise --no-ask-user")
		}
		if supports["allow_tool"] {
			extraArgs = append(extraArgs, "--allow-tool", "edit")
			mechanisms = append(mechanisms, "copilot:allow-tool=edit")
		}
		if requestedScope == "codebase" {
			fallbackReasons = append(fallbackReasons, "copilot CLI scope controls are advisory for codebase scope")
		}
	}
	minimumControls := buildMinimumControls(participant.Backend)
	missingMinimumControls := missingBuildMinimumControls(participant.Backend, supports)
	if len(missingMinimumControls) > 0 {
		metadata := map[string]any{
			"requested_scope":            requestedScope,
			"policy":                     enforcement,
			"effective_scope":            "advisory",
			"enforcement_level":          "failed",
			"mechanisms":                 mechanisms,
			"fallback_reason":            strings.Join(fallbackReasons, "; "),
			"minimum_controls":           minimumControls,
			"minimum_controls_satisfied": false,
			"minimum_control_failures":   missingMinimumControls,
			"cwd":                        worktreePath,
			"temporary_cwd":              false,
		}
		return nil, metadata, &scope.EnforcementError{Message: strings.Join(fallbackReasons, "; ")}
	}
	metadata := map[string]any{
		"requested_scope":            requestedScope,
		"policy":                     enforcement,
		"effective_scope":            requestedScope,
		"enforcement_level":          "enforced",
		"mechanisms":                 mechanisms,
		"fallback_reason":            nil,
		"minimum_controls":           minimumControls,
		"minimum_controls_satisfied": len(minimumControls) == 0 || len(missingMinimumControls) == 0,
		"cwd":                        worktreePath,
		"temporary_cwd":              false,
	}
	if len(fallbackReasons) > 0 {
		metadata["fallback_reason"] = strings.Join(fallbackReasons, "; ")
		if enforcement == "required" {
			metadata["effective_scope"] = "advisory"
			metadata["enforcement_level"] = "failed"
			return nil, metadata, &scope.EnforcementError{Message: strings.Join(fallbackReasons, "; ")}
		}
		metadata["enforcement_level"] = "partial"
	}
	argv, err := provider.BuildParticipantArgv(participant, worktreePath, extraArgs, finalMessagePath, commands.SupportsOutputLastMessage(participant, caps))
	return argv, metadata, err
}

func mustFailBuildScope(backend string, supports map[string]bool) bool {
	return len(missingBuildMinimumControls(backend, supports)) > 0
}

func buildMinimumControls(backend string) []string {
	switch backend {
	case "codex":
		return []string{"codex:sandbox=workspace-write"}
	case "gemini":
		return []string{"gemini:non-interactive-edit-mode"}
	case "copilot":
		return []string{"copilot:no-ask-user"}
	default:
		return nil
	}
}

func missingBuildMinimumControls(backend string, supports map[string]bool) []string {
	switch backend {
	case "codex":
		if !supports["sandbox_workspace_write"] {
			return []string{"codex:sandbox=workspace-write"}
		}
	case "gemini":
		if !supports["approval_auto_edit"] && !supports["approval_yolo"] && !supports["yolo_flag"] {
			return []string{"gemini:non-interactive-edit-mode"}
		}
	case "copilot":
		if !supports["no_ask_user"] {
			return []string{"copilot:no-ask-user"}
		}
	}
	return nil
}

func providerCapabilities(ctx context.Context, f commands.Factory, wo *workorder.WorkOrder) map[string]provider.ScopeCapabilities {
	out := map[string]provider.ScopeCapabilities{}
	for _, participant := range wo.Providers {
		if _, ok := out[participant.Backend]; ok {
			continue
		}
		out[participant.Backend] = f.Capabilities().DetectScopeCapabilities(ctx, participant.Backend)
	}
	return out
}

func diagnoseBuildScope(repo buildworkspace.Repository, changed []buildworkspace.ChangedFile) buildScopeDiagnostics {
	prefix := strings.Trim(filepath.ToSlash(repo.InvocationRelPath), "/")
	if prefix == "" {
		prefix = "."
	}
	diagnostics := buildScopeDiagnostics{IntendedPrefix: prefix}
	for _, file := range changed {
		path := normalizeChangedPath(file.Path)
		if prefix != "." && path != prefix && !strings.HasPrefix(path, prefix+"/") {
			diagnostics.OutOfInvocationFiles = append(diagnostics.OutOfInvocationFiles, file)
		}
		if isAgentInstructionPath(path) {
			diagnostics.AgentInstructionFiles = append(diagnostics.AgentInstructionFiles, file)
		}
	}
	if len(diagnostics.OutOfInvocationFiles) > 0 {
		diagnostics.Warnings = append(diagnostics.Warnings, "patch changes files outside the invocation directory")
	}
	if len(diagnostics.AgentInstructionFiles) > 0 {
		diagnostics.Warnings = append(diagnostics.Warnings, "patch changes local agent instruction/config files")
	}
	return diagnostics
}

func normalizeChangedPath(path string) string {
	if strings.Contains(path, " -> ") {
		parts := strings.Split(path, " -> ")
		path = parts[len(parts)-1]
	}
	return strings.Trim(filepath.ToSlash(path), "/")
}

func isAgentInstructionPath(path string) bool {
	path = strings.Trim(filepath.ToSlash(path), "/")
	base := filepath.Base(path)
	if base == "CLAUDE.md" || base == "AGENTS.md" || base == "GEMINI.md" {
		return true
	}
	return strings.HasPrefix(path, ".claude/") ||
		strings.HasPrefix(path, ".codex/") ||
		strings.HasPrefix(path, ".gemini/") ||
		path == ".github/copilot-instructions.md" ||
		strings.Contains(path, "/.claude/") ||
		strings.Contains(path, "/.codex/") ||
		strings.Contains(path, "/.gemini/") ||
		strings.HasSuffix(path, "/.github/copilot-instructions.md")
}
