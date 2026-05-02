"""Run-scoped execution worktrees for launcher hardening."""

from __future__ import annotations

import hashlib
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX-only lock primitive.
    fcntl = None  # type: ignore[assignment]

from .paths import REPO_ROOT
from .post_writer import worktree_diff_summary
from .run_state import _atomic_json_write, append_run_event, utc_now, validate_run_event
from .unit_sessions import (
    find_unit_session,
    load_unit_sessions,
    locked_unit_sessions,
    replace_unit_session,
    unit_session_template,
    unit_sessions_path,
    write_unit_sessions,
)


class RunExecutionWorktreeError(RuntimeError):
    """Raised when a run execution worktree cannot be prepared or adopted."""


class RunExecutionWorktreeAdoptionBlocked(RunExecutionWorktreeError):
    """Raised when copyback is explicitly blocked by adoption safety checks."""

    def __init__(self, message: str, payload: Mapping[str, Any]):
        super().__init__(message)
        self.payload = dict(payload)


class RunExecutionWorktreeRebuildRequired(RunExecutionWorktreeError):
    """Raised when base drift exists but automatic rebuild would discard work."""

    def __init__(self, message: str, payload: Mapping[str, Any]):
        super().__init__(message)
        self.payload = dict(payload)
        self.unadopted_commits = tuple(str(item) for item in self.payload.get("unadopted_commits") or [])


@dataclass(frozen=True)
class CommitRecord:
    commit_sha: str | None
    paths_committed: tuple[str, ...]
    worktree_diff: Mapping[str, list[str]]
    status: str = "committed"


RUN_EXECUTION_WORKTREE_SCHEMA_PATH = REPO_ROOT / "schemas" / "run_execution_worktree.schema.json"
_RUN_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class ManifestDriftClassification:
    kind: str
    mismatched: tuple[str, ...] = ()
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CopiedArtifact:
    source_path: Path
    destination_path: Path
    relative_path: str
    source_sha256: str
    destination_sha256: str
    kind: str
    transformed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "destination_path": str(self.destination_path),
            "relative_path": self.relative_path,
            "source_sha256": self.source_sha256,
            "destination_sha256": self.destination_sha256,
            "kind": self.kind,
            "transformed": self.transformed,
        }


@dataclass(frozen=True)
class RunExecutionWorktree:
    run_id: str
    source_git_root: Path
    source_project_root: Path
    safe_git_root: Path
    safe_project_root: Path
    project_subdir: str
    branch: str
    base_sha: str
    base_ref: str
    manifest_path: Path
    copied_artifacts: tuple[CopiedArtifact, ...]
    adoption_state: str
    source_dirty_ignored_paths: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source_git_top_level": str(self.source_git_root),
            "source_project_root": str(self.source_project_root),
            "safe_git_worktree_root": str(self.safe_git_root),
            "safe_project_root": str(self.safe_project_root),
            "project_subdir": self.project_subdir,
            "run_execution_branch": self.branch,
            "git_base_sha": self.base_sha,
            "git_base_ref": self.base_ref,
            "run_worktree_manifest_path": str(self.manifest_path),
            "copied_ignored_artifacts": [artifact.to_dict() for artifact in self.copied_artifacts],
            "source_dirty_ignored_paths": list(self.source_dirty_ignored_paths),
            "adoption_state": self.adoption_state,
        }


@dataclass(frozen=True)
class ArtifactCopySpec:
    source_path: Path
    relative_path: Path
    kind: str
    required: bool = True
    transform: Callable[[bytes, "ResolvedExecutionWorktree"], bytes] | None = None


@dataclass(frozen=True)
class ResolvedExecutionWorktree:
    run_id: str
    source_git_root: Path
    source_project_root: Path
    safe_git_root: Path
    safe_project_root: Path
    project_subdir: str
    branch: str
    base_sha: str
    base_ref: str
    manifest_path: Path
    copy_specs: tuple[ArtifactCopySpec, ...]
    source_dirty_block_patterns: tuple[str, ...] = ()


