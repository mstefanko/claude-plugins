"""Foreground phase-session pump and MVP launcher adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .context_bundle import render_context_bundle
from .paths import resolve_data_dir
from .phase_sessions import (
    PhaseSessionError,
    claim_next_phase,
    init_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_status,
    record_phase_result,
    reap_expired_phases,
    start_phase,
)
from .run_state import active_run_path, append_run_event, load_active_run, utc_now, write_active_run, write_checkpoint_from_active
from .session_capabilities import doctor_report


RESULT_STATUS_FOR_COMMAND = {
    "complete": "complete",
    "failed": "failed",
    "blocked": "blocked",
    "needs_input": "needs_input",
}


def pump_phases(
    run_id: str,
    *,
    launcher: str,
    max_phases: int | None = 1,
    init_if_missing: bool = False,
    stop_on_checkpoint: bool = False,
    fake_statuses: Iterable[str] = (),
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the foreground pump over manual or fake-test launchers."""

    base = data_dir or resolve_data_dir()
    if launcher not in {"manual", "fake-test", "claude-print"}:
        raise ValueError(f"unsupported launcher: {launcher}")
    _append_pump_event(base, run_id=run_id, event_type="phase_pump_started", details={"launcher": launcher})

    if launcher == "claude-print":
        capability = next(item for item in doctor_report().get("launchers", []) if item.get("name") == "claude-print")
        _append_pump_event(
            base,
            run_id=run_id,
            event_type="phase_pump_launcher_ineligible",
            details={"launcher": launcher, "capability": capability},
        )
        _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "ineligible"})
        return {"status": "ineligible", "launcher": launcher, "capability": capability, "completed_phases": []}

    status = phase_status(run_id, data_dir=base)
    if status["status"] == "not_initialized":
        if not init_if_missing:
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "not_initialized"})
            return {"status": "not_initialized", "completed_phases": [], "recommended_command": status["recommended_command"]}
        init_phase_sessions(run_id, data_dir=base)

    completed: list[dict[str, Any]] = []
    manual: dict[str, Any] | None = None
    fake_sequence = list(fake_statuses)
    max_count = 1_000_000 if max_phases is None else max(0, max_phases)

    for phase_number in range(max_count):
        reaped = reap_expired_phases(run_id, data_dir=base)
        if reaped["reaped"]:
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "stale", "reaped": reaped["reaped"]})
            return {"status": "stale", "completed_phases": completed, "reaped": reaped["reaped"]}

        claim = claim_next_phase(run_id, data_dir=base, lease_command=f"phase-pump:{launcher}")
        if not claim.get("claimed"):
            current = phase_status(run_id, data_dir=base)
            final_status = "complete" if current.get("status") == "complete" else str(claim.get("reason") or current.get("status"))
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": final_status})
            return {"status": final_status, "completed_phases": completed, "claim": claim}

        phase = claim["phase"]
        phase_id = str(phase["phase_id"])
        started = start_phase(
            run_id,
            phase_id,
            launcher=launcher,
            data_dir=base,
            lease_owner=str(claim["lease_owner"]),
            lease_command=f"phase-pump:{launcher}",
        )
        running_phase = started["phase"]
        context = render_context_bundle(run_id=run_id, phase_id=phase_id, role="dispatcher", data_dir=base)

        if launcher == "manual":
            prompt_path = context["prompt_path"]
            result_path = phase_result_path(run_id, phase_id, int(running_phase["attempt"]), data_dir=base)
            manual = {
                "phase": running_phase,
                "prompt_path": prompt_path,
                "follow_up_command": f"bin/swarm phases complete {run_id} --phase {phase_id} --json-file {result_path}",
            }
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "manual_waiting", **manual})
            return {"status": "manual_waiting", "completed_phases": completed, "manual": manual}

        fake_status = fake_sequence[phase_number] if phase_number < len(fake_sequence) else "complete"
        if fake_status not in RESULT_STATUS_FOR_COMMAND:
            raise ValueError(f"unknown fake phase status: {fake_status}")
        result_file = _write_fake_result(
            run_id,
            phase_id,
            running_phase,
            status=fake_status,
            data_dir=base,
        )
        recorded = record_phase_result(
            run_id,
            phase_id,
            json_file=result_file,
            expected_status=RESULT_STATUS_FOR_COMMAND[fake_status],
            data_dir=base,
        )
        completed.append(recorded["phase"])
        _write_phase_checkpoint(base, run_id, recorded["phase"])
        if stop_on_checkpoint:
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "checkpoint"})
            return {"status": "checkpoint", "completed_phases": completed}
        if fake_status != "complete":
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": fake_status})
            return {"status": fake_status, "completed_phases": completed}

    _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "max_phases"})
    return {"status": "max_phases", "completed_phases": completed, "manual": manual}


