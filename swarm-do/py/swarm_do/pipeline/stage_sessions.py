"""Durable per-stage ledger for controller-owned phase sessions."""

from __future__ import annotations

import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX-only lock primitive.
    fcntl = None  # type: ignore[assignment]

from .paths import REPO_ROOT, resolve_data_dir
from .run_state import _atomic_json_write, utc_now


SCHEMA_VERSION = 1
STATE_FILENAME = "stage_sessions.v1.json"
LOCK_FILENAME = "stage_sessions.v1.lock"

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_ADOPTED = "adopted"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

TERMINAL_STATUSES = {STATUS_ADOPTED, STATUS_FAILED, STATUS_BLOCKED, STATUS_SKIPPED}


class StageSessionError(ValueError):
    """Raised when the stage-session ledger is invalid or cannot transition."""


class StageSessionLockTimeout(TimeoutError):
    """Raised when a stage-session lock cannot be acquired."""


def stage_session_path(run_id: str, phase_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / "phases" / phase_id / STATE_FILENAME


def stage_session_lock_path(run_id: str, phase_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / "phases" / phase_id / LOCK_FILENAME


@contextmanager
def locked_stage_sessions(
    run_id: str,
    phase_id: str,
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = 10,
) -> Iterator[None]:
    if fcntl is None:
        raise StageSessionError("stage-session locks require fcntl")
    lock_path = stage_session_lock_path(run_id, phase_id, data_dir=data_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise StageSessionLockTimeout(f"timed out waiting for {lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def init_stage_sessions(
    run_id: str,
    phase_id: str,
    planned_stages: list[Any],
    graph_snapshot: Mapping[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_stage_sessions(run_id, phase_id, data_dir=base):
        path = stage_session_path(run_id, phase_id, data_dir=base)
        if path.exists():
            existing = load_stage_sessions(run_id, phase_id, data_dir=base)
            if existing.get("graph_hash") == graph_snapshot.get("graph_hash"):
                return {"initialized": False, "state": existing, "state_path": str(path)}
            _archive_existing(path)
        now = utc_now()
        stages = [_stage_record(stage, now) for stage in planned_stages]
        state = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "phase_id": phase_id,
            "graph_hash": str(graph_snapshot.get("graph_hash") or ""),
            "preset_id": graph_snapshot.get("preset_id") if isinstance(graph_snapshot.get("preset_id"), str) else None,
            "topological_layers": _list_of_string_lists(graph_snapshot.get("topological_layers")),
            "fan_out_branches": _string_list_map(graph_snapshot.get("fan_out_branches")),
            "lenses": _string_list_map(graph_snapshot.get("lenses")),
            "failure_tolerance": _string_map(graph_snapshot.get("failure_tolerance")),
            "stages": stages,
            "created_at": now,
            "updated_at": now,
        }
        _validate_state(state)
        _atomic_json_write(path, state)
        return {"initialized": True, "state": state, "state_path": str(path)}


def load_stage_sessions(run_id: str, phase_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    path = stage_session_path(run_id, phase_id, data_dir=data_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise StageSessionError(f"stage-session state is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise StageSessionError("stage-session state root must be an object")
    _validate_state(value)
    return value


def claim_stage(
    run_id: str,
    phase_id: str,
    stage_id: str,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_stage_sessions(run_id, phase_id, data_dir=base):
        state = load_stage_sessions(run_id, phase_id, data_dir=base)
        stage = _find_stage(state, stage_id)
        if stage["status"] in TERMINAL_STATUSES:
            return {"claimed": False, "reason": "terminal", "stage": dict(stage), "state": state}
        if stage["status"] == STATUS_IN_PROGRESS:
            return {"claimed": True, "stage": dict(stage), "state": state}
        if stage["status"] != STATUS_PENDING:
            raise StageSessionError(f"stage {stage_id} cannot be claimed from {stage['status']}")
        stage["status"] = STATUS_IN_PROGRESS
        stage["attempt"] = int(stage.get("attempt") or 0) + 1
        stage["started_at"] = utc_now()
        _touch_and_write(base, run_id, phase_id, state)
        return {"claimed": True, "stage": dict(stage), "state": state}


def record_stage_adopted(
    run_id: str,
    phase_id: str,
    stage_id: str,
    *,
    commit_sha: str | None,
    result_path: str | Path | None,
    transcript_path: str | Path | None = None,
    notes: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return _record_terminal(
        run_id,
        phase_id,
        stage_id,
        status=STATUS_ADOPTED,
        commit_sha=commit_sha,
        result_path=str(result_path) if result_path else None,
        transcript_path=str(transcript_path) if transcript_path else None,
        failure_kind=None,
        notes=notes,
        data_dir=data_dir,
    )


def record_stage_blocked(
    run_id: str,
    phase_id: str,
    stage_id: str,
    failure_kind: str,
    notes: str | None = None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return _record_terminal(
        run_id,
        phase_id,
        stage_id,
        status=STATUS_BLOCKED,
        commit_sha=None,
        result_path=None,
        transcript_path=None,
        failure_kind=failure_kind,
        notes=notes,
        data_dir=data_dir,
    )


def record_stage_failed(
    run_id: str,
    phase_id: str,
    stage_id: str,
    failure_kind: str,
    notes: str | None = None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return _record_terminal(
        run_id,
        phase_id,
        stage_id,
        status=STATUS_FAILED,
        commit_sha=None,
        result_path=None,
        transcript_path=None,
        failure_kind=failure_kind,
        notes=notes,
        data_dir=data_dir,
    )


def record_stage_retry_requested(
    run_id: str,
    phase_id: str,
    stage_id: str,
    failure_kind: str,
    notes: str | None = None,
    *,
    data_dir: Path | None = None,
    fresh_reviewer: bool = True,
) -> dict[str, Any]:
    """Record a retryable stage failure without making the stage terminal."""

    base = data_dir or resolve_data_dir()
    with locked_stage_sessions(run_id, phase_id, data_dir=base):
        state = load_stage_sessions(run_id, phase_id, data_dir=base)
        stage = _find_stage(state, stage_id)
        if stage["status"] in TERMINAL_STATUSES:
            return {"recorded": False, "reason": "already_terminal", "stage": dict(stage), "state": state}
        if stage["status"] == STATUS_PENDING:
            stage["attempt"] = int(stage.get("attempt") or 0) + 1
            stage["started_at"] = stage.get("started_at") or utc_now()
        stage["status"] = STATUS_PENDING
        stage["failure_kind"] = failure_kind
        stage["notes"] = notes
        stage["retry_cycle_count"] = int(stage.get("attempt") or 0)
        stage["fresh_reviewer_required"] = bool(fresh_reviewer)
        stage["last_retry_requested_at"] = utc_now()
        stage["closed_at"] = None
        _touch_and_write(base, run_id, phase_id, state)
        return {"recorded": True, "stage": dict(stage), "state": state}


def record_stage_skipped(
    run_id: str,
    phase_id: str,
    stage_id: str,
    notes: str | None = None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return _record_terminal(
        run_id,
        phase_id,
        stage_id,
        status=STATUS_SKIPPED,
        commit_sha=None,
        result_path=None,
        transcript_path=None,
        failure_kind=None,
        notes=notes,
        data_dir=data_dir,
    )


def assign_stage_bead(
    run_id: str,
    phase_id: str,
    stage_id: str,
    bead_id: str | None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_stage_sessions(run_id, phase_id, data_dir=base):
        state = load_stage_sessions(run_id, phase_id, data_dir=base)
        stage = _find_stage(state, stage_id)
        stage["bead_id"] = bead_id
        _touch_and_write(base, run_id, phase_id, state)
        return {"assigned": True, "stage": dict(stage), "state": state}


def next_resumable_stage(run_id: str, phase_id: str, *, data_dir: Path | None = None) -> dict[str, Any] | None:
    state = load_stage_sessions(run_id, phase_id, data_dir=data_dir)
    for stage in state.get("stages") or []:
        if isinstance(stage, Mapping) and stage.get("status") not in TERMINAL_STATUSES:
            return dict(stage)
    return None


def stage_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    stages = [stage for stage in state.get("stages") or [] if isinstance(stage, Mapping)]
    return {
        "stage_count": len(stages),
        "adopted": sum(1 for stage in stages if stage.get("status") == STATUS_ADOPTED),
        "failed": sum(1 for stage in stages if stage.get("status") == STATUS_FAILED),
        "blocked": sum(1 for stage in stages if stage.get("status") == STATUS_BLOCKED),
        "skipped": sum(1 for stage in stages if stage.get("status") == STATUS_SKIPPED),
    }


def _record_terminal(
    run_id: str,
    phase_id: str,
    stage_id: str,
    *,
    status: str,
    commit_sha: str | None,
    result_path: str | None,
    transcript_path: str | None,
    failure_kind: str | None,
    notes: str | None,
    data_dir: Path | None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_stage_sessions(run_id, phase_id, data_dir=base):
        state = load_stage_sessions(run_id, phase_id, data_dir=base)
        stage = _find_stage(state, stage_id)
        if stage["status"] in TERMINAL_STATUSES and stage["status"] == status:
            updated = _fill_terminal_fields(
                stage,
                commit_sha=commit_sha,
                result_path=result_path,
                transcript_path=transcript_path,
                failure_kind=failure_kind,
                notes=notes,
            )
            if updated:
                _touch_and_write(base, run_id, phase_id, state)
            return {
                "recorded": updated,
                "reason": "already_terminal_updated" if updated else "already_terminal",
                "stage": dict(stage),
                "state": state,
            }
        if stage["status"] == STATUS_PENDING:
            stage["attempt"] = int(stage.get("attempt") or 0) + 1
            stage["started_at"] = stage.get("started_at") or utc_now()
        stage["status"] = status
        stage["commit_sha"] = commit_sha
        stage["result_path"] = result_path
        stage["transcript_path"] = transcript_path
        stage["failure_kind"] = failure_kind
        stage["notes"] = notes
        stage["fresh_reviewer_required"] = False
        stage["closed_at"] = utc_now()
        _touch_and_write(base, run_id, phase_id, state)
        return {"recorded": True, "stage": dict(stage), "state": state}


def _fill_terminal_fields(
    stage: dict[str, Any],
    *,
    commit_sha: str | None,
    result_path: str | None,
    transcript_path: str | None,
    failure_kind: str | None,
    notes: str | None,
) -> bool:
    updated = False
    for key, value in (
        ("commit_sha", commit_sha),
        ("result_path", result_path),
        ("transcript_path", transcript_path),
        ("failure_kind", failure_kind),
        ("notes", notes),
    ):
        if value is not None and not stage.get(key):
            stage[key] = value
            updated = True
    if updated and not stage.get("closed_at"):
        stage["closed_at"] = utc_now()
    return updated


def _stage_record(stage: Any, now: str) -> dict[str, Any]:
    def get(name: str, default: Any = None) -> Any:
        if isinstance(stage, Mapping):
            return stage.get(name, default)
        return getattr(stage, name, default)

    return {
        "stage_id": str(get("stage_id")),
        "agent_role": str(get("agent_role")),
        "subagent_type": _str_or_none(get("subagent_type")),
        "work_unit_id": _str_or_none(get("work_unit_id")),
        "worktree_path": str(get("worktree_path")) if get("worktree_path") else None,
        "allowed_files": [str(item) for item in (get("allowed_files", ()) or ())],
        "acceptance_criteria": str(get("acceptance_criteria", "")),
        "layer_index": _int_or_none(get("layer_index")),
        "fan_out_key": _str_or_none(get("fan_out_key")),
        "fan_out_index": _int_or_none(get("fan_out_index")),
        "merge_target": _str_or_none(get("merge_target")),
        "is_provider_stage": bool(get("is_provider_stage", False)),
        "lens_chain": [str(item) for item in (get("lens_chain", ()) or ())],
        "failure_tolerance": str(get("failure_tolerance", "strict")),
        "upstream_stage_ids": [str(item) for item in (get("upstream_stage_ids", ()) or ())],
        "bead_id": None,
        "status": STATUS_PENDING,
        "attempt": 0,
        "task_prompt_path": str(get("task_prompt_path")) if get("task_prompt_path") else None,
        "transcript_path": None,
        "result_path": str(get("expected_result_path")) if get("expected_result_path") else None,
        "commit_sha": None,
        "failure_kind": None,
        "notes": None,
        "retry_cycle_count": 0,
        "fresh_reviewer_required": False,
        "last_retry_requested_at": None,
        "started_at": None,
        "closed_at": None,
        "retry_after_seconds": None,
        "created_at": now,
    }


def _find_stage(state: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in state.get("stages") or []:
        if isinstance(stage, dict) and stage.get("stage_id") == stage_id:
            return stage
    raise StageSessionError(f"stage not found: {stage_id}")


def _touch_and_write(base: Path, run_id: str, phase_id: str, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    _validate_state(state)
    _atomic_json_write(stage_session_path(run_id, phase_id, data_dir=base), state)


def _archive_existing(path: Path) -> None:
    archive_dir = path.parent / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{path.name}.{int(time.time())}"
    shutil.copy2(path, target)


def _validate_state(state: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads((REPO_ROOT / "schemas" / "stage_sessions.schema.json").read_text(encoding="utf-8"))
    errors = validate_value(dict(state), schema)
    if errors:
        raise StageSessionError("stage-session state schema invalid: " + "; ".join(errors))


def _list_of_string_lists(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    out: list[list[str]] = []
    for item in value:
        if isinstance(item, list):
            out.append([str(inner) for inner in item if isinstance(inner, str)])
    return out


def _string_list_map(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): [str(item) for item in items if isinstance(item, str)]
        for key, items in value.items()
        if isinstance(items, list)
    }


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "StageSessionError",
    "assign_stage_bead",
    "claim_stage",
    "init_stage_sessions",
    "load_stage_sessions",
    "next_resumable_stage",
    "record_stage_adopted",
    "record_stage_blocked",
    "record_stage_failed",
    "record_stage_retry_requested",
    "record_stage_skipped",
    "stage_session_path",
    "stage_summary",
]
