package artifact

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runnerenv"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func ResultMap(result runner.Result) map[string]any {
	out := map[string]any{
		"status":                result.Status,
		"exit_code":             result.ExitCode,
		"wall_seconds":          result.WallSeconds,
		"output_bytes":          result.OutputBytes,
		"stdout_bytes":          result.StdoutBytes,
		"stderr_bytes":          result.StderrBytes,
		"stdout_observed_bytes": result.StdoutObservedBytes,
		"stderr_observed_bytes": result.StderrObservedBytes,
		"stdout_truncated":      result.StdoutTruncated,
		"stderr_truncated":      result.StderrTruncated,
		"io":                    result.IO,
		"stdout":                result.Stdout,
		"stderr":                result.Stderr,
		"final_json":            result.FinalJSON,
	}
	if result.FinalJSONSource != "" {
		out["final_json_source"] = result.FinalJSONSource
	}
	if result.OutputCap != nil {
		out["output_cap"] = result.OutputCap
	}
	if result.Salvage != nil {
		out["salvage"] = result.Salvage
	}
	if result.FormatRetry != nil {
		out["format_retry"] = result.FormatRetry
	}
	if result.RepairArtifacts != nil {
		out["repair_artifacts"] = result.RepairArtifacts
	}
	if !ProviderSucceeded(out) {
		if kind := resultFailureKind(result); kind != "" {
			out["failure_kind"] = kind
		}
	}
	out["stderr_kind"] = StderrKind(out)
	return out
}

// PreserveJudgeErrorKind keeps the legacy judge_error_kind field in sync with
// classified judge failures.
func PreserveJudgeErrorKind(result map[string]any) {
	if ProviderSucceeded(result) {
		return
	}
	if kind := jsonutil.StringValue(result["failure_kind"]); kind != "" {
		result["judge_error_kind"] = kind
	}
}

func StatusWithoutPayload(result map[string]any) map[string]any {
	status := map[string]any{}
	for _, key := range []string{
		"status",
		"exit_code",
		"wall_seconds",
		"output_bytes",
		"stdout_bytes",
		"stderr_bytes",
		"stdout_observed_bytes",
		"stderr_observed_bytes",
		"stdout_truncated",
		"stderr_truncated",
		"final_json_source",
		"stderr_kind",
		"failure_kind",
		"judge_error_kind",
		"salvage_artifact_error",
	} {
		if value, ok := result[key]; ok {
			status[key] = value
		}
	}
	for _, key := range []string{"io", "output_cap", "salvage", "format_retry", "scope_enforcement"} {
		if value, ok := result[key]; ok {
			status[key] = value
		}
	}
	return status
}

func StderrKind(result map[string]any) string {
	stderr := strings.TrimSpace(jsonutil.StringValue(result["stderr"]))
	if stderr == "" {
		return "none"
	}
	if !ProviderSucceeded(result) {
		return "errors"
	}
	if codexTransportNoise(stderr, result["final_json"]) {
		return "transport_noise"
	}
	return "diagnostic"
}

func codexTransportNoise(stderr string, finalJSON any) bool {
	if finalJSON == nil {
		return false
	}
	if !strings.HasPrefix(stderr, "Reading prompt from stdin...\nOpenAI Codex ") && !strings.HasPrefix(stderr, "OpenAI Codex ") {
		return false
	}
	return endsWithValidFinalJSON(stderr)
}

func endsWithValidFinalJSON(text string) bool {
	trimmed := strings.TrimSpace(text)
	if !strings.HasSuffix(trimmed, runner.FinalJSONClose) {
		return false
	}
	start := strings.LastIndex(trimmed, runner.FinalJSONOpen)
	if start < 0 {
		return false
	}
	payload := strings.TrimSpace(trimmed[start+len(runner.FinalJSONOpen) : len(trimmed)-len(runner.FinalJSONClose)])
	if payload == "" {
		return false
	}
	var obj map[string]any
	decoder := json.NewDecoder(strings.NewReader(payload))
	decoder.UseNumber()
	if err := decoder.Decode(&obj); err != nil {
		return false
	}
	var extra any
	return decoder.Decode(&extra) == io.EOF
}

func ProviderSucceeded(result map[string]any) bool {
	status, _ := result["status"].(string)
	return status == runner.StatusOK || status == runner.StatusOKAfterFormatRetry
}

