package runlinks

import (
	"os"
	"path/filepath"
	"sort"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type Escalation struct {
	RunID           string
	RunDir          string
	SourceRunID     string
	SourceType      string
	Mode            string
	AddedProvider   string
	DecisionKind    string
	TriageState     string
	StaleInputs     []string
	FinishedAt      string
	ReportPath      string
	ManifestPath    string
	SourceRunDir    string
	CanonicalWinner any
}

func EscalationsForSource(outDir string, sourceRunID string) []Escalation {
	escalations := ScanEscalations(outDir)
	out := []Escalation{}
	for _, escalation := range escalations {
		if escalation.SourceRunID == sourceRunID {
			out = append(out, escalation)
		}
	}
	return out
}

func ScanEscalations(outDir string) []Escalation {
	entries, err := os.ReadDir(outDir)
	if err != nil {
		return nil
	}
	out := []Escalation{}
	for _, entry := range entries {
		if !entry.IsDir() || entry.Name() == "latest" {
			continue
		}
		runDir := filepath.Join(outDir, entry.Name())
		manifestPath := filepath.Join(runDir, "manifest.json")
		manifest, ok := readObject(manifestPath)
		if !ok || jsonutil.StringValue(manifest["type"]) != "escalation" {
			continue
		}
		sourceRunID := jsonutil.StringValue(manifest["source_run_id"])
		if sourceRunID == "" {
			continue
		}
		state, staleInputs := triage.DisplayStateDetail(runDir)
		escalation := Escalation{
			RunID:           entry.Name(),
			RunDir:          runDir,
			SourceRunID:     sourceRunID,
			SourceType:      jsonutil.StringValue(manifest["source_type"]),
			Mode:            jsonutil.StringValue(manifest["escalation_mode"]),
			AddedProvider:   providerID(manifest["added_provider"]),
			DecisionKind:    jsonutil.StringValue(manifest["decision_kind"]),
			TriageState:     state,
			StaleInputs:     staleInputs,
			FinishedAt:      jsonutil.StringValue(manifest["finished_at"]),
			ManifestPath:    manifestPath,
			SourceRunDir:    jsonutil.StringValue(manifest["source_run_dir"]),
			CanonicalWinner: manifest["canonical_winner"],
		}
		if artifacts, ok := manifest["artifacts"].(map[string]any); ok {
			if report := jsonutil.StringValue(artifacts["report"]); report != "" {
				escalation.ReportPath = filepath.Join(runDir, report)
			}
		}
		if escalation.ReportPath == "" {
			escalation.ReportPath = filepath.Join(runDir, "report.md")
		}
		out = append(out, escalation)
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].FinishedAt != "" && out[j].FinishedAt != "" && out[i].FinishedAt != out[j].FinishedAt {
			return out[i].FinishedAt < out[j].FinishedAt
		}
		return out[i].RunID < out[j].RunID
	})
	return out
}

func RunManifest(runDir string) (map[string]any, bool) {
	return readObject(filepath.Join(runDir, "manifest.json"))
}

func readObject(path string) (map[string]any, bool) {
	value, err := workorder.ReadOptionalJSON(path)
	if err != nil {
		return nil, false
	}
	obj, ok := value.(map[string]any)
	if !ok || obj == nil {
		return nil, false
	}
	return obj, true
}

func providerID(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	obj, ok := value.(map[string]any)
	if !ok {
		return jsonutil.StringValue(value)
	}
	if id := jsonutil.StringValue(obj["id"]); id != "" {
		return id
	}
	return jsonutil.StringValue(obj["backend"])
}
