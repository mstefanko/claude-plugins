"""Run-scoped shared decisions for phase-session context rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_data_dir
from .run_state import _atomic_json_write, utc_now


SCHEMA_VERSION = 1
SHARED_DECISIONS_FILENAME = "shared_decisions.v1.json"


def shared_decisions_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / SHARED_DECISIONS_FILENAME


def add_shared_decision(
    run_id: str,
    *,
    source_phase_id: str,
    text: str,
    applies_to_phase_ids: list[str],
    reason: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Append a controller-promoted shared decision to the run sidecar."""

    if not source_phase_id:
        raise ValueError("source_phase_id is required")
    if not text or not text.strip():
        raise ValueError("decision text is required")
    applies = [item for item in applies_to_phase_ids if item]
    if not applies:
        raise ValueError("at least one applies-to phase id or '*' is required")
    path = shared_decisions_path(run_id, data_dir=data_dir)
    payload = _load_or_empty(path, run_id)
    decisions = payload.setdefault("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("shared decisions sidecar decisions must be a list")
    decision = {
        "id": f"decision-{len(decisions) + 1:03d}",
        "source_phase_id": source_phase_id,
        "created_at": utc_now(),
        "text": text.strip(),
        "applies_to_phase_ids": applies,
        "reason": reason,
    }
    decisions.append(decision)
    _validate_shared_decisions(payload, run_id)
    _atomic_json_write(path, payload)
    return {"path": str(path), "decision": decision, "payload": payload}


def load_shared_decisions(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any] | None:
    path = shared_decisions_path(run_id, data_dir=data_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"shared decisions sidecar is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("shared decisions sidecar root must be an object")
    _validate_shared_decisions(payload, run_id)
    return payload


def render_shared_decisions_markdown(
    run_id: str,
    *,
    phase_id: str,
    data_dir: Path | None = None,
) -> str:
    payload = load_shared_decisions(run_id, data_dir=data_dir)
    if payload is None:
        return "No shared decisions.\n"
    decisions = [
        item
        for item in payload.get("decisions") or []
        if isinstance(item, Mapping) and _applies_to_phase(item, phase_id)
    ]
    if not decisions:
        return "No shared decisions.\n"
    lines = ["# Shared Decisions"]
    for item in decisions:
        lines.append("")
        lines.append(f"- {item.get('text')}")
        lines.append(f"  source_phase_id: {item.get('source_phase_id')}")
        if item.get("reason"):
            lines.append(f"  reason: {item.get('reason')}")
    return "\n".join(lines).rstrip() + "\n"


def _load_or_empty(path: Path, run_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "decisions": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("shared decisions sidecar root must be an object")
    _validate_shared_decisions(payload, run_id)
    return payload


def _validate_shared_decisions(payload: Mapping[str, Any], run_id: str) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("shared decisions schema_version must be 1")
    if payload.get("run_id") != run_id:
        raise ValueError("shared decisions run_id mismatch")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("shared decisions decisions must be a list")
    for idx, item in enumerate(decisions):
        if not isinstance(item, Mapping):
            raise ValueError(f"shared decisions decisions[{idx}] must be an object")
        for key in ("id", "source_phase_id", "created_at", "text"):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValueError(f"shared decisions decisions[{idx}].{key} must be a non-empty string")
        applies = item.get("applies_to_phase_ids")
        if not isinstance(applies, list) or not all(isinstance(value, str) and value for value in applies):
            raise ValueError(f"shared decisions decisions[{idx}].applies_to_phase_ids must be non-empty strings")
        if item.get("reason") is not None and not isinstance(item.get("reason"), str):
            raise ValueError(f"shared decisions decisions[{idx}].reason must be string or null")


def _applies_to_phase(item: Mapping[str, Any], phase_id: str) -> bool:
    applies = item.get("applies_to_phase_ids") or []
    return "*" in applies or phase_id in applies


__all__ = [
    "SHARED_DECISIONS_FILENAME",
    "add_shared_decision",
    "load_shared_decisions",
    "render_shared_decisions_markdown",
    "shared_decisions_path",
]
