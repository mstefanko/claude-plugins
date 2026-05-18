package buildworkspace

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

const (
	ContextSchemaVersion  = 1
	lockFileName          = "bakeoff-build.lock"
	lockStaleAfter        = 6 * time.Hour
	maxSourceStateEntries = 50
)

type Repository struct {
	Root                   string              `json:"source_git_root"`
	CommonDir              string              `json:"git_common_dir"`
	SourceIsLinkedWorktree bool                `json:"source_is_linked_worktree"`
	Branch                 string              `json:"source_branch"`
	HeadCommit             string              `json:"source_head_commit"`
	InvocationPath         string              `json:"source_invocation_path"`
	InvocationRelPath      string              `json:"source_invocation_relative_path"`
	SourceClean            bool                `json:"source_clean"`
	SourceDirtyCount       int                 `json:"source_dirty_count,omitempty"`
	SourceDirtyEntries     []SourceStatusEntry `json:"source_dirty_entries,omitempty"`
	SourceHasGitmodules    bool                `json:"source_has_gitmodules,omitempty"`
	SourceGitlinkCount     int                 `json:"source_gitlink_count,omitempty"`
	SourceGitlinkEntries   []GitlinkEntry      `json:"source_gitlink_entries,omitempty"`
	BaseRef                string              `json:"base_ref"`
	BaseCommit             string              `json:"base_commit"`
}

type SourceStatusEntry struct {
	Code string `json:"code"`
	Path string `json:"path"`
}

type GitlinkEntry struct {
	Path   string `json:"path"`
	Commit string `json:"commit"`
}

type WorktreeParent struct {
	Path                string `json:"worktree_parent_path"`
	InsideSource        bool   `json:"worktree_parent_inside_source"`
	InsideIgnoredSource bool   `json:"worktree_parent_inside_ignored_source"`
	FallbackUsed        bool   `json:"worktree_parent_fallback_used"`
}

type ContextMetadata struct {
	SchemaVersion                     int                 `json:"schema_version"`
	RunID                             string              `json:"run_id"`
	SourceGitRoot                     string              `json:"source_git_root"`
	GitCommonDir                      string              `json:"git_common_dir"`
	SourceIsLinkedWorktree            bool                `json:"source_is_linked_worktree"`
	SourceBranch                      string              `json:"source_branch"`
	SourceHeadCommit                  string              `json:"source_head_commit"`
	SourceInvocationPath              string              `json:"source_invocation_path"`
	SourceInvocationRelPath           string              `json:"source_invocation_relative_path"`
	SourceClean                       bool                `json:"source_clean"`
	SourceDirtyCount                  int                 `json:"source_dirty_count,omitempty"`
	SourceDirtyEntries                []SourceStatusEntry `json:"source_dirty_entries,omitempty"`
	SourceHasGitmodules               bool                `json:"source_has_gitmodules,omitempty"`
	SourceGitlinkCount                int                 `json:"source_gitlink_count,omitempty"`
	SourceGitlinkEntries              []GitlinkEntry      `json:"source_gitlink_entries,omitempty"`
	BaseRef                           string              `json:"base_ref"`
	BaseCommit                        string              `json:"base_commit"`
	WorktreeParentPath                string              `json:"worktree_parent_path"`
	WorktreeParentInsideSource        bool                `json:"worktree_parent_inside_source"`
	WorktreeParentInsideIgnoredSource bool                `json:"worktree_parent_inside_ignored_source"`
	WorktreeParentFallbackUsed        bool                `json:"worktree_parent_fallback_used"`
	BaselineWorktreePath              string              `json:"baseline_worktree_path,omitempty"`
	BaselineCleanupStatus             string              `json:"baseline_cleanup_status,omitempty"`
	ProviderIDs                       []string            `json:"provider_ids"`
	Verifiers                         []VerifierMetadata  `json:"verifiers"`
	CreatedAt                         string              `json:"created_at"`
}

type VerifierMetadata struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
}

