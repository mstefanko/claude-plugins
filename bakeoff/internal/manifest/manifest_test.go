package manifest_test

import (
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/verify"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestWriteRunManifestAndVerifyFingerprints(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "both_failed", "judge_ran": false, "provider_statuses": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "type": "gather", "resolved_models": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# report\n"); err != nil {
		t.Fatal(err)
	}
	if _, err := manifest.WriteRunManifest(runDir); err != nil {
		t.Fatal(err)
	}
	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode != 0 || result.Fingerprints.CheckedCount != 4 {
		t.Fatalf("verify result = %#v", result)
	}

	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# changed\n"); err != nil {
		t.Fatal(err)
	}
	result = verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode == 0 || result.Fingerprints.Status != "failed" {
		t.Fatalf("expected fingerprint failure, got %#v", result)
	}
}

func TestWriteRunManifestFingerprintsProviderAndJudgeEvidence(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeText(t, filepath.Join(runDir, "providers", "claude", "prompt.txt"), "provider prompt\n")
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "status.json"), map[string]any{"status": "ok", "final_json_source": "last_message"})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "final.json"), map[string]any{"ok": true})
	writeJSON(t, filepath.Join(runDir, "providers", "codex", "failure.json"), map[string]any{"status": "exit_error", "failure_kind": "api_transient"})
	writeText(t, filepath.Join(runDir, "providers", "claude", "last-message.txt"), "<final_json>{}\n")
	writeText(t, filepath.Join(runDir, "providers", "claude", "stdout.txt"), "provider stdout\n")
	writeText(t, filepath.Join(runDir, "providers", "claude", "stderr.txt"), "provider stderr\n")
	writeText(t, filepath.Join(runDir, "judge", "prompt.txt"), "judge prompt\n")
	writeJSON(t, filepath.Join(runDir, "judge", "status.json"), map[string]any{"status": "ok"})
	writeJSON(t, filepath.Join(runDir, "judge", "result.json"), map[string]any{"winner": "claude"})
	writeText(t, filepath.Join(runDir, "judge", "last-message.txt"), "<final_json>{}\n")
	writeText(t, filepath.Join(runDir, "judge", "stdout.txt"), "judge stdout\n")
	writeText(t, filepath.Join(runDir, "judge", "stderr.txt"), "judge stderr\n")
	writeJSON(t, filepath.Join(runDir, "judge", "synthesis-result.json"), map[string]any{"winner": "claude"})
	writeText(t, filepath.Join(runDir, "judge", "synthesis-last-message.txt"), "<final_json>{}\n")
	writeText(t, filepath.Join(runDir, "judge", "synthesis-stdout.txt"), "synthesis stdout\n")
	writeText(t, filepath.Join(runDir, "judge", "synthesis-stderr.txt"), "synthesis stderr\n")

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	fingerprints := value["artifact_fingerprints"].(map[string]any)
	for _, relative := range []string{
		"providers/claude/prompt.txt",
		"providers/claude/status.json",
		"providers/claude/final.json",
		"providers/codex/failure.json",
		"providers/claude/last-message.txt",
		"providers/claude/stdout.txt",
		"providers/claude/stderr.txt",
		"judge/prompt.txt",
		"judge/status.json",
		"judge/result.json",
		"judge/last-message.txt",
		"judge/stdout.txt",
		"judge/stderr.txt",
		"judge/synthesis-result.json",
		"judge/synthesis-last-message.txt",
		"judge/synthesis-stdout.txt",
		"judge/synthesis-stderr.txt",
	} {
		if _, ok := fingerprints[relative]; !ok {
			t.Fatalf("missing fingerprint for %s in %#v", relative, fingerprints)
		}
	}

	writeText(t, filepath.Join(runDir, "providers", "claude", "prompt.txt"), "changed provider prompt\n")
	writeJSON(t, filepath.Join(runDir, "providers", "codex", "failure.json"), map[string]any{"status": "timeout", "failure_kind": "timeout"})
	writeJSON(t, filepath.Join(runDir, "judge", "result.json"), map[string]any{"winner": "codex"})
	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode == 0 || result.Fingerprints.Status != "failed" {
		t.Fatalf("expected provider/judge fingerprint failure, got %#v", result)
	}
	paths := []string{}
	for _, mismatch := range result.Fingerprints.Mismatches {
		paths = append(paths, mismatch["path"])
	}
	got := strings.Join(paths, ",")
	if !strings.Contains(got, "providers/claude/prompt.txt") || !strings.Contains(got, "providers/codex/failure.json") || !strings.Contains(got, "judge/result.json") {
		t.Fatalf("missing expected mismatches: %#v", result.Fingerprints.Mismatches)
	}
}