def execution_branch_name(run_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/execution"


def integration_branch_name(run_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/integration"


def unit_execution_branch_name(run_id: str, phase_id: str, unit_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/{_safe_ref_segment(phase_id)}/{_safe_ref_segment(unit_id)}"


def unit_execution_worktree_root(data_dir: Path, run_id: str, phase_id: str, unit_id: str) -> Path:
    return (
        Path(data_dir)
        / "worktrees"
        / run_id
        / "units"
        / _safe_ref_segment(phase_id)
        / _safe_ref_segment(unit_id)
        / "repo"
    )


def resolve_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> ResolvedExecutionWorktree:
    _assert_valid_run_id(run_id)
    source_project = Path(source_project_root).expanduser().resolve(strict=False)
    source_git = Path(_git_stdout(source_project, "rev-parse", "--show-toplevel")).resolve(strict=False)
    prefix = _git_stdout(source_project, "rev-parse", "--show-prefix").strip()
    project_subdir = prefix.strip("/")
    expected_project = (source_git / project_subdir).resolve(strict=False) if project_subdir else source_git
    if expected_project != source_project:
        raise RunExecutionWorktreeError(
            f"git prefix maps to {expected_project}, expected source project root {source_project}"
        )
    _assert_supported_git_checkout(source_project)
    control_run_root = Path(data_dir).expanduser() / "worktrees" / run_id
    checkout_run_root = _safe_run_worktree_root(data_dir, run_id, sensitive_prefixes=sensitive_prefixes)
    safe_git = (checkout_run_root / "repo").resolve(strict=False)
    safe_project = (safe_git / project_subdir).resolve(strict=False) if project_subdir else safe_git
    manifest_path = control_run_root / "manifest.json"
    _assert_not_sensitive(safe_git, sensitive_prefixes=sensitive_prefixes)
    _assert_not_sensitive(safe_project, sensitive_prefixes=sensitive_prefixes)
    base_ref = str(prepared_plan.get("git_base_ref") or "HEAD")
    base_sha = _prepared_base_sha(source_project, prepared_plan, base_ref=base_ref)
    copy_specs = _artifact_copy_specs(
        run_id,
        data_dir=Path(data_dir),
        source_project_root=source_project,
        prepared_plan=prepared_plan,
    )
    return ResolvedExecutionWorktree(
        run_id=run_id,
        source_git_root=source_git,
        source_project_root=source_project,
        safe_git_root=safe_git,
        safe_project_root=safe_project,
        project_subdir=project_subdir,
        branch=execution_branch_name(run_id),
        base_sha=base_sha,
        base_ref=base_ref,
        manifest_path=manifest_path,
        copy_specs=copy_specs,
        source_dirty_block_patterns=_source_dirty_block_patterns(prepared_plan),
    )


def materialize_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> RunExecutionWorktree:
    resolved = resolve_run_execution_worktree(
        run_id,
        source_project_root=source_project_root,
        data_dir=data_dir,
        prepared_plan=prepared_plan,
        sensitive_prefixes=sensitive_prefixes,
    )
    source_dirty_ignored_paths = _assert_clean_source_project(resolved)
    existing_manifest = _load_manifest(resolved.manifest_path)
    if existing_manifest is not None:
        classification = _classify_existing_manifest(resolved, existing_manifest)
        if classification.kind == "identity_mismatch":
            raise RunExecutionWorktreeError(
                "existing run worktree manifest does not match this run: "
                + ", ".join(classification.mismatched)
            )
        if classification.kind == "base_drift_safe":
            _rebuild_run_worktree_for_base_drift(
                resolved,
                existing_manifest,
                data_dir=Path(data_dir),
                details=dict(classification.payload or {}),
            )
            existing_manifest = None
        elif classification.kind == "base_drift_unsafe":
            payload = dict(classification.payload or {})
            raise RunExecutionWorktreeRebuildRequired(
                "run execution worktree requires explicit rebuild: " + str(payload.get("reason") or "base_drift"),
                payload,
            )
        elif classification.kind != "match":
            raise RunExecutionWorktreeError(f"unknown worktree manifest classification: {classification.kind}")
        if existing_manifest is not None and not resolved.safe_git_root.exists():
            raise RunExecutionWorktreeError(f"run worktree manifest exists but checkout is missing: {resolved.safe_git_root}")
    if existing_manifest is None:
        _create_run_worktree(resolved)
    copied = _copy_required_artifacts(resolved)
    manifest = _manifest_payload(resolved, copied, previous=existing_manifest)
    _write_manifest(resolved.manifest_path, manifest)
    return RunExecutionWorktree(
        run_id=run_id,
        source_git_root=resolved.source_git_root,
        source_project_root=resolved.source_project_root,
        safe_git_root=resolved.safe_git_root,
        safe_project_root=resolved.safe_project_root,
        project_subdir=resolved.project_subdir,
        branch=resolved.branch,
        base_sha=resolved.base_sha,
        base_ref=resolved.base_ref,
        manifest_path=resolved.manifest_path,
        copied_artifacts=tuple(copied),
        adoption_state=str(manifest.get("adoption_state") or "unadopted"),
        source_dirty_ignored_paths=tuple(source_dirty_ignored_paths),
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
    """Commit the current stage's dirty artifacts with explicit path staging."""

    safe_git_root = _resolved_path(resolved, "safe_git_root", "safe_git_worktree_root")
    project_subdir = _resolved_string(resolved, "project_subdir")
    base_sha = _resolved_string(resolved, "base_sha", "git_base_sha")
    summary = worktree_diff_summary(
        safe_git_root,
        base_sha=base_sha,
        project_subdir=project_subdir,
        extra_excludes=tuple(run_artifact_excludes),
    )
    dirty_paths = sorted({path for key in ("staged", "unstaged", "untracked") for path in summary.get(key, [])})
    if not dirty_paths:
        return CommitRecord(commit_sha=None, paths_committed=(), worktree_diff=summary, status="no_changes")
    allowed = tuple(str(item) for item in allowed_files if isinstance(item, str) and item)
    outside = [
        path
        for path in dirty_paths
        if not _path_allowed(_project_relative_from_git(path, project_subdir=project_subdir), allowed)
    ]
    if outside:
        raise RunExecutionWorktreeError("phase_artifact_outside_allowed_files: " + ", ".join(outside))
    _run_git_stage(safe_git_root, dirty_paths)
    subject = _commit_subject(stage_id, commit_subject)
    result = _run_git_with_env(
        safe_git_root,
        "commit",
        "--no-verify",
        "-m",
        subject,
        "-m",
        writer_summary or "stage artifacts committed by swarm-do controller",
        check=False,
    )
    if result.returncode != 0:
        # Nothing staged is a valid no-op race; any other commit failure should
        # route the stage through retry.
        if "nothing to commit" in _combined_output(result).lower():
            return CommitRecord(commit_sha=None, paths_committed=(), worktree_diff=summary, status="no_changes")
        raise RunExecutionWorktreeError("adoptable_artifacts_uncommittable: " + (_combined_output(result) or "git commit failed"))
    commit_sha = _git_stdout(safe_git_root, "rev-parse", "HEAD")
    post_summary = worktree_diff_summary(
        safe_git_root,
        base_sha=base_sha,
        project_subdir=project_subdir,
        extra_excludes=tuple(run_artifact_excludes),
    )
    return CommitRecord(commit_sha=commit_sha, paths_committed=tuple(dirty_paths), worktree_diff=post_summary)


def adopt_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    adoption_source = _adoption_source(manifest)
    safe_project = adoption_source["project_root"]
    source_project = Path(str(manifest["source_project_root"]))
    copied_rels = _copied_artifact_rels(manifest)
    changes = _adoption_changes(manifest, adoption_source=adoption_source)
    operations, blocked = _copyback_plan(
        manifest,
        source_project=safe_project,
        destination_project=source_project,
        changes=changes,
        copied_rels=copied_rels,
    )
    prepared = _read_prepared_artifact(run_id, data_dir=Path(data_dir))
    scope_check = build_run_worktree_scope_check(
        prepared,
        changed_files=changes,
        blocked_paths=blocked,
        adoption_operations=operations,
        source_project_root=source_project,
        safe_project_root=safe_project,
    )
    blocked = _merge_blocked_paths(blocked, scope_check.get("blocked_paths"))
    scope_check_path = Path(data_dir) / "worktrees" / run_id / "scope-check.json"
    payload = {
        "run_id": run_id,
        "applied": False,
        "manifest_path": str(manifest_path),
        "source_project_root": str(source_project),
        "safe_project_root": str(safe_project),
        "adoption_source": adoption_source["kind"],
        "run_execution_branch": manifest.get("branch"),
        "integration_branch": adoption_source.get("integration_branch"),
        "base_sha": manifest.get("base_sha"),
        "adoption_state": manifest.get("adoption_state"),
        "changed_files": [change["path"] for change in changes],
        "blocked_paths": blocked,
        "scope_check": scope_check,
        "scope_check_path": str(scope_check_path),
        "copyback_operations": operations,
        "applied_operations": [],
        "apply_command": f"bin/swarm worktrees adopt-run {run_id} --apply",
    }
    if apply and blocked:
        raise RunExecutionWorktreeAdoptionBlocked(
            "adoption has blocked paths: " + ", ".join(f"{item['path']} ({item['reason']})" for item in blocked),
            payload,
        )
    applied_operations: list[dict[str, Any]] = []
    if apply:
        _write_scope_check(scope_check_path, scope_check)
        for operation in operations:
            src = Path(str(operation["source_path"]))
            dst = Path(str(operation["destination_path"]))
            if operation["action"] == "delete":
                if dst.is_dir():
                    raise RunExecutionWorktreeError(f"refusing to delete directory during run adoption: {dst}")
                if dst.exists():
                    dst.unlink()
            else:
                if not src.is_file():
                    raise RunExecutionWorktreeError(f"cannot copy non-file changed path: {src}")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            applied_operations.append(operation)
        manifest = dict(manifest)
        manifest["adoption_state"] = "adopted" if operations else "complete_no_changes"
        if operations:
            manifest["adopted_at"] = utc_now()
        else:
            manifest.setdefault("adopted_at", None)
        manifest["scope_check_path"] = str(scope_check_path)
        manifest["last_used_at"] = utc_now()
        _write_manifest(manifest_path, manifest)
        payload["applied"] = True
        payload["adoption_state"] = manifest["adoption_state"]
        payload["applied_operations"] = applied_operations
    return payload


def integrate_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    base = Path(data_dir)
    manifest_path = base / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    prepared = _read_prepared_artifact(run_id, data_dir=base)
    source_git = Path(str(manifest["source_git_root"]))
    source_project = Path(str(manifest["source_project_root"]))
    execution_project = Path(str(manifest["safe_project_root"]))
    project_subdir = str(manifest.get("project_subdir") or "")
    execution_branch = str(manifest["branch"])
    integration_branch = integration_branch_name(run_id)
    integration_git = base / "worktrees" / run_id / "integration" / "repo"
    integration_project = (integration_git / project_subdir).resolve(strict=False) if project_subdir else integration_git
    integration_manifest_path = base / "worktrees" / run_id / "integration" / "manifest.json"
    conflict_manifest_path = base / "worktrees" / run_id / "conflict.json"
    branch_changed = _execution_branch_changes(manifest)
    dirty_changed = _filter_source_overlay_changes(
        _status_changes(execution_project, project_subdir=project_subdir),
        manifest,
        root=execution_project,
    )
    changed = _dedupe_changes([*branch_changed, *dirty_changed])
    copied_rels = _copied_artifact_rels(manifest)
    operations, blocked = _copyback_plan(
        manifest,
        source_project=integration_project,
        destination_project=source_project,
        changes=changed,
        copied_rels=copied_rels,
    )
    scope_check = build_run_worktree_scope_check(
        prepared,
        changed_files=changed,
        blocked_paths=blocked,
        adoption_operations=operations,
        source_project_root=source_project,
        safe_project_root=integration_project,
    )
    blocked = _merge_blocked_paths(blocked, scope_check.get("blocked_paths"))
    validation_commands = _validation_commands(prepared)
    merge_command = [
        "git",
        "-C",
        str(integration_git),
        "merge",
        "--no-ff",
        execution_branch,
        "-m",
        f"Merge run execution {run_id}",
    ]
    payload: dict[str, Any] = {
        "run_id": run_id,
        "applied": False,
        "status": "dry_run",
        "manifest_path": str(manifest_path),
        "source_git_root": str(source_git),
        "source_project_root": str(source_project),
        "source_branch": _current_branch(source_git),
        "execution_branch": execution_branch,
        "execution_project_root": str(execution_project),
        "integration_branch": integration_branch,
        "integration_git_worktree_root": str(integration_git),
        "integration_project_root": str(integration_project),
        "base_sha": manifest.get("base_sha"),
        "changed_files": [change["path"] for change in changed],
        "execution_worktree_dirty": [change["path"] for change in dirty_changed],
        "scope_check": scope_check,
        "blocked_paths": blocked,
        "validation_commands": validation_commands,
        "validation_results": [],
        "predicted_merge_command": " ".join(merge_command),
        "copyback_operations": operations,
        "apply_command": f"bin/swarm worktrees integrate-run {run_id} --apply",
    }
    if not apply:
        return payload
    if dirty_changed:
        dirty_blocks = [{"path": change["path"], "reason": "execution_worktree_dirty"} for change in dirty_changed]
        payload["blocked_paths"] = _merge_blocked_paths(blocked, dirty_blocks)
        payload["status"] = "blocked"
        raise RunExecutionWorktreeAdoptionBlocked(
            "integration requires committed execution-branch changes; dirty paths: "
            + ", ".join(str(change["path"]) for change in dirty_changed),
            payload,
        )

    _ensure_integration_worktree(
        source_git,
        integration_git=integration_git,
        integration_branch=integration_branch,
        base_sha=str(manifest["base_sha"]),
    )
    merge_result = _run_git(
        integration_git,
        "merge",
        "--no-ff",
        execution_branch,
        "-m",
        f"Merge run execution {run_id}",
        check=False,
    )
    conflicted = _conflicted_files(integration_git)
    if merge_result.returncode != 0 or conflicted:
        conflict = _write_integration_conflict_manifest(
            conflict_manifest_path,
            run_id=run_id,
            source_git=source_git,
            integration_git=integration_git,
            execution_branch=execution_branch,
            integration_branch=integration_branch,
            base_sha=str(manifest["base_sha"]),
            merge_command=merge_command,
            merge_result=merge_result,
            conflicted_files=conflicted,
        )
        updated = dict(manifest)
        updated["adoption_state"] = "conflicted"
        updated["conflict_manifest_path"] = str(conflict_manifest_path)
        updated["last_used_at"] = utc_now()
        _write_manifest(manifest_path, updated)
        _append_worktree_conflict_event(base, run_id=run_id, details=conflict)
        payload.update(
            {
                "applied": True,
                "status": "conflicted",
                "adoption_state": "conflicted",
                "conflict_manifest_path": str(conflict_manifest_path),
                "conflicted_files": conflicted,
                "merge_stdout": merge_result.stdout,
                "merge_stderr": merge_result.stderr,
            }
        )
        return payload

    validation_results = _run_integration_validations(prepared, integration_project)
    integration_manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "source_git_root": str(source_git),
        "source_project_root": str(source_project),
        "execution_branch": execution_branch,
        "integration_branch": integration_branch,
        "integration_git_worktree_root": str(integration_git),
        "integration_project_root": str(integration_project),
        "base_sha": manifest.get("base_sha"),
        "head_sha": _git_stdout(integration_git, "rev-parse", "HEAD"),
        "merge_command": merge_command,
        "changed_files": [change["path"] for change in changed],
        "scope_check": scope_check,
        "blocked_paths": blocked,
        "validation_results": validation_results,
        "created_at": utc_now(),
    }
    _atomic_json_write(integration_manifest_path, integration_manifest)
    updated = dict(manifest)
    updated["integration_manifest_path"] = str(integration_manifest_path)
    updated["conflict_manifest_path"] = None
    updated["last_used_at"] = utc_now()
    _write_manifest(manifest_path, updated)
    payload.update(
        {
            "applied": True,
            "status": "integrated",
            "integration_manifest_path": str(integration_manifest_path),
            "integration_head_sha": integration_manifest["head_sha"],
            "validation_results": validation_results,
        }
    )
    return payload


def initialize_unit_sessions(run_id: str, *, data_dir: Path) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    base = Path(data_dir)
    manifest_path = base / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    prepared = _read_prepared_artifact(run_id, data_dir=base)
    return _ensure_unit_sessions(run_id, data_dir=base, manifest=manifest, prepared=prepared)


def materialize_unit_execution_worktree(
    run_id: str,
    phase_id: str,
    unit_id: str,
    *,
    data_dir: Path,
    base: str = "execution",
) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    data = Path(data_dir)
    manifest_path = data / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    prepared = _read_prepared_artifact(run_id, data_dir=data)
    source_git = Path(str(manifest["source_git_root"]))
    source_project = Path(str(manifest["source_project_root"]))
    project_subdir = str(manifest.get("project_subdir") or "")
    base_ref = _unit_worktree_base_ref(manifest, base=base)
    base_sha = _git_stdout(source_git, "rev-parse", base_ref)
    branch = unit_execution_branch_name(run_id, phase_id, unit_id)
    unit_git = unit_execution_worktree_root(data, run_id, phase_id, unit_id).resolve(strict=False)
    unit_project = (unit_git / project_subdir).resolve(strict=False) if project_subdir else unit_git

    state = _ensure_unit_sessions(
        run_id,
        data_dir=data,
        manifest=manifest,
        prepared=prepared,
        base_ref=base_ref,
        base_sha=base_sha,
    )
    find_unit_session(state, phase_id, unit_id)
    _ensure_unit_worktree(source_git, unit_git=unit_git, branch=branch, base_ref=base_ref)
    copy_specs = _artifact_copy_specs(
        run_id,
        data_dir=data,
        source_project_root=source_project,
        prepared_plan=prepared,
    )
    resolved = ResolvedExecutionWorktree(
        run_id=run_id,
        source_git_root=source_git,
        source_project_root=source_project,
        safe_git_root=unit_git,
        safe_project_root=unit_project,
        project_subdir=project_subdir,
        branch=branch,
        base_sha=base_sha,
        base_ref=base_ref,
        manifest_path=unit_git.parent / "manifest.json",
        copy_specs=copy_specs,
    )
    copied = _copy_required_artifacts(resolved)
    with locked_unit_sessions(run_id, data_dir=data):
        state = load_unit_sessions(run_id, data_dir=data)
        unit = find_unit_session(state, phase_id, unit_id)
        unit.update(
            {
                "branch": branch,
                "worktree_root": str(unit_git),
                "project_root": str(unit_project),
                "base_sha": base_sha,
                "base_ref": base_ref,
                "updated_at": utc_now(),
            }
        )
        state = write_unit_sessions(
            replace_unit_session(state, phase_id, unit_id, unit),
            data_dir=data,
        )
    return {
        "run_id": run_id,
        "phase_id": phase_id,
        "unit_id": unit_id,
        "branch": branch,
        "worktree_root": str(unit_git),
        "project_root": str(unit_project),
        "base_ref": base_ref,
        "base_sha": base_sha,
        "copied_artifacts": [artifact.to_dict() for artifact in copied],
        "unit_sessions_path": str(unit_sessions_path(run_id, data_dir=data)),
        "unit_sessions_unit_count": len(state.get("units") or []),
    }


def record_unit_post_writer_report(
    run_id: str,
    phase_id: str,
    unit_id: str,
    *,
    data_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    data = Path(data_dir)
    report = _read_json_mapping(Path(report_path)) or {}
    _validate_post_writer_report_binding(report, run_id=run_id, phase_id=phase_id, unit_id=unit_id)
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    gate_status = str(gate.get("status") or "unknown")
    post_writer_status = "passed" if gate_status == "passed" else "failed"
    gate_reasons = [str(item) for item in gate.get("failure_reasons") or [] if isinstance(item, str)]
    with locked_unit_sessions(run_id, data_dir=data):
        state = load_unit_sessions(run_id, data_dir=data)
        unit = find_unit_session(state, phase_id, unit_id)
        report_base_sha = report.get("base_sha")
        if isinstance(report_base_sha, str) and report_base_sha and report_base_sha != unit.get("base_sha"):
            raise RunExecutionWorktreeError(
                f"post-writer report base_sha {report_base_sha} does not match unit base_sha {unit.get('base_sha')}"
            )
        unit_git = Path(str(unit["worktree_root"]))
        unit_head = _rev_parse_or_none(unit_git, "HEAD")
        attempt = max(1, int(unit.get("attempt") or 0))
        recorded_at = utc_now()
        history = [dict(item) for item in unit.get("attempt_history") or [] if isinstance(item, Mapping)]
        history_row = {
            "attempt": attempt,
            "post_writer_report_path": str(Path(report_path)),
            "writer_status": "approved" if post_writer_status == "passed" else "blocked",
            "post_writer_status": post_writer_status,
            "gate_status": gate_status,
            "changed_files": report.get("changed_files") if isinstance(report.get("changed_files"), list) else [],
            "recorded_at": recorded_at,
        }
        if not history or history[-1].get("post_writer_report_path") != history_row["post_writer_report_path"]:
            history.append(history_row)
        unit.update(
            {
                "attempt": attempt,
                "writer_status": "approved" if post_writer_status == "passed" else "blocked",
                "post_writer_status": post_writer_status,
                "post_writer_gate_reasons": gate_reasons,
                "post_writer_report_path": str(Path(report_path)),
                "post_writer_report_sha256": _sha256_file(Path(report_path)),
                "post_writer_unit_head_sha": unit_head,
                "post_writer_base_sha": unit.get("base_sha"),
                "merge_state": _unit_merge_state_after_gates(unit, post_writer_status=post_writer_status),
                "attempt_history": history,
                "updated_at": recorded_at,
                "completed_at": recorded_at if post_writer_status == "passed" else unit.get("completed_at"),
            }
        )
        state = write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)
        return find_unit_session(state, phase_id, unit_id)


def record_unit_spec_review_verdict(
    run_id: str,
    phase_id: str,
    unit_id: str,
    *,
    data_dir: Path,
    verdict: str,
    report_path: Path | None = None,
) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    if verdict not in {"approved", "rejected", "skipped"}:
        raise RunExecutionWorktreeError("spec-review verdict must be approved, rejected, or skipped")
    if verdict in {"approved", "rejected"} and report_path is None:
        raise RunExecutionWorktreeError("approved/rejected spec-review verdicts require a report_path")
    report: Mapping[str, Any] = {}
    if report_path is not None:
        report = _read_json_mapping(Path(report_path)) or {}
        _validate_spec_review_binding(report, run_id=run_id, phase_id=phase_id, unit_id=unit_id)
    data = Path(data_dir)
    with locked_unit_sessions(run_id, data_dir=data):
        state = load_unit_sessions(run_id, data_dir=data)
        unit = find_unit_session(state, phase_id, unit_id)
        unit_git = Path(str(unit["worktree_root"]))
        unit_head = _rev_parse_or_none(unit_git, "HEAD")
        recorded_at = utc_now()
        unit.update(
            {
                "spec_review_status": verdict,
                "spec_review_report_path": str(Path(report_path)) if report_path is not None else None,
                "spec_review_report_sha256": _sha256_file(Path(report_path)) if report_path is not None else None,
                "spec_review_unit_head_sha": unit_head,
                "spec_review_recorded_at": recorded_at,
                "merge_state": _unit_merge_state_after_gates(unit, spec_review_status=verdict),
                "updated_at": recorded_at,
            }
        )
        state = write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)
        return find_unit_session(state, phase_id, unit_id)


def merge_unit_execution_worktree(
    run_id: str,
    phase_id: str,
    unit_id: str,
    *,
    data_dir: Path,
    apply: bool = False,
) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    data = Path(data_dir)
    manifest_path = data / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    source_git = Path(str(manifest["source_git_root"]))
    project_subdir = str(manifest.get("project_subdir") or "")
    integration_branch = integration_branch_name(run_id)
    integration_git = data / "worktrees" / run_id / "integration" / "repo"
    integration_project = (integration_git / project_subdir).resolve(strict=False) if project_subdir else integration_git
    conflict_manifest_path = (
        data
        / "worktrees"
        / run_id
        / "units"
        / _safe_ref_segment(phase_id)
        / _safe_ref_segment(unit_id)
        / "conflict.json"
    )
    state = load_unit_sessions(run_id, data_dir=data)
    unit = find_unit_session(state, phase_id, unit_id)
    unit_branch = str(unit["branch"])
    unit_git = Path(str(unit["worktree_root"]))
    merge_command = [
        "git",
        "-C",
        str(integration_git),
        "merge",
        "--no-ff",
        unit_branch,
        "-m",
        f"Merge work unit {unit_id}",
    ]
    payload: dict[str, Any] = {
        "run_id": run_id,
        "phase_id": phase_id,
        "unit_id": unit_id,
        "applied": False,
        "status": "dry_run",
        "unit_branch": unit_branch,
        "unit_worktree_root": str(unit_git),
        "post_writer_status": unit.get("post_writer_status"),
        "spec_review_status": unit.get("spec_review_status"),
        "merge_state": unit.get("merge_state"),
        "integration_branch": integration_branch,
        "integration_git_worktree_root": str(integration_git),
        "integration_project_root": str(integration_project),
        "predicted_merge_command": " ".join(merge_command),
        "unit_sessions_path": str(unit_sessions_path(run_id, data_dir=data)),
    }
    if not apply:
        return payload

    with locked_unit_sessions(run_id, data_dir=data):
        state = load_unit_sessions(run_id, data_dir=data)
        unit = find_unit_session(state, phase_id, unit_id)
        unit_branch = str(unit["branch"])
        unit_git = Path(str(unit["worktree_root"]))
        blocker = _unit_merge_gate_blocker(unit_git, unit)
        if blocker is not None:
            unit["merge_state"] = "blocked"
            unit["updated_at"] = utc_now()
            write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)
            payload["status"] = "blocked"
            raise RunExecutionWorktreeAdoptionBlocked(blocker, payload)
        unit["merge_state"] = "ready"
        unit["merge_target_branch"] = integration_branch
        unit["updated_at"] = utc_now()
        write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)

    if unit.get("post_writer_status") != "passed":
        payload["status"] = "blocked"
        raise RunExecutionWorktreeAdoptionBlocked(
            f"unit {unit_id} has not passed the post-writer gate",
            payload,
        )
    if _git_status_entries(unit_git, "."):
        payload["status"] = "blocked"
        raise RunExecutionWorktreeAdoptionBlocked(
            f"unit worktree has uncommitted changes: {unit_git}",
            payload,
        )

    with locked_integration_merge(run_id, data_dir=data):
        with locked_unit_sessions(run_id, data_dir=data):
            state = load_unit_sessions(run_id, data_dir=data)
            unit = find_unit_session(state, phase_id, unit_id)
            current_merge_state = str(unit.get("merge_state") or "")
            if current_merge_state != "ready":
                payload.update(
                    {
                        "merge_state": current_merge_state,
                        "unit_session": unit,
                    }
                )
                if current_merge_state == "merged":
                    payload.update({"applied": True, "status": "merged"})
                    if integration_git.exists():
                        payload["integration_head_sha"] = _git_stdout(integration_git, "rev-parse", "HEAD")
                    return payload
                payload["status"] = "blocked"
                raise RunExecutionWorktreeAdoptionBlocked(
                    f"unit {unit_id} merge_state changed before merge: {current_merge_state or 'unknown'}",
                    payload,
                )
            unit_branch = str(unit["branch"])
            unit_git = Path(str(unit["worktree_root"]))
            merge_command = [
                "git",
                "-C",
                str(integration_git),
                "merge",
                "--no-ff",
                unit_branch,
                "-m",
                f"Merge work unit {unit_id}",
            ]
            payload.update(
                {
                    "unit_branch": unit_branch,
                    "unit_worktree_root": str(unit_git),
                    "predicted_merge_command": " ".join(merge_command),
                }
            )
        _ensure_integration_worktree(
            source_git,
            integration_git=integration_git,
            integration_branch=integration_branch,
            base_sha=str(manifest["base_sha"]),
        )
        merge_result = _run_git(
            integration_git,
            "merge",
            "--no-ff",
            unit_branch,
            "-m",
            f"Merge work unit {unit_id}",
            check=False,
        )
    conflicted = _conflicted_files(integration_git)
    if merge_result.returncode != 0 or conflicted:
        conflict = _write_unit_conflict_manifest(
            conflict_manifest_path,
            run_id=run_id,
            phase_id=phase_id,
            unit_id=unit_id,
            source_git=source_git,
            integration_git=integration_git,
            unit_branch=unit_branch,
            integration_branch=integration_branch,
            base_sha=str(manifest["base_sha"]),
            merge_command=merge_command,
            merge_result=merge_result,
            conflicted_files=conflicted,
        )
        with locked_unit_sessions(run_id, data_dir=data):
            state = load_unit_sessions(run_id, data_dir=data)
            unit = find_unit_session(state, phase_id, unit_id)
            unit.update(
                {
                    "merge_state": "conflicted",
                    "merge_target_branch": integration_branch,
                    "conflict_manifest_path": str(conflict_manifest_path),
                    "cleanup_state": "preserved",
                    "updated_at": utc_now(),
                }
            )
            write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)
        _append_unit_worktree_conflict_event(
            data,
            run_id=run_id,
            phase_id=phase_id,
            unit_id=unit_id,
            details=conflict,
        )
        payload.update(
            {
                "applied": True,
                "status": "conflicted",
                "conflict_manifest_path": str(conflict_manifest_path),
                "conflicted_files": conflicted,
                "merge_stdout": merge_result.stdout,
                "merge_stderr": merge_result.stderr,
            }
        )
        return payload

    with locked_unit_sessions(run_id, data_dir=data):
        state = load_unit_sessions(run_id, data_dir=data)
        unit = find_unit_session(state, phase_id, unit_id)
        current_merge_state = str(unit.get("merge_state") or "")
        if current_merge_state != "ready":
            payload.update(
                {
                    "applied": True,
                    "status": "merged" if current_merge_state == "merged" else current_merge_state,
                    "merge_state": current_merge_state,
                    "integration_head_sha": _git_stdout(integration_git, "rev-parse", "HEAD"),
                    "unit_session": unit,
                }
            )
            return payload
        unit.update(
            {
                "merge_state": "merged",
                "merge_target_branch": integration_branch,
                "conflict_manifest_path": None,
                "cleanup_state": "cleanup_eligible",
                "updated_at": utc_now(),
                "completed_at": utc_now(),
            }
        )
        state = write_unit_sessions(replace_unit_session(state, phase_id, unit_id, unit), data_dir=data)
    payload.update(
        {
            "applied": True,
            "status": "merged",
            "integration_head_sha": _git_stdout(integration_git, "rev-parse", "HEAD"),
            "unit_session": find_unit_session(state, phase_id, unit_id),
        }
    )
    return payload


