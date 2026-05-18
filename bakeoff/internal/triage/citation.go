package triage

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

func ResolveCitationCWD(meta map[string]any) (string, []string) {
	caveats := []string{}
	raw, _ := meta["cwd"].(string)
	if strings.TrimSpace(raw) != "" {
		candidate := expandUser(raw)
		info, err := os.Stat(candidate)
		if err != nil {
			caveats = append(caveats, "original cwd from meta.json does not exist; using current working directory for citation checks")
		} else if info.IsDir() {
			resolved, err := realAbs(candidate)
			if err == nil {
				return resolved, caveats
			}
			caveats = append(caveats, "original cwd from meta.json does not exist; using current working directory for citation checks")
		} else {
			caveats = append(caveats, "original cwd from meta.json is not a directory; using current working directory for citation checks")
		}
	} else {
		caveats = append(caveats, "original cwd missing from meta.json; using current working directory for citation checks")
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "", caveats
	}
	resolved, err := realAbs(cwd)
	if err != nil {
		return cwd, caveats
	}
	return resolved, caveats
}

func CollectCitationText(runDir string, reportText string, decision map[string]any) string {
	parts := []string{reportText}
	if data, err := json.Marshal(decision); err == nil {
		parts = append(parts, string(data))
	}
	for _, pattern := range []string{
		filepath.Join(runDir, "providers", "*", "final.json"),
		filepath.Join(runDir, "judge", "result*.json"),
	} {
		paths, _ := filepath.Glob(pattern)
		sort.Strings(paths)
		for _, path := range paths {
			data, err := os.ReadFile(path)
			if err == nil {
				parts = append(parts, string(data))
			}
		}
	}
	return strings.Join(parts, "\n")
}

func ExtractCitationsFromText(text string) []string {
	citations := []string{}
	seen := map[string]bool{}
	index := 0
	for index < len(text) {
		relative := strings.Index(text[index:], ":")
		if relative == -1 {
			break
		}
		colon := index + relative
		citation, next, ok := parseCitationAtColon(text, colon)
		if !ok {
			index = colon + 1
			continue
		}
		if !seen[citation] {
			seen[citation] = true
			citations = append(citations, citation)
		}
		index = next
	}
	return citations
}

func CheckCitations(citations []string, cwd string) map[string]any {
	checks := make([]any, 0, len(citations))
	for i, citation := range citations {
		check := CheckCitation(citation, cwd)
		check["id"] = fmt.Sprintf("C-%03d", i+1)
		checks = append(checks, check)
	}
	return map[string]any{"schema_version": 1, "cwd": cwd, "checks": checks}
}

func CitationCheckIDs(citationChecks map[string]any) map[string]bool {
	out := map[string]bool{}
	checks, _ := citationChecks["checks"].([]any)
	for _, check := range checks {
		obj, ok := check.(map[string]any)
		if !ok {
			continue
		}
		id, _ := obj["id"].(string)
		if id != "" {
			out[id] = true
		}
	}
	return out
}

func CheckCitation(citation string, cwd string) map[string]any {
	cwd, _ = realAbs(cwd)
	rawPath, lineStart, lineEnd, ok := ParseCitation(citation)
	if !ok {
		return map[string]any{"citation": citation, "status": "unsupported"}
	}
	resolved := rawPath
	if !filepath.IsAbs(resolved) {
		resolved = filepath.Join(cwd, resolved)
	}
	resolved = resolvePathBestEffort(resolved)
	base := map[string]any{
		"citation":      citation,
		"resolved_path": resolved,
		"line_start":    lineStart,
		"line_end":      lineEnd,
	}
	if !isRelativeTo(resolved, cwd) {
		base["status"] = "path_escape"
		return base
	}
	data, err := os.ReadFile(resolved)
	if err != nil {
		if os.IsNotExist(err) {
			base["status"] = "missing_file"
		} else {
			base["status"] = "read_error"
			base["error"] = err.Error()
		}
		return base
	}
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	if len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	if lineStart <= 0 || lineEnd < lineStart || lineStart > len(lines) || lineEnd > len(lines) {
		base["status"] = "line_out_of_range"
		base["line_count"] = len(lines)
		return base
	}
	excerptStart := max(1, lineStart-1)
	excerptEnd := min(len(lines), max(lineEnd, lineStart+1))
	for excerptEnd-excerptStart+1 > 3 {
		excerptEnd--
	}
	excerpt := []string{}
	for lineNumber := excerptStart; lineNumber <= excerptEnd; lineNumber++ {
		excerpt = append(excerpt, lines[lineNumber-1])
	}
	base["status"] = "ok"
	base["excerpt"] = strings.Join(excerpt, "\n")
	return base
}

