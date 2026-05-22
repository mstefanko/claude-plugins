package doctorcmd

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/modeldefaults"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type DoctorOptions struct {
	SkipAuthProbe bool
	Build         bool
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
	cmd.Flags().BoolVar(&opts.Build, "build", false, "run live provider edit probes in temporary workspaces")
	cmd.Flags().BoolVar(&opts.SkipAuthProbe, "skip-auth-probe", false, "skip spendful provider auth probes")
	cmd.Flags().BoolVar(&opts.Quiet, "quiet", false, "suppress provider heartbeat lines")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a parseable JSON readiness report")
	return cmd
}

func runDoctor(ctx context.Context, f commands.Factory, opts *DoctorOptions) error {
	failed := false
	defaults := modeldefaults.DoctorModelIDs()
	canonicalPair := provider.CanonicalDefaultPair()
	report := map[string]any{
		"command":                         "doctor",
		"status":                          "ok",
		"tools":                           map[string]any{},
		"defaults":                        defaults,
		"canonical_default_pair":          canonicalPair,
		"selected_default_pair":           nil,
		"fallback_candidates":             [][]string{},
		"fallback_requires_user_choice":   false,
		"canonical_default_available":     false,
		"runnable_default_pair_available": false,
		"providers":                       map[string]any{},
		"scope_policy": map[string]any{
			"default_enforcement": "best_effort",
			"status_artifacts":    []string{"provider status.json", "meta.json"},
		},
		"scope_capabilities": map[string]any{},
		"auth_probes":        map[string]any{},
		"warnings":           []string{},
	}
	tools := report["tools"].(map[string]any)
	providerEntries := report["providers"].(map[string]any)
	toolNames := append([]string{}, provider.BackendNames()...)
	toolNames = append(toolNames, "git")
	toolOK := map[string]bool{}
	for _, tool := range toolNames {
		path, err := f.LookupProvider(tool)
		if err != nil {
			tools[tool] = map[string]any{"ok": false, "path": nil, "version": nil}
			toolOK[tool] = false
		} else {
			version := artifact.ToolVersion(ctx, tool, f.LookupProvider)
			tools[tool] = map[string]any{"ok": true, "path": path, "version": version}
			toolOK[tool] = true
		}
	}
	if !toolOK["git"] {
		failed = true
		report["warnings"] = appendStringAny(report["warnings"], "git is required for most Bakeoff workflows")
	}

	scopeCaps := report["scope_capabilities"].(map[string]any)
	capabilityValues := map[string]provider.ScopeCapabilities{}
	readyForDefault := map[string]bool{}
	for _, spec := range provider.KnownBackends() {
		toolStatus := tools[spec.Name].(map[string]any)
		entry := map[string]any{
			"canonical_default":             provider.BackendInPair(canonicalPair, spec.Name),
			"optional":                      spec.Optional,
			"required_for_selected_default": false,
			"available":                     toolOK[spec.Name],
			"path":                          toolStatus["path"],
			"version":                       toolStatus["version"],
			"default_model":                 spec.DefaultModel,
			"prompt_flavor":                 spec.PromptFlavor,
			"supports_build":                spec.SupportsBuild,
		}
		caps := provider.ScopeCapabilities{Backend: spec.Name, Available: false, Supports: map[string]bool{}, ProbeError: "executable not found"}
		if toolOK[spec.Name] {
			caps = f.Capabilities().DetectScopeCapabilities(ctx, spec.Name)
		}
		capabilityValues[spec.Name] = caps
		capMap := map[string]any{
			"available": caps.Available,
			"backend":   caps.Backend,
			"supports":  caps.Supports,
		}
		if caps.ProbeError != "" {
			capMap["probe_error"] = caps.ProbeError
		}
		scopeCaps[spec.Name] = capMap
		entry["scope_capabilities"] = capMap
		providerEntries[spec.Name] = entry
		readyForDefault[spec.Name] = toolOK[spec.Name] && caps.Available
	}
	resolution := provider.ResolveDefaultPair(readyForDefault)
	report["canonical_default_available"] = resolution.CanonicalDefaultAvailable
	report["runnable_default_pair_available"] = resolution.RunnableDefaultPair
	report["fallback_candidates"] = resolution.FallbackCandidates
	report["fallback_requires_user_choice"] = resolution.FallbackRequiresUserChoice
	if len(resolution.SelectedDefaultPair) > 0 {
		report["selected_default_pair"] = resolution.SelectedDefaultPair
		for _, backend := range resolution.SelectedDefaultPair {
			if entry, ok := providerEntries[backend].(map[string]any); ok {
				entry["required_for_selected_default"] = true
			}
		}
	}
	if !readyForDefault["claude"] {
		failed = true
		report["warnings"] = appendStringAny(report["warnings"], "claude is required because generated judges default to claude/opus")
	}
	if !resolution.RunnableDefaultPair {
		failed = true
		report["warnings"] = appendStringAny(report["warnings"], "no runnable two-provider default pair is available")
	}
	if !resolution.CanonicalDefaultAvailable {
		report["warnings"] = appendStringAny(report["warnings"], "canonical default provider pair claude + codex is degraded")
	}
	if resolution.FallbackRequiresUserChoice {
		report["warnings"] = appendStringAny(report["warnings"], "multiple fallback provider pairs are available; natural-language drafting must ask which peer to use")
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
		for _, tool := range toolNames {
			toolStatus := tools[tool].(map[string]any)
			if !toolStatus["ok"].(bool) {
				streams.Printf("- %s: missing\n", tool)
			} else {
				streams.Printf("- %s: %s (%s)\n", tool, toolStatus["path"], toolStatus["version"])
			}
		}
		streams.Printf("- defaults:\n")
		for _, key := range []string{"claude_sonnet", "claude_opus", "claude_haiku", "codex", "codex_gpt5", "gemini", "copilot"} {
			streams.Printf("  %s: %s\n", key, defaults[key])
		}
		streams.Printf("- canonical default pair: %s\n", joinComma(canonicalPair))
		if selected, ok := report["selected_default_pair"].([]string); ok && len(selected) > 0 {
			streams.Printf("- selected default pair: %s\n", joinComma(selected))
		} else if resolution.FallbackRequiresUserChoice {
			streams.Printf("- selected default pair: requires user choice\n")
		} else {
			streams.Printf("- selected default pair: unavailable\n")
		}
		streams.Printf("- scope policy: best_effort by default; provider status records enforcement and advisory fallback.\n")
		streams.Printf("- scope capabilities:\n")
		for _, backend := range provider.BackendNames() {
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
	if opts.Build {
		ok, err := runBuildPreflight(ctx, f, opts, report, capabilityValues, toolOK, resolution)
		if err != nil {
			return err
		}
		if !ok {
			failed = true
		}
	} else if !opts.SkipAuthProbe && !failed {
		if err := runAuthProbes(ctx, f, opts, report, installedBackends(toolOK)); err != nil {
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
	if failed {
		return &apperror.SilentError{Err: errDoctorFailed{}}
	}
	return nil
}

type errDoctorFailed struct{}

func (errDoctorFailed) Error() string { return "doctor failed" }

func runAuthProbes(ctx context.Context, f commands.Factory, opts *DoctorOptions, report map[string]any, backends []string) error {
	authProbes := report["auth_probes"].(map[string]any)
	providerEntries, _ := report["providers"].(map[string]any)
	prompt := `Auth probe. Reply exactly with <final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>`
	cwd, _ := os.Getwd()
	participants := make([]workorder.Participant, 0, len(backends))
	for _, backend := range backends {
		participants = append(participants, participantForBackend(backend, "low"))
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
			Env:     runnerenv.SafeEnv(os.Environ()),
			OnTick:  commands.MakeTickPrinter(f, participant.Backend+":auth", opts.Quiet),
		}))
		if ctx.Err() != nil {
			return ctx.Err()
		}
		probeStatus := authProbeStatus(result)
		authProbes[participant.Backend] = probeStatus
		if entry, ok := providerEntries[participant.Backend].(map[string]any); ok {
			entry["auth_probe"] = probeStatus
		}
		if !opts.JSON {
			f.Streams().Printf("- %s auth probe: %s\n", participant.Backend, result["status"])
		}
		if result["status"] != runner.StatusOK {
			warning := participant.Backend + " auth probe failed with " + jsonutil.StringValue(result["status"])
			if reason := jsonutil.StringValue(probeStatus["reason"]); reason != "" {
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

const buildProbeFile = "bakeoff-doctor-build-probe.txt"

func runBuildPreflight(ctx context.Context, f commands.Factory, opts *DoctorOptions, report map[string]any, capabilityValues map[string]provider.ScopeCapabilities, toolOK map[string]bool, resolution provider.DefaultPairResolution) (bool, error) {
	preflight := map[string]any{
		"enabled":                     true,
		"ok":                          false,
		"temporary_workspace_removed": false,
		"providers":                   map[string]any{},
	}
	report["build_preflight"] = preflight

	if !opts.JSON {
		f.Streams().Printf("- build preflight:\n")
	}

	parent, err := os.MkdirTemp("", "bakeoff-doctor-build-")
	if err != nil {
		preflight["reason"] = err.Error()
		if !opts.JSON {
			f.Streams().Printf("  setup: failed (%s)\n", err)
		}
		return false, nil
	}
	defer func() {
		if err := os.RemoveAll(parent); err != nil {
			preflight["cleanup_error"] = err.Error()
			report["warnings"] = appendStringAny(report["warnings"], "build preflight temporary workspace cleanup failed: "+err.Error())
			return
		}
		preflight["temporary_workspace_removed"] = true
	}()

	overallOK := true
	required := requiredBuildBackends(resolution)
	providers := preflight["providers"].(map[string]any)
	for _, backend := range provider.BackendNames() {
		if !toolOK[backend] {
			continue
		}
		entry, err := runBuildProviderPreflight(ctx, f, opts, backend, parent, capabilityValues[backend])
		if err != nil {
			return false, err
		}
		providers[backend] = entry
		ok, _ := entry["ok"].(bool)
		if !ok && required[backend] {
			overallOK = false
		}
		if !opts.JSON {
			status := "failed"
			if ok {
				status = "ok"
			}
			reason := jsonutil.StringValue(entry["reason"])
			if reason != "" {
				f.Streams().Printf("  %s: %s (%s)\n", backend, status, reason)
			} else {
				f.Streams().Printf("  %s: %s\n", backend, status)
			}
		}
	}
	preflight["ok"] = overallOK
	return overallOK, nil
}

func runBuildProviderPreflight(ctx context.Context, f commands.Factory, opts *DoctorOptions, backend string, parent string, caps provider.ScopeCapabilities) (map[string]any, error) {
	entry := map[string]any{
		"ok":              false,
		"backend":         backend,
		"probe_file":      buildProbeFile,
		"workspace_write": false,
	}
	if !caps.Available {
		reason := "scope capability probe unavailable"
		if caps.ProbeError != "" {
			reason += ": " + caps.ProbeError
		}
		entry["reason"] = reason
		return entry, nil
	}
	if backend == "codex" && !caps.Supports["sandbox_workspace_write"] {
		entry["reason"] = "codex exec --help did not advertise --sandbox workspace-write"
		entry["supports_sandbox_workspace_write"] = false
		return entry, nil
	}
	if backend == "codex" {
		entry["supports_sandbox_workspace_write"] = true
	}
	if backend == "gemini" {
		switch {
		case caps.Supports["approval_auto_edit"]:
			entry["edit_mode"] = "approval-mode auto_edit"
		case caps.Supports["approval_yolo"]:
			entry["edit_mode"] = "approval-mode yolo"
		case caps.Supports["yolo_flag"]:
			entry["edit_mode"] = "yolo"
		default:
			entry["reason"] = "gemini --help did not advertise non-interactive edit mode; see Gemini CLI headless/configuration docs for --approval-mode auto_edit or --yolo"
			return entry, nil
		}
	}
	if backend == "copilot" && !caps.Supports["no_ask_user"] {
		entry["reason"] = "copilot --help did not advertise --no-ask-user"
		return entry, nil
	}

	workspace := filepath.Join(parent, backend)
	if err := os.Mkdir(workspace, 0o700); err != nil {
		entry["reason"] = err.Error()
		return entry, nil
	}
	participant := buildProbeParticipant(backend)
	extraArgs := []string{}
	if backend == "codex" {
		extraArgs = append(extraArgs, "--sandbox", "workspace-write")
	} else if backend == "gemini" {
		switch {
		case caps.Supports["approval_auto_edit"]:
			extraArgs = append(extraArgs, "--approval-mode", "auto_edit")
		case caps.Supports["approval_yolo"]:
			extraArgs = append(extraArgs, "--approval-mode", "yolo")
		case caps.Supports["yolo_flag"]:
			extraArgs = append(extraArgs, "--yolo")
		}
	} else if backend == "copilot" && caps.Supports["allow_tool"] {
		extraArgs = append(extraArgs, "--allow-tool", "edit")
	}
	argv, err := provider.BuildParticipantArgv(participant, workspace, extraArgs, "", false)
	if err != nil {
		return nil, &apperror.RuntimeError{Err: err}
	}
	token := "bakeoff-build-write-ok-" + backend
	result := artifact.ResultMap(runner.RunProvider(ctx, runner.Options{
		Argv:    argv,
		Prompt:  buildProbePrompt(token),
		Budgets: runner.Budgets{WallClockSeconds: 60, MaxOutputBytes: 10000, HeartbeatSeconds: 10},
		CWD:     workspace,
		Env:     runnerenv.SafeEnv(os.Environ()),
		OnTick:  commands.MakeTickPrinter(f, backend+":build", opts.Quiet || opts.JSON),
	}))
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	entry["runner"] = authProbeStatus(result)
	entry["runner_status"] = result["status"]
	if result["status"] != runner.StatusOK {
		reason := "provider live edit probe failed with " + jsonutil.StringValue(result["status"])
		if detail := jsonutil.StringValue(entry["runner"].(map[string]any)["reason"]); detail != "" {
			reason += ": " + detail
		}
		entry["reason"] = reason
		return entry, nil
	}

	data, err := os.ReadFile(filepath.Join(workspace, buildProbeFile))
	if err != nil {
		entry["reason"] = "provider did not create probe file: " + err.Error()
		return entry, nil
	}
	if strings.TrimSpace(string(data)) != token {
		entry["reason"] = "probe file content did not match expected token"
		return entry, nil
	}
	entry["ok"] = true
	entry["workspace_write"] = true
	entry["reason"] = "edited temporary workspace"
	return entry, nil
}

func buildProbeParticipant(backend string) workorder.Participant {
	return participantForBackend(backend, "low")
}

func buildProbePrompt(token string) string {
	return `BAKEOFF_DOCTOR_BUILD_EDIT_PROBE_V1

You are running a Bakeoff build readiness smoke test in a temporary directory.
Create or overwrite ` + buildProbeFile + ` in the current working directory with this single line:
` + token + `

Do not edit any other file. After writing the file, emit exactly one JSON object wrapped in <final_json>...</final_json>:
<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
`
}

func authProbeStatus(result map[string]any) map[string]any {
	status := artifact.StatusWithoutPayload(result)
	if result["status"] == runner.StatusOK {
		return status
	}
	diagnosticText := jsonutil.StringValue(result["stderr"])
	if diagnosticText == "" {
		diagnosticText = jsonutil.StringValue(result["stdout"])
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
	switch backend {
	case "claude":
		return []string{"allowed_tools", "disallowed_tools", "tools", "permission_mode", "output_last_message"}
	case "codex":
		return []string{"sandbox", "sandbox_workspace_write", "disable_feature", "profile", "config", "output_last_message"}
	case "gemini":
		return []string{"model", "approval_mode", "approval_auto_edit", "approval_yolo", "yolo_flag"}
	case "copilot":
		return []string{"model", "no_ask_user", "allow_tool", "deny_tool"}
	default:
		return nil
	}
}

func installedBackends(toolOK map[string]bool) []string {
	backends := []string{}
	for _, backend := range provider.BackendNames() {
		if toolOK[backend] {
			backends = append(backends, backend)
		}
	}
	return backends
}

func participantForBackend(backend string, effort string) workorder.Participant {
	return workorder.Participant{
		ID:      backend,
		Backend: backend,
		Model:   provider.DefaultModel(backend),
		Effort:  effort,
		Scope:   "codebase",
	}
}

func requiredBuildBackends(resolution provider.DefaultPairResolution) map[string]bool {
	required := map[string]bool{}
	if len(resolution.SelectedDefaultPair) > 0 {
		for _, backend := range resolution.SelectedDefaultPair {
			required[backend] = true
		}
		return required
	}
	for _, pair := range resolution.FallbackCandidates {
		for _, backend := range pair {
			required[backend] = true
		}
	}
	return required
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
