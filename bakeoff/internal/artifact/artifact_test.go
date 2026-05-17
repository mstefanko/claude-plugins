package artifact

import "testing"

func TestStatusWithoutPayloadOmitsLargeFields(t *testing.T) {
	status := StatusWithoutPayload(map[string]any{
		"status":            "ok",
		"stdout":            "large stdout",
		"stderr":            "large stderr",
		"final_json":        map[string]any{"claims": []any{}},
		"stdout_bytes":      12,
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