func TestWriteRunManifestProviderSummaryKeepsRawAndAddsCompactStatus(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	status := map[string]any{
		"status":                "schema_error",
		"exit_code":             1,
		"output_bytes":          2048,
		"stdout_bytes":          1024,
		"stderr_bytes":          512,
		"stdout_truncated":      true,
		"stderr_truncated":      true,
		"stdout_observed_bytes": 4096,
		"stderr_observed_bytes": 8192,
		"failure_kind":          "schema_error",
		"scope_enforcement":     map[string]any{"requested_scope": "codebase", "effective_scope": "codebase"},
		"stderr_path":           "providers/claude/stderr.txt",
	}
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":     "provider_union_only",
		"judge_ran":         true,
		"judge_attempted":   true,
		"judge_completed":   false,
		"provider_statuses": map[string]any{"claude": status},
	})
	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	providers := value["providers"].(map[string]any)
	claude := providers["claude"].(map[string]any)
	if claude["status"] != "schema_error" || claude["compact_status"] != "failed" {
		t.Fatalf("provider summary status = %#v", claude)
	}
	status["status"] = "salvaged"
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":     "single_provider_only",
		"judge_ran":         false,
		"judge_attempted":   true,
		"judge_completed":   false,
		"provider_statuses": map[string]any{"claude": status},
	})
	value, err = manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	claude = value["providers"].(map[string]any)["claude"].(map[string]any)
	if claude["status"] != "salvaged" || claude["compact_status"] != "warn" {
		t.Fatalf("salvaged provider summary status = %#v", claude)
	}
	for _, key := range []string{"exit_code", "output_bytes", "stderr_truncated", "stdout_truncated", "stdout_observed_bytes", "stderr_observed_bytes", "failure_kind", "scope_enforcement", "stderr_path"} {
		if _, ok := claude[key]; !ok {
			t.Fatalf("missing passthrough %s in %#v", key, claude)
		}
	}
	if value["judge_attempted"] != true || value["judge_completed"] != false {
		t.Fatalf("judge fields = %#v", value)
	}
}

func TestWriteRunManifestHoistsExperimentFields(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{
		"run_id":          "r1",
		"type":            "gather",
		"resolved_models": map[string]any{},
		"experiment": map[string]any{
			"id":               "review-auth",
			"task_id":          "auth-review",
			"condition_id":     "pairwise.security",
			"run_kind":         "pairwise",
			"repetition_index": 2,
			"slot_id":          "security",
			"slot_attempt":     1,
		},
	})

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]any{
		"experiment_id":    "review-auth",
		"task_id":          "auth-review",
		"condition_id":     "pairwise.security",
		"run_kind":         "pairwise",
		"repetition_index": 2,
		"slot_id":          "security",
		"slot_attempt":     1,
	} {
		if value[key] != want {
			t.Fatalf("%s = %#v, want %#v in %#v", key, value[key], want, value)
		}
	}
}

func TestWriteRunManifestHoistsNullableExperimentSlotFields(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{
		"run_id":          "r1",
		"type":            "gather",
		"resolved_models": map[string]any{},
		"experiment": map[string]any{
			"id":               "review-auth",
			"task_id":          "auth-review",
			"condition_id":     "pairwise.security",
			"run_kind":         "pairwise",
			"repetition_index": 1,
		},
	})

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	if value["experiment_id"] != "review-auth" || value["slot_id"] != nil || value["slot_attempt"] != nil {
		t.Fatalf("experiment fields = %#v", value)
	}
}

func TestWriteRunManifestAddsDerivedLocalTelemetry(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"facet":          map[string]any{"id": "code-review", "kind": "generic", "focus": "bugs", "include": []string{"correctness"}},
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":   "structured_union",
		"judge_ran":       true,
		"judge_attempted": true,
		"judge_completed": true,
		"prompt_trim":     map[string]any{"dropped": []any{map[string]any{"prompt": "worker:claude"}, map[string]any{"prompt": "judge:pass1"}}},
		"provider_statuses": map[string]any{
			"claude": map[string]any{"status": "ok", "stdout_truncated": true},
			"codex":  map[string]any{"status": "ok", "stderr_truncated": true},
		},
	})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{
		"run_id": "r1",
		"type":   "gather",
		"facet":  map[string]any{"id": "code-review"},
		"resolved_models": map[string]any{
			"providers": map[string]any{
				"codex":  map[string]any{"backend": "codex", "model": "gpt"},
				"claude": map[string]any{"backend": "claude", "model": "sonnet"},
			},
			"judge": map[string]any{"backend": "claude", "model": "opus"},
		},
	})

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	telemetry := value["telemetry"].(map[string]any)
	if telemetry["schema_version"] != manifest.TelemetrySchemaVersion {
		t.Fatalf("telemetry schema = %#v", telemetry)
	}
	route := telemetry["route"].(map[string]any)
	if route["type"] != "gather" || route["facet_id"] != "code-review" || route["escalation_mode"] != nil || route["source_type"] != nil {
		t.Fatalf("route telemetry = %#v", route)
	}
	providers := telemetry["providers"].(map[string]any)
	if providers["count"] != 2 || providers["family_diversity"] != "mixed" {
		t.Fatalf("provider telemetry = %#v", providers)
	}
	if !reflect.DeepEqual(providers["backends"], []string{"claude", "codex"}) {
		t.Fatalf("provider backends = %#v", providers["backends"])
	}
	if !reflect.DeepEqual(providers["families"], []string{provider.ProviderFamilyAnthropic, provider.ProviderFamilyOpenAI}) {
		t.Fatalf("provider families = %#v", providers["families"])
	}
	judge := telemetry["judge"].(map[string]any)
	if judge["backend"] != "claude" || judge["family"] != provider.ProviderFamilyAnthropic || judge["family_relation"] != provider.JudgeFamilyRelationSameAsSome || judge["ran"] != true || judge["completed"] != true {
		t.Fatalf("judge telemetry = %#v", judge)
	}
	artifacts := telemetry["artifacts"].(map[string]any)
	if artifacts["prompt_trim_count"] != 2 || artifacts["output_truncation_count"] != 2 {
		t.Fatalf("artifact telemetry = %#v", artifacts)
	}
	telemetryJSON, err := json.Marshal(telemetry)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(telemetryJSON), "worker:claude") || strings.Contains(string(telemetryJSON), "judge:pass1") {
		t.Fatalf("telemetry leaked prompt trim source text: %s", telemetryJSON)
	}
	triageTelemetry := telemetry["triage"].(map[string]any)
	if triageTelemetry["state"] != "no" {
		t.Fatalf("triage telemetry = %#v", triageTelemetry)
	}
	for _, key := range []string{"item_count", "highest_severity"} {
		if _, ok := triageTelemetry[key]; !ok {
			t.Fatalf("triage telemetry missing nullable key %q: %#v", key, triageTelemetry)
		}
	}
}

