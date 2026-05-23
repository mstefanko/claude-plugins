package artifact

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestStatusWithoutPayloadOmitsLargeFields(t *testing.T) {
	status := StatusWithoutPayload(map[string]any{
		"status":            "ok",
		"stdout":            "large stdout",
		"stderr":            "large stderr",
		"final_json":        map[string]any{"claims": []any{}},
		"stdout_bytes":      12,
		"stderr_kind":       "transport_noise",
		"failure_kind":      "api_transient",
		"scope_enforcement": map[string]any{"policy": "best_effort"},
	})

	if status["status"] != "ok" || status["stdout_bytes"] != 12 {
		t.Fatalf("status = %#v", status)
	}
	if _, ok := status["stdout"]; ok {
		t.Fatalf("stdout leaked into status: %#v", status)
	}
	if _, ok := status["final_json"]; ok {
		t.Fatalf("final_json leaked into status: %#v", status)
	}
	if _, ok := status["scope_enforcement"]; !ok {
		t.Fatalf("scope_enforcement missing from status: %#v", status)
	}
	if status["stderr_kind"] != "transport_noise" {
		t.Fatalf("stderr_kind missing from status: %#v", status)
	}
	if status["failure_kind"] != "api_transient" {
		t.Fatalf("failure_kind missing from status: %#v", status)
	}
}

func TestProviderSucceeded(t *testing.T) {
	if !ProviderSucceeded(map[string]any{"status": "ok"}) {
		t.Fatal("ok should succeed")
	}
	if !ProviderSucceeded(map[string]any{"status": "ok_after_format_retry"}) {
		t.Fatal("ok_after_format_retry should succeed")
	}
	if ProviderSucceeded(map[string]any{"status": "schema_error"}) {
		t.Fatal("schema_error should fail")
	}
	if ProviderSucceeded(map[string]any{"status": runner.StatusSalvaged}) {
		t.Fatal("salvaged should fail")
	}
}

func TestResultMapClassifiesStderrKind(t *testing.T) {
	codex := ResultMap(runner.Result{
		Status:    runner.StatusOK,
		Stderr:    "Reading prompt from stdin...\nOpenAI Codex v0.125.0\nuser\n...\n<final_json>{}</final_json>",
		FinalJSON: map[string]any{"ok": true},
	})
	if codex["stderr_kind"] != "transport_noise" {
		t.Fatalf("codex stderr kind = %#v", codex["stderr_kind"])
	}
	changedPreamble := ResultMap(runner.Result{
		Status:    runner.StatusOK,
		Stderr:    "Future Codex banner\nprompt echo\n<final_json>{\"ok\":true}</final_json>\n2026-05-23T12:00:00Z WARN failed to record rollout items",
		FinalJSON: map[string]any{"ok": true},
	})
	if changedPreamble["stderr_kind"] != "transport_noise" {
		t.Fatalf("changed-preamble stderr kind = %#v", changedPreamble["stderr_kind"])
	}
	preambleOnly := ResultMap(runner.Result{
		Status: runner.StatusOK,
		Stderr: "Reading prompt from stdin...\nOpenAI Codex v0.125.0\n" +
			"user\ntranscript without final json",
	})
	if preambleOnly["stderr_kind"] != "diagnostic" {
		t.Fatalf("preamble-only stderr kind = %#v", preambleOnly["stderr_kind"])
	}
	trailingError := ResultMap(runner.Result{
		Status:    runner.StatusOK,
		Stderr:    "Reading prompt from stdin...\nOpenAI Codex v0.125.0\n<final_json>{\"ok\":true}</final_json>\nERROR trailing failure",
		FinalJSON: map[string]any{"ok": true},
	})
	if trailingError["stderr_kind"] != "diagnostic" {
		t.Fatalf("trailing-error stderr kind = %#v", trailingError["stderr_kind"])
	}
	failed := ResultMap(runner.Result{Status: runner.StatusExitError, Stderr: "boom"})
	if failed["stderr_kind"] != "errors" {
		t.Fatalf("failed stderr kind = %#v", failed["stderr_kind"])
	}
	empty := ResultMap(runner.Result{Status: runner.StatusOK})
	if empty["stderr_kind"] != "none" {
		t.Fatalf("empty stderr kind = %#v", empty["stderr_kind"])
	}
}

