"""Durable phase-session queue state for accepted prepared runs."""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - v1 is POSIX-only by design.
    fcntl = None  # type: ignore[assignment]

from .paths import REPO_ROOT, resolve_data_dir
from .prepare import STATUS_ACCEPTED, StalePreparedArtifactError, check_stale, load_prepared_artifact
from .run_state import _atomic_json_write, append_run_event, utc_now, validate_run_event


SCHEMA_VERSION = 1
STATE_FILENAME = "phase_sessions.v1.json"
LOCK_FILENAME = "phase_sessions.v1.lock"

STATUS_PENDING = "pending"
STATUS_LEASED = "leased"
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_NEEDS_INPUT = "needs_input"
STATUS_STALE = "stale"
STATUS_RETRY_WAITING = "retry_waiting"
STATUS_RETRY_EXHAUSTED = "retry_exhausted"

CLAIMABLE_STATUSES = {STATUS_PENDING}
ACTIVE_STATUSES = {STATUS_LEASED, STATUS_RUNNING}
TERMINAL_STATUSES = {STATUS_COMPLETE, STATUS_FAILED, STATUS_BLOCKED, STATUS_NEEDS_INPUT, STATUS_RETRY_EXHAUSTED}
RESULT_TO_PHASE_STATUS = {
    "complete": STATUS_COMPLETE,
    "failed": STATUS_FAILED,
    "blocked": STATUS_BLOCKED,
    "needs_input": STATUS_NEEDS_INPUT,
}
PHASE_STATUS_TO_EVENT = {
    STATUS_COMPLETE: "phase_session_completed",
    STATUS_FAILED: "phase_session_failed",
    STATUS_BLOCKED: "phase_session_blocked",
    STATUS_NEEDS_INPUT: "phase_session_needs_input",
}
DEFAULT_LEASE_POLICY = {
    "claim_ttl_seconds": 900,
    "running_ttl_seconds": 14400,
    "refresh_interval_seconds": 300,
}
DEFAULT_RETRY_POLICY = {
    "max_session_attempts": 3,
    "max_recovery_attempts": 1,
    "recovery_timeout_threshold_seconds": 600,
    "retry_sleep_threshold_seconds": 60,
    "short_retry_backoff_seconds": 0,
    "max_retry_after_seconds": 1800,
    "worktree_baseline_path": None,
    "worktree_baseline_warning": None,
}


class PhaseSessionError(ValueError):
    """Raised when a phase-session transition is invalid."""


class PhaseSessionLockTimeout(TimeoutError):
    """Raised when the phase-session state lock cannot be acquired."""


def phase_session_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / STATE_FILENAME


def phase_session_lock_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / LOCK_FILENAME


def phase_result_path(
    run_id: str,
    phase_id: str,
    attempt: int,
    *,
    data_dir: Path | None = None,
) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / "phase_results" / phase_id / f"attempt-{attempt}.result.json"


def phase_handoff_path(
    run_id: str,
    phase_id: str,
    attempt: int,
    *,
    data_dir: Path | None = None,
) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / "phase_handoffs" / phase_id / f"attempt-{attempt}.handoff.json"


def init_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    mode: str = "cli-pump",
) -> dict[str, Any]:
    """Initialize state from an accepted prepared artifact, idempotently."""

    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state_path = phase_session_path(run_id, data_dir=base)
        if state_path.exists():
            state = load_phase_sessions(run_id, data_dir=base)
            return {"initialized": False, "state": state, "state_path": str(state_path)}

        prepared = _load_accepted_prepared(run_id, data_dir=base, repo_root=repo_root)
        now = utc_now()
        phases: list[dict[str, Any]] = []
        previous_phase_id: str | None = None
        for phase_index, phase in enumerate(prepared.get("phase_map") or []):
            phase_id = str(phase["phase_id"])
            explicit_deps = phase.get("depends_on_phase_ids")
            depends_on = _string_list(explicit_deps) if isinstance(explicit_deps, list) else ([previous_phase_id] if previous_phase_id else [])
            phases.append(
                {
                    "phase_id": phase_id,
                    "phase_index": phase_index,
                    "title": str(phase.get("title") or phase_id),
                    "depends_on_phase_ids": depends_on,
                    "status": STATUS_PENDING,
                    "lease_owner": None,
                    "lease_host": None,
                    "lease_pid": None,
                    "lease_command": None,
                    "lease_expires_at": None,
                    "attempt": 0,
                    "session_name": None,
                    "started_at": None,
                    "completed_at": None,
                    "result_path": None,
                    "handoff_path": None,
                    "last_error": None,
                    "max_session_attempts": None,
                    "next_retry_at": None,
                    "last_failure_kind": None,
                    "last_launcher_error": None,
                    "retry_exhausted_at": None,
                    "launch_dir": None,
                    "command_path": None,
                    "parent_pid": None,
                    "child_pid": None,
                    "process_group_id": None,
                    "prompt_sha": None,
                    "expected_result_path": None,
                    "expected_handoff_path": None,
                    "launch_metadata_error": None,
                    "recovery_context_path": None,
                    "attempt_history": [],
                }
            )
            previous_phase_id = phase_id
        retry_policy = dict(DEFAULT_RETRY_POLICY)
        try:
            from .worktree_baseline import snapshot_worktree_baseline

            baseline = snapshot_worktree_baseline(
                run_id,
                data_dir=base,
                repo_root=_prepared_repo_root(prepared, repo_root=repo_root),
            )
            retry_policy["worktree_baseline_path"] = _display_path(Path(str(baseline["path"])))
            if baseline.get("warning"):
                retry_policy["worktree_baseline_warning"] = str(baseline["warning"])
        except Exception as exc:
            retry_policy["worktree_baseline_warning"] = str(exc)
        state = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "prepared_artifact_path": _display_path(_prepared_artifact_path(run_id, data_dir=base)),
            "prepared_plan_sha": prepared["prepared_plan_sha"],
            "created_at": now,
            "updated_at": now,
            "mode": mode,
            "lease_policy": dict(DEFAULT_LEASE_POLICY),
            "retry_policy": retry_policy,
            "phases": phases,
        }
        _validate_state(state)
        _atomic_json_write(state_path, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_initialized",
            details={"state_path": str(state_path), "phase_count": len(phases)},
            bd_epic_id=_bd_epic_id(prepared),
        )
        return {"initialized": True, "state": state, "state_path": str(state_path)}


