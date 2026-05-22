package artifact

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
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
