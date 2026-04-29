"""Foreground phase-session pump and MVP launcher adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .context_bundle import render_context_bundle
from .paths import resolve_data_dir
from .phase_sessions import (
    PhaseSessionError,
    claim_next_phase,
    init_phase_sessions,
    load_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_status,
    record_launch_metadata,
    record_phase_result,
    refresh_phase,
    start_phase,
)
from .phase_recovery import reconcile_phase_sessions
from .run_state import (
    active_run_path,
    append_run_event,
    load_active_run,
    utc_now,
    validate_run_event,
    write_active_run,
    write_checkpoint_from_active,
)
from .session_capabilities import doctor_report


ENABLED_LAUNCHERS = {"manual", "fake-test", "claude-print"}
ClaudeRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

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
    claude_runner: ClaudeRunner | None = None,
    claude_path: str | None = None,
    max_budget_usd: float | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the foreground pump over manual or fake-test launchers."""

    base = data_dir or resolve_data_dir()
    if launcher == "claude-print":
        capability = next(item for item in doctor_report().get("launchers", []) if item.get("name") == "claude-print")
        if not capability.get("eligible"):
            _append_pump_event(
                base,
                run_id=run_id,
                event_type="phase_pump_launcher_ineligible",
                details={"launcher": launcher, "capability": capability},
            )
            _append_pump_event(base, run_id=run_id, event_type="phase_pump_stopped", details={"status": "ineligible"})
            return {"status": "ineligible", "launcher": launcher, "capability": capability, "completed_phases": []}

    if launcher not in ENABLED_LAUNCHERS:
        raise ValueError(f"unsupported launcher: {launcher}")
    _append_pump_event(base, run_id=run_id, event_type="phase_pump_started", details={"launcher": launcher})

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
        recovery = reconcile_phase_sessions(run_id, data_dir=base, launcher=launcher)
        recovery_result = _handle_recovery_decision(
            recovery,
            completed=completed,
            data_dir=base,
            run_id=run_id,
            stop_on_checkpoint=stop_on_checkpoint,
        )
        if recovery_result is not None:
            if recovery_result.get("continue"):
                continue
            return dict(recovery_result["result"])

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

        if launcher == "claude-print":
            launch = _run_claude_print_phase(
                run_id,
                phase_id,
                running_phase,
                prompt_path=Path(context["prompt_path"]),
                lease_owner=str(claim["lease_owner"]),
                claude_runner=claude_runner,
                claude_path=claude_path,
                max_budget_usd=max_budget_usd,
                data_dir=base,
            )
            if launch["status"] != "launched":
                recovery = reconcile_phase_sessions(
                    run_id,
                    data_dir=base,
                    launcher=launcher,
                    launcher_result=launch,
                )
                recovery_result = _handle_recovery_decision(
                    recovery,
                    completed=completed,
                    data_dir=base,
                    run_id=run_id,
                    stop_on_checkpoint=stop_on_checkpoint,
                    launcher_result=launch,
                )
                if recovery_result is not None:
                    if recovery_result.get("continue"):
                        continue
                    return dict(recovery_result["result"])
                continue
            recovery = reconcile_phase_sessions(
                run_id,
                data_dir=base,
                launcher=launcher,
                launcher_result=launch,
            )
            recovery_result = _handle_recovery_decision(
                recovery,
                completed=completed,
                data_dir=base,
                run_id=run_id,
                stop_on_checkpoint=stop_on_checkpoint,
                launcher_result=launch,
            )
            if recovery_result is not None:
                if recovery_result.get("continue"):
                    continue
                return dict(recovery_result["result"])
            continue

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


