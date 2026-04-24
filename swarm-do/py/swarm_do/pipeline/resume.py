"""Resume manifest lookup and conservative drift reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import resolve_data_dir


READY_TO_RESUME = 0
RESUMED = READY_TO_RESUME
COMPLETE = 2
NOTHING_TO_RESUME = COMPLETE
DRIFT_DETECTED = 3
NOT_FOUND = 4

READY = "ready"
STATUS_COMPLETE = "complete"
DRIFT = "drift"
STATUS_NOT_FOUND = "not-found"

COMPLETE_UNIT_STATUSES = {"complete", "completed", "approved", "done"}


@dataclass(frozen=True)
class ResumeReport:
    bd_epic_id: str
    run_id: str | None
    checkpoint_path: Path | None
    run_event_path: Path
    status: str
    resume_from: dict[str, str | None] | None
    drift_keys: list[str]
    completed_units: list[str]

    @property
    def complete(self) -> bool:
        return self.status == STATUS_COMPLETE

    def to_manifest(self) -> dict[str, Any]:
        return {
            "bd_epic_id": self.bd_epic_id,
            "run_id": self.run_id,
            "status": self.status,
            "resume_from": self.resume_from,
            "drift_keys": self.drift_keys,
            "completed_units": self.completed_units,
            "checkpoint_path": str(self.checkpoint_path) if self.checkpoint_path else None,
            "run_event_path": str(self.run_event_path),
        }


def build_resume_report(bd_epic_id: str) -> ResumeReport:
    run_event_path = _run_event_path()
    rows = _run_event_rows(run_event_path)
    latest_event = _latest_event_for_epic(rows, bd_epic_id)
    run_id = latest_event.get("run_id") if latest_event else None
    checkpoint = _checkpoint_for_run(run_id) if isinstance(run_id, str) else None
    checkpoint_data = _load_json(checkpoint) if checkpoint else {}
    drift = _checkpoint_drift(bd_epic_id, checkpoint_data, latest_event)
    completed = _completed_units(checkpoint_data, rows, run_id)
    resume_from = _resume_from(checkpoint_data, latest_event)

    if not run_id:
        status = STATUS_NOT_FOUND
        resume_from = None
    elif drift:
        status = DRIFT
    elif _is_complete(checkpoint_data, latest_event):
        status = STATUS_COMPLETE
        resume_from = None
    else:
        status = READY

    return ResumeReport(
        bd_epic_id=bd_epic_id,
        run_id=run_id if isinstance(run_id, str) else None,
        checkpoint_path=checkpoint,
        run_event_path=run_event_path,
        status=status,
        resume_from=resume_from,
        drift_keys=drift,
        completed_units=completed,
    )


def format_resume_report(report: ResumeReport, *, merge: bool = False) -> str:
    lines = [f"resume: {report.bd_epic_id}"]
    lines.append(f"  run_id: {report.run_id or 'not found'}")
    lines.append(f"  status: {report.status}")
    lines.append(f"  checkpoint: {report.checkpoint_path or 'not found'}")
    lines.append(f"  run_events: {report.run_event_path}")
    lines.append(f"  merge: {'explicitly requested' if merge else 'disabled'}")
    if report.resume_from:
        phase = report.resume_from.get("phase_id") or "unknown"
        work_unit = report.resume_from.get("work_unit_id") or "phase-boundary"
        lines.append(f"  resume_from: phase={phase} work_unit={work_unit}")
    if report.completed_units:
        lines.append("  completed_units:")
        lines.extend(f"    - {unit}" for unit in report.completed_units)
    if report.drift_keys:
        lines.append("  drift detected:")
        lines.extend(f"    - {key}" for key in report.drift_keys)
    elif report.status == READY:
        lines.append("  action: restart orchestration from resume_from")
    elif report.status == STATUS_COMPLETE:
        lines.append("  action: no-op; run is already complete")
    else:
        lines.append("  action: no run_events mapping found")
    return "\n".join(lines)


def resume_exit_code(report: ResumeReport) -> int:
    if report.status == READY:
        return READY_TO_RESUME
    if report.status == STATUS_COMPLETE:
        return COMPLETE
    if report.status == DRIFT:
        return DRIFT_DETECTED
    return NOT_FOUND


def _run_event_path() -> Path:
    return resolve_data_dir() / "telemetry" / "run_events.jsonl"


def _run_event_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _latest_event_for_epic(rows: list[dict[str, Any]], bd_epic_id: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for row in rows:
        if row.get("bd_epic_id") == bd_epic_id and isinstance(row.get("run_id"), str):
            latest = row
    return latest


def _checkpoint_for_run(run_id: str | None) -> Path | None:
    if not run_id:
        return None
    path = resolve_data_dir() / "runs" / run_id / "checkpoint.v1.json"
    return path if path.is_file() else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_invalid_json": True}
    return value if isinstance(value, dict) else {"_invalid_root": True}


def _checkpoint_drift(
    bd_epic_id: str,
    checkpoint: dict[str, Any],
    latest_event: dict[str, Any] | None,
) -> list[str]:
    if not checkpoint:
        return []
    drift: list[str] = []
    if checkpoint.get("_invalid_json"):
        drift.append("checkpoint_json")
    if checkpoint.get("_invalid_root"):
        drift.append("checkpoint_root")
    if checkpoint.get("bd_epic_id") not in (None, bd_epic_id):
        drift.append("bd_epic_id")
    child_ids = checkpoint.get("child_bead_ids")
    if child_ids is not None and (not isinstance(child_ids, list) or not all(isinstance(item, str) for item in child_ids)):
        drift.append("child_bead_ids")
    event_child_ids = latest_event.get("child_bead_ids") if latest_event else None
    if isinstance(child_ids, list) and isinstance(event_child_ids, list) and child_ids != event_child_ids:
        drift.append("child_bead_ids")
    work_units = checkpoint.get("work_units")
    if work_units is not None and not isinstance(work_units, list):
        drift.append("work_units")
    return _dedupe(drift)


def _completed_units(checkpoint: dict[str, Any], rows: list[dict[str, Any]], run_id: str | None) -> list[str]:
    completed: list[str] = []
    for unit in _work_units(checkpoint):
        unit_id = _unit_id(unit)
        status = unit.get("status")
        if unit_id and isinstance(status, str) and status.lower() in COMPLETE_UNIT_STATUSES:
            completed.append(unit_id)
    for row in rows:
        if row.get("run_id") != run_id:
            continue
        if row.get("event_type") == "resume_completed":
            unit_id = row.get("work_unit_id")
            if isinstance(unit_id, str):
                completed.append(unit_id)
    return _dedupe(completed)


def _resume_from(checkpoint: dict[str, Any], latest_event: dict[str, Any] | None) -> dict[str, str | None] | None:
    phase_id = checkpoint.get("phase_id")
    if not isinstance(phase_id, str):
        phase_id = latest_event.get("phase_id") if latest_event and isinstance(latest_event.get("phase_id"), str) else None
    for unit in _work_units(checkpoint):
        status = unit.get("status")
        if not isinstance(status, str) or status.lower() not in COMPLETE_UNIT_STATUSES:
            return {"phase_id": phase_id, "work_unit_id": _unit_id(unit)}
    event_unit = latest_event.get("work_unit_id") if latest_event else None
    return {"phase_id": phase_id, "work_unit_id": event_unit if isinstance(event_unit, str) else None}


def _is_complete(checkpoint: dict[str, Any], latest_event: dict[str, Any] | None) -> bool:
    if checkpoint.get("status") == STATUS_COMPLETE:
        return True
    if latest_event and latest_event.get("event_type") == "resume_completed" and latest_event.get("reason") == STATUS_COMPLETE:
        return True
    units = _work_units(checkpoint)
    return bool(units) and all(str(unit.get("status", "")).lower() in COMPLETE_UNIT_STATUSES for unit in units)


def _work_units(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    units = checkpoint.get("work_units")
    if not isinstance(units, list):
        return []
    return [unit for unit in units if isinstance(unit, dict)]


def _unit_id(unit: dict[str, Any]) -> str | None:
    value = unit.get("id") or unit.get("work_unit_id")
    return value if isinstance(value, str) else None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