func TestResultMapClassifiesFailureKindOnlyForConfidentFailures(t *testing.T) {
	failed := ResultMap(runner.Result{Status: runner.StatusExitError, Stderr: "rate_limit_error: retry later"})
	if failed["failure_kind"] != "rate_or_quota_limited" {
		t.Fatalf("failed failure_kind = %#v", failed["failure_kind"])
	}
	guard := ResultMap(runner.Result{Status: runner.StatusExitError, Stderr: "prompt too large: 1000001 bytes exceeds 1000000 byte limit"})
	if guard["failure_kind"] != "prompt_too_large" {
		t.Fatalf("prompt guard failure_kind = %#v", guard["failure_kind"])
	}

	ambiguous := ResultMap(runner.Result{Status: runner.StatusExitError, Stderr: "fatal"})
	if _, ok := ambiguous["failure_kind"]; ok {
		t.Fatalf("ambiguous failure_kind should be absent: %#v", ambiguous)
	}

	wedged := ResultMap(runner.Result{Status: runner.StatusExitError, WallSeconds: 120, IO: runner.IOStats{QuietThresholdSeconds: 20}})
	if wedged["failure_kind"] != "wedged_no_output" {
		t.Fatalf("wedged failure_kind = %#v", wedged["failure_kind"])
	}

	success := ResultMap(runner.Result{Status: runner.StatusOK, Stderr: "rate_limit_error: ignored because provider succeeded"})
	if _, ok := success["failure_kind"]; ok {
		t.Fatalf("success failure_kind should be absent: %#v", success)
	}
}

func TestResultMapSubtypesTimeoutFailures(t *testing.T) {
	quiet := ResultMap(runner.Result{Status: runner.StatusTimeout})
	if quiet["failure_kind"] != "quiet_stdout" {
		t.Fatalf("quiet timeout failure_kind = %#v", quiet["failure_kind"])
	}

	lastStdoutAge := 1.0
	wall := ResultMap(runner.Result{
		Status:              runner.StatusTimeout,
		StdoutObservedBytes: 42,
		IO:                  runner.IOStats{StdoutObservedBytes: 42, LastStdoutAge: &lastStdoutAge, QuietThresholdSeconds: 10},
	})
	if wall["failure_kind"] != "wall_clock" {
		t.Fatalf("wall timeout failure_kind = %#v", wall["failure_kind"])
	}

	maxTokens := ResultMap(runner.Result{Status: runner.StatusTimeout, Stderr: `{"stop_reason":"max_tokens"}`})
	if maxTokens["failure_kind"] != "max_tokens" {
		t.Fatalf("max_tokens failure_kind = %#v", maxTokens["failure_kind"])
	}
}

func TestResultMapClassifiesSalvagedFromOriginalStatus(t *testing.T) {
	result := ResultMap(runner.Result{
		Status: runner.StatusSalvaged,
		Salvage: &runner.SalvageMetadata{
			Source:         "last-message.txt",
			OriginalStatus: runner.StatusTimeout,
		},
	})
	if result["failure_kind"] != "quiet_stdout" {
		t.Fatalf("salvaged failure_kind = %#v", result["failure_kind"])
	}
}

func TestPreserveJudgeErrorKindCopiesClassifiedFailure(t *testing.T) {
	failed := map[string]any{"status": runner.StatusExitError, "failure_kind": "api_transient"}
	PreserveJudgeErrorKind(failed)
	if failed["judge_error_kind"] != "api_transient" {
		t.Fatalf("judge_error_kind = %#v", failed["judge_error_kind"])
	}

	success := map[string]any{"status": runner.StatusOK, "failure_kind": "api_transient"}
	PreserveJudgeErrorKind(success)
	if _, ok := success["judge_error_kind"]; ok {
		t.Fatalf("success should not get judge_error_kind: %#v", success)
	}
}