func TestWriteRunManifestTelemetryJudgeFamilyRelations(t *testing.T) {
	tests := []struct {
		name        string
		judge       string
		providers   []string
		relation    any
		judgeFamily any
		families    []string
		diversity   string
		backends    []string
		count       int
	}{
		{name: "same all", judge: "claude", providers: []string{"claude"}, relation: provider.JudgeFamilyRelationSameAsAll, judgeFamily: provider.ProviderFamilyAnthropic, families: []string{provider.ProviderFamilyAnthropic}, diversity: "single", backends: []string{"claude"}, count: 1},
		{name: "same some", judge: "claude", providers: []string{"claude", "codex"}, relation: provider.JudgeFamilyRelationSameAsSome, judgeFamily: provider.ProviderFamilyAnthropic, families: []string{provider.ProviderFamilyAnthropic, provider.ProviderFamilyOpenAI}, diversity: "mixed", backends: []string{"claude", "codex"}, count: 2},
		{name: "different all", judge: "claude", providers: []string{"codex"}, relation: provider.JudgeFamilyRelationDifferentFromAll, judgeFamily: provider.ProviderFamilyAnthropic, families: []string{provider.ProviderFamilyOpenAI}, diversity: "single", backends: []string{"codex"}, count: 1},
		{name: "unknown provider", judge: "claude", providers: []string{"mystery"}, relation: provider.JudgeFamilyRelationUnknown, judgeFamily: provider.ProviderFamilyAnthropic, families: []string{}, diversity: "unknown", backends: []string{"mystery"}, count: 1},
		{name: "unknown judge", judge: "mystery", providers: []string{"claude"}, relation: provider.JudgeFamilyRelationUnknown, judgeFamily: provider.ProviderFamilyUnknown, families: []string{provider.ProviderFamilyAnthropic}, diversity: "single", backends: []string{"claude"}, count: 1},
		{name: "no judge configured", judge: "", providers: []string{"claude"}, relation: nil, judgeFamily: nil, families: []string{provider.ProviderFamilyAnthropic}, diversity: "single", backends: []string{"claude"}, count: 1},
		{name: "duplicate provider backend", judge: "claude", providers: []string{"claude", "claude"}, relation: provider.JudgeFamilyRelationSameAsAll, judgeFamily: provider.ProviderFamilyAnthropic, families: []string{provider.ProviderFamilyAnthropic}, diversity: "single", backends: []string{"claude", "claude"}, count: 2},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := filepath.Join(t.TempDir(), "runs", "r1")
			writeTelemetryBackendRun(t, runDir, tt.judge, tt.providers)

			value, err := manifest.WriteRunManifest(runDir)
			if err != nil {
				t.Fatal(err)
			}
			telemetry := value["telemetry"].(map[string]any)
			judge := telemetry["judge"].(map[string]any)
			if judge["family"] != tt.judgeFamily || judge["family_relation"] != tt.relation {
				t.Fatalf("judge telemetry = %#v", judge)
			}
			providers := telemetry["providers"].(map[string]any)
			if providers["count"] != tt.count || providers["family_diversity"] != tt.diversity || !reflect.DeepEqual(providers["families"], tt.families) || !reflect.DeepEqual(providers["backends"], tt.backends) {
				t.Fatalf("provider telemetry = %#v", providers)
			}
		})
	}
}

func TestWriteRunManifestTelemetryResolvedProviderBackendsKeepWorkOrderOrder(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "left", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "right", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":     "structured_union",
		"judge_ran":         true,
		"judge_completed":   true,
		"provider_statuses": map[string]any{"left": map[string]any{"status": "ok"}, "right": map[string]any{"status": "ok"}},
	})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{
		"run_id": "r1",
		"type":   "gather",
		"resolved_models": map[string]any{
			"providers": map[string]any{
				"right": map[string]any{"backend": "codex", "model": "gpt"},
				"left":  map[string]any{"backend": "gemini", "model": "pro"},
			},
			"judge": map[string]any{"backend": "claude", "model": "opus"},
		},
	})

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	telemetry := value["telemetry"].(map[string]any)
	providers := telemetry["providers"].(map[string]any)
	if !reflect.DeepEqual(providers["backends"], []string{"gemini", "codex"}) {
		t.Fatalf("provider backends = %#v", providers["backends"])
	}
	if !reflect.DeepEqual(providers["families"], []string{provider.ProviderFamilyGoogleGemini, provider.ProviderFamilyOpenAI}) {
		t.Fatalf("provider families = %#v", providers["families"])
	}
	judge := telemetry["judge"].(map[string]any)
	if judge["family_relation"] != provider.JudgeFamilyRelationDifferentFromAll {
		t.Fatalf("judge telemetry = %#v", judge)
	}
}

