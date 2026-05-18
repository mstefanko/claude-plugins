package buildverify

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const (
	StatusPassed         = "passed"
	StatusFailed         = "failed"
	StatusTimeout        = "timeout"
	StatusOutputCap      = "output_cap"
	StatusMissingCommand = "missing_command"
	StatusCancelled      = "cancelled"
)

type Options struct {
	CWD                   string
	ProviderID            string
	Baseline              bool
	Verifiers             []workorder.VerifierSpec
	Env                   []string
	HeartbeatSeconds      int
	OutputCapGraceSeconds int
	MaxOutputOverrunBytes int
	ArtifactDir           string
	OnTick                func(label string, tick runner.Tick)
}

type Result struct {
	Scope       string           `json:"scope"`
	ProviderID  string           `json:"provider_id,omitempty"`
	GatesPassed bool             `json:"gates_passed"`
	Results     []VerifierResult `json:"results"`
}

type VerifierResult struct {
	ID                  string                    `json:"id"`
	Kind                string                    `json:"kind"`
	Status              string                    `json:"status"`
	ExitCode            *int                      `json:"exit_code"`
	WallSeconds         float64                   `json:"wall_seconds"`
	OutputBytes         int                       `json:"output_bytes"`
	StdoutBytes         int                       `json:"stdout_bytes"`
	StderrBytes         int                       `json:"stderr_bytes"`
	StdoutObservedBytes int                       `json:"stdout_observed_bytes"`
	StderrObservedBytes int                       `json:"stderr_observed_bytes"`
	StdoutTruncated     bool                      `json:"stdout_truncated"`
	StderrTruncated     bool                      `json:"stderr_truncated"`
	IO                  runner.IOStats            `json:"io"`
	OutputCap           *runner.OutputCapMetadata `json:"output_cap,omitempty"`
	StdoutPath          string                    `json:"stdout_path,omitempty"`
	StderrPath          string                    `json:"stderr_path,omitempty"`
	StatusPath          string                    `json:"status_path,omitempty"`
	MetricPath          string                    `json:"metric_path,omitempty"`
	ArtifactError       string                    `json:"artifact_error,omitempty"`
	Metric              *MetricResult             `json:"metric,omitempty"`
}

type MetricResult struct {
	Name       string   `json:"name"`
	Value      *float64 `json:"value,omitempty"`
	Conclusive bool     `json:"conclusive"`
	Error      string   `json:"error,omitempty"`
}

type MetricComparison struct {
	ID           string  `json:"id"`
	Name         string  `json:"name"`
	Direction    string  `json:"direction"`
	Winner       string  `json:"winner,omitempty"`
	DeltaPercent float64 `json:"delta_percent,omitempty"`
	Threshold    float64 `json:"threshold_percent"`
	Conclusive   bool    `json:"conclusive"`
	Reason       string  `json:"reason,omitempty"`
}

func Run(ctx context.Context, opts Options) Result {
	scope := "provider"
	labelPrefix := "verify:" + opts.ProviderID + ":"
	if opts.Baseline {
		scope = "baseline"
		labelPrefix = "baseline:"
	}
	result := Result{Scope: scope, ProviderID: opts.ProviderID, GatesPassed: true}
	if opts.Baseline {
		result.ProviderID = ""
	}
	for _, verifier := range opts.Verifiers {
		if ctx.Err() != nil {
			result.GatesPassed = false
			break
		}
		label := labelPrefix + verifier.ID
		commandResult := runner.RunCommand(ctx, runner.Options{
			Argv: verifier.Argv,
			Budgets: runner.Budgets{
				WallClockSeconds:           verifier.WallClockSeconds,
				MaxOutputBytes:             verifier.MaxOutputBytes,
				HeartbeatSeconds:           opts.HeartbeatSeconds,
				OutputCapGraceSeconds:      opts.OutputCapGraceSeconds,
				MaxOutputOverrunBytes:      opts.MaxOutputOverrunBytes,
				MaxOutputOverrunBytesIsSet: true,
			},
			CWD: opts.CWD,
			Env: opts.Env,
			OnTick: func(tick runner.Tick) {
				if opts.OnTick != nil {
					opts.OnTick(label, tick)
				}
			},
		})
		verifierResult := resultFromRunner(verifier, commandResult)
		if verifier.Kind == "metric" {
			metric := ParseMetric(commandResult.Stdout, verifier.Metric)
			if commandResult.Status != runner.StatusOK && metric.Error == "" {
				metric.Error = "metric command did not exit successfully"
			}
			if commandResult.Status != runner.StatusOK {
				metric.Conclusive = false
				metric.Value = nil
			}
			verifierResult.Metric = metric
		}
		if opts.ArtifactDir != "" {
			verifierDir := filepath.Join(opts.ArtifactDir, verifier.ID)
			verifierResult.StdoutPath = filepath.Join(verifierDir, "stdout.txt")
			verifierResult.StderrPath = filepath.Join(verifierDir, "stderr.txt")
			verifierResult.StatusPath = filepath.Join(verifierDir, "status.json")
			if verifierResult.Metric != nil {
				verifierResult.MetricPath = filepath.Join(verifierDir, "metric.json")
			}
			writeErr := WriteVerifierArtifacts(verifierDir, verifierResult, commandResult)
			if writeErr != nil {
				verifierResult.ArtifactError = writeErr.Error()
			}
		}
		if verifier.Kind == "gate" && verifierResult.Status != StatusPassed {
			result.GatesPassed = false
		}
		result.Results = append(result.Results, verifierResult)
	}
	return result
}

