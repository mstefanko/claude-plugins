"""Failed-attempt spend snapshots for durable autopilot policy gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .phase_attempts import is_failed_attempt, summarize_phase_attempts


@dataclass(frozen=True)
class FailedSpendSnapshot:
    current_attempt_cost_usd: float | None
    current_attempt_cost_confidence: str | None
    failed_phase_cost_usd: float
    failed_run_cost_usd: float
    unknown_failed_attempt_count: int


def failed_spend_snapshot(
    run_id: str,
    phase_id: str,
    attempt: int,
    *,
    data_dir: Path | None = None,
    include_archived: bool = False,
) -> FailedSpendSnapshot:
    summary = summarize_phase_attempts(run_id, data_dir=data_dir, include_archived=include_archived)
    rows = [row for row in (summary.get("attempts") or {}).get("rows") or [] if isinstance(row, Mapping)]
    current_key = (str(phase_id), int(attempt))
    current = next((row for row in rows if (str(row.get("phase_id")), int(row.get("attempt") or 0)) == current_key), None)
    current_cost, current_confidence = _known_cost(current)
    failed_phase_cost = 0.0
    failed_run_cost = 0.0
    unknown_failed = 0
    for row in rows:
        if row.get("archived") and not include_archived:
            continue
        row_key = (str(row.get("phase_id")), int(row.get("attempt") or 0))
        failed = is_failed_attempt(row) or row_key == current_key
        if not failed:
            continue
        cost, confidence = _known_cost(row)
        if cost is None:
            if confidence in {"unknown", "conflict", None}:
                unknown_failed += 1
            continue
        failed_run_cost += cost
        if str(row.get("phase_id")) == str(phase_id):
            failed_phase_cost += cost
    return FailedSpendSnapshot(
        current_attempt_cost_usd=current_cost,
        current_attempt_cost_confidence=current_confidence,
        failed_phase_cost_usd=failed_phase_cost,
        failed_run_cost_usd=failed_run_cost,
        unknown_failed_attempt_count=unknown_failed,
    )


def _known_cost(row: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    if row is None:
        return None, "unknown"
    confidence = row.get("cost_confidence")
    cost = row.get("total_cost_usd")
    if confidence == "provider_reported" and isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return float(cost), "provider_reported"
    if confidence == "conflict":
        return None, "conflict"
    return None, "unknown"


__all__ = ["FailedSpendSnapshot", "failed_spend_snapshot"]