func TestWriteRunManifestTelemetryJudgeDecisionMetadata(t *testing.T) {
	tests := []struct {
		name             string
		decision         map[string]any
		meta             map[string]any
		wantBasis        any
		wantWinner       any
		wantWinnerFamily any
		wantSwap         bool
		wantOrderMaps    bool
		wantJudgePasses  bool
	}{
		{
			name: "gate winner",
			decision: map[string]any{
				"decision_kind":     "pick_winner",
				"selection_basis":   "gate",
				"canonical_winner":  "claude",
				"judge_ran":         false,
				"provider_statuses": map[string]any{"claude": map[string]any{"status": "ok"}, "codex": map[string]any{"status": "ok"}},
			},
			wantBasis:        "gate",
			wantWinner:       "claude",
			wantWinnerFamily: provider.ProviderFamilyAnthropic,
		},
		{
			name: "metric winner uses resolved backend",
			decision: map[string]any{
				"decision_kind":     "pick_winner",
				"selection_basis":   "metric",
				"canonical_winner":  "codex",
				"judge_ran":         false,
				"provider_statuses": map[string]any{"claude": map[string]any{"status": "ok"}, "codex": map[string]any{"status": "ok"}},
			},
			meta: map[string]any{
				"run_id": "build1",
				"type":   "build",
				"resolved_models": map[string]any{
					"providers": map[string]any{
						"claude": map[string]any{"backend": "claude", "model": "sonnet"},
						"codex":  map[string]any{"backend": "gemini", "model": "pro"},
					},
					"judge": map[string]any{"backend": "claude", "model": "opus"},
				},
			},
			wantBasis:        "metric",
			wantWinner:       "gemini",
			wantWinnerFamily: provider.ProviderFamilyGoogleGemini,
		},
		{
			name: "judge winner without swap",
			decision: map[string]any{
				"decision_kind":    "pick_winner",
				"selection_basis":  "judge",
				"canonical_winner": "claude",
				"judge_ran":        true,
				"judge_completed":  true,
				"order_maps": map[string]any{
					"pass1": map[string]any{"A": "claude", "B": "codex"},
					"pass2": map[string]any{"A": "claude", "B": "codex"},
				},
				"judge_passes": map[string]any{
					"pass1": map[string]any{"canonical_winner": "claude"},
					"pass2": map[string]any{"canonical_winner": "claude"},
				},
				"provider_statuses": map[string]any{"claude": map[string]any{"status": "ok"}, "codex": map[string]any{"status": "ok"}},
			},
			wantBasis:        "judge",
			wantWinner:       "claude",
			wantWinnerFamily: provider.ProviderFamilyAnthropic,
			wantOrderMaps:    true,
			wantJudgePasses:  true,
		},
		{
			name: "judge winner with swap",
			decision: map[string]any{
				"decision_kind":    "pick_winner",
				"selection_basis":  "judge",
				"canonical_winner": "claude",
				"judge_ran":        true,
				"judge_completed":  true,
				"order_maps": map[string]any{
					"pass1": map[string]any{"A": "claude", "B": "codex"},
					"pass2": map[string]any{"A": "codex", "B": "claude"},
				},
				"judge_passes": map[string]any{
					"pass1": map[string]any{"canonical_winner": "claude"},
					"pass2": map[string]any{"canonical_winner": "claude"},
				},
				"provider_statuses": map[string]any{"claude": map[string]any{"status": "ok"}, "codex": map[string]any{"status": "ok"}},
			},
			wantBasis:        "judge",
			wantWinner:       "claude",
			wantWinnerFamily: provider.ProviderFamilyAnthropic,
			wantSwap:         true,
			wantOrderMaps:    true,
			wantJudgePasses:  true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := filepath.Join(t.TempDir(), "runs", "build1")
			writeMinimalBuildRun(t, runDir, true)
			writeJSON(t, filepath.Join(runDir, "decision.json"), tt.decision)
			if tt.meta != nil {
				writeJSON(t, filepath.Join(runDir, "meta.json"), tt.meta)
			}

			value, err := manifest.WriteRunManifest(runDir)
			if err != nil {
				t.Fatal(err)
			}
			judge := value["telemetry"].(map[string]any)["judge"].(map[string]any)
			if judge["selection_basis"] != tt.wantBasis || judge["winner_backend"] != tt.wantWinner || judge["winner_family"] != tt.wantWinnerFamily || judge["position_swap_used"] != tt.wantSwap {
				t.Fatalf("judge telemetry = %#v", judge)
			}
			if (judge["order_maps"] != nil) != tt.wantOrderMaps {
				t.Fatalf("order_maps = %#v, want present %t", judge["order_maps"], tt.wantOrderMaps)
			}
			if (judge["judge_passes"] != nil) != tt.wantJudgePasses {
				t.Fatalf("judge_passes = %#v, want present %t", judge["judge_passes"], tt.wantJudgePasses)
			}
		})
	}
}

