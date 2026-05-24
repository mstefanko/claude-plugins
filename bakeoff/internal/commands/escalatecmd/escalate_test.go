package escalatecmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	triagepkg "github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type escalateTestFactory struct {
	streams output.Streams
}

func (f escalateTestFactory) Streams() output.Streams {
	return f.streams
}

func (f escalateTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f escalateTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f escalateTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f escalateTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestDryRunDoesNotCreateRunDirectory(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "tie", "canonical_winner": nil})
	var out, errOut bytes.Buffer
	f := escalateTestFactory{streams: output.NewStreams(&out, &errOut)}

	err := Run(context.Background(), f, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		RunID:       "next",
		Mode:        ModeIndependent,
		Provider:    "gemini:pro",
		DryRun:      true,
	})
	if err != nil {
		t.Fatalf("Run returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	if _, err := os.Stat(filepath.Join(outDir, "next")); !os.IsNotExist(err) {
		t.Fatalf("dry-run created run directory, stat err=%v", err)
	}
	if !strings.Contains(out.String(), "estimated calls: 1 provider call, 1 judge passes") {
		t.Fatalf("dry-run missing call envelope:\n%s", out.String())
	}
}

func TestEscalateRejectsBuildSourceRun(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeBuildSourceRun(t, outDir, "build-source")
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}, &EscalateOptions{
		SourceRunID: "build-source",
		Out:         outDir,
		Mode:        ModeWitness,
		Provider:    "gemini",
		DryRun:      true,
	})
	if err == nil || !strings.Contains(err.Error(), "build source runs cannot be escalated") {
		t.Fatalf("expected build rejection, got %v", err)
	}
}

func TestEscalateRejectsDuplicateProviderID(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "gather", map[string]any{"decision_kind": "structured_union", "canonical_winner": nil})
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		Mode:        ModeWitness,
		Provider:    "claude",
		DryRun:      true,
	})
	if err == nil || !strings.Contains(err.Error(), `already has provider id "claude"`) {
		t.Fatalf("expected duplicate provider rejection, got %v", err)
	}
}

func TestDisputeWithoutPointsFailsBeforeMutation(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "pick_winner", "canonical_winner": "claude"})
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&bytes.Buffer{}, &bytes.Buffer{})}, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		RunID:       "dispute",
		Mode:        ModeDispute,
		Provider:    "gemini",
	})
	if err == nil || !strings.Contains(err.Error(), "no focused dispute points") {
		t.Fatalf("expected no-points validation error, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(outDir, "dispute")); !os.IsNotExist(err) {
		t.Fatalf("dispute validation created run directory, stat err=%v", err)
	}
}

func TestResolveAddedScopePreservesCodeReviewCommonScope(t *testing.T) {
	wo := scopeWorkOrder("mixed", "mixed", true)
	scope, err := resolveAddedScope(wo, ModeIndependent, "")
	if err != nil {
		t.Fatalf("resolveAddedScope returned error: %v", err)
	}
	if scope != "mixed" {
		t.Fatalf("scope = %q, want mixed", scope)
	}
}

func TestResolveAddedScopeRejectsExplicitScopeForAdvisoryModes(t *testing.T) {
	_, err := resolveAddedScope(scopeWorkOrder("codebase", "codebase", false), ModeWitness, "web")
	if err == nil || !strings.Contains(err.Error(), "--scope is only supported for --mode independent") {
		t.Fatalf("expected mode-specific scope error, got %v", err)
	}
}

func TestResolveAddedScopeFallsBackForArtifactCenteredModes(t *testing.T) {
	scope, err := resolveAddedScope(scopeWorkOrder("codebase", "web", false), ModeWitness, "")
	if err != nil {
		t.Fatalf("resolveAddedScope returned error: %v", err)
	}
	if scope != "codebase" {
		t.Fatalf("scope = %q, want codebase", scope)
	}
}

