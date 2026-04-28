"""Durable orchestration state helpers for swarm-do runs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_data_dir


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def active_run_path(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "active-run.json"


def checkpoint_path(data_dir: Path, run_id: str) -> Path:
    return data_dir / "runs" / run_id / "checkpoint.v1.json"


def write_active_run(path: str | os.PathLike[str], state: Mapping[str, Any]) -> Path:
    """Atomically write the canonical dispatcher-owned active run record."""

    target = Path(path)
    payload = _active_run_payload(state)
    _atomic_json_write(target, payload)
    return target


def load_active_run(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def clear_active_run(path: str | os.PathLike[str]) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def append_run_event(data_dir: str | os.PathLike[str], row: Mapping[str, Any]) -> Path:
    """Append one normalized row to telemetry/run_events.jsonl."""

    base = Path(data_dir)
    telemetry = base / "telemetry"
    telemetry.mkdir(parents=True, exist_ok=True)
    path = telemetry / "run_events.jsonl"
    payload = dict(row)
    payload.setdefault("timestamp", utc_now())
    payload.setdefault("schema_ok", True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def write_checkpoint_from_active(
    data_dir: str | os.PathLike[str],
    active_state: Mapping[str, Any],
    *,
    source: str,
    reason: str,
) -> Path | None:
    """Persist checkpoint.v1.json and append the matching run_event row."""

    base = Path(data_dir)
    run_id = active_state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None

    written_at = utc_now()
    checkpoint = {
        "schema_version": SCHEMA_VERSION,
        "written_at": written_at,
        "source": source,
        "run_id": run_id,
        "bd_epic_id": active_state.get("bd_epic_id"),
        "phase_id": active_state.get("phase_id"),
        "child_bead_ids": _string_list(active_state.get("child_bead_ids")),
        "work_units": _work_units(active_state.get("work_units")),
        "handoff_counts": _dict_or_empty(active_state.get("handoff_counts")),
        "retry_counts": _dict_or_empty(active_state.get("retry_counts")),
        "integration_branch_head": active_state.get("integration_branch_head"),
        "status": active_state.get("status", "incomplete"),
        "prepared_artifact_path": active_state.get("prepared_artifact_path"),
        "prepared_plan_path": active_state.get("prepared_plan_path"),
        "prepared_inspect_path": active_state.get("prepared_inspect_path"),
        "phase_map": _dict_list(active_state.get("phase_map")),
        "review_findings": _dict_list(active_state.get("review_findings")),
        "work_unit_artifacts": _dict_or_empty(active_state.get("work_unit_artifacts")),
    }
    path = checkpoint_path(base, run_id)
    _atomic_json_write(path, checkpoint)

    append_run_event(
        base,
        {
            "run_id": run_id,
            "timestamp": written_at,
            "event_type": "checkpoint_written",
            "bd_epic_id": checkpoint["bd_epic_id"],
            "phase_id": checkpoint["phase_id"],
            "work_unit_id": _resume_work_unit_id(checkpoint["work_units"]),
            "child_bead_ids": checkpoint["child_bead_ids"],
            "reason": reason,
            "retry_count": None,
            "handoff_count": None,
            "integration_branch_head": checkpoint["integration_branch_head"],
            "details": {"checkpoint_path": str(path), "source": source},
            "schema_ok": True,
        },
    )
    return path


def _active_run_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "run_id": state.get("run_id"),
        "bd_epic_id": state.get("bd_epic_id"),
        "phase_id": state.get("phase_id"),
        "child_bead_ids": _string_list(state.get("child_bead_ids")),
        "work_units": _work_units(state.get("work_units")),
        "retry_counts": _dict_or_empty(state.get("retry_counts")),
        "handoff_counts": _dict_or_empty(state.get("handoff_counts")),
        "integration_branch_head": state.get("integration_branch_head"),
        "status": state.get("status", "incomplete"),
        "prepared_artifact_path": state.get("prepared_artifact_path"),
        "prepared_plan_path": state.get("prepared_plan_path"),
        "prepared_inspect_path": state.get("prepared_inspect_path"),
        "phase_map": _dict_list(state.get("phase_map")),
        "review_findings": _dict_list(state.get("review_findings")),
        "work_unit_artifacts": _dict_or_empty(state.get("work_unit_artifacts")),
    }
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise ValueError("active run state requires run_id")
    return payload


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _work_units(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    units: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            units.append(dict(item))
        elif isinstance(item, str):
            units.append({"id": item, "status": "pending"})
    return units


def _resume_work_unit_id(work_units: list[dict[str, Any]]) -> str | None:
    for unit in work_units:
        if unit.get("status") not in {"complete", "completed", "approved"}:
            value = unit.get("id") or unit.get("work_unit_id")
            return value if isinstance(value, str) else None
    return None
