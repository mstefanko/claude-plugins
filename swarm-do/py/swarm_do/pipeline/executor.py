"""Deterministic work-unit executor planning helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .validation import schema_lint_work_units
from .work_units import topological_work_unit_layers


COMPLETE_STATUSES = {"approved", "merged"}
INCOMPLETE_STATUSES = {"pending", "running", "blocked", "failed"}
WORKER_LOCAL_UPDATE = "child_note"
COORDINATOR_UPDATE_KINDS = {
    "child_note",
    "cross_unit_summary",
    "merge_state",
    "retry_state",
    "phase_completion",
    "run_event",
}


def load_work_units(path: str | Path) -> dict[str, Any]:
    """Load and fail-closed validate a persisted work_units.v1 artifact."""

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"work-unit artifact not found: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"work-unit artifact is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("work-unit artifact root must be an object")
    errors = schema_lint_work_units(value)
    if errors:
        raise ValueError("invalid work-unit artifact: " + "; ".join(errors))
    topological_work_unit_layers(value)
    return value


def ready_work_units(artifact: Mapping[str, Any], unit_state: Mapping[str, Any] | None = None) -> list[str]:
    """Return the currently executable pending units in stable topological order."""

    state = unit_state or {}
    ready: list[str] = []
    unit_by_id = _unit_by_id(artifact)
    for layer in topological_work_unit_layers(artifact):
        for unit_id in layer:
            if _status(unit_by_id[unit_id], state) != "pending":
                continue
            deps = unit_by_id[unit_id].get("depends_on") or []
            if all(_status(unit_by_id[dep], state) in COMPLETE_STATUSES for dep in deps):
                ready.append(unit_id)
        if ready:
            break
    return ready


def execution_batches(
    artifact: Mapping[str, Any],
    unit_state: Mapping[str, Any] | None = None,
    parallelism: int = 1,
) -> list[list[str]]:
    """Split the next ready wave into deterministic batches capped by parallelism."""

    cap = parallelism if isinstance(parallelism, int) and parallelism >= 1 else 1
    ready = ready_work_units(artifact, unit_state)
    return [ready[idx : idx + cap] for idx in range(0, len(ready), cap)]


def next_resume_point(artifact: Mapping[str, Any], unit_state: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    """Return the first incomplete/failed unit from artifact plus durable state."""

    state = unit_state or {}
    unit_by_id = _unit_by_id(artifact)
    for layer in topological_work_unit_layers(artifact):
        for unit_id in layer:
            status = _status(unit_by_id[unit_id], state)
            if status not in COMPLETE_STATUSES:
                return {"work_unit_id": unit_id, "status": status}
    return None


def beads_update_allowed(actor: str, update_kind: str, *, owns_child_issue: bool = False) -> bool:
    """Enforce coordinator-only shared state writes.

    Workers may append notes only to their own child issue. The coordinator owns
    merge state, summaries, retries, phase completion, and run-event rows.
    """

    if actor == "coordinator":
        return update_kind in COORDINATOR_UPDATE_KINDS
    return update_kind == WORKER_LOCAL_UPDATE and owns_child_issue


def _unit_by_id(artifact: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    units = artifact.get("work_units") or []
    return {unit["id"]: unit for unit in units if isinstance(unit, Mapping) and isinstance(unit.get("id"), str)}


def _status(unit: Mapping[str, Any], unit_state: Mapping[str, Any]) -> str:
    unit_id = unit.get("id")
    override = unit_state.get(unit_id) if isinstance(unit_id, str) else None
    if isinstance(override, str):
        return override
    if isinstance(override, Mapping) and isinstance(override.get("status"), str):
        return override["status"]
    value = unit.get("status")
    return value if isinstance(value, str) else "pending"