func TestResolveAddedScopeRequiresIndependentScopeForMixedSourceScopes(t *testing.T) {
	_, err := resolveAddedScope(scopeWorkOrder("codebase", "web", false), ModeIndependent, "")
	if err == nil || !strings.Contains(err.Error(), "source providers used different scopes") {
		t.Fatalf("expected mixed-scope independent error, got %v", err)
	}
}

func TestWitnessRunWritesEscalationArtifacts(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	writeFakeProvider(t, fakeBin, "gemini", `<final_json>{"status":"complete","headline":"Decision is supported.","assessment":"supported","source_decision_effect":"supports_source","confidence":"high","would_change_outcome":false,"material_errors":[],"missed_material":[],"triage_concerns":[],"out_of_scope":[],"recommended_action":"stop","recommended_next_checks":[],"rationale":["source decision is consistent"]}</final_json>`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "pick_winner", "canonical_winner": "claude"})

	var out, errOut bytes.Buffer
	f := escalateTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := Run(context.Background(), f, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		RunID:       "witness",
		Mode:        ModeWitness,
		Provider:    "gemini:pro",
		Quiet:       true,
		NoTriage:    true,
	})
	if err != nil {
		t.Fatalf("Run returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "witness")
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["mode"] != "escalation" || decisionDoc["decision_kind"] != "escalation_advisory_supported" {
		t.Fatalf("unexpected decision: %#v", decisionDoc)
	}
	if decisionDoc["canonical_winner"] != nil {
		t.Fatalf("witness should not set canonical winner: %#v", decisionDoc["canonical_winner"])
	}
	for _, relative := range []string{"source-run.json", "escalation/mode.json", "escalation/witness-prompt.txt", "providers/gemini/final.json", "manifest.json", "report.md"} {
		if _, err := os.Stat(filepath.Join(runDir, relative)); err != nil {
			t.Fatalf("missing %s: %v", relative, err)
		}
	}
	manifestDoc := readTestJSON(t, filepath.Join(runDir, "manifest.json"))
	if manifestDoc["type"] != "escalation" || manifestDoc["escalation_mode"] != "witness" {
		t.Fatalf("unexpected manifest: %#v", manifestDoc)
	}
	reportData, err := os.ReadFile(filepath.Join(runDir, "report.md"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(reportData), "advisory") {
		t.Fatalf("report should label witness as advisory:\n%s", string(reportData))
	}
	latest, err := os.Readlink(filepath.Join(outDir, "latest"))
	if err == nil && latest != "witness" {
		t.Fatalf("latest symlink = %q", latest)
	}
	if err != nil {
		data, readErr := os.ReadFile(filepath.Join(outDir, "latest"))
		if readErr != nil {
			t.Fatal(readErr)
		}
		if strings.TrimSpace(string(data)) != "witness" {
			t.Fatalf("latest file = %q", string(data))
		}
	}
}

func TestDisputeWritesPacketAndStaysAdvisory(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	writeFakeProvider(t, fakeBin, "gemini", `<final_json>{"status":"complete","headline":"The dispute remains unresolved.","resolved_points":[],"unresolved_points":["D-001 still conflicts"],"new_evidence":[],"outcome_effect":"insufficient_evidence","source_decision_effect":"questions_source","confidence":"medium","out_of_scope":[],"recommended_action":"independent_escalation","recommended_next_checks":[],"rationale":["packet evidence is not decisive"]}</final_json>`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{
		"decision_kind":    "tie",
		"canonical_winner": nil,
		"judge_passes": map[string]any{
			"pass1": map[string]any{"canonical_winner": "claude"},
			"pass2": map[string]any{"canonical_winner": "codex"},
		},
		"caveats": []any{"position swap did not produce a stable winner"},
	})
	var out, errOut bytes.Buffer
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&out, &errOut)}, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		RunID:       "dispute",
		Mode:        ModeDispute,
		Provider:    "gemini",
		Quiet:       true,
		NoTriage:    true,
	})
	if err != nil {
		t.Fatalf("Run returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "dispute")
	packet := readTestJSON(t, filepath.Join(runDir, "escalation", "dispute-packet.json"))
	points, _ := packet["points"].([]any)
	if len(points) == 0 {
		t.Fatalf("expected dispute packet points: %#v", packet)
	}
	decisionDoc := readTestJSON(t, filepath.Join(runDir, "decision.json"))
	if decisionDoc["canonical_winner"] != nil {
		t.Fatalf("dispute should not set canonical winner: %#v", decisionDoc)
	}
}

func TestIndependentCompareRunsSynthesisJudge(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	writeFakeProvider(t, fakeBin, "gemini", `<final_json>{"status":"complete","position":"Gemini position","claims":[{"id":"G-001","claim":"Gemini adds decisive evidence.","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>`)
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --version "*) printf '%s\n' 'claude fake'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools --output-last-message'; exit 0 ;;
esac
cat >/dev/null
cat <<'JSON'
<final_json>{"headline":"Gemini makes the source tie decisive.","source_decision_effect":"recommends_winner","recommended_winner":"gemini","confidence":"high","what_changed":["Gemini added decisive evidence."],"material_new_evidence":["fake:1"],"unresolved_questions":[],"out_of_scope":[],"recommended_action":"inspect","rationale":["Gemini is materially stronger."]}</final_json>
JSON
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "tie", "canonical_winner": nil})
	var out, errOut bytes.Buffer
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&out, &errOut)}, &EscalateOptions{
		SourceRunID: "source",
		Out:         outDir,
		RunID:       "independent",
		Mode:        ModeIndependent,
		Provider:    "gemini",
		Quiet:       true,
		NoTriage:    true,
	})
	if err != nil {
		t.Fatalf("Run returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	decisionDoc := readTestJSON(t, filepath.Join(outDir, "independent", "decision.json"))
	if decisionDoc["decision_kind"] != "escalation_recommends_winner" || decisionDoc["canonical_winner"] != "gemini" {
		t.Fatalf("unexpected synthesis decision: %#v", decisionDoc)
	}
	if decisionDoc["selection_basis"] != "escalation_synthesis" {
		t.Fatalf("missing synthesis selection basis: %#v", decisionDoc)
	}
	if _, err := os.Stat(filepath.Join(outDir, "independent", "judge", "synthesis-result.json")); err != nil {
		t.Fatalf("missing synthesis judge artifact: %v", err)
	}
}

func TestSourceRunIdentityIncludesTriageSnapshotWithAbsentSentinel(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "pick_winner", "canonical_winner": "claude"})
	src, err := loadSourceRun(filepath.Join(outDir, "source"), "source")
	if err != nil {
		t.Fatal(err)
	}
	identity := sourceRunIdentity(src)
	sourceTriage := identity["source_triage"].(map[string]any)
	if sourceTriage["state"] != "absent" {
		t.Fatalf("source_triage = %#v", sourceTriage)
	}
}