func TestWriteRunManifestMarksZeroSelectedTriage(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	hashes, err := triage.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	filter := map[string]any{"included": 0, "skipped_non_actionable": 2, "skipped_out_of_facet": 1}
	writeJSON(t, filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "ok", "source_finding_filter": filter})
	writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{"schema_version": 1, "status": "complete", "summary": "none", "items": []any{}, "input_hashes": hashes, "source_finding_filter": filter})
	writeJSON(t, filepath.Join(runDir, "triage", "source_finding_filter.json"), map[string]any{"summary": filter})
	writeJSON(t, filepath.Join(runDir, "triage", "citation_checks.json"), map[string]any{"checks": []any{}})
	writeJSON(t, filepath.Join(runDir, "triage", "finding_index.json"), []any{})
	writeText(t, filepath.Join(runDir, "triage", "prompt.txt"), "triage prompt\n")
	writeText(t, filepath.Join(runDir, "triage", "stdout.txt"), "triage stdout\n")
	writeText(t, filepath.Join(runDir, "triage", "stderr.txt"), "triage stderr\n")
	writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	triageSummary := value["triage"].(map[string]any)
	if triageSummary["zero_selected"] != true {
		t.Fatalf("triage summary = %#v", triageSummary)
	}
	sourceFilter := triageSummary["source_finding_filter"].(map[string]int)
	if sourceFilter["included"] != 0 || sourceFilter["skipped_non_actionable"] != 2 || sourceFilter["skipped_out_of_facet"] != 1 {
		t.Fatalf("source finding filter = %#v", sourceFilter)
	}
	telemetry := value["telemetry"].(map[string]any)
	triageTelemetry := telemetry["triage"].(map[string]any)
	if triageTelemetry["state"] != "yes" || triageTelemetry["item_count"] != 0 || triageTelemetry["highest_severity"] != nil {
		t.Fatalf("triage telemetry = %#v", triageTelemetry)
	}
	if _, ok := triageTelemetry["highest_severity"]; !ok {
		t.Fatalf("triage telemetry missing highest_severity: %#v", triageTelemetry)
	}
	fingerprints := value["artifact_fingerprints"].(map[string]any)
	for _, relative := range []string{
		"triage/source_finding_filter.json",
		"triage/citation_checks.json",
		"triage/finding_index.json",
		"triage/prompt.txt",
		"triage/stdout.txt",
		"triage/stderr.txt",
	} {
		if _, ok := fingerprints[relative]; !ok {
			t.Fatalf("missing triage fingerprint for %s in %#v", relative, fingerprints)
		}
	}
}

func TestWriteRunManifestTelemetryTriageStates(t *testing.T) {
	tests := []struct {
		name                string
		setup               func(t *testing.T, runDir string)
		wantState           string
		wantItems           any
		wantHighestSeverity any
	}{
		{name: "no", wantState: "no", wantItems: nil},
		{name: "dry run", wantState: "dry_run", wantItems: nil, setup: func(t *testing.T, runDir string) {
			writeJSON(t, filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "dry_run"})
		}},
		{name: "yes", wantState: "yes", wantItems: 2, wantHighestSeverity: "medium", setup: func(t *testing.T, runDir string) {
			hashes, err := triage.ComputeInputHashes(runDir)
			if err != nil {
				t.Fatal(err)
			}
			writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
				"schema_version": 1,
				"status":         "complete",
				"input_hashes":   hashes,
				"items": []any{
					map[string]any{"classification": "real_issue", "severity": "medium"},
					map[string]any{"classification": "false_positive", "severity": "high"},
				},
			})
			writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")
		}},
		{name: "needs repro ignored", wantState: "yes", wantItems: 2, wantHighestSeverity: "medium", setup: func(t *testing.T, runDir string) {
			hashes, err := triage.ComputeInputHashes(runDir)
			if err != nil {
				t.Fatal(err)
			}
			writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
				"schema_version": 1,
				"status":         "complete",
				"input_hashes":   hashes,
				"items": []any{
					map[string]any{"classification": "needs_repro", "severity": "high"},
					map[string]any{"classification": "real_issue", "severity": "medium"},
				},
			})
			writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")
		}},
		{name: "false positives do not outrank real issues", wantState: "yes", wantItems: 3, wantHighestSeverity: "low", setup: func(t *testing.T, runDir string) {
			hashes, err := triage.ComputeInputHashes(runDir)
			if err != nil {
				t.Fatal(err)
			}
			writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
				"schema_version": 1,
				"status":         "complete",
				"input_hashes":   hashes,
				"items": []any{
					map[string]any{"classification": "false_positive", "severity": "high"},
					map[string]any{"classification": "already_fixed", "severity": "high"},
					map[string]any{"classification": "real_issue", "severity": "low"},
				},
			})
			writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")
		}},
		{name: "only non-actionable", wantState: "yes", wantItems: 1, setup: func(t *testing.T, runDir string) {
			hashes, err := triage.ComputeInputHashes(runDir)
			if err != nil {
				t.Fatal(err)
			}
			writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
				"schema_version": 1,
				"status":         "complete",
				"input_hashes":   hashes,
				"items":          []any{map[string]any{"classification": "false_positive", "severity": "high"}},
			})
			writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")
		}},
		{name: "stale", wantState: "stale", wantItems: 1, wantHighestSeverity: "low", setup: func(t *testing.T, runDir string) {
			writeJSON(t, filepath.Join(runDir, "triage", "final.json"), map[string]any{
				"schema_version": 1,
				"status":         "complete",
				"input_hashes":   map[string]any{"decision_sha256": "stale", "report_sha256": "stale"},
				"items":          []any{map[string]any{"classification": "real_issue", "severity": "low"}},
			})
			writeText(t, filepath.Join(runDir, "triage", "triage.md"), "# triage\n")
		}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := filepath.Join(t.TempDir(), "runs", "r1")
			writeMinimalRun(t, runDir)
			if tt.setup != nil {
				tt.setup(t, runDir)
			}

			value, err := manifest.WriteRunManifest(runDir)
			if err != nil {
				t.Fatal(err)
			}
			telemetry := value["telemetry"].(map[string]any)
			triageTelemetry := telemetry["triage"].(map[string]any)
			if triageTelemetry["state"] != tt.wantState || triageTelemetry["item_count"] != tt.wantItems {
				t.Fatalf("triage telemetry = %#v", triageTelemetry)
			}
			for _, key := range []string{"item_count", "highest_severity"} {
				if _, ok := triageTelemetry[key]; !ok {
					t.Fatalf("triage telemetry missing nullable key %q: %#v", key, triageTelemetry)
				}
			}
			if tt.wantHighestSeverity != nil {
				triageSummary := value["triage"].(map[string]any)
				if triageSummary["highest_severity"] != tt.wantHighestSeverity {
					t.Fatalf("triage summary = %#v", triageSummary)
				}
				if triageTelemetry["highest_severity"] != tt.wantHighestSeverity {
					t.Fatalf("triage telemetry = %#v", triageTelemetry)
				}
				if triageTelemetry["highest_severity"] != triageSummary["highest_severity"] {
					t.Fatalf("triage telemetry highest_severity = %#v, triage summary highest_severity = %#v", triageTelemetry["highest_severity"], triageSummary["highest_severity"])
				}
			} else if triageTelemetry["highest_severity"] != nil {
				t.Fatalf("triage telemetry highest_severity = %#v, want nil", triageTelemetry["highest_severity"])
			}
		})
	}
}

