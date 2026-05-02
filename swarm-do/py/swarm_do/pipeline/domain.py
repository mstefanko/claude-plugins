"""In-process domain records for runtime control-plane reads.

These records are not persisted and are not a second validation system beside
the JSON artifact contracts. Untyped input enters through ``from_mapping``.
Runtime control-plane records reject unknown keys by default; projector-facing
records may opt into preserving unknown keys in ``extra`` so new read-model
columns do not break older consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .phase_artifact_contract import PHASE_RESULT_STATUSES as PHASE_RESULT_STATUSES
from .phase_sessions import (
    ACTIVE_STATUSES as ACTIVE_STATUSES,
    CLAIMABLE_STATUSES as CLAIMABLE_STATUSES,
    RESULT_TO_PHASE_STATUS as RESULT_TO_PHASE_STATUS,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_LEASED,
    STATUS_NEEDS_INPUT,
    STATUS_PENDING,
    STATUS_RETRY_EXHAUSTED,
    STATUS_RETRY_WAITING,
    STATUS_RUNNING,
    STATUS_STALE,
    TERMINAL_STATUSES as TERMINAL_STATUSES,
)


PHASE_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_LEASED,
        STATUS_RUNNING,
        STATUS_COMPLETE,
        STATUS_FAILED,
        STATUS_BLOCKED,
        STATUS_NEEDS_INPUT,
        STATUS_STALE,
        STATUS_RETRY_WAITING,
        STATUS_RETRY_EXHAUSTED,
    }
)
DOCTOR_REPORT_STATUSES = frozenset({"ok", "findings"})
DOCTOR_FINDING_SEVERITIES = frozenset({"error", "warning", "info"})
WORKTREE_STATUS_SENTINELS = frozenset({"ok", "not_found"})


class DomainContractError(ValueError):
    """Raised when an untyped payload does not match an in-process record."""


@dataclass(frozen=True, slots=True)
class PhaseRecord:
    phase_id: str
    status: str
    attempt: int
    phase_index: int | None = None
    title: str | None = None
    depends_on_phase_ids: tuple[str, ...] = ()
    lease_owner: str | None = None
    lease_host: str | None = None
    lease_pid: int | None = None
    lease_command: str | None = None
    lease_expires_at: str | None = None
    session_name: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result_path: str | None = None
    handoff_path: str | None = None
    last_error: str | None = None
    max_session_attempts: int | None = None
    next_retry_at: str | None = None
    last_failure_kind: str | None = None
    last_launcher_error: str | None = None
    retry_exhausted_at: str | None = None
    blocked_reason: str | None = None
    retry_policy_decision: str | None = None
    blocked_at: str | None = None
    launch_dir: str | None = None
    command_path: str | None = None
    parent_pid: int | None = None
    child_pid: int | None = None
    process_group_id: int | None = None
    prompt_sha: str | None = None
    expected_result_path: str | None = None
    expected_handoff_path: str | None = None
    launch_metadata_error: str | None = None
    recovery_context_path: str | None = None
    evidence_path: str | None = None
    failure_category: str | None = None
    failure_retry_class: str | None = None
    failure_operator_title: str | None = None
    failure_operator_message: str | None = None
    failure_known: bool | None = None
    policy_action: str | None = None
    policy_reason: str | None = None
    policy_inputs: Mapping[str, Any] | None = None
    attempt_history: tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)
    _present_keys: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, preserve_unknown: bool = False) -> "PhaseRecord":
        extra = _extra_or_reject(value, _PHASE_KEYS, "PhaseRecord", preserve_unknown=preserve_unknown)
        phase_id = _required_str(value, "phase_id", "PhaseRecord")
        status = _required_str(value, "status", "PhaseRecord")
        if status not in PHASE_STATUSES:
            raise DomainContractError(f"PhaseRecord.status must be one of {sorted(PHASE_STATUSES)}, got {status!r}")
        record = cls(
            phase_id=phase_id,
            status=status,
            attempt=_int_value(value.get("attempt"), "attempt", default=0),
            phase_index=_optional_int(value.get("phase_index"), "phase_index"),
            title=_optional_str(value.get("title"), "title"),
            depends_on_phase_ids=tuple(_string_list(value.get("depends_on_phase_ids"), "depends_on_phase_ids")),
            lease_owner=_optional_str(value.get("lease_owner"), "lease_owner"),
            lease_host=_optional_str(value.get("lease_host"), "lease_host"),
            lease_pid=_optional_int(value.get("lease_pid"), "lease_pid"),
            lease_command=_optional_str(value.get("lease_command"), "lease_command"),
            lease_expires_at=_optional_str(value.get("lease_expires_at"), "lease_expires_at"),
            session_name=_optional_str(value.get("session_name"), "session_name"),
            started_at=_optional_str(value.get("started_at"), "started_at"),
            completed_at=_optional_str(value.get("completed_at"), "completed_at"),
            result_path=_optional_str(value.get("result_path"), "result_path"),
            handoff_path=_optional_str(value.get("handoff_path"), "handoff_path"),
            last_error=_optional_str(value.get("last_error"), "last_error"),
            max_session_attempts=_optional_int(value.get("max_session_attempts"), "max_session_attempts"),
            next_retry_at=_optional_str(value.get("next_retry_at"), "next_retry_at"),
            last_failure_kind=_optional_str(value.get("last_failure_kind"), "last_failure_kind"),
            last_launcher_error=_optional_str(value.get("last_launcher_error"), "last_launcher_error"),
            retry_exhausted_at=_optional_str(value.get("retry_exhausted_at"), "retry_exhausted_at"),
            blocked_reason=_optional_str(value.get("blocked_reason"), "blocked_reason"),
            retry_policy_decision=_optional_str(value.get("retry_policy_decision"), "retry_policy_decision"),
            blocked_at=_optional_str(value.get("blocked_at"), "blocked_at"),
            launch_dir=_optional_str(value.get("launch_dir"), "launch_dir"),
            command_path=_optional_str(value.get("command_path"), "command_path"),
            parent_pid=_optional_int(value.get("parent_pid"), "parent_pid"),
            child_pid=_optional_int(value.get("child_pid"), "child_pid"),
            process_group_id=_optional_int(value.get("process_group_id"), "process_group_id"),
            prompt_sha=_optional_str(value.get("prompt_sha"), "prompt_sha"),
            expected_result_path=_optional_str(value.get("expected_result_path"), "expected_result_path"),
            expected_handoff_path=_optional_str(value.get("expected_handoff_path"), "expected_handoff_path"),
            launch_metadata_error=_optional_str(value.get("launch_metadata_error"), "launch_metadata_error"),
            recovery_context_path=_optional_str(value.get("recovery_context_path"), "recovery_context_path"),
            evidence_path=_optional_str(value.get("evidence_path"), "evidence_path"),
            failure_category=_optional_str(value.get("failure_category"), "failure_category"),
            failure_retry_class=_optional_str(value.get("failure_retry_class"), "failure_retry_class"),
            failure_operator_title=_optional_str(value.get("failure_operator_title"), "failure_operator_title"),
            failure_operator_message=_optional_str(value.get("failure_operator_message"), "failure_operator_message"),
            failure_known=_optional_bool(value.get("failure_known"), "failure_known"),
            policy_action=_optional_str(value.get("policy_action"), "policy_action"),
            policy_reason=_optional_str(value.get("policy_reason"), "policy_reason"),
            policy_inputs=_optional_mapping(value.get("policy_inputs"), "policy_inputs"),
            attempt_history=tuple(item for item in value.get("attempt_history") or [] if isinstance(item, Mapping)),
            extra=extra,
            _present_keys=tuple(value.keys()),
        )
        return record.validate()

    def validate(self) -> "PhaseRecord":
        if self.status not in PHASE_STATUSES:
            raise DomainContractError(f"PhaseRecord.status must be one of {sorted(PHASE_STATUSES)}, got {self.status!r}")
        if not self.phase_id:
            raise DomainContractError("PhaseRecord missing required field 'phase_id'")
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = _present_dict(
            self._present_keys,
            {
                "phase_id": self.phase_id,
                "phase_index": self.phase_index,
                "title": self.title,
                "depends_on_phase_ids": list(self.depends_on_phase_ids),
                "status": self.status,
                "lease_owner": self.lease_owner,
                "lease_host": self.lease_host,
                "lease_pid": self.lease_pid,
                "lease_command": self.lease_command,
                "lease_expires_at": self.lease_expires_at,
                "attempt": self.attempt,
                "session_name": self.session_name,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "result_path": self.result_path,
                "handoff_path": self.handoff_path,
                "last_error": self.last_error,
                "max_session_attempts": self.max_session_attempts,
                "next_retry_at": self.next_retry_at,
                "last_failure_kind": self.last_failure_kind,
                "last_launcher_error": self.last_launcher_error,
                "retry_exhausted_at": self.retry_exhausted_at,
                "blocked_reason": self.blocked_reason,
                "retry_policy_decision": self.retry_policy_decision,
                "blocked_at": self.blocked_at,
                "launch_dir": self.launch_dir,
                "command_path": self.command_path,
                "parent_pid": self.parent_pid,
                "child_pid": self.child_pid,
                "process_group_id": self.process_group_id,
                "prompt_sha": self.prompt_sha,
                "expected_result_path": self.expected_result_path,
                "expected_handoff_path": self.expected_handoff_path,
                "launch_metadata_error": self.launch_metadata_error,
                "recovery_context_path": self.recovery_context_path,
                "evidence_path": self.evidence_path,
                "failure_category": self.failure_category,
                "failure_retry_class": self.failure_retry_class,
                "failure_operator_title": self.failure_operator_title,
                "failure_operator_message": self.failure_operator_message,
                "failure_known": self.failure_known,
                "policy_action": self.policy_action,
                "policy_reason": self.policy_reason,
                "policy_inputs": dict(self.policy_inputs) if self.policy_inputs is not None else None,
                "attempt_history": [dict(item) for item in self.attempt_history],
            },
        )
        payload.update(dict(self.extra))
        return payload


@dataclass(frozen=True, slots=True)
class PhaseAttemptRecord:
    run_id: str | None
    phase_id: str
    phase_title: str | None
    attempt: int
    status: str
    failure_kind: str | None = None
    retry_decision: str | None = None
    policy_action: str | None = None
    policy_reason: str | None = None
    policy_inputs: Mapping[str, Any] | None = None
    adopted: bool | None = None
    started_at: str | None = None
    completed_at: str | None = None
    elapsed_seconds: float | None = None
    launcher_returncode: int | None = None
    session_name: str | None = None
    child_pid: int | None = None
    process_group_id: int | None = None
    launch_dir: str | None = None
    evidence_path: str | None = None
    result_path: str | None = None
    handoff_path: str | None = None
    recovery_context_path: str | None = None
    stdout_tail_path: str | None = None
    stderr_tail_path: str | None = None
    changed_files: tuple[str, ...] = ()
    cleanup: Mapping[str, Any] | None = None
    child_process: Mapping[str, Any] | None = None
    archived: bool = False
    archive: str | None = None
    failure_category: str | None = None
    failure_retry_class: str | None = None
    failure_operator_title: str | None = None
    failure_operator_message: str | None = None
    failure_known: bool | None = None
    total_cost_usd: float | None = None
    cost_confidence: str | None = None
    input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    num_turns: int | None = None
    permission_denial_count: int | None = None
    diff_summary_path: str | None = None
    transcript_diagnostics_path: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    _present_keys: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, preserve_unknown: bool = False) -> "PhaseAttemptRecord":
        extra = _extra_or_reject(value, _ATTEMPT_KEYS, "PhaseAttemptRecord", preserve_unknown=preserve_unknown)
        phase_id = _required_str(value, "phase_id", "PhaseAttemptRecord")
        record = cls(
            run_id=_optional_str(value.get("run_id"), "run_id"),
            phase_id=phase_id,
            phase_title=_optional_str(value.get("phase_title"), "phase_title"),
            attempt=_int_value(value.get("attempt"), "attempt", default=0),
            status=_required_str(value, "status", "PhaseAttemptRecord"),
            failure_kind=_optional_str(value.get("failure_kind"), "failure_kind"),
            retry_decision=_optional_str(value.get("retry_decision"), "retry_decision"),
            policy_action=_optional_str(value.get("policy_action"), "policy_action"),
            policy_reason=_optional_str(value.get("policy_reason"), "policy_reason"),
            policy_inputs=_optional_mapping(value.get("policy_inputs"), "policy_inputs"),
            adopted=value.get("adopted") if isinstance(value.get("adopted"), bool) else None,
            started_at=_optional_str(value.get("started_at"), "started_at"),
            completed_at=_optional_str(value.get("completed_at"), "completed_at"),
            elapsed_seconds=_optional_float(value.get("elapsed_seconds"), "elapsed_seconds"),
            launcher_returncode=_optional_int(value.get("launcher_returncode"), "launcher_returncode"),
            session_name=_optional_str(value.get("session_name"), "session_name"),
            child_pid=_optional_int(value.get("child_pid"), "child_pid"),
            process_group_id=_optional_int(value.get("process_group_id"), "process_group_id"),
            launch_dir=_optional_str(value.get("launch_dir"), "launch_dir"),
            evidence_path=_optional_str(value.get("evidence_path"), "evidence_path"),
            result_path=_optional_str(value.get("result_path"), "result_path"),
            handoff_path=_optional_str(value.get("handoff_path"), "handoff_path"),
            recovery_context_path=_optional_str(value.get("recovery_context_path"), "recovery_context_path"),
            stdout_tail_path=_optional_str(value.get("stdout_tail_path"), "stdout_tail_path"),
            stderr_tail_path=_optional_str(value.get("stderr_tail_path"), "stderr_tail_path"),
            changed_files=tuple(_string_list(value.get("changed_files"), "changed_files")),
            cleanup=_optional_mapping(value.get("cleanup"), "cleanup"),
            child_process=_optional_mapping(value.get("child_process"), "child_process"),
            archived=bool(value.get("archived")),
            archive=_optional_str(value.get("archive"), "archive"),
            failure_category=_optional_str(value.get("failure_category"), "failure_category"),
            failure_retry_class=_optional_str(value.get("failure_retry_class"), "failure_retry_class"),
            failure_operator_title=_optional_str(value.get("failure_operator_title"), "failure_operator_title"),
            failure_operator_message=_optional_str(value.get("failure_operator_message"), "failure_operator_message"),
            failure_known=_optional_bool(value.get("failure_known"), "failure_known"),
            total_cost_usd=_optional_float(value.get("total_cost_usd"), "total_cost_usd"),
            cost_confidence=_optional_str(value.get("cost_confidence"), "cost_confidence"),
            input_tokens=_optional_int(value.get("input_tokens"), "input_tokens"),
            cache_creation_input_tokens=_optional_int(value.get("cache_creation_input_tokens"), "cache_creation_input_tokens"),
            cache_read_input_tokens=_optional_int(value.get("cache_read_input_tokens"), "cache_read_input_tokens"),
            output_tokens=_optional_int(value.get("output_tokens"), "output_tokens"),
            duration_ms=_optional_int(value.get("duration_ms"), "duration_ms"),
            duration_api_ms=_optional_int(value.get("duration_api_ms"), "duration_api_ms"),
            num_turns=_optional_int(value.get("num_turns"), "num_turns"),
            permission_denial_count=_optional_int(value.get("permission_denial_count"), "permission_denial_count"),
            diff_summary_path=_optional_str(value.get("diff_summary_path"), "diff_summary_path"),
            transcript_diagnostics_path=_optional_str(value.get("transcript_diagnostics_path"), "transcript_diagnostics_path"),
            extra=extra,
            _present_keys=tuple(value.keys()),
        )
        return record.validate()

    def validate(self) -> "PhaseAttemptRecord":
        if not self.phase_id:
            raise DomainContractError("PhaseAttemptRecord missing required field 'phase_id'")
        if not self.status:
            raise DomainContractError("PhaseAttemptRecord missing required field 'status'")
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = _present_dict(
            self._present_keys,
            {
                "run_id": self.run_id,
                "phase_id": self.phase_id,
                "phase_title": self.phase_title,
                "attempt": self.attempt,
                "status": self.status,
                "failure_kind": self.failure_kind,
                "retry_decision": self.retry_decision,
                "policy_action": self.policy_action,
                "policy_reason": self.policy_reason,
                "policy_inputs": dict(self.policy_inputs) if self.policy_inputs is not None else None,
                "adopted": self.adopted,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "elapsed_seconds": self.elapsed_seconds,
                "launcher_returncode": self.launcher_returncode,
                "session_name": self.session_name,
                "child_pid": self.child_pid,
                "process_group_id": self.process_group_id,
                "launch_dir": self.launch_dir,
                "evidence_path": self.evidence_path,
                "result_path": self.result_path,
                "handoff_path": self.handoff_path,
                "recovery_context_path": self.recovery_context_path,
                "stdout_tail_path": self.stdout_tail_path,
                "stderr_tail_path": self.stderr_tail_path,
                "changed_files": list(self.changed_files),
                "cleanup": dict(self.cleanup) if self.cleanup is not None else None,
                "child_process": dict(self.child_process) if self.child_process is not None else None,
                "archived": self.archived,
                "archive": self.archive,
                "failure_category": self.failure_category,
                "failure_retry_class": self.failure_retry_class,
                "failure_operator_title": self.failure_operator_title,
                "failure_operator_message": self.failure_operator_message,
                "failure_known": self.failure_known,
                "total_cost_usd": self.total_cost_usd,
                "cost_confidence": self.cost_confidence,
                "input_tokens": self.input_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
                "cache_read_input_tokens": self.cache_read_input_tokens,
                "output_tokens": self.output_tokens,
                "duration_ms": self.duration_ms,
                "duration_api_ms": self.duration_api_ms,
                "num_turns": self.num_turns,
                "permission_denial_count": self.permission_denial_count,
                "diff_summary_path": self.diff_summary_path,
                "transcript_diagnostics_path": self.transcript_diagnostics_path,
            },
        )
        payload.update(dict(self.extra))
        return payload

    def to_row(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    id: str
    severity: str
    detail: str | None = None
    recommended_command: str | None = None
    phase_id: str | None = None
    status: str | None = None
    probe: str | None = None
    stale_reasons: tuple[str, ...] = ()
    worktree: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    _present_keys: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DoctorFinding":
        extra = _extra_or_reject(value, _DOCTOR_KEYS, "DoctorFinding", preserve_unknown=False)
        finding_id = _required_str(value, "id", "DoctorFinding")
        severity = _optional_str(value.get("severity"), "severity") or "info"
        if severity not in DOCTOR_FINDING_SEVERITIES:
            raise DomainContractError(
                f"DoctorFinding.severity must be one of {sorted(DOCTOR_FINDING_SEVERITIES)}, got {severity!r}"
            )
        record = cls(
            id=finding_id,
            severity=severity,
            detail=_optional_str(value.get("detail"), "detail"),
            recommended_command=_optional_str(value.get("recommended_command"), "recommended_command"),
            phase_id=_optional_str(value.get("phase_id"), "phase_id"),
            status=_optional_str(value.get("status"), "status"),
            probe=_optional_str(value.get("probe"), "probe"),
            stale_reasons=tuple(_string_list(value.get("stale_reasons"), "stale_reasons")),
            worktree=_optional_mapping(value.get("worktree"), "worktree"),
            extra=extra,
            _present_keys=tuple(value.keys()),
        )
        return record.validate()

    def validate(self) -> "DoctorFinding":
        if not self.id:
            raise DomainContractError("DoctorFinding missing required field 'id'")
        if self.severity not in DOCTOR_FINDING_SEVERITIES:
            raise DomainContractError(
                f"DoctorFinding.severity must be one of {sorted(DOCTOR_FINDING_SEVERITIES)}, got {self.severity!r}"
            )
        return self

    def rank_key(self) -> tuple[int, str]:
        return {"error": 0, "warning": 1, "info": 2}.get(self.severity, 3), self.id

    def to_dict(self) -> dict[str, Any]:
        payload = _present_dict(
            self._present_keys,
            {
                "id": self.id,
                "severity": self.severity,
                "detail": self.detail,
                "recommended_command": self.recommended_command,
                "phase_id": self.phase_id,
                "status": self.status,
                "probe": self.probe,
                "stale_reasons": list(self.stale_reasons),
                "worktree": dict(self.worktree) if self.worktree is not None else None,
            },
        )
        payload.update(dict(self.extra))
        return payload


@dataclass(frozen=True, slots=True)
class PhaseStatusReport:
    run_id: str
    status: str
    phases: tuple[PhaseRecord, ...]
    state_path: str | None = None
    prepared_artifact_path: str | None = None
    prepared_plan_sha: str | None = None
    updated_at: str | None = None
    retry_policy: Mapping[str, Any] | None = None
    dependency_status: tuple[Mapping[str, Any], ...] = ()
    drift: tuple[str, ...] = ()
    recommended_command: str | None = None
    active_phase: PhaseRecord | None = None
    next_phase: PhaseRecord | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    _present_keys: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PhaseStatusReport":
        extra = _extra_or_reject(value, _PHASE_STATUS_REPORT_KEYS, "PhaseStatusReport", preserve_unknown=True)
        run_id = _required_str(value, "run_id", "PhaseStatusReport")
        status = _required_str(value, "status", "PhaseStatusReport")
        phases = tuple(
            PhaseRecord.from_mapping(item, preserve_unknown=True)
            for item in value.get("phases") or []
            if isinstance(item, Mapping)
        )
        active_raw = value.get("active_phase")
        next_raw = value.get("next_phase")
        report = cls(
            run_id=run_id,
            status=status,
            phases=phases,
            state_path=_optional_str(value.get("state_path"), "state_path"),
            prepared_artifact_path=_optional_str(value.get("prepared_artifact_path"), "prepared_artifact_path"),
            prepared_plan_sha=_optional_str(value.get("prepared_plan_sha"), "prepared_plan_sha"),
            updated_at=_optional_str(value.get("updated_at"), "updated_at"),
            retry_policy=_optional_mapping(value.get("retry_policy"), "retry_policy"),
            dependency_status=tuple(
                dict(item)
                for item in value.get("dependency_status") or []
                if isinstance(item, Mapping)
            ),
            drift=tuple(_string_list(value.get("drift"), "drift")),
            recommended_command=_optional_str(value.get("recommended_command"), "recommended_command"),
            active_phase=PhaseRecord.from_mapping(active_raw, preserve_unknown=True) if isinstance(active_raw, Mapping) else None,
            next_phase=PhaseRecord.from_mapping(next_raw, preserve_unknown=True) if isinstance(next_raw, Mapping) else None,
            extra=extra,
            _present_keys=tuple(value.keys()),
        )
        return report.validate()

    def validate(self) -> "PhaseStatusReport":
        if not self.run_id:
            raise DomainContractError("PhaseStatusReport missing required field 'run_id'")
        if not self.status:
            raise DomainContractError("PhaseStatusReport missing required field 'status'")
        for phase in self.phases:
            phase.validate()
        if self.active_phase is not None:
            self.active_phase.validate()
        if self.next_phase is not None:
            self.next_phase.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = _present_dict(
            self._present_keys,
            {
                "run_id": self.run_id,
                "status": self.status,
                "state_path": self.state_path,
                "prepared_artifact_path": self.prepared_artifact_path,
                "prepared_plan_sha": self.prepared_plan_sha,
                "updated_at": self.updated_at,
                "retry_policy": dict(self.retry_policy) if self.retry_policy is not None else None,
                "dependency_status": [dict(item) for item in self.dependency_status],
                "drift": list(self.drift),
                "phases": [phase.to_dict() for phase in self.phases],
                "recommended_command": self.recommended_command,
                "active_phase": self.active_phase.to_dict() if self.active_phase is not None else None,
                "next_phase": self.next_phase.to_dict() if self.next_phase is not None else None,
            },
        )
        payload.update(dict(self.extra))
        return payload


_PHASE_KEYS = {
    "phase_id",
    "phase_index",
    "title",
    "depends_on_phase_ids",
    "status",
    "lease_owner",
    "lease_host",
    "lease_pid",
    "lease_command",
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
    "failure_category",
    "failure_retry_class",
    "failure_operator_title",
    "failure_operator_message",
    "failure_known",
    "policy_action",
    "policy_reason",
    "policy_inputs",
}

_ATTEMPT_KEYS = {
    "run_id",
    "phase_id",
    "phase_title",
    "attempt",
    "status",
    "failure_kind",
    "retry_decision",
    "policy_action",
    "policy_reason",
    "policy_inputs",
    "adopted",
    "started_at",
    "completed_at",
    "elapsed_seconds",
    "launcher_returncode",
    "session_name",
    "child_pid",
    "process_group_id",
    "launch_dir",
    "evidence_path",
    "result_path",
    "handoff_path",
    "recovery_context_path",
    "stdout_tail_path",
    "stderr_tail_path",
    "changed_files",
    "cleanup",
    "child_process",
    "archived",
    "archive",
    "failure_category",
    "failure_retry_class",
    "failure_operator_title",
    "failure_operator_message",
    "failure_known",
    "total_cost_usd",
    "cost_confidence",
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "duration_ms",
    "duration_api_ms",
    "num_turns",
    "permission_denial_count",
    "diff_summary_path",
    "transcript_diagnostics_path",
}

_DOCTOR_KEYS = {
    "id",
    "severity",
    "detail",
    "recommended_command",
    "phase_id",
    "status",
    "probe",
    "stale_reasons",
    "worktree",
}

_PHASE_STATUS_REPORT_KEYS = {
    "run_id",
    "status",
    "state_path",
    "prepared_artifact_path",
    "prepared_plan_sha",
    "updated_at",
    "retry_policy",
    "next_phase",
    "active_phase",
    "phases",
    "dependency_status",
    "recommended_command",
    "drift",
}


def _extra_or_reject(
    value: Mapping[str, Any],
    allowed: set[str],
    label: str,
    *,
    preserve_unknown: bool,
) -> Mapping[str, Any]:
    unknown = {key: item for key, item in value.items() if key not in allowed}
    if unknown and not preserve_unknown:
        raise DomainContractError(f"{label} got unknown field(s): {', '.join(sorted(unknown))}")
    return unknown


def _required_str(value: Mapping[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or item == "":
        raise DomainContractError(f"{label} missing required field {key!r}")
    return item


def _optional_str(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainContractError(f"{key} must be a string or null")
    return value


def _optional_int(value: Any, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainContractError(f"{key} must be an integer or null")
    return value


def _optional_float(value: Any, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainContractError(f"{key} must be a number or null")
    return float(value)


def _optional_bool(value: Any, key: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise DomainContractError(f"{key} must be a boolean or null")
    return value


def _optional_mapping(value: Any, key: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DomainContractError(f"{key} must be an object or null")
    return dict(value)


def _int_value(value: Any, key: str, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainContractError(f"{key} must be an integer")
    return value


def _string_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DomainContractError(f"{key} must be an array")
    if not all(isinstance(item, str) for item in value):
        raise DomainContractError(f"{key} must contain only strings")
    return list(value)


def _present_dict(keys: tuple[str, ...], values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in keys if key in values}


__all__ = [
    "ACTIVE_STATUSES",
    "CLAIMABLE_STATUSES",
    "DOCTOR_FINDING_SEVERITIES",
    "DOCTOR_REPORT_STATUSES",
    "DomainContractError",
    "DoctorFinding",
    "PHASE_RESULT_STATUSES",
    "PHASE_STATUSES",
    "PhaseAttemptRecord",
    "PhaseRecord",
    "PhaseStatusReport",
    "RESULT_TO_PHASE_STATUS",
    "TERMINAL_STATUSES",
    "WORKTREE_STATUS_SENTINELS",
]
