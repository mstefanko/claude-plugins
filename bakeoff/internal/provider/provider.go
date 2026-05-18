package provider

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

var DefaultModelIDs = map[string]string{
	"claude_sonnet": "claude-sonnet-4-6",
	"claude_opus":   "claude-opus-4-7",
	"claude_haiku":  "claude-haiku-4-5-20251001",
	"codex":         "gpt-5.5",
	"codex_gpt5":    "gpt-5",
}

type LookupFunc func(string) (string, error)

type CapabilityRegistry struct {
	lookup LookupFunc

	mu    sync.Mutex
	cache map[string]capabilityEntry
}

type capabilityEntry struct {
	ready chan struct{}
	value any
}

type ScopeCapabilities struct {
	Backend    string          `json:"backend"`
	Available  bool            `json:"available"`
	Supports   map[string]bool `json:"supports"`
	ProbeError string          `json:"probe_error,omitempty"`
}

func NewCapabilityRegistry(lookup LookupFunc) *CapabilityRegistry {
	if lookup == nil {
		lookup = exec.LookPath
	}
	return &CapabilityRegistry{lookup: lookup, cache: map[string]capabilityEntry{}}
}

func BuildParticipantArgv(participant workorder.Participant, cwd string, extraArgs []string, finalMessagePath string, codexOutputLastMessage bool) ([]string, error) {
	effort := participant.Effort
	if effort == "" {
		effort = "high"
	}
	extras := append([]string(nil), extraArgs...)
	switch participant.Backend {
	case "claude":
		argv := []string{"claude", "-p", "--model", participant.Model, "--effort", effort}
		argv = append(argv, extras...)
		return argv, nil
	case "codex":
		argv := []string{"codex", "exec", "-m", participant.Model, "-c", fmt.Sprintf(`model_reasoning_effort="%s"`, effort), "--skip-git-repo-check"}
		argv = append(argv, extras...)
		if finalMessagePath != "" && codexOutputLastMessage {
			argv = append(argv, "--output-last-message", finalMessagePath)
		}
		if cwd != "" {
			argv = append(argv, "-C", cwd)
		}
		return argv, nil
	default:
		return nil, fmt.Errorf("unsupported backend: %s", participant.Backend)
	}
}

func VersionArgv(tool string) ([]string, error) {
	switch tool {
	case "claude":
		return []string{"claude", "--version"}, nil
	case "codex":
		return []string{"codex", "--version"}, nil
	case "git":
		return []string{"git", "--version"}, nil
	default:
		return nil, fmt.Errorf("unsupported tool: %s", tool)
	}
}

func ScopeHelpArgv(backend string) ([]string, error) {
	switch backend {
	case "claude":
		return []string{"claude", "-p", "--help"}, nil
	case "codex":
		return []string{"codex", "exec", "--help"}, nil
	default:
		return nil, fmt.Errorf("unsupported backend: %s", backend)
	}
}

func (r *CapabilityRegistry) DetectScopeCapabilities(ctx context.Context, backend string) ScopeCapabilities {
	key := "scope:" + backend
	value := r.getOrProbe(key, func() any {
		return r.probeScopeCapabilities(ctx, backend)
	})
	caps, ok := value.(ScopeCapabilities)
	if !ok {
		return ScopeCapabilities{Backend: backend, Available: false, Supports: map[string]bool{}, ProbeError: "invalid cached capability result"}
	}
	return caps
}

func (r *CapabilityRegistry) getOrProbe(key string, probe func() any) any {
	r.mu.Lock()
	if entry, ok := r.cache[key]; ok {
		r.mu.Unlock()
		<-entry.ready
		return entry.value
	}
	entry := capabilityEntry{ready: make(chan struct{})}
	r.cache[key] = entry
	r.mu.Unlock()

	value := probe()

	r.mu.Lock()
	entry.value = value
	r.cache[key] = entry
	close(entry.ready)
	r.mu.Unlock()
	return value
}

func (r *CapabilityRegistry) probeScopeCapabilities(ctx context.Context, backend string) ScopeCapabilities {
	argv, err := ScopeHelpArgv(backend)
	if err != nil {
		return ScopeCapabilities{Backend: backend, Available: false, Supports: map[string]bool{}, ProbeError: err.Error()}
	}
	helpText, err := r.runProbe(ctx, argv, 10*time.Second)
	if err != nil {
		return ScopeCapabilities{Backend: backend, Available: false, Supports: map[string]bool{}, ProbeError: err.Error()}
	}
	return ScopeCapabilitiesFromHelp(backend, helpText)
}

func (r *CapabilityRegistry) runProbe(ctx context.Context, argv []string, timeout time.Duration) (string, error) {
	if len(argv) == 0 {
		return "", fmt.Errorf("empty probe argv")
	}
	exe, err := r.lookup(argv[0])
	if err != nil {
		return "", fmt.Errorf("FileNotFoundError: [Errno 2] No such file or directory: '%s'", argv[0])
	}
	probeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(probeCtx, exe, argv[1:]...)
	cmd.Env = runnerenv.SafeEnv(os.Environ())
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err = cmd.Run()
	if probeCtx.Err() == context.DeadlineExceeded {
		return "", fmt.Errorf("%s probe timed out: %w", argv[0], probeCtx.Err())
	}
	text := stdout.String() + "\n" + stderr.String()
	if err != nil {
		// Python treats a help command that exits non-zero but prints help as available.
		if strings.TrimSpace(text) != "" {
			return text, nil
		}
		return "", fmt.Errorf("%s probe failed: %w", argv[0], err)
	}
	return text, nil
}

func ScopeCapabilitiesFromHelp(backend string, helpText string) ScopeCapabilities {
	options := HelpOptionTokens(helpText)
	supports := map[string]bool{}
	switch backend {
	case "claude":
		supports["allowed_tools"] = HasHelpOption(options, "--allowedTools", "--allowed-tools")
		supports["disallowed_tools"] = HasHelpOption(options, "--disallowedTools", "--disallowed-tools")
		supports["tools"] = HasHelpOption(options, "--tools")
		supports["permission_mode"] = HasHelpOption(options, "--permission-mode")
	case "codex":
		supports["sandbox"] = HasHelpOption(options, "--sandbox")
		supports["sandbox_workspace_write"] = supports["sandbox"] && strings.Contains(helpText, "workspace-write")
		supports["disable_feature"] = HasHelpOption(options, "--disable")
		supports["profile"] = HasHelpOption(options, "--profile")
		supports["config"] = HasHelpOption(options, "--config")
		supports["output_last_message"] = HasHelpOption(options, "--output-last-message")
	default:
		return ScopeCapabilities{Backend: backend, Available: false, Supports: supports, ProbeError: fmt.Sprintf("unsupported backend: %s", backend)}
	}
	return ScopeCapabilities{Backend: backend, Available: true, Supports: supports}
}

var helpOptionRE = regexp.MustCompile(`--[A-Za-z0-9][A-Za-z0-9-]*`)

func HelpOptionTokens(helpText string) map[string]bool {
	out := map[string]bool{}
	for _, token := range helpOptionRE.FindAllString(helpText, -1) {
		out[token] = true
	}
	return out
}

func HasHelpOption(options map[string]bool, names ...string) bool {
	for _, name := range names {
		if options[name] {
			return true
		}
	}
	return false
}
