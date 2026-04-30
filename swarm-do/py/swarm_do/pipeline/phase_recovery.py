"""Durable reconciliation for phase-session foreground recovery."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT, resolve_data_dir
from .phase_sessions import (
    BLOCKED_DETERMINISTIC_CONTRACT_FAILURE,
    BLOCKED_PERMISSION_CONTRACT_FAILURE,
    BLOCKED_RETRY_POLICY_HUMAN_GATE,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_LEASED,
    STATUS_NEEDS_INPUT,
    STATUS_PENDING,
    STATUS_RETRY_EXHAUSTED,
    STATUS_RETRY_WAITING,
    STATUS_RUNNING,
    PhaseArtifactContractError,
    PhaseSessionError,
    abandon_attempt_and_retry,
    adopt_phase_result,
    load_phase_sessions,
    mark_phase_blocked,
    mark_retry_exhausted,
    parse_phase_datetime,
    phase_handoff_path,
    phase_result_path,
    phase_status,
    release_retry_waiting,
    validate_phase_artifacts,
)
from .run_state import append_run_event, utc_now, validate_run_event
from .session_capabilities import extract_claude_print_artifacts, parse_claude_print_json
from .worktree_baseline import changed_files_since_baseline
from .phase_beads import write_phase_beads_note


ACTIVE_STATUSES = {STATUS_LEASED, STATUS_RUNNING}
STOP_STATUSES = (STATUS_BLOCKED, STATUS_NEEDS_INPUT, STATUS_RETRY_EXHAUSTED)
MAX_RECONCILIATION_PASSES = 20
DEFAULT_BACKOFF_SCHEDULE_SECONDS = (60, 180, 600)


def reconcile_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    launcher: str | None = None,
    now: datetime | None = None,
    launcher_result: Mapping[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    actions: list[dict[str, Any]] = []

    try:
        state = load_phase_sessions(run_id, data_dir=base)
    except Exception as exc:
        return _decision(
            run_id,
            base,
            "drift",
            actions,
            blocked_reason=str(exc),
        )

    # A single pass may adopt/release one phase and then need to re-read state.
    # This cap prevents malformed state from spinning the foreground pump forever.
    for _ in range(MAX_RECONCILIATION_PASSES):
        status = _stable_terminal_status(state)
        if status is not None:
            return _decision(run_id, base, status, actions)

        retry_waiting = _first_phase(state, STATUS_RETRY_WAITING)
        if retry_waiting is not None:
            retry_at = parse_phase_datetime(retry_waiting.get("next_retry_at"))
            retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
            retry_sleep_threshold = int(retry_policy.get("retry_sleep_threshold_seconds") or 0)
            if retry_at is not None and retry_at > current_time:
                wait_seconds = max(0, int((retry_at - current_time).total_seconds()))
                actions.append(
                    {
                        "phase_id": retry_waiting.get("phase_id"),
                        "attempt": retry_waiting.get("attempt"),
                        "action": "retry_waiting",
                        "next_retry_at": retry_waiting.get("next_retry_at"),
                        "retry_sleep_seconds": wait_seconds,
                        "retry_sleep_threshold_seconds": retry_sleep_threshold,
                    }
                )
                return _decision(run_id, base, STATUS_RETRY_WAITING, actions)
            actions.append(
                {
                    "phase_id": retry_waiting.get("phase_id"),
                    "attempt": retry_waiting.get("attempt"),
                    "action": "retry_ready",
                }
            )
            if not dry_run:
                release_retry_waiting(run_id, str(retry_waiting["phase_id"]), data_dir=base)
                state = load_phase_sessions(run_id, data_dir=base)
                continue
            return _decision(run_id, base, "ready", actions)

        phase = _first_recoverable_phase(state)
        if phase is None:
            current = phase_status(run_id, data_dir=base, repo_root=repo_root)
            return _decision(
                run_id,
                base,
                str(current.get("status") or "ready"),
                actions,
                current_status=current,
            )

        phase_id = str(phase["phase_id"])
        attempt = int(phase.get("attempt") or 0)
        artifact = _current_attempt_artifacts(run_id, phase, data_dir=base)
        if artifact.get("valid"):
            result = artifact["result"]
            handoff = artifact["handoff"]
            terminal_status = str(result.get("status"))
            retryable_failed = terminal_status == "failed" and bool(result.get("retryable")) and not _handoff_do_not_retry(handoff)
            evidence = _build_attempt_evidence(
                run_id,
                phase,
                state=state,
                data_dir=base,
                repo_root=repo_root,
                launcher=launcher,
                launcher_result=launcher_result,
                failure_kind=_artifact_failure_kind(result, launcher_result),
                retry_decision="retry" if retryable_failed else "adopted",
                adopted=not retryable_failed,
                result_path=str(artifact["result_path"]),
                handoff_path=str(artifact["handoff_path"]),
            )
            if retryable_failed:
                action = _retry_or_exhaust(
                    run_id,
                    phase,
                    state=state,
                    data_dir=base,
                    now=current_time,
                    evidence=evidence,
                    failure_kind=str(result.get("failure_kind") or "structured_retryable_failed"),
                    launcher_error=_result_error(result),
                    retry_after_seconds=_retry_after_seconds(result, state),
                    dry_run=dry_run,
                )
                actions.append(action)
                if not dry_run and action.get("action") in {"retry_scheduled", "retry_ready"}:
                    state = load_phase_sessions(run_id, data_dir=base)
                    continue
                return _decision(run_id, base, str(action.get("status") or STATUS_RETRY_EXHAUSTED), actions)

            action_name = "adopted_completion" if terminal_status == "complete" else f"adopted_{terminal_status}"
            actions.append(
                {
                    "phase_id": phase_id,
                    "attempt": attempt,
                    "action": action_name,
                    "failure_kind": evidence.get("failure_kind"),
                    "retry_decision": "adopted",
                    "result_path": str(artifact["result_path"]),
                    "handoff_path": str(artifact["handoff_path"]),
                }
            )
            if not dry_run:
                adopt_phase_result(
                    run_id,
                    phase_id,
                    json_file=str(artifact["result_path"]),
                    expected_status=terminal_status,
                    data_dir=base,
                    attempt_record=evidence,
                )
                _append_recovery_event(base, run_id=run_id, event_type="phase_session_reconciled", details=actions[-1])
                note_kind = (
                    "phase_attempt_adopted"
                    if terminal_status == "complete"
                    else "phase_human_gated"
                    if terminal_status in {"blocked", "needs_input"}
                    else "phase_hard_stop"
                )
                _write_recovery_note(
                    run_id,
                    base,
                    kind=note_kind,
                    phase_id=phase_id,
                    details=actions[-1],
                )
                state = load_phase_sessions(run_id, data_dir=base)
                if terminal_status == "complete":
                    continue
            return _decision(run_id, base, terminal_status if terminal_status != "failed" else "failed_nonretryable", actions)

        if phase.get("status") in ACTIVE_STATUSES and launcher_result is None:
            active_action = _active_phase_decision(phase, now=current_time)
            if active_action.get("status") == "active":
                actions.append(active_action)
                return _decision(run_id, base, "active", actions)
            failure_kind = str(active_action.get("failure_kind") or "active_attempt_abandoned")
        elif phase.get("status") == STATUS_FAILED:
            failure_kind = str(phase.get("last_failure_kind") or "failed_nonretryable")
            return _decision(run_id, base, "failed_nonretryable", actions, blocked_reason=failure_kind)
        else:
            failure_kind = _launcher_failure_kind(launcher_result, artifact)

        evidence = _build_attempt_evidence(
            run_id,
            phase,
            state=state,
            data_dir=base,
            repo_root=repo_root,
            launcher=launcher,
            launcher_result=launcher_result,
            failure_kind=failure_kind,
            retry_decision="retry",
            adopted=False,
            partial_artifacts=artifact.get("partial", False),
            artifact_error_kinds=artifact.get("error_kinds") or [],
        )
        action = _retry_or_exhaust(
            run_id,
            phase,
            state=state,
            data_dir=base,
            now=current_time,
            evidence=evidence,
            failure_kind=failure_kind,
            launcher_error=_launcher_error(launcher_result, artifact),
            retry_after_seconds=None,
            dry_run=dry_run,
        )
        actions.append(action)
        if not dry_run and action.get("action") in {"retry_scheduled", "retry_ready"}:
            state = load_phase_sessions(run_id, data_dir=base)
            continue
        return _decision(run_id, base, str(action.get("status") or STATUS_RETRY_EXHAUSTED), actions)

    return _decision(run_id, base, "drift", actions, blocked_reason="reconciliation iteration limit exceeded")


def _current_attempt_artifacts(run_id: str, phase: Mapping[str, Any], *, data_dir: Path) -> dict[str, Any]:
    attempt = int(phase.get("attempt") or 0)
    if attempt <= 0:
        return {"valid": False, "partial": False, "errors": ["phase attempt is zero"]}
    result_path = _phase_path(phase.get("expected_result_path"), data_dir=data_dir) or phase_result_path(
        run_id,
        str(phase["phase_id"]),
        attempt,
        data_dir=data_dir,
    )
    handoff_path = _phase_path(phase.get("expected_handoff_path"), data_dir=data_dir) or phase_handoff_path(
        run_id,
        str(phase["phase_id"]),
        attempt,
        data_dir=data_dir,
    )
    partial = result_path.exists() or handoff_path.exists()
    try:
        resolved_result, result, resolved_handoff, handoff = validate_phase_artifacts(
            run_id,
            str(phase["phase_id"]),
            json_file=str(result_path),
            expected_status=None,
            data_dir=data_dir,
        )
    except PhaseArtifactContractError as exc:
        return {
            "valid": False,
            "partial": partial,
            "result_path": result_path,
            "handoff_path": handoff_path,
            "errors": [str(exc)],
            "error_kinds": [exc.kind],
        }
    except Exception as exc:
        return {
            "valid": False,
            "partial": partial,
            "result_path": result_path,
            "handoff_path": handoff_path,
            "errors": [str(exc)],
            "error_kinds": [],
        }
    return {
        "valid": True,
        "partial": partial,
        "result_path": resolved_result,
        "handoff_path": resolved_handoff,
        "result": result,
        "handoff": handoff,
        "errors": [],
    }


def _retry_or_exhaust(
    run_id: str,
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    data_dir: Path,
    now: datetime,
    evidence: Mapping[str, Any],
    failure_kind: str,
    launcher_error: str | None,
    retry_after_seconds: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    attempt = int(phase.get("attempt") or 0)
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    max_attempts = int(phase.get("max_session_attempts") or retry_policy.get("max_session_attempts") or 3)
    phase_id = str(phase["phase_id"])

    stop_decision = _retry_stop_decision(failure_kind, evidence)
    same_failure_count = _same_failure_count(phase, failure_kind, include_current=True)
    same_failure_limit = int(retry_policy.get("max_consecutive_same_failure_kind") or 2)
    if stop_decision is not None:
        blocked_reason, retry_policy_decision = stop_decision
        if not dry_run:
            mark_phase_blocked(
                run_id,
                phase_id,
                failure_kind=failure_kind,
                blocked_reason=blocked_reason,
                retry_policy_decision=retry_policy_decision,
                data_dir=data_dir,
                launcher_error=launcher_error,
                attempt_record={**evidence, "retry_decision": retry_policy_decision},
                details={
                    "same_failure_count": same_failure_count,
                    "max_consecutive_same_failure_kind": same_failure_limit,
                },
            )
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_human_gated",
                phase_id=phase_id,
                details={"failure_kind": failure_kind, "retry_policy_decision": retry_policy_decision},
            )
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": attempt,
            "action": "blocked",
            "status": STATUS_BLOCKED,
            "failure_kind": failure_kind,
            "blocked_reason": blocked_reason,
            "retry_decision": retry_policy_decision,
        }

    if same_failure_count >= same_failure_limit:
        retry_policy_decision = "same_failure_limit"
        if not dry_run:
            mark_phase_blocked(
                run_id,
                phase_id,
                failure_kind=failure_kind,
                blocked_reason=BLOCKED_RETRY_POLICY_HUMAN_GATE,
                retry_policy_decision=retry_policy_decision,
                data_dir=data_dir,
                launcher_error=launcher_error,
                attempt_record={**evidence, "retry_decision": retry_policy_decision},
                details={
                    "same_failure_count": same_failure_count,
                    "max_consecutive_same_failure_kind": same_failure_limit,
                },
            )
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_human_gated",
                phase_id=phase_id,
                details={
                    "failure_kind": failure_kind,
                    "retry_policy_decision": retry_policy_decision,
                    "same_failure_count": same_failure_count,
                },
            )
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": attempt,
            "action": "blocked",
            "status": STATUS_BLOCKED,
            "failure_kind": failure_kind,
            "blocked_reason": BLOCKED_RETRY_POLICY_HUMAN_GATE,
            "retry_decision": retry_policy_decision,
            "same_failure_count": same_failure_count,
        }

    needs_recovery_retry = _needs_recovery_retry(evidence, state)
    max_recovery_attempts = int(retry_policy.get("max_recovery_attempts") or 0)
    recovery_attempts_used = sum(
        1
        for item in phase.get("attempt_history") or []
        if isinstance(item, Mapping) and item.get("retry_decision") == "recovery_retry"
    )
    if attempt >= max_attempts or (needs_recovery_retry and recovery_attempts_used >= max_recovery_attempts):
        if not dry_run:
            mark_retry_exhausted(
                run_id,
                phase_id,
                failure_kind=failure_kind,
                data_dir=data_dir,
                launcher_error=launcher_error,
                attempt_record=evidence,
            )
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_attempt_retry_exhausted",
                phase_id=phase_id,
                details={"failure_kind": failure_kind, "recovery_context_path": evidence.get("recovery_context_path")},
            )
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": attempt,
            "action": "retry_exhausted",
            "status": STATUS_RETRY_EXHAUSTED,
            "failure_kind": failure_kind,
            "retry_decision": "retry_exhausted",
        }

    retry_after_seconds = retry_after_seconds if retry_after_seconds is not None else _fallback_retry_after_seconds(attempt, retry_policy)
    next_retry_at = _format_dt(now + timedelta(seconds=retry_after_seconds)) if retry_after_seconds > 0 else None
    retry_decision = "recovery_retry" if needs_recovery_retry else "retry"
    record = dict(evidence)
    record["retry_decision"] = retry_decision
    record["retry_after_seconds"] = retry_after_seconds if retry_after_seconds > 0 else None
    if not dry_run:
        abandon_attempt_and_retry(
            run_id,
            phase_id,
            failure_kind=failure_kind,
            data_dir=data_dir,
            launcher_error=launcher_error,
            next_retry_at=next_retry_at,
            retry_after_seconds=retry_after_seconds if retry_after_seconds > 0 else None,
            attempt_record=record,
        )
        if next_retry_at:
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_attempt_retry_scheduled",
                phase_id=phase_id,
                details={
                    "failure_kind": failure_kind,
                    "next_retry_at": next_retry_at,
                    "recovery_context_path": evidence.get("recovery_context_path"),
                },
            )
    return {
        "phase_id": phase.get("phase_id"),
        "attempt": attempt,
        "action": "retry_scheduled" if next_retry_at else "retry_ready",
        "status": STATUS_RETRY_WAITING if next_retry_at else "ready",
        "failure_kind": failure_kind,
        "retry_decision": retry_decision,
        "next_retry_at": next_retry_at,
        "retry_after_seconds": retry_after_seconds if retry_after_seconds > 0 else None,
    }


def _build_attempt_evidence(
    run_id: str,
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    data_dir: Path,
    repo_root: Path | None,
    launcher: str | None,
    launcher_result: Mapping[str, Any] | None,
    failure_kind: str,
    retry_decision: str,
    adopted: bool,
    result_path: str | None = None,
    handoff_path: str | None = None,
    partial_artifacts: bool = False,
    artifact_error_kinds: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    attempt = int(phase.get("attempt") or 0)
    recovery_dir = data_dir / "runs" / run_id / "phase_recovery" / str(phase["phase_id"])
    recovery_dir.mkdir(parents=True, exist_ok=True)
    launch_dir = _launch_dir(run_id, phase, data_dir=data_dir)
    stdout_tail_path = recovery_dir / f"attempt-{attempt}.stdout.tail.txt"
    stderr_tail_path = recovery_dir / f"attempt-{attempt}.stderr.tail.txt"
    stdout_text = _tail_text(_launch_text(launch_dir, "stdout.txt", launcher_result, "stdout"))
    stderr_text = _tail_text(_launch_text(launch_dir, "stderr.txt", launcher_result, "stderr"))
    stdout_tail_path.write_text(stdout_text, encoding="utf-8")
    stderr_tail_path.write_text(stderr_text, encoding="utf-8")
    baseline_path = None
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    if isinstance(retry_policy.get("worktree_baseline_path"), str):
        baseline_path = retry_policy.get("worktree_baseline_path")
    diff = changed_files_since_baseline(baseline_path, repo_root=repo_root)
    diff_summary_path = recovery_dir / f"attempt-{attempt}.diff-summary.md"
    diff_summary = str(diff.get("diff_summary") or diff.get("warning") or "No baseline-relative diff evidence.")
    diff_summary_path.write_text(diff_summary.rstrip() + "\n", encoding="utf-8")
    recovery_context_path = recovery_dir / f"attempt-{attempt}.recovery.md"
    changed_files = [str(item) for item in diff.get("changed_files") or [] if isinstance(item, str)]
    command = _command_metadata(launch_dir)
    completed_at = utc_now()
    elapsed = _elapsed_seconds(phase, completed_at)
    recovery_context_path.write_text(
        _recovery_markdown(
            phase=phase,
            failure_kind=failure_kind,
            retry_decision=retry_decision,
            launch_dir=str(launch_dir) if launch_dir else str(phase.get("launch_dir") or ""),
            returncode=_returncode(launcher_result, command),
            elapsed_seconds=elapsed,
            stdout_tail_path=stdout_tail_path,
            stderr_tail_path=stderr_tail_path,
            changed_files=changed_files,
            diff_summary_path=diff_summary_path,
            partial_artifacts=partial_artifacts,
        ),
        encoding="utf-8",
    )
    return {
        "attempt": attempt,
        "session_name": phase.get("session_name"),
        "launcher": launcher or _metadata_launcher(command) or _launcher_from_phase(phase),
        "lease_owner": phase.get("lease_owner"),
        "lease_host": phase.get("lease_host"),
        "lease_pid": phase.get("lease_pid"),
        "child_pid": phase.get("child_pid") or command.get("child_pid"),
        "process_group_id": phase.get("process_group_id") or command.get("process_group_id"),
        "started_at": phase.get("started_at"),
        "completed_at": completed_at,
        "elapsed_seconds": elapsed,
        "launch_dir": str(launch_dir) if launch_dir else phase.get("launch_dir"),
        "result_path": result_path or phase.get("result_path") or phase.get("expected_result_path"),
        "handoff_path": handoff_path or phase.get("handoff_path") or phase.get("expected_handoff_path"),
        "returncode": _returncode(launcher_result, command),
        "failure_kind": failure_kind,
        "retry_decision": retry_decision,
        "retry_after_seconds": None,
        "adopted": adopted,
        "partial_artifacts": partial_artifacts,
        "artifact_error_kinds": [str(item) for item in artifact_error_kinds if isinstance(item, str)],
        "stdout_tail_path": str(stdout_tail_path),
        "stderr_tail_path": str(stderr_tail_path),
        "changed_files": changed_files,
        "diff_summary_path": str(diff_summary_path),
        "recovery_context_path": str(recovery_context_path),
    }


def _needs_recovery_retry(evidence: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    threshold = float(retry_policy.get("recovery_timeout_threshold_seconds") or 600)
    elapsed = evidence.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)) and elapsed > threshold:
        return True
    if evidence.get("changed_files"):
        return True
    if evidence.get("partial_artifacts"):
        return True
    return False


def _same_failure_count(phase: Mapping[str, Any], failure_kind: str, *, include_current: bool) -> int:
    count = 1 if include_current else 0
    for item in phase.get("attempt_history") or []:
        if isinstance(item, Mapping) and item.get("failure_kind") == failure_kind:
            count += 1
    return count


def _fallback_retry_after_seconds(attempt: int, retry_policy: Mapping[str, Any]) -> int:
    maximum = int(retry_policy.get("max_retry_after_seconds") or 1800)
    configured = retry_policy.get("short_retry_backoff_seconds")
    if isinstance(configured, int) and configured > 0 and attempt <= 1:
        return min(configured, maximum)
    index = min(max(attempt - 1, 0), len(DEFAULT_BACKOFF_SCHEDULE_SECONDS) - 1)
    return min(DEFAULT_BACKOFF_SCHEDULE_SECONDS[index], maximum)


def _retry_stop_decision(failure_kind: str, evidence: Mapping[str, Any]) -> tuple[str, str] | None:
    returncode = evidence.get("returncode")
    if failure_kind in {"claude_cli_missing", "launcher_ineligible"}:
        return (BLOCKED_RETRY_POLICY_HUMAN_GATE, failure_kind)
    if failure_kind == "permission_contract_failure":
        return (BLOCKED_PERMISSION_CONTRACT_FAILURE, "permission_contract_failure")
    if failure_kind in {"outer_json_invalid_no_artifacts", "outer_artifacts_missing"} and returncode == 0:
        return (BLOCKED_RETRY_POLICY_HUMAN_GATE, "deterministic_contract_failure")
    artifact_error_kinds = {str(item) for item in evidence.get("artifact_error_kinds") or [] if isinstance(item, str)}
    if artifact_error_kinds & _DETERMINISTIC_ARTIFACT_ERROR_KINDS:
        return (BLOCKED_DETERMINISTIC_CONTRACT_FAILURE, "deterministic_contract_failure")
    return None


_DETERMINISTIC_ARTIFACT_ERROR_KINDS = {
    "path_escape",
    "result_identity_mismatch",
    "prepared_plan_sha_mismatch",
    "phase_content_sha_mismatch",
    "handoff_identity_mismatch",
    "attempt_mismatch",
    "handoff_status_mismatch",
    "completed_work_units_not_prepared",
}


def _active_phase_decision(phase: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    expires = parse_phase_datetime(phase.get("lease_expires_at"))
    if expires is not None and expires <= now:
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": phase.get("attempt"),
            "action": "lease_expired",
            "failure_kind": "lease_expired_no_artifacts",
        }
    if phase.get("lease_host") == socket.gethostname() and _child_death_proven(phase):
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": phase.get("attempt"),
            "action": "child_dead",
            "failure_kind": "child_process_dead_no_artifacts",
        }
    return {
        "phase_id": phase.get("phase_id"),
        "attempt": phase.get("attempt"),
        "action": "active_preserved",
        "status": "active",
    }


def _child_death_proven(phase: Mapping[str, Any]) -> bool:
    pid = phase.get("child_pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    alive = _pid_alive(pid)
    if alive is False:
        return True
    if alive is True:
        expected_pgid = phase.get("process_group_id")
        if isinstance(expected_pgid, int) and expected_pgid > 0:
            group_matches = _process_group_matches(pid, expected_pgid)
            if group_matches is False:
                return True
    return False


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


def _process_group_matches(pid: int, expected_pgid: int) -> bool | None:
    try:
        return os.getpgid(pid) == expected_pgid
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None


def _stable_terminal_status(state: Mapping[str, Any]) -> str | None:
    phases = [phase for phase in state.get("phases") or [] if isinstance(phase, Mapping)]
    if phases and all(phase.get("status") == STATUS_COMPLETE for phase in phases):
        return "complete"
    for status in STOP_STATUSES:
        if _first_phase(state, status) is not None:
            return str(status)
    return None


def _first_recoverable_phase(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for phase in state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        status = phase.get("status")
        if status in {STATUS_COMPLETE, STATUS_PENDING}:
            continue
        return phase
    return None


def _first_phase(state: Mapping[str, Any], status: str) -> Mapping[str, Any] | None:
    for phase in state.get("phases") or []:
        if isinstance(phase, Mapping) and phase.get("status") == status:
            return phase
    return None


def _decision(
    run_id: str,
    data_dir: Path,
    status: str,
    actions: list[dict[str, Any]],
    *,
    current_status: Mapping[str, Any] | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    current = dict(current_status or phase_status(run_id, data_dir=data_dir))
    return {
        "status": status,
        "actions": actions,
        "active_phase": current.get("active_phase"),
        "next_phase": current.get("next_phase"),
        "blocked_reason": blocked_reason,
        "phase_status": current,
    }


def _artifact_failure_kind(result: Mapping[str, Any], launcher_result: Mapping[str, Any] | None) -> str:
    if isinstance(result.get("failure_kind"), str):
        return str(result["failure_kind"])
    if launcher_result is not None and int(launcher_result.get("returncode") or 0) != 0:
        return "launcher_nonzero_with_artifacts"
    return "adoptable_artifacts"


def _launcher_failure_kind(launcher_result: Mapping[str, Any] | None, artifact: Mapping[str, Any]) -> str:
    if artifact.get("partial"):
        return "partial_artifacts_invalid"
    if not launcher_result:
        return "lease_expired_no_artifacts"
    reason = launcher_result.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    returncode = launcher_result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return "launcher_nonzero_no_artifacts"
    stdout = str(launcher_result.get("stdout") or "")
    try:
        outer = parse_claude_print_json(stdout)
        extract_claude_print_artifacts(outer, run_dir=Path("/definitely-not-used"))
    except ValueError as exc:
        if not stdout:
            return "outer_json_missing_no_artifacts"
        if "missing artifact object" in str(exc):
            return "outer_artifacts_missing"
        return "outer_json_invalid_no_artifacts"
    except Exception:
        return "outer_json_invalid_no_artifacts" if stdout else "outer_json_missing_no_artifacts"
    return "outer_artifacts_missing"


def _launcher_error(launcher_result: Mapping[str, Any] | None, artifact: Mapping[str, Any]) -> str | None:
    if artifact.get("errors"):
        return "; ".join(str(item) for item in artifact.get("errors") or [])
    if not launcher_result:
        return None
    reason = launcher_result.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    if launcher_result.get("returncode") is not None:
        return f"launcher returncode {launcher_result.get('returncode')}"
    return None


def _result_error(result: Mapping[str, Any]) -> str | None:
    error = result.get("error")
    if isinstance(error, Mapping):
        message = error.get("message") or error.get("type")
        if isinstance(message, str):
            return message
    return result.get("summary") if isinstance(result.get("summary"), str) else None


def _retry_after_seconds(result: Mapping[str, Any], state: Mapping[str, Any]) -> int | None:
    value = result.get("retry_after_seconds")
    if not isinstance(value, int):
        return None
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    maximum = int(retry_policy.get("max_retry_after_seconds") or 1800)
    return min(max(0, value), maximum)


def _handoff_do_not_retry(handoff: Mapping[str, Any]) -> bool:
    values = handoff.get("do_not_retry")
    return isinstance(values, list) and any(isinstance(item, str) and item for item in values)


def _launch_dir(run_id: str, phase: Mapping[str, Any], *, data_dir: Path) -> Path | None:
    path = _phase_path(phase.get("launch_dir"), data_dir=data_dir)
    if path is not None:
        return path
    attempt = int(phase.get("attempt") or 0)
    if attempt <= 0:
        return None
    return data_dir / "runs" / run_id / "phase_launches" / str(phase["phase_id"]) / f"attempt-{attempt}"


def _phase_path(value: Any, *, data_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [REPO_ROOT / path, data_dir / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _command_metadata(launch_dir: Path | None) -> dict[str, Any]:
    if launch_dir is None:
        return {}
    path = launch_dir / "command.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _launch_text(
    launch_dir: Path | None,
    filename: str,
    launcher_result: Mapping[str, Any] | None,
    result_key: str,
) -> str:
    if launch_dir is not None:
        path = launch_dir / filename
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    if launcher_result is not None:
        value = launcher_result.get(result_key)
        if isinstance(value, str):
            return value
    return ""


def _tail_text(value: str, *, max_bytes: int = 4000) -> str:
    data = value.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return value
    return data[-max_bytes:].decode("utf-8", errors="replace")


def _returncode(launcher_result: Mapping[str, Any] | None, command: Mapping[str, Any]) -> int | None:
    value = launcher_result.get("returncode") if launcher_result is not None else None
    if isinstance(value, int):
        return value
    value = command.get("returncode")
    return value if isinstance(value, int) else None


def _metadata_launcher(command: Mapping[str, Any]) -> str | None:
    argv = command.get("argv")
    if isinstance(argv, list) and argv:
        return "claude-print"
    return None


def _launcher_from_phase(phase: Mapping[str, Any]) -> str | None:
    command = phase.get("lease_command")
    if isinstance(command, str) and ":" in command:
        return command.rsplit(":", 1)[-1]
    return command if isinstance(command, str) else None


def _elapsed_seconds(phase: Mapping[str, Any], completed_at: str) -> float | None:
    started = parse_phase_datetime(phase.get("started_at"))
    completed = parse_phase_datetime(completed_at)
    if started is None or completed is None:
        return None
    elapsed = (completed - started).total_seconds()
    return elapsed if elapsed >= 0 else None


def _recovery_markdown(
    *,
    phase: Mapping[str, Any],
    failure_kind: str,
    retry_decision: str,
    launch_dir: str,
    returncode: int | None,
    elapsed_seconds: float | None,
    stdout_tail_path: Path,
    stderr_tail_path: Path,
    changed_files: list[str],
    diff_summary_path: Path,
    partial_artifacts: bool,
) -> str:
    lines = [
        f"# Recovery Context: Phase {phase.get('phase_id')} Attempt {phase.get('attempt')}",
        "",
        f"- session_name: {phase.get('session_name')}",
        f"- failure_kind: {failure_kind}",
        f"- retry_decision: {retry_decision}",
        f"- launch_dir: {launch_dir or 'unknown'}",
        f"- returncode: {returncode if returncode is not None else 'unknown'}",
        f"- elapsed_seconds: {elapsed_seconds if elapsed_seconds is not None else 'unknown'}",
        f"- stdout_tail_path: {stdout_tail_path}",
        f"- stderr_tail_path: {stderr_tail_path}",
        f"- diff_summary_path: {diff_summary_path}",
        f"- partial_artifacts: {str(partial_artifacts).lower()}",
        "",
        "## Changed Files Since Baseline",
    ]
    lines.extend(f"- {path}" for path in changed_files)
    if not changed_files:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Recovery Instruction",
            "Inspect the existing work and continue from it, or return blocked/needs_input with a clear reason. Do not restart blindly.",
            "",
        ]
    )
    return "\n".join(lines)


def _append_recovery_event(data_dir: Path, *, run_id: str, event_type: str, details: Mapping[str, Any]) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": event_type,
        "bd_epic_id": None,
        "phase_id": details.get("phase_id"),
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": details.get("failure_kind"),
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": dict(details),
        "schema_ok": True,
    }
    validate_run_event(row, error_cls=PhaseSessionError)
    append_run_event(data_dir, row)


def _write_recovery_note(
    run_id: str,
    data_dir: Path,
    *,
    kind: str,
    phase_id: str | None,
    details: Mapping[str, Any],
) -> None:
    bd_epic_id = _bd_epic_id_for_run(run_id, data_dir=data_dir)
    if not bd_epic_id:
        return
    result = write_phase_beads_note(
        run_id,
        kind=kind,
        bd_epic_id=bd_epic_id,
        phase_id=phase_id,
        details=details,
        data_dir=data_dir,
    )
    if not result.get("written"):
        _append_recovery_event(
            data_dir,
            run_id=run_id,
            event_type="phase_beads_note_failed",
            details={
                "phase_id": phase_id,
                "kind": kind,
                "reason": result.get("reason"),
                "failure_kind": details.get("failure_kind"),
            },
        )


def _bd_epic_id_for_run(run_id: str, *, data_dir: Path) -> str | None:
    path = data_dir / "runs" / run_id / "prepared_plan.v1.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = payload.get("bd_epic_id") if isinstance(payload, Mapping) else None
    return value if isinstance(value, str) and value else None


def _format_dt(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["reconcile_phase_sessions"]