func WriteProviderArtifacts(providerDir string, result map[string]any) error {
	if err := workorder.WriteTextAtomic(filepath.Join(providerDir, "stdout.txt"), jsonutil.StringValue(result["stdout"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(providerDir, "stderr.txt"), jsonutil.StringValue(result["stderr"])); err != nil {
		return err
	}
	if err := WriteFormatRetryArtifacts(providerDir, result, ""); err != nil {
		return err
	}
	if err := WriteSalvageArtifact(providerDir, result, ""); err != nil {
		result["salvage_artifact_error"] = err.Error()
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(providerDir, "status.json"), StatusWithoutPayload(result)); err != nil {
		return err
	}
	if ProviderSucceeded(result) {
		return workorder.WriteJSONAtomic(filepath.Join(providerDir, "final.json"), result["final_json"])
	}
	return nil
}

func WriteJudgeArtifacts(judgeDir string, label string, result map[string]any) error {
	var resultName, statusName, stdoutName, stderrName string
	if label == "gather" {
		resultName, statusName, stdoutName, stderrName = "result.json", "status.json", "stdout.txt", "stderr.txt"
	} else {
		resultName = "result-" + label + ".json"
		statusName = "status-" + label + ".json"
		stdoutName = "stdout-" + label + ".txt"
		stderrName = "stderr-" + label + ".txt"
	}
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, stdoutName), jsonutil.StringValue(result["stdout"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(judgeDir, stderrName), jsonutil.StringValue(result["stderr"])); err != nil {
		return err
	}
	suffix := ""
	if label != "gather" {
		suffix = label
	}
	if err := WriteFormatRetryArtifacts(judgeDir, result, suffix); err != nil {
		return err
	}
	if err := WriteSalvageArtifact(judgeDir, result, suffix); err != nil {
		result["salvage_artifact_error"] = err.Error()
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(judgeDir, statusName), StatusWithoutPayload(result)); err != nil {
		return err
	}
	if ProviderSucceeded(result) {
		return workorder.WriteJSONAtomic(filepath.Join(judgeDir, resultName), result["final_json"])
	}
	return nil
}

func WriteFormatRetryArtifacts(directory string, result map[string]any, suffix string) error {
	artifacts, ok := result["repair_artifacts"]
	if !ok || artifacts == nil {
		return nil
	}
	obj := map[string]any{}
	switch typed := artifacts.(type) {
	case *runner.RepairArtifacts:
		obj["prompt"] = typed.Prompt
		obj["stdout"] = typed.Stdout
		obj["stderr"] = typed.Stderr
		obj["status"] = typed.Status
	case runner.RepairArtifacts:
		obj["prompt"] = typed.Prompt
		obj["stdout"] = typed.Stdout
		obj["stderr"] = typed.Stderr
		obj["status"] = typed.Status
	case map[string]any:
		obj = typed
	default:
		return nil
	}
	suffixPart := ""
	if suffix != "" {
		suffixPart = "-" + suffix
	}
	if err := workorder.WriteTextAtomic(filepath.Join(directory, "repair-prompt"+suffixPart+".txt"), jsonutil.StringValue(obj["prompt"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(directory, "repair-stdout"+suffixPart+".txt"), jsonutil.StringValue(obj["stdout"])); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(filepath.Join(directory, "repair-stderr"+suffixPart+".txt"), jsonutil.StringValue(obj["stderr"])); err != nil {
		return err
	}
	return workorder.WriteJSONAtomic(filepath.Join(directory, "repair-status"+suffixPart+".json"), obj["status"])
}

func WriteSalvageArtifact(directory string, result map[string]any, suffix string) error {
	salvage, ok := result["salvage"]
	if !ok || salvage == nil {
		return nil
	}
	suffixPart := ""
	if suffix != "" {
		suffixPart = "-" + suffix
	}
	return workorder.WriteJSONAtomic(filepath.Join(directory, "salvage"+suffixPart+".json"), salvage)
}

func resultFailureKind(result runner.Result) string {
	if failureStopReasonHint(result) == "max_tokens" {
		return "max_tokens"
	}
	status := originalStatus(result)
	if status == runner.StatusTimeout {
		return timeoutFailureKind(result)
	}
	return runner.ClassifyFailure(status, result.Stdout, result.Stderr)
}

func originalStatus(result runner.Result) string {
	if result.Salvage != nil && result.Salvage.OriginalStatus != "" {
		return result.Salvage.OriginalStatus
	}
	return result.Status
}

func failureStopReasonHint(result runner.Result) string {
	if result.Salvage != nil && result.Salvage.StopReasonHint != "" {
		return result.Salvage.StopReasonHint
	}
	return runner.StopReasonHint(result.Stdout, result.Stderr)
}

func timeoutFailureKind(result runner.Result) string {
	if result.StdoutObservedBytes == 0 && result.IO.StdoutObservedBytes == 0 {
		return "quiet_stdout"
	}
	if result.IO.QuietTickCount > 0 {
		return "quiet_stdout"
	}
	if result.IO.LastStdoutAge != nil && result.IO.QuietThresholdSeconds > 0 && *result.IO.LastStdoutAge >= float64(result.IO.QuietThresholdSeconds) {
		return "quiet_stdout"
	}
	return "wall_clock"
}

type MetaOptions struct {
	WorkerResults  map[string]map[string]any
	Decision       map[string]any
	ExitCode       int
	LookupProvider provider.LookupFunc
}

func WriteMeta(ctx context.Context, runDir string, wo *workorder.WorkOrder, runID string, startedAt string, opts MetaOptions) error {
	return WriteMetaWithExtra(ctx, runDir, wo, runID, startedAt, opts, nil)
}

func WriteMetaWithExtra(ctx context.Context, runDir string, wo *workorder.WorkOrder, runID string, startedAt string, opts MetaOptions, extra map[string]any) error {
	inputHashes, err := triage.ComputeInputHashes(runDir)
	if err != nil {
		return err
	}
	providers := map[string]any{}
	for _, participant := range wo.Providers {
		entry := map[string]any{
			"backend": participant.Backend,
			"model":   participant.Model,
			"scope":   participant.Scope,
			"effort":  participant.Effort,
		}
		if result, ok := opts.WorkerResults[participant.ID]; ok {
			if scopeMetadata, ok := result["scope_enforcement"]; ok {
				entry["scope_enforcement"] = scopeMetadata
			}
		}
		providers[participant.ID] = entry
	}
	meta := map[string]any{
		"run_id":                runID,
		"type":                  wo.Type,
		"facet":                 facetMap(wo.Facet),
		"decision_kind":         nil,
		"canonical_winner":      nil,
		"judge_ran":             nil,
		"exit_code":             opts.ExitCode,
		"started_at":            startedAt,
		"finished_at":           UTCNow(),
		"cwd":                   mustGetwd(),
		"bakeoff_version":       buildinfo.Current().Version,
		"scope_policy":          map[string]any{"enforcement": wo.ScopePolicy.Enforcement},
		"provider_cli_versions": map[string]any{"claude": ToolVersion(ctx, "claude", opts.LookupProvider), "codex": ToolVersion(ctx, "codex", opts.LookupProvider), "git": ToolVersion(ctx, "git", opts.LookupProvider)},
		"input_hashes":          inputHashes,
		"resolved_models": map[string]any{
			"providers": providers,
			"judge": map[string]any{
				"backend": wo.Judge.Backend,
				"model":   wo.Judge.Model,
				"effort":  wo.Judge.Effort,
			},
		},
	}
	if opts.Decision != nil {
		meta["decision_kind"] = opts.Decision["decision_kind"]
		meta["canonical_winner"] = opts.Decision["canonical_winner"]
		meta["judge_ran"] = jsonutil.BoolValue(opts.Decision["judge_ran"])
	}
	for key, value := range extra {
		meta[key] = value
	}
	return workorder.WriteJSONAtomic(filepath.Join(runDir, "meta.json"), meta)
}

func ToolVersion(ctx context.Context, tool string, lookup provider.LookupFunc) string {
	argv, err := provider.VersionArgv(tool)
	if err != nil {
		return "unavailable"
	}
	if lookup == nil {
		lookup = exec.LookPath
	}
	exe, err := lookup(argv[0])
	if err != nil {
		return "unavailable"
	}
	probeCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(probeCtx, exe, argv[1:]...)
	cmd.Env = runnerenv.SafeEnv(os.Environ())
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil && probeCtx.Err() != nil {
		return "unavailable"
	}
	text := strings.TrimSpace(stdout.String())
	if text == "" {
		text = strings.TrimSpace(stderr.String())
	}
	if text == "" && cmd.ProcessState != nil {
		return "exit " + strconv.Itoa(cmd.ProcessState.ExitCode())
	}
	lines := strings.Split(text, "\n")
	return strings.TrimSpace(lines[0])
}

func UTCNow() string {
	return time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
}

func facetMap(facet *workorder.Facet) any {
	if facet == nil {
		return nil
	}
	out := map[string]any{
		"id":      facet.ID,
		"kind":    facet.Kind,
		"focus":   facet.Focus,
		"include": facet.Include,
	}
	if len(facet.Exclude) > 0 {
		out["exclude"] = facet.Exclude
	}
	if facet.Notes != "" {
		out["notes"] = facet.Notes
	}
	return out
}

func mustGetwd() string {
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	return cwd
}