type WorkspaceMetadata struct {
	GitRoot                  string `json:"git_root"`
	BaseRef                  string `json:"base_ref"`
	BaseCommit               string `json:"base_commit"`
	WorktreePath             string `json:"worktree_path"`
	ProviderCWD              string `json:"provider_cwd"`
	WorktreeRetained         bool   `json:"worktree_retained"`
	WorktreeRemoved          bool   `json:"worktree_removed"`
	CleanupStatus            string `json:"cleanup_status"`
	ProviderHead             string `json:"provider_head"`
	ProviderHeadIsBase       bool   `json:"provider_head_is_base"`
	ProviderCommittedChanges bool   `json:"provider_committed_changes"`
	ProviderID               string `json:"provider_id"`
	ProviderBackend          string `json:"provider_backend"`
	ProviderModel            string `json:"provider_model"`
	ProviderEffort           string `json:"provider_effort"`
}

type CleanupResult struct {
	Path                  string `json:"path"`
	Retained              bool   `json:"retained"`
	GitWorktreeRemoved    bool   `json:"git_worktree_removed"`
	FilesystemPathRemoved bool   `json:"filesystem_path_removed"`
	Status                string `json:"status"`
	Error                 string `json:"error,omitempty"`
}

type CaptureOptions struct {
	WorktreePath  string
	BaseCommit    string
	OutputDir     string
	PatchMaxBytes int
}

type CaptureResult struct {
	ProviderHead             string        `json:"provider_head"`
	ProviderHeadIsBase       bool          `json:"provider_head_is_base"`
	ProviderCommittedChanges bool          `json:"provider_committed_changes"`
	ChangedFiles             []ChangedFile `json:"changed_files"`
	TestFiles                []ChangedFile `json:"test_files"`
	BenchmarkFiles           []ChangedFile `json:"benchmark_files"`
	PatchBytes               int           `json:"patch_bytes"`
	PatchOverCap             bool          `json:"patch_over_cap"`
	GitlinkChangeRejected    bool          `json:"gitlink_change_rejected"`
	PatchPath                string        `json:"patch_path,omitempty"`
	DiffstatPath             string        `json:"diffstat_path,omitempty"`
	ChangedFilesPath         string        `json:"changed_files_path,omitempty"`
	TestFilesPath            string        `json:"test_files_path,omitempty"`
	BenchmarkFilesPath       string        `json:"benchmark_files_path,omitempty"`
}

type ChangedFile struct {
	Status string `json:"status"`
	Path   string `json:"path"`
}

type Lock struct {
	Path          string
	file          *os.File
	heartbeatStop chan struct{}
	heartbeatDone chan struct{}
}

// ResolveRepository performs source-checkout preflight. Build command callers
// should hold the repository build lock around this and subsequent worktree
// admin operations so source state and created worktrees share one critical
// section.
func ResolveRepository(ctx context.Context, cwd string, baseRef string) (Repository, error) {
	baseRef = strings.TrimSpace(baseRef)
	if baseRef == "" {
		return Repository{}, fmt.Errorf("base_ref must be a non-empty commit-ish")
	}
	if err := validateBaseRefSyntax(baseRef); err != nil {
		return Repository{}, err
	}
	root, err := gitOutput(ctx, cwd, "rev-parse", "--show-toplevel")
	if err != nil {
		return Repository{}, err
	}
	root, err = filepath.Abs(strings.TrimSpace(root))
	if err != nil {
		return Repository{}, err
	}
	commonDir, err := gitOutput(ctx, root, "rev-parse", "--git-common-dir")
	if err != nil {
		return Repository{}, err
	}
	commonDir = absGitPath(root, commonDir)
	gitDir, err := gitOutput(ctx, root, "rev-parse", "--git-dir")
	if err != nil {
		return Repository{}, err
	}
	gitDir = absGitPath(root, gitDir)
	invocationPath, err := filepath.Abs(cwd)
	if err != nil {
		return Repository{}, err
	}
	invocationRel, err := filepath.Rel(root, invocationPath)
	if err != nil {
		return Repository{}, err
	}
	invocationRel = filepath.Clean(invocationRel)
	if invocationRel == "" || invocationRel == "." {
		invocationRel = "."
	} else if strings.HasPrefix(invocationRel, ".."+string(filepath.Separator)) || invocationRel == ".." || filepath.IsAbs(invocationRel) {
		return Repository{}, fmt.Errorf("current working directory %q is outside git root %q", invocationPath, root)
	}
	branch, err := gitOutput(ctx, root, "branch", "--show-current")
	if err != nil {
		return Repository{}, err
	}
	head, err := gitOutput(ctx, root, "rev-parse", "--verify", "HEAD^{commit}")
	if err != nil {
		return Repository{}, err
	}
	baseCommit, err := gitOutput(ctx, root, "rev-parse", "--verify", baseRef+"^{commit}")
	if err != nil {
		return Repository{}, fmt.Errorf("resolve base_ref %q: %w", baseRef, err)
	}
	sourceState, err := InspectSourceState(ctx, root)
	if err != nil {
		return Repository{}, err
	}
	return Repository{
		Root:                   root,
		CommonDir:              commonDir,
		SourceIsLinkedWorktree: filepath.Clean(gitDir) != filepath.Clean(commonDir),
		Branch:                 strings.TrimSpace(branch),
		HeadCommit:             strings.TrimSpace(head),
		InvocationPath:         invocationPath,
		InvocationRelPath:      filepath.ToSlash(invocationRel),
		SourceClean:            sourceState.Clean,
		SourceDirtyCount:       sourceState.DirtyCount,
		SourceDirtyEntries:     sourceState.DirtyEntries,
		SourceHasGitmodules:    sourceState.HasGitmodules,
		SourceGitlinkCount:     sourceState.GitlinkCount,
		SourceGitlinkEntries:   sourceState.GitlinkEntries,
		BaseRef:                baseRef,
		BaseCommit:             strings.TrimSpace(baseCommit),
	}, nil
}

