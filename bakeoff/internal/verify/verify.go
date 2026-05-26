package verify

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/fsutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type Result struct {
	SchemaVersion     int               `json:"schema_version"`
	Command           string            `json:"command"`
	Status            string            `json:"status"`
	ExitCode          int               `json:"exit_code"`
	Warnings          []string          `json:"warnings"`
	RunID             string            `json:"run_id"`
	RunDir            string            `json:"run_dir"`
	Manifest          ManifestStatus    `json:"manifest"`
	RequiredArtifacts RequiredArtifacts `json:"required_artifacts"`
	Fingerprints      Fingerprints      `json:"fingerprints"`
	Triage            TriageStatus      `json:"triage"`
	Problems          []string          `json:"problems"`
	Next              string            `json:"next"`
}

type ManifestStatus struct {
	Status string `json:"status"`
	Path   string `json:"path"`
}

type RequiredArtifacts struct {
	Status  string   `json:"status"`
	Checked []string `json:"checked"`
	Missing []string `json:"missing"`
}

type Fingerprints struct {
	Status       string              `json:"status"`
	CheckedCount int                 `json:"checked_count"`
	Mismatches   []map[string]string `json:"mismatches"`
}

type TriageStatus struct {
	State       string   `json:"state"`
	StaleInputs []string `json:"stale_inputs"`
}

func Run(runDir string, displayOutDir string) Result {
	manifestPath := filepath.Join(runDir, "manifest.json")
	problems := []string{}
	warnings := []string{}
	var loadedManifest *manifestDocument
	manifestStatus := "ok"
	if !fsutil.FileExists(manifestPath) {
		manifestStatus = "failed"
		problems = append(problems, "missing manifest: "+manifestPath)
	} else {
		data, err := os.ReadFile(manifestPath)
		if err != nil {
			manifestStatus = "failed"
			problems = append(problems, "invalid manifest: "+err.Error())
		} else {
			var parsed manifestDocument
			err := json.Unmarshal(data, &parsed)
			if err != nil {
				manifestStatus = "failed"
				problems = append(problems, "invalid manifest: "+err.Error())
			} else {
				loadedManifest = &parsed
			}
		}
		if loadedManifest == nil {
			// Error already recorded above.
		} else {
			if loadedManifest.SchemaVersion != manifest.SchemaVersion {
				manifestStatus = "failed"
				problems = append(problems, fmt.Sprintf("invalid manifest schema_version: %v", loadedManifest.SchemaVersion))
			}
			if loadedManifest.RunID != filepath.Base(runDir) {
				manifestStatus = "failed"
				problems = append(problems, fmt.Sprintf("manifest run_id %q does not match %q", loadedManifest.RunID, filepath.Base(runDir)))
			}
		}
	}

	runType, runTypeErr := manifest.RunTypeForRun(runDir)
	if runTypeErr != nil {
		problems = append(problems, runTypeErr.Error())
	}
	requiredArtifacts := manifest.RequiredArtifactsForType(runType)
	requiredArtifacts = append(requiredArtifacts, dynamicRequiredArtifacts(runDir, runType)...)
	missingRequired := []string{}
	for _, relative := range requiredArtifacts {
		if !fsutil.FileExists(filepath.Join(runDir, relative)) {
			missingRequired = append(missingRequired, relative)
			problems = append(problems, "missing artifact: "+filepath.Join(runDir, relative))
		}
	}
	reviewPresent, missing := reviewContextSetStatus(runDir)
	reviewRequested := reviewContextRequested(runDir)
	if reviewRequested && !reviewPresent && len(missing) == 0 {
		missing = append([]string(nil), manifest.ReviewContextArtifacts...)
	}
	if (reviewPresent || reviewRequested) && len(missing) > 0 {
		for _, relative := range missing {
			problems = append(problems, "missing review context artifact: "+filepath.Join(runDir, relative))
		}
	}

	fingerprintMismatches := []map[string]string{}
	checkedCount := 0
	fingerprintStatus := "ok"
	if loadedManifest != nil {
		fingerprints, ok := parseFingerprintEntries(loadedManifest.ArtifactFingerprints)
		if !ok {
			fingerprintStatus = "failed"
			problems = append(problems, "invalid manifest: artifact_fingerprints must be an object")
		} else {
			for relative, expected := range fingerprints {
				checkedCount++
				if reason := verifyFingerprintEntry(runDir, relative, expected); reason != "" {
					fingerprintStatus = "failed"
					fingerprintMismatches = append(fingerprintMismatches, map[string]string{"path": relative, "reason": reason})
					if reason == "missing" {
						problems = append(problems, "missing artifact: "+filepath.Join(runDir, relative))
					} else if reason == "invalid" {
						problems = append(problems, "unsafe manifest path: "+relative)
					} else {
						problems = append(problems, "fingerprint mismatch: "+filepath.Join(runDir, relative))
					}
				}
			}
			if shouldCheckLegacyStableFingerprints(fingerprints) {
				if legacyMissing := legacyMissingStableFingerprints(runDir, fingerprints); len(legacyMissing) > 0 {
					warnings = append(warnings, "manifest was written before stable provider/judge evidence fingerprinting: "+strings.Join(legacyMissing, ", "))
				}
			}
		}
	} else if manifestStatus == "failed" {
		fingerprintStatus = "failed"
	}

	requiredStatus := "ok"
	if len(missingRequired) > 0 {
		requiredStatus = "failed"
	}
	state, staleInputs := triage.DisplayStateDetail(runDir)
	exitCode := 0
	if len(problems) > 0 {
		exitCode = 1
	}
	return Result{
		SchemaVersion: 1,
		Command:       "runs verify",
		Status:        summary.CommandStatus(exitCode),
		ExitCode:      exitCode,
		Warnings:      warnings,
		RunID:         filepath.Base(runDir),
		RunDir:        runDir,
		Manifest:      ManifestStatus{Status: manifestStatus, Path: manifestPath},
		RequiredArtifacts: RequiredArtifacts{
			Status:  requiredStatus,
			Checked: requiredArtifacts,
			Missing: missingRequired,
		},
		Fingerprints: Fingerprints{
			Status:       fingerprintStatus,
			CheckedCount: checkedCount,
			Mismatches:   fingerprintMismatches,
		},
		Triage:   TriageStatus{State: state, StaleInputs: staleInputs},
		Problems: problems,
		Next:     Next(runDir, displayOutDir, exitCode, state),
	}
}