def format_pump_result(result: Mapping[str, Any]) -> str:
    lines = [f"phase pump: {result.get('status')}"]
    lines.append(f"completed_phases: {len(result.get('completed_phases') or [])}")
    manual = result.get("manual")
    if isinstance(manual, Mapping):
        lines.append(f"prompt: {manual.get('prompt_path')}")
        lines.append(f"follow_up: {manual.get('follow_up_command')}")
    recommended = result.get("recommended_command")
    if recommended:
        lines.append(f"next: {recommended}")
    return "\n".join(lines)


def _write_fake_result(
    run_id: str,
    phase_id: str,
    phase: Mapping[str, Any],
    *,
    status: str,
    data_dir: Path,
) -> Path:
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data_dir)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data_dir)
    now = utc_now()
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": f"fake-test {status} for phase {phase_id}",
        "decisions": [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [f"fake-test {status}"] if status == "blocked" else [],
        "do_not_retry": [],
        "validation_summary": [],
        "artifacts": [],
        "next_phase_context": [],
    }
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "launcher": "fake-test",
        "session_name": phase.get("session_name"),
        "prepared_plan_sha": _status_prepared_sha(run_id, data_dir=data_dir),
        "phase_content_sha": _phase_content_sha(run_id, phase_id, data_dir=data_dir),
        "started_at": phase.get("started_at") or now,
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": f"fake-test {status} for phase {phase_id}",
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": "fake-test blocked" if status == "blocked" else None,
        "needs_input": ["fake-test input"] if status == "needs_input" else [],
        "validation": [],
        "artifacts": [],
        "error": {"message": "fake-test failure"} if status == "failed" else None,
    }
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result_path


def _status_prepared_sha(run_id: str, *, data_dir: Path) -> str:
    status = phase_status(run_id, data_dir=data_dir)
    value = status.get("prepared_plan_sha")
    return value if isinstance(value, str) else "0" * 64


def _phase_content_sha(run_id: str, phase_id: str, *, data_dir: Path) -> str:
    state = phase_status(run_id, data_dir=data_dir)
    prepared_path = Path(str(state.get("prepared_artifact_path") or data_dir / "runs" / run_id / "prepared_plan.v1.json"))
    if not prepared_path.is_absolute() and not prepared_path.is_file():
        prepared_path = data_dir / "runs" / run_id / "prepared_plan.v1.json"
    try:
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    except Exception:
        return "0" * 64
    for phase in prepared.get("phase_map") or []:
        if isinstance(phase, Mapping) and phase.get("phase_id") == phase_id and isinstance(phase.get("content_sha"), str):
            return str(phase["content_sha"])
    return "0" * 64


def _write_phase_checkpoint(base: Path, run_id: str, phase: Mapping[str, Any]) -> None:
    current = load_active_run(active_run_path(base)) or {"run_id": run_id}
    state = dict(current)
    state.update(
        {
            "run_id": run_id,
            "phase_id": phase.get("phase_id"),
            "status": "incomplete" if phase.get("status") != "complete" else "prepared",
            "phase_session_status": phase.get("status"),
            "phase_session_phase_id": phase.get("phase_id"),
            "phase_session_phase_index": phase.get("phase_index"),
            "phase_session_attempt": phase.get("attempt"),
            "phase_session_state_path": str(base / "runs" / run_id / "phase_sessions.v1.json"),
            "phase_session_lease_owner": phase.get("lease_owner"),
        }
    )
    write_active_run(active_run_path(base), state)
    write_checkpoint_from_active(base, state, source="phase-pump", reason=str(phase.get("status") or "phase"))


def _append_pump_event(
    data_dir: Path,
    *,
    run_id: str,
    event_type: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": event_type,
        "bd_epic_id": None,
        "phase_id": None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": None,
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details or {}),
        "schema_ok": True,
    }
    _validate_run_event(row)
    append_run_event(data_dir, row)


def _validate_run_event(row: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import load_schema, validate_value

    errors = validate_value(dict(row), load_schema("run_events"))
    if errors:
        raise PhaseSessionError("run_event schema invalid: " + "; ".join(errors))


__all__ = ["format_pump_result", "pump_phases"]