def load_phase_sessions(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    path = phase_session_path(run_id, data_dir=data_dir)
    if not path.is_file():
        raise FileNotFoundError(f"phase-session state not found: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PhaseSessionError(f"phase-session state is invalid JSON: {path}") from exc
    if not isinstance(state, dict):
        raise PhaseSessionError("phase-session state root must be an object")
    _normalize_state(state)
    _validate_state(state)
    return state


def phase_status(run_id: str, *, data_dir: Path | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    """Read-only status for CLI, TUI, and resume integration."""

    base = data_dir or resolve_data_dir()
    state_path = phase_session_path(run_id, data_dir=base)
    prepared_path = _prepared_artifact_path(run_id, data_dir=base)
    if not state_path.exists():
        try:
            prepared = _load_accepted_prepared(run_id, data_dir=base, repo_root=repo_root)
        except FileNotFoundError:
            return {
                "run_id": run_id,
                "status": "not_found",
                "state_path": str(state_path),
                "prepared_artifact_path": str(prepared_path),
                "next_phase": None,
                "phases": [],
                "recommended_command": None,
            }
        except Exception as exc:
            return {
                "run_id": run_id,
                "status": "drift",
                "state_path": str(state_path),
                "prepared_artifact_path": str(prepared_path),
                "next_phase": None,
                "phases": [],
                "drift": [str(exc)],
                "recommended_command": None,
            }
        return {
            "run_id": run_id,
            "status": "not_initialized",
            "state_path": str(state_path),
            "prepared_artifact_path": str(prepared_path),
            "prepared_plan_sha": prepared.get("prepared_plan_sha"),
            "next_phase": None,
            "phases": [],
            "recommended_command": f"bin/swarm phases init {run_id}",
        }

    try:
        state = load_phase_sessions(run_id, data_dir=base)
    except Exception as exc:
        return {
            "run_id": run_id,
            "status": "drift",
            "state_path": str(state_path),
            "prepared_artifact_path": str(prepared_path),
            "next_phase": None,
            "phases": [],
            "drift": [str(exc)],
            "recommended_command": None,
        }

    next_phase = _next_claimable_phase(state)
    active = _active_phase(state)
    stale = next((phase for phase in state["phases"] if phase.get("status") == STATUS_STALE), None)
    failed = next((phase for phase in state["phases"] if phase.get("status") == STATUS_FAILED), None)
    retry_waiting = next((phase for phase in state["phases"] if phase.get("status") == STATUS_RETRY_WAITING), None)
    retry_exhausted = next((phase for phase in state["phases"] if phase.get("status") == STATUS_RETRY_EXHAUSTED), None)
    blocked = next(
        (phase for phase in state["phases"] if phase.get("status") in {STATUS_BLOCKED, STATUS_NEEDS_INPUT}),
        None,
    )
    if all(phase.get("status") == STATUS_COMPLETE for phase in state["phases"]):
        overall = "complete"
        recommended = None
    elif active is not None:
        overall = str(active["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif retry_waiting is not None:
        overall = STATUS_RETRY_WAITING
        recommended = f"bin/swarm phases recover {run_id}"
    elif retry_exhausted is not None:
        overall = STATUS_RETRY_EXHAUSTED
        recommended = f"bin/swarm phases status {run_id}"
    elif stale is not None:
        overall = "stale"
        recommended = f"bin/swarm phases recover {run_id}"
    elif failed is not None:
        overall = "failed"
        recommended = f"bin/swarm phases status {run_id}"
    elif blocked is not None:
        overall = str(blocked["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif next_phase is not None:
        overall = "ready"
        recommended = f"bin/swarm do --prepared {run_id} --phase-sessions auto"
    else:
        overall = "waiting"
        recommended = f"bin/swarm phases status {run_id}"
    return {
        "run_id": run_id,
        "status": overall,
        "state_path": str(state_path),
        "prepared_artifact_path": state.get("prepared_artifact_path"),
        "prepared_plan_sha": state.get("prepared_plan_sha"),
        "updated_at": state.get("updated_at"),
        "retry_policy": state.get("retry_policy"),
        "next_phase": _phase_summary(next_phase) if next_phase else None,
        "active_phase": _phase_summary(active) if active else None,
        "phases": [_phase_summary(phase) for phase in state["phases"]],
        "dependency_status": _dependency_status(state, next_phase) if overall == "waiting" else [],
        "recommended_command": recommended,
    }


def read_phase_session_summary(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    return phase_status(run_id, data_dir=data_dir)


def claim_next_phase(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    lease_owner: str | None = None,
    lease_command: str | None = None,
    reclaim_stale: bool = False,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    owner = lease_owner or generate_lease_owner()
    with locked_phase_sessions(run_id, data_dir=base):
        prepared = _load_accepted_prepared(run_id, data_dir=base, repo_root=repo_root)
        state = load_phase_sessions(run_id, data_dir=base)
        _assert_prepared_sha_matches(state, prepared)
        if reclaim_stale:
            for phase in state["phases"]:
                if phase.get("status") == STATUS_STALE and _dependencies_complete(state, phase):
                    _reset_phase_to_pending(phase)
                    break
        stale = next((phase for phase in state["phases"] if phase.get("status") == STATUS_STALE), None)
        if stale is not None:
            return {"claimed": False, "reason": "stale_phase", "phase": _phase_summary(stale), "state": state}
        active = _active_phase(state)
        if active is not None:
            return {"claimed": False, "reason": "active_phase", "phase": _phase_summary(active), "state": state}
        phase = _next_claimable_phase(state)
        if phase is None:
            return {"claimed": False, "reason": "no_claimable_phase", "phase": None, "state": state}
        now = _utc_now_dt()
        expires = now + timedelta(seconds=int(state["lease_policy"]["claim_ttl_seconds"]))
        phase["status"] = STATUS_LEASED
        phase["lease_owner"] = owner
        phase["lease_host"] = socket.gethostname()
        phase["lease_pid"] = os.getpid()
        phase["lease_command"] = lease_command
        phase["lease_expires_at"] = _format_dt(expires)
        phase["last_error"] = None
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_claimed",
            phase=phase,
            bd_epic_id=_bd_epic_id(prepared),
        )
        return {"claimed": True, "phase": _phase_summary(phase), "lease_owner": owner, "state": state}


def start_phase(
    run_id: str,
    phase_id: str,
    *,
    launcher: str,
    data_dir: Path | None = None,
    lease_owner: str | None = None,
    session_name: str | None = None,
    lease_command: str | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase["status"] != STATUS_LEASED:
            raise PhaseSessionError(f"phase {phase_id} must be leased before start; got {phase['status']}")
        if lease_owner is not None and phase.get("lease_owner") != lease_owner:
            raise PhaseSessionError("lease owner mismatch")
        owner = str(phase.get("lease_owner") or lease_owner or generate_lease_owner())
        now = _utc_now_dt()
        expires = now + timedelta(seconds=int(state["lease_policy"]["running_ttl_seconds"]))
        phase["status"] = STATUS_RUNNING
        phase["lease_owner"] = owner
        phase["lease_host"] = socket.gethostname()
        phase["lease_pid"] = os.getpid()
        phase["lease_command"] = lease_command
        phase["lease_expires_at"] = _format_dt(expires)
        phase["attempt"] = int(phase.get("attempt") or 0) + 1
        phase["session_name"] = session_name or _default_session_name(run_id, phase_id, int(phase["attempt"]))
        phase["started_at"] = _format_dt(now)
        phase["completed_at"] = None
        phase["result_path"] = None
        phase["handoff_path"] = None
        phase["last_error"] = None
        phase["next_retry_at"] = None
        phase["retry_exhausted_at"] = None
        phase["last_launcher_error"] = None
        phase["launch_dir"] = None
        phase["command_path"] = None
        phase["parent_pid"] = os.getpid()
        phase["child_pid"] = None
        phase["process_group_id"] = None
        phase["prompt_sha"] = None
        phase["expected_result_path"] = None
        phase["expected_handoff_path"] = None
        phase["launch_metadata_error"] = None
        phase["recovery_context_path"] = None
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_started",
            phase=phase,
            launcher=launcher,
            session_name=str(phase["session_name"]),
        )
        return {"started": True, "phase": _phase_summary(phase), "state": state}


def refresh_phase(
    run_id: str,
    phase_id: str,
    *,
    lease_owner: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase["status"] != STATUS_RUNNING:
            raise PhaseSessionError(f"phase {phase_id} is not running")
        if phase.get("lease_owner") != lease_owner:
            raise PhaseSessionError("lease owner mismatch")
        expires = _utc_now_dt() + timedelta(seconds=int(state["lease_policy"]["running_ttl_seconds"]))
        phase["lease_expires_at"] = _format_dt(expires)
        _touch_and_write(base, run_id, state)
        _append_phase_event(base, run_id=run_id, event_type="phase_session_refreshed", phase=phase)
        return {"refreshed": True, "phase": _phase_summary(phase), "state": state}


def reap_expired_phases(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    reaped: list[dict[str, Any]] = []
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        now = _utc_now_dt()
        for phase in state["phases"]:
            if phase.get("status") not in ACTIVE_STATUSES:
                continue
            expires = _parse_dt(phase.get("lease_expires_at"))
            if expires is None or expires > now:
                continue
            previous = str(phase["status"])
            phase["status"] = STATUS_STALE
            phase["last_error"] = f"{previous} lease expired at {phase.get('lease_expires_at')}"
            reaped.append(_phase_summary(phase))
            _append_phase_event(
                base,
                run_id=run_id,
                event_type="phase_session_lease_expired",
                phase=phase,
                reason=phase["last_error"],
            )
        if reaped:
            _touch_and_write(base, run_id, state)
        return {"reaped": reaped, "state": state}


def record_phase_result(
    run_id: str,
    phase_id: str,
    *,
    json_file: str | os.PathLike[str],
    expected_status: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    result_path, result, handoff_path, handoff = _validate_phase_artifacts(
        run_id,
        phase_id,
        json_file=json_file,
        expected_status=expected_status,
        data_dir=base,
    )
    result_status = str(result["status"])

    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase["status"] != STATUS_RUNNING:
            raise PhaseSessionError(f"phase {phase_id} must be running before recording result")
        if int(phase.get("attempt") or 0) != int(result["phase_attempt"]):
            raise PhaseSessionError("result attempt does not match running phase attempt")
        phase_status = _apply_phase_result(phase, result=result, result_path=result_path, handoff_path=handoff_path)
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_result_recorded",
            phase=phase,
            result_path=_display_path(result_path),
            schema_valid=True,
        )
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_handoff_recorded",
            phase=phase,
            handoff_path=_display_path(handoff_path),
            schema_valid=True,
        )
        _append_phase_event(
            base,
            run_id=run_id,
            event_type=PHASE_STATUS_TO_EVENT[phase_status],
            phase=phase,
            result_path=_display_path(result_path),
            handoff_path=_display_path(handoff_path),
        )
        return {"recorded": True, "phase": _phase_summary(phase), "state": state}


def adopt_phase_result(
    run_id: str,
    phase_id: str,
    *,
    json_file: str | os.PathLike[str],
    expected_status: str | None = None,
    data_dir: Path | None = None,
    attempt_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adopt valid current-attempt artifacts during recovery.

    Unlike ``record_phase_result()``, recovery can adopt artifacts from a stale
    or otherwise abandoned attempt after the parent launcher has died.
    """

    base = data_dir or resolve_data_dir()
    result_path, result, handoff_path, _handoff = _validate_phase_artifacts(
        run_id,
        phase_id,
        json_file=json_file,
        expected_status=expected_status,
        data_dir=base,
    )
    result_status = str(result["status"])
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase.get("status") not in {
            STATUS_RUNNING,
            STATUS_STALE,
            STATUS_FAILED,
            STATUS_RETRY_WAITING,
            STATUS_PENDING,
        }:
            raise PhaseSessionError(f"phase {phase_id} cannot adopt result while {phase.get('status')}")
        if int(phase.get("attempt") or 0) != int(result["phase_attempt"]):
            raise PhaseSessionError("result attempt does not match current phase attempt")
        phase_status = _apply_phase_result(phase, result=result, result_path=result_path, handoff_path=handoff_path)
        if attempt_record is not None:
            _append_attempt_history(phase, attempt_record)
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_attempt_adopted",
            phase=phase,
            result_path=_display_path(result_path),
            handoff_path=_display_path(handoff_path),
            details={
                "status": result_status,
                "failure_kind": (attempt_record or {}).get("failure_kind"),
                "retry_decision": "adopted",
            },
        )
        _append_phase_event(
            base,
            run_id=run_id,
            event_type=PHASE_STATUS_TO_EVENT[phase_status],
            phase=phase,
            result_path=_display_path(result_path),
            handoff_path=_display_path(handoff_path),
        )
        return {"adopted": True, "phase": _phase_summary(phase), "state": state}


def abandon_attempt_and_retry(
    run_id: str,
    phase_id: str,
    *,
    failure_kind: str,
    data_dir: Path | None = None,
    launcher_error: str | None = None,
    next_retry_at: str | None = None,
    retry_after_seconds: int | None = None,
    attempt_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase.get("status") not in {STATUS_RUNNING, STATUS_STALE, STATUS_FAILED, STATUS_RETRY_WAITING}:
            raise PhaseSessionError(f"phase {phase_id} cannot retry from {phase.get('status')}")
        record = dict(attempt_record or _attempt_record_from_phase(phase))
        record.setdefault("failure_kind", failure_kind)
        record.setdefault("retry_decision", "retry")
        record.setdefault("retry_after_seconds", retry_after_seconds)
        record.setdefault("adopted", False)
        _append_attempt_history(phase, record)
        phase["status"] = STATUS_RETRY_WAITING if next_retry_at else STATUS_PENDING
        phase["lease_owner"] = None
        phase["lease_host"] = None
        phase["lease_pid"] = None
        phase["lease_command"] = None
        phase["lease_expires_at"] = None
        phase["last_error"] = launcher_error or failure_kind
        phase["last_failure_kind"] = failure_kind
        phase["last_launcher_error"] = launcher_error
        phase["next_retry_at"] = next_retry_at
        _touch_and_write(base, run_id, state)
        event_type = "phase_attempt_retry_scheduled" if next_retry_at else "phase_attempt_abandoned"
        _append_phase_event(
            base,
            run_id=run_id,
            event_type=event_type,
            phase=phase,
            reason=failure_kind,
            details={"failure_kind": failure_kind, "next_retry_at": next_retry_at, "retry_after_seconds": retry_after_seconds},
        )
        return {"retry": True, "phase": _phase_summary(phase), "state": state}


def release_retry_waiting(
    run_id: str,
    phase_id: str,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase.get("status") != STATUS_RETRY_WAITING:
            raise PhaseSessionError(f"phase {phase_id} is not retry_waiting")
        phase["status"] = STATUS_PENDING
        phase["next_retry_at"] = None
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_attempt_retry_ready",
            phase=phase,
            details={"failure_kind": phase.get("last_failure_kind")},
        )
        return {"ready": True, "phase": _phase_summary(phase), "state": state}


def mark_retry_exhausted(
    run_id: str,
    phase_id: str,
    *,
    failure_kind: str,
    data_dir: Path | None = None,
    launcher_error: str | None = None,
    attempt_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        record = dict(attempt_record or _attempt_record_from_phase(phase))
        record.setdefault("failure_kind", failure_kind)
        record.setdefault("retry_decision", "retry_exhausted")
        record.setdefault("adopted", False)
        _append_attempt_history(phase, record)
        now = utc_now()
        phase["status"] = STATUS_RETRY_EXHAUSTED
        phase["completed_at"] = phase.get("completed_at") or now
        phase["retry_exhausted_at"] = now
        phase["last_error"] = launcher_error or failure_kind
        phase["last_failure_kind"] = failure_kind
        phase["last_launcher_error"] = launcher_error
        phase["lease_owner"] = None
        phase["lease_host"] = None
        phase["lease_pid"] = None
        phase["lease_command"] = None
        phase["lease_expires_at"] = None
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_attempt_retry_exhausted",
            phase=phase,
            reason=failure_kind,
            details={"failure_kind": failure_kind, "recommended_command": f"bin/swarm phases status {run_id}"},
        )
        return {"retry_exhausted": True, "phase": _phase_summary(phase), "state": state}


def record_launch_metadata(
    run_id: str,
    phase_id: str,
    *,
    data_dir: Path | None = None,
    launch_dir: str | os.PathLike[str] | None = None,
    command_path: str | os.PathLike[str] | None = None,
    parent_pid: int | None = None,
    child_pid: int | None = None,
    process_group_id: int | None = None,
    prompt_sha: str | None = None,
    expected_result_path: str | os.PathLike[str] | None = None,
    expected_handoff_path: str | os.PathLike[str] | None = None,
    launch_metadata_error: str | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase.get("status") not in ACTIVE_STATUSES:
            raise PhaseSessionError(f"phase {phase_id} is not active")
        if launch_dir is not None:
            phase["launch_dir"] = _display_path(Path(launch_dir))
        if command_path is not None:
            phase["command_path"] = _display_path(Path(command_path))
        if parent_pid is not None:
            phase["parent_pid"] = int(parent_pid)
        if child_pid is not None:
            phase["child_pid"] = int(child_pid)
        if process_group_id is not None:
            phase["process_group_id"] = int(process_group_id)
        if prompt_sha is not None:
            phase["prompt_sha"] = prompt_sha
        if expected_result_path is not None:
            phase["expected_result_path"] = _display_path(Path(expected_result_path))
        if expected_handoff_path is not None:
            phase["expected_handoff_path"] = _display_path(Path(expected_handoff_path))
        if launch_metadata_error is not None:
            phase["launch_metadata_error"] = launch_metadata_error
        _touch_and_write(base, run_id, state)
        return {"recorded": True, "phase": _phase_summary(phase), "state": state}


def generate_lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def _default_session_name(run_id: str, phase_id: str, attempt: int) -> str:
    return f"swarmdaddy-{run_id}-{phase_id}-attempt-{attempt}"


@contextmanager
def locked_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = 10.0,
) -> Iterator[None]:
    """Hold the sibling advisory lock without deleting the lock file.

    POSIX locks attach to open file descriptions. Leaving the file in place
    avoids inode churn that can split contenders on shared/NFS-like filesystems.
    """

    if fcntl is None:
        raise PhaseSessionError("phase-session locks require POSIX fcntl.flock")
    lock_path = phase_session_lock_path(run_id, data_dir=data_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise PhaseSessionLockTimeout(
                        f"timed out waiting for phase-session lock for run {run_id}: {lock_path}"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_accepted_prepared(
    run_id: str,
    *,
    data_dir: Path,
    repo_root: Path | None,
) -> dict[str, Any]:
    prepared = load_prepared_artifact(run_id, data_dir=data_dir, repo_root=repo_root)
    if prepared.get("status") != STATUS_ACCEPTED:
        raise PhaseSessionError(f"phase sessions require accepted prepared artifact; got {prepared.get('status')!r}")
    root = _prepared_repo_root(prepared, repo_root=repo_root)
    drift = check_stale(prepared, repo_root=root)
    if drift is not None:
        raise StalePreparedArtifactError(
            f"prepared artifact is stale: {', '.join(drift.reasons)}",
            drift.reasons,
        )
    _verify_sidecar_hashes(prepared, repo_root=root)
    return prepared


def _prepared_repo_root(prepared: Mapping[str, Any], *, repo_root: Path | None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path(str(prepared.get("repo_root") or REPO_ROOT))
    return root.resolve(strict=False)


def _verify_sidecar_hashes(prepared: Mapping[str, Any], *, repo_root: Path) -> None:
    descriptors = prepared.get("work_unit_artifacts") or {}
    phase_ids = {str(phase.get("phase_id")) for phase in prepared.get("phase_map") or [] if isinstance(phase, Mapping)}
    if set(descriptors.keys()) != phase_ids:
        raise PhaseSessionError("work_unit_artifacts do not cover every phase")
    for phase_id, descriptor in descriptors.items():
        if not isinstance(descriptor, Mapping):
            raise PhaseSessionError(f"work_unit_artifacts[{phase_id}] is invalid")
        rel = Path(str(descriptor.get("path") or ""))
        path = repo_root / rel
        if not path.is_file():
            raise PhaseSessionError(f"work-unit sidecar missing for phase {phase_id}: {rel}")
        if _sha256_file(path) != descriptor.get("sha"):
            raise PhaseSessionError(f"work-unit sidecar sha mismatch for phase {phase_id}")


def _assert_prepared_sha_matches(state: Mapping[str, Any], prepared: Mapping[str, Any]) -> None:
    if state.get("prepared_plan_sha") != prepared.get("prepared_plan_sha"):
        raise PhaseSessionError("phase-session prepared_plan_sha does not match accepted prepared artifact")


def _next_claimable_phase(state: Mapping[str, Any]) -> dict[str, Any] | None:
    for phase in state.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        if phase.get("status") not in CLAIMABLE_STATUSES:
            continue
        if _dependencies_complete(state, phase):
            return phase
    return None


def _dependencies_complete(state: Mapping[str, Any], phase: Mapping[str, Any]) -> bool:
    by_id = {
        item.get("phase_id"): item
        for item in state.get("phases") or []
        if isinstance(item, Mapping)
    }
    for dep_id in phase.get("depends_on_phase_ids") or []:
        dep = by_id.get(dep_id)
        if not isinstance(dep, Mapping) or dep.get("status") != STATUS_COMPLETE:
            return False
    return True


def _dependency_status(state: Mapping[str, Any], phase: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if phase is None:
        pending = next(
            (item for item in state.get("phases") or [] if isinstance(item, Mapping) and item.get("status") == STATUS_PENDING),
            None,
        )
        phase = pending
    if not isinstance(phase, Mapping):
        return []
    by_id = {
        item.get("phase_id"): item
        for item in state.get("phases") or []
        if isinstance(item, Mapping)
    }
    results: list[dict[str, Any]] = []
    for dep_id in phase.get("depends_on_phase_ids") or []:
        dep = by_id.get(dep_id)
        results.append(
            {
                "phase_id": dep_id,
                "status": dep.get("status") if isinstance(dep, Mapping) else "missing",
            }
        )
    return results


def _active_phase(state: Mapping[str, Any]) -> dict[str, Any] | None:
    for phase in state.get("phases") or []:
        if isinstance(phase, dict) and phase.get("status") in ACTIVE_STATUSES:
            return phase
    return None


def _find_phase(state: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    for phase in state.get("phases") or []:
        if isinstance(phase, dict) and phase.get("phase_id") == phase_id:
            return phase
    raise PhaseSessionError(f"phase not found: {phase_id}")


def _reset_phase_to_pending(phase: dict[str, Any]) -> None:
    phase["status"] = STATUS_PENDING
    phase["lease_owner"] = None
    phase["lease_host"] = None
    phase["lease_pid"] = None
    phase["lease_command"] = None
    phase["lease_expires_at"] = None
    phase["last_error"] = None
    phase["next_retry_at"] = None


def _normalize_state(state: dict[str, Any]) -> None:
    retry_policy = state.get("retry_policy")
    if not isinstance(retry_policy, dict):
        state["retry_policy"] = dict(DEFAULT_RETRY_POLICY)
    else:
        normalized_policy = dict(DEFAULT_RETRY_POLICY)
        normalized_policy.update(retry_policy)
        state["retry_policy"] = normalized_policy
    for phase in state.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase.setdefault("max_session_attempts", None)
        phase.setdefault("next_retry_at", None)
        phase.setdefault("last_failure_kind", None)
        phase.setdefault("last_launcher_error", None)
        phase.setdefault("retry_exhausted_at", None)
        phase.setdefault("launch_dir", None)
        phase.setdefault("command_path", None)
        phase.setdefault("parent_pid", None)
        phase.setdefault("child_pid", None)
        phase.setdefault("process_group_id", None)
        phase.setdefault("prompt_sha", None)
        phase.setdefault("expected_result_path", None)
        phase.setdefault("expected_handoff_path", None)
        phase.setdefault("launch_metadata_error", None)
        phase.setdefault("recovery_context_path", None)
        if not isinstance(phase.get("attempt_history"), list):
            phase["attempt_history"] = []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _touch_and_write(data_dir: Path, run_id: str, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    _normalize_state(state)
    _validate_state(state)
    _atomic_json_write(phase_session_path(run_id, data_dir=data_dir), state)


def _phase_summary(phase: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if phase is None:
        return None
    keys = (
        "phase_id",
        "phase_index",
        "title",
        "depends_on_phase_ids",
        "status",
        "lease_owner",
        "lease_expires_at",
        "attempt",
        "session_name",
        "started_at",
        "completed_at",
        "result_path",
        "handoff_path",
        "last_error",
        "max_session_attempts",
        "next_retry_at",
        "last_failure_kind",
        "last_launcher_error",
        "retry_exhausted_at",
        "launch_dir",
        "command_path",
        "parent_pid",
        "child_pid",
        "process_group_id",
        "prompt_sha",
        "expected_result_path",
        "expected_handoff_path",
        "launch_metadata_error",
        "recovery_context_path",
        "attempt_history",
    )
    return {key: phase.get(key) for key in keys}


def _append_phase_event(
    data_dir: Path,
    *,
    run_id: str,
    event_type: str,
    phase: Mapping[str, Any] | None = None,
    bd_epic_id: str | None = None,
    launcher: str | None = None,
    session_name: str | None = None,
    result_path: str | None = None,
    handoff_path: str | None = None,
    schema_valid: bool | None = None,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> Path:
    event_details = dict(details or {})
    if phase:
        event_details.update(
            {
                "phase_index": phase.get("phase_index"),
                "phase_id": phase.get("phase_id"),
                "attempt": phase.get("attempt"),
                "lease_owner": phase.get("lease_owner"),
                "lease_expires_at": phase.get("lease_expires_at"),
            }
        )
    if launcher is not None:
        event_details["launcher"] = launcher
    if session_name is not None:
        event_details["session_name"] = session_name
    if result_path is not None:
        event_details["result_path"] = result_path
    if handoff_path is not None:
        event_details["handoff_path"] = handoff_path
    if schema_valid is not None:
        event_details["schema_valid"] = schema_valid
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": event_type,
        "bd_epic_id": bd_epic_id,
        "phase_id": phase.get("phase_id") if phase else None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": reason,
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": event_details,
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=PhaseSessionError)
    return append_run_event(data_dir, row)


def _validate_phase_artifacts(
    run_id: str,
    phase_id: str,
    *,
    json_file: str | os.PathLike[str],
    expected_status: str | None,
    data_dir: Path,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    result_path = _resolve_artifact_path(json_file, data_dir=data_dir, run_id=run_id, label="phase result")
    result = _load_and_validate_result(result_path)
    result_status = str(result["status"])
    if expected_status is not None and result_status != expected_status:
        raise PhaseSessionError(f"result status {result_status!r} does not match expected {expected_status!r}")
    if result.get("run_id") != run_id or result.get("phase_id") != phase_id:
        raise PhaseSessionError("result run_id/phase_id mismatch")
    if result.get("prepared_plan_sha") != _phase_session_prepared_sha(run_id, data_dir=data_dir):
        raise PhaseSessionError("result prepared_plan_sha does not match phase-session state")
    expected_phase_sha = _prepared_phase_content_sha(run_id, phase_id, data_dir=data_dir)
    if result.get("phase_content_sha") != expected_phase_sha:
        raise PhaseSessionError("result phase_content_sha does not match prepared phase metadata")
    handoff_path = _resolve_artifact_path(result["handoff_path"], data_dir=data_dir, run_id=run_id, label="phase handoff")
    handoff = _load_and_validate_handoff(handoff_path)
    if handoff.get("run_id") != run_id or handoff.get("phase_id") != phase_id:
        raise PhaseSessionError("handoff run_id/phase_id mismatch")
    if handoff.get("phase_attempt") != result.get("phase_attempt"):
        raise PhaseSessionError("handoff attempt does not match result attempt")
    if handoff.get("status") != result_status:
        raise PhaseSessionError("handoff status does not match result status")
    return result_path, result, handoff_path, handoff


def _apply_phase_result(
    phase: dict[str, Any],
    *,
    result: Mapping[str, Any],
    result_path: Path,
    handoff_path: Path,
) -> str:
    phase_status = RESULT_TO_PHASE_STATUS[str(result["status"])]
    phase["status"] = phase_status
    phase["completed_at"] = result["completed_at"]
    phase["result_path"] = _display_path(result_path)
    phase["handoff_path"] = _display_path(handoff_path)
    phase["lease_owner"] = None
    phase["lease_host"] = None
    phase["lease_pid"] = None
    phase["lease_command"] = None
    phase["lease_expires_at"] = None
    phase["next_retry_at"] = None
    phase["last_error"] = _result_error_message(result) if phase_status != STATUS_COMPLETE else None
    phase["last_failure_kind"] = result.get("failure_kind") if isinstance(result.get("failure_kind"), str) else phase.get("last_failure_kind")
    return phase_status


def _attempt_record_from_phase(phase: Mapping[str, Any]) -> dict[str, Any]:
    started = _parse_dt(phase.get("started_at"))
    completed = _parse_dt(phase.get("completed_at")) or _utc_now_dt()
    elapsed = (completed - started).total_seconds() if started is not None else None
    return {
        "attempt": int(phase.get("attempt") or 0),
        "session_name": phase.get("session_name"),
        "launcher": _launcher_from_command(phase.get("lease_command")),
        "lease_owner": phase.get("lease_owner"),
        "lease_host": phase.get("lease_host"),
        "lease_pid": phase.get("lease_pid"),
        "child_pid": phase.get("child_pid"),
        "process_group_id": phase.get("process_group_id"),
        "started_at": phase.get("started_at"),
        "completed_at": _format_dt(completed),
        "elapsed_seconds": elapsed if elapsed is not None and elapsed >= 0 else None,
        "launch_dir": phase.get("launch_dir"),
        "result_path": phase.get("result_path") or phase.get("expected_result_path"),
        "handoff_path": phase.get("handoff_path") or phase.get("expected_handoff_path"),
        "returncode": None,
        "failure_kind": phase.get("last_failure_kind"),
        "retry_decision": None,
        "retry_after_seconds": None,
        "adopted": False,
        "stdout_tail_path": None,
        "stderr_tail_path": None,
        "changed_files": [],
        "diff_summary_path": None,
        "recovery_context_path": phase.get("recovery_context_path"),
    }


def _append_attempt_history(phase: dict[str, Any], record: Mapping[str, Any]) -> None:
    attempt = int(record.get("attempt") or phase.get("attempt") or 0)
    if attempt <= 0:
        return
    item = dict(_attempt_record_from_phase(phase))
    item.update({key: value for key, value in record.items() if value is not None})
    item["attempt"] = attempt
    item["adopted"] = bool(item.get("adopted"))
    history = phase.setdefault("attempt_history", [])
    if not isinstance(history, list):
        history = []
        phase["attempt_history"] = history
    signature = (
        item.get("attempt"),
        item.get("failure_kind"),
        item.get("retry_decision"),
        item.get("returncode"),
        item.get("adopted"),
    )
    for existing in history:
        if not isinstance(existing, Mapping):
            continue
        if (
            existing.get("attempt"),
            existing.get("failure_kind"),
            existing.get("retry_decision"),
            existing.get("returncode"),
            existing.get("adopted"),
        ) == signature:
            return
    history.append(item)


def _launcher_from_command(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if ":" in value:
        return value.rsplit(":", 1)[-1]
    return value or None


def _phase_session_prepared_sha(run_id: str, *, data_dir: Path) -> str:
    state = load_phase_sessions(run_id, data_dir=data_dir)
    value = state.get("prepared_plan_sha")
    if isinstance(value, str):
        return value
    raise PhaseSessionError("phase-session prepared_plan_sha missing")


def _prepared_phase_content_sha(run_id: str, phase_id: str, *, data_dir: Path) -> str:
    path = _prepared_artifact_path(run_id, data_dir=data_dir)
    try:
        prepared = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PhaseSessionError(f"prepared artifact unavailable for phase hash check: {path}") from exc
    for phase in prepared.get("phase_map") or []:
        if isinstance(phase, Mapping) and phase.get("phase_id") == phase_id and isinstance(phase.get("content_sha"), str):
            return str(phase["content_sha"])
    raise PhaseSessionError(f"prepared phase metadata missing for phase {phase_id}")


def _load_and_validate_result(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="phase result")
    _validate_payload(payload, REPO_ROOT / "schemas" / "phase_result.schema.json", label="phase result")
    return payload


def _load_and_validate_handoff(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="phase handoff")
    _validate_payload(payload, REPO_ROOT / "schemas" / "phase_handoff.schema.json", label="phase handoff")
    return payload


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PhaseSessionError(f"{label} is not readable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PhaseSessionError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PhaseSessionError(f"{label} must be a JSON object: {path}")
    return value


def _validate_state(state: Mapping[str, Any]) -> None:
    _validate_payload(state, REPO_ROOT / "schemas" / "phase_sessions.schema.json", label="phase-session state")


def _validate_payload(payload: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_value(dict(payload), schema)
    if errors:
        raise PhaseSessionError(f"{label} schema invalid: " + "; ".join(errors))


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _prepared_artifact_path(run_id: str, *, data_dir: Path) -> Path:
    return data_dir / "runs" / run_id / "prepared_plan.v1.json"


def _resolve_artifact_path(
    value: Any,
    *,
    data_dir: Path,
    run_id: str,
    label: str,
) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        _assert_path_under_run(resolved, data_dir=data_dir, run_id=run_id, label=label)
        return resolved
    candidates = [REPO_ROOT / path, data_dir / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve(strict=False)
            _assert_path_under_run(resolved, data_dir=data_dir, run_id=run_id, label=label)
            return resolved
    resolved = candidates[0].resolve(strict=False)
    _assert_path_under_run(resolved, data_dir=data_dir, run_id=run_id, label=label)
    return resolved


def _assert_path_under_run(path: Path, *, data_dir: Path, run_id: str, label: str) -> None:
    run_root = (data_dir / "runs" / run_id).resolve(strict=False)
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise PhaseSessionError(f"{label} path escapes run directory: {path}") from exc


def _display_path(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve(strict=False)))
    except ValueError:
        return str(path)


def _bd_epic_id(prepared: Mapping[str, Any]) -> str | None:
    value = prepared.get("bd_epic_id")
    return value if isinstance(value, str) else None


def _result_error_message(result: Mapping[str, Any]) -> str | None:
    error = result.get("error")
    if isinstance(error, Mapping):
        message = error.get("message") or error.get("type")
        if isinstance(message, str) and message:
            return message
    for key in ("blocked_reason", "summary"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _utc_now_dt() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_dt(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "PhaseSessionError",
    "PhaseSessionLockTimeout",
    "abandon_attempt_and_retry",
    "adopt_phase_result",
    "claim_next_phase",
    "generate_lease_owner",
    "init_phase_sessions",
    "load_phase_sessions",
    "locked_phase_sessions",
    "mark_retry_exhausted",
    "phase_handoff_path",
    "phase_result_path",
    "phase_session_path",
    "phase_status",
    "read_phase_session_summary",
    "reap_expired_phases",
    "record_phase_result",
    "record_launch_metadata",
    "release_retry_waiting",
    "refresh_phase",
    "start_phase",
]
