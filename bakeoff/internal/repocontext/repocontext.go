package repocontext

import (
	"bytes"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const (
	LayoutPolicyAuto = workorder.ScopeRepoLayoutAuto
	LayoutPolicyOff  = workorder.ScopeRepoLayoutOff

	layoutEntryCap = 20
	layoutByteCap  = 1536
	pathMissCap    = 10
	suggestionCap  = 3
)

var (
	markdownLinkRE = regexp.MustCompile(`!?\[[^\]\n]*\]\(([^\s)]+)[^)]*\)`)
	pathTokenRE    = regexp.MustCompile(`(?:\./|/)?[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+(?:\:\d+(?:-\d+)?)?`)
	promptTagRE    = regexp.MustCompile(`<\s*/?\s*[A-Za-z][A-Za-z0-9_-]*(\s+[^>]*)?>`)
	urlRE          = regexp.MustCompile(`[A-Za-z][A-Za-z0-9+.-]*://\S+`)
)

var commonPathRoots = map[string]bool{
	".github":    true,
	"app":        true,
	"apps":       true,
	"assets":     true,
	"backend":    true,
	"bin":        true,
	"build":      true,
	"client":     true,
	"cmd":        true,
	"config":     true,
	"configs":    true,
	"data":       true,
	"db":         true,
	"docs":       true,
	"examples":   true,
	"frontend":   true,
	"internal":   true,
	"lib":        true,
	"libs":       true,
	"migrations": true,
	"package":    true,
	"packages":   true,
	"pkg":        true,
	"public":     true,
	"scripts":    true,
	"server":     true,
	"src":        true,
	"test":       true,
	"tests":      true,
	"tools":      true,
	"ui":         true,
	"web":        true,
}

type LayoutEntry struct {
	Path        string
	Description string
}

type PathWarning struct {
	Field       string
	Token       string
	Suggestions []string
}

func LayoutEnabled(policy workorder.ScopePolicy, disabled bool) bool {
	return !disabled && policy.RepoLayout != LayoutPolicyOff
}

func ParticipantReceivesLayout(policy workorder.ScopePolicy, participant workorder.Participant, disabled bool) bool {
	if !LayoutEnabled(policy, disabled) {
		return false
	}
	return participant.Scope == "codebase" || participant.Scope == "mixed"
}

func LayoutBlockForParticipant(policy workorder.ScopePolicy, participant workorder.Participant, block string, disabled bool) string {
	if block == "" || !ParticipantReceivesLayout(policy, participant, disabled) {
		return ""
	}
	return block
}

func AnyParticipantReceivesLayout(wo *workorder.WorkOrder, disabled bool) bool {
	if wo == nil {
		return false
	}
	for _, participant := range wo.Providers {
		if ParticipantReceivesLayout(wo.ScopePolicy, participant, disabled) {
			return true
		}
	}
	return false
}

func BuildLayoutBlock(root string) (string, error) {
	entries, err := BuildLayout(root)
	if err != nil {
		return "", err
	}
	return RenderLayout(entries), nil
}

func BuildLayout(root string) ([]LayoutEntry, error) {
	root = filepath.Clean(root)
	files, ok := gitTrackedFiles(root)
	if !ok {
		return fallbackTopLevelDirs(root)
	}
	return topLevelDirsFromFiles(root, files)
}

func RenderLayout(entries []LayoutEntry) string {
	if len(entries) == 0 {
		return ""
	}
	lines := []string{
		"<repo_layout>",
		"Orientation only — directory map at run start. Verify before citing; do not assume file:line locations.",
	}
	closeTag := "</repo_layout>"
	currentBytes := len([]byte(strings.Join(lines, "\n")))
	added := 0
	for _, entry := range entries {
		if added >= layoutEntryCap {
			break
		}
		line, ok := renderLayoutEntry(entry)
		if !ok {
			continue
		}
		nextBytes := currentBytes + len([]byte("\n"+line+"\n"+closeTag))
		if nextBytes > layoutByteCap {
			break
		}
		lines = append(lines, line)
		currentBytes += len([]byte("\n" + line))
		added++
	}
	if added == 0 {
		return ""
	}
	lines = append(lines, closeTag)
	return strings.Join(lines, "\n")
}

func ValidateProsePaths(root string, wo *workorder.WorkOrder) ([]PathWarning, error) {
	if wo == nil {
		return nil, nil
	}
	root = filepath.Clean(root)
	index, err := buildPathIndex(root)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var warnings []PathWarning
	for _, field := range []struct {
		name string
		text string
	}{
		{name: "goal", text: wo.Goal},
		{name: "background", text: wo.Background},
	} {
		for _, token := range extractPathTokens(field.text) {
			if seen[token] {
				continue
			}
			seen[token] = true
			ref := stripLineSuffix(token)
			path, ok := resolveUnderRoot(root, ref)
			if ok && pathExists(path) {
				continue
			}
			suggestions := suggestPaths(ref, index)
			if !plausibleMissingPath(token, ref, suggestions) {
				continue
			}
			warnings = append(warnings, PathWarning{
				Field:       field.name,
				Token:       token,
				Suggestions: suggestions,
			})
			if len(warnings) >= pathMissCap {
				return warnings, nil
			}
		}
	}
	return warnings, nil
}

func extractPathTokens(text string) []string {
	text = markdownLinkRE.ReplaceAllString(text, " $1 ")
	text = urlRE.ReplaceAllString(text, " ")
	replacer := strings.NewReplacer(
		"`", " ",
		"[", " ",
		"]", " ",
		"(", " ",
		")", " ",
		"{", " ",
		"}", " ",
		"<", " ",
		">", " ",
		"\"", " ",
		"'", " ",
	)
	text = replacer.Replace(text)
	matches := pathTokenRE.FindAllString(text, -1)
	out := make([]string, 0, len(matches))
	for _, match := range matches {
		token := strings.TrimSpace(match)
		token = strings.TrimRight(token, ".,;!?")
		if token == "" || domainLikePath(token) {
			continue
		}
		out = append(out, token)
	}
	return out
}

func plausibleMissingPath(token string, ref string, suggestions []string) bool {
	if len(suggestions) > 0 || strings.HasPrefix(ref, "./") || stripLineSuffix(token) != token {
		return true
	}
	ref = cleanSlash(ref)
	first, _, _ := strings.Cut(ref, "/")
	if commonPathRoots[first] {
		return true
	}
	base := filepath.Base(ref)
	return strings.Contains(base, ".")
}

func domainLikePath(token string) bool {
	token = strings.TrimPrefix(token, "./")
	first, _, _ := strings.Cut(token, "/")
	if first == "" || strings.HasPrefix(first, ".") {
		return false
	}
	return strings.Contains(first, ".")
}

func stripLineSuffix(token string) string {
	idx := strings.LastIndex(token, ":")
	if idx == -1 {
		return token
	}
	suffix := token[idx+1:]
	if suffix == "" {
		return token
	}
	for _, part := range strings.Split(suffix, "-") {
		if part == "" {
			return token
		}
		for _, r := range part {
			if r < '0' || r > '9' {
				return token
			}
		}
	}
	return token[:idx]
}

func resolveUnderRoot(root string, ref string) (string, bool) {
	ref = filepath.FromSlash(strings.TrimSpace(ref))
	ref = strings.TrimPrefix(ref, "."+string(filepath.Separator))
	if ref == "" || ref == "." {
		return "", false
	}
	if filepath.IsAbs(ref) {
		cleanAbs := filepath.Clean(ref)
		rel, err := filepath.Rel(root, cleanAbs)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return "", false
		}
		return cleanAbs, true
	}
	clean := filepath.Clean(ref)
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", false
	}
	full := filepath.Join(root, clean)
	rel, err := filepath.Rel(root, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", false
	}
	return full, true
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

