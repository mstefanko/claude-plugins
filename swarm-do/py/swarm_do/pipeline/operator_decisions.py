"""Human-recorded recovery choices for operator decision artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .failure_taxonomy import failure_kind_details
from .paths import resolve_data_dir
from .phase_session_store import (
    PhaseSessionLockTimeout,
    abandon_attempt_and_retry,
    load_phase_sessions,
    locked_phase_sessions,
    phase_session_path,
)
from .run_state import _atomic_json_write, append_run_event, utc_now, validate_run_event


assert "shared_decisions" not in __doc__.lower(), (
    "operator_decisions module must not be confused with shared_decisions"
)


SCHEMA_VERSION = 1
OPERATOR_DECISIONS_FILENAME = "operator_decisions.v1.json"

STATUS_RECORDED = "recorded"
STATUS_APPLIED = "applied"
STATUS_SUPERSEDED = "superseded"
STATUS_REVOKED = "revoked"
STATUS_ERROR = "error"
STATUSES = {
    STATUS_RECORDED,
    STATUS_APPLIED,
    STATUS_SUPERSEDED,
    STATUS_REVOKED,
    STATUS_ERROR,
}

KINDS = {
    "resume_with_input",
    "retry_phase",
    "skip_best_effort_stage",
    "reset_phase",
    "rebuild_worktree",
    "archive_attempt",
    "cancel_run",
    "abort_phase",
    "accept_provider_partial",
}
INTEGRATED_KINDS = {"retry_phase"}
DESTRUCTIVE_REAPPLY_KINDS = {"retry_phase", "reset_phase", "rebuild_worktree", "archive_attempt"}
CONFIRM_REQUIRED_KINDS = {"archive_attempt", "cancel_run", "rebuild_worktree"}
LOCK_TIMEOUT_SECONDS = 5.0
MAX_DECISION_RECORDS_BEFORE_WARNING = 1000


class OperatorDecisionError(ValueError):
    """Controlled operator decision failure with a CLI-friendly payload."""

    def __init__(self, error: str, message: str, *, exit_code: int = 2, **details: Any) -> None:
        super().__init__(message)
        self.error = error
        self.exit_code = exit_code
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload = {"error": self.error, "message": str(self)}
        payload.update(self.details)
        return payload


@dataclass(frozen=True)
class OperatorDecision:
    schema_version: int
    decision_id: str
    run_id: str
    kind: str
    created_at: str
    operator: str
    payload: dict[str, Any]
    status: str = STATUS_RECORDED
    applied_at: str | None = None
    applied_event_path: str | None = None
    supersedes: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OperatorDecision":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise OperatorDecisionError(
                "schema-mismatch",
                "operator decision schema_version must be 1",
            )
        decision_id = _required_string(value, "decision_id")
        run_id = _required_string(value, "run_id")
        kind = _required_string(value, "kind")
        if kind not in KINDS:
            raise OperatorDecisionError("unknown-kind", f"unknown operator decision kind: {kind}")
        created_at = _required_string(value, "created_at")
        operator = _validate_operator(_required_string(value, "operator"))
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise OperatorDecisionError("invalid-payload", "operator decision payload must be an object")
        status = _required_string(value, "status")
        if status not in STATUSES:
            raise OperatorDecisionError("invalid-status", f"unknown operator decision status: {status}")
        applied_at = _optional_string(value.get("applied_at"), "applied_at")
        applied_event_path = _optional_string(value.get("applied_event_path"), "applied_event_path")
        supersedes = _optional_string(value.get("supersedes"), "supersedes")
        return cls(
            schema_version=SCHEMA_VERSION,
            decision_id=decision_id,
            run_id=run_id,
            kind=kind,
            created_at=created_at,
            operator=operator,
            payload=validate_payload(kind, payload),
            status=status,
            applied_at=applied_at,
            applied_event_path=applied_event_path,
            supersedes=supersedes,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "operator": self.operator,
            "payload": dict(self.payload),
            "status": self.status,
            "applied_at": self.applied_at,
            "applied_event_path": self.applied_event_path,
            "supersedes": self.supersedes,
        }


class OperatorDecisionStore:
    """Per-run JSON store for append-only operator decision records."""

    def __init__(self, *, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or resolve_data_dir()

    def path(self, run_id: str) -> Path:
        return operator_decisions_path(run_id, data_dir=self.data_dir)

    def load(self, run_id: str) -> dict[str, Any] | None:
        path = self.path(run_id)
        if not path.is_file():
            return None
        payload = _read_json_object(path)
        _validate_artifact(payload, run_id)
        return _with_current_decisions(payload)

    def record(
        self,
        run_id: str,
        kind: str,
        payload: Mapping[str, Any],
        *,
        operator: str | None = None,
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise OperatorDecisionError("unknown-kind", f"unknown operator decision kind: {kind}")
        normalized_payload = validate_payload(kind, payload)
        operator_id = _validate_operator(operator or default_operator())
        created_at = utc_now()
        path = self.path(run_id)
        _assert_run_dir_exists(run_id, self.data_dir)
        try:
            with locked_phase_sessions(run_id, data_dir=self.data_dir, timeout_seconds=LOCK_TIMEOUT_SECONDS):
                state = _assert_run_state(run_id, self.data_dir)
                _assert_payload_targets_state(kind, normalized_payload, state)
                artifact = _load_or_empty(path, run_id)
                existing = _find_duplicate_record(artifact, run_id, kind, normalized_payload, created_at)
                if existing is not None:
                    decision = _current_decision(existing, artifact.get("events") or [])
                    return _record_result(path, decision)

                decisions = artifact["decisions"]
                decision_id = _decision_id(
                    run_id,
                    kind,
                    normalized_payload,
                    created_at=created_at,
                    sequence=len(decisions) + 1,
                )
                decision = OperatorDecision(
                    schema_version=SCHEMA_VERSION,
                    decision_id=decision_id,
                    run_id=run_id,
                    kind=kind,
                    created_at=created_at,
                    operator=operator_id,
                    payload=normalized_payload,
                ).to_record()
                decisions.append(decision)
                _validate_artifact(artifact, run_id)
                _write_artifact(path, artifact)
        except PhaseSessionLockTimeout as exc:
            raise OperatorDecisionError("run-locked", "operator decision run is locked", exit_code=75, run_id=run_id) from exc

        _append_operator_run_event(
            self.data_dir,
            run_id=run_id,
            event_type="operator_decision_recorded",
            decision=decision,
            status=STATUS_RECORDED,
            artifact_path=path,
        )
        if len(decisions) > MAX_DECISION_RECORDS_BEFORE_WARNING:
            _append_retention_warning(self.data_dir, run_id=run_id, decision_count=len(decisions), artifact_path=path)
        return _record_result(path, decision)

    def apply(self, run_id: str, decision_id: str, *, confirm_token: str | None = None) -> dict[str, Any]:
        path = self.path(run_id)
        _assert_run_dir_exists(run_id, self.data_dir)
        try:
            with locked_phase_sessions(run_id, data_dir=self.data_dir, timeout_seconds=LOCK_TIMEOUT_SECONDS):
                _assert_run_state(run_id, self.data_dir)
                artifact = _load_existing(path, run_id)
                decision = _find_decision(artifact, decision_id)
                current = _current_decision(decision, artifact.get("events") or [])
                if current["status"] == STATUS_APPLIED:
                    if current["kind"] in DESTRUCTIVE_REAPPLY_KINDS:
                        raise OperatorDecisionError(
                            "decision-already-applied",
                            "operator decision was already applied",
                            decision_id=decision_id,
                        )
                    event = _status_event(
                        decision=current,
                        event_type="apply_noop",
                        status=STATUS_APPLIED,
                        applied_at=current.get("applied_at"),
                        applied_event_path=current.get("applied_event_path"),
                    )
                    artifact["events"].append(event)
                    _validate_artifact(artifact, run_id)
                    _write_artifact(path, artifact)
                    _append_operator_run_event(
                        self.data_dir,
                        run_id=run_id,
                        event_type="operator_decision_apply_noop",
                        decision=current,
                        status=STATUS_APPLIED,
                        artifact_path=path,
                    )
                    return {
                        "path": str(path),
                        "decision": _current_decision(decision, artifact.get("events") or []),
                        "applied": False,
                        "noop": True,
                    }

                if current["status"] != STATUS_RECORDED:
                    raise OperatorDecisionError(
                        "decision-not-recorded",
                        "operator decision must be recorded before apply",
                        decision_id=decision_id,
                        status=current["status"],
                    )
                expected_confirm = confirm_token_for_decision(current)
                if _confirm_required(current) and confirm_token != expected_confirm:
                    raise OperatorDecisionError(
                        "confirm-required",
                        "operator decision apply requires --confirm with the first 8 chars of the decision id",
                        decision_id=decision_id,
                        confirm_token=expected_confirm,
                    )
                if current["kind"] not in INTEGRATED_KINDS:
                    raise OperatorDecisionError(
                        "kind-not-integrated",
                        "operator decision kind is recorded but not integrated with apply yet",
                        decision_id=decision_id,
                        kind=current["kind"],
                    )

                apply_result = _apply_integrated_decision(run_id, current, data_dir=self.data_dir)
                applied_at = utc_now()
                applied_event_path = str(self.data_dir / "telemetry" / "run_events.jsonl")
                artifact["events"].append(
                    _status_event(
                        decision=current,
                        event_type="applied",
                        status=STATUS_APPLIED,
                        applied_at=applied_at,
                        applied_event_path=applied_event_path,
                        result=apply_result,
                    )
                )
                _validate_artifact(artifact, run_id)
                _write_artifact(path, artifact)
        except PhaseSessionLockTimeout as exc:
            raise OperatorDecisionError("run-locked", "operator decision run is locked", exit_code=75, run_id=run_id) from exc

        updated = _current_decision(decision, artifact.get("events") or [])
        _append_operator_run_event(
            self.data_dir,
            run_id=run_id,
            event_type="operator_decision_applied",
            decision=updated,
            status=STATUS_APPLIED,
            artifact_path=path,
            result=apply_result,
        )
        return {"path": str(path), "decision": updated, "applied": True, "result": apply_result}

    def list(
        self,
        run_id: str,
        *,
        status: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        artifact = self.load(run_id)
        if artifact is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "path": str(self.path(run_id)),
                "decisions": [],
            }
        decisions = [
            item
            for item in artifact["decisions"]
            if (status is None or item.get("status") == status) and (kind is None or item.get("kind") == kind)
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "path": str(self.path(run_id)),
            "decisions": decisions,
        }

    def show(self, run_id: str, decision_id: str) -> dict[str, Any]:
        artifact = self.load(run_id)
        if artifact is None:
            raise OperatorDecisionError("decision-not-found", "operator decision not found", decision_id=decision_id)
        for decision in artifact["decisions"]:
            if decision.get("decision_id") == decision_id:
                return {"path": str(self.path(run_id)), "decision": decision}
        raise OperatorDecisionError("decision-not-found", "operator decision not found", decision_id=decision_id)


def operator_decisions_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "runs" / run_id / OPERATOR_DECISIONS_FILENAME


def default_operator() -> str:
    identity = os.environ.get("USER") or socket.gethostname()
    if "@" in identity:
        identity = identity.split("@", 1)[0]
    identity = re.sub(r"[^A-Za-z0-9._-]+", "-", identity).strip("-._") or socket.gethostname()
    return f"local:{identity}"


def record(
    run_id: str,
    kind: str,
    payload: Mapping[str, Any],
    *,
    operator: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return OperatorDecisionStore(data_dir=data_dir).record(run_id, kind, payload, operator=operator)


def apply(
    run_id: str,
    decision_id: str,
    *,
    data_dir: Path | None = None,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    return OperatorDecisionStore(data_dir=data_dir).apply(run_id, decision_id, confirm_token=confirm_token)


def list_decisions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    status: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    return OperatorDecisionStore(data_dir=data_dir).list(run_id, status=status, kind=kind)


def show_decision(run_id: str, decision_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    return OperatorDecisionStore(data_dir=data_dir).show(run_id, decision_id)


def validate_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    validators = {
        "resume_with_input": _validate_resume_with_input_payload,
        "retry_phase": _validate_phase_reason_payload,
        "skip_best_effort_stage": _validate_skip_best_effort_stage_payload,
        "reset_phase": _validate_phase_reason_payload,
        "abort_phase": _validate_phase_reason_payload,
        "rebuild_worktree": _validate_rebuild_worktree_payload,
        "archive_attempt": _validate_archive_attempt_payload,
        "cancel_run": _validate_cancel_run_payload,
        "accept_provider_partial": _validate_accept_provider_partial_payload,
    }
    if kind not in validators:
        raise OperatorDecisionError("unknown-kind", f"unknown operator decision kind: {kind}")
    return validators[kind](payload)


def confirm_token_for_decision(decision: Mapping[str, Any]) -> str:
    return str(decision.get("decision_id") or "")[:8]


def _validate_resume_with_input_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "input"})
    operator_input = payload.get("input")
    if not isinstance(operator_input, Mapping):
        raise OperatorDecisionError("invalid-payload", "resume_with_input input must be an object")
    return {"phase_id": _payload_string(payload, "phase_id"), "input": dict(operator_input)}


def _validate_phase_reason_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "reason"})
    return {"phase_id": _payload_string(payload, "phase_id"), "reason": _payload_string(payload, "reason")}


def _validate_skip_best_effort_stage_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "stage_id", "reason"})
    return {
        "phase_id": _payload_string(payload, "phase_id"),
        "stage_id": _payload_string(payload, "stage_id"),
        "reason": _payload_string(payload, "reason"),
    }


def _validate_rebuild_worktree_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "reason", "archive_branch"})
    archive_branch = payload.get("archive_branch")
    if not isinstance(archive_branch, bool):
        raise OperatorDecisionError("invalid-payload", "rebuild_worktree archive_branch must be boolean")
    return {
        "phase_id": _payload_string(payload, "phase_id"),
        "reason": _payload_string(payload, "reason"),
        "archive_branch": archive_branch,
    }


def _validate_archive_attempt_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "attempt", "reason"})
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise OperatorDecisionError("invalid-payload", "archive_attempt attempt must be a positive integer")
    return {
        "phase_id": _payload_string(payload, "phase_id"),
        "attempt": attempt,
        "reason": _payload_string(payload, "reason"),
    }


def _validate_cancel_run_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"reason", "confirm_token"})
    normalized = {"reason": _payload_string(payload, "reason")}
    if payload.get("confirm_token") is not None:
        normalized["confirm_token"] = _payload_string(payload, "confirm_token")
    return normalized


def _validate_accept_provider_partial_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(payload, {"phase_id", "manifest_path", "accepted_findings"})
    accepted = payload.get("accepted_findings")
    if not isinstance(accepted, list) or not all(isinstance(item, str) and item for item in accepted):
        raise OperatorDecisionError("invalid-payload", "accept_provider_partial accepted_findings must be strings")
    return {
        "phase_id": _payload_string(payload, "phase_id"),
        "manifest_path": _payload_string(payload, "manifest_path"),
        "accepted_findings": list(accepted),
    }


def _apply_integrated_decision(run_id: str, decision: Mapping[str, Any], *, data_dir: Path) -> dict[str, Any]:
    kind = str(decision["kind"])
    payload = decision["payload"]
    if kind == "retry_phase":
        phase_id = str(payload["phase_id"])
        reason = str(payload["reason"])
        attempt_record = {
            "failure_kind": "operator_requested_retry",
            "retry_decision": "operator_decision_retry",
            "adopted": False,
            "status": "pending",
            "operator_decision_id": decision["decision_id"],
            "operator_decision_kind": kind,
            "operator": decision["operator"],
            "operator_reason": reason,
            **failure_kind_details("operator_requested_retry"),
        }
        return abandon_attempt_and_retry(
            run_id,
            phase_id,
            failure_kind="operator_requested_retry",
            data_dir=data_dir,
            launcher_error=reason,
            attempt_record=attempt_record,
            assume_locked=True,
        )
    raise OperatorDecisionError(
        "kind-not-integrated",
        "operator decision kind is recorded but not integrated with apply yet",
        decision_id=decision["decision_id"],
        kind=kind,
    )


def _assert_run_state(run_id: str, data_dir: Path) -> dict[str, Any]:
    _assert_run_dir_exists(run_id, data_dir)
    state_path = phase_session_path(run_id, data_dir=data_dir)
    if not state_path.is_file():
        raise OperatorDecisionError(
            "phase-session-not-found",
            "operator decision requires phase_sessions.v1.json",
            run_id=run_id,
            path=str(state_path),
        )
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperatorDecisionError("phase-session-invalid-json", "phase session state is invalid JSON", path=str(state_path)) from exc
    except OSError as exc:
        raise OperatorDecisionError("phase-session-unreadable", "phase session state is unreadable", path=str(state_path)) from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
        raise OperatorDecisionError(
            "phase-session-schema-mismatch",
            "operator decision requires phase_sessions.v1.json schema_version 1",
            path=str(state_path),
        )
    return load_phase_sessions(run_id, data_dir=data_dir)


def _assert_run_dir_exists(run_id: str, data_dir: Path) -> None:
    run_dir = data_dir / "runs" / run_id
    if not run_dir.is_dir():
        raise OperatorDecisionError("run-not-found", "operator decision run not found", run_id=run_id)


def _assert_payload_targets_state(kind: str, payload: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    phase_id = payload.get("phase_id")
    if phase_id is None:
        return
    phases = state.get("phases") if isinstance(state.get("phases"), list) else []
    if not any(isinstance(phase, Mapping) and phase.get("phase_id") == phase_id for phase in phases):
        raise OperatorDecisionError("phase-not-found", "operator decision phase not found", phase_id=phase_id, kind=kind)


def _load_or_empty(path: Path, run_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "decisions": [], "events": []}
    payload = _read_json_object(path)
    _validate_artifact(payload, run_id)
    return payload


def _load_existing(path: Path, run_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise OperatorDecisionError("artifact-not-found", "operator decision artifact not found", path=str(path))
    return _load_or_empty(path, run_id)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperatorDecisionError("invalid-json", "operator decision artifact is invalid JSON", path=str(path)) from exc
    except OSError as exc:
        raise OperatorDecisionError("read-failed", "operator decision artifact is not readable", path=str(path)) from exc
    if not isinstance(payload, dict):
        raise OperatorDecisionError("invalid-artifact", "operator decision artifact root must be an object", path=str(path))
    return payload


def _validate_artifact(payload: Mapping[str, Any], run_id: str) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise OperatorDecisionError("schema-mismatch", "operator decision artifact schema_version must be 1")
    if payload.get("run_id") != run_id:
        raise OperatorDecisionError("run-id-mismatch", "operator decision artifact run_id mismatch")
    decisions = payload.get("decisions")
    events = payload.get("events")
    if not isinstance(decisions, list):
        raise OperatorDecisionError("invalid-artifact", "operator decision decisions must be a list")
    if not isinstance(events, list):
        raise OperatorDecisionError("invalid-artifact", "operator decision events must be a list")
    for item in decisions:
        if not isinstance(item, Mapping):
            raise OperatorDecisionError("invalid-artifact", "operator decision records must be objects")
        OperatorDecision.from_mapping(item)
    for item in events:
        if not isinstance(item, Mapping):
            raise OperatorDecisionError("invalid-artifact", "operator decision events must be objects")
        _validate_status_event(item)


def _validate_status_event(event: Mapping[str, Any]) -> None:
    _required_string(event, "event_id")
    _required_string(event, "decision_id")
    _required_string(event, "event_type")
    _required_string(event, "created_at")
    status = _required_string(event, "status")
    if status not in STATUSES:
        raise OperatorDecisionError("invalid-status", f"unknown operator decision event status: {status}")


def _with_current_decisions(payload: Mapping[str, Any]) -> dict[str, Any]:
    events = payload.get("events") or []
    out = dict(payload)
    out["decisions"] = [_current_decision(item, events) for item in payload.get("decisions") or [] if isinstance(item, Mapping)]
    return out


def _current_decision(decision: Mapping[str, Any], events: list[Any]) -> dict[str, Any]:
    current = OperatorDecision.from_mapping(decision).to_record()
    for event in events:
        if not isinstance(event, Mapping) or event.get("decision_id") != current["decision_id"]:
            continue
        status = event.get("status")
        if status in STATUSES:
            current["status"] = status
            if status == STATUS_APPLIED:
                current["applied_at"] = current.get("applied_at") or event.get("applied_at") or event.get("created_at")
                current["applied_event_path"] = current.get("applied_event_path") or event.get("applied_event_path")
            if status == STATUS_SUPERSEDED:
                current["supersedes"] = event.get("supersedes") if isinstance(event.get("supersedes"), str) else current.get("supersedes")
    return current


def _find_decision(artifact: Mapping[str, Any], decision_id: str) -> dict[str, Any]:
    for item in artifact.get("decisions") or []:
        if isinstance(item, Mapping) and item.get("decision_id") == decision_id:
            return dict(item)
    raise OperatorDecisionError("decision-not-found", "operator decision not found", decision_id=decision_id)


def _find_duplicate_record(
    artifact: Mapping[str, Any],
    run_id: str,
    kind: str,
    payload: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any] | None:
    target_digest = _decision_digest(run_id, kind, payload, created_at=created_at)
    for item in artifact.get("decisions") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("kind") != kind:
            continue
        if _decision_digest(run_id, kind, item.get("payload") if isinstance(item.get("payload"), Mapping) else {}, created_at=str(item.get("created_at") or "")) == target_digest:
            return dict(item)
    return None


def _record_result(path: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    result = {"path": str(path), "decision": dict(decision)}
    if _confirm_required(decision):
        result["confirm_token"] = confirm_token_for_decision(decision)
    return result


def _status_event(
    *,
    decision: Mapping[str, Any],
    event_type: str,
    status: str,
    applied_at: str | None = None,
    applied_event_path: str | None = None,
    result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    created_at = utc_now()
    event = {
        "event_id": f"ode-{_sha1_hex(_canonical_json({'decision_id': decision['decision_id'], 'event_type': event_type, 'created_at': created_at}))[:12]}",
        "decision_id": decision["decision_id"],
        "event_type": event_type,
        "created_at": created_at,
        "status": status,
        "applied_at": applied_at,
        "applied_event_path": applied_event_path,
    }
    if result is not None:
        event["result"] = _event_result_summary(result)
    return event


def _event_result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    phase = result.get("phase") if isinstance(result.get("phase"), Mapping) else {}
    return {
        "retry": bool(result.get("retry")),
        "phase_id": phase.get("phase_id"),
        "status": phase.get("status"),
        "attempt": phase.get("attempt"),
    }


def _write_artifact(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        _atomic_json_write(path, payload)
    except OSError as exc:
        raise OperatorDecisionError("write-failed", "operator decision write failed", exit_code=74, path=str(path)) from exc


def _append_operator_run_event(
    data_dir: Path,
    *,
    run_id: str,
    event_type: str,
    decision: Mapping[str, Any],
    status: str,
    artifact_path: Path,
    result: Mapping[str, Any] | None = None,
) -> Path:
    payload = decision.get("payload") if isinstance(decision.get("payload"), Mapping) else {}
    details: dict[str, Any] = {
        "decision_id": decision.get("decision_id"),
        "kind": decision.get("kind"),
        "operator": decision.get("operator"),
        "status": status,
        "artifact_path": str(artifact_path),
        "payload_summary": _payload_event_summary(str(decision.get("kind") or ""), payload),
    }
    if result is not None:
        details["result"] = _event_result_summary(result)
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": event_type,
        "bd_epic_id": None,
        "phase_id": payload.get("phase_id") if isinstance(payload.get("phase_id"), str) else None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": decision.get("kind"),
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": details,
        "schema_ok": True,
    }
    validate_run_event(row)
    return append_run_event(data_dir, row)


def _append_retention_warning(data_dir: Path, *, run_id: str, decision_count: int, artifact_path: Path) -> None:
    row = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "operator_decisions_retention_warning",
        "bd_epic_id": None,
        "phase_id": None,
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": "operator_decisions_retention",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": {"decision_count": decision_count, "artifact_path": str(artifact_path)},
        "schema_ok": True,
    }
    validate_run_event(row)
    append_run_event(data_dir, row)


def _payload_event_summary(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _canonical_json(payload)
    if kind == "resume_with_input":
        operator_input = payload.get("input") if isinstance(payload.get("input"), Mapping) else {}
        redacted_payload = {
            "phase_id": payload.get("phase_id"),
            "input": "<redacted>",
            "input_sha1": _sha1_hex(_canonical_json(operator_input)),
        }
        preview = _canonical_json(redacted_payload)
        return {"sha1": _sha1_hex(canonical), "preview": preview[:256], "redacted": True}
    return {"sha1": _sha1_hex(canonical), "preview": canonical[:256], "redacted": False}


def _confirm_required(decision: Mapping[str, Any]) -> bool:
    return decision.get("kind") in CONFIRM_REQUIRED_KINDS


def _decision_id(
    run_id: str,
    kind: str,
    payload: Mapping[str, Any],
    *,
    created_at: str,
    sequence: int,
) -> str:
    digest = _decision_digest(run_id, kind, payload, created_at=created_at)
    return f"od-{_run_id_short(run_id)}-{sequence:03d}-{digest[:8]}"


def _decision_digest(run_id: str, kind: str, payload: Mapping[str, Any], *, created_at: str) -> str:
    basis = {
        "run_id": run_id,
        "kind": kind,
        "payload": payload,
        "created_at_minute": _truncate_timestamp_to_minute(created_at),
    }
    return _sha1_hex(_canonical_json(basis))


def _run_id_short(run_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "", run_id)
    return (clean[:8] or "run").lower()


def _truncate_timestamp_to_minute(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return value[:16]
    return dt.replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _validate_operator(value: str) -> str:
    if "@" in value:
        raise OperatorDecisionError("invalid-operator", "operator decision operator must not contain email addresses")
    if ":" not in value:
        raise OperatorDecisionError("invalid-operator", "operator decision operator must use <scope>:<identity>")
    scope, identity = value.split(":", 1)
    if scope not in {"local", "ci"}:
        raise OperatorDecisionError("invalid-operator", "operator decision operator scope must be local or ci")
    if not identity or not re.match(r"^[A-Za-z0-9._-]+$", identity):
        raise OperatorDecisionError("invalid-operator", "operator decision operator identity is invalid")
    return value


def _reject_unknown_keys(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise OperatorDecisionError(
            "invalid-payload",
            "operator decision payload contains unknown keys",
            unknown_keys=unknown,
        )


def _payload_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperatorDecisionError("invalid-payload", f"operator decision payload {key} must be a non-empty string")
    return value.strip()


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise OperatorDecisionError("invalid-artifact", f"operator decision {key} must be a non-empty string")
    return item


def _optional_string(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise OperatorDecisionError("invalid-artifact", f"operator decision {key} must be string or null")
    return value


__all__ = [
    "OPERATOR_DECISIONS_FILENAME",
    "OperatorDecision",
    "OperatorDecisionError",
    "OperatorDecisionStore",
    "apply",
    "confirm_token_for_decision",
    "default_operator",
    "list_decisions",
    "operator_decisions_path",
    "record",
    "show_decision",
    "validate_payload",
]