type SourceState struct {
	Clean          bool
	DirtyCount     int
	DirtyEntries   []SourceStatusEntry
	HasGitmodules  bool
	GitlinkCount   int
	GitlinkEntries []GitlinkEntry
}

func InspectSourceState(ctx context.Context, root string) (SourceState, error) {
	status, err := gitOutput(ctx, root, "status", "--porcelain=v1", "--untracked-files=all")
	if err != nil {
		return SourceState{}, err
	}
	state := SourceState{Clean: strings.TrimSpace(status) == ""}
	for _, line := range strings.Split(strings.TrimSpace(status), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		state.DirtyCount++
		if len(state.DirtyEntries) >= maxSourceStateEntries {
			continue
		}
		code := strings.TrimSpace(line[:min(2, len(line))])
		path := ""
		if len(line) > 3 {
			path = strings.TrimSpace(line[3:])
		}
		state.DirtyEntries = append(state.DirtyEntries, SourceStatusEntry{Code: code, Path: path})
	}
	if info, err := os.Stat(filepath.Join(root, ".gitmodules")); err == nil && !info.IsDir() {
		state.HasGitmodules = true
	} else if err != nil && !os.IsNotExist(err) {
		return SourceState{}, err
	}
	entries, err := gitOutput(ctx, root, "ls-files", "-s")
	if err != nil {
		return SourceState{}, err
	}
	for _, line := range strings.Split(entries, "\n") {
		if !strings.HasPrefix(line, "160000 ") {
			continue
		}
		state.GitlinkCount++
		if len(state.GitlinkEntries) >= maxSourceStateEntries {
			continue
		}
		meta, path, ok := strings.Cut(line, "\t")
		fields := strings.Fields(meta)
		if ok && len(fields) >= 2 {
			state.GitlinkEntries = append(state.GitlinkEntries, GitlinkEntry{Commit: fields[1], Path: path})
		}
	}
	return state, nil
}

func ResolveCommonDir(ctx context.Context, cwd string) (string, error) {
	root, err := gitOutput(ctx, cwd, "rev-parse", "--show-toplevel")
	if err != nil {
		return "", err
	}
	root, err = filepath.Abs(strings.TrimSpace(root))
	if err != nil {
		return "", err
	}
	commonDir, err := gitOutput(ctx, root, "rev-parse", "--git-common-dir")
	if err != nil {
		return "", err
	}
	return absGitPath(root, commonDir), nil
}