type indexedPath struct {
	Path  string
	IsDir bool
}

func buildPathIndex(root string) ([]indexedPath, error) {
	files, ok := gitTrackedFiles(root)
	if ok {
		return indexFromFiles(files), nil
	}
	return walkPathIndex(root)
}

func indexFromFiles(files []string) []indexedPath {
	seen := map[string]indexedPath{}
	for _, file := range files {
		file = cleanSlash(file)
		if file == "" {
			continue
		}
		seen[file] = indexedPath{Path: file, IsDir: false}
		parts := strings.Split(file, "/")
		for i := 1; i < len(parts); i++ {
			dir := strings.Join(parts[:i], "/") + "/"
			seen[dir] = indexedPath{Path: dir, IsDir: true}
		}
	}
	return sortedIndex(seen)
}

func walkPathIndex(root string) ([]indexedPath, error) {
	seen := map[string]indexedPath{}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == root {
			return nil
		}
		name := d.Name()
		if d.IsDir() && ignoredLayoutDir(name) {
			return filepath.SkipDir
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			rel += "/"
		}
		seen[rel] = indexedPath{Path: rel, IsDir: d.IsDir()}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return sortedIndex(seen), nil
}

func sortedIndex(seen map[string]indexedPath) []indexedPath {
	out := make([]indexedPath, 0, len(seen))
	for _, path := range seen {
		out = append(out, path)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].Path < out[j].Path
	})
	return out
}

