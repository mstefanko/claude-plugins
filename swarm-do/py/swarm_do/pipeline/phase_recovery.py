"""Durable reconciliation for phase-session foreground recovery."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT, resolve_data_dir
from .policies import (
    AutopilotPolicyInput,
    evaluate_autopilot_policy,
    retry_policy_config,
)
from .failure_taxonomy import failure_kind_details
from .phase_failure_classifier import FailureClassification, classify_launcher_failure
from .phase_spend import FailedSpendSnapshot, failed_spend_snapshot
from .phase_sessions import (
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
    repair_active_phase_lease,
    validate_phase_artifacts,
)
from .run_state import append_run_event, utc_now, validate_run_event
from .session_capabilities import extract_claude_print_artifacts, parse_claude_print_json
from .worktree_baseline import changed_files_since_baseline
from .phase_beads import write_phase_beads_note


ACTIVE_STATUSES = {STATUS_LEASED, STATUS_RUNNING}
STOP_STATUSES = (STATUS_BLOCKED, STATUS_NEEDS_INPUT, STATUS_RETRY_EXHAUSTED)
MAX_RECONCILIATION_PASSES = 20


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
            handoff_do_not_retry = _handoff_do_not_retry(handoff)
            retryable_failed = terminal_status == "failed" and bool(result.get("retryable"))
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
                    handoff_do_not_retry=handoff_do_not_retry,
                    dry_run=dry_run,
                )
                actions.append(action)
                if not dry_run and action.get("action") in {"retry_scheduled", "retry_ready"}:
                    state = load_phase_sessions(run_id, data_dir=base)
                    continue
                return _decision(run_id, base, str(action.get("status") or STATUS_RETRY_EXHAUSTED), actions)

            action_name = "adopted_completion" if terminal_status == "complete" else f"adopted_{terminal_status}"
            action = {
                "phase_id": phase_id,
                "attempt": attempt,
                "action": action_name,
                "failure_kind": evidence.get("failure_kind"),
                "retry_decision": "adopted",
                "result_path": str(artifact["result_path"]),
                "handoff_path": str(artifact["handoff_path"]),
                **_taxonomy_note_details(evidence),
            }
            if not dry_run:
                adopted = adopt_phase_result(
                    run_id,
                    phase_id,
                    json_file=str(artifact["result_path"]),
                    expected_status=terminal_status,
                    data_dir=base,
                    attempt_record=evidence,
                )
                if isinstance(adopted.get("phase"), Mapping):
                    action["evidence_path"] = adopted["phase"].get("evidence_path")
                _append_recovery_event(base, run_id=run_id, event_type="phase_session_reconciled", details=action)
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
                    details=action,
                )
                state = load_phase_sessions(run_id, data_dir=base)
                if terminal_status == "complete":
                    actions.append(action)
                    continue
            actions.append(action)
            return _decision(run_id, base, terminal_status if terminal_status != "failed" else "failed_nonretryable", actions)

        active_action_details: dict[str, Any] | None = None
        if phase.get("status") in ACTIVE_STATUSES and launcher_result is None:
            active_action = _active_phase_decision(phase, now=current_time)
            if active_action.get("status") == "active":
                repair = _active_lease_repair(
                    phase,
                    state=state,
                    data_dir=base,
                    now=current_time,
                    action=active_action,
                    dry_run=dry_run,
                )
                if repair is not None:
                    active_action["lease_repair"] = repair
                    if not dry_run and repair.get("applied"):
                        state = load_phase_sessions(run_id, data_dir=base)
                actions.append(active_action)
                return _decision(run_id, base, "active", actions)
            active_action_details = dict(active_action)
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
            classify_launcher=launcher_result is not None,
        )
        failure_kind = str(evidence.get("failure_kind") or failure_kind)
        launcher_error = evidence.get("diagnostic_last_error")
        launcher_error_text = launcher_error if isinstance(launcher_error, str) and launcher_error else _launcher_error(launcher_result, artifact)
        action = _retry_or_exhaust(
            run_id,
            phase,
            state=state,
            data_dir=base,
            now=current_time,
            evidence=evidence,
            failure_kind=failure_kind,
            launcher_error=launcher_error_text,
            retry_after_seconds=None,
            dry_run=dry_run,
        )
        if active_action_details is not None:
            action["active_attempt_action"] = active_action_details.get("action")
            action["active_attempt_details"] = active_action_details
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
    handoff_do_not_retry: bool = False,
) -> dict[str, Any]:
    attempt = int(phase.get("attempt") or 0)
    retry_policy = state.get("retry_policy") if isinstance(state.get("retry_policy"), Mapping) else {}
    config = retry_policy_config(retry_policy)
    max_attempts = int(phase.get("max_session_attempts") or config.max_session_attempts)
    phase_id = str(phase["phase_id"])
    same_failure_count = _same_failure_count(phase, failure_kind, include_current=True)
    needs_recovery_retry = _needs_recovery_retry(evidence, state)
    recovery_attempts_used = sum(
        1
        for item in phase.get("attempt_history") or []
        if isinstance(item, Mapping) and item.get("retry_decision") == "recovery_retry"
    )
    spend = _spend_snapshot(run_id, phase_id, attempt, data_dir=data_dir)
    decision = evaluate_autopilot_policy(
        AutopilotPolicyInput(
            failure_kind=failure_kind,
            failure_category=_string_or_none(evidence.get("failure_category")),
            failure_retry_class=_string_or_none(evidence.get("failure_retry_class")),
            attempt=attempt,
            same_failure_count=same_failure_count,
            max_session_attempts=max_attempts,
            recovery_attempts_used=recovery_attempts_used,
            needs_recovery_retry=needs_recovery_retry,
            returncode=evidence.get("returncode") if isinstance(evidence.get("returncode"), int) else None,
            artifact_error_kinds=tuple(str(item) for item in evidence.get("artifact_error_kinds") or [] if isinstance(item, str)),
            partial_artifacts=bool(evidence.get("partial_artifacts")),
            changed_file_count=len([item for item in evidence.get("changed_files") or [] if isinstance(item, str)]),
            elapsed_seconds=float(evidence["elapsed_seconds"]) if isinstance(evidence.get("elapsed_seconds"), (int, float)) else None,
            retry_after_seconds_requested=retry_after_seconds,
            current_attempt_cost_usd=spend.current_attempt_cost_usd,
            cost_confidence=spend.current_attempt_cost_confidence,
            failed_phase_cost_usd=spend.failed_phase_cost_usd,
            failed_run_cost_usd=spend.failed_run_cost_usd,
            unknown_failed_attempt_count=spend.unknown_failed_attempt_count,
            handoff_do_not_retry=handoff_do_not_retry,
        ),
        config,
        operator_title=_string_or_none(evidence.get("failure_operator_title")),
        operator_message=_string_or_none(evidence.get("failure_operator_message")),
    )
    record = dict(evidence)
    record.update(
        {
            "retry_decision": decision.retry_policy_decision,
            "policy_action": decision.action,
            "policy_reason": decision.policy_reason,
            "policy_inputs": decision.inputs,
            "retry_after_seconds": decision.retry_after_seconds,
        }
    )
    policy_details = _policy_action_details(decision)

    if decision.action == "human_gate":
        blocked_reason = decision.blocked_reason or BLOCKED_RETRY_POLICY_HUMAN_GATE
        evidence_path = None
        if not dry_run:
            blocked = mark_phase_blocked(
                run_id,
                phase_id,
                failure_kind=failure_kind,
                blocked_reason=blocked_reason,
                retry_policy_decision=decision.retry_policy_decision,
                data_dir=data_dir,
                launcher_error=launcher_error,
                attempt_record=record,
                details={
                    "same_failure_count": same_failure_count,
                    "max_consecutive_same_failure_kind": config.max_consecutive_same_failure_kind,
                    **policy_details,
                    **_attempt_diagnostic_details(evidence),
                },
            )
            evidence_path = (blocked.get("phase") or {}).get("evidence_path") if isinstance(blocked.get("phase"), Mapping) else None
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_human_gated",
                phase_id=phase_id,
                details={
                    "failure_kind": failure_kind,
                    "retry_policy_decision": decision.retry_policy_decision,
                    "policy_action": decision.action,
                    "policy_reason": decision.policy_reason,
                    "evidence_path": evidence_path,
                    **_taxonomy_note_details(evidence),
                    **_attempt_diagnostic_details(evidence),
                },
            )
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": attempt,
            "action": "blocked",
            "status": STATUS_BLOCKED,
            "failure_kind": failure_kind,
            "blocked_reason": blocked_reason,
            "retry_decision": decision.retry_policy_decision,
            "evidence_path": evidence_path,
            **policy_details,
            **_taxonomy_note_details(evidence),
        }

    if decision.action == "retry_exhausted":
        evidence_path = None
        if not dry_run:
            exhausted = mark_retry_exhausted(
                run_id,
                phase_id,
                failure_kind=failure_kind,
                data_dir=data_dir,
                launcher_error=launcher_error,
                attempt_record=record,
            )
            evidence_path = (exhausted.get("phase") or {}).get("evidence_path") if isinstance(exhausted.get("phase"), Mapping) else None
            _write_recovery_note(
                run_id,
                data_dir,
                kind="phase_attempt_retry_exhausted",
                phase_id=phase_id,
                details={
                    "failure_kind": failure_kind,
                    "recovery_context_path": evidence.get("recovery_context_path"),
                    "policy_action": decision.action,
                    "policy_reason": decision.policy_reason,
                    "evidence_path": evidence_path,
                    **_taxonomy_note_details(evidence),
                },
            )
        return {
            "phase_id": phase.get("phase_id"),
            "attempt": attempt,
            "action": "retry_exhausted",
            "status": STATUS_RETRY_EXHAUSTED,
            "failure_kind": failure_kind,
            "retry_decision": "retry_exhausted",
            "evidence_path": evidence_path,
            **policy_details,
            **_taxonomy_note_details(evidence),
        }

    retry_after_seconds = int(decision.retry_after_seconds or 0)
    next_retry_at = _format_dt(now + timedelta(seconds=retry_after_seconds)) if retry_after_seconds > 0 else None
    evidence_path = None
    if not dry_run:
        retry = abandon_attempt_and_retry(
            run_id,
            phase_id,
            failure_kind=failure_kind,
            data_dir=data_dir,
            launcher_error=launcher_error,
            next_retry_at=next_retry_at,
            retry_after_seconds=retry_after_seconds if retry_after_seconds > 0 else None,
            attempt_record=record,
        )
        evidence_path = (retry.get("phase") or {}).get("evidence_path") if isinstance(retry.get("phase"), Mapping) else None
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
                    "policy_action": decision.action,
                    "policy_reason": decision.policy_reason,
                    "evidence_path": evidence_path,
                    **_taxonomy_note_details(evidence),
                },
            )
    return {
        "phase_id": phase.get("phase_id"),
        "attempt": attempt,
        "action": "retry_scheduled" if next_retry_at else "retry_ready",
        "status": STATUS_RETRY_WAITING if next_retry_at else "ready",
        "failure_kind": failure_kind,
        "retry_decision": decision.retry_policy_decision,
        "next_retry_at": next_retry_at,
        "retry_after_seconds": retry_after_seconds if retry_after_seconds > 0 else None,
        "evidence_path": evidence_path,
        **policy_details,
        **_taxonomy_note_details(evidence),
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
    classify_launcher: bool = False,
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
    command = _command_metadata(launch_dir)
    diff = changed_files_since_baseline(baseline_path, repo_root=_attempt_diff_repo_root(command, repo_root))
    diff_summary_path = recovery_dir / f"attempt-{attempt}.diff-summary.md"
    diff_summary = str(diff.get("diff_summary") or diff.get("warning") or "No baseline-relative diff evidence.")
    diff_summary_path.write_text(diff_summary.rstrip() + "\n", encoding="utf-8")
    recovery_context_path = recovery_dir / f"attempt-{attempt}.recovery.md"
    changed_files = [str(item) for item in diff.get("changed_files") or [] if isinstance(item, str)]
    completed_at = utc_now()
    elapsed = _elapsed_seconds(phase, completed_at)
    classification: FailureClassification | None = None
    if classify_launcher:
        classifier_command = dict(command)
        classifier_command.setdefault("launcher", launcher or _metadata_launcher(command) or _launcher_from_phase(phase))
        classification = classify_launcher_failure(
            launcher_result,
            {"valid": False, "partial": partial_artifacts},
            changed_files=changed_files,
            command_metadata=classifier_command,
        )
        failure_kind = classification.failure_kind
    transcript_diagnostics_path = _write_transcript_diagnostics(
        recovery_dir,
        attempt=attempt,
        classification=classification,
    )
    diagnostic_evidence = _diagnostic_evidence(classification, transcript_diagnostics_path)
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
            diagnostic_evidence=diagnostic_evidence,
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
        "command_metadata": _execution_workspace_evidence(command),
        **_execution_workspace_evidence(command),
        **failure_kind_details(failure_kind),
        **diagnostic_evidence,
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


def _write_transcript_diagnostics(
    recovery_dir: Path,
    *,
    attempt: int,
    classification: FailureClassification | None,
) -> Path | None:
    if classification is None or classification.transcript_diagnostics is None:
        return None
    if not _has_diagnostic_signal(classification):
        return None
    path = recovery_dir / f"attempt-{attempt}.transcript-diagnostics.json"
    path.write_text(json.dumps(classification.transcript_diagnostics.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _diagnostic_evidence(
    classification: FailureClassification | None,
    diagnostics_path: Path | None,
) -> dict[str, Any]:
    if classification is None:
        return {}
    if not _has_diagnostic_signal(classification):
        return {}
    diagnostics = classification.transcript_diagnostics
    evidence: dict[str, Any] = {}
    if diagnostics_path is not None:
        evidence["transcript_diagnostics_path"] = str(diagnostics_path)
    if diagnostics is not None:
        evidence.update(
            {
                "transcript_found": diagnostics.transcript_found,
                "transcript_path": str(diagnostics.transcript_path) if diagnostics.transcript_path else None,
                "tool_errors_count": len(diagnostics.tool_errors),
                "diagnostic_last_error": classification.last_error or diagnostics.last_error_summary,
            }
        )
    elif classification.last_error:
        evidence["diagnostic_last_error"] = classification.last_error
    details = dict(classification.details or {})
    for key in ("tool_name", "tool_error_kind", "message_excerpt", "sensitive_path_excerpt"):
        if details.get(key) is not None:
            evidence[key] = details[key]
    return evidence


def _has_diagnostic_signal(classification: FailureClassification) -> bool:
    diagnostics = classification.transcript_diagnostics
    if classification.failure_kind in {
        "writer_tool_denied_no_artifacts",
        "writer_silent_with_turns",
        "canonical_path_leaked_in_tool_result",
    }:
        return True
    if diagnostics is None:
        return bool(classification.last_error or classification.details)
    return bool(diagnostics.session_id or diagnostics.transcript_found or diagnostics.tool_errors)


def _attempt_diagnostic_details(evidence: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "transcript_diagnostics_path",
        "transcript_found",
        "transcript_path",
        "tool_errors_count",
        "diagnostic_last_error",
        "tool_name",
        "tool_error_kind",
        "message_excerpt",
        "sensitive_path_excerpt",
    )
    return {key: evidence[key] for key in keys if key in evidence}


def _attempt_diff_repo_root(command: Mapping[str, Any], repo_root: Path | None) -> Path | None:
    if command.get("execution_workspace_mode") == "safe-worktree":
        safe_project_root = command.get("safe_project_root")
        if not isinstance(safe_project_root, str) or not safe_project_root:
            raise PhaseSessionError(
                "safe-worktree command metadata is missing safe_project_root; refusing to diff source checkout"
            )
        return Path(safe_project_root)
    return repo_root


def _execution_workspace_evidence(command: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "execution_workspace_mode",
        "source_git_top_level",
        "source_project_root",
        "safe_git_worktree_root",
        "safe_project_root",
        "project_subdir",
        "run_execution_branch",
        "git_base_sha",
        "git_base_ref",
        "run_worktree_manifest_path",
        "copied_ignored_artifacts",
    )
    return {key: command[key] for key in keys if key in command}


def _taxonomy_note_details(evidence: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "failure_category",
        "failure_retry_class",
        "failure_operator_title",
        "failure_operator_message",
        "failure_known",
    )
    return {key: evidence[key] for key in keys if key in evidence}


def _policy_action_details(decision: Any) -> dict[str, Any]:
    return {
        "policy_action": decision.action,
        "policy_reason": decision.policy_reason,
        "policy_inputs": dict(decision.inputs),
    }


def _spend_snapshot(run_id: str, phase_id: str, attempt: int, *, data_dir: Path) -> FailedSpendSnapshot:
    try:
        return failed_spend_snapshot(run_id, phase_id, attempt, data_dir=data_dir)
    except Exception:
        return FailedSpendSnapshot(
            current_attempt_cost_usd=None,
            current_attempt_cost_confidence="unknown",
            failed_phase_cost_usd=0.0,
            failed_run_cost_usd=0.0,
            unknown_failed_attempt_count=1 if attempt > 0 else 0,
        )


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _same_failure_count(phase: Mapping[str, Any], failure_kind: str, *, include_current: bool) -> int:
    count = 1 if include_current else 0
    for item in phase.get("attempt_history") or []:
        if isinstance(item, Mapping) and item.get("failure_kind") == failure_kind:
            count += 1
    return count


def _active_phase_decision(phase: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    expires = parse_phase_datetime(phase.get("lease_expires_at"))
    lease_expired = expires is not None and expires <= now
    current_host = socket.gethostname()
    lease_host = phase.get("lease_host")
    child_pid = phase.get("child_pid")
    has_child_pid = isinstance(child_pid, int) and child_pid > 0
    same_host = lease_host == current_host

    if same_host and has_child_pid:
        alive = _pid_alive(child_pid)
        if alive is False:
            return _active_action(
                phase,
                "child_dead",
                now=now,
                failure_kind="child_process_dead_no_artifacts",
                child_alive=alive,
                process_group_matches=None,
            )
        if alive is True:
            expected_pgid = phase.get("process_group_id")
            group_matches = None
            if isinstance(expected_pgid, int) and expected_pgid > 0:
                group_matches = _process_group_matches(child_pid, expected_pgid)
                if group_matches is False:
                    return _active_action(
                        phase,
                        "child_dead",
                        now=now,
                        failure_kind="child_process_dead_no_artifacts",
                        child_alive=alive,
                        process_group_matches=group_matches,
                    )
                if group_matches is None:
                    return _active_action(
                        phase,
                        "active_preserved_child_unknown",
                        now=now,
                        status="active",
                        child_alive=alive,
                        process_group_matches=group_matches,
                    )
            return _active_action(
                phase,
                "active_preserved_child_alive",
                now=now,
                status="active",
                child_alive=alive,
                process_group_matches=group_matches,
            )
        if lease_expired:
            return _active_action(
                phase,
                "lease_expired",
                now=now,
                failure_kind="lease_expired_no_artifacts",
                child_alive=alive,
                process_group_matches=None,
            )
        return _active_action(
            phase,
            "active_preserved_child_unknown",
            now=now,
            status="active",
            child_alive=alive,
            process_group_matches=None,
        )

    if has_child_pid and not same_host:
        if lease_expired:
            return _active_action(
                phase,
                "lease_expired_cross_host",
                now=now,
                failure_kind="lease_expired_no_artifacts",
                child_alive=None,
                process_group_matches=None,
            )
        return _active_action(
            phase,
            "active_preserved_cross_host",
            now=now,
            status="active",
            child_alive=None,
            process_group_matches=None,
        )

    if lease_expired:
        action = "lease_expired_cross_host" if lease_host and lease_host != current_host else "lease_expired"
        return _active_action(
            phase,
            action,
            now=now,
            failure_kind="lease_expired_no_artifacts",
            child_alive=None,
            process_group_matches=None,
        )
    if lease_host and lease_host != current_host:
        return _active_action(
            phase,
            "active_preserved_cross_host",
            now=now,
            status="active",
            child_alive=None,
            process_group_matches=None,
        )
    return _active_action(
        phase,
        "active_preserved_no_child_metadata",
        now=now,
        status="active",
        child_alive=None,
        process_group_matches=None,
    )


def _active_action(
    phase: Mapping[str, Any],
    action: str,
    *,
    now: datetime,
    status: str | None = None,
    failure_kind: str | None = None,
    child_alive: bool | None,
    process_group_matches: bool | None,
) -> dict[str, Any]:
    expires = parse_phase_datetime(phase.get("lease_expires_at"))
    payload: dict[str, Any] = {
        "phase_id": phase.get("phase_id"),
        "attempt": phase.get("attempt"),
        "action": action,
        "lease_host": phase.get("lease_host"),
        "current_host": socket.gethostname(),
        "lease_expires_at": phase.get("lease_expires_at"),
        "lease_expired": bool(expires is not None and expires <= now),
        "child_pid": phase.get("child_pid"),
        "process_group_id": phase.get("process_group_id"),
        "child_alive": child_alive,
        "process_group_matches": process_group_matches,
    }
    if status is not None:
        payload["status"] = status
    if failure_kind is not None:
        payload["failure_kind"] = failure_kind
    return payload


def _active_lease_repair(
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    data_dir: Path,
    now: datetime,
    action: Mapping[str, Any],
    dry_run: bool,
) -> dict[str, Any] | None:
    if action.get("action") != "active_preserved_child_alive" or not action.get("lease_expired"):
        return None
    lease_policy = state.get("lease_policy") if isinstance(state.get("lease_policy"), Mapping) else {}
    ttl_seconds = int(lease_policy.get("running_ttl_seconds") or 14400)
    old_expires_at = phase.get("lease_expires_at")
    new_expires_at = _format_dt(now + timedelta(seconds=ttl_seconds))
    payload = {
        "applied": False,
        "phase_id": phase.get("phase_id"),
        "attempt": phase.get("attempt"),
        "child_pid": phase.get("child_pid"),
        "process_group_id": phase.get("process_group_id"),
        "old_lease_expires_at": old_expires_at,
        "new_lease_expires_at": new_expires_at,
        "action": "active_preserved_child_alive",
    }
    if dry_run:
        return payload
    repaired = repair_active_phase_lease(
        str(state["run_id"]),
        str(phase["phase_id"]),
        data_dir=data_dir,
        now=now,
        action="active_preserved_child_alive",
    )
    payload.update({key: repaired.get(key) for key in payload if key in repaired})
    payload["applied"] = True
    return payload


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
    diagnostic_evidence: Mapping[str, Any] | None = None,
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
    diagnostics = dict(diagnostic_evidence or {})
    if diagnostics:
        lines.extend(
            [
                "",
                "## Transcript Diagnostics",
                f"- diagnostics_path: {diagnostics.get('transcript_diagnostics_path') or 'not written'}",
                f"- transcript_found: {str(bool(diagnostics.get('transcript_found'))).lower()}",
                f"- transcript_path: {diagnostics.get('transcript_path') or 'unknown'}",
                f"- tool_errors_count: {diagnostics.get('tool_errors_count', 0)}",
                f"- last_error_summary: {diagnostics.get('diagnostic_last_error') or 'none'}",
            ]
        )
        if diagnostics.get("tool_name") or diagnostics.get("tool_error_kind"):
            lines.extend(
                [
                    f"- tool_name: {diagnostics.get('tool_name') or 'unknown'}",
                    f"- tool_error_kind: {diagnostics.get('tool_error_kind') or 'unknown'}",
                ]
            )
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