func WriteVerifierArtifacts(dir string, result VerifierResult, commandResult runner.Result) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	result.StdoutPath = filepath.Join(dir, "stdout.txt")
	result.StderrPath = filepath.Join(dir, "stderr.txt")
	result.StatusPath = filepath.Join(dir, "status.json")
	if err := workorder.WriteTextAtomic(result.StdoutPath, commandResult.Stdout); err != nil {
		return err
	}
	if err := workorder.WriteTextAtomic(result.StderrPath, commandResult.Stderr); err != nil {
		return err
	}
	if result.Metric != nil {
		result.MetricPath = filepath.Join(dir, "metric.json")
		if err := workorder.WriteJSONAtomic(result.MetricPath, result.Metric); err != nil {
			return err
		}
	}
	return workorder.WriteJSONAtomic(result.StatusPath, result)
}

func ParseMetric(stdout string, spec *workorder.MetricSpec) *MetricResult {
	name := ""
	if spec != nil {
		name = spec.Name
	}
	result := &MetricResult{Name: name}
	line := lastNonEmptyLine(stdout)
	if line == "" {
		result.Error = "metric stdout did not contain a non-empty JSON line"
		return result
	}
	var obj map[string]any
	decoder := json.NewDecoder(strings.NewReader(line))
	decoder.UseNumber()
	if err := decoder.Decode(&obj); err != nil {
		result.Error = "last non-empty stdout line was not a JSON object"
		return result
	}
	var extra any
	if err := decoder.Decode(&extra); err == nil {
		result.Error = "last non-empty stdout line contained trailing JSON data"
		return result
	} else if err != io.EOF {
		result.Error = "last non-empty stdout line contained trailing non-JSON data"
		return result
	}
	if spec == nil || strings.TrimSpace(spec.Name) == "" {
		result.Error = "metric spec is missing"
		return result
	}
	value, ok := numericMetric(obj[spec.Name])
	if !ok {
		result.Error = fmt.Sprintf("metric %q missing or not a finite number", spec.Name)
		return result
	}
	result.Value = &value
	result.Conclusive = true
	return result
}

func CompareMetric(spec workorder.VerifierSpec, leftProvider string, left VerifierResult, rightProvider string, right VerifierResult) MetricComparison {
	comparison := MetricComparison{
		ID:        spec.ID,
		Direction: "",
		Threshold: 0,
	}
	if spec.Metric != nil {
		comparison.Name = spec.Metric.Name
		comparison.Direction = spec.Metric.Direction
		comparison.Threshold = math.Max(spec.Metric.MinDeltaPercent, spec.Metric.NoiseFloorPercent)
	}
	if spec.Kind != "metric" || spec.Metric == nil {
		comparison.Reason = "not a metric verifier"
		return comparison
	}
	if left.Metric == nil || right.Metric == nil || !left.Metric.Conclusive || !right.Metric.Conclusive || left.Metric.Value == nil || right.Metric.Value == nil {
		comparison.Reason = "metric was inconclusive for at least one provider"
		return comparison
	}
	leftValue := *left.Metric.Value
	rightValue := *right.Metric.Value
	winner, delta := metricWinner(spec.Metric.Direction, leftProvider, leftValue, rightProvider, rightValue)
	comparison.DeltaPercent = round3(delta)
	if winner == "" {
		comparison.Reason = "metric values were equal"
		return comparison
	}
	if delta < comparison.Threshold {
		comparison.Reason = "metric delta did not meet threshold"
		return comparison
	}
	comparison.Winner = winner
	comparison.Conclusive = true
	return comparison
}

