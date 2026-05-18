package verify

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

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
	var loadedManifest map[string]any
	manifestStatus := "ok"
	if !fileExists(manifestPath) {
		manifestStatus = "failed"
		problems = append(problems, "missing manifest: "+manifestPath)
	} else {
		data, err := os.ReadFile(manifestPath)
		if err != nil {
			manifestStatus = "failed"
			problems = append(problems, "invalid manifest: "+err.Error())
		} else if err := json.Unmarshal(data, &loadedManifest); err != nil {
			manifestStatus = "failed"
			problems = append(problems, "invalid manifest: "+err.Error())
		} else {
			if intValue(loadedManifest["schema_version"]) != manifest.SchemaVersion {
				manifestStatus = "failed"
				problems = append(problems, fmt.Sprintf("invalid manifest schema_version: %v", loadedManifest["schema_version"]))
			}
			if loadedManifest["run_id"] != filepath.Base(runDir) {
				manifestStatus = "failed"
				problems = append(problems, fmt.Sprintf("manifest run_id %q does not match %q", loadedManifest["run_id"], filepath.Base(runDir)))
			}
		}
	}

	missingRequired := []string{}
	for _, relative := range manifest.RequiredArtifacts {
		if !fileExists(filepath.Join(runDir, relative)) {
			missingRequired = append(missingRequired, relative)
			problems = append(problems, "missing artifact: "+filepath.Join(runDir, relative))
		}
	}
	if reviewPresent, missing := reviewContextSetStatus(runDir); reviewPresent && len(missing) > 0 {
		for _, relative := range missing {
			problems = append(problems, "missing review context artifact: "+filepath.Join(runDir, relative))
		}
	}

	fingerprintMismatches := []map[string]string{}
	checkedCount := 0
	fingerprintStatus := "ok"
	if loadedManifest != nil {
		fingerprints, ok := loadedManifest["artifact_fingerprints"].(map[string]any)
		if !ok {
			fingerprintStatus = "failed"
			problems = append(problems, "invalid manifest: artifact_fingerprints must be an object")
		} else {
			for relative, expected := range fingerprints {
				checkedCount++
				if reason := VerifyFingerprintEntry(runDir, relative, expected); reason != "" {
					fingerprintStatus = "failed"
					fingerprintMismatches = append(fingerprintMismatches, map[string]string{"path": relative, "reason": reason})
					if reason == "missing" {
						problems = append(problems, "missing artifact: "+filepath.Join(runDir, relative))
					} else {
						problems = append(problems, "fingerprint mismatch: "+filepath.Join(runDir, relative))
					}
				}
			}
			if legacyMissing := legacyMissingStableFingerprints(runDir, fingerprints); len(legacyMissing) > 0 {
				warnings = append(warnings, "manifest was written before stable provider/judge evidence fingerprinting: "+strings.Join(legacyMissing, ", "))
			}
		}
	} else if manifestStatus == "failed" {
		fingerprintStatus = "failed"
	}

	requiredStatus := "ok"
	if len(missingRequired) > 0 {
		requiredStatus = "failed"
	}
	state, staleInputs := triage.StateDetail(runDir)
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
			Checked: append([]string(nil), manifest.RequiredArtifacts...),
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

func legacyMissingStableFingerprints(runDir string, fingerprints map[string]any) []string {
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

func reviewContextSetStatus(runDir string) (bool, []string) {
	presentCount := 0
	missing := []string{}
	for _, relative := range manifest.ReviewContextArtifacts {
		if fileExists(filepath.Join(runDir, relative)) {
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

func VerifyFingerprintEntry(runDir string, relative string, expected any) string {
	obj, ok := expected.(map[string]any)
	if !ok || relative == "" {
		return "invalid"
	}
	path := filepath.Join(runDir, relative)
	if !fileExists(path) {
		return "missing"
	}
	size, sha, err := workorder.FileFingerprint(path)
	if err != nil {
		return "missing"
	}
	if int64Value(obj["size_bytes"]) != size || stringValue(obj["sha256"]) != sha {
		return "sha256_or_size"
	}
	return ""
}

func Next(runDir string, outDir string, exitCode int, triageState string) string {
	runID := filepath.Base(runDir)
	if exitCode == 0 {
		if triageState == "stale" {
			return ledger.BakeoffTriageCommand(runID, outDir, true)
		}
		if triageState == "yes" {
			return ledger.BakeoffShowCommand(runID, outDir, "--triage")
		}
		return ledger.BakeoffShowCommand(runID, outDir, "")
	}
	if fileExists(filepath.Join(runDir, "work-order.json")) {
		return ledger.BakeoffRerunCommand(runID, outDir)
	}
	return "restore the listed artifacts or rerun the original work order"
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func intValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case float64:
		return int(typed)
	default:
		return 0
	}
}

func int64Value(value any) int64 {
	switch typed := value.(type) {
	case int64:
		return typed
	case int:
		return int64(typed)
	case float64:
		return int64(typed)
	default:
		return 0
	}
}

func stringValue(value any) string {
	text, _ := value.(string)
	return text
}