func TestSourceRunIdentityIncludesCompletedTriageSnapshot(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	writeSourceRun(t, outDir, "source", "compare", map[string]any{"decision_kind": "pick_winner", "canonical_winner": "claude"})
	runDir := filepath.Join(outDir, "source")
	hashes, err := triagepkg.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	filter := map[string]any{"included": 1, "skipped_non_actionable": 0, "skipped_out_of_facet": 0}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "ok", "source_finding_filter": filter}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "final.json"), map[string]any{
		"schema_version":        1,
		"status":                "complete",
		"summary":               "triaged",
		"input_hashes":          hashes,
		"source_finding_filter": filter,
		"items": []any{map[string]any{
			"classification":     "real_issue",
			"recommended_action": "fix_now",
		}},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# triage\n"); err != nil {
		t.Fatal(err)
	}
	src, err := loadSourceRun(runDir, "source")
	if err != nil {
		t.Fatal(err)
	}
	identity := sourceRunIdentity(src)
	sourceTriage := identity["source_triage"].(map[string]any)
	if sourceTriage["state"] != "yes" || sourceTriage["item_count"] != 1 {
		t.Fatalf("source_triage = %#v", sourceTriage)
	}
	for _, key := range []string{"status_path", "status_sha256", "final_path", "final_sha256", "triage_md_path", "triage_md_sha256", "artifacts", "source_finding_filter"} {
		if _, ok := sourceTriage[key]; !ok {
			t.Fatalf("source_triage missing %s: %#v", key, sourceTriage)
		}
	}
}