func RequireCleanSource(ctx context.Context, root string) error {
	status, err := gitOutput(ctx, root, "status", "--porcelain=v1", "--untracked-files=all")
	if err != nil {
		return err
	}
	if strings.TrimSpace(status) != "" {
		return fmt.Errorf("source checkout is dirty; commit, stash, or remove local changes before build")
	}
	return nil
}

func RejectSubmodules(ctx context.Context, root string) error {
	if info, err := os.Stat(filepath.Join(root, ".gitmodules")); err == nil && !info.IsDir() {
		return fmt.Errorf("build mode does not support repositories with .gitmodules in v1")
	} else if err != nil && !os.IsNotExist(err) {
		return err
	}
	entries, err := gitOutput(ctx, root, "ls-files", "-s")
	if err != nil {
		return err
	}
	for _, line := range strings.Split(entries, "\n") {
		if strings.HasPrefix(line, "160000 ") {
			return fmt.Errorf("build mode does not support repositories with gitlink submodule entries in v1")
		}
	}
	return nil
}

func PrepareWorktreeParent(ctx context.Context, repo Repository, runDir string) (WorktreeParent, error) {
	absRunDir, err := filepath.Abs(runDir)
	if err != nil {
		return WorktreeParent{}, err
	}
	defaultPath := filepath.Join(absRunDir, "worktrees")
	inside := IsChildPath(repo.Root, defaultPath)
	if !inside {
		return WorktreeParent{Path: defaultPath, InsideSource: false}, nil
	}
	if IsIgnored(ctx, repo.Root, defaultPath) && !HasTrackedPrefix(ctx, repo.Root, defaultPath) {
		return WorktreeParent{Path: defaultPath, InsideSource: true, InsideIgnoredSource: true}, nil
	}
	fallback, err := os.MkdirTemp("", "bakeoff-worktrees-")
	if err != nil {
		return WorktreeParent{}, err
	}
	if err := os.Chmod(fallback, 0o700); err != nil {
		_ = os.RemoveAll(fallback)
		return WorktreeParent{}, err
	}
	return WorktreeParent{Path: fallback, InsideSource: false, FallbackUsed: true}, nil
}

func IsIgnored(ctx context.Context, repoRoot string, path string) bool {
	relative, err := filepath.Rel(repoRoot, path)
	if err != nil || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || relative == ".." {
		return false
	}
	cmd := exec.CommandContext(ctx, "git", "-C", repoRoot, "check-ignore", "-q", "--", filepath.ToSlash(relative))
	return cmd.Run() == nil
}

func HasTrackedPrefix(ctx context.Context, repoRoot string, path string) bool {
	relative, err := filepath.Rel(repoRoot, path)
	if err != nil || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || relative == ".." || relative == "." {
		return false
	}
	parts := strings.Split(filepath.ToSlash(relative), "/")
	if len(parts) == 0 || parts[0] == "" {
		return false
	}
	out, err := gitOutput(ctx, repoRoot, "ls-files", "--", parts[0])
	if err != nil {
		return false
	}
	return strings.TrimSpace(out) != ""
}

func IsChildPath(parent string, child string) bool {
	parentAbs, err := filepath.Abs(parent)
	if err != nil {
		return false
	}
	childAbs, err := filepath.Abs(child)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(parentAbs, childAbs)
	if err != nil {
		return false
	}
	return rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)))
}

