"""Adopt successful unit-backed stage markers through unit worktrees."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution_worktree import (
    RunExecutionWorktreeError,
    commit_stage_artifacts,
    merge_unit_execution_worktree,
    record_unit_post_writer_report,
    record_unit_spec_review_verdict,
)
from .post_writer import changed_files_from_worktree_diff
from .run_state import utc_now
from .stage_invocation import StageInvocation
from .unit_sessions import find_unit_session, load_unit_sessions


_UNIT_MUTATING_ROLES = {"agent-writer"}


def adopt_unit_stage(
    *,
    run_id: str,
    phase_id: str,
    invocation: StageInvocation,
    stage_result: Mapping[str, Any],
    data_dir: Path,
    workspace_metadata: Mapping[str, Any],
    commit_subject: str,
    writer_summary: str,
    journal_checkpoint: Callable[[str, Mapping[str, Any] | None], None] | None = None,
) -> dict[str, Any] | None:
    """Commit and merge a unit-backed writer stage before stage adoption.

    Non-mutating unit stages keep using the phase-level marker path. The first
    fan-out implementation only commits writer output; review/report stages may
    still produce stage result JSON without mutating the unit worktree.
    """

    if not invocation.work_unit_id or invocation.worktree_path is None:
        return None
    if invocation.agent_role not in _UNIT_MUTATING_ROLES:
        return {"status": "skipped", "reason": "non_mutating_unit_stage", "work_unit_id": invocation.work_unit_id}

    data = Path(data_dir)
    state = load_unit_sessions(run_id, data_dir=data)
    unit = find_unit_session(state, phase_id, invocation.work_unit_id)
    unit_git = Path(str(unit["worktree_root"]))
    project_subdir = str(workspace_metadata.get("project_subdir") or "")
    target = {
        "safe_git_root": str(unit_git),
        "project_subdir": project_subdir,
        "base_sha": str(unit.get("base_sha") or workspace_metadata.get("git_base_sha") or "HEAD"),
    }
    record = commit_stage_artifacts(
        target,
        allowed_files=invocation.allowed_files or ("**/*",),
        run_artifact_excludes=_run_artifact_excludes(run_id, project_subdir=project_subdir),
        commit_subject=commit_subject,
        writer_summary=writer_summary,
        stage_id=invocation.stage_id,
    )
    _checkpoint(
        journal_checkpoint,
        "unit_committed",
        {
            "commit_sha": record.commit_sha,
            "paths_committed": list(record.paths_committed),
            "status": record.status,
        },
    )
    changed_files = changed_files_from_worktree_diff(record.worktree_diff)
    report_path = _write_post_writer_report(
        data,
        run_id=run_id,
        phase_id=phase_id,
        unit_id=invocation.work_unit_id,
        stage_id=invocation.stage_id,
        gate_status="passed",
        changed_files=changed_files,
        stage_result=stage_result,
    )
    record_unit_post_writer_report(run_id, phase_id, invocation.work_unit_id, data_dir=data, report_path=report_path)
    record_unit_spec_review_verdict(run_id, phase_id, invocation.work_unit_id, data_dir=data, verdict="skipped")
    _checkpoint(
        journal_checkpoint,
        "unit_reported",
        {
            "post_writer_report_path": str(report_path),
            "spec_review_verdict": "skipped",
        },
    )
    merged = merge_unit_execution_worktree(run_id, phase_id, invocation.work_unit_id, data_dir=data, apply=True)
    if merged.get("status") not in {"merged", "dry_run"}:
        raise RunExecutionWorktreeError(f"unit adoption did not merge cleanly: {merged.get('status')}")
    _checkpoint(journal_checkpoint, "unit_merged", merged)
    return {
        "status": "merged",
        "work_unit_id": invocation.work_unit_id,
        "commit_sha": record.commit_sha,
        "integration_head_sha": merged.get("integration_head_sha"),
        "paths_committed": list(record.paths_committed),
        "worktree_diff": dict(record.worktree_diff),
        "changed_files": changed_files,
        "post_writer_report_path": str(report_path),
        "merge": merged,
    }


def _write_post_writer_report(
    data_dir: Path,
    *,
    run_id: str,
    phase_id: str,
    unit_id: str,
    stage_id: str,
    gate_status: str,
    changed_files: list[str],
    stage_result: Mapping[str, Any],
) -> Path:
    path = data_dir / "runs" / run_id / "unit_reports" / f"{phase_id}-{unit_id}-{stage_id}.post-writer.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "post_writer_report.v1",
        "run_id": run_id,
        "phase_id": phase_id,
        "unit_id": unit_id,
        "work_unit_id": unit_id,
        "stage_id": stage_id,
        "recorded_at": utc_now(),
        "changed_files": changed_files,
        "summary": str(stage_result.get("summary") or ""),
        "gate": {"status": gate_status, "failure_reasons": [] if gate_status == "passed" else ["unit adoption failed"]},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run_artifact_excludes(run_id: str, *, project_subdir: str) -> list[str]:
    rel = f"data/runs/{run_id}"
    return [str(Path(project_subdir.strip("/")) / rel) if project_subdir.strip("/") else rel]


def _checkpoint(
    callback: Callable[[str, Mapping[str, Any] | None], None] | None,
    checkpoint: str,
    payload: Mapping[str, Any] | None,
) -> None:
    if callback is not None:
        callback(checkpoint, payload)


__all__ = ["adopt_unit_stage"]
