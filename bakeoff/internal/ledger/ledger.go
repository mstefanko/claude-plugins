package ledger

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var runIDRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

func MakeRunID(now time.Time, suffix string) string {
	if suffix == "" {
		suffix = fmt.Sprintf("%04x", now.UnixNano()&0xffff)
	}
	if len(suffix) > 4 {
		suffix = suffix[:4]
	}
	return fmt.Sprintf("%s-%s", now.UTC().Format("2006-01-02"), suffix)
}

func ValidateRunID(runID string) error {
	if runID == "latest" || runID == "." || runID == ".." || !runIDRE.MatchString(runID) {
		return fmt.Errorf("run-id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$ and not latest")
	}
	return nil
}

func ValidateVerifyRunID(runID string) error {
	if runID == "latest" {
		return nil
	}
	if IsPathLikeRunID(runID) {
		for _, part := range splitPath(runID) {
			if part == "." || part == ".." {
				return fmt.Errorf("run-id path must not contain . or .. segments")
			}
		}
		return nil
	}
	return ValidateRunID(runID)
}

func IsPathLikeRunID(runID string) bool {
	return strings.ContainsRune(runID, os.PathSeparator)
}

func RunDir(outDir string, runID string) string {
	return filepath.Join(outDir, runID)
}

func UpdateLatest(outDir string, runID string) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	latest := filepath.Join(outDir, "latest")
	tmp := filepath.Join(outDir, ".latest.tmp")
	_ = os.Remove(tmp)
	if err := os.Symlink(runID, tmp); err == nil {
		return os.Rename(tmp, latest)
	}
	_ = os.Remove(latest)
	return os.WriteFile(latest, []byte(runID+"\n"), 0o644)
}

func ResolveRunDir(outDir string, runID string) (string, error) {
	if runID == "latest" {
		latest := filepath.Join(outDir, "latest")
		if target, err := os.Readlink(latest); err == nil {
			if filepath.IsAbs(target) {
				return target, nil
			}
			return filepath.Abs(filepath.Join(outDir, target))
		}
		if data, err := os.ReadFile(latest); err == nil {
			target := strings.TrimSpace(string(data))
			if target != "" {
				resolved, err := ResolveRunDir(outDir, target)
				if err != nil {
					return "", err
				}
				return filepath.Abs(resolved)
			}
		}
	}
	candidate := filepath.Join(outDir, runID)
	if info, err := os.Stat(candidate); err == nil && info.IsDir() {
		return candidate, nil
	}
	if IsPathLikeRunID(runID) {
		if info, err := os.Stat(runID); err == nil && info.IsDir() {
			return runID, nil
		}
	}
	return "", fmt.Errorf("run not found: %s", runID)
}

func EnsureChildPath(parent string, child string) error {
	parentResolved, err := filepath.Abs(parent)
	if err != nil {
		return err
	}
	childResolved, err := filepath.Abs(child)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(parentResolved, childResolved)
	if err != nil {
		return err
	}
	if rel == "." || (!strings.HasPrefix(rel, ".."+string(os.PathSeparator)) && rel != "..") {
		return nil
	}
	return fmt.Errorf("refusing to remove run directory outside %s", parent)
}

func EnsureVerifyPathInsideOut(outDir string, runDir string) error {
	outResolved, err := filepath.Abs(outDir)
	if err != nil {
		return err
	}
	runResolved, err := filepath.Abs(runDir)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(outResolved, runResolved)
	if err != nil {
		return err
	}
	if rel == "." || (!strings.HasPrefix(rel, ".."+string(os.PathSeparator)) && rel != "..") {
		return nil
	}
	return fmt.Errorf("run-id path must stay inside --out")
}

func OutputDirForResolvedRun(outDir string, runDir string) string {
	if samePath(outDir, filepath.Dir(runDir)) {
		return outDir
	}
	return filepath.Dir(runDir)
}

func BakeoffShowCommand(runID string, outDir string, flag string) string {
	cmd := "bakeoff show " + shellQuote(runID) + outDirSuffix(outDir)
	if flag != "" {
		cmd += " " + flag
	}
	return cmd
}

func BakeoffTriageCommand(runID string, outDir string, force bool) string {
	cmd := "bakeoff triage " + shellQuote(runID) + outDirSuffix(outDir)
	if force {
		cmd += " --force"
	}
	return cmd
}

func BakeoffRerunCommand(runID string, outDir string) string {
	return "bakeoff rerun " + shellQuote(runID) + outDirSuffix(outDir)
}

func outDirSuffix(outDir string) string {
	if outDir == "runs" {
		return ""
	}
	return " --out " + shellQuote(outDir)
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}
	if regexp.MustCompile(`^[A-Za-z0-9._/@:+-]+$`).MatchString(value) {
		return value
	}
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func samePath(left string, right string) bool {
	leftAbs, leftErr := filepath.Abs(left)
	rightAbs, rightErr := filepath.Abs(right)
	return leftErr == nil && rightErr == nil && leftAbs == rightAbs
}

func splitPath(path string) []string {
	parts := []string{}
	for _, part := range strings.Split(filepath.Clean(path), string(os.PathSeparator)) {
		if part != "" {
			parts = append(parts, part)
		}
	}
	return parts
}
