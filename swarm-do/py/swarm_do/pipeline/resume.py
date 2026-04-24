"""Checkpoint lookup and conservative resume reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import resolve_data_dir


RESUMED = 0
NOTHING_TO_RESUME = 2
DRIFT_DETECTED = 3


@dataclass(frozen=True)
class ResumeReport:
    bd_epic_id: str
    run_id: str | None
    checkpoint_path: Path | None
    drift_keys: list[str]
    complete: bool


def build_resume_report(bd_epic_id: str) -> ResumeReport:
    run_id = _latest_run_id_for_epic(bd_epic_id)
    checkpoint = _checkpoint_for_run(run_id) if run_id else None
    checkpoint_data = _load_json(checkpoint) if checkpoint else {}
    drift = _checkpoint_drift(bd_epic_id, checkpoint_data)
    complete = checkpoint_data.get("status") == "complete"
    return ResumeReport(bd_epic_id, run_id, checkpoint, drift, complete)


def format_resume_report(report: ResumeReport, *, merge: bool = False) -> str:
    lines = [f"resume: {report.bd_epic_id}"]
    lines.append(f"  run_id: {report.run_id or 'not found'}")
    lines.append(f"  checkpoint: {report.checkpoint_path or 'not found'}")
    lines.append(f"  merge: {'explicitly requested' if merge else 'disabled'}")
    if report.drift_keys:
        lines.append("  drift detected:")
        lines.extend(f"    - {key}" for key in report.drift_keys)
    elif report.complete:
        lines.append("  status: complete")
    elif report.run_id:
        lines.append("  status: ready to resume from first incomplete work unit")
    else:
        lines.append("  status: no run_events mapping found")
    return "\n".join(lines)


def resume_exit_code(report: ResumeReport) -> int:
    if report.drift_keys:
        return DRIFT_DETECTED
    if report.complete or not report.run_id:
        return NOTHING_TO_RESUME
    return RESUMED


def _latest_run_id_for_epic(bd_epic_id: str) -> str | None:
    path = resolve_data_dir() / "telemetry" / "run_events.jsonl"
    if not path.is_file():
        return None
    run_id = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("bd_epic_id") == bd_epic_id and isinstance(row.get("run_id"), str):
                run_id = row["run_id"]
    return run_id


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


def _checkpoint_drift(bd_epic_id: str, checkpoint: dict[str, Any]) -> list[str]:
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
    work_units = checkpoint.get("work_units")
    if work_units is not None and not isinstance(work_units, list):
        drift.append("work_units")
    return drift