func ParseCitation(citation string) (string, int, int, bool) {
	colon := strings.LastIndex(citation, ":")
	if colon == -1 {
		return "", 0, 0, false
	}
	rawPath := citation[:colon]
	rawLines := citation[colon+1:]
	if rawPath == "" || rawLines == "" {
		return "", 0, 0, false
	}
	startText := rawLines
	endText := rawLines
	if dash := strings.Index(rawLines, "-"); dash != -1 {
		startText = rawLines[:dash]
		endText = rawLines[dash+1:]
	}
	lineStart, err := strconv.Atoi(startText)
	if err != nil {
		return "", 0, 0, false
	}
	lineEnd, err := strconv.Atoi(endText)
	if err != nil {
		return "", 0, 0, false
	}
	return rawPath, lineStart, lineEnd, true
}

func parseCitationAtColon(text string, colon int) (string, int, bool) {
	if colon+1 >= len(text) || text[colon+1] < '0' || text[colon+1] > '9' {
		return "", 0, false
	}
	pathStart := colon
	for pathStart > 0 && isPathChar(text[pathStart-1]) {
		pathStart--
	}
	rawPath := text[pathStart:colon]
	if !looksLikeSupportedPath(rawPath, text, pathStart) {
		return "", 0, false
	}
	lineEnd := colon + 1
	for lineEnd < len(text) && text[lineEnd] >= '0' && text[lineEnd] <= '9' {
		lineEnd++
	}
	if lineEnd < len(text) && text[lineEnd] == '-' {
		rangeEnd := lineEnd + 1
		for rangeEnd < len(text) && text[rangeEnd] >= '0' && text[rangeEnd] <= '9' {
			rangeEnd++
		}
		if rangeEnd > lineEnd+1 {
			lineEnd = rangeEnd
		}
	}
	return text[pathStart:lineEnd], lineEnd, true
}

func looksLikeSupportedPath(rawPath string, fullText string, start int) bool {
	if rawPath == "" || strings.HasPrefix(rawPath, "//") || strings.Contains(rawPath, "://") {
		return false
	}
	windowStart := max(0, start-12)
	windowEnd := min(len(fullText), start+len(rawPath))
	if strings.Contains(fullText[windowStart:windowEnd], "://") {
		return false
	}
	if strings.HasSuffix(rawPath, ".") || !strings.Contains(filepath.Base(rawPath), ".") {
		return false
	}
	first := rawPath[0]
	return strings.HasPrefix(rawPath, "/") ||
		strings.HasPrefix(rawPath, "./") ||
		strings.HasPrefix(rawPath, "../") ||
		strings.Contains(rawPath, "/") ||
		(first >= 'A' && first <= 'Z') ||
		(first >= 'a' && first <= 'z') ||
		(first >= '0' && first <= '9')
}

func isPathChar(char byte) bool {
	return (char >= 'A' && char <= 'Z') ||
		(char >= 'a' && char <= 'z') ||
		(char >= '0' && char <= '9') ||
		char == '.' || char == '_' || char == '-' || char == '/'
}

func isRelativeTo(path string, parent string) bool {
	parentAbs, err := realAbs(parent)
	if err != nil {
		return false
	}
	pathAbs := resolvePathBestEffort(path)
	rel, err := filepath.Rel(parentAbs, pathAbs)
	if err != nil {
		return false
	}
	return rel == "." || (!strings.HasPrefix(rel, ".."+string(os.PathSeparator)) && rel != "..")
}

func realAbs(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return abs, nil
	}
	return real, nil
}

func resolvePathBestEffort(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		return path
	}
	real, err := filepath.EvalSymlinks(abs)
	if err == nil {
		return real
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(abs))
	if err == nil {
		return filepath.Join(parent, filepath.Base(abs))
	}
	return abs
}

func expandUser(path string) string {
	if path == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			return home
		}
	}
	if strings.HasPrefix(path, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, path[2:])
		}
	}
	return path
}