func TestBuildReviewClaimTargetsRanksAndCapsFreshCodeReviewTriage(t *testing.T) {
	items := []any{
		triageTargetTestItem("T-001", "F-001", "false_positive", "high", "high", "ignore"),
		triageTargetTestItem("T-002", "F-002", "real_issue", "high", "low", "defer"),
		triageTargetTestItem("T-003", "F-003", "needs_repro", "low", "medium", "reproduce"),
	}
	for i := 4; i <= 13; i++ {
		items = append(items, triageTargetTestItem(fmt.Sprintf("T-%03d", i), fmt.Sprintf("F-%03d", i), "evidence_gap", "low", "low", "ignore"))
	}
	items = append(items, triageTargetTestItem("T-014", "F-014", "real_issue", "medium", "high", "fix_now"))

	src := sourceRun{
		WorkOrder: &workorder.WorkOrder{
			Type: "gather",
			Raw:  map[string]any{"facet": map[string]any{"id": "code-review"}},
		},
		TriageArtifacts: map[string]any{
			"state": "yes",
			"final": map[string]any{"items": items},
		},
	}
	targets := buildReviewClaimTargets(src)
	if targets == nil {
		t.Fatal("expected review claim targets")
	}
	if targets["selected"] != 12 || targets["omitted_count"] != 2 {
		t.Fatalf("unexpected target counts: %#v", targets)
	}
	selected := targets["targets"].([]any)
	first := selected[0].(map[string]any)
	if first["source_finding_id"] != "F-014" || first["triage_id"] != "T-014" {
		t.Fatalf("fix_now target should rank first: %#v", first)
	}
	second := selected[1].(map[string]any)
	if second["source_finding_id"] != "F-003" {
		t.Fatalf("reproduce/needs_repro target should rank second: %#v", second)
	}
}

func TestBuildReviewClaimTargetsRequiresFreshCodeReviewTriage(t *testing.T) {
	src := sourceRun{
		WorkOrder: &workorder.WorkOrder{
			Type: "gather",
			Raw:  map[string]any{"facet": map[string]any{"id": "code-review"}},
		},
		TriageArtifacts: map[string]any{
			"state": "stale",
			"final": map[string]any{"items": []any{triageTargetTestItem("T-001", "F-001", "real_issue", "high", "high", "fix_now")}},
		},
	}
	if targets := buildReviewClaimTargets(src); targets != nil {
		t.Fatalf("stale triage should not build targets: %#v", targets)
	}
	src.TriageArtifacts["state"] = "yes"
	src.WorkOrder.Raw = map[string]any{"facet": map[string]any{"id": "docs"}}
	if targets := buildReviewClaimTargets(src); targets != nil {
		t.Fatalf("non-code-review facet should not build targets: %#v", targets)
	}
	src.WorkOrder.Raw = map[string]any{"facet": map[string]any{"id": "code-review"}}
	src.WorkOrder.Type = "analyze"
	if targets := buildReviewClaimTargets(src); targets != nil {
		t.Fatalf("non-gather source should not build targets: %#v", targets)
	}
}