func TestWriteProviderArtifactsWritesSalvageMetadata(t *testing.T) {
	dir := t.TempDir()
	result := ResultMap(runner.Result{
		Status:          runner.StatusSalvaged,
		FinalJSON:       map[string]any{"ok": true},
		FinalJSONSource: runner.FinalJSONSourceLastMessage,
		Salvage: &runner.SalvageMetadata{
			Source:             "last-message.txt",
			RecoveredJSONBytes: 34,
			RecoveredAt:        "2026-05-22T15:04:05Z",
			OriginalStatus:     runner.StatusTimeout,
		},
	})
	if err := WriteProviderArtifacts(dir, result); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "salvage.json"))
	if err != nil {
		t.Fatal(err)
	}
	var salvage map[string]any
	if err := json.Unmarshal(data, &salvage); err != nil {
		t.Fatal(err)
	}
	if salvage["source"] != "last-message.txt" || salvage["original_status"] != nil {
		t.Fatalf("salvage metadata = %#v", salvage)
	}
	if _, err := os.Stat(filepath.Join(dir, "final.json")); !os.IsNotExist(err) {
		t.Fatalf("salvaged provider should not write final.json: %v", err)
	}
}

func TestWriteProviderArtifactsFiltersCodexTransportStderr(t *testing.T) {
	dir := t.TempDir()
	result := ResultMap(runner.Result{
		Status: runner.StatusOK,
		Stderr: "Reading prompt from stdin...\nOpenAI Codex v0.125.0\n" +
			"user prompt echo\n<final_json>{\"ok\":true}</final_json>\n2026-05-23T12:00:00Z WARN failed to record rollout items\n",
		FinalJSON: map[string]any{"ok": true},
	})
	if err := WriteProviderArtifacts(dir, result); err != nil {
		t.Fatal(err)
	}
	stderr, err := os.ReadFile(filepath.Join(dir, "stderr.txt"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(stderr)
	if strings.Contains(text, "user prompt echo") || strings.Contains(text, "<final_json>") {
		t.Fatalf("transport echo was not filtered:\n%s", text)
	}
	for _, want := range []string{"Reading prompt from stdin", "OpenAI Codex", "WARN failed to record rollout items", "transport echo filtered"} {
		if !strings.Contains(text, want) {
			t.Fatalf("filtered stderr missing %q:\n%s", want, text)
		}
	}
	status := readArtifactJSON(t, filepath.Join(dir, "status.json"))
	if status["stderr_filtered"] != true {
		t.Fatalf("status missing stderr_filtered: %#v", status)
	}
}

func TestWriteProviderArtifactsDoesNotMarkUnchangedTransportStderr(t *testing.T) {
	dir := t.TempDir()
	result := map[string]any{
		"status":      runner.StatusOK,
		"stderr_kind": "transport_noise",
		"stderr":      "Reading prompt from stdin...\nOpenAI Codex v0.125.0\n2026-05-23T12:00:00Z WARN failed to record rollout items\n",
		"stdout":      "",
		"final_json":  map[string]any{"ok": true},
	}
	if err := WriteProviderArtifacts(dir, result); err != nil {
		t.Fatal(err)
	}
	stderr, err := os.ReadFile(filepath.Join(dir, "stderr.txt"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(stderr)
	if strings.Contains(text, "transport echo filtered") {
		t.Fatalf("unchanged stderr should not get filter marker:\n%s", text)
	}
	status := readArtifactJSON(t, filepath.Join(dir, "status.json"))
	if _, ok := status["stderr_filtered"]; ok {
		t.Fatalf("unchanged stderr should not be marked filtered: %#v", status)
	}
}

func TestWriteProviderArtifactsWritesFailureJSONForFailedProviders(t *testing.T) {
	dir := t.TempDir()
	result := ResultMap(runner.Result{
		Status:              runner.StatusExitError,
		ExitCode:            intPtr(42),
		Stdout:              strings.Repeat("o", 5000),
		Stderr:              "rate_limit_error: retry later",
		StdoutBytes:         100,
		StderrBytes:         29,
		StdoutObservedBytes: 5000,
		StderrObservedBytes: 29,
		StdoutTruncated:     true,
	})
	if err := WriteProviderArtifacts(dir, result, ProviderMetadata{
		ID:           "claude",
		Backend:      "claude",
		Model:        "sonnet",
		Effort:       "high",
		Scope:        "codebase",
		PromptFlavor: "claude",
	}); err != nil {
		t.Fatal(err)
	}
	failure := readArtifactJSON(t, filepath.Join(dir, "failure.json"))
	if failure["provider_id"] != "claude" || failure["backend"] != "claude" || failure["prompt_flavor"] != "claude" {
		t.Fatalf("failure metadata = %#v", failure)
	}
	if failure["status"] != runner.StatusExitError || failure["failure_kind"] != "rate_or_quota_limited" {
		t.Fatalf("failure classification = %#v", failure)
	}
	raw := failure["raw_artifacts"].(map[string]any)
	if raw["stdout"] != "stdout.txt" || raw["stderr"] != "stderr.txt" || raw["status"] != "status.json" {
		t.Fatalf("raw artifact pointers = %#v", raw)
	}
	if len(failure["stdout_tail"].(string)) != failureTailBytes {
		t.Fatalf("stdout tail length = %d", len(failure["stdout_tail"].(string)))
	}
	if _, err := os.Stat(filepath.Join(dir, "final.json")); !os.IsNotExist(err) {
		t.Fatalf("failed provider should not write final.json: %v", err)
	}

	successDir := t.TempDir()
	success := ResultMap(runner.Result{Status: runner.StatusOK, FinalJSON: map[string]any{"ok": true}})
	if err := WriteProviderArtifacts(successDir, success); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(successDir, "failure.json")); !os.IsNotExist(err) {
		t.Fatalf("successful provider should not write failure.json: %v", err)
	}
}

func readArtifactJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	if err := json.Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

func intPtr(value int) *int {
	return &value
}

func TestWriteMetaIncludesDecisionAndExitCode(t *testing.T) {
	runDir := t.TempDir()
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), map[string]any{"id": "sample"}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "tie"}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "report\n"); err != nil {
		t.Fatal(err)
	}
	wo := &workorder.WorkOrder{
		Type: "compare",
		Providers: []workorder.Participant{
			{ID: "claude", Backend: "claude", Model: "sonnet", Effort: "high", Scope: "codebase"},
			{ID: "gemini", Backend: "gemini", Model: "pro", Effort: "high", Scope: "codebase"},
		},
		Judge: workorder.Participant{Backend: "copilot", Model: "auto", Effort: "xhigh"},
	}
	lookupMissing := func(string) (string, error) { return "", os.ErrNotExist }
	err := WriteMeta(context.Background(), runDir, wo, "run-1", "2026-05-19T00:00:00Z", MetaOptions{
		WorkerResults:  map[string]map[string]any{"claude": {"scope_enforcement": map[string]any{"level": "advisory"}}},
		Decision:       map[string]any{"decision_kind": "tie", "canonical_winner": nil, "judge_ran": true},
		ExitCode:       3,
		LookupProvider: lookupMissing,
	})
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(runDir, "meta.json"))
	if err != nil {
		t.Fatal(err)
	}
	var meta map[string]any
	if err := json.Unmarshal(data, &meta); err != nil {
		t.Fatal(err)
	}
	if meta["decision_kind"] != "tie" || meta["judge_ran"] != true || meta["exit_code"] != float64(3) {
		t.Fatalf("meta missing terminal fields: %#v", meta)
	}
	versions := meta["provider_cli_versions"].(map[string]any)
	if _, ok := versions["gemini"]; !ok {
		t.Fatalf("meta missing selected provider CLI version: %#v", versions)
	}
	if _, ok := versions["copilot"]; !ok {
		t.Fatalf("meta missing selected judge CLI version: %#v", versions)
	}
	if _, ok := versions["codex"]; ok {
		t.Fatalf("meta should not record unused provider CLI version: %#v", versions)
	}
}