type manifestDocument struct {
	SchemaVersion        int                         `json:"schema_version"`
	RunID                string                      `json:"run_id"`
	ArtifactFingerprints map[string]fingerprintEntry `json:"artifact_fingerprints"`
}

type fingerprintEntry struct {
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
}

func parseFingerprintEntries(fingerprints map[string]fingerprintEntry) (map[string]fingerprintEntry, bool) {
	if fingerprints == nil {
		return nil, false
	}
	return fingerprints, true
}

func verifyFingerprintEntry(runDir string, relative string, entry fingerprintEntry) string {
	return verifyFingerprintValues(runDir, relative, entry.SizeBytes, entry.SHA256)
}

func shouldCheckLegacyStableFingerprints(fingerprints map[string]fingerprintEntry) bool {
	for relative := range fingerprints {
		if isStableEvidenceArtifact(relative) {
			return false
		}
	}
	return true
}

func legacyMissingStableFingerprints(runDir string, fingerprints map[string]fingerprintEntry) []string {
	missing := []string{}
	for _, relative := range manifest.FingerprintArtifactPaths(runDir) {
		if !isStableEvidenceArtifact(relative) {
			continue
		}
		if _, ok := fingerprints[relative]; !ok {
			missing = append(missing, relative)
		}
	}
	return missing
}

func isStableEvidenceArtifact(relative string) bool {
	return strings.HasPrefix(relative, "providers/") || strings.HasPrefix(relative, "judge/")
}

func verifyFingerprintValues(runDir string, relative string, expectedSize int64, expectedSHA string) string {
	path, ok := safeChild(runDir, relative)
	if !ok {
		return "invalid"
	}
	size, sha, err := workorder.FileFingerprint(path)
	if err != nil {
		return "missing"
	}
	if expectedSize != size || expectedSHA != sha {
		return "sha256_or_size"
	}
	return ""
}

func safeChild(runDir, relative string) (string, bool) {
	if relative == "" || filepath.IsAbs(relative) {
		return "", false
	}
	cleaned := filepath.Clean(relative)
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, ".."+string(filepath.Separator)) {
		return "", false
	}
	abs := filepath.Join(runDir, cleaned)
	rel, err := filepath.Rel(runDir, abs)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", false
	}
	return abs, true
}

func reviewContextSetStatus(runDir string) (bool, []string) {
	presentCount := 0
	missing := []string{}
	for _, relative := range manifest.ReviewContextArtifacts {
		if fsutil.FileExists(filepath.Join(runDir, relative)) {
			presentCount++
		} else {
			missing = append(missing, relative)
		}
	}
	if presentCount == 0 {
		return false, nil
	}
	if presentCount == len(manifest.ReviewContextArtifacts) {
		return true, nil
	}
	return true, missing
}

func reviewContextRequested(runDir string) bool {
	meta := readOptionalObject(filepath.Join(runDir, "meta.json"))
	return jsonutil.BoolValue(meta["review_context_requested"])
}

func dynamicRequiredArtifacts(runDir string, runType string) []string {
	if runType != "build" {
		return nil
	}
	decision := readOptionalObject(filepath.Join(runDir, "decision.json"))
	winner := strings.TrimSpace(jsonutil.StringValue(decision["canonical_winner"]))
	if winner == "" {
		return nil
	}
	return []string{
		filepath.ToSlash(filepath.Join("providers", winner, "build", "diff.patch")),
		filepath.ToSlash(filepath.Join("providers", winner, "build", "verify", "result.json")),
	}
}

func readOptionalObject(path string) map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var obj map[string]any
	if err := json.Unmarshal(data, &obj); err != nil {
		return nil
	}
	return obj
}

func VerifyFingerprintEntry(runDir string, relative string, expected any) string {
	obj, ok := expected.(map[string]any)
	if !ok || relative == "" {
		return "invalid"
	}
	return verifyFingerprintValues(runDir, relative, jsonutil.Int64Value(obj["size_bytes"]), jsonutil.StringValue(obj["sha256"]))
}

func Next(runDir string, outDir string, exitCode int, triageState string) string {
	runID := filepath.Base(runDir)
	if exitCode == 0 {
		if triageState == "stale" || triageState == "dry_run" || triageState == "failed" {
			return ledger.BakeoffTriageCommand(runID, outDir, true)
		}
		if triageState == "yes" {
			return ledger.BakeoffShowCommand(runID, outDir, "--triage")
		}
		return ledger.BakeoffShowCommand(runID, outDir, "")
	}
	if fsutil.FileExists(filepath.Join(runDir, "work-order.json")) {
		return ledger.BakeoffRerunCommand(runID, outDir)
	}
	return "restore the listed artifacts or rerun the original work order"
}
