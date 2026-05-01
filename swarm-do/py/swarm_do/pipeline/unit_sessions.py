"""Durable unit-session state for data-dir unit worktrees."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT
from .run_state import _atomic_json_write, utc_now


class UnitSessionError(RuntimeError):
    """Raised when durable unit-session state is missing or invalid."""


UNIT_SESSIONS_SCHEMA_PATH = REPO_ROOT / "schemas" / "unit_sessions.schema.json"
_RUN_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def unit_sessions_path(run_id: str, *, data_dir: Path) -> Path:
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise UnitSessionError(f"invalid run_id: {run_id!r}")
    return Path(data_dir) / "runs" / run_id / "unit_sessions.v1.json"


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
    validate_unit_sessions(value)
    return value


def write_unit_sessions(payload: Mapping[str, Any], *, data_dir: Path) -> dict[str, Any]:
    state = dict(payload)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        raise UnitSessionError("unit sessions require run_id")
    state["updated_at"] = utc_now()
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
        "post_writer_report_path": None,
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


__all__ = [
    "UNIT_SESSIONS_SCHEMA_PATH",
    "UnitSessionError",
    "find_unit_session",
    "load_unit_sessions",
    "replace_unit_session",
    "unit_session_template",
    "unit_sessions_path",
    "validate_unit_sessions",
    "write_unit_sessions",
]