// CreateDetachedWorktree mutates git worktree metadata. Callers must hold the
// repository build lock returned by AcquireLock while calling it.
func CreateDetachedWorktree(ctx context.Context, repo Repository, path string) error {
	if repo.BaseCommit == "" {
		return fmt.Errorf("base commit is required")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	_, err := gitOutput(ctx, repo.Root, "worktree", "add", "--detach", path, repo.BaseCommit)
	return err
}

func WorktreeInvocationPath(repo Repository, worktreePath string) string {
	rel := strings.TrimSpace(repo.InvocationRelPath)
	if rel == "" || rel == "." {
		return worktreePath
	}
	return filepath.Join(worktreePath, filepath.FromSlash(rel))
}

// CleanupWorktree forcibly removes a provider worktree. The force is intentional
// because provider changes are staged during capture; callers must invoke this
// only after patch capture has completed or when discarding an already-failed
// setup path.
func CleanupWorktree(ctx context.Context, repo Repository, path string, keep bool) CleanupResult {
	result := CleanupResult{Path: path}
	if keep {
		result.Retained = true
		result.Status = "retained"
		return result
	}
	var messages []string
	gitRemoved := false
	if _, err := gitOutput(ctx, repo.Root, "worktree", "remove", "--force", path); err != nil {
		messages = append(messages, err.Error())
	} else {
		result.GitWorktreeRemoved = true
		gitRemoved = true
	}
	if _, err := os.Stat(path); os.IsNotExist(err) {
		if gitRemoved {
			result.FilesystemPathRemoved = true
		} else {
			messages = append(messages, fmt.Sprintf("filesystem path does not exist: %s", path))
		}
	} else if err != nil {
		messages = append(messages, err.Error())
	} else if err := os.RemoveAll(path); err != nil {
		messages = append(messages, err.Error())
	} else {
		result.FilesystemPathRemoved = true
	}
	if len(messages) > 0 {
		result.Status = "failed"
		result.Error = strings.Join(messages, "; ")
		return result
	}
	result.Status = "removed"
	return result
}

func CaptureChanges(ctx context.Context, opts CaptureOptions) (CaptureResult, error) {
	if opts.WorktreePath == "" {
		return CaptureResult{}, fmt.Errorf("worktree path is required")
	}
	if opts.BaseCommit == "" {
		return CaptureResult{}, fmt.Errorf("base commit is required")
	}
	if opts.PatchMaxBytes <= 0 {
		return CaptureResult{}, fmt.Errorf("patch max bytes must be positive")
	}
	if err := requireWorktreeRoot(ctx, opts.WorktreePath); err != nil {
		return CaptureResult{}, err
	}
	if _, err := gitOutput(ctx, opts.WorktreePath, "add", "-A"); err != nil {
		return CaptureResult{}, err
	}
	head, err := gitOutput(ctx, opts.WorktreePath, "rev-parse", "--verify", "HEAD^{commit}")
	if err != nil {
		return CaptureResult{}, err
	}
	ahead, err := gitOutput(ctx, opts.WorktreePath, "rev-list", "--count", opts.BaseCommit+"..HEAD")
	if err != nil {
		return CaptureResult{}, err
	}
	nameStatus, err := gitOutput(ctx, opts.WorktreePath, "diff", "--cached", "--name-status", opts.BaseCommit, "--", ".")
	if err != nil {
		return CaptureResult{}, err
	}
	diffstat, err := gitOutput(ctx, opts.WorktreePath, "diff", "--cached", "--stat", opts.BaseCommit, "--", ".")
	if err != nil {
		return CaptureResult{}, err
	}
	patch, err := gitOutputRaw(ctx, opts.WorktreePath, "diff", "--cached", "--binary", opts.BaseCommit, "--", ".")
	if err != nil {
		return CaptureResult{}, err
	}
	raw, err := gitOutput(ctx, opts.WorktreePath, "diff", "--cached", "--raw", opts.BaseCommit, "--", ".")
	if err != nil {
		return CaptureResult{}, err
	}
	aheadCount, _ := strconv.Atoi(strings.TrimSpace(ahead))
	result := CaptureResult{
		ProviderHead:             strings.TrimSpace(head),
		ProviderHeadIsBase:       strings.TrimSpace(head) == opts.BaseCommit,
		ProviderCommittedChanges: aheadCount > 0,
		ChangedFiles:             ParseNameStatus(nameStatus),
		PatchBytes:               len(patch),
		PatchOverCap:             len(patch) > opts.PatchMaxBytes,
		GitlinkChangeRejected:    HasGitlinkDiff(raw),
	}
	result.TestFiles, result.BenchmarkFiles = ClassifyBuildEvidenceFiles(result.ChangedFiles)
	if opts.OutputDir != "" {
		if err := os.MkdirAll(opts.OutputDir, 0o755); err != nil {
			return CaptureResult{}, err
		}
		result.ChangedFilesPath = filepath.Join(opts.OutputDir, "changed-files.txt")
		result.TestFilesPath = filepath.Join(opts.OutputDir, "test-files.json")
		result.BenchmarkFilesPath = filepath.Join(opts.OutputDir, "benchmark-files.json")
		result.DiffstatPath = filepath.Join(opts.OutputDir, "diffstat.txt")
		result.PatchPath = filepath.Join(opts.OutputDir, "diff.patch")
		if err := workorder.WriteTextAtomic(result.ChangedFilesPath, nameStatus); err != nil {
			return CaptureResult{}, err
		}
		if err := workorder.WriteJSONAtomic(result.TestFilesPath, result.TestFiles); err != nil {
			return CaptureResult{}, err
		}
		if err := workorder.WriteJSONAtomic(result.BenchmarkFilesPath, result.BenchmarkFiles); err != nil {
			return CaptureResult{}, err
		}
		if err := workorder.WriteTextAtomic(result.DiffstatPath, diffstat); err != nil {
			return CaptureResult{}, err
		}
		if err := workorder.WriteTextAtomic(result.PatchPath, string(patch)); err != nil {
			return CaptureResult{}, err
		}
	}
	return result, nil
}

func ClassifyBuildEvidenceFiles(changed []ChangedFile) ([]ChangedFile, []ChangedFile) {
	tests := []ChangedFile{}
	benchmarks := []ChangedFile{}
	for _, file := range changed {
		path := normalizedChangedPath(file.Path)
		if isBuildTestPath(path) {
			tests = append(tests, file)
		}
		if isBuildBenchmarkPath(path) {
			benchmarks = append(benchmarks, file)
		}
	}
	return tests, benchmarks
}

func normalizedChangedPath(path string) string {
	if strings.Contains(path, " -> ") {
		parts := strings.Split(path, " -> ")
		path = parts[len(parts)-1]
	}
	return strings.Trim(filepath.ToSlash(path), "/")
}

func isBuildTestPath(path string) bool {
	lower := strings.ToLower(path)
	base := filepath.Base(lower)
	switch {
	case strings.HasSuffix(base, "_test.go"):
		return true
	case strings.HasPrefix(base, "test_") && strings.HasSuffix(base, ".py"):
		return true
	case strings.HasSuffix(base, "_test.py"):
		return true
	case strings.Contains(base, ".test."):
		return true
	case strings.Contains(base, ".spec."):
		return true
	}
	for _, part := range strings.Split(lower, "/") {
		switch part {
		case "__tests__", "tests", "test", "spec":
			return true
		}
	}
	if strings.Contains(lower, "/fixtures/") || strings.HasPrefix(lower, "fixtures/") {
		return strings.Contains(lower, "/tests/") || strings.Contains(lower, "/test/") || strings.Contains(lower, "/spec/") || strings.Contains(lower, "__tests__/")
	}
	return false
}

func isBuildBenchmarkPath(path string) bool {
	lower := strings.ToLower(path)
	base := filepath.Base(lower)
	switch {
	case strings.HasSuffix(base, "_bench_test.go"):
		return true
	case strings.HasPrefix(base, "bench") && strings.HasSuffix(base, ".py"):
		return true
	case strings.HasPrefix(base, "benchmark") && strings.HasSuffix(base, ".py"):
		return true
	}
	parts := strings.Split(lower, "/")
	for _, part := range parts {
		switch part {
		case "bench", "benchmarks", "perf", "performance", "load", "stress", "probes":
			return true
		}
	}
	if len(parts) >= 2 && parts[0] == "scripts" {
		for _, marker := range []string{"bench", "perf", "load", "stress", "probe"} {
			if strings.Contains(base, marker) {
				return true
			}
		}
	}
	return false
}

func ParseNameStatus(text string) []ChangedFile {
	out := []ChangedFile{}
	for _, line := range strings.Split(strings.TrimSpace(text), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		fields := strings.Split(line, "\t")
		if len(fields) < 2 {
			continue
		}
		path := fields[1]
		if len(fields) > 2 {
			path = fields[1] + " -> " + fields[2]
		}
		out = append(out, ChangedFile{Status: fields[0], Path: path})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Path == out[j].Path {
			return out[i].Status < out[j].Status
		}
		return out[i].Path < out[j].Path
	})
	return out
}