def _handle_recovery_decision(
    recovery: Mapping[str, Any],
    *,
    completed: list[dict[str, Any]],
    data_dir: Path,
    run_id: str,
    stop_on_checkpoint: bool,
    launcher_result: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    status = str(recovery.get("status") or "ready")
    adopted = _record_adopted_completions(recovery, completed=completed, data_dir=data_dir, run_id=run_id)
    if adopted and stop_on_checkpoint:
        _append_pump_event(data_dir, run_id=run_id, event_type="phase_pump_stopped", details={"status": "checkpoint", "recovery": recovery})
        return {"result": {"status": "checkpoint", "completed_phases": completed, "recovery": recovery}}
    if status == "ready":
        return None
    if status == "complete":
        _append_pump_event(data_dir, run_id=run_id, event_type="phase_pump_stopped", details={"status": "complete", "recovery": recovery})
        return {"result": {"status": "complete", "completed_phases": completed, "recovery": recovery}}
    if status == "retry_waiting":
        wait_seconds = _retry_wait_seconds(recovery)
        if wait_seconds is not None and wait_seconds <= 60:
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            return {"continue": True}
        _append_pump_event(data_dir, run_id=run_id, event_type="phase_pump_stopped", details={"status": status, "recovery": recovery})
        return {
            "result": {
                "status": status,
                "completed_phases": completed,
                "recovery": recovery,
                "launcher_result": launcher_result,
            }
        }
    if status in {"active", "leased", "running"}:
        _append_pump_event(data_dir, run_id=run_id, event_type="phase_pump_stopped", details={"status": "active", "recovery": recovery})
        return {"result": {"status": "active", "completed_phases": completed, "recovery": recovery}}
    if status in {"blocked", "needs_input", "failed", "failed_nonretryable", "retry_exhausted", "drift"}:
        _append_pump_event(data_dir, run_id=run_id, event_type="phase_pump_stopped", details={"status": status, "recovery": recovery})
        return {
            "result": {
                "status": status,
                "completed_phases": completed,
                "recovery": recovery,
                "launcher_result": launcher_result,
            }
        }
    return None


def _record_adopted_completions(
    recovery: Mapping[str, Any],
    *,
    completed: list[dict[str, Any]],
    data_dir: Path,
    run_id: str,
) -> bool:
    phase_status_payload = recovery.get("phase_status")
    phases = phase_status_payload.get("phases") if isinstance(phase_status_payload, Mapping) else []
    by_id = {str(phase.get("phase_id")): phase for phase in phases or [] if isinstance(phase, Mapping)}
    appended = False
    for action in recovery.get("actions") or []:
        if not isinstance(action, Mapping) or action.get("action") != "adopted_completion":
            continue
        phase_id = str(action.get("phase_id"))
        phase = by_id.get(phase_id)
        if not isinstance(phase, Mapping):
            continue
        signature = (phase.get("phase_id"), phase.get("attempt"))
        if any((item.get("phase_id"), item.get("attempt")) == signature for item in completed):
            continue
        completed.append(dict(phase))
        _write_phase_checkpoint(data_dir, run_id, phase)
        appended = True
    return appended


def _retry_wait_seconds(recovery: Mapping[str, Any]) -> int | None:
    waits = []
    for action in recovery.get("actions") or []:
        if isinstance(action, Mapping) and isinstance(action.get("retry_sleep_seconds"), int):
            waits.append(int(action["retry_sleep_seconds"]))
    return min(waits) if waits else None


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


def _run_claude_print_phase(
    run_id: str,
    phase_id: str,
    phase: Mapping[str, Any],
    *,
    prompt_path: Path,
    lease_owner: str,
    claude_runner: ClaudeRunner | None,
    claude_path: str | None,
    max_budget_usd: float | None,
    data_dir: Path,
) -> dict[str, Any]:
    attempt = int(phase["attempt"])
    run_dir = data_dir / "runs" / run_id
    launch_dir = run_dir / "phase_launches" / phase_id / f"attempt-{attempt}"
    launch_dir.mkdir(parents=True, exist_ok=True)
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data_dir)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data_dir)
    launcher_prompt_path = launch_dir / "dispatcher.launcher.prompt.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    prompt_text = _append_claude_print_contract(
        prompt_text,
        result_path=result_path,
        handoff_path=handoff_path,
        status_values=sorted(RESULT_STATUS_FOR_COMMAND),
    )
    launcher_prompt_path.write_text(prompt_text, encoding="utf-8")
    prompt_sha = _sha256_file(launcher_prompt_path)

    resolved_claude = claude_path or shutil.which("claude") or ("claude" if claude_runner is not None else None)
    if not resolved_claude:
        return {"status": "launcher_error", "reason": "claude_cli_missing"}
    argv = [
        resolved_claude,
        "-p",
        "--name",
        str(phase.get("session_name") or f"swarmdaddy-{run_id}-{phase_id}"),
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        _allowed_tools_arg(),
    ]
    if max_budget_usd is not None:
        argv.extend(["--max-budget-usd", str(max_budget_usd)])
    argv.append(prompt_text)
    metadata = {
        "argv": [*argv[:-1], "<prompt_text omitted>"],
        "prompt_path": str(launcher_prompt_path),
        "prompt_sha": prompt_sha,
        "source_prompt_path": str(prompt_path),
        "source_prompt_sha": _sha256_file(prompt_path),
        "result_path": str(result_path),
        "handoff_path": str(handoff_path),
        "env_redacted": True,
    }
    (launch_dir / "command.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record_launch_metadata(
        run_id,
        phase_id,
        data_dir=data_dir,
        launch_dir=launch_dir,
        command_path=launch_dir / "command.json",
        parent_pid=os.getpid(),
        prompt_sha=prompt_sha,
        expected_result_path=result_path,
        expected_handoff_path=handoff_path,
    )

    try:
        if claude_runner is not None:
            proc = claude_runner(argv)
        else:
            proc = _run_real_claude(
                argv,
                run_id=run_id,
                phase_id=phase_id,
                lease_owner=lease_owner,
                data_dir=data_dir,
                launch_dir=launch_dir,
                command_path=launch_dir / "command.json",
                metadata=metadata,
                prompt_sha=prompt_sha,
                result_path=result_path,
                handoff_path=handoff_path,
            )
    except subprocess.TimeoutExpired as exc:
        (launch_dir / "stdout.txt").write_text(exc.stdout or "", encoding="utf-8")
        (launch_dir / "stderr.txt").write_text(exc.stderr or "", encoding="utf-8")
        return {"status": "launcher_error", "reason": "claude_print_timeout", "launch_dir": str(launch_dir)}
    except Exception as exc:
        return {"status": "launcher_error", "reason": str(exc), "launch_dir": str(launch_dir)}

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    (launch_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (launch_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    metadata["returncode"] = proc.returncode
    (launch_dir / "command.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "launched",
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "launch_dir": str(launch_dir),
    }


def _append_claude_print_contract(
    prompt: str,
    *,
    result_path: Path,
    handoff_path: Path,
    status_values: list[str],
) -> str:
    contract = [
        "",
        "## Launcher Artifact Contract",
        "",
        f"- Write the phase result JSON exactly to: {result_path}",
        f"- Write the phase handoff JSON exactly to: {handoff_path}",
        f"- The result status must be one of: {', '.join(status_values)}",
        "- Return a final JSON object containing status, result_path, handoff_path, and session_name.",
        "- Do not start another orchestrator or mutate the global phase queue.",
        "",
    ]
    return prompt.rstrip() + "\n" + "\n".join(contract)


def _run_real_claude(
    argv: Sequence[str],
    *,
    run_id: str,
    phase_id: str,
    lease_owner: str,
    data_dir: Path,
    launch_dir: Path,
    command_path: Path,
    metadata: dict[str, Any],
    prompt_sha: str,
    result_path: Path,
    handoff_path: Path,
) -> subprocess.CompletedProcess[str]:
    state = load_phase_sessions(run_id, data_dir=data_dir)
    policy = state.get("lease_policy") if isinstance(state.get("lease_policy"), Mapping) else {}
    refresh_interval = max(1, int(policy.get("refresh_interval_seconds") or 300))
    timeout_seconds = max(1, int(policy.get("running_ttl_seconds") or 14400) - (2 * refresh_interval))
    started = time.monotonic()
    proc = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    process_group_id: int | None = None
    metadata_error: str | None = None
    try:
        process_group_id = os.getpgid(proc.pid)
    except Exception as exc:
        metadata_error = str(exc)
    metadata["child_pid"] = proc.pid
    metadata["process_group_id"] = process_group_id
    if metadata_error:
        metadata["process_group_lookup_error"] = metadata_error
    command_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record_launch_metadata(
        run_id,
        phase_id,
        data_dir=data_dir,
        launch_dir=launch_dir,
        command_path=command_path,
        parent_pid=os.getpid(),
        child_pid=proc.pid,
        process_group_id=process_group_id,
        prompt_sha=prompt_sha,
        expected_result_path=result_path,
        expected_handoff_path=handoff_path,
        launch_metadata_error=metadata_error,
    )
    while True:
        elapsed = time.monotonic() - started
        if elapsed > timeout_seconds:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(argv, timeout_seconds, output=stdout, stderr=stderr)
        wait_for = min(refresh_interval, max(0.1, timeout_seconds - elapsed))
        try:
            stdout, stderr = proc.communicate(timeout=wait_for)
            return subprocess.CompletedProcess(list(argv), proc.returncode, stdout=stdout, stderr=stderr)
        except subprocess.TimeoutExpired:
            refresh_phase(run_id, phase_id, lease_owner=lease_owner, data_dir=data_dir)


def _allowed_tools_arg() -> str:
    path = Path(__file__).resolve().parents[3] / "permissions" / "writer.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        allow = (payload.get("permissions") or {}).get("allow") or []
    except Exception as exc:
        raise PhaseSessionError(f"writer permission fragment unavailable: {path}") from exc
    values = [item for item in allow if isinstance(item, str) and item]
    if not values:
        raise PhaseSessionError("writer permission fragment has no allowed tools")
    return ",".join(values)


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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
    if current.get("run_id") != run_id:
        current = {"run_id": run_id}
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
    validate_run_event(row, error_cls=PhaseSessionError)
    append_run_event(data_dir, row)


__all__ = ["format_pump_result", "pump_phases"]
