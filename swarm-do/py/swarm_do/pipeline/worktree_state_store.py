"""Thin owner-facing wrapper for run execution worktree state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from . import execution_worktree as _execution_worktree


ArtifactCopySpec = _execution_worktree.ArtifactCopySpec
CommitRecord = _execution_worktree.CommitRecord
ManifestDriftClassification = _execution_worktree.ManifestDriftClassification
ResolvedExecutionWorktree = _execution_worktree.ResolvedExecutionWorktree
RunExecutionWorktree = _execution_worktree.RunExecutionWorktree
RunExecutionWorktreeAdoptionBlocked = _execution_worktree.RunExecutionWorktreeAdoptionBlocked
RunExecutionWorktreeError = _execution_worktree.RunExecutionWorktreeError
RunExecutionWorktreeRebuildRequired = _execution_worktree.RunExecutionWorktreeRebuildRequired


def execution_branch_name(run_id: str) -> str:
    return _execution_worktree.execution_branch_name(run_id)


def integration_branch_name(run_id: str) -> str:
    return _execution_worktree.integration_branch_name(run_id)


def unit_execution_branch_name(run_id: str, phase_id: str, unit_id: str) -> str:
    return _execution_worktree.unit_execution_branch_name(run_id, phase_id, unit_id)


def unit_execution_worktree_root(data_dir: Path, run_id: str, phase_id: str, unit_id: str) -> Path:
    return _execution_worktree.unit_execution_worktree_root(data_dir, run_id, phase_id, unit_id)


def resolve_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> ResolvedExecutionWorktree:
    return _execution_worktree.resolve_run_execution_worktree(
        run_id,
        source_project_root=source_project_root,
        data_dir=data_dir,
        prepared_plan=prepared_plan,
        sensitive_prefixes=sensitive_prefixes,
    )


def materialize_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> RunExecutionWorktree:
    return _execution_worktree.materialize_run_execution_worktree(
        run_id,
        source_project_root=source_project_root,
        data_dir=data_dir,
        prepared_plan=prepared_plan,
        sensitive_prefixes=sensitive_prefixes,
    )


def commit_stage_artifacts(
    resolved: RunExecutionWorktree | ResolvedExecutionWorktree | Mapping[str, Any],
    *,
    allowed_files: Iterable[str],
    run_artifact_excludes: Iterable[str],
    commit_subject: str,
    writer_summary: str,
    stage_id: str,
) -> CommitRecord:
    return _execution_worktree.commit_stage_artifacts(
        resolved,
        allowed_files=allowed_files,
        run_artifact_excludes=run_artifact_excludes,
        commit_subject=commit_subject,
        writer_summary=writer_summary,
        stage_id=stage_id,
    )


def adopt_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    return _execution_worktree.adopt_run_worktree(run_id, data_dir=data_dir, apply=apply)


def integrate_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    return _execution_worktree.integrate_run_worktree(run_id, data_dir=data_dir, apply=apply)


class JsonWorktreeStateStore:
    """Path-bound adapter over the existing execution-worktree owner module."""

    def __init__(
        self,
        *,
        data_dir: Path,
        sensitive_prefixes: Iterable[str] = (),
    ) -> None:
        self.data_dir = Path(data_dir)
        self.sensitive_prefixes = tuple(str(item) for item in sensitive_prefixes)

    def resolve(
        self,
        run_id: str,
        *,
        source_project_root: Path,
        prepared_plan: Mapping[str, Any],
    ) -> ResolvedExecutionWorktree:
        return resolve_run_execution_worktree(
            run_id,
            source_project_root=source_project_root,
            data_dir=self.data_dir,
            prepared_plan=prepared_plan,
            sensitive_prefixes=self.sensitive_prefixes,
        )

    def materialize(
        self,
        run_id: str,
        *,
        source_project_root: Path,
        prepared_plan: Mapping[str, Any],
    ) -> RunExecutionWorktree:
        return materialize_run_execution_worktree(
            run_id,
            source_project_root=source_project_root,
            data_dir=self.data_dir,
            prepared_plan=prepared_plan,
            sensitive_prefixes=self.sensitive_prefixes,
        )

    def commit_stage_artifacts(
        self,
        resolved: RunExecutionWorktree | ResolvedExecutionWorktree | Mapping[str, Any],
        *,
        allowed_files: Iterable[str],
        run_artifact_excludes: Iterable[str],
        commit_subject: str,
        writer_summary: str,
        stage_id: str,
    ) -> CommitRecord:
        return commit_stage_artifacts(
            resolved,
            allowed_files=allowed_files,
            run_artifact_excludes=run_artifact_excludes,
            commit_subject=commit_subject,
            writer_summary=writer_summary,
            stage_id=stage_id,
        )

    def adopt(self, run_id: str, *, apply: bool = False) -> dict[str, Any]:
        return adopt_run_worktree(run_id, data_dir=self.data_dir, apply=apply)

    def integrate(self, run_id: str, *, apply: bool = False) -> dict[str, Any]:
        return integrate_run_worktree(run_id, data_dir=self.data_dir, apply=apply)


__all__ = [
    "ArtifactCopySpec",
    "CommitRecord",
    "JsonWorktreeStateStore",
    "ManifestDriftClassification",
    "ResolvedExecutionWorktree",
    "RunExecutionWorktree",
    "RunExecutionWorktreeAdoptionBlocked",
    "RunExecutionWorktreeError",
    "RunExecutionWorktreeRebuildRequired",
    "adopt_run_worktree",
    "commit_stage_artifacts",
    "execution_branch_name",
    "integrate_run_worktree",
    "integration_branch_name",
    "materialize_run_execution_worktree",
    "resolve_run_execution_worktree",
    "unit_execution_branch_name",
    "unit_execution_worktree_root",
]
