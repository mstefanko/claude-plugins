"""Deterministic helpers for work-unit graph artifacts."""

from __future__ import annotations

from typing import Any, Mapping


def topological_work_unit_layers(artifact: Mapping[str, Any]) -> list[list[str]]:
    units = artifact.get("work_units") or []
    ids = [unit["id"] for unit in units]
    deps = {unit["id"]: set(unit.get("depends_on") or []) for unit in units}
    missing = sorted(dep for unit_deps in deps.values() for dep in unit_deps if dep not in ids)
    if missing:
        raise ValueError(f"work-unit dependency references unknown id: {', '.join(missing)}")
    remaining = set(ids)
    layers: list[list[str]] = []
    while remaining:
        ready = sorted(unit_id for unit_id in remaining if deps[unit_id].isdisjoint(remaining))
        if not ready:
            raise ValueError(f"cycle detected among work units: {', '.join(sorted(remaining))}")
        layers.append(ready)
        remaining.difference_update(ready)
    return layers


def unit_file_scope(unit: Mapping[str, Any]) -> list[str]:
    """Return the v2 allowed_files scope, accepting v1 files as a legacy alias."""

    value = unit.get("allowed_files", unit.get("files"))
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def retry_state_transition(review_verdict: str, retry_count: int, *, max_retries: int = 2) -> str:
    if review_verdict == "APPROVED":
        return "approved"
    if review_verdict == "SPEC_MISMATCH":
        return "escalate" if retry_count >= max_retries else "retry"
    if review_verdict in {"BLOCKED", "NEEDS_CONTEXT", "SPEC_AMBIGUOUS"}:
        return "operator"
    return "invalid-review-output"