func TestWriteRunManifestRejectsPartialReviewContextArtifacts(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeMinimalRun(t, runDir)
	writeText(t, filepath.Join(runDir, "review-context.md"), "review\n")
	if _, err := manifest.WriteRunManifest(runDir); err == nil || !strings.Contains(err.Error(), "review context artifacts must be all-or-none") {
		t.Fatalf("expected partial review context error, got %v", err)
	}
}

func TestBuildManifestRequiresContextAndFingerprintsBuildArtifacts(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "build1")
	writeMinimalBuildRun(t, runDir, true)
	writeJSON(t, filepath.Join(runDir, "baseline", "verify", "unit", "status.json"), map[string]any{"id": "unit", "status": "passed"})
	writeText(t, filepath.Join(runDir, "baseline", "verify", "unit", "stdout.txt"), "")
	writeText(t, filepath.Join(runDir, "baseline", "verify", "unit", "stderr.txt"), "")
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "workspace.json"), map[string]any{"provider_id": "claude"})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "capture.json"), map[string]any{"patch_bytes": 12})
	writeText(t, filepath.Join(runDir, "providers", "claude", "build", "changed-files.txt"), "A\tmain.go\n")
	writeText(t, filepath.Join(runDir, "providers", "claude", "build", "diff.patch"), "diff --git a/main.go b/main.go\n")
	writeText(t, filepath.Join(runDir, "providers", "claude", "build", "diffstat.txt"), " main.go | 1 +\n")
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "test-files.json"), []any{})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "benchmark-files.json"), []any{})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "result.json"), map[string]any{"scope": "provider", "provider_id": "claude", "gates_passed": true})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "unit", "status.json"), map[string]any{"id": "unit", "status": "passed"})
	writeText(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "unit", "stdout.txt"), "")
	writeText(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "unit", "stderr.txt"), "")

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	artifacts := value["artifacts"].(map[string]any)
	if artifacts["build_context"] != "build-context.json" {
		t.Fatalf("artifacts = %#v", artifacts)
	}
	fingerprints := value["artifact_fingerprints"].(map[string]any)
	for _, relative := range []string{
		"build-context.json",
		"baseline/verify/unit/status.json",
		"providers/claude/build/diff.patch",
		"providers/claude/build/verify/result.json",
		"providers/claude/build/verify/unit/status.json",
	} {
		if _, ok := fingerprints[relative]; !ok {
			t.Fatalf("missing build fingerprint for %s in %#v", relative, fingerprints)
		}
	}
	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode != 0 || !contains(result.RequiredArtifacts.Checked, "build-context.json") {
		t.Fatalf("verify result = %#v", result)
	}
	row := manifest.RowForLS(runDir)
	if row["type"] != "build" || row["decision_kind"] != "pick_winner" || !strings.HasSuffix(row["report_path"].(string), filepath.Join("build1", "report.md")) {
		t.Fatalf("ls row = %#v", row)
	}
}