func TestWitnessRunIncludesReviewRulesAndClaimTargets(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	writeFakeProvider(t, fakeBin, "gemini", `<final_json>{"status":"complete","headline":"Review report has concerns.","assessment":"questionable","source_decision_effect":"questions_source","confidence":"medium","would_change_outcome":false,"material_errors":[],"missed_material":[],"triage_concerns":[],"out_of_scope":[],"recommended_action":"inspect","recommended_next_checks":[],"rationale":["review witness ran"]}</final_json>`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	outDir := filepath.Join(root, "runs")
	writeCodeReviewSourceRun(t, outDir, "source-review", map[string]any{"decision_kind": "structured_union", "canonical_winner": nil})
	runDir := filepath.Join(outDir, "source-review")
	writeFreshTriage(t, runDir, []any{
		triageTargetTestItem("T-001", "F-001", "real_issue", "medium", "high", "fix_now"),
	})

	var out, errOut bytes.Buffer
	err := Run(context.Background(), escalateTestFactory{streams: output.NewStreams(&out, &errOut)}, &EscalateOptions{
		SourceRunID: "source-review",
		Out:         outDir,
		RunID:       "witness-review",
		Mode:        ModeWitness,
		Provider:    "gemini",
		Quiet:       true,
		NoTriage:    true,
	})
	if err != nil {
		t.Fatalf("Run returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	promptData, err := os.ReadFile(filepath.Join(outDir, "witness-review", "escalation", "witness-prompt.txt"))
	if err != nil {
		t.Fatal(err)
	}
	promptText := string(promptData)
	for _, want := range []string{
		"This is a code-review witness pass.",
		"<review_claim_targets>",
		`"source_finding_id": "F-001"`,
		`"recommended_action": "fix_now"`,
	} {
		if !strings.Contains(promptText, want) {
			t.Fatalf("witness prompt missing %q:\n%s", want, promptText)
		}
	}
}

func writeSourceRun(t *testing.T, outDir string, runID string, mode string, decisionDoc map[string]any) {
	t.Helper()
	writeSourceRunWithFacet(t, outDir, runID, mode, decisionDoc, nil)
}

func writeCodeReviewSourceRun(t *testing.T, outDir string, runID string, decisionDoc map[string]any) {
	t.Helper()
	writeSourceRunWithFacet(t, outDir, runID, "gather", decisionDoc, map[string]any{
		"id":      "code-review",
		"kind":    "generic",
		"focus":   "Find actionable defects introduced or exposed by the change.",
		"include": []any{"correctness bugs and edge cases"},
		"exclude": []any{"style-only preferences"},
	})
}

func writeSourceRunWithFacet(t *testing.T, outDir string, runID string, mode string, decisionDoc map[string]any, facet map[string]any) {
	t.Helper()
	runDir := filepath.Join(outDir, runID)
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	providers := []map[string]any{
		{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
		{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "codebase"},
	}
	workOrder := map[string]any{
		"schema_version": 1,
		"id":             "source-" + mode,
		"type":           mode,
		"goal":           "Test goal.",
		"background":     "Test background.",
		"providers":      providers,
		"judge":          map[string]any{"backend": "claude", "model": "judge-test", "effort": "high"},
		"budgets":        map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
		"scope_policy":   map[string]any{"enforcement": "best_effort"},
	}
	if facet != nil {
		workOrder["facet"] = facet
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), workOrder); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"claude", "codex"} {
		providerDir := filepath.Join(runDir, "providers", id)
		if err := os.MkdirAll(providerDir, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(providerDir, "status.json"), map[string]any{"status": "ok", "wall_seconds": 1, "stdout_bytes": 100, "stderr_bytes": 0}); err != nil {
			t.Fatal(err)
		}
		final := map[string]any{
			"status":                  "complete",
			"claims":                  []any{map[string]any{"id": strings.ToUpper(id[:1]) + "-001", "claim": id + " claim.", "evidence": []any{"fake:1"}, "confidence": "high"}},
			"conflicts":               []any{},
			"unknowns":                []any{},
			"recommended_next_checks": []any{},
		}
		if mode == "compare" {
			final["position"] = id + " position"
		}
		if err := workorder.WriteJSONAtomic(filepath.Join(providerDir, "final.json"), final); err != nil {
			t.Fatal(err)
		}
	}
	statuses := map[string]any{
		"claude": map[string]any{"status": "ok", "wall_seconds": 1},
		"codex":  map[string]any{"status": "ok", "wall_seconds": 1},
	}
	decisionDoc["mode"] = mode
	decisionDoc["provider_statuses"] = statuses
	if _, ok := decisionDoc["judge_ran"]; !ok {
		decisionDoc["judge_ran"] = mode != "gather"
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), decisionDoc); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# Report\n\nSource report.\n"); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "meta.json"), map[string]any{"run_id": runID, "type": mode, "started_at": "2026-05-22T00:00:00Z", "finished_at": "2026-05-22T00:00:01Z"}); err != nil {
		t.Fatal(err)
	}
}