def cleanup_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    adoption_state = str(manifest.get("adoption_state") or "unadopted")
    safe_git = Path(str(manifest["safe_git_worktree_root"]))
    integration_git = _integration_git_from_manifest(manifest)
    source_git = Path(str(manifest["source_git_root"]))
    eligible = adoption_state in {"adopted", "complete_no_changes"}
    removed: list[str] = []
    if apply and not eligible:
        raise RunExecutionWorktreeError(
            f"run worktree is {adoption_state}; adopt or mark complete before cleanup"
        )
    if apply:
        for worktree_root in _cleanup_worktree_roots(safe_git, integration_git):
            result = _run_git(source_git, "worktree", "remove", "--force", str(worktree_root), check=False)
            if result.returncode != 0 and worktree_root.exists():
                shutil.rmtree(worktree_root)
            removed.append(str(worktree_root))
        manifest_path.unlink(missing_ok=True)
        try:
            manifest_path.parent.rmdir()
        except OSError:
            pass
    return {
        "run_id": run_id,
        "applied": apply,
        "eligible": eligible,
        "preserved_reason": None if eligible else f"worktree is {adoption_state}",
        "manifest_path": str(manifest_path),
        "safe_git_worktree_root": str(safe_git),
        "integration_git_worktree_root": str(integration_git) if integration_git is not None else None,
        "source_git_root": str(source_git),
        "adoption_state": adoption_state,
        "targets": [str(path) for path in _cleanup_worktree_roots(safe_git, integration_git)] + [str(manifest_path)],
        "removed": removed,
        "apply_command": f"bin/swarm worktrees cleanup-run {run_id} --apply",
    }