func TestBuildManifestTelemetryOutputTruncationCount(t *testing.T) {
	tests := []struct {
		name  string
		setup func(t *testing.T, runDir string)
		want  int
	}{
		{
			name: "no diagnostics falls back to provider statuses",
			want: 2,
		},
		{
			name: "diagnostics records are authoritative when present",
			setup: func(t *testing.T, runDir string) {
				writeJSON(t, filepath.Join(runDir, "diagnostics.json"), map[string]any{
					"schema_version": 1,
					"output_truncation": []any{
						map[string]any{"scope": "provider", "provider_id": "claude", "stream": "stdout"},
						map[string]any{"scope": "verify", "provider_id": "claude", "verifier_id": "unit", "stream": "stderr"},
						map[string]any{"scope": "baseline", "verifier_id": "unit", "stream": "stdout"},
					},
				})
			},
			want: 3,
		},
		{
			name: "diagnostics without truncation key falls back to provider statuses",
			setup: func(t *testing.T, runDir string) {
				writeJSON(t, filepath.Join(runDir, "diagnostics.json"), map[string]any{"schema_version": 1})
			},
			want: 2,
		},
		{
			name: "work order type controls build diagnostics even when meta type drifts",
			setup: func(t *testing.T, runDir string) {
				writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "build1", "type": "gather", "resolved_models": map[string]any{}})
				writeJSON(t, filepath.Join(runDir, "diagnostics.json"), map[string]any{
					"schema_version": 1,
					"output_truncation": []any{
						map[string]any{"scope": "provider", "provider_id": "claude", "stream": "stdout"},
						map[string]any{"scope": "verify", "provider_id": "claude", "verifier_id": "unit", "stream": "stderr"},
						map[string]any{"scope": "baseline", "verifier_id": "unit", "stream": "stdout"},
					},
				})
			},
			want: 3,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runDir := filepath.Join(t.TempDir(), "runs", "build1")
			writeMinimalBuildRun(t, runDir, true)
			writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
				"decision_kind":    "pick_winner",
				"selection_basis":  "gate",
				"canonical_winner": "claude",
				"judge_ran":        false,
				"provider_statuses": map[string]any{
					"claude": map[string]any{"status": "ok", "stdout_truncated": true, "stderr_truncated": true},
				},
			})
			if tt.setup != nil {
				tt.setup(t, runDir)
			}

			value, err := manifest.WriteRunManifest(runDir)
			if err != nil {
				t.Fatal(err)
			}
			telemetry := value["telemetry"].(map[string]any)
			artifacts := telemetry["artifacts"].(map[string]any)
			if artifacts["output_truncation_count"] != tt.want {
				t.Fatalf("artifact telemetry = %#v, want %d", artifacts, tt.want)
			}
			route := telemetry["route"].(map[string]any)
			if route["type"] != "build" {
				t.Fatalf("route telemetry = %#v", route)
			}
		})
	}
}

func TestWriteRunManifestTelemetryEscalationRoute(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "child")
	writeMinimalRun(t, runDir)
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{
		"run_id":          "child",
		"type":            "escalation",
		"source_type":     "gather",
		"escalation_mode": "witness",
		"resolved_models": map[string]any{},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":     "escalation_advisory_supported",
		"judge_ran":         false,
		"source_mode":       "gather",
		"escalation_mode":   "witness",
		"provider_statuses": map[string]any{},
	})
	writeJSON(t, filepath.Join(runDir, "source-run.json"), map[string]any{"source_run_id": "source"})
	writeJSON(t, filepath.Join(runDir, "escalation", "mode.json"), map[string]any{"mode": "witness"})

	value, err := manifest.WriteRunManifest(runDir)
	if err != nil {
		t.Fatal(err)
	}
	telemetry := value["telemetry"].(map[string]any)
	route := telemetry["route"].(map[string]any)
	if route["type"] != "escalation" || route["source_type"] != "gather" || route["escalation_mode"] != "witness" {
		t.Fatalf("route telemetry = %#v", route)
	}
}

func TestRowForLSProjectsTriageAndRerunFields(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "retry")
	writeJSON(t, filepath.Join(runDir, "manifest.json"), map[string]any{
		"schema_version": manifest.SchemaVersion,
		"run_id":         "retry",
		"type":           "gather",
		"decision_kind":  "structured_union",
		"finished_at":    "2026-05-25T00:00:00Z",
		"source_run_id":  "source",
		"rerun_mode":     "judge_only",
		"artifacts":      map[string]any{"report": "report.md"},
		"triage": map[string]any{
			"state":            "yes",
			"item_count":       2,
			"highest_severity": "medium",
		},
	})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")

	row := manifest.RowForLS(runDir)
	if row["source_run_id"] != "source" || row["rerun_mode"] != "judge_only" || row["triage_state"] != "yes" {
		t.Fatalf("ls row = %#v", row)
	}
	triageRow := row["triage"].(map[string]any)
	if triageRow["state"] != "yes" || triageRow["item_count"] != 2 || triageRow["highest_severity"] != "medium" {
		t.Fatalf("triage row = %#v", triageRow)
	}
}

func TestRowForLSProjectsExperimentFields(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "r1")
	writeJSON(t, filepath.Join(runDir, "manifest.json"), map[string]any{
		"schema_version":   manifest.SchemaVersion,
		"run_id":           "r1",
		"type":             "gather",
		"decision_kind":    "structured_union",
		"finished_at":      "2026-05-25T00:00:00Z",
		"experiment_id":    "review-auth",
		"task_id":          "auth-review",
		"condition_id":     "pairwise.security",
		"run_kind":         "pairwise",
		"repetition_index": 1,
		"artifacts":        map[string]any{"report": "report.md"},
		"triage":           map[string]any{"state": "no"},
	})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")

	row := manifest.RowForLS(runDir)
	if row["experiment_id"] != "review-auth" || row["task_id"] != "auth-review" || row["condition_id"] != "pairwise.security" || row["run_kind"] != "pairwise" || row["repetition_index"] != 1 || row["slot_id"] != nil || row["slot_attempt"] != nil {
		t.Fatalf("ls row = %#v", row)
	}
}

func TestBuildManifestRequiresBuildContext(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "build1")
	writeMinimalBuildRun(t, runDir, false)
	if _, err := manifest.WriteRunManifest(runDir); err == nil || !strings.Contains(err.Error(), "build-context.json") {
		t.Fatalf("expected build-context requirement, got %v", err)
	}
}

