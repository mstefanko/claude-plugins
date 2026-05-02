"""Durable phase-session queue state for accepted prepared runs."""

from __future__ import annotations

import json
import os
import shutil
import signal
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
from .prepare import StalePreparedArtifactError, verify_prepared_run
from .failure_taxonomy import failure_kind_details
from .policies import (
    ResolvedPolicyUpdate,
    default_retry_policy,
    profile_defaults,
    retry_policy_config,
    validate_policy_overrides,
)
from .phase_evidence import MANIFEST_SCHEMA_VERSION, attempt_evidence_path, write_attempt_evidence_manifest
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
BLOCKED_RETRY_POLICY_HUMAN_GATE = "retry_policy_human_gate"
BLOCKED_DETERMINISTIC_CONTRACT_FAILURE = "deterministic_contract_failure"
BLOCKED_PERMISSION_CONTRACT_FAILURE = "permission_contract_failure"
BLOCKED_OPERATOR_CANCELLED = "operator_cancelled"
BLOCKED_CHILD_REPORTED_BLOCKED = "child_reported_blocked"

BLOCKED_REASONS = {
    BLOCKED_RETRY_POLICY_HUMAN_GATE,
    BLOCKED_DETERMINISTIC_CONTRACT_FAILURE,
    BLOCKED_PERMISSION_CONTRACT_FAILURE,
    BLOCKED_OPERATOR_CANCELLED,
    BLOCKED_CHILD_REPORTED_BLOCKED,
}


class PhaseSessionError(ValueError):
    """Raised when a phase-session transition is invalid."""