func HasGitlinkDiff(raw string) bool {
	for _, line := range strings.Split(raw, "\n") {
		if !strings.HasPrefix(line, ":") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) >= 2 && (strings.TrimPrefix(fields[0], ":") == "160000" || fields[1] == "160000") {
			return true
		}
	}
	return false
}

func AcquireLock(ctx context.Context, commonDir string, timeout time.Duration) (*Lock, error) {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	if err := os.MkdirAll(commonDir, 0o755); err != nil {
		return nil, err
	}
	lockPath := filepath.Join(commonDir, lockFileName)
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(25 * time.Millisecond)
	defer ticker.Stop()
	metadata := fmt.Sprintf("pid=%d\ncreated_at=%s\n", os.Getpid(), time.Now().UTC().Format(time.RFC3339))
	for {
		acquired, err := createLockFile(lockPath, metadata)
		if err == nil && acquired {
			lock := &Lock{Path: lockPath}
			lock.startHeartbeat()
			return lock, nil
		}
		if err != nil {
			return nil, err
		}
		if removeStaleLock(lockPath) {
			continue
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-deadline.C:
			return nil, fmt.Errorf("another build run is active for this repository: %s", lockPath)
		case <-ticker.C:
		}
	}
}

func createLockFile(path string, contents string) (bool, error) {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".")
	if err != nil {
		return false, err
	}
	tmpName := tmp.Name()
	removeTmp := true
	defer func() {
		if removeTmp {
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := tmp.WriteString(contents); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Close(); err != nil {
		return false, err
	}
	if err := os.Link(tmpName, path); err == nil {
		return true, nil
	} else if os.IsExist(err) {
		return false, nil
	} else {
		return false, err
	}
}

func removeStaleLock(path string) bool {
	info, statErr := os.Stat(path)
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	age := time.Duration(0)
	if statErr == nil {
		age = time.Since(info.ModTime())
	}
	pid, ok := parseLockPID(string(data))
	if statErr == nil && age > lockStaleAfter {
		return os.Remove(path) == nil
	}
	if !ok {
		return false
	}
	if pid == os.Getpid() {
		return false
	}
	alive, known := processAlive(pid)
	if known && !alive {
		return os.Remove(path) == nil
	}
	if alive {
		return false
	}
	return false
}

func parseLockPID(text string) (int, bool) {
	for _, line := range strings.Split(text, "\n") {
		if !strings.HasPrefix(line, "pid=") {
			continue
		}
		pid, err := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "pid=")))
		if err != nil || pid <= 0 {
			return 0, false
		}
		return pid, true
	}
	return 0, false
}