def run_worktree_status(run_id: str, *, data_dir: Path, include_units: bool = False) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    if not manifest_path.is_file():
        return {
            "run_id": run_id,
            "status": "not_found",
            "manifest_path": str(manifest_path),
            "recommended_command": None,
        }
    manifest = _require_manifest(manifest_path)
    source_git = Path(str(manifest["source_git_root"]))
    safe_git = Path(str(manifest["safe_git_worktree_root"]))
    branch = str(manifest["branch"])
    base_sha = str(manifest["base_sha"])
    base_ref = str(manifest.get("base_ref") or "HEAD")
    source_base_sha = _rev_parse_or_none(source_git, base_ref)
    unadopted_commits = _branch_commits_ahead(source_git, base_sha, branch)
    copied_rels = _copied_artifact_rels(manifest)
    raw_dirty_entries = _git_status_entries(safe_git, ".") if (safe_git / ".git").exists() else []
    dirty_entries, ignored_artifact_paths = _filter_run_artifact_status_entries(
        raw_dirty_entries,
        copied_rels=copied_rels,
        root=safe_git,
        source_overlay_shas=_copied_source_overlay_shas(manifest),
    )
    units = _unit_worktree_statuses(run_id, data_dir=Path(data_dir), include_details=include_units)
    unit_dirty_count = sum(1 for item in units if item.get("dirty"))
    unit_conflict_count = sum(1 for item in units if item.get("conflict_manifest_present"))
    unit_unmerged_ready_count = sum(1 for item in units if item.get("merge_state") == "ready")
    unit_drift = unit_dirty_count + unit_conflict_count + unit_unmerged_ready_count > 0
    drift = []
    if source_base_sha is not None and source_base_sha != base_sha:
        drift.append("base_sha")
    if unadopted_commits:
        drift.append("unadopted_commits")
    if dirty_entries:
        drift.append("dirty_worktree")
    if unit_drift:
        drift.append("unit_drift")
    return {
        "run_id": run_id,
        "status": "drift" if drift else "ok",
        "manifest_path": str(manifest_path),
        "source_git_root": str(source_git),
        "safe_git_worktree_root": str(safe_git),
        "safe_project_root": manifest.get("safe_project_root"),
        "branch": branch,
        "base_ref": base_ref,
        "manifest_base_sha": base_sha,
        "source_base_sha": source_base_sha,
        "base_drift": source_base_sha is not None and source_base_sha != base_sha,
        "base_drift_safe": bool(source_base_sha is not None and source_base_sha != base_sha and not unadopted_commits and not dirty_entries),
        "unadopted_commits": unadopted_commits,
        "dirty_paths": [_format_status_entry(entry) for entry in dirty_entries],
        "copied_artifact_paths": ignored_artifact_paths,
        "dirty_file_count": len(dirty_entries),
        "unit_drift": unit_drift,
        "unit_dirty_count": unit_dirty_count,
        "unit_conflict_count": unit_conflict_count,
        "unit_unmerged_ready_count": unit_unmerged_ready_count,
        "units": units if include_units else [],
        "adoption_state": str(manifest.get("adoption_state") or "unadopted"),
        "drift": drift,
        "recommended_command": f"bin/swarm worktrees reset {run_id} --discard" if drift else None,
    }


