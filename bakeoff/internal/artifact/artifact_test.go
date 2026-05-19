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
		},
		Judge: workorder.Participant{Backend: "claude", Model: "opus", Effort: "xhigh"},
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
}