func (l *Lock) Release() error {
	if l == nil {
		return nil
	}
	l.stopHeartbeat()
	var messages []string
	if l.file != nil {
		if err := l.file.Close(); err != nil {
			messages = append(messages, err.Error())
		}
	}
	if l.Path != "" {
		if err := os.Remove(l.Path); err != nil && !os.IsNotExist(err) {
			messages = append(messages, err.Error())
		}
	}
	if len(messages) > 0 {
		return errors.New(strings.Join(messages, "; "))
	}
	return nil
}

func (l *Lock) startHeartbeat() {
	l.heartbeatStop = make(chan struct{})
	l.heartbeatDone = make(chan struct{})
	go func() {
		defer close(l.heartbeatDone)
		ticker := time.NewTicker(time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-l.heartbeatStop:
				return
			case <-ticker.C:
				now := time.Now()
				_ = os.Chtimes(l.Path, now, now)
			}
		}
	}()
}

func (l *Lock) stopHeartbeat() {
	if l.heartbeatStop == nil {
		return
	}
	close(l.heartbeatStop)
	if l.heartbeatDone != nil {
		<-l.heartbeatDone
	}
	l.heartbeatStop = nil
	l.heartbeatDone = nil
}

func WriteContext(runDir string, metadata ContextMetadata) error {
	metadata.SchemaVersion = ContextSchemaVersion
	if metadata.CreatedAt == "" {
		metadata.CreatedAt = time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
	}
	return workorder.WriteJSONAtomic(filepath.Join(runDir, "build-context.json"), metadata)
}

func WriteWorkspace(path string, metadata WorkspaceMetadata) error {
	return workorder.WriteJSONAtomic(path, metadata)
}

