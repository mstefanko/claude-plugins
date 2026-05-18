package buildverify

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestRunGateVerifierStatusesAndArtifacts(t *testing.T) {
	dir := t.TempDir()
	result := Run(context.Background(), Options{
		CWD: dir,
		Verifiers: []workorder.VerifierSpec{
			{ID: "pass", Kind: "gate", Argv: []string{"test", "-d", "."}, WallClockSeconds: 2, MaxOutputBytes: 1000},
			{ID: "fail", Kind: "gate", Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
			{ID: "missing", Kind: "gate", Argv: []string{"definitely-missing-bakeoff-command"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
		ArtifactDir: filepath.Join(dir, "artifacts"),
	})
	if result.GatesPassed {
		t.Fatal("expected gate aggregate to fail")
	}
	got := map[string]string{}
	for _, item := range result.Results {
		got[item.ID] = item.Status
		if item.StatusPath == "" {
			t.Fatalf("%s missing status path", item.ID)
		}
		if _, err := os.Stat(item.StatusPath); err != nil {
			t.Fatalf("%s status artifact missing: %v", item.ID, err)
		}
	}
	if got["pass"] != StatusPassed || got["fail"] != StatusFailed || got["missing"] != StatusMissingCommand {
		t.Fatalf("statuses = %#v", got)
	}
}

func TestRunVerifierTimeoutAndOutputCapStatuses(t *testing.T) {
	dir := t.TempDir()
	result := Run(context.Background(), Options{
		CWD:                   dir,
		OutputCapGraceSeconds: 0,
		MaxOutputOverrunBytes: 0,
		Verifiers: []workorder.VerifierSpec{
			{ID: "timeout", Kind: "gate", Argv: []string{"sh", "-c", "sleep 2"}, WallClockSeconds: 1, MaxOutputBytes: 1000},
			{ID: "cap", Kind: "gate", Argv: []string{"sh", "-c", "yes x | head -c 5000"}, WallClockSeconds: 2, MaxOutputBytes: 10},
		},
	})
	got := map[string]string{}
	for _, item := range result.Results {
		got[item.ID] = item.Status
	}
	if got["timeout"] != StatusTimeout || got["cap"] != StatusOutputCap {
		t.Fatalf("statuses = %#v", got)
	}
}

func TestArtifactWriteFailureDoesNotChangeVerifierStatus(t *testing.T) {
	dir := t.TempDir()
	artifactFile := filepath.Join(dir, "not-a-directory")
	if err := os.WriteFile(artifactFile, []byte("file\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	result := Run(context.Background(), Options{
		CWD:         dir,
		ArtifactDir: artifactFile,
		Verifiers: []workorder.VerifierSpec{
			{ID: "pass", Kind: "gate", Argv: []string{"test", "-d", "."}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	if !result.GatesPassed || len(result.Results) != 1 {
		t.Fatalf("result = %#v", result)
	}
	if result.Results[0].Status != StatusPassed || result.Results[0].ArtifactError == "" {
		t.Fatalf("verifier result = %#v", result.Results[0])
	}
}

func TestRunStopsBeforeNextVerifierWhenContextCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result := Run(ctx, Options{
		CWD: t.TempDir(),
		Verifiers: []workorder.VerifierSpec{
			{ID: "first", Kind: "gate", Argv: []string{"test", "-d", "."}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	if result.GatesPassed || len(result.Results) != 0 {
		t.Fatalf("result = %#v", result)
	}
}

func TestParseMetricUsesLastNonEmptyStdoutLine(t *testing.T) {
	spec := &workorder.MetricSpec{Name: "p95_ms", Direction: "lower", MinDeltaPercent: 10}
	metric := ParseMetric("warmup\n{\"p95_ms\": 12.5}\n", spec)
	if !metric.Conclusive || metric.Value == nil || *metric.Value != 12.5 {
		t.Fatalf("metric = %#v", metric)
	}
	metric = ParseMetric("warmup\r\n{\"p95_ms\": 7}\r\n", spec)
	if !metric.Conclusive || metric.Value == nil || *metric.Value != 7 {
		t.Fatalf("CRLF metric = %#v", metric)
	}
	metric = ParseMetric("{\"p95_ms\": 12.5}\nnot json\n", spec)
	if metric.Conclusive || metric.Error == "" {
		t.Fatalf("expected inconclusive metric, got %#v", metric)
	}
	metric = ParseMetric("{\"p95_ms\": 12.5} trailing\n", spec)
	if metric.Conclusive || metric.Error == "" {
		t.Fatalf("expected trailing data error, got %#v", metric)
	}
	metric = ParseMetric("{\"other\": 1}\n", spec)
	if metric.Conclusive || metric.Error == "" {
		t.Fatalf("expected missing metric error, got %#v", metric)
	}
	metric = ParseMetric("{\"p95_ms\": 1e999}\n", spec)
	if metric.Conclusive || metric.Error == "" {
		t.Fatalf("expected non-finite metric error, got %#v", metric)
	}
}

func TestCompareMetricHonorsThresholdAndDirection(t *testing.T) {
	spec := workorder.VerifierSpec{
		ID:   "bench",
		Kind: "metric",
		Metric: &workorder.MetricSpec{
			Name:              "p95_ms",
			Direction:         "lower",
			MinDeltaPercent:   10,
			NoiseFloorPercent: 5,
		},
	}
	leftValue := 80.0
	rightValue := 100.0
	comparison := CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &leftValue, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &rightValue, Conclusive: true}})
	if !comparison.Conclusive || comparison.Winner != "left" {
		t.Fatalf("comparison = %#v", comparison)
	}
	leftValue = 96
	comparison = CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &leftValue, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &rightValue, Conclusive: true}})
	if comparison.Conclusive || comparison.Winner != "" {
		t.Fatalf("expected threshold miss, got %#v", comparison)
	}
}

func TestRunMetricVerifierWritesMetricArtifact(t *testing.T) {
	dir := t.TempDir()
	result := Run(context.Background(), Options{
		CWD: dir,
		Verifiers: []workorder.VerifierSpec{
			{
				ID:               "metric",
				Kind:             "metric",
				Argv:             []string{"sh", "-c", "printf '{\"score\":2}\\n'"},
				WallClockSeconds: 2,
				MaxOutputBytes:   1000,
				Metric:           &workorder.MetricSpec{Name: "score", Direction: "lower", MinDeltaPercent: 10},
			},
		},
		ArtifactDir: filepath.Join(dir, "artifacts"),
	})
	if len(result.Results) != 1 || result.Results[0].MetricPath == "" {
		t.Fatalf("result = %#v", result)
	}
	if _, err := os.Stat(result.Results[0].MetricPath); err != nil {
		t.Fatalf("metric artifact missing: %v", err)
	}
}
