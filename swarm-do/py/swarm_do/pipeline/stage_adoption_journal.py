"""Crash-safe adoption checkpoints for controller-owned stage results."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .run_state import _atomic_json_write, utc_now
from .stage_invocation import StageInvocation
from .orchestrator_stream import StageMarker


CHECKPOINT_ORDER = (
    "marker_seen",
    "result_validated",
    "unit_committed",
    "unit_reported",
    "unit_merged",
    "stage_recorded",
    "bead_closed",
    "event_appended",
)


def adoption_journal_dir(data_dir: Path, run_id: str, phase_id: str) -> Path:
    return Path(data_dir) / "runs" / run_id / "phases" / phase_id / "stage_adoptions"


def adoption_journal_path(
    data_dir: Path,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    stage_id: str,
    *,
    result_path: str | None = None,
) -> Path:
    suffix = f".{_result_path_key(result_path)}" if result_path else ""
    name = f"attempt-{int(phase_attempt)}.{_safe_filename(stage_id)}{suffix}.journal.json"
    return adoption_journal_dir(data_dir, run_id, phase_id) / name


def start_adoption_journal(
    *,
    data_dir: Path,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    marker: StageMarker,
    invocation: StageInvocation,
) -> dict[str, Any]:
    path = adoption_journal_path(
        data_dir,
        run_id,
        phase_id,
        phase_attempt,
        marker.stage_id,
        result_path=marker.result_path,
    )
    existing = _read_journal(path)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": int(phase_attempt),
        "stage_id": marker.stage_id,
        "result_path": marker.result_path,
        "expected_result_path": str(invocation.expected_result_path),
        "work_unit_id": invocation.work_unit_id,
        "worktree_path": str(invocation.worktree_path) if invocation.worktree_path else None,
        "bead_id": invocation.bead_id,
        "allowed_files": list(invocation.allowed_files),
        "marker": marker.to_dict(),
        "checkpoints": dict(existing.get("checkpoints") or {}) if isinstance(existing, Mapping) else {},
        "completed": bool(existing.get("completed")) if isinstance(existing, Mapping) else False,
        "created_at": existing.get("created_at") if isinstance(existing, Mapping) and existing.get("created_at") else utc_now(),
        "updated_at": utc_now(),
    }
    payload["checkpoints"].setdefault("marker_seen", {"recorded_at": utc_now(), "payload": {}})
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, payload)
    return payload


def checkpoint_adoption_journal(
    *,
    data_dir: Path,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    stage_id: str,
    checkpoint: str,
    payload: Mapping[str, Any] | None = None,
    completed: bool | None = None,
) -> dict[str, Any]:
    if checkpoint not in CHECKPOINT_ORDER:
        raise ValueError(f"unknown adoption checkpoint: {checkpoint}")
    path = _existing_journal_path(
        data_dir,
        run_id,
        phase_id,
        phase_attempt,
        stage_id,
        result_path=_optional_str(payload.get("result_path")) if payload is not None else None,
    )
    journal = _read_journal(path)
    if not journal:
        journal = {
            "schema_version": 1,
            "run_id": run_id,
            "phase_id": phase_id,
            "phase_attempt": int(phase_attempt),
            "stage_id": stage_id,
            "checkpoints": {},
            "completed": False,
            "created_at": utc_now(),
        }
    checkpoints = dict(journal.get("checkpoints") or {})
    checkpoints[checkpoint] = {"recorded_at": utc_now(), "payload": dict(payload or {})}
    journal["checkpoints"] = checkpoints
    if completed is not None:
        journal["completed"] = bool(completed)
    journal["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, journal)
    return journal


def incomplete_adoption_journals(
    *,
    data_dir: Path,
    run_id: str,
    phase_id: str,
    phase_attempt: int | None = None,
) -> list[dict[str, Any]]:
    root = adoption_journal_dir(data_dir, run_id, phase_id)
    if not root.is_dir():
        return []
    journals: list[dict[str, Any]] = []
    for path in sorted(root.glob("attempt-*.journal.json")):
        payload = _read_journal(path)
        if not payload or payload.get("completed") is True:
            continue
        if phase_attempt is not None and int(payload.get("phase_attempt") or 0) != int(phase_attempt):
            continue
        payload["_path"] = str(path)
        journals.append(payload)
    return journals


def marker_from_journal(journal: Mapping[str, Any]) -> StageMarker | None:
    raw_marker = journal.get("marker")
    if not isinstance(raw_marker, Mapping):
        return None
    raw = raw_marker.get("raw")
    raw_mapping = dict(raw) if isinstance(raw, Mapping) else {}
    kind = raw_marker.get("kind")
    stage_id = raw_marker.get("stage_id")
    if kind not in {"complete", "failed"} or not isinstance(stage_id, str) or not stage_id:
        return None
    return StageMarker(
        kind=str(kind),
        stage_id=stage_id,
        result_path=_optional_str(raw_marker.get("result_path")),
        failure_kind=_optional_str(raw_marker.get("failure_kind")),
        notes=_optional_str(raw_marker.get("notes")),
        commit_subject=_optional_str(raw_marker.get("commit_subject")),
        summary=_optional_str(raw_marker.get("summary")),
        raw=raw_mapping,
    )


def _existing_journal_path(
    data_dir: Path,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    stage_id: str,
    *,
    result_path: str | None = None,
) -> Path:
    if result_path:
        path = adoption_journal_path(
            data_dir,
            run_id,
            phase_id,
            phase_attempt,
            stage_id,
            result_path=result_path,
        )
        if path.exists():
            return path
    root = adoption_journal_dir(data_dir, run_id, phase_id)
    pattern = f"attempt-{int(phase_attempt)}.{_safe_filename(stage_id)}.*.journal.json"
    matches = sorted(root.glob(pattern)) if root.is_dir() else []
    if matches:
        return matches[0]
    return adoption_journal_path(
        data_dir,
        run_id,
        phase_id,
        phase_attempt,
        stage_id,
        result_path=result_path,
    )


def _read_journal(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise ValueError(f"adoption journal unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"adoption journal invalid: {path}: root must be an object")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "stage"


def _result_path_key(value: str | None) -> str:
    return sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


__all__ = [
    "adoption_journal_path",
    "checkpoint_adoption_journal",
    "incomplete_adoption_journals",
    "marker_from_journal",
    "start_adoption_journal",
]