class PhaseArtifactContractError(PhaseSessionError):
    """Raised when phase result/handoff artifacts violate durable identity rules."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


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
    policy_update: ResolvedPolicyUpdate | None = None,
) -> dict[str, Any]:
    """Initialize state from an accepted prepared artifact, idempotently."""

    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state_path = phase_session_path(run_id, data_dir=base)
        if state_path.exists():
            state = load_phase_sessions(run_id, data_dir=base)
            if _policy_update_forces(policy_update):
                state = _configure_retry_policy_in_state(state, policy_update)
                _touch_and_write(base, run_id, state)
                return {
                    "initialized": False,
                    "policy_configured": True,
                    "state": state,
                    "state_path": str(state_path),
                }
            return {"initialized": False, "state": state, "state_path": str(state_path)}

        prepared = _load_accepted_prepared(run_id, data_dir=base, repo_root=repo_root)
        _assert_no_orphaned_phase_artifacts(run_id, data_dir=base)
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
                    "blocked_reason": None,
                    "retry_policy_decision": None,
                    "blocked_at": None,
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
                    "evidence_path": None,
                    "attempt_history": [],
                }
            )
            previous_phase_id = phase_id
        retry_policy = _retry_policy_with_update({}, policy_update)
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


def configure_retry_policy(
    run_id: str,
    policy_update: ResolvedPolicyUpdate | None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Merge validated retry-policy overrides into durable state."""

    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = _read_state_object(phase_session_path(run_id, data_dir=base))
        state = _configure_retry_policy_in_state(state, policy_update)
        _touch_and_write(base, run_id, state)
        return {"policy_configured": True, "state": state, "state_path": str(phase_session_path(run_id, data_dir=base))}


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
    if os.environ.get("SWARM_DISABLE_STATE_MIRROR") != "1":
        try:
            import sqlite3

            from .state_projector import load_phase_status_from_mirror

            mirror_status = load_phase_status_from_mirror(run_id, data_dir=base)
            if mirror_status is not None:
                return mirror_status
        except (FileNotFoundError, OSError, ValueError, sqlite3.DatabaseError):
            pass
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
    blocked = next(
        (phase for phase in state["phases"] if phase.get("status") in {STATUS_BLOCKED, STATUS_NEEDS_INPUT}),
        None,
    )
    retry_exhausted = next((phase for phase in state["phases"] if phase.get("status") == STATUS_RETRY_EXHAUSTED), None)
    if all(phase.get("status") == STATUS_COMPLETE for phase in state["phases"]):
        overall = "complete"
        recommended = None
    elif active is not None:
        overall = str(active["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif retry_waiting is not None:
        overall = STATUS_RETRY_WAITING
        recommended = f"bin/swarm phases recover {run_id}"
    elif blocked is not None:
        overall = str(blocked["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif retry_exhausted is not None:
        overall = STATUS_RETRY_EXHAUSTED
        recommended = f"bin/swarm phases status {run_id}"
    elif stale is not None:
        overall = "stale"
        recommended = f"bin/swarm phases recover {run_id}"
    elif failed is not None:
        overall = "failed"
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


def reset_phase_session(
    run_id: str,
    phase_id: str,
    *,
    hard: bool = False,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Reset one phase to pending through the in-process state writer."""

    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        before = _phase_summary(phase)
        _reset_phase_to_pending(phase)
        if hard:
            _hard_reset_phase_to_pending(phase)
        _touch_and_write(base, run_id, state)
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_reset",
            phase=phase,
            reason="hard_reset" if hard else "reset",
            details={
                "hard": hard,
                "previous_status": (before or {}).get("status"),
                "previous_attempt": (before or {}).get("attempt"),
            },
        )
        return {
            "run_id": run_id,
            "phase_id": phase_id,
            "hard": hard,
            "before": before,
            "phase": _phase_summary(phase),
            "state_path": str(phase_session_path(run_id, data_dir=base)),
        }


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
        phase["blocked_reason"] = None
        phase["retry_policy_decision"] = None
        phase["blocked_at"] = None
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
        phase["evidence_path"] = None
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


def repair_active_phase_lease(
    run_id: str,
    phase_id: str,
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
    action: str = "active_preserved_child_alive",
) -> dict[str, Any]:
    if action != "active_preserved_child_alive":
        raise PhaseSessionError(f"unsupported active lease repair action: {action}")
    base = data_dir or resolve_data_dir()
    current_time = (now or _utc_now_dt()).astimezone(UTC)
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        if phase["status"] not in ACTIVE_STATUSES:
            raise PhaseSessionError(f"phase {phase_id} is not active")
        old_expires_at = phase.get("lease_expires_at")
        ttl_seconds = int(state["lease_policy"]["running_ttl_seconds"])
        new_expires_at = _format_dt(current_time + timedelta(seconds=ttl_seconds))
        phase["lease_expires_at"] = new_expires_at
        _touch_and_write(base, run_id, state)
        details = {
            "phase_id": phase.get("phase_id"),
            "attempt": phase.get("attempt"),
            "child_pid": phase.get("child_pid"),
            "process_group_id": phase.get("process_group_id"),
            "old_lease_expires_at": old_expires_at,
            "new_lease_expires_at": new_expires_at,
            "action": action,
        }
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_active_preserved",
            phase=phase,
            details=details,
        )
        return {
            "repaired": True,
            "phase_id": phase.get("phase_id"),
            "attempt": phase.get("attempt"),
            "child_pid": phase.get("child_pid"),
            "process_group_id": phase.get("process_group_id"),
            "old_lease_expires_at": old_expires_at,
            "new_lease_expires_at": new_expires_at,
            "action": action,
            "phase": _phase_summary(phase),
            "state": state,
        }


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
        evidence_path = _write_attempt_evidence_best_effort(
            base,
            run_id=run_id,
            state=state,
            phase=phase,
            transition="record_phase_result",
        )
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
            details={"evidence_path": evidence_path} if evidence_path else None,
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
        record = dict(attempt_record or {})
        record.setdefault("status", phase_status)
        record.setdefault("retry_decision", "adopted")
        evidence_path = _write_attempt_evidence_best_effort(
            base,
            run_id=run_id,
            state=state,
            phase=phase,
            transition="adopt_phase_result",
            attempt_record=record,
        )
        if evidence_path:
            record["evidence_path"] = evidence_path
        if attempt_record is not None:
            _append_attempt_history(phase, record)
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
                "failure_kind": record.get("failure_kind"),
                "retry_decision": "adopted",
                "evidence_path": evidence_path,
                **_taxonomy_event_details(record),
            },
        )
        _append_phase_event(
            base,
            run_id=run_id,
            event_type=PHASE_STATUS_TO_EVENT[phase_status],
            phase=phase,
            result_path=_display_path(result_path),
            handoff_path=_display_path(handoff_path),
            details={"evidence_path": evidence_path} if evidence_path else None,
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
        record.setdefault("status", STATUS_RETRY_WAITING if next_retry_at else STATUS_PENDING)
        evidence_path = _write_attempt_evidence_best_effort(
            base,
            run_id=run_id,
            state=state,
            phase=phase,
            transition="abandon_attempt_and_retry",
            attempt_record=record,
        )
        if evidence_path:
            record["evidence_path"] = evidence_path
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
        phase["retry_policy_decision"] = record.get("retry_decision")
        _touch_and_write(base, run_id, state)
        event_type = "phase_attempt_retry_scheduled" if next_retry_at else "phase_attempt_abandoned"
        _append_phase_event(
            base,
            run_id=run_id,
            event_type=event_type,
            phase=phase,
            reason=failure_kind,
            details={
                "failure_kind": failure_kind,
                "next_retry_at": next_retry_at,
                "retry_after_seconds": retry_after_seconds,
                "evidence_path": evidence_path,
                **_taxonomy_event_details(record),
                **_policy_event_details(record),
            },
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
        record.setdefault("status", STATUS_RETRY_EXHAUSTED)
        evidence_path = _write_attempt_evidence_best_effort(
            base,
            run_id=run_id,
            state=state,
            phase=phase,
            transition="mark_retry_exhausted",
            attempt_record=record,
        )
        if evidence_path:
            record["evidence_path"] = evidence_path
        _append_attempt_history(phase, record)
        now = utc_now()
        phase["status"] = STATUS_RETRY_EXHAUSTED
        phase["completed_at"] = phase.get("completed_at") or now
        phase["retry_exhausted_at"] = now
        phase["last_error"] = launcher_error or failure_kind
        phase["last_failure_kind"] = failure_kind
        phase["last_launcher_error"] = launcher_error
        phase["retry_policy_decision"] = "retry_exhausted"
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
            details={
                "failure_kind": failure_kind,
                "recommended_command": f"bin/swarm phases status {run_id}",
                "evidence_path": evidence_path,
                **_taxonomy_event_details(record),
                **_policy_event_details(record),
            },
        )
        return {"retry_exhausted": True, "phase": _phase_summary(phase), "state": state}


def mark_phase_blocked(
    run_id: str,
    phase_id: str,
    *,
    failure_kind: str,
    blocked_reason: str,
    retry_policy_decision: str,
    data_dir: Path | None = None,
    launcher_error: str | None = None,
    attempt_record: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if blocked_reason not in BLOCKED_REASONS:
        raise PhaseSessionError(f"unsupported blocked_reason: {blocked_reason}")
    base = data_dir or resolve_data_dir()
    with locked_phase_sessions(run_id, data_dir=base):
        state = load_phase_sessions(run_id, data_dir=base)
        phase = _find_phase(state, phase_id)
        record = dict(attempt_record or _attempt_record_from_phase(phase))
        record.setdefault("failure_kind", failure_kind)
        record["retry_decision"] = retry_policy_decision
        record.setdefault("adopted", False)
        record.setdefault("status", STATUS_BLOCKED)
        record.setdefault("blocked_reason", blocked_reason)
        evidence_path = _write_attempt_evidence_best_effort(
            base,
            run_id=run_id,
            state=state,
            phase=phase,
            transition="mark_phase_blocked",
            attempt_record=record,
        )
        if evidence_path:
            record["evidence_path"] = evidence_path
        _append_attempt_history(phase, record)
        now = utc_now()
        phase["status"] = STATUS_BLOCKED
        phase["completed_at"] = phase.get("completed_at") or now
        phase["blocked_at"] = now
        phase["blocked_reason"] = blocked_reason
        phase["retry_policy_decision"] = retry_policy_decision
        phase["last_error"] = launcher_error or failure_kind
        phase["last_failure_kind"] = failure_kind
        phase["last_launcher_error"] = launcher_error
        phase["lease_owner"] = None
        phase["lease_host"] = None
        phase["lease_pid"] = None
        phase["lease_command"] = None
        phase["lease_expires_at"] = None
        phase["next_retry_at"] = None
        _touch_and_write(base, run_id, state)
        event_details = {
            "failure_kind": failure_kind,
            "blocked_reason": blocked_reason,
            "retry_policy_decision": retry_policy_decision,
            "recommended_command": f"bin/swarm phases status {run_id} --attempts --cost",
            "evidence_path": evidence_path,
            **_taxonomy_event_details(record),
            **_policy_event_details(record),
        }
        event_details.update(dict(details or {}))
        _append_phase_event(
            base,
            run_id=run_id,
            event_type="phase_session_blocked",
            phase=phase,
            reason=blocked_reason,
            details=event_details,
        )
        return {"blocked": True, "phase": _phase_summary(phase), "state": state}


def cancel_phase_session_run(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    phase_id: str | None = None,
    kill_child: bool = True,
) -> dict[str, Any]:
    """Durably mark the current phase as operator-cancelled."""

    base = data_dir or resolve_data_dir()
    state = load_phase_sessions(run_id, data_dir=base)
    phase = _phase_to_cancel(state, phase_id)
    if phase is None:
        raise PhaseSessionError(f"no active phase-session phase to cancel for run {run_id}")
    target_phase_id = str(phase["phase_id"])
    child = _cancel_child_process_details(phase, kill_child=kill_child)
    cleanup = _cancel_cleanup_details(state, target_phase_id, data_dir=base, repo_root=repo_root)
    record = _attempt_record_from_phase(phase)
    record.update(
        {
            "failure_kind": BLOCKED_OPERATOR_CANCELLED,
            "retry_decision": BLOCKED_OPERATOR_CANCELLED,
            "adopted": False,
            "child_process": child,
            "cleanup": cleanup,
            "changed_files": cleanup.get("untracked_artifacts_by_phase", {}).get(target_phase_id, []),
        }
    )
    result = mark_phase_blocked(
        run_id,
        target_phase_id,
        failure_kind=BLOCKED_OPERATOR_CANCELLED,
        blocked_reason=BLOCKED_OPERATOR_CANCELLED,
        retry_policy_decision=BLOCKED_OPERATOR_CANCELLED,
        data_dir=base,
        launcher_error="operator cancelled phase session",
        attempt_record=record,
        details={"child_process": child, "cleanup": cleanup},
    )
    return {
        "cancelled": True,
        "run_id": run_id,
        "phase_id": target_phase_id,
        "phase": result["phase"],
        "child_process": child,
        "cleanup": cleanup,
        "state": result["state"],
    }


def cleanup_phase_generated_artifacts(
    run_id: str,
    *,
    data_dir: Path | None = None,
    phase_id: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    targets = _phase_generated_artifact_targets(run_id, data_dir=base, phase_id=phase_id)
    removed: list[str] = []
    existing = [target for target in targets if target.exists()]
    if apply:
        for target in existing:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(str(target))
    return {
        "run_id": run_id,
        "phase_id": phase_id,
        "applied": apply,
        "targets": [str(target) for target in targets],
        "existing_targets": [str(target) for target in existing],
        "removed": removed,
    }


def archive_phase_session_evidence(
    run_id: str,
    *,
    data_dir: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    run_dir = base / "runs" / run_id
    if not run_dir.is_dir():
        raise PhaseSessionError(f"run evidence directory not found: {run_dir}")
    suffix = _archive_label(label) if label else utc_now().replace(":", "").replace("-", "").replace(".", "")
    archive_dir = run_dir / f".archived-{suffix}"
    index = 1
    while archive_dir.exists():
        archive_dir = run_dir / f".archived-{suffix}-{index}"
        index += 1
    archive_dir.mkdir(parents=True)
    copied: list[str] = []
    for name in (
        STATE_FILENAME,
        "checkpoint.v1.json",
        "writer-settings.json",
        "phase_results",
        "phase_handoffs",
        "phase_launches",
        "phase_recovery",
    ):
        source = run_dir / name
        if not source.exists():
            continue
        target = archive_dir / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        copied.append(str(target))
    return {"run_id": run_id, "archive_dir": str(archive_dir), "copied": copied}


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
    try:
        return dict(verify_prepared_run(run_id, data_dir=data_dir, repo_root=repo_root).payload)
    except StalePreparedArtifactError:
        raise
    except Exception as exc:
        raise PhaseSessionError(str(exc)) from exc


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


def _assert_no_orphaned_phase_artifacts(run_id: str, *, data_dir: Path) -> None:
    run_dir = data_dir / "runs" / run_id
    artifact_roots = ("phase_launches", "phase_results", "phase_handoffs")
    found: list[str] = []
    for name in artifact_roots:
        root = run_dir / name
        if root.exists() and any(root.rglob("*")):
            found.append(str(root))
    recovery_root = run_dir / "phase_recovery"
    if recovery_root.exists():
        phase_recovery_children = [
            child
            for child in recovery_root.iterdir()
            if child.name != "worktree-baseline.json" and child.name != "worktree-baseline-files"
        ]
        if phase_recovery_children:
            found.append(str(recovery_root))
    if found:
        raise PhaseSessionError(
            "phase-session state is missing but phase execution artifacts already exist; "
            "refusing to create a new baseline over partial work: " + ", ".join(found)
        )


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


def _phase_to_cancel(state: Mapping[str, Any], phase_id: str | None) -> dict[str, Any] | None:
    if phase_id is not None:
        phase = _find_phase(state, phase_id)
        return phase if phase.get("status") not in TERMINAL_STATUSES else None
    for status in (STATUS_RUNNING, STATUS_LEASED, STATUS_RETRY_WAITING, STATUS_STALE):
        for phase in state.get("phases") or []:
            if isinstance(phase, dict) and phase.get("status") == status:
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
    phase["blocked_reason"] = None
    phase["retry_policy_decision"] = None
    phase["blocked_at"] = None
    phase["evidence_path"] = None


def _hard_reset_phase_to_pending(phase: dict[str, Any]) -> None:
    clear_to_none = (
        "child_pid",
        "command_path",
        "completed_at",
        "expected_handoff_path",
        "expected_result_path",
        "handoff_path",
        "last_failure_kind",
        "last_launcher_error",
        "launch_dir",
        "launch_metadata_error",
        "max_session_attempts",
        "parent_pid",
        "process_group_id",
        "prompt_sha",
        "recovery_context_path",
        "result_path",
        "retry_exhausted_at",
        "session_name",
        "started_at",
    )
    for key in clear_to_none:
        if key in phase:
            phase[key] = None
    phase["attempt"] = 0
    phase["attempt_history"] = []


def _normalize_state(state: dict[str, Any]) -> None:
    retry_policy = state.get("retry_policy")
    state["retry_policy"] = _normalize_retry_policy(retry_policy)
    for phase in state.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase.setdefault("max_session_attempts", None)
        phase.setdefault("next_retry_at", None)
        phase.setdefault("last_failure_kind", None)
        phase.setdefault("last_launcher_error", None)
        phase.setdefault("retry_exhausted_at", None)
        phase.setdefault("blocked_reason", None)
        phase.setdefault("retry_policy_decision", None)
        phase.setdefault("blocked_at", None)
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
        phase.setdefault("evidence_path", None)
        if not isinstance(phase.get("attempt_history"), list):
            phase["attempt_history"] = []


def _read_state_object(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PhaseSessionError(f"phase-session state is invalid JSON: {path}") from exc
    except OSError as exc:
        raise PhaseSessionError(f"phase-session state is not readable: {path}") from exc
    if not isinstance(state, dict):
        raise PhaseSessionError("phase-session state root must be an object")
    return state


def _policy_update_forces(policy_update: ResolvedPolicyUpdate | None) -> bool:
    forced = getattr(policy_update, "forced_overrides", None)
    return isinstance(forced, dict) and bool(forced)


def _configure_retry_policy_in_state(
    state: dict[str, Any],
    policy_update: ResolvedPolicyUpdate | None,
) -> dict[str, Any]:
    state = dict(state)
    state["retry_policy"] = _retry_policy_with_update(state.get("retry_policy"), policy_update)
    _normalize_state(state)
    _validate_state(state)
    return state


def _retry_policy_with_update(
    retry_policy: Any,
    policy_update: ResolvedPolicyUpdate | None,
) -> dict[str, Any]:
    existing = dict(retry_policy) if isinstance(retry_policy, Mapping) else {}
    defaults = dict(getattr(policy_update, "default_overrides", {}) or {})
    forced = dict(getattr(policy_update, "forced_overrides", {}) or {})
    try:
        validate_policy_overrides(defaults)
        validate_policy_overrides(forced)
    except ValueError as exc:
        raise PhaseSessionError(str(exc)) from exc
    for key, value in defaults.items():
        if existing.get(key) is None:
            existing[key] = value
    existing.update(forced)
    return _normalize_retry_policy(existing)


def _normalize_retry_policy(retry_policy: Any) -> dict[str, Any]:
    existing = dict(retry_policy) if isinstance(retry_policy, Mapping) else {}
    profile_value = existing.get("autopilot_profile")
    defaults = default_retry_policy()
    profile = profile_value if isinstance(profile_value, str) and profile_value else str(defaults["autopilot_profile"])
    try:
        normalized = default_retry_policy()
        normalized.update(profile_defaults(profile))
        normalized["autopilot_profile"] = profile
        for key, value in existing.items():
            if value is not None:
                normalized[key] = value
            elif key not in normalized:
                normalized[key] = value
        retry_policy_config(normalized)
    except ValueError as exc:
        raise PhaseSessionError(str(exc)) from exc
    return normalized


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _cancel_child_process_details(phase: Mapping[str, Any], *, kill_child: bool) -> dict[str, Any]:
    child_pid = phase.get("child_pid")
    process_group_id = phase.get("process_group_id")
    child_alive = _pid_alive(child_pid) if isinstance(child_pid, int) and child_pid > 0 else None
    details: dict[str, Any] = {
        "child_pid": child_pid if isinstance(child_pid, int) else None,
        "process_group_id": process_group_id if isinstance(process_group_id, int) else None,
        "child_alive_before_cancel": child_alive,
        "kill_requested": bool(kill_child),
        "kill_attempted": False,
        "kill_signal": None,
        "kill_target": None,
        "kill_error": None,
    }
    if not kill_child:
        return details
    if child_alive is False:
        return details
    current_pid = os.getpid()
    current_pgid = os.getpgrp() if hasattr(os, "getpgrp") else None
    try:
        if isinstance(process_group_id, int) and process_group_id > 0 and process_group_id != current_pgid:
            details["kill_attempted"] = True
            details["kill_signal"] = "SIGTERM"
            details["kill_target"] = f"pgid:{process_group_id}"
            os.killpg(process_group_id, signal.SIGTERM)
        elif isinstance(child_pid, int) and child_pid > 0 and child_pid != current_pid:
            details["kill_attempted"] = True
            details["kill_signal"] = "SIGTERM"
            details["kill_target"] = f"pid:{child_pid}"
            os.kill(child_pid, signal.SIGTERM)
    except ProcessLookupError:
        details["kill_error"] = "process_not_found"
    except Exception as exc:
        details["kill_error"] = str(exc)
    return details


def _pid_alive(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None


def _cancel_cleanup_details(
    state: Mapping[str, Any],
    phase_id: str,
    *,
    data_dir: Path,
    repo_root: Path | None,
) -> dict[str, Any]:
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    baseline_path = retry_policy.get("worktree_baseline_path") if isinstance(retry_policy.get("worktree_baseline_path"), str) else None
    untracked: list[str] = []
    warning = None
    try:
        from .worktree_baseline import changed_files_since_baseline

        changed = changed_files_since_baseline(baseline_path, repo_root=repo_root)
        warning = changed.get("warning") if isinstance(changed.get("warning"), str) else None
        changed_files = {str(item) for item in changed.get("changed_files") or [] if isinstance(item, str)}
        for line in changed.get("current_status_porcelain") or []:
            if isinstance(line, str) and line.startswith("?? ") and line[3:] in changed_files:
                untracked.append(line[3:])
    except Exception as exc:
        warning = str(exc)
    by_phase = {phase_id: untracked} if untracked else {}
    return {
        "untracked_artifacts_by_phase": by_phase,
        "untracked_artifact_count": len(untracked),
        "warning": warning,
        "commands": {
            "keep": "no command needed; run evidence and source files are preserved",
            "inspect": f"bin/swarm phases status {state.get('run_id')} --attempts --cost --events",
            "remove_generated_phase_artifacts": f"bin/swarm phases cleanup {state.get('run_id')} --phase {phase_id} --generated-artifacts --apply",
            "archive_run_evidence": f"bin/swarm phases archive {state.get('run_id')}",
        },
    }


def _phase_generated_artifact_targets(run_id: str, *, data_dir: Path, phase_id: str | None) -> list[Path]:
    run_dir = data_dir / "runs" / run_id
    specs: list[tuple[Path, Path]] = []
    for name in ("phase_results", "phase_handoffs", "phase_launches", "phase_recovery"):
        root = run_dir / name
        target = root / phase_id if phase_id else root
        specs.append((root, target))
    targets: list[Path] = []
    for root, target in specs:
        root_resolved = root.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        try:
            target_resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise PhaseSessionError(f"refusing cleanup target outside generated artifact allowlist: {target}") from exc
        targets.append(target)
    return targets


def _archive_label(label: str) -> str:
    if not label or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in label):
        raise PhaseSessionError("archive label may only contain letters, digits, dot, underscore, and dash")
    return label


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
        "blocked_reason",
        "retry_policy_decision",
        "blocked_at",
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
        "evidence_path",
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
        raise PhaseArtifactContractError("status_mismatch", f"result status {result_status!r} does not match expected {expected_status!r}")
    if result.get("run_id") != run_id or result.get("phase_id") != phase_id:
        raise PhaseArtifactContractError("result_identity_mismatch", "result run_id/phase_id mismatch")
    if result.get("prepared_plan_sha") != _phase_session_prepared_sha(run_id, data_dir=data_dir):
        raise PhaseArtifactContractError("prepared_plan_sha_mismatch", "result prepared_plan_sha does not match phase-session state")
    expected_phase_sha = _prepared_phase_content_sha(run_id, phase_id, data_dir=data_dir)
    if result.get("phase_content_sha") != expected_phase_sha:
        raise PhaseArtifactContractError("phase_content_sha_mismatch", "result phase_content_sha does not match prepared phase metadata")
    handoff_path = _resolve_artifact_path(result["handoff_path"], data_dir=data_dir, run_id=run_id, label="phase handoff")
    handoff = _load_and_validate_handoff(handoff_path)
    if handoff.get("run_id") != run_id or handoff.get("phase_id") != phase_id:
        raise PhaseArtifactContractError("handoff_identity_mismatch", "handoff run_id/phase_id mismatch")
    if handoff.get("phase_attempt") != result.get("phase_attempt"):
        raise PhaseArtifactContractError("attempt_mismatch", "handoff attempt does not match result attempt")
    if handoff.get("status") != result_status:
        raise PhaseArtifactContractError("handoff_status_mismatch", "handoff status does not match result status")
    if _enforce_work_unit_subset(run_id, phase_id, int(result["phase_attempt"]), data_dir=data_dir):
        allowed_unit_ids = _prepared_work_unit_ids(run_id, phase_id, data_dir=data_dir)
        _assert_completed_work_units_subset(result, allowed_unit_ids, label="result")
        _assert_completed_work_units_subset(handoff, allowed_unit_ids, label="handoff")
    return result_path, result, handoff_path, handoff


def validate_phase_artifacts(
    run_id: str,
    phase_id: str,
    *,
    json_file: str | os.PathLike[str],
    expected_status: str | None,
    data_dir: Path,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    return _validate_phase_artifacts(
        run_id,
        phase_id,
        json_file=json_file,
        expected_status=expected_status,
        data_dir=data_dir,
    )


def parse_phase_datetime(value: Any) -> datetime | None:
    return _parse_dt(value)


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
    if phase_status == STATUS_BLOCKED:
        phase["blocked_reason"] = BLOCKED_CHILD_REPORTED_BLOCKED
        phase["retry_policy_decision"] = "child_reported_blocked"
        phase["blocked_at"] = result["completed_at"]
    elif phase_status == STATUS_NEEDS_INPUT:
        phase["blocked_reason"] = BLOCKED_CHILD_REPORTED_BLOCKED
        phase["retry_policy_decision"] = "child_reported_needs_input"
        phase["blocked_at"] = result["completed_at"]
    elif phase_status == STATUS_COMPLETE:
        phase["blocked_reason"] = None
        phase["retry_policy_decision"] = None
        phase["blocked_at"] = None
    return phase_status


def _attempt_record_from_phase(phase: Mapping[str, Any]) -> dict[str, Any]:
    started = _parse_dt(phase.get("started_at"))
    completed = _parse_dt(phase.get("completed_at")) or _utc_now_dt()
    elapsed = (completed - started).total_seconds() if started is not None else None
    record = {
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
        "partial_artifacts": False,
        "evidence_path": phase.get("evidence_path"),
        "stdout_tail_path": None,
        "stderr_tail_path": None,
        "changed_files": [],
        "artifact_error_kinds": [],
        "diff_summary_path": None,
        "recovery_context_path": phase.get("recovery_context_path"),
    }
    record.update(_taxonomy_event_details(record))
    return record


def _append_attempt_history(phase: dict[str, Any], record: Mapping[str, Any]) -> None:
    attempt = int(record.get("attempt") or phase.get("attempt") or 0)
    if attempt <= 0:
        return
    item = dict(_attempt_record_from_phase(phase))
    item.update(
        {
            key: value
            for key, value in record.items()
            if value is not None and key not in {"status", "blocked_reason"}
        }
    )
    taxonomy = _taxonomy_event_details(item)
    for key, value in taxonomy.items():
        if item.get(key) is None:
            item[key] = value
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


def _taxonomy_event_details(record: Mapping[str, Any]) -> dict[str, Any]:
    failure_kind = record.get("failure_kind")
    details = failure_kind_details(failure_kind)
    fields = {
        "failure_category",
        "failure_retry_class",
        "failure_operator_title",
        "failure_operator_message",
        "failure_known",
    }
    return {
        key: value
        for key, value in details.items()
        if key in fields
    }


def _policy_event_details(record: Mapping[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for key in ("policy_action", "policy_reason"):
        value = record.get(key)
        if isinstance(value, str) and value:
            details[key] = value
    policy_inputs = record.get("policy_inputs")
    if isinstance(policy_inputs, Mapping):
        details["policy_inputs"] = dict(policy_inputs)
    return details


def _write_attempt_evidence_best_effort(
    data_dir: Path,
    *,
    run_id: str,
    state: Mapping[str, Any],
    phase: dict[str, Any],
    transition: str,
    attempt_record: Mapping[str, Any] | None = None,
) -> str | None:
    attempt = int((attempt_record or {}).get("attempt") or phase.get("attempt") or 0)
    if attempt <= 0:
        return None
    phase_id = str(phase.get("phase_id") or "")
    launch_dir = phase.get("launch_dir")
    evidence_path = attempt_evidence_path(data_dir, run_id, phase_id, attempt)
    try:
        path = write_attempt_evidence_manifest(
            run_id,
            phase,
            state=state,
            attempt_record=attempt_record,
            data_dir=data_dir,
        )
    except Exception as exc:
        try:
            _append_phase_event(
                data_dir,
                run_id=run_id,
                event_type="phase_attempt_evidence_failed",
                phase=phase,
                reason="manifest_write_failed",
                details={
                    "phase_id": phase_id,
                    "attempt": attempt,
                    "launcher": (attempt_record or {}).get("launcher") or _launcher_from_command(phase.get("lease_command")),
                    "transition": transition,
                    "launch_dir": launch_dir,
                    "evidence_path": str(evidence_path),
                    "error_class": exc.__class__.__name__,
                    "error_message": str(exc),
                    "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                },
            )
        except Exception:
            pass
        return None
    value = str(path)
    phase["evidence_path"] = value
    return value


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


def _enforce_work_unit_subset(run_id: str, phase_id: str, attempt: int, *, data_dir: Path) -> bool:
    try:
        state = load_phase_sessions(run_id, data_dir=data_dir)
    except Exception:
        return False
    for phase in state.get("phases") or []:
        if not isinstance(phase, Mapping) or phase.get("phase_id") != phase_id:
            continue
        if int(phase.get("attempt") or 0) != attempt:
            return False
        return phase.get("status") in {STATUS_RUNNING, STATUS_STALE}
    return False


def _prepared_work_unit_ids(run_id: str, phase_id: str, *, data_dir: Path) -> set[str]:
    try:
        prepared = json.loads(_prepared_artifact_path(run_id, data_dir=data_dir).read_text(encoding="utf-8"))
    except Exception:
        return set()
    root = _prepared_repo_root(prepared, repo_root=None)
    descriptor = (prepared.get("work_unit_artifacts") or {}).get(phase_id)
    if not isinstance(descriptor, Mapping):
        return set()
    path = root / str(descriptor.get("path") or "")
    try:
        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {
        str(unit["id"])
        for unit in sidecar.get("work_units") or []
        if isinstance(unit, Mapping) and isinstance(unit.get("id"), str)
    }


def _assert_completed_work_units_subset(payload: Mapping[str, Any], allowed_unit_ids: set[str], *, label: str) -> None:
    values = payload.get("completed_work_units")
    if not isinstance(values, list):
        return
    unexpected = sorted({str(item) for item in values if isinstance(item, str)} - allowed_unit_ids)
    if unexpected:
        raise PhaseArtifactContractError(
            "completed_work_units_not_prepared",
            f"{label} completed_work_units contains ids that were not prepared for this phase: {', '.join(unexpected)}",
        )


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
        raise PhaseArtifactContractError("path_escape", f"{label} path escapes run directory: {path}") from exc


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
    "PhaseArtifactContractError",
    "PhaseSessionLockTimeout",
    "abandon_attempt_and_retry",
    "adopt_phase_result",
    "archive_phase_session_evidence",
    "cancel_phase_session_run",
    "claim_next_phase",
    "cleanup_phase_generated_artifacts",
    "generate_lease_owner",
    "init_phase_sessions",
    "load_phase_sessions",
    "mark_phase_blocked",
    "locked_phase_sessions",
    "mark_retry_exhausted",
    "phase_handoff_path",
    "phase_result_path",
    "phase_session_path",
    "phase_status",
    "parse_phase_datetime",
    "read_phase_session_summary",
    "reap_expired_phases",
    "record_phase_result",
    "record_launch_metadata",
    "release_retry_waiting",
    "repair_active_phase_lease",
    "reset_phase_session",
    "refresh_phase",
    "start_phase",
    "validate_phase_artifacts",
]
