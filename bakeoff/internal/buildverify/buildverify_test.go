package buildverify

import (
	"context"
	"os"
	"path/filepath"
	"strings"
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

func TestRunExecutesGatesBeforeMetricsAndSkipsMetricsAfterGateFailure(t *testing.T) {
	dir := t.TempDir()
	marker := filepath.Join(dir, "metric-ran")
	result := Run(context.Background(), Options{
		CWD: dir,
		Verifiers: []workorder.VerifierSpec{
			{
				ID:               "metric",
				Kind:             "metric",
				Argv:             []string{"sh", "-c", "touch " + marker + "; printf '{\"score\":1}\\n'"},
				WallClockSeconds: 2,
				MaxOutputBytes:   1000,
				Metric:           &workorder.MetricSpec{Name: "score", Direction: "higher"},
			},
			{ID: "gate", Kind: "gate", Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
		ArtifactDir: filepath.Join(dir, "artifacts"),
	})
	if result.GatesPassed || len(result.Results) != 2 {
		t.Fatalf("result = %#v", result)
	}
	if result.Results[0].ID != "gate" || result.Results[0].Status != StatusFailed {
		t.Fatalf("gate was not executed first: %#v", result.Results)
	}
	if got := result.Results[1]; got.ID != "metric" || got.Status != StatusSkipped || got.SkipReason == "" {
		t.Fatalf("metric was not skipped explicitly: %#v", got)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("metric command should not have run, stat err=%v", err)
	}
	if _, err := os.Stat(result.Results[1].StatusPath); err != nil {
		t.Fatalf("skipped metric status artifact missing: %v", err)
	}
}

func TestRunBaselineVerifierExpectations(t *testing.T) {
	dir := t.TempDir()
	result := Run(context.Background(), Options{
		CWD:      dir,
		Baseline: true,
		Verifiers: []workorder.VerifierSpec{
			{ID: "must-pass", Kind: "gate", Baseline: workorder.VerifierBaselineMustPass, Argv: []string{"test", "-d", "."}, WallClockSeconds: 2, MaxOutputBytes: 1000},
			{ID: "must-fail", Kind: "gate", Baseline: workorder.VerifierBaselineMustFail, Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
			{ID: "may-fail", Kind: "gate", Baseline: workorder.VerifierBaselineMayFail, Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	if !result.GatesPassed {
		t.Fatalf("expected baseline expectations to match: %#v", result)
	}
	for _, item := range result.Results {
		if item.BaselineExpectation == "" || item.BaselineMatched == nil || !*item.BaselineMatched {
			t.Fatalf("missing matched baseline fields: %#v", item)
		}
	}

	surprise := Run(context.Background(), Options{
		CWD:      dir,
		Baseline: true,
		Verifiers: []workorder.VerifierSpec{
			{ID: "must-fail", Kind: "gate", Baseline: workorder.VerifierBaselineMustFail, Argv: []string{"test", "-d", "."}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	if surprise.GatesPassed || len(surprise.Results) != 1 || surprise.Results[0].BaselineMatched == nil || *surprise.Results[0].BaselineMatched {
		t.Fatalf("expected must_fail baseline pass surprise: %#v", surprise)
	}
}

func TestRunProviderGateMustPassAfterPatchWithBaselineTransition(t *testing.T) {
	dir := t.TempDir()
	baseline := Run(context.Background(), Options{
		CWD:      dir,
		Baseline: true,
		Verifiers: []workorder.VerifierSpec{
			{ID: "target", Kind: "gate", Baseline: workorder.VerifierBaselineMustFail, Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	provider := Run(context.Background(), Options{
		CWD:             dir,
		ProviderID:      "claude",
		BaselineResults: byID(baseline.Results),
		Verifiers: []workorder.VerifierSpec{
			{ID: "target", Kind: "gate", Baseline: workorder.VerifierBaselineMustFail, Argv: []string{"test", "-f", "missing"}, WallClockSeconds: 2, MaxOutputBytes: 1000},
		},
	})
	if provider.GatesPassed || len(provider.Results) != 1 {
		t.Fatalf("provider gate should still have to pass: %#v", provider)
	}
	got := provider.Results[0]
	if got.BaselineMatched == nil || !*got.BaselineMatched || got.Transition != "baseline_failed_to_provider_failed" {
		t.Fatalf("provider baseline fields = %#v", got)
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

func TestParseMetricMetadataAndIgnoredSamples(t *testing.T) {
	spec := &workorder.MetricSpec{Name: "p95_ms", Direction: "lower", MinDeltaPercent: 10}
	metric := ParseMetric("warmup\n{\"p95_ms\": 13}\n{\"p95_ms\": 12.5, \"unit\":\" ms \", \"n\":10, \"statistic\":\"median\", \"method\":\"benchstat\", \"ignored\":true}\n", spec)
	if !metric.Conclusive || metric.Value == nil || *metric.Value != 12.5 {
		t.Fatalf("metric = %#v", metric)
	}
	if metric.Unit != "ms" || metric.N == nil || *metric.N != 10 || metric.Statistic != "median" || metric.Method != "benchstat" {
		t.Fatalf("metadata = %#v", metric)
	}
	if metric.SampleJSONLinesIgnored != 1 || len(metric.MetadataWarnings) != 1 {
		t.Fatalf("ignored sample warnings = %#v", metric)
	}
}

func TestParseMetricDropsInvalidOptionalMetadata(t *testing.T) {
	spec := &workorder.MetricSpec{Name: "score", Direction: "higher", MinDeltaPercent: 1}
	metric := ParseMetric("{\"score\": 5, \"unit\": 123, \"n\": 0, \"statistic\": \"ok\"}\n", spec)
	if !metric.Conclusive || metric.Value == nil {
		t.Fatalf("metric should remain conclusive with invalid optional metadata: %#v", metric)
	}
	if metric.Unit != "" || metric.N != nil || metric.Statistic != "ok" || len(metric.MetadataWarnings) != 2 {
		t.Fatalf("metadata warnings = %#v", metric)
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
	if !comparison.MeetsMinDelta || !comparison.MeetsNoiseFloor || comparison.MinDeltaPercent != 10 || comparison.NoiseFloorPercent != 5 {
		t.Fatalf("comparison thresholds = %#v", comparison)
	}
	leftValue = 96
	comparison = CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &leftValue, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "p95_ms", Value: &rightValue, Conclusive: true}})
	if comparison.Conclusive || comparison.Winner != "" {
		t.Fatalf("expected threshold miss, got %#v", comparison)
	}
	if comparison.MeetsMinDelta || comparison.MeetsNoiseFloor {
		t.Fatalf("expected both threshold gates to miss, got %#v", comparison)
	}
}

func TestCompareMetricRequiresConfiguredMinRuns(t *testing.T) {
	spec := workorder.VerifierSpec{
		ID:   "bench",
		Kind: "metric",
		Metric: &workorder.MetricSpec{
			Name:              "score",
			Direction:         "higher",
			MinDeltaPercent:   5,
			NoiseFloorPercent: 1,
			MinRuns:           10,
		},
	}
	leftValue := 120.0
	rightValue := 100.0
	comparison := CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "score", Value: &leftValue, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "score", Value: &rightValue, Conclusive: true}})
	if comparison.Conclusive || !strings.Contains(comparison.Reason, "n was missing") {
		t.Fatalf("expected missing n to be inconclusive, got %#v", comparison)
	}
	lowRuns := 3
	enoughRuns := 10
	comparison = CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "score", Value: &leftValue, N: &lowRuns, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "score", Value: &rightValue, N: &enoughRuns, Conclusive: true}})
	if comparison.Conclusive || !strings.Contains(comparison.Reason, "below") {
		t.Fatalf("expected low n to be inconclusive, got %#v", comparison)
	}
	comparison = CompareMetric(spec, "left", VerifierResult{Metric: &MetricResult{Name: "score", Value: &leftValue, N: &enoughRuns, Conclusive: true}}, "right", VerifierResult{Metric: &MetricResult{Name: "score", Value: &rightValue, N: &enoughRuns, Conclusive: true}})
	if !comparison.Conclusive || comparison.Winner != "left" {
		t.Fatalf("expected enough runs to compare, got %#v", comparison)
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