def reset_run_worktree(
    run_id: str,
    *,
    data_dir: Path,
    discard: bool = False,
    archive_branch: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    _assert_valid_run_id(run_id)
    if discard == archive_branch:
        raise RunExecutionWorktreeError("choose exactly one of discard or archive_branch")
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    source_git = Path(str(manifest["source_git_root"]))
    safe_git = Path(str(manifest["safe_git_worktree_root"]))
    branch = str(manifest["branch"])
    base_sha = str(manifest["base_sha"])
    status = run_worktree_status(run_id, data_dir=data_dir, include_units=True)
    unsafe_reasons = []
    if status.get("unadopted_commits"):
        unsafe_reasons.append("unadopted_commits")
    if status.get("dirty_paths"):
        unsafe_reasons.append("dirty_worktree")
    if status.get("adoption_state") != "unadopted":
        unsafe_reasons.append("adoption_state")
    if status.get("unit_dirty_count"):
        unsafe_reasons.append("unit_dirty_worktree")
    if status.get("unit_conflict_count"):
        unsafe_reasons.append("unit_conflict")
    if status.get("unit_unmerged_ready_count"):
        unsafe_reasons.append("unit_ready_unmerged")
    if unsafe_reasons and not force:
        payload = {
            **status,
            "safe_to_rebuild": False,
            "unsafe_reasons": unsafe_reasons,
            "recommended_command": f"bin/swarm worktrees reset {run_id} --archive-branch --force",
        }
        raise RunExecutionWorktreeRebuildRequired(
            "run worktree reset would discard or hide unadopted work; pass --force or archive the branch",
            payload,
        )

    removed_unit_worktrees: list[str] = []
    archived_unit_branches: list[str] = []
    deleted_unit_branches: list[str] = []
    if force:
        for unit in status.get("units") or []:
            if not isinstance(unit, Mapping):
                continue
            unit_root_value = unit.get("worktree_root")
            unit_branch = unit.get("branch")
            if isinstance(unit_root_value, str) and unit_root_value:
                unit_root = Path(unit_root_value)
                if unit_root.exists():
                    _remove_run_worktree_checkout(source_git, unit_root)
                    removed_unit_worktrees.append(str(unit_root))
            if isinstance(unit_branch, str) and unit_branch and _branch_exists(source_git, unit_branch):
                if archive_branch:
                    archived = _archived_unit_branch_name(unit_branch)
                    _git(source_git, "branch", "-m", unit_branch, archived)
                    archived_unit_branches.append(archived)
                else:
                    _git(source_git, "branch", "-D", unit_branch)
                    deleted_unit_branches.append(unit_branch)

    _remove_run_worktree_checkout(source_git, safe_git)
    archived_branch: str | None = None
    if _branch_exists(source_git, branch):
        if archive_branch:
            archived_branch = _archived_execution_branch_name(run_id)
            _git(source_git, "branch", "-m", branch, archived_branch)
        else:
            _git(source_git, "branch", "-D", branch)
    manifest_path.unlink(missing_ok=True)
    try:
        manifest_path.parent.rmdir()
    except OSError:
        pass
    payload = {
        "run_id": run_id,
        "status": "reset",
        "discarded": discard,
        "archived_branch": archived_branch,
        "deleted_branch": branch if discard else None,
        "archived_unit_branches": archived_unit_branches,
        "deleted_unit_branches": deleted_unit_branches,
        "removed_unit_worktrees": removed_unit_worktrees,
        "manifest_path": str(manifest_path),
        "safe_git_worktree_root": str(safe_git),
        "base_sha": base_sha,
    }
    _append_worktree_reset_event(Path(data_dir), run_id=run_id, details=payload)
    return payload


def _unit_worktree_base_ref(manifest: Mapping[str, Any], *, base: str) -> str:
    if base == "execution":
        return str(manifest["branch"])
    if base == "integration":
        integration_path = manifest.get("integration_manifest_path")
        if not isinstance(integration_path, str) or not integration_path:
            raise RunExecutionWorktreeError("unit worktree base=integration requires an integration manifest")
        integration = _read_json_mapping(Path(integration_path))
        if integration is None or not isinstance(integration.get("integration_branch"), str):
            raise RunExecutionWorktreeError(f"integration manifest is missing integration_branch: {integration_path}")
        return str(integration["integration_branch"])
    raise RunExecutionWorktreeError(f"unsupported unit worktree base: {base}")


def _ensure_unit_worktree(source_git: Path, *, unit_git: Path, branch: str, base_ref: str) -> None:
    if unit_git.exists() and (unit_git / ".git").exists():
        if _git_stdout(unit_git, "branch", "--show-current") != branch:
            raise RunExecutionWorktreeError(f"unit worktree branch mismatch: expected {branch} at {unit_git}")
        return
    if unit_git.exists() and any(unit_git.iterdir()):
        raise RunExecutionWorktreeError(f"unit worktree path already exists without a git checkout: {unit_git}")
    unit_git.parent.mkdir(parents=True, exist_ok=True)
    if _branch_exists(source_git, branch):
        _git(source_git, "worktree", "add", str(unit_git), branch)
    else:
        _git(source_git, "worktree", "add", "-b", branch, str(unit_git), base_ref)


def _ensure_unit_sessions(
    run_id: str,
    *,
    data_dir: Path,
    manifest: Mapping[str, Any],
    prepared: Mapping[str, Any],
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> dict[str, Any]:
    with locked_unit_sessions(run_id, data_dir=data_dir):
        if unit_sessions_path(run_id, data_dir=data_dir).is_file():
            return load_unit_sessions(run_id, data_dir=data_dir)
        state = _new_unit_sessions_state(
            run_id,
            data_dir=data_dir,
            manifest=manifest,
            prepared=prepared,
            base_ref=base_ref,
            base_sha=base_sha,
        )
        return write_unit_sessions(state, data_dir=data_dir)


def _new_unit_sessions_state(
    run_id: str,
    *,
    data_dir: Path,
    manifest: Mapping[str, Any],
    prepared: Mapping[str, Any],
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    source_git = Path(str(manifest["source_git_root"]))
    project_subdir = str(manifest.get("project_subdir") or "")
    resolved_base_ref = base_ref or str(manifest["branch"])
    resolved_base_sha = base_sha or _git_stdout(source_git, "rev-parse", resolved_base_ref)
    units: list[dict[str, Any]] = []
    for phase_id, unit in _prepared_units_by_phase(prepared):
        unit_id = str(unit.get("id") or "")
        if not unit_id:
            continue
        branch = unit_execution_branch_name(run_id, phase_id, unit_id)
        worktree_root = unit_execution_worktree_root(data_dir, run_id, phase_id, unit_id).resolve(strict=False)
        project_root = (worktree_root / project_subdir).resolve(strict=False) if project_subdir else worktree_root
        units.append(
            unit_session_template(
                phase_id=phase_id,
                unit_id=unit_id,
                branch=branch,
                worktree_root=worktree_root,
                project_root=project_root,
                base_sha=resolved_base_sha,
                base_ref=resolved_base_ref,
                now=now,
            )
        )
    return {
        "schema_version": 1,
        "run_id": run_id,
        "prepared_artifact_path": str(Path(data_dir) / "runs" / run_id / "prepared_plan.v1.json"),
        "source_run_worktree_manifest_path": str(Path(data_dir) / "worktrees" / run_id / "manifest.json"),
        "created_at": now,
        "updated_at": now,
        "mode": "unit-worktrees",
        "units": units,
    }


def _adoption_source(manifest: Mapping[str, Any]) -> dict[str, Any]:
    integration_path = manifest.get("integration_manifest_path")
    if isinstance(integration_path, str) and integration_path:
        integration = _read_json_mapping(Path(integration_path))
        if integration is not None and isinstance(integration.get("integration_project_root"), str):
            return {
                "kind": "integration",
                "project_root": Path(str(integration["integration_project_root"])),
                "git_root": Path(str(integration.get("integration_git_worktree_root") or integration["integration_project_root"])),
                "integration_branch": integration.get("integration_branch"),
                "head_sha": integration.get("head_sha"),
            }
    return {
        "kind": "execution",
        "project_root": Path(str(manifest["safe_project_root"])),
        "git_root": Path(str(manifest["safe_git_worktree_root"])),
        "integration_branch": None,
        "head_sha": None,
    }


def _integration_git_from_manifest(manifest: Mapping[str, Any]) -> Path | None:
    integration_path = manifest.get("integration_manifest_path")
    if not isinstance(integration_path, str) or not integration_path:
        return None
    integration = _read_json_mapping(Path(integration_path))
    if integration is None or not isinstance(integration.get("integration_git_worktree_root"), str):
        return None
    return Path(str(integration["integration_git_worktree_root"]))


def _cleanup_worktree_roots(safe_git: Path, integration_git: Path | None) -> list[Path]:
    roots = [safe_git]
    if integration_git is not None and integration_git != safe_git:
        roots.append(integration_git)
    return roots


def _adoption_changes(manifest: Mapping[str, Any], *, adoption_source: Mapping[str, Any]) -> list[dict[str, str]]:
    project_subdir = str(manifest.get("project_subdir") or "")
    if adoption_source.get("kind") == "integration":
        head = str(adoption_source.get("head_sha") or "HEAD")
        return _diff_changes(
            Path(str(adoption_source["git_root"])),
            str(manifest["base_sha"]),
            head,
            project_subdir=project_subdir,
        )
    project_root = Path(str(adoption_source["project_root"]))
    return _filter_source_overlay_changes(
        _status_changes(project_root, project_subdir=project_subdir),
        manifest,
        root=project_root,
    )


def _execution_branch_changes(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    source_git = Path(str(manifest["source_git_root"]))
    project_subdir = str(manifest.get("project_subdir") or "")
    return _diff_changes(
        source_git,
        str(manifest["base_sha"]),
        str(manifest["branch"]),
        project_subdir=project_subdir,
    )


def _dedupe_changes(changes: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for change in changes:
        path = str(change.get("path") or "")
        status = str(change.get("status") or "")
        if not path:
            continue
        key = (status, path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"status": status, "path": path})
    return deduped


def _copyback_plan(
    manifest: Mapping[str, Any],
    *,
    source_project: Path,
    destination_project: Path,
    changes: Iterable[Mapping[str, str]],
    copied_rels: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    operations: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for change in changes:
        rel = str(change.get("path") or "")
        if not rel:
            continue
        block_reason = _adoption_block_reason(rel, copied_rels=copied_rels)
        if block_reason is not None:
            blocked.append({"path": rel, "reason": block_reason})
            continue
        source_path = source_project / rel
        destination = destination_project / rel
        action = "delete" if str(change.get("status") or "").strip().startswith("D") else "copy"
        operations.append(
            {
                "action": action,
                "path": rel,
                "source_path": str(source_path),
                "destination_path": str(destination),
            }
        )
    for operation in operations:
        block_reason = _destination_block_reason(manifest, operation)
        if block_reason is not None:
            blocked.append({"path": str(operation["path"]), "reason": block_reason})
    return operations, blocked


def _ensure_integration_worktree(
    source_git: Path,
    *,
    integration_git: Path,
    integration_branch: str,
    base_sha: str,
) -> None:
    if integration_git.exists() and (integration_git / ".git").exists():
        if _git_status_entries(integration_git, "."):
            raise RunExecutionWorktreeError(f"integration worktree has uncommitted changes: {integration_git}")
        return
    if integration_git.exists() and any(integration_git.iterdir()):
        raise RunExecutionWorktreeError(f"integration worktree path already exists without a git checkout: {integration_git}")
    integration_git.parent.mkdir(parents=True, exist_ok=True)
    if _branch_exists(source_git, integration_branch):
        _git(source_git, "worktree", "add", str(integration_git), integration_branch)
    else:
        _git(source_git, "worktree", "add", "-b", integration_branch, str(integration_git), base_sha)


@contextmanager
def locked_integration_merge(
    run_id: str,
    *,
    data_dir: Path,
    timeout_seconds: float = 60.0,
) -> Iterator[None]:
    if fcntl is None:
        raise RunExecutionWorktreeError("integration merge locks require POSIX fcntl.flock")
    lock_path = Path(data_dir) / "runs" / run_id / "integration-merge.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RunExecutionWorktreeError(f"timed out waiting for integration merge lock: {lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_post_writer_report_binding(
    report: Mapping[str, Any],
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
) -> None:
    if report.get("schema_version") != "post_writer_report.v1":
        raise RunExecutionWorktreeError("post-writer report schema_version must be post_writer_report.v1")
    _validate_optional_identity(report, run_id=run_id, phase_id=phase_id, unit_id=unit_id, label="post-writer report")
    if report.get("work_unit_id") != unit_id:
        raise RunExecutionWorktreeError(
            f"post-writer report work_unit_id {report.get('work_unit_id')!r} does not match {unit_id!r}"
        )


def _validate_spec_review_binding(
    report: Mapping[str, Any],
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
) -> None:
    _validate_optional_identity(report, run_id=run_id, phase_id=phase_id, unit_id=unit_id, label="spec-review report")


def _validate_optional_identity(
    report: Mapping[str, Any],
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
    label: str,
) -> None:
    for key, expected in (("run_id", run_id), ("phase_id", phase_id), ("unit_id", unit_id), ("work_unit_id", unit_id)):
        value = report.get(key)
        if isinstance(value, str) and value and value != expected:
            raise RunExecutionWorktreeError(f"{label} {key} {value!r} does not match {expected!r}")


def _unit_merge_state_after_gates(
    unit: Mapping[str, Any],
    *,
    post_writer_status: str | None = None,
    spec_review_status: str | None = None,
) -> str:
    existing = unit.get("merge_state")
    if existing in {"merged", "conflicted"}:
        return str(existing)
    post = post_writer_status or str(unit.get("post_writer_status") or "pending")
    spec = spec_review_status or str(unit.get("spec_review_status") or "pending")
    if post == "failed" or spec == "rejected":
        return "blocked"
    if post == "passed" and spec in {"approved", "skipped"}:
        return "ready"
    return "pending"


def _unit_merge_gate_blocker(unit_git: Path, unit: Mapping[str, Any]) -> str | None:
    unit_id = str(unit.get("unit_id") or "<unknown>")
    if unit.get("post_writer_status") != "passed":
        return f"unit {unit_id} has not passed the post-writer gate"
    spec_status = unit.get("spec_review_status")
    if spec_status not in {"approved", "skipped"}:
        return f"unit {unit_id} has not passed the spec-review gate"
    current_head = _rev_parse_or_none(unit_git, "HEAD")
    if current_head is None:
        return f"unit {unit_id} branch HEAD cannot be resolved"
    post_head = unit.get("post_writer_unit_head_sha")
    if isinstance(post_head, str) and post_head and post_head != current_head:
        return f"unit {unit_id} post-writer report is stale for current branch HEAD"
    if spec_status == "approved" and not unit.get("spec_review_report_sha256"):
        return f"unit {unit_id} approved spec-review report is missing"
    spec_head = unit.get("spec_review_unit_head_sha")
    if isinstance(spec_head, str) and spec_head and spec_head != current_head:
        return f"unit {unit_id} spec-review report is stale for current branch HEAD"
    return None


def _write_integration_conflict_manifest(
    path: Path,
    *,
    run_id: str,
    source_git: Path,
    integration_git: Path,
    execution_branch: str,
    integration_branch: str,
    base_sha: str,
    merge_command: list[str],
    merge_result: subprocess.CompletedProcess[str],
    conflicted_files: list[str],
) -> dict[str, Any]:
    conflict = {
        "schema_version": 1,
        "run_id": run_id,
        "written_at": utc_now(),
        "source_git_root": str(source_git),
        "integration_git_worktree_root": str(integration_git),
        "execution_branch": execution_branch,
        "integration_branch": integration_branch,
        "base_sha": base_sha,
        "execution_head": _rev_parse_or_none(source_git, execution_branch),
        "integration_head": _rev_parse_or_none(integration_git, "HEAD"),
        "merge_command": merge_command,
        "merge_returncode": merge_result.returncode,
        "merge_stdout": merge_result.stdout,
        "merge_stderr": merge_result.stderr,
        "conflicted_files": conflicted_files,
        "status_porcelain_z": _run_git(integration_git, "status", "--porcelain=v1", "-z", check=False).stdout,
    }
    _atomic_json_write(path, conflict)
    return conflict


def _write_unit_conflict_manifest(
    path: Path,
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
    source_git: Path,
    integration_git: Path,
    unit_branch: str,
    integration_branch: str,
    base_sha: str,
    merge_command: list[str],
    merge_result: subprocess.CompletedProcess[str],
    conflicted_files: list[str],
) -> dict[str, Any]:
    conflict = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "unit_id": unit_id,
        "written_at": utc_now(),
        "source_git_root": str(source_git),
        "integration_git_worktree_root": str(integration_git),
        "unit_branch": unit_branch,
        "integration_branch": integration_branch,
        "base_sha": base_sha,
        "unit_head": _rev_parse_or_none(source_git, unit_branch),
        "integration_head": _rev_parse_or_none(integration_git, "HEAD"),
        "merge_command": merge_command,
        "merge_returncode": merge_result.returncode,
        "merge_stdout": merge_result.stdout,
        "merge_stderr": merge_result.stderr,
        "conflicted_files": conflicted_files,
        "status_porcelain_z": _run_git(integration_git, "status", "--porcelain=v1", "-z", check=False).stdout,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, conflict)
    return conflict


def _append_worktree_conflict_event(data_dir: Path, *, run_id: str, details: Mapping[str, Any]) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "worktree_merge_conflict",
        "bd_epic_id": None,
        "phase_id": None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": "merge-conflict",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details),
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=RunExecutionWorktreeError)
    append_run_event(data_dir, row)


def _append_unit_worktree_conflict_event(
    data_dir: Path,
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
    details: Mapping[str, Any],
) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "worktree_merge_conflict",
        "bd_epic_id": None,
        "phase_id": phase_id,
        "work_unit_id": unit_id,
        "child_bead_ids": None,
        "reason": "merge-conflict",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details),
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=RunExecutionWorktreeError)
    append_run_event(data_dir, row)


def _run_integration_validations(prepared: Mapping[str, Any], integration_project: Path) -> list[dict[str, Any]]:
    from .post_writer import run_validation_commands

    results: list[dict[str, Any]] = []
    for unit in _prepared_units(prepared):
        unit_id = str(unit.get("id") or "")
        for result in run_validation_commands(unit, repo=integration_project, timeout_seconds=120):
            row = dict(result)
            row["work_unit_id"] = unit_id
            results.append(row)
    return results


def _validation_commands(prepared: Mapping[str, Any]) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for unit in _prepared_units(prepared):
        for command in unit.get("validation_commands") or []:
            if not isinstance(command, str) or not command.strip() or command in seen:
                continue
            seen.add(command)
            commands.append(command)
    return commands


def _prepared_units(prepared: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    units: list[Mapping[str, Any]] = []
    descriptors = prepared.get("work_unit_artifacts") if isinstance(prepared.get("work_unit_artifacts"), Mapping) else {}
    for descriptor in descriptors.values():
        if not isinstance(descriptor, Mapping):
            continue
        artifact = descriptor.get("artifact") if isinstance(descriptor.get("artifact"), Mapping) else None
        if artifact is None:
            continue
        for unit in artifact.get("work_units") or []:
            if isinstance(unit, Mapping):
                units.append(unit)
    return units


def _source_dirty_block_patterns(prepared: Mapping[str, Any]) -> tuple[str, ...]:
    patterns: list[str] = []
    for unit in _prepared_units(prepared):
        for key in ("allowed_files", "files", "context_files"):
            value = unit.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and item.strip():
                    patterns.append(item)
    return tuple(dict.fromkeys(_normalize_scope_path(pattern) for pattern in patterns if pattern.strip()))


def _prepared_units_by_phase(prepared: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    units: list[tuple[str, Mapping[str, Any]]] = []
    descriptors = prepared.get("work_unit_artifacts") if isinstance(prepared.get("work_unit_artifacts"), Mapping) else {}
    for phase_id, descriptor in descriptors.items():
        if not isinstance(descriptor, Mapping):
            continue
        artifact = descriptor.get("artifact") if isinstance(descriptor.get("artifact"), Mapping) else None
        if artifact is None:
            continue
        for unit in artifact.get("work_units") or []:
            if isinstance(unit, Mapping):
                units.append((str(phase_id), unit))
    return units


def _current_branch(repo: Path) -> str | None:
    value = _run_git(repo, "branch", "--show-current", check=False).stdout.strip()
    return value or None


def _conflicted_files(repo: Path) -> list[str]:
    result = _run_git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
    return [line for line in result.stdout.splitlines() if line]


def _rev_parse_or_none(repo: Path, ref: str) -> str | None:
    result = _run_git(repo, "rev-parse", ref, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _assert_supported_git_checkout(source_project: Path) -> None:
    super_root = _git_stdout(source_project, "rev-parse", "--show-superproject-working-tree")
    if super_root.strip():
        raise RunExecutionWorktreeError("safe-worktree launcher does not support submodule project roots yet")
    sparse = _git_config_bool(source_project, "core.sparseCheckout")
    if sparse:
        raise RunExecutionWorktreeError("safe-worktree launcher does not support sparse-checkout sources yet")


def _assert_clean_source_project(resolved: ResolvedExecutionWorktree) -> tuple[str, ...]:
    scope = resolved.project_subdir or "."
    entries = _git_status_entries(
        resolved.source_git_root,
        scope,
    )
    allowed = {_git_relative_artifact_path(resolved, spec.relative_path) for spec in resolved.copy_specs}
    dirty: list[str] = []
    ignored: list[str] = []
    for entry in entries:
        paths = [entry.get("path"), entry.get("original_path")]
        present_paths = [path for path in paths if isinstance(path, str) and path]
        if present_paths and all(path in allowed for path in present_paths):
            continue
        if any(_source_dirty_path_overlaps_run_scope(resolved, path) for path in present_paths):
            dirty.append(_format_project_status_entry(entry, project_subdir=resolved.project_subdir))
        else:
            ignored.append(_format_project_status_entry(entry, project_subdir=resolved.project_subdir))
    if dirty:
        raise RunExecutionWorktreeError(
            "source checkout has dirty files that overlap this run's allowed/context file scope; "
            "commit/stash them before safe-worktree launch: " + ", ".join(dirty)
        )
    return tuple(sorted(set(ignored)))


def _format_project_status_entry(entry: Mapping[str, str], *, project_subdir: str) -> str:
    path = _project_relative_status_path(entry.get("path") or "", project_subdir=project_subdir)
    original = _project_relative_status_path(entry.get("original_path") or "", project_subdir=project_subdir)
    if original:
        return f"{original} -> {path}"
    return path


def _source_dirty_path_overlaps_run_scope(resolved: ResolvedExecutionWorktree, git_relative_path: str) -> bool:
    patterns = resolved.source_dirty_block_patterns
    if not patterns:
        return False
    variants = _source_dirty_path_variants(resolved, git_relative_path)
    return any(
        _path_matches_source_pattern(pattern, variant)
        for pattern in patterns
        for variant in variants
    )


def _source_dirty_path_variants(resolved: ResolvedExecutionWorktree, git_relative_path: str) -> tuple[str, ...]:
    project_relative = _project_relative_status_path(
        git_relative_path,
        project_subdir=resolved.project_subdir,
    )
    return tuple(dict.fromkeys(path for path in (git_relative_path, project_relative) if path))


def _path_matches_source_pattern(pattern: str, path: str) -> bool:
    normalized_pattern = _normalize_scope_path(pattern)
    normalized_path = _normalize_scope_path(path)
    if not normalized_pattern or not normalized_path:
        return False
    if _glob_matches(normalized_pattern, normalized_path):
        return True
    parent = _source_scope_parent_dir(normalized_pattern)
    if parent not in {"", "."} and (normalized_path == parent or normalized_path.startswith(parent + "/")):
        return True
    if any(char in normalized_pattern for char in "*?["):
        return False
    directory = normalized_pattern.rstrip("/")
    if normalized_path == directory or normalized_path.startswith(directory + "/"):
        return True
    parent = Path(directory).parent.as_posix()
    return parent not in {"", "."} and (normalized_path == parent or normalized_path.startswith(parent + "/"))


def _source_scope_parent_dir(pattern: str) -> str:
    parts = Path(pattern).parts
    parent_parts: list[str] = []
    for part in parts:
        if any(char in part for char in "*?["):
            break
        parent_parts.append(part)
    if not parent_parts:
        return "."
    candidate = Path(*parent_parts)
    if any(char in pattern for char in "*?["):
        return candidate.as_posix()
    return candidate.parent.as_posix()


_DISPATCHER_POLICY_WORKTREE_RELPATHS: tuple[str, ...] = (
    ".claude/settings.local.json",
    ".claude/settings.local.json.bak",
)


def _create_run_worktree(resolved: ResolvedExecutionWorktree) -> None:
    if resolved.safe_git_root.exists() and any(resolved.safe_git_root.iterdir()):
        raise RunExecutionWorktreeError(f"run worktree path already exists without a valid manifest: {resolved.safe_git_root}")
    if _branch_exists(resolved.source_git_root, resolved.branch):
        raise RunExecutionWorktreeError(f"run execution branch already exists without a valid manifest: {resolved.branch}")
    resolved.safe_git_root.parent.mkdir(parents=True, exist_ok=True)
    _git(resolved.source_git_root, "worktree", "add", "-b", resolved.branch, str(resolved.safe_git_root), resolved.base_sha)
    _scrub_dispatcher_policy_files(resolved)


def _scrub_dispatcher_policy_files(resolved: ResolvedExecutionWorktree) -> None:
    # The source-tree .claude/settings.local.json is the dispatcher's coordinator
    # minimum allowlist (Read + Bash(bd:*); deny Write/Edit/Glob/Grep). It must
    # not follow into a writer worktree: Claude Code merges .claude/settings.local.json
    # from the worker's cwd at launch and deny rules win, blocking the writer's Write
    # tool even though --settings/--allowedTools grant it. Drop the file from the
    # worktree checkout and flip skip-worktree on the index entry so the deletion is
    # invisible to git status and adoption copyback does not propagate it back.
    project_subdir = resolved.project_subdir.strip("/") if resolved.project_subdir else ""
    for project_relative in _DISPATCHER_POLICY_WORKTREE_RELPATHS:
        worktree_path = resolved.safe_project_root / project_relative
        if not worktree_path.exists():
            continue
        index_path = f"{project_subdir}/{project_relative}" if project_subdir else project_relative
        _run_git(
            resolved.safe_git_root,
            "update-index",
            "--skip-worktree",
            "--",
            index_path,
            check=False,
        )
        try:
            worktree_path.unlink()
        except FileNotFoundError:
            pass


def _copy_required_artifacts(resolved: ResolvedExecutionWorktree) -> list[CopiedArtifact]:
    copied: list[CopiedArtifact] = []
    for spec in _dedupe_copy_specs(resolved.copy_specs):
        if not _is_regular_file_no_symlink(spec.source_path):
            if spec.source_path.exists() or spec.source_path.is_symlink():
                _raise_if_not_regular_file(spec.source_path)
            if spec.required:
                raise RunExecutionWorktreeError(f"required run artifact is missing: {spec.source_path}")
            continue
        destination = resolved.safe_project_root / spec.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_sha = _sha256_file(spec.source_path)
        transformed = False
        if spec.transform is not None:
            _atomic_write_bytes(destination, spec.transform(spec.source_path.read_bytes(), resolved))
            transformed = True
        else:
            _atomic_copy2(spec.source_path, destination)
        copied.append(
            CopiedArtifact(
                source_path=spec.source_path.resolve(strict=False),
                destination_path=destination.resolve(strict=False),
                relative_path=str(spec.relative_path),
                source_sha256=source_sha,
                destination_sha256=_sha256_file(destination),
                kind=spec.kind,
                transformed=transformed,
            )
        )
    return copied


def _manifest_payload(
    resolved: ResolvedExecutionWorktree,
    copied: list[CopiedArtifact],
    *,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    created_at = previous.get("created_at") if isinstance(previous, Mapping) and isinstance(previous.get("created_at"), str) else utc_now()
    adoption_state = (
        previous.get("adoption_state")
        if isinstance(previous, Mapping) and isinstance(previous.get("adoption_state"), str)
        else "unadopted"
    )
    adopted_at = previous.get("adopted_at") if isinstance(previous, Mapping) and "adopted_at" in previous else None
    scope_check_path = previous.get("scope_check_path") if isinstance(previous, Mapping) else None
    conflict_manifest_path = previous.get("conflict_manifest_path") if isinstance(previous, Mapping) else None
    integration_manifest_path = previous.get("integration_manifest_path") if isinstance(previous, Mapping) else None
    return {
        "schema_version": 1,
        "run_id": resolved.run_id,
        "source_git_root": str(resolved.source_git_root),
        "source_project_root": str(resolved.source_project_root),
        "safe_git_worktree_root": str(resolved.safe_git_root),
        "safe_project_root": str(resolved.safe_project_root),
        "project_subdir": resolved.project_subdir,
        "branch": resolved.branch,
        "base_sha": resolved.base_sha,
        "base_ref": resolved.base_ref,
        "copied_artifacts": [artifact.to_dict() for artifact in copied],
        "adoption_state": adoption_state,
        "adopted_at": adopted_at,
        "created_at": created_at,
        "last_used_at": utc_now(),
        "scope_check_path": scope_check_path if isinstance(scope_check_path, str) else None,
        "conflict_manifest_path": conflict_manifest_path if isinstance(conflict_manifest_path, str) else None,
        "integration_manifest_path": integration_manifest_path if isinstance(integration_manifest_path, str) else None,
    }


def _validate_existing_manifest(resolved: ResolvedExecutionWorktree, manifest: Mapping[str, Any]) -> None:
    classification = _classify_existing_manifest(resolved, manifest)
    if classification.kind != "match":
        raise RunExecutionWorktreeError(
            "existing run worktree manifest does not match this run/base: "
            + ", ".join(classification.mismatched)
        )


def _classify_existing_manifest(
    resolved: ResolvedExecutionWorktree,
    manifest: Mapping[str, Any],
) -> ManifestDriftClassification:
    identity_expected = {
        "run_id": resolved.run_id,
        "source_git_root": str(resolved.source_git_root),
        "source_project_root": str(resolved.source_project_root),
        "safe_git_worktree_root": str(resolved.safe_git_root),
        "safe_project_root": str(resolved.safe_project_root),
        "project_subdir": resolved.project_subdir,
    }
    identity_mismatched = tuple(
        key for key, expected_value in identity_expected.items() if manifest.get(key) != expected_value
    )
    if identity_mismatched:
        return ManifestDriftClassification("identity_mismatch", mismatched=identity_mismatched)

    drift_expected = {
        "branch": resolved.branch,
        "base_sha": resolved.base_sha,
    }
    drift_mismatched = tuple(
        key for key, expected_value in drift_expected.items() if manifest.get(key) != expected_value
    )
    if not drift_mismatched:
        return ManifestDriftClassification("match")

    payload = _base_drift_payload(resolved, manifest, mismatched=drift_mismatched)
    if payload["safe_to_rebuild"]:
        return ManifestDriftClassification("base_drift_safe", mismatched=drift_mismatched, payload=payload)
    return ManifestDriftClassification("base_drift_unsafe", mismatched=drift_mismatched, payload=payload)


def _base_drift_payload(
    resolved: ResolvedExecutionWorktree,
    manifest: Mapping[str, Any],
    *,
    mismatched: tuple[str, ...],
) -> dict[str, Any]:
    branch = str(manifest.get("branch") or resolved.branch)
    recorded_base = str(manifest.get("base_sha") or "")
    adoption_state = str(manifest.get("adoption_state") or "unadopted")
    unadopted_commits = _branch_commits_ahead(resolved.source_git_root, recorded_base, branch)
    raw_dirty_entries = (
        _git_status_entries(resolved.safe_git_root, ".")
        if (resolved.safe_git_root / ".git").exists()
        else []
    )
    copied_rels = _copied_artifact_rels(manifest)
    dirty_entries, ignored_artifact_paths = _filter_run_artifact_status_entries(
        raw_dirty_entries,
        copied_rels=copied_rels,
        root=resolved.safe_git_root,
        source_overlay_shas=_copied_source_overlay_shas(manifest),
    )
    unsafe_reasons: list[str] = []
    if adoption_state != "unadopted":
        unsafe_reasons.append("adoption_state")
    if unadopted_commits:
        unsafe_reasons.append("unadopted_commits")
    if dirty_entries:
        unsafe_reasons.append("dirty_worktree")
    return {
        "run_id": resolved.run_id,
        "reason": "base_drift",
        "mismatched": list(mismatched),
        "manifest_base_sha": recorded_base,
        "resolved_base_sha": resolved.base_sha,
        "manifest_branch": branch,
        "resolved_branch": resolved.branch,
        "adoption_state": adoption_state,
        "unadopted_commits": unadopted_commits,
        "dirty_paths": [_format_status_entry(entry) for entry in dirty_entries],
        "copied_artifact_paths": ignored_artifact_paths,
        "safe_to_rebuild": not unsafe_reasons,
        "unsafe_reasons": unsafe_reasons,
        "recommended_command": f"bin/swarm worktrees reset {resolved.run_id} --discard --force",
    }


def _branch_commits_ahead(repo: Path, base_ref: str, branch: str) -> list[str]:
    if not base_ref or not _branch_exists(repo, branch):
        return []
    result = _run_git(repo, "rev-list", f"{base_ref}..{branch}", check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _rebuild_run_worktree_for_base_drift(
    resolved: ResolvedExecutionWorktree,
    manifest: Mapping[str, Any],
    *,
    data_dir: Path,
    details: Mapping[str, Any],
) -> None:
    _remove_run_worktree_checkout(resolved.source_git_root, resolved.safe_git_root)
    branches = [str(manifest.get("branch") or resolved.branch), resolved.branch]
    for branch in dict.fromkeys(branches):
        if _branch_exists(resolved.source_git_root, branch):
            _git(resolved.source_git_root, "branch", "-D", branch)
    try:
        resolved.manifest_path.unlink()
    except FileNotFoundError:
        pass
    _append_worktree_rebuilt_event(
        data_dir,
        run_id=resolved.run_id,
        details={
            **dict(details),
            "manifest_path": str(resolved.manifest_path),
            "safe_git_worktree_root": str(resolved.safe_git_root),
        },
    )


def _remove_run_worktree_checkout(source_git: Path, safe_git: Path) -> None:
    if safe_git.exists():
        result = _run_git(source_git, "worktree", "remove", "--force", str(safe_git), check=False)
        if result.returncode != 0 and safe_git.exists():
            shutil.rmtree(safe_git)


def _append_worktree_rebuilt_event(data_dir: Path, *, run_id: str, details: Mapping[str, Any]) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "worktree_rebuilt",
        "bd_epic_id": None,
        "phase_id": None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": "base_drift",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details),
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=RunExecutionWorktreeError)
    append_run_event(data_dir, row)


def _append_worktree_reset_event(data_dir: Path, *, run_id: str, details: Mapping[str, Any]) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "worktree_reset",
        "bd_epic_id": None,
        "phase_id": None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": "operator_reset",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details),
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=RunExecutionWorktreeError)
    append_run_event(data_dir, row)


def _archived_execution_branch_name(run_id: str) -> str:
    stamp = utc_now().replace(":", "").replace(".", "-")
    return f"{execution_branch_name(run_id)}.archived-{stamp}"


def _archived_unit_branch_name(branch: str) -> str:
    stamp = utc_now().replace(":", "").replace(".", "-")
    return f"{branch}.archived-{stamp}"


def _artifact_copy_specs(
    run_id: str,
    *,
    data_dir: Path,
    source_project_root: Path,
    prepared_plan: Mapping[str, Any],
) -> tuple[ArtifactCopySpec, ...]:
    run_rel = Path("data") / "runs" / run_id
    run_data = Path(data_dir) / "runs" / run_id
    specs: list[ArtifactCopySpec] = [
        ArtifactCopySpec(
            run_data / "prepared_plan.v1.json",
            run_rel / "prepared_plan.v1.json",
            "prepared_artifact",
            transform=_rebase_prepared_artifact,
        ),
        ArtifactCopySpec(
            source_project_root / str(prepared_plan.get("source_plan_path")),
            Path(str(prepared_plan.get("source_plan_path"))),
            "source_plan",
        ),
        ArtifactCopySpec(
            source_project_root / str(prepared_plan.get("prepared_plan_path")),
            Path(str(prepared_plan.get("prepared_plan_path"))),
            "prepared_plan",
        ),
    ]
    inspect = prepared_plan.get("inspect_artifact")
    if isinstance(inspect, Mapping) and isinstance(inspect.get("path"), str):
        specs.append(ArtifactCopySpec(source_project_root / str(inspect["path"]), Path(str(inspect["path"])), "inspect_artifact"))
    for descriptor in (prepared_plan.get("work_unit_artifacts") or {}).values():
        if isinstance(descriptor, Mapping) and isinstance(descriptor.get("path"), str):
            specs.append(
                ArtifactCopySpec(
                    source_project_root / str(descriptor["path"]),
                    Path(str(descriptor["path"])),
                    "work_unit_artifact",
                )
            )
    for relative, kind, transform in (
        (run_rel / "checkpoint.v1.json", "checkpoint", None),
        (run_rel / "phase_sessions.v1.json", "phase_sessions", None),
        (run_rel / "phase_recovery" / "worktree-baseline.json", "worktree_baseline", _rebase_baseline_artifact),
    ):
        source = run_data / relative.relative_to(run_rel)
        specs.append(ArtifactCopySpec(source, relative, kind, required=False, transform=transform))
    return tuple(specs)


def _rebase_prepared_artifact(raw: bytes, resolved: ResolvedExecutionWorktree) -> bytes:
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        payload["repo_root"] = str(resolved.safe_project_root)
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _rebase_baseline_artifact(raw: bytes, resolved: ResolvedExecutionWorktree) -> bytes:
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        payload["repo_root"] = str(resolved.safe_project_root)
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _prepared_base_sha(source_project: Path, prepared_plan: Mapping[str, Any], *, base_ref: str) -> str:
    value = prepared_plan.get("git_base_sha")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) and value != "0" * 40:
        return value
    return _git_stdout(source_project, "rev-parse", base_ref).strip()


def _status_changes(repo: Path, *, project_subdir: str = "") -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for entry in _git_status_entries(repo, "."):
        status = entry["status"]
        path = _project_relative_status_path(entry["path"], project_subdir=project_subdir)
        original = _project_relative_status_path(entry.get("original_path") or "", project_subdir=project_subdir)
        if _is_rename_status(status):
            if original:
                changes.append({"status": "D ", "path": original})
            if path:
                changes.append({"status": status, "path": path})
            continue
        if path:
            changes.append({"status": status, "path": path})
    return changes


def _diff_changes(repo: Path, base_ref: str, head_ref: str, *, project_subdir: str = "") -> list[dict[str, str]]:
    pathspec = project_subdir.strip("/") or "."
    output = _run_git(
        repo,
        "diff",
        "--name-status",
        "-z",
        base_ref,
        head_ref,
        "--",
        pathspec,
        check=True,
    ).stdout
    fields = [field for field in output.split("\0") if field]
    changes: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if _is_rename_status(status) or _is_copy_status(status):
            if index + 1 >= len(fields):
                break
            original = _project_relative_status_path(fields[index], project_subdir=project_subdir)
            index += 1
            path = _project_relative_status_path(fields[index], project_subdir=project_subdir) if index < len(fields) else ""
            index += 1
            if original:
                changes.append({"status": "D", "path": original})
            if path:
                changes.append({"status": status, "path": path})
            continue
        if index >= len(fields):
            break
        path = _project_relative_status_path(fields[index], project_subdir=project_subdir)
        index += 1
        if path:
            changes.append({"status": status, "path": path})
    return changes


def _git_status_entries(repo: Path, *pathspecs: str) -> list[dict[str, str]]:
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if pathspecs:
        args.extend(["--", *pathspecs])
    output = _run_git(repo, *args, check=True).stdout
    fields = output.split("\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        if len(field) < 4:
            continue
        status = field[:2]
        path = field[3:]
        entry = {"status": status, "path": path}
        if _is_rename_status(status) or _is_copy_status(status):
            if index < len(fields) and fields[index]:
                entry["original_path"] = fields[index]
                index += 1
        entries.append(entry)
    return entries


def _is_rename_status(status: str) -> bool:
    return "R" in status[:2]


def _is_copy_status(status: str) -> bool:
    return "C" in status[:2]


def _format_status_entry(entry: Mapping[str, str]) -> str:
    path = entry.get("path") or ""
    original = entry.get("original_path") or ""
    if original:
        return f"{original} -> {path}"
    return path


def _project_relative_status_path(path: str, *, project_subdir: str) -> str:
    prefix = project_subdir.strip("/")
    if prefix and path == prefix:
        return ""
    if prefix and path.startswith(prefix + "/"):
        return path[len(prefix) + 1 :]
    return path


def _adoption_block_reason(path: str, *, copied_rels: set[str]) -> str | None:
    if _is_run_artifact_path(path, copied_rels=copied_rels):
        return "run_artifact"
    rel = Path(path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        return "path_escape"
    return None


def _is_run_artifact_path(path: str, *, copied_rels: set[str]) -> bool:
    rel = Path(path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        return False
    normalized = rel.as_posix()
    return normalized in copied_rels or normalized.startswith("data/runs/")


def _copied_artifact_rels(manifest: Mapping[str, Any]) -> set[str]:
    return {
        Path(str(item.get("relative_path"))).as_posix()
        for item in manifest.get("copied_artifacts") or []
        if isinstance(item, Mapping) and isinstance(item.get("relative_path"), str)
        and item.get("kind") != "source_plan"
    }


def _copied_source_overlay_shas(manifest: Mapping[str, Any]) -> dict[str, str]:
    overlays: dict[str, str] = {}
    for item in manifest.get("copied_artifacts") or []:
        if not isinstance(item, Mapping) or item.get("kind") != "source_plan":
            continue
        relative = item.get("relative_path")
        sha = item.get("destination_sha256")
        if not isinstance(relative, str) or not isinstance(sha, str):
            continue
        project_relative = Path(relative).as_posix()
        overlays[project_relative] = sha
        overlays[_source_git_relative_path(manifest, project_relative)] = sha
    return overlays


def _is_unchanged_source_overlay(root: Path, path: str, overlays: Mapping[str, str]) -> bool:
    normalized = Path(path).as_posix()
    expected = overlays.get(normalized)
    if expected is None:
        return False
    candidate = root / normalized
    return candidate.is_file() and _sha256_file(candidate) == expected


def _filter_source_overlay_changes(
    changes: Iterable[Mapping[str, str]],
    manifest: Mapping[str, Any],
    *,
    root: Path,
) -> list[dict[str, str]]:
    overlays = _copied_source_overlay_shas(manifest)
    return [
        dict(change)
        for change in changes
        if not _is_unchanged_source_overlay(root, str(change.get("path") or ""), overlays)
    ]


def _filter_run_artifact_status_entries(
    entries: Iterable[Mapping[str, str]],
    *,
    copied_rels: set[str],
    root: Path | None = None,
    source_overlay_shas: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    kept: list[dict[str, str]] = []
    ignored: list[str] = []
    for entry in entries:
        paths = [entry.get("path"), entry.get("original_path")]
        present = [str(path) for path in paths if isinstance(path, str) and path]
        if present and root is not None and all(
            _is_unchanged_source_overlay(root, path, source_overlay_shas or {}) for path in present
        ):
            ignored.extend(Path(path).as_posix() for path in present)
            continue
        if present and all(_is_run_artifact_path(path, copied_rels=copied_rels) for path in present):
            ignored.extend(Path(path).as_posix() for path in present)
            continue
        kept.append(dict(entry))
    return kept, sorted(set(ignored))


def _unit_worktree_statuses(run_id: str, *, data_dir: Path, include_details: bool) -> list[dict[str, Any]]:
    state_path = unit_sessions_path(run_id, data_dir=data_dir)
    if not state_path.is_file():
        return []
    try:
        state = load_unit_sessions(run_id, data_dir=data_dir)
    except Exception:
        return [
            {
                "run_id": run_id,
                "status": "unit_sessions_unreadable",
                "dirty": False,
                "conflict_manifest_present": False,
                "merge_state": "unknown",
            }
        ]
    units: list[dict[str, Any]] = []
    for unit in state.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        root = Path(str(unit.get("worktree_root") or ""))
        dirty_entries = _git_status_entries(root, ".") if (root / ".git").exists() else []
        branch = str(unit.get("branch") or "")
        base_sha = str(unit.get("base_sha") or "")
        ahead = _branch_commits_ahead(root, base_sha, branch) if branch and base_sha and (root / ".git").exists() else []
        conflict_path = unit.get("conflict_manifest_path")
        conflict_present = isinstance(conflict_path, str) and bool(conflict_path) and Path(conflict_path).is_file()
        row = {
            "phase_id": unit.get("phase_id"),
            "unit_id": unit.get("unit_id"),
            "branch": branch,
            "worktree_root": str(root) if str(root) else None,
            "project_root": unit.get("project_root"),
            "merge_state": unit.get("merge_state"),
            "post_writer_status": unit.get("post_writer_status"),
            "spec_review_status": unit.get("spec_review_status"),
            "dirty": bool(dirty_entries),
            "dirty_file_count": len(dirty_entries),
            "branch_ahead_count": len(ahead),
            "conflict_manifest_present": conflict_present,
        }
        if include_details:
            row["dirty_paths"] = [_format_status_entry(entry) for entry in dirty_entries]
            row["unmerged_commits"] = ahead
            row["conflict_manifest_path"] = conflict_path if isinstance(conflict_path, str) else None
        units.append(row)
    return units


def _destination_block_reason(manifest: Mapping[str, Any], operation: Mapping[str, Any]) -> str | None:
    rel = str(operation.get("path") or "")
    destination = Path(str(operation.get("destination_path") or ""))
    if operation.get("action") == "delete" and destination.is_dir():
        return "delete_directory"
    source_git = Path(str(manifest["source_git_root"]))
    git_rel = _source_git_relative_path(manifest, rel)
    if _git_status_entries(source_git, git_rel):
        return "destination_dirty"
    changed = _run_git(
        source_git,
        "diff",
        "--name-only",
        str(manifest["base_sha"]),
        "HEAD",
        "--",
        git_rel,
        check=True,
    ).stdout.strip()
    if changed:
        return "destination_changed_since_base"
    return None


def build_run_worktree_scope_check(
    prepared_artifact: Mapping[str, Any],
    *,
    changed_files: Iterable[Mapping[str, str]],
    blocked_paths: Iterable[Mapping[str, str]],
    adoption_operations: Iterable[Mapping[str, Any]],
    source_project_root: Path,
    safe_project_root: Path,
) -> dict[str, Any]:
    units = _scope_units(prepared_artifact, source_project_root=source_project_root)
    basic_blocks = {str(item.get("path")): str(item.get("reason")) for item in blocked_paths if isinstance(item, Mapping)}
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = [dict(item) for item in blocked_paths if isinstance(item, Mapping)]
    decisions = {"allow": 0, "warn": 0, "block": 0}
    for change in changed_files:
        if not isinstance(change, Mapping):
            continue
        path = str(change.get("path") or "")
        status = str(change.get("status") or "")
        matched_allowed: list[str] = []
        matched_blocked: list[str] = []
        phase_ids: list[str] = []
        work_unit_ids: list[str] = []
        for unit in units:
            allowed = [pattern for pattern in unit["allowed_files"] if _glob_matches(pattern, path)]
            blocked_matches = [pattern for pattern in unit["blocked_files"] if _glob_matches(pattern, path)]
            if allowed or blocked_matches:
                phase_ids.append(unit["phase_id"])
                work_unit_ids.append(unit["work_unit_id"])
                matched_allowed.extend(allowed)
                matched_blocked.extend(blocked_matches)
        decision = "allow"
        reason = None
        if basic_blocks.get(path):
            decision = "block"
            reason = basic_blocks[path]
        elif matched_blocked:
            decision = "block"
            reason = "blocked_files"
            blocked.append({"path": path, "reason": reason})
        elif not matched_allowed:
            decision = "warn"
            reason = "outside_allowed_files"
            warnings.append({"path": path, "reason": reason})
        decisions[decision] += 1
        records.append(
            {
                "path": path,
                "status": status,
                "matching_phase_ids": sorted(set(phase_ids)),
                "matching_work_unit_ids": sorted(set(work_unit_ids)),
                "matched_allowed_patterns": sorted(set(matched_allowed)),
                "matched_blocked_patterns": sorted(set(matched_blocked)),
                "decision": decision,
                "reason": reason,
            }
        )
    return {
        "schema_version": 1,
        "run_id": str(prepared_artifact.get("run_id") or ""),
        "generated_at": utc_now(),
        "source_project_root": str(source_project_root),
        "safe_project_root": str(safe_project_root),
        "changed_files": records,
        "blocked_paths": _dedupe_blocked_paths(blocked),
        "warnings": _dedupe_blocked_paths(warnings),
        "copyback_operations": [dict(item) for item in adoption_operations if isinstance(item, Mapping)],
        "decisions": decisions,
        "enforcement": {
            "blocks": ["path_escape", "data/runs/**", "blocked_files"],
            "warnings": ["outside_allowed_files"],
        },
    }


def validate_run_execution_worktree_manifest(payload: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads(RUN_EXECUTION_WORKTREE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = validate_value(dict(payload), schema)
    if errors:
        raise RunExecutionWorktreeError("run execution worktree manifest schema validation failed: " + "; ".join(errors))


def _normalize_run_worktree_manifest(raw: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    manifest = dict(raw)
    changed = False
    if manifest.get("adoption_state") is None:
        manifest["adoption_state"] = "unadopted"
        changed = True
    elif manifest.get("adoption_state") == "completed":
        manifest["adoption_state"] = "complete_no_changes"
        changed = True
    for key in ("scope_check_path", "conflict_manifest_path", "integration_manifest_path"):
        if key not in manifest:
            manifest[key] = None
            changed = True
    return manifest, changed


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    normalized, _changed = _normalize_run_worktree_manifest(manifest)
    validate_run_execution_worktree_manifest(normalized)
    _atomic_json_write(path, normalized)


def _write_scope_check(path: Path, scope_check: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, dict(scope_check))


def _read_prepared_artifact(run_id: str, *, data_dir: Path) -> dict[str, Any]:
    path = data_dir / "runs" / run_id / "prepared_plan.v1.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"run_id": run_id}
    return payload if isinstance(payload, dict) else {"run_id": run_id}


def _scope_units(prepared_artifact: Mapping[str, Any], *, source_project_root: Path) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    descriptors = prepared_artifact.get("work_unit_artifacts") if isinstance(prepared_artifact.get("work_unit_artifacts"), Mapping) else {}
    for phase_id, descriptor in descriptors.items():
        if not isinstance(descriptor, Mapping):
            continue
        artifact = descriptor.get("artifact") if isinstance(descriptor.get("artifact"), Mapping) else None
        if artifact is None and isinstance(descriptor.get("path"), str):
            artifact = _read_json_mapping(source_project_root / str(descriptor["path"]))
        if artifact is None:
            continue
        for unit in artifact.get("work_units") or []:
            if not isinstance(unit, Mapping):
                continue
            work_unit_id = str(unit.get("id") or f"{phase_id}:unit")
            allowed = unit.get("allowed_files", unit.get("files"))
            blocked = unit.get("blocked_files")
            units.append(
                {
                    "phase_id": str(phase_id),
                    "work_unit_id": work_unit_id,
                    "allowed_files": [str(item) for item in allowed or [] if isinstance(item, str)],
                    "blocked_files": [str(item) for item in blocked or [] if isinstance(item, str)],
                }
            )
    return units


def _read_json_mapping(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _merge_blocked_paths(
    existing: Iterable[Mapping[str, str]],
    additional: Any,
) -> list[dict[str, str]]:
    values: list[dict[str, str]] = [dict(item) for item in existing if isinstance(item, Mapping)]
    if isinstance(additional, list):
        values.extend(dict(item) for item in additional if isinstance(item, Mapping))
    return _dedupe_blocked_paths(values)


def _dedupe_blocked_paths(items: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        path = str(item.get("path") or "")
        reason = str(item.get("reason") or "")
        if not path or not reason:
            continue
        key = (path, reason)
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": path, "reason": reason})
    return out


def _glob_matches(pattern: str, path: str) -> bool:
    posix = Path(path).as_posix()
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(posix, pattern)


def _normalize_scope_path(path: str) -> str:
    return Path(path.strip()).as_posix().lstrip("./")


def _source_git_relative_path(manifest: Mapping[str, Any], project_relative_path: str) -> str:
    project_subdir = str(manifest.get("project_subdir") or "").strip("/")
    return str(Path(project_subdir) / project_relative_path) if project_subdir else project_relative_path


def _git_relative_artifact_path(resolved: ResolvedExecutionWorktree, rel: Path) -> str:
    return str((Path(resolved.project_subdir) / rel) if resolved.project_subdir else rel)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunExecutionWorktreeError(f"run worktree manifest is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RunExecutionWorktreeError(f"run worktree manifest must be an object: {path}")
    manifest, _changed = _normalize_run_worktree_manifest(value)
    validate_run_execution_worktree_manifest(manifest)
    return manifest


def _require_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_manifest(path)
    if manifest is None:
        raise RunExecutionWorktreeError(f"run worktree manifest not found: {path}")
    return manifest


def _dedupe_copy_specs(specs: Iterable[ArtifactCopySpec]) -> tuple[ArtifactCopySpec, ...]:
    result: list[ArtifactCopySpec] = []
    seen: set[str] = set()
    for spec in specs:
        key = str(spec.relative_path)
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
    return tuple(result)


def _assert_not_sensitive(path: Path, *, sensitive_prefixes: Iterable[str]) -> None:
    resolved = Path(path).expanduser().resolve(strict=False)
    for prefix_text in sensitive_prefixes:
        prefix = Path(prefix_text).expanduser().resolve(strict=False)
        try:
            resolved.relative_to(prefix)
        except ValueError:
            continue
        raise RunExecutionWorktreeError(f"safe worktree root resolves inside a sensitive path: {path}")


def _safe_run_worktree_root(data_dir: Path, run_id: str, *, sensitive_prefixes: Iterable[str]) -> Path:
    prefixes = tuple(sensitive_prefixes)
    candidates = [
        Path(data_dir).expanduser() / "worktrees" / run_id,
        _default_worktree_data_dir() / "worktrees" / run_id,
        Path("/tmp") / "swarmdaddy-worktrees" / run_id,
        Path(tempfile.gettempdir()) / "swarmdaddy-worktrees" / run_id,
    ]
    for candidate in _unique_paths(candidates):
        try:
            _assert_not_sensitive(candidate, sensitive_prefixes=prefixes)
        except RunExecutionWorktreeError:
            continue
        return candidate
    raise RunExecutionWorktreeError("no non-sensitive run execution worktree directory is available")


def _default_worktree_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg).expanduser() / "swarmdaddy"


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(Path(path).expanduser())
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(path))
    return tuple(out)


def _git_config_bool(repo: Path, key: str) -> bool:
    result = _run_git(repo, "config", "--bool", "--get", key, check=False)
    if result.returncode != 0:
        return False
    return result.stdout.strip().lower() == "true"


def _branch_exists(repo: Path, branch: str) -> bool:
    return _run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _git(repo: Path, *args: str) -> None:
    _run_git(repo, *args, check=True)


def _git_stdout(repo: Path, *args: str) -> str:
    return _run_git(repo, *args, check=True).stdout.strip()


def _git_lines(repo: Path, *args: str) -> list[str]:
    return [line for line in _git_stdout(repo, *args).splitlines() if line]


def _run_git_stage(repo: Path, paths: Iterable[str]) -> None:
    path_list = [path for path in paths if path]
    if not path_list:
        return
    _run_git_with_env(repo, "add", "--", *path_list, check=True)


def _run_git_with_env(repo: Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "swarm-do"),
        "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "swarm-do@example.invalid"),
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "swarm-do"),
        "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL", "swarm-do@example.invalid"),
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if check and result.returncode != 0:
        raise RunExecutionWorktreeError(_combined_output(result) or f"git {' '.join(args)} failed")
    return result


def _run_git(repo: Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise RunExecutionWorktreeError(_combined_output(result) or f"git {' '.join(args)} failed")
    return result


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def _resolved_path(value: RunExecutionWorktree | ResolvedExecutionWorktree | Mapping[str, Any], *names: str) -> Path:
    for name in names:
        if isinstance(value, Mapping):
            raw = value.get(name)
        else:
            raw = getattr(value, name, None)
        if raw:
            return Path(str(raw))
    raise RunExecutionWorktreeError(f"resolved worktree is missing path field: {'/'.join(names)}")


def _resolved_string(value: RunExecutionWorktree | ResolvedExecutionWorktree | Mapping[str, Any], *names: str) -> str:
    for name in names:
        if isinstance(value, Mapping):
            raw = value.get(name)
        else:
            raw = getattr(value, name, None)
        if isinstance(raw, str):
            return raw
    raise RunExecutionWorktreeError(f"resolved worktree is missing string field: {'/'.join(names)}")


def _project_relative_from_git(path: str, *, project_subdir: str) -> str:
    prefix = project_subdir.strip("/")
    normalized = Path(path).as_posix()
    if prefix and normalized == prefix:
        return ""
    if prefix and normalized.startswith(prefix + "/"):
        return normalized[len(prefix) + 1 :]
    return normalized


def _path_allowed(project_relative_path: str, allowed_files: tuple[str, ...]) -> bool:
    if not allowed_files:
        return False
    return any(fnmatch.fnmatch(project_relative_path, pattern) for pattern in allowed_files)


def _commit_subject(stage_id: str, commit_subject: str) -> str:
    subject = " ".join((commit_subject or "stage artifacts").split())
    prefix = f"{stage_id}: "
    max_subject = 72 - len(prefix)
    if max_subject > 10 and len(subject) > max_subject:
        subject = subject[: max_subject - 3].rstrip() + "..."
    return prefix + subject


def _safe_ref_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not safe or safe in {".", ".."}:
        raise ValueError(f"invalid git ref segment: {value!r}")
    return safe


def _assert_valid_run_id(run_id: str) -> None:
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise RunExecutionWorktreeError(f"invalid run_id: {run_id!r}")


def _sha256_file(path: Path) -> str:
    _raise_if_not_regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy2(source: Path, destination: Path) -> None:
    _raise_if_not_regular_file(source)
    temp_path: Path | None = None
    try:
        with source.open("rb") as src, tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as tmp:
            temp_path = Path(tmp.name)
            shutil.copyfileobj(src, tmp, length=1024 * 1024)
        shutil.copystat(source, temp_path)
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _is_regular_file_no_symlink(path: Path) -> bool:
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode)


def _raise_if_not_regular_file(path: Path) -> None:
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise RunExecutionWorktreeError(f"run artifact is missing: {path}") from exc
    if stat.S_ISLNK(mode):
        raise RunExecutionWorktreeError(f"run artifact must not be a symlink: {path}")
    if not stat.S_ISREG(mode):
        raise RunExecutionWorktreeError(f"run artifact must be a regular file: {path}")


def _atomic_write_bytes(destination: Path, data: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(data)
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "CommitRecord",
    "RunExecutionWorktree",
    "RunExecutionWorktreeAdoptionBlocked",
    "RunExecutionWorktreeError",
    "RunExecutionWorktreeRebuildRequired",
    "adopt_run_worktree",
    "build_run_worktree_scope_check",
    "cleanup_run_worktree",
    "commit_stage_artifacts",
    "execution_branch_name",
    "initialize_unit_sessions",
    "integrate_run_worktree",
    "integration_branch_name",
    "materialize_unit_execution_worktree",
    "merge_unit_execution_worktree",
    "record_unit_post_writer_report",
    "record_unit_spec_review_verdict",
    "materialize_run_execution_worktree",
    "reset_run_worktree",
    "resolve_run_execution_worktree",
    "run_worktree_status",
    "unit_execution_branch_name",
    "unit_execution_worktree_root",
    "validate_run_execution_worktree_manifest",
]
