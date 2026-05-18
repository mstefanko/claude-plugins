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
	ContextSchemaVersion = 1
	lockFileName         = "bakeoff-build.lock"
)

type Repository struct {
	Root                   string `json:"source_git_root"`
	CommonDir              string `json:"git_common_dir"`
	SourceIsLinkedWorktree bool   `json:"source_is_linked_worktree"`
	Branch                 string `json:"source_branch"`
	HeadCommit             string `json:"source_head_commit"`
	SourceClean            bool   `json:"source_clean"`
	BaseRef                string `json:"base_ref"`
	BaseCommit             string `json:"base_commit"`
}

type WorktreeParent struct {
	Path                string `json:"worktree_parent_path"`
	InsideSource        bool   `json:"worktree_parent_inside_source"`
	InsideIgnoredSource bool   `json:"worktree_parent_inside_ignored_source"`
	FallbackUsed        bool   `json:"worktree_parent_fallback_used"`
}

type ContextMetadata struct {
	SchemaVersion                     int                `json:"schema_version"`
	RunID                             string             `json:"run_id"`
	SourceGitRoot                     string             `json:"source_git_root"`
	GitCommonDir                      string             `json:"git_common_dir"`
	SourceIsLinkedWorktree            bool               `json:"source_is_linked_worktree"`
	SourceBranch                      string             `json:"source_branch"`
	SourceHeadCommit                  string             `json:"source_head_commit"`
	SourceClean                       bool               `json:"source_clean"`
	BaseRef                           string             `json:"base_ref"`
	BaseCommit                        string             `json:"base_commit"`
	WorktreeParentPath                string             `json:"worktree_parent_path"`
	WorktreeParentInsideSource        bool               `json:"worktree_parent_inside_source"`
	WorktreeParentInsideIgnoredSource bool               `json:"worktree_parent_inside_ignored_source"`
	WorktreeParentFallbackUsed        bool               `json:"worktree_parent_fallback_used"`
	BaselineWorktreePath              string             `json:"baseline_worktree_path,omitempty"`
	BaselineCleanupStatus             string             `json:"baseline_cleanup_status,omitempty"`
	ProviderIDs                       []string           `json:"provider_ids"`
	Verifiers                         []VerifierMetadata `json:"verifiers"`
	CreatedAt                         string             `json:"created_at"`
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
	PatchBytes               int           `json:"patch_bytes"`
	PatchOverCap             bool          `json:"patch_over_cap"`
	GitlinkChangeRejected    bool          `json:"gitlink_change_rejected"`
	PatchPath                string        `json:"patch_path,omitempty"`
	DiffstatPath             string        `json:"diffstat_path,omitempty"`
	ChangedFilesPath         string        `json:"changed_files_path,omitempty"`
}

type ChangedFile struct {
	Status string `json:"status"`
	Path   string `json:"path"`
}

type Lock struct {
	Path string
	file *os.File
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
	if err := RequireCleanSource(ctx, root); err != nil {
		return Repository{}, err
	}
	if err := RejectSubmodules(ctx, root); err != nil {
		return Repository{}, err
	}
	return Repository{
		Root:                   root,
		CommonDir:              commonDir,
		SourceIsLinkedWorktree: filepath.Clean(gitDir) != filepath.Clean(commonDir),
		Branch:                 strings.TrimSpace(branch),
		HeadCommit:             strings.TrimSpace(head),
		SourceClean:            true,
		BaseRef:                baseRef,
		BaseCommit:             strings.TrimSpace(baseCommit),
	}, nil
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
	if opts.OutputDir != "" {
		if err := os.MkdirAll(opts.OutputDir, 0o755); err != nil {
			return CaptureResult{}, err
		}
		result.ChangedFilesPath = filepath.Join(opts.OutputDir, "changed-files.txt")
		result.DiffstatPath = filepath.Join(opts.OutputDir, "diffstat.txt")
		result.PatchPath = filepath.Join(opts.OutputDir, "diff.patch")
		if err := workorder.WriteTextAtomic(result.ChangedFilesPath, nameStatus); err != nil {
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
	for {
		file, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
		if err == nil {
			_, _ = fmt.Fprintf(file, "pid=%d\ncreated_at=%s\n", os.Getpid(), time.Now().UTC().Format(time.RFC3339))
			return &Lock{Path: lockPath, file: file}, nil
		}
		if !os.IsExist(err) {
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

func removeStaleLock(path string) bool {
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	pid, ok := parseLockPID(string(data))
	if !ok || pid == os.Getpid() {
		return false
	}
	alive, known := processAlive(pid)
	if !known || alive {
		return false
	}
	return os.Remove(path) == nil
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
		SourceClean:                       repo.SourceClean,
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