func suggestPaths(ref string, index []indexedPath) []string {
	ref = cleanSlash(strings.TrimPrefix(ref, "./"))
	refBase := strings.TrimSuffix(filepath.Base(ref), "/")
	type candidate struct {
		path  string
		score int
	}
	var candidates []candidate
	for _, item := range index {
		path := strings.TrimSuffix(item.Path, "/")
		score := -1
		switch {
		case path == ref || strings.HasSuffix(path, "/"+ref):
			score = 0
		case item.IsDir && filepath.Base(path) == refBase:
			score = 1
		case !item.IsDir && filepath.Base(path) == refBase:
			score = 2
		}
		if score >= 0 {
			candidates = append(candidates, candidate{path: item.Path, score: score})
		}
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].score != candidates[j].score {
			return candidates[i].score < candidates[j].score
		}
		if len(candidates[i].path) != len(candidates[j].path) {
			return len(candidates[i].path) < len(candidates[j].path)
		}
		return candidates[i].path < candidates[j].path
	})
	limit := min(len(candidates), suggestionCap)
	out := make([]string, 0, limit)
	for i := 0; i < limit; i++ {
		out = append(out, candidates[i].path)
	}
	return out
}

func gitTrackedFiles(root string) ([]string, bool) {
	filesBytes, err := exec.Command("git", "-C", root, "ls-files", "--", ".").Output()
	if err != nil {
		return nil, false
	}
	lines := bytes.Split(filesBytes, []byte{'\n'})
	files := make([]string, 0, len(lines))
	for _, line := range lines {
		path := cleanSlash(strings.TrimSpace(string(line)))
		if path == "" {
			continue
		}
		files = append(files, path)
	}
	return files, true
}

func topLevelDirsFromFiles(root string, files []string) ([]LayoutEntry, error) {
	dirs := map[string]bool{}
	for _, file := range files {
		file = cleanSlash(file)
		if file == "" {
			continue
		}
		first, rest, ok := strings.Cut(file, "/")
		if !ok || rest == "" {
			continue
		}
		dirs[first+"/"] = true
	}
	return layoutEntries(root, dirs)
}

func fallbackTopLevelDirs(root string) ([]LayoutEntry, error) {
	items, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	dirs := map[string]bool{}
	for _, item := range items {
		if !item.IsDir() || ignoredLayoutDir(item.Name()) {
			continue
		}
		dirs[item.Name()+"/"] = true
	}
	return layoutEntries(root, dirs)
}

func layoutEntries(root string, dirs map[string]bool) ([]LayoutEntry, error) {
	paths := make([]string, 0, len(dirs))
	for path := range dirs {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	entries := make([]LayoutEntry, 0, min(len(paths), layoutEntryCap))
	for _, path := range paths {
		if len(entries) >= layoutEntryCap {
			break
		}
		description := packageDescription(filepath.Join(root, filepath.FromSlash(strings.TrimSuffix(path, "/"))))
		if description == "" {
			description = strings.TrimSuffix(filepath.Base(path), "/")
		}
		entries = append(entries, LayoutEntry{Path: path, Description: description})
	}
	return entries, nil
}

func packageDescription(dir string) string {
	items, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	var goFiles []string
	for _, item := range items {
		name := item.Name()
		if item.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		goFiles = append(goFiles, filepath.Join(dir, name))
	}
	sort.Strings(goFiles)
	for _, file := range goFiles {
		description := packageDocDescription(file)
		if description != "" {
			return description
		}
	}
	return ""
}

func packageDocDescription(path string) string {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, path, nil, parser.PackageClauseOnly|parser.ParseComments)
	if err != nil || file.Doc == nil {
		return ""
	}
	return firstDocLine(file.Doc)
}

func firstDocLine(group *ast.CommentGroup) string {
	text := strings.TrimSpace(group.Text())
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "go:build") || strings.HasPrefix(line, "+build") {
			continue
		}
		return line
	}
	return ""
}

func renderLayoutEntry(entry LayoutEntry) (string, bool) {
	path := cleanSlash(entry.Path)
	if strings.HasSuffix(entry.Path, "/") && path != "" {
		path += "/"
	}
	description := strings.TrimSpace(entry.Description)
	if unsafePromptText(path) || unsafePromptText(description) {
		return "", false
	}
	path = escapeAngles(path)
	description = escapeAngles(description)
	if description == "" {
		description = strings.TrimSuffix(filepath.Base(path), "/")
	}
	return path + " — " + description, true
}

func unsafePromptText(value string) bool {
	return promptTagRE.MatchString(value)
}

func escapeAngles(value string) string {
	value = strings.ReplaceAll(value, "<", "&lt;")
	value = strings.ReplaceAll(value, ">", "&gt;")
	return value
}

func ignoredLayoutDir(name string) bool {
	return name == ".git" || name == ".bakeoff" || strings.HasPrefix(name, ".")
}

func cleanSlash(path string) string {
	path = filepath.ToSlash(filepath.Clean(path))
	if path == "." {
		return ""
	}
	return strings.TrimPrefix(path, "./")
}
