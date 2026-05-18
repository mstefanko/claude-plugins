package buildcmd

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildworkspace"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func cleanupPatchIntegrityWorktree(ctx context.Context, repo buildworkspace.Repository, path string, created bool) {
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
	defer cancel()
	if created {
		_ = withRepoLock(cleanupCtx, repo, buildCleanupLockTimeout, func() error {
			result := buildworkspace.CleanupWorktree(cleanupCtx, repo, path, false)
			if result.Error != "" {
				return errors.New(result.Error)
			}
			return nil
		})
		return
	}
	_ = os.RemoveAll(path)
}

func workspaceMetadata(repo buildworkspace.Repository, participant workorder.Participant, worktreePath string, providerCWD string, cleanup buildworkspace.CleanupResult, capture *buildworkspace.CaptureResult) buildworkspace.WorkspaceMetadata {
	workspace := buildworkspace.WorkspaceMetadata{
		GitRoot:          repo.Root,
		BaseRef:          repo.BaseRef,
		BaseCommit:       repo.BaseCommit,
		WorktreePath:     worktreePath,
		ProviderCWD:      providerCWD,
		WorktreeRetained: cleanup.Retained,
		WorktreeRemoved:  cleanup.Status == "removed",
		CleanupStatus:    cleanup.Status,
		ProviderID:       participant.ID,
		ProviderBackend:  participant.Backend,
		ProviderModel:    participant.Model,
		ProviderEffort:   participant.Effort,
	}
	if capture != nil {
		workspace.ProviderHead = capture.ProviderHead
		workspace.ProviderHeadIsBase = capture.ProviderHeadIsBase
		workspace.ProviderCommittedChanges = capture.ProviderCommittedChanges
	}
	return workspace
}

func cleanupWorktree(ctx context.Context, repo buildworkspace.Repository, path string, keep bool) (buildworkspace.CleanupResult, error) {
	var result buildworkspace.CleanupResult
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
	defer cancel()
	err := withRepoLock(cleanupCtx, repo, buildCleanupLockTimeout, func() error {
		result = buildworkspace.CleanupWorktree(cleanupCtx, repo, path, keep)
		if result.Status == "failed" {
			return errors.New(result.Error)
		}
		return nil
	})
	return result, err
}

func forceRemoveRunDir(ctx context.Context, repo buildworkspace.Repository, runDir string) error {
	worktreeParent := filepath.Join(runDir, "worktrees")
	entries, err := os.ReadDir(worktreeParent)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		result := buildworkspace.CleanupWorktree(ctx, repo, filepath.Join(worktreeParent, entry.Name()), false)
		if result.Status == "failed" {
			return errors.New(result.Error)
		}
	}
	return os.RemoveAll(runDir)
}

func withRepoLock(ctx context.Context, repo buildworkspace.Repository, timeout time.Duration, fn func() error) error {
	lock, err := buildworkspace.AcquireLock(ctx, repo.CommonDir, timeout)
	if err != nil {
		return err
	}
	err = fn()
	if releaseErr := lock.Release(); err == nil {
		err = releaseErr
	}
	return err
}