func TestFingerprintArtifactPathsMatchesBuildEvidenceSet(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "build1")
	writeMinimalBuildRun(t, runDir, true)
	writeJSON(t, filepath.Join(runDir, "baseline", "verify", "unit", "metric.json"), map[string]any{"value": 1})
	writeJSON(t, filepath.Join(runDir, "baseline", "verify", "result.json"), map[string]any{"scope": "baseline", "gates_passed": true})
	writeText(t, filepath.Join(runDir, "judge", "prompt-pass1.txt"), "judge\n")
	writeJSON(t, filepath.Join(runDir, "judge", "result-pass1.json"), map[string]any{"winner": "claude"})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "scope.json"), map[string]any{"ignored": true})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "protected-paths.json"), map[string]any{"violations": []any{}})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "result.json"), map[string]any{"scope": "provider", "provider_id": "claude", "gates_passed": true})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "unit", "metric.json"), map[string]any{"value": 2})
	writeJSON(t, filepath.Join(runDir, "providers", "claude", "build", "verify", "unit", "result.json"), map[string]any{"id": "unit", "status": "passed"})

	paths := manifest.FingerprintArtifactPaths(runDir)
	for _, want := range []string{
		"baseline/verify/result.json",
		"baseline/verify/unit/metric.json",
		"judge/prompt-pass1.txt",
		"judge/result-pass1.json",
		"providers/claude/build/protected-paths.json",
		"providers/claude/build/scope.json",
		"providers/claude/build/verify/result.json",
		"providers/claude/build/verify/unit/metric.json",
		"providers/claude/build/verify/unit/result.json",
	} {
		if !contains(paths, want) {
			t.Fatalf("missing %s in %#v", want, paths)
		}
	}
}

func TestVerifyFailsOnMalformedRunTypeSource(t *testing.T) {
	runDir := filepath.Join(t.TempDir(), "runs", "bad-type")
	writeText(t, filepath.Join(runDir, "work-order.json"), "{not json\n")
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "both_failed", "judge_ran": false, "provider_statuses": map[string]any{}})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "bad-type", "resolved_models": map[string]any{}})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")
	writeJSON(t, filepath.Join(runDir, "manifest.json"), map[string]any{
		"schema_version":        manifest.SchemaVersion,
		"run_id":                "bad-type",
		"artifact_fingerprints": map[string]any{},
	})

	result := verify.Run(runDir, filepath.Dir(runDir))
	if result.ExitCode == 0 {
		t.Fatalf("expected malformed run type source to fail verify: %#v", result)
	}
	got := strings.Join(result.Problems, "\n")
	if !strings.Contains(got, "work-order.json run type source is invalid JSON") {
		t.Fatalf("missing malformed run type problem: %#v", result.Problems)
	}
}

func writeMinimalRun(t *testing.T, runDir string) {
	t.Helper()
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "web"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "both_failed", "judge_ran": false, "provider_statuses": map[string]any{}})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "type": "gather", "resolved_models": map[string]any{}})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")
}

func writeMinimalBuildRun(t *testing.T, runDir string, includeContext bool) {
	t.Helper()
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "build-sample",
		"type":           "build",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
		"build": map[string]any{
			"base_ref":        "HEAD",
			"patch_max_bytes": 100000,
			"verify": []map[string]any{
				{"id": "unit", "kind": "gate", "argv": []string{"true"}, "wall_clock_seconds": 3, "max_output_bytes": 1000},
			},
		},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "pick_winner", "selection_basis": "gate", "canonical_winner": "claude", "judge_ran": false, "provider_statuses": map[string]any{}})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "build1", "type": "build", "resolved_models": map[string]any{}})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")
	if includeContext {
		writeJSON(t, filepath.Join(runDir, "build-context.json"), map[string]any{"schema_version": 1, "run_id": "build1"})
	}
}

func writeTelemetryBackendRun(t *testing.T, runDir string, judge string, backends []string) {
	t.Helper()
	providers := make([]map[string]any, 0, len(backends))
	statuses := map[string]any{}
	for i, backend := range backends {
		id := backend
		if id == "" {
			id = "provider"
		}
		if _, ok := statuses[id]; ok {
			id = id + "-" + string(rune('a'+i))
		}
		providers = append(providers, map[string]any{"id": id, "backend": backend, "model": "m", "scope": "codebase"})
		statuses[id] = map[string]any{"status": "ok"}
	}
	writeJSON(t, filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "sample",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers":      providers,
		"judge":          map[string]any{"backend": judge, "model": "judge"},
		"budgets":        map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 1000},
	})
	writeJSON(t, filepath.Join(runDir, "decision.json"), map[string]any{
		"decision_kind":     "structured_union",
		"judge_ran":         true,
		"judge_completed":   true,
		"provider_statuses": statuses,
	})
	writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "r1", "type": "gather", "resolved_models": map[string]any{}})
	writeText(t, filepath.Join(runDir, "report.md"), "# report\n")
}

func contains(items []string, want string) bool {
	for _, item := range items {
		if item == want {
			return true
		}
	}
	return false
}

func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := workorder.WriteJSONAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}

func writeText(t *testing.T, path string, value string) {
	t.Helper()
	if err := workorder.WriteTextAtomic(path, value); err != nil {
		t.Fatal(err)
	}
}