func triageTargetTestItem(id string, sourceFindingID string, classification string, severity string, confidence string, action string) map[string]any {
	return map[string]any{
		"id":                  id,
		"source_finding_id":   sourceFindingID,
		"source_finding":      "Finding " + sourceFindingID,
		"classification":      classification,
		"severity":            severity,
		"confidence":          confidence,
		"supporting_evidence": []any{"internal/example.go:12"},
		"counterevidence":     []any{},
		"citation_check_ids":  []any{},
		"recommended_action":  action,
		"rationale":           "test rationale",
	}
}

func writeFreshTriage(t *testing.T, runDir string, items []any) {
	t.Helper()
	hashes, err := triagepkg.ComputeInputHashes(runDir)
	if err != nil {
		t.Fatal(err)
	}
	filter := map[string]any{"included": len(items), "skipped_non_actionable": 0, "skipped_out_of_facet": 0}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "status.json"), map[string]any{"status": "ok", "source_finding_filter": filter}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "triage", "final.json"), map[string]any{
		"schema_version":        1,
		"status":                "complete",
		"summary":               "triaged",
		"input_hashes":          hashes,
		"source_finding_filter": filter,
		"items":                 items,
		"unknowns":              []any{},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "triage", "triage.md"), "# triage\n"); err != nil {
		t.Fatal(err)
	}
}

func writeBuildSourceRun(t *testing.T, outDir string, runID string) {
	t.Helper()
	runDir := filepath.Join(outDir, runID)
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "work-order.json"), map[string]any{
		"schema_version": 1,
		"id":             "source-build",
		"type":           "build",
		"goal":           "Build something.",
		"background":     "Build background.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets": map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
		"build": map[string]any{
			"base_ref":        "HEAD",
			"patch_max_bytes": 1000,
			"verify": []map[string]any{
				{"id": "tests", "kind": "gate", "argv": []string{"true"}, "wall_clock_seconds": 1, "max_output_bytes": 1000},
			},
		},
	}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "decision.json"), map[string]any{"decision_kind": "pick_winner", "canonical_winner": "claude"}); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteTextAtomic(filepath.Join(runDir, "report.md"), "# Report\n"); err != nil {
		t.Fatal(err)
	}
	if err := workorder.WriteJSONAtomic(filepath.Join(runDir, "meta.json"), map[string]any{"run_id": runID, "type": "build"}); err != nil {
		t.Fatal(err)
	}
}

func writeFakeProvider(t *testing.T, dir string, name string, finalJSON string) {
	t.Helper()
	writeExecutable(t, filepath.Join(dir, name), `#!/bin/sh
case " $* " in
  *" --version "*) printf '%s\n' '`+name+` fake'; exit 0 ;;
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools --sandbox workspace-write --disable --output-last-message'; exit 0 ;;
esac
cat >/dev/null
cat <<'JSON'
`+finalJSON+`
JSON
`)
}

func writeExecutable(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o755); err != nil {
		t.Fatal(err)
	}
}

func readTestJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func scopeWorkOrder(left string, right string, codeReview bool) *workorder.WorkOrder {
	raw := map[string]any{}
	if codeReview {
		raw["facet"] = map[string]any{"id": "code-review"}
	}
	return &workorder.WorkOrder{
		Raw: raw,
		Providers: []workorder.Participant{
			{ID: "claude", Scope: left},
			{ID: "codex", Scope: right},
		},
	}
}
