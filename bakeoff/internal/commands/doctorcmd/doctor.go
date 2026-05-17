package doctorcmd

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type DoctorOptions struct {
	SkipAuthProbe bool
	Quiet         bool
	JSON          bool
}

func NewCmdDoctor(f commands.Factory, runF func(context.Context, *DoctorOptions) error) *cobra.Command {
	_ = f
	opts := &DoctorOptions{}
	cmd := &cobra.Command{
		Use:           "doctor",
		Short:         "check provider CLIs, auth, and local readiness",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			if runF == nil {
				return runDoctor(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().BoolVar(&opts.SkipAuthProbe, "skip-auth-probe", false, "skip spendful provider auth probes")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a parseable JSON readiness report")
	return cmd
}

func runDoctor(ctx context.Context, f commands.Factory, opts *DoctorOptions) error {
	failed := false
	report := map[string]any{
		"command": "doctor",
		"status":  "ok",
		"tools":   map[string]any{},
		"defaults": map[string]any{
			"claude_haiku":  provider.DefaultModelIDs["claude_haiku"],
			"claude_opus":   provider.DefaultModelIDs["claude_opus"],
			"claude_sonnet": provider.DefaultModelIDs["claude_sonnet"],
			"codex":         provider.DefaultModelIDs["codex"],
			"codex_gpt5":    provider.DefaultModelIDs["codex_gpt5"],
		},
		"scope_policy": map[string]any{
			"default_enforcement": "best_effort",
			"status_artifacts":    []string{"provider status.json", "meta.json"},
		},
		"scope_capabilities": map[string]any{},
		"auth_probes":        map[string]any{},
		"warnings":           []string{},
	}
	tools := report["tools"].(map[string]any)
	for _, tool := range []string{"claude", "codex", "git"} {
		path, err := f.LookupProvider(tool)
		if err != nil {
			tools[tool] = map[string]any{"ok": false, "path": nil, "version": nil}
			failed = true
			continue
		}
		tools[tool] = map[string]any{"ok": true, "path": path, "version": artifact.ToolVersion(ctx, tool, f.LookupProvider)}
	}

	scopeCaps := report["scope_capabilities"].(map[string]any)
	capabilityValues := map[string]provider.ScopeCapabilities{}
	for _, backend := range []string{"claude", "codex"} {
		caps := f.Capabilities().DetectScopeCapabilities(ctx, backend)
		capabilityValues[backend] = caps
		capMap := map[string]any{
			"available": caps.Available,
			"backend":   caps.Backend,
			"supports":  caps.Supports,
		}
		if caps.ProbeError != "" {
			capMap["probe_error"] = caps.ProbeError
		}
		scopeCaps[backend] = capMap
		if !caps.Available {
			failed = true
		}
	}
	writable, detail := checkCWDWritable()
	cwd, _ := os.Getwd()
	report["cwd_writable"] = map[string]any{"ok": writable, "detail": detail, "cwd": cwd}
	if !writable {
		failed = true
	}
	report["bias"] = "Default judge is claude/opus alongside claude/sonnet workers. Position-swap is the primary bias mitigation; same-family bias is an accepted v1 risk."

	if !opts.JSON {
		streams := f.Streams()
		streams.Printf("bakeoff doctor\n")
		for _, tool := range []string{"claude", "codex", "git"} {
			toolStatus := tools[tool].(map[string]any)
			if !toolStatus["ok"].(bool) {
				streams.Printf("- %s: missing\n", tool)
			} else {
				streams.Printf("- %s: %s (%s)\n", tool, toolStatus["path"], toolStatus["version"])
			}
		}
		streams.Printf("- defaults:\n")
		for _, key := range []string{"claude_sonnet", "claude_opus", "claude_haiku", "codex", "codex_gpt5"} {
			streams.Printf("  %s: %s\n", key, provider.DefaultModelIDs[key])
		}
		streams.Printf("- scope policy: best_effort by default; provider status records enforcement and advisory fallback.\n")
		streams.Printf("- scope capabilities:\n")
		for _, backend := range []string{"claude", "codex"} {
			caps := capabilityValues[backend]
			if !caps.Available {
				streams.Printf("  %s: unavailable (%s)\n", backend, caps.ProbeError)
				continue
			}
			supported := []string{}
			missing := []string{}
			for _, name := range supportOrder(backend) {
				if caps.Supports[name] {
					supported = append(supported, name)
				} else {
					missing = append(missing, name)
				}
			}
			supportedText := "none"
			if len(supported) > 0 {
				supportedText = joinComma(supported)
			}
			streams.Printf("  %s: supports %s\n", backend, supportedText)
			if len(missing) > 0 {
				streams.Printf("    missing: %s\n", joinComma(missing))
			}
		}
		status := "failed"
		if writable {
			status = "ok"
		}
		streams.Printf("- cwd writable: %s (%s)\n", status, detail)
		streams.Printf("- bias: %s\n", report["bias"])
	}
	if !opts.SkipAuthProbe && !failed {
		if err := runAuthProbes(ctx, f, opts, report); err != nil {
			return err
		}
	}
	if failed {
		report["status"] = "failed"
	}
	if opts.JSON {
		if err := summary.Print(f.Streams().Out, report); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
	}
	return nil
}

func runAuthProbes(ctx context.Context, f commands.Factory, opts *DoctorOptions, report map[string]any) error {
	authProbes := report["auth_probes"].(map[string]any)
	prompt := `Auth probe. Reply exactly with <final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>`
	cwd, _ := os.Getwd()
	participants := []workorder.Participant{
		{Backend: "claude", Model: provider.DefaultModelIDs["claude_sonnet"], Effort: "low"},
		{Backend: "codex", Model: provider.DefaultModelIDs["codex"], Effort: "low"},
	}
	for _, participant := range participants {
		argv, err := provider.BuildParticipantArgv(participant, cwd, nil, "", false)
		if err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		result := artifact.ResultMap(runner.RunProvider(ctx, runner.Options{
			Argv:    argv,
			Prompt:  prompt,
			Budgets: runner.Budgets{WallClockSeconds: 30, MaxOutputBytes: 10000},
			CWD:     cwd,
			Env:     os.Environ(),
			OnTick:  commands.MakeTickPrinter(f, participant.Backend+":auth", opts.Quiet),
		}))
		if ctx.Err() != nil {
			return ctx.Err()
		}
		probeStatus := authProbeStatus(result)
		authProbes[participant.Backend] = probeStatus
		if !opts.JSON {
			f.Streams().Printf("- %s auth probe: %s\n", participant.Backend, result["status"])
		}
		if result["status"] != runner.StatusOK {
			warning := participant.Backend + " auth probe failed with " + stringValue(result["status"])
			if reason := stringValue(probeStatus["reason"]); reason != "" {
				warning += ": " + reason
			}
			report["warnings"] = appendStringAny(report["warnings"], warning)
			if !opts.JSON {
				f.Streams().Errorf("warning: %s\n", warning)
			}
		}
	}
	return nil
}

func authProbeStatus(result map[string]any) map[string]any {
	status := artifact.StatusWithoutPayload(result)
	if result["status"] == runner.StatusOK {
		return status
	}
	diagnosticText := stringValue(result["stderr"])
	if diagnosticText == "" {
		diagnosticText = stringValue(result["stdout"])
	}
	if reason := lastNonemptyLine(diagnosticText); reason != "" {
		status["reason"] = reason
	}
	if tail := diagnosticTail(diagnosticText); tail != "" {
		status["diagnostic_tail"] = tail
	}
	return status
}

func checkCWDWritable() (bool, string) {
	cwd, err := os.Getwd()
	if err != nil {
		return false, err.Error()
	}
	file, err := os.CreateTemp(cwd, ".bakeoff-doctor-write-test-*")
	if err != nil {
		return false, err.Error()
	}
	name := file.Name()
	_, writeErr := file.WriteString("ok\n")
	closeErr := file.Close()
	removeErr := os.Remove(name)
	if writeErr != nil {
		return false, writeErr.Error()
	}
	if closeErr != nil {
		return false, closeErr.Error()
	}
	if removeErr != nil {
		return false, removeErr.Error()
	}
	return true, filepath.Clean(cwd)
}

func supportOrder(backend string) []string {
	if backend == "claude" {
		return []string{"allowed_tools", "disallowed_tools", "tools", "permission_mode"}
	}
	return []string{"sandbox", "disable_feature", "profile", "config", "output_last_message"}
}

func joinComma(items []string) string {
	out := ""
	for i, item := range items {
		if i > 0 {
			out += ", "
		}
		out += item
	}
	return out
}

func lastNonemptyLine(text string) string {
	lines := strings.Split(text, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		stripped := strings.TrimSpace(lines[i])
		if stripped != "" {
			return stripped
		}
	}
	return ""
}

func diagnosticTail(text string) string {
	lines := []string{}
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) != "" {
			lines = append(lines, strings.TrimRight(line, " \t\r"))
		}
	}
	if len(lines) == 0 {
		return ""
	}
	if len(lines) > 5 {
		lines = lines[len(lines)-5:]
	}
	tail := strings.Join(lines, "\n")
	if len(tail) > 1000 {
		return tail[len(tail)-1000:]
	}
	return tail
}

func appendStringAny(value any, item string) []string {
	items, _ := value.([]string)
	return append(items, item)
}

func stringValue(value any) string {
	text, _ := value.(string)
	return text
}