func CompareMetrics(verifiers []workorder.VerifierSpec, providerOrder []string, results map[string]Result) []MetricComparison {
	if len(providerOrder) != 2 {
		return nil
	}
	leftID := providerOrder[0]
	rightID := providerOrder[1]
	leftResults := byID(results[leftID].Results)
	rightResults := byID(results[rightID].Results)
	comparisons := []MetricComparison{}
	for _, verifier := range verifiers {
		if verifier.Kind != "metric" {
			continue
		}
		comparisons = append(comparisons, CompareMetric(verifier, leftID, leftResults[verifier.ID], rightID, rightResults[verifier.ID]))
	}
	sort.Slice(comparisons, func(i, j int) bool { return comparisons[i].ID < comparisons[j].ID })
	return comparisons
}

func resultFromRunner(verifier workorder.VerifierSpec, result runner.Result) VerifierResult {
	return VerifierResult{
		ID:                  verifier.ID,
		Kind:                verifier.Kind,
		Status:              verifierStatus(result.Status),
		ExitCode:            result.ExitCode,
		WallSeconds:         result.WallSeconds,
		OutputBytes:         result.OutputBytes,
		StdoutBytes:         result.StdoutBytes,
		StderrBytes:         result.StderrBytes,
		StdoutObservedBytes: result.StdoutObservedBytes,
		StderrObservedBytes: result.StderrObservedBytes,
		StdoutTruncated:     result.StdoutTruncated,
		StderrTruncated:     result.StderrTruncated,
		IO:                  result.IO,
		OutputCap:           result.OutputCap,
	}
}

func verifierStatus(status string) string {
	switch status {
	case runner.StatusOK, runner.StatusOKAfterFormatRetry:
		return StatusPassed
	case runner.StatusTimeout:
		return StatusTimeout
	case runner.StatusOutputCap:
		return StatusOutputCap
	case runner.StatusMissingProvider:
		return StatusMissingCommand
	case runner.StatusCancelled:
		return StatusCancelled
	default:
		return StatusFailed
	}
}

func lastNonEmptyLine(text string) string {
	lines := strings.Split(text, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if line != "" {
			return line
		}
	}
	return ""
}

func numericMetric(value any) (float64, bool) {
	var out float64
	switch typed := value.(type) {
	case json.Number:
		parsed, err := typed.Float64()
		if err != nil {
			return 0, false
		}
		out = parsed
	case float64:
		out = typed
	case int:
		out = float64(typed)
	default:
		return 0, false
	}
	if math.IsNaN(out) || math.IsInf(out, 0) {
		return 0, false
	}
	return out, true
}

func metricWinner(direction string, leftProvider string, leftValue float64, rightProvider string, rightValue float64) (string, float64) {
	if leftValue == rightValue {
		return "", 0
	}
	leftBetter := leftValue > rightValue
	if direction == "lower" {
		leftBetter = leftValue < rightValue
	}
	winner := leftProvider
	winnerValue := leftValue
	loserValue := rightValue
	if !leftBetter {
		winner = rightProvider
		winnerValue = rightValue
		loserValue = leftValue
	}
	denominator := math.Abs(loserValue)
	if denominator == 0 {
		denominator = math.Max(math.Abs(winnerValue), 1)
	}
	return winner, math.Abs(loserValue-winnerValue) / denominator * 100
}

func byID(results []VerifierResult) map[string]VerifierResult {
	out := map[string]VerifierResult{}
	for _, result := range results {
		out[result.ID] = result
	}
	return out
}

func round3(value float64) float64 {
	return math.Round(value*1000) / 1000
}
