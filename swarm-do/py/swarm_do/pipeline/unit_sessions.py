"""Durable unit-session state for data-dir unit worktrees."""

from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX-only lock primitive.
    fcntl = None  # type: ignore[assignment]

from .paths import REPO_ROOT
from .run_state import _atomic_json_write, utc_now


class UnitSessionError(RuntimeError):
    """Raised when durable unit-session state is missing or invalid."""


class UnitSessionLockTimeout(TimeoutError):
    """Raised when the unit-session state lock cannot be acquired."""


UNIT_SESSIONS_SCHEMA_PATH = REPO_ROOT / "schemas" / "unit_sessions.schema.json"
_RUN_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
LOCK_FILENAME = "unit_sessions.v1.lock"


def unit_sessions_path(run_id: str, *, data_dir: Path) -> Path:
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise UnitSessionError(f"invalid run_id: {run_id!r}")
    return Path(data_dir) / "runs" / run_id / "unit_sessions.v1.json"


def unit_sessions_lock_path(run_id: str, *, data_dir: Path) -> Path:
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise UnitSessionError(f"invalid run_id: {run_id!r}")
    return Path(data_dir) / "runs" / run_id / LOCK_FILENAME


@contextmanager
def locked_unit_sessions(
    run_id: str,
    *,
    data_dir: Path,
    timeout_seconds: float = 10.0,
) -> Iterator[None]:
    """Hold the sibling advisory unit-session lock for a short transaction."""

    if fcntl is None:
        raise UnitSessionError("unit-session locks require POSIX fcntl.flock")
    lock_path = unit_sessions_lock_path(run_id, data_dir=data_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise UnitSessionLockTimeout(
                        f"timed out waiting for unit-session lock for run {run_id}: {lock_path}"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_unit_sessions(payload: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads(UNIT_SESSIONS_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = validate_value(dict(payload), schema)
    if errors:
        raise UnitSessionError("unit sessions schema validation failed: " + "; ".join(errors))


def load_unit_sessions(run_id: str, *, data_dir: Path) -> dict[str, Any]:
    path = unit_sessions_path(run_id, data_dir=data_dir)
    if not path.is_file():
        raise UnitSessionError(f"unit sessions not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UnitSessionError(f"unit sessions are not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise UnitSessionError(f"unit sessions must be an object: {path}")
    _normalize_unit_sessions(value)
    validate_unit_sessions(value)
    return value


def write_unit_sessions(payload: Mapping[str, Any], *, data_dir: Path) -> dict[str, Any]:
    state = dict(payload)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        raise UnitSessionError("unit sessions require run_id")
    state["updated_at"] = utc_now()
    _normalize_unit_sessions(state)
    validate_unit_sessions(state)
    path = unit_sessions_path(run_id, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, state)
    return state


def find_unit_session(state: Mapping[str, Any], phase_id: str, unit_id: str) -> dict[str, Any]:
    for unit in state.get("units") or []:
        if (
            isinstance(unit, Mapping)
            and unit.get("phase_id") == phase_id
            and unit.get("unit_id") == unit_id
        ):
            return dict(unit)
    raise UnitSessionError(f"unit session not found: phase={phase_id} unit={unit_id}")


def replace_unit_session(
    state: Mapping[str, Any],
    phase_id: str,
    unit_id: str,
    updated_unit: Mapping[str, Any],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    replaced = False
    for unit in state.get("units") or []:
        if (
            isinstance(unit, Mapping)
            and unit.get("phase_id") == phase_id
            and unit.get("unit_id") == unit_id
        ):
            units.append(dict(updated_unit))
            replaced = True
        elif isinstance(unit, Mapping):
            units.append(dict(unit))
    if not replaced:
        raise UnitSessionError(f"unit session not found: phase={phase_id} unit={unit_id}")
    next_state = dict(state)
    next_state["units"] = units
    return next_state


def unit_session_template(
    *,
    phase_id: str,
    unit_id: str,
    branch: str,
    worktree_root: Path,
    project_root: Path,
    base_sha: str,
    base_ref: str,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    return {
        "phase_id": phase_id,
        "unit_id": unit_id,
        "branch": branch,
        "worktree_root": str(worktree_root),
        "project_root": str(project_root),
        "base_sha": base_sha,
        "base_ref": base_ref,
        "lease_owner": None,
        "lease_host": None,
        "lease_pid": None,
        "lease_command": None,
        "lease_expires_at": None,
        "attempt": 0,
        "writer_status": "pending",
        "post_writer_status": "pending",
        "post_writer_gate_reasons": [],
        "post_writer_report_path": None,
        "post_writer_report_sha256": None,
        "post_writer_unit_head_sha": None,
        "post_writer_base_sha": None,
        "spec_review_status": "pending",
        "spec_review_report_path": None,
        "spec_review_report_sha256": None,
        "spec_review_unit_head_sha": None,
        "spec_review_recorded_at": None,
        "scope_check_path": None,
        "merge_state": "pending",
        "merge_target_branch": None,
        "conflict_manifest_path": None,
        "attempt_history": [],
        "cleanup_state": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
    }


def _normalize_unit_sessions(state: dict[str, Any]) -> None:
    for unit in state.get("units") or []:
        if not isinstance(unit, dict):
            continue
        writer_status = unit.get("writer_status")
        if writer_status == "approved":
            default_post_writer = "passed"
        elif writer_status in {"blocked", "failed"}:
            default_post_writer = "failed"
        else:
            default_post_writer = "pending"
        unit.setdefault("post_writer_status", default_post_writer)
        if not isinstance(unit.get("post_writer_gate_reasons"), list):
            unit["post_writer_gate_reasons"] = []
        unit.setdefault("post_writer_report_sha256", None)
        unit.setdefault("post_writer_unit_head_sha", None)
        unit.setdefault("post_writer_base_sha", None)
        unit.setdefault("spec_review_status", "pending")
        unit.setdefault("spec_review_report_path", None)
        unit.setdefault("spec_review_report_sha256", None)
        unit.setdefault("spec_review_unit_head_sha", None)
        unit.setdefault("spec_review_recorded_at", None)
        unit.setdefault("writer_status", _writer_alias_from_post_writer(unit.get("post_writer_status")))
        unit.setdefault("merge_state", _derive_merge_state(unit))


def _writer_alias_from_post_writer(status: Any) -> str:
    if status == "passed":
        return "approved"
    if status == "failed":
        return "blocked"
    return "pending"


def _derive_merge_state(unit: Mapping[str, Any]) -> str:
    if unit.get("merge_state") in {"merged", "conflicted"}:
        return str(unit["merge_state"])
    if unit.get("post_writer_status") == "failed" or unit.get("spec_review_status") == "rejected":
        return "blocked"
    if unit.get("post_writer_status") == "passed" and unit.get("spec_review_status") in {"approved", "skipped"}:
        return "ready"
    return "pending"


__all__ = [
    "UNIT_SESSIONS_SCHEMA_PATH",
    "UnitSessionError",
    "UnitSessionLockTimeout",
    "find_unit_session",
    "load_unit_sessions",
    "locked_unit_sessions",
    "replace_unit_session",
    "unit_session_template",
    "unit_sessions_lock_path",
    "unit_sessions_path",
    "validate_unit_sessions",
    "write_unit_sessions",
]