func ContextFrom(repo Repository, runID string, parent WorktreeParent, providerIDs []string, verifiers []VerifierMetadata) ContextMetadata {
	return ContextMetadata{
		SchemaVersion:                     ContextSchemaVersion,
		RunID:                             runID,
		SourceGitRoot:                     repo.Root,
		GitCommonDir:                      repo.CommonDir,
		SourceIsLinkedWorktree:            repo.SourceIsLinkedWorktree,
		SourceBranch:                      repo.Branch,
		SourceHeadCommit:                  repo.HeadCommit,
		SourceInvocationPath:              repo.InvocationPath,
		SourceInvocationRelPath:           repo.InvocationRelPath,
		SourceClean:                       repo.SourceClean,
		SourceDirtyCount:                  repo.SourceDirtyCount,
		SourceDirtyEntries:                append([]SourceStatusEntry(nil), repo.SourceDirtyEntries...),
		SourceHasGitmodules:               repo.SourceHasGitmodules,
		SourceGitlinkCount:                repo.SourceGitlinkCount,
		SourceGitlinkEntries:              append([]GitlinkEntry(nil), repo.SourceGitlinkEntries...),
		BaseRef:                           repo.BaseRef,
		BaseCommit:                        repo.BaseCommit,
		WorktreeParentPath:                parent.Path,
		WorktreeParentInsideSource:        parent.InsideSource,
		WorktreeParentInsideIgnoredSource: parent.InsideIgnoredSource,
		WorktreeParentFallbackUsed:        parent.FallbackUsed,
		ProviderIDs:                       append([]string(nil), providerIDs...),
		Verifiers:                         append([]VerifierMetadata(nil), verifiers...),
		CreatedAt:                         time.Now().UTC().Truncate(time.Second).Format(time.RFC3339),
	}
}

func gitOutput(ctx context.Context, dir string, args ...string) (string, error) {
	data, err := gitOutputRaw(ctx, dir, args...)
	return string(data), err
}

func gitOutputRaw(ctx context.Context, dir string, args ...string) ([]byte, error) {
	argv := append([]string{"-C", dir}, args...)
	cmd := exec.CommandContext(ctx, "git", argv...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		message := strings.TrimSpace(stderr.String())
		if message == "" {
			message = err.Error()
		}
		return nil, fmt.Errorf("git %s: %s", strings.Join(args, " "), message)
	}
	return stdout.Bytes(), nil
}

func requireWorktreeRoot(ctx context.Context, path string) error {
	root, err := gitOutput(ctx, path, "rev-parse", "--show-toplevel")
	if err != nil {
		return err
	}
	expected, err := canonicalPath(path)
	if err != nil {
		return err
	}
	actual, err := canonicalPath(strings.TrimSpace(root))
	if err != nil {
		return err
	}
	if expected != actual {
		return fmt.Errorf("worktree path must be the git worktree root: got %s, root is %s", expected, actual)
	}
	return nil
}

func canonicalPath(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	evaluated, err := filepath.EvalSymlinks(abs)
	if err == nil {
		abs = evaluated
	}
	return filepath.Clean(abs), nil
}

func absGitPath(root string, path string) string {
	path = strings.TrimSpace(path)
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	abs, err := filepath.Abs(filepath.Join(root, path))
	if err != nil {
		return filepath.Clean(filepath.Join(root, path))
	}
	return filepath.Clean(abs)
}

func validateBaseRefSyntax(ref string) error {
	if strings.ContainsRune(ref, '\x00') {
		return fmt.Errorf("base_ref must not contain NUL bytes")
	}
	if strings.ContainsAny(ref, "\r\n\t") {
		return fmt.Errorf("base_ref must not contain control whitespace")
	}
	if strings.ContainsAny(ref, " \t\r\n") {
		return fmt.Errorf("base_ref must not contain whitespace")
	}
	if strings.HasPrefix(ref, "-") {
		return fmt.Errorf("base_ref must not start with '-'")
	}
	for _, disallowed := range []string{"..", ":", "^@", "^!", "@{"} {
		if strings.Contains(ref, disallowed) {
			return fmt.Errorf("base_ref must be a single commit-ish, not a range or path expression")
		}
	}
	return nil
}
