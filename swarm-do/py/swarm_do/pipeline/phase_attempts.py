"""Phase-session attempt evidence reader.

The reader is deliberately best-effort: unreadable attempt payloads should make
one row noisy, never make the whole run invisible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .domain import DomainContractError, PhaseAttemptRecord, PhaseRecord
from .failure_taxonomy import failure_kind_details
from .paths import resolve_data_dir
from .phase_attempt_metrics import TOKEN_FIELDS, stdout_metrics
from .phase_evidence import read_attempt_evidence_manifest
from .phase_sessions import load_phase_sessions, phase_status


def summarize_phase_attempts(
    run_id: str,
    *,
    data_dir: Path | None = None,
    include_archived: bool = False,
    include_events: bool = False,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    run_dir = base / "runs" / run_id
    state = load_phase_sessions(run_id, data_dir=base)
    status = phase_status(run_id, data_dir=base)
    attempts: list[dict[str, Any]] = []
    attempts.extend(_attempts_from_state(run_id, run_dir, state, archived_label=None))
    _merge_launch_dirs(attempts, run_dir / "phase_launches", archived_label=None)

    archived_provider_reported_usd = 0.0
    archived_provider_count = 0
    archived_unknown_count = 0
    for archive in sorted(path for path in run_dir.glob(".archived-*") if path.is_dir()):
        archived_rows: list[dict[str, Any]] = []
        archived_state_path = archive / "phase_sessions.v1.json"
        if archived_state_path.is_file():
            try:
                archived_state = json.loads(archived_state_path.read_text(encoding="utf-8"))
            except Exception:
                archived_state = {"phases": []}
            archived_rows.extend(_attempts_from_state(run_id, archive, archived_state, archived_label=archive.name))
        _merge_launch_dirs(archived_rows, archive / "phase_launches", archived_label=archive.name)
        for row in archived_rows:
            if row.get("cost_confidence") == "provider_reported" and isinstance(row.get("total_cost_usd"), (int, float)):
                archived_provider_reported_usd += float(row["total_cost_usd"])
                archived_provider_count += 1
            elif row.get("cost_confidence") in {"unknown", "conflict"}:
                archived_unknown_count += 1
        if include_archived:
            attempts.extend(archived_rows)

    attempts = sorted(attempts, key=_attempt_sort_key)
    cost = _cost_summary(attempts, archived_provider_reported_usd, archived_provider_count, archived_unknown_count)
    payload = {
        "run_id": run_id,
        "status": status.get("status"),
        "updated_at": status.get("updated_at"),
        "cost": cost,
        "tokens": _token_summary(attempts),
        "attempts": {
            "total": len([row for row in attempts if not row.get("archived")]),
            "by_phase": _attempt_counts_by_phase(attempts),
            "rows": attempts,
        },
        "last_failure": _last_failure(status),
        "last_error": _last_error(status),
        "permission_denial_count": sum(int(row.get("permission_denial_count") or 0) for row in attempts),
        "recommended_action": _recommended_action(run_id, status),
    }
    if include_events:
        payload["events"] = _recent_events(run_id, base)
    return payload


def _attempts_from_state(
    run_id: str,
    root: Path,
    state: Mapping[str, Any],
    *,
    archived_label: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        try:
            phase_record = PhaseRecord.from_mapping(phase)
        except DomainContractError:
            continue
        phase_id = phase_record.phase_id
        title = phase_record.title or phase_id
        for item in phase.get("attempt_history") or []:
            if isinstance(item, Mapping):
                rows.append(_row_from_mapping(run_id, root, phase, item, title=title, archived_label=archived_label))
        attempt = phase_record.attempt
        if attempt > 0 and not any(row.get("phase_id") == phase_id and row.get("attempt") == attempt for row in rows):
            rows.append(_row_from_mapping(run_id, root, phase, phase, title=title, archived_label=archived_label))
    return rows


def _row_from_mapping(
    run_id: str,
    root: Path,
    phase: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    title: str,
    archived_label: str | None,
) -> dict[str, Any]:
    phase_id = str(phase.get("phase_id") or item.get("phase_id") or "")
    attempt = int(item.get("attempt") or phase.get("attempt") or 0)
    launch_dir = _path_value(item.get("launch_dir") or phase.get("launch_dir"), root=root)
    if launch_dir is None and attempt > 0:
        launch_dir = root / "phase_launches" / phase_id / f"attempt-{attempt}"
    command = _read_json_object((launch_dir / "command.json") if launch_dir else None)
    metrics = stdout_metrics((launch_dir / "stdout.txt") if launch_dir else None)
    evidence_path = _evidence_path(item, phase, launch_dir)
    manifest = _read_manifest(evidence_path)
    taxonomy = _taxonomy_details(item, phase)
    row = {
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_title": title,
        "attempt": attempt,
        "status": item.get("status") or phase.get("status"),
        "failure_kind": item.get("failure_kind") or phase.get("last_failure_kind"),
        "retry_decision": item.get("retry_decision") or phase.get("retry_policy_decision"),
        "policy_action": item.get("policy_action"),
        "policy_reason": item.get("policy_reason"),
        "policy_inputs": item.get("policy_inputs") if isinstance(item.get("policy_inputs"), Mapping) else None,
        "adopted": item.get("adopted"),
        "started_at": item.get("started_at") or phase.get("started_at"),
        "completed_at": item.get("completed_at") or phase.get("completed_at"),
        "elapsed_seconds": item.get("elapsed_seconds"),
        "launcher_returncode": item.get("returncode") if item.get("returncode") is not None else command.get("returncode"),
        "session_name": item.get("session_name") or phase.get("session_name"),
        "child_pid": item.get("child_pid") or phase.get("child_pid") or command.get("child_pid"),
        "process_group_id": item.get("process_group_id") or phase.get("process_group_id") or command.get("process_group_id"),
        "launch_dir": str(launch_dir) if launch_dir else None,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "result_path": item.get("result_path") or phase.get("result_path") or phase.get("expected_result_path") or command.get("result_path"),
        "handoff_path": item.get("handoff_path") or phase.get("handoff_path") or phase.get("expected_handoff_path") or command.get("handoff_path"),
        "recovery_context_path": item.get("recovery_context_path") or phase.get("recovery_context_path"),
        "stdout_tail_path": item.get("stdout_tail_path"),
        "stderr_tail_path": item.get("stderr_tail_path"),
        "changed_files": _string_list(item.get("changed_files")),
        "cleanup": item.get("cleanup") if isinstance(item.get("cleanup"), Mapping) else None,
        "child_process": item.get("child_process") if isinstance(item.get("child_process"), Mapping) else None,
        "archived": archived_label is not None,
        "archive": archived_label,
    }
    row.update(taxonomy)
    row.update(metrics)
    if manifest is not None:
        _apply_manifest_projection(row, manifest)
    return PhaseAttemptRecord.from_mapping(row, preserve_unknown=True).to_row()


def _merge_launch_dirs(rows: list[dict[str, Any]], launch_root: Path, *, archived_label: str | None) -> None:
    if not launch_root.is_dir():
        return
    by_key = {(_archive_key(row), str(row.get("phase_id")), int(row.get("attempt") or 0)): row for row in rows}
    for attempt_dir in sorted(launch_root.glob("*/attempt-*")):
        if not attempt_dir.is_dir():
            continue
        phase_id = attempt_dir.parent.name
        match = re.match(r"attempt-(\d+)$", attempt_dir.name)
        if not match:
            continue
        attempt = int(match.group(1))
        key = (archived_label or "", phase_id, attempt)
        row = by_key.get(key)
        command = _read_json_object(attempt_dir / "command.json")
        metrics = stdout_metrics(attempt_dir / "stdout.txt")
        if row is None:
            evidence_path = attempt_dir / "evidence.json" if (attempt_dir / "evidence.json").is_file() else None
            manifest = _read_manifest(evidence_path)
            row = {
                "run_id": None,
                "phase_id": phase_id,
                "phase_title": phase_id,
                "attempt": attempt,
                "status": "unknown",
                "failure_kind": None,
                "retry_decision": None,
                "policy_action": None,
                "policy_reason": None,
                "policy_inputs": None,
                "failure_category": None,
                "failure_retry_class": None,
                "failure_operator_title": None,
                "failure_operator_message": None,
                "failure_known": False,
                "started_at": None,
                "completed_at": None,
                "elapsed_seconds": None,
                "launcher_returncode": command.get("returncode"),
                "session_name": None,
                "child_pid": command.get("child_pid"),
                "process_group_id": command.get("process_group_id"),
                "launch_dir": str(attempt_dir),
                "evidence_path": str(evidence_path) if evidence_path else None,
                "result_path": command.get("result_path"),
                "handoff_path": command.get("handoff_path"),
                "recovery_context_path": None,
                "stdout_tail_path": None,
                "stderr_tail_path": None,
                "changed_files": [],
                "cleanup": None,
                "child_process": None,
                "archived": archived_label is not None,
                "archive": archived_label,
            }
            row.update(metrics)
            if manifest is not None:
                _apply_manifest_projection(row, manifest)
            rows.append(row)
            by_key[key] = row
            continue
        for key_name, value in {
            "launch_dir": str(attempt_dir),
            "evidence_path": str(attempt_dir / "evidence.json") if (attempt_dir / "evidence.json").is_file() else None,
            "launcher_returncode": command.get("returncode"),
            "child_pid": command.get("child_pid"),
            "process_group_id": command.get("process_group_id"),
            "result_path": command.get("result_path"),
            "handoff_path": command.get("handoff_path"),
        }.items():
            if row.get(key_name) is None and value is not None:
                row[key_name] = value
        row.update(metrics)
        manifest = _read_manifest(Path(str(row["evidence_path"]))) if isinstance(row.get("evidence_path"), str) else None
        if manifest is not None:
            _apply_manifest_projection(row, manifest)


def _taxonomy_details(item: Mapping[str, Any], phase: Mapping[str, Any]) -> dict[str, Any]:
    failure_kind = item.get("failure_kind") or phase.get("last_failure_kind")
    details = failure_kind_details(failure_kind)
    for key in (
        "failure_category",
        "failure_retry_class",
        "failure_operator_title",
        "failure_operator_message",
        "failure_known",
    ):
        if item.get(key) is not None:
            details[key] = item.get(key)
        elif phase.get(key) is not None:
            details[key] = phase.get(key)
    return details


def _evidence_path(item: Mapping[str, Any], phase: Mapping[str, Any], launch_dir: Path | None) -> Path | None:
    value = item.get("evidence_path") or phase.get("evidence_path")
    if isinstance(value, str) and value:
        return Path(value)
    if launch_dir is not None:
        candidate = launch_dir / "evidence.json"
        if candidate.is_file():
            return candidate
    return None


def _read_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        return read_attempt_evidence_manifest(path)
    except Exception:
        return None


def _apply_manifest_projection(row: dict[str, Any], manifest: Mapping[str, Any]) -> None:
    paths = manifest.get("paths") if isinstance(manifest.get("paths"), Mapping) else {}
    process = manifest.get("process") if isinstance(manifest.get("process"), Mapping) else {}
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), Mapping) else {}
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), Mapping) else {}
    failure = manifest.get("failure") if isinstance(manifest.get("failure"), Mapping) else {}
    recovery = manifest.get("recovery") if isinstance(manifest.get("recovery"), Mapping) else {}
    for key, value in {
        "status": manifest.get("status"),
        "session_name": manifest.get("session_name"),
        "launch_dir": paths.get("launch_dir"),
        "evidence_path": paths.get("evidence_path"),
        "result_path": paths.get("result_path"),
        "handoff_path": paths.get("handoff_path"),
        "launcher_returncode": process.get("returncode"),
        "child_pid": process.get("child_pid"),
        "process_group_id": process.get("process_group_id"),
        "recovery_context_path": recovery.get("recovery_context_path"),
        "stdout_tail_path": recovery.get("stdout_tail_path"),
        "stderr_tail_path": recovery.get("stderr_tail_path"),
        "diff_summary_path": recovery.get("diff_summary_path"),
        "transcript_diagnostics_path": recovery.get("transcript_diagnostics_path"),
        "failure_kind": failure.get("failure_kind"),
        "retry_decision": failure.get("retry_decision"),
        "failure_category": failure.get("failure_category"),
        "failure_retry_class": failure.get("failure_retry_class"),
        "failure_operator_title": failure.get("failure_operator_title"),
        "failure_operator_message": failure.get("failure_operator_message"),
        "failure_known": failure.get("failure_known"),
        "policy_action": failure.get("policy_action"),
        "policy_reason": failure.get("policy_reason"),
        "policy_inputs": failure.get("policy_inputs") if isinstance(failure.get("policy_inputs"), Mapping) else None,
    }.items():
        if key == "status" and row.get(key) in {None, "unknown"} and value is not None:
            row[key] = value
        elif key == "failure_known" and row.get(key) in {None, False} and value is not None:
            row[key] = value
        elif row.get(key) is None and value is not None:
            row[key] = value
    if not row.get("changed_files") and isinstance(artifacts.get("changed_files"), list):
        row["changed_files"] = _string_list(artifacts.get("changed_files"))
    for key in (
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
    ):
        if key == "cost_confidence" and row.get(key) in {None, "unknown"} and metrics.get(key) is not None:
            row[key] = metrics.get(key)
        elif row.get(key) is None and metrics.get(key) is not None:
            row[key] = metrics.get(key)


def _cost_summary(
    attempts: list[dict[str, Any]],
    archived_provider_reported_usd: float,
    archived_provider_count: int,
    archived_unknown_count: int,
) -> dict[str, Any]:
    total = 0.0
    failed = 0.0
    unknown = 0
    by_phase: dict[str, dict[str, Any]] = {}
    for row in attempts:
        if row.get("archived"):
            continue
        phase_id = str(row.get("phase_id"))
        bucket = by_phase.setdefault(phase_id, {"total_usd": 0.0, "failed_usd": 0.0, "unknown_attempt_count": 0})
        cost = row.get("total_cost_usd")
        if row.get("cost_confidence") == "provider_reported" and isinstance(cost, (int, float)):
            total += float(cost)
            bucket["total_usd"] += float(cost)
            if is_failed_attempt(row):
                failed += float(cost)
                bucket["failed_usd"] += float(cost)
        else:
            unknown += 1
            bucket["unknown_attempt_count"] += 1
    return {
        "total_usd": total,
        "failed_usd": failed,
        "unknown_attempt_count": unknown,
        "archived_provider_reported_usd": archived_provider_reported_usd if archived_provider_count else None,
        "archived_provider_reported_attempt_count": archived_provider_count,
        "archived_unknown_attempt_count": archived_unknown_count,
        "by_phase": by_phase,
    }


def _token_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    by_phase: dict[str, dict[str, int]] = {}
    for row in attempts:
        if row.get("archived"):
            continue
        phase = by_phase.setdefault(str(row.get("phase_id")), {field: 0 for field in TOKEN_FIELDS})
        for field in TOKEN_FIELDS:
            value = row.get(field)
            if isinstance(value, int):
                phase[field] += value
    return {"by_phase": by_phase}


def _attempt_counts_by_phase(attempts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in attempts:
        if row.get("archived"):
            continue
        phase_id = str(row.get("phase_id"))
        counts[phase_id] = counts.get(phase_id, 0) + 1
    return counts


def is_failed_attempt(row: Mapping[str, Any]) -> bool:
    try:
        record = PhaseAttemptRecord.from_mapping(row, preserve_unknown=True)
    except DomainContractError:
        record = None
    adopted = record.adopted if record is not None else row.get("adopted")
    retry_decision = record.retry_decision if record is not None else row.get("retry_decision")
    failure_kind = record.failure_kind if record is not None else row.get("failure_kind")
    status = record.status if record is not None else row.get("status")
    if adopted is True or retry_decision == "adopted":
        return False
    if failure_kind:
        return True
    if retry_decision in {"retry", "recovery_retry", "retry_exhausted", "same_failure_limit", "deterministic_contract_failure"}:
        return True
    return status in {"failed", "blocked", "needs_input", "retry_waiting", "retry_exhausted"}


def _last_failure(status: Mapping[str, Any]) -> dict[str, Any] | None:
    for phase in reversed(status.get("phases") or []):
        if not isinstance(phase, Mapping):
            continue
        try:
            record = PhaseRecord.from_mapping(phase)
        except DomainContractError:
            continue
        if not record.last_failure_kind:
            continue
        details = failure_kind_details(record.last_failure_kind)
        for key in (
            "failure_category",
            "failure_retry_class",
            "failure_operator_title",
            "failure_operator_message",
            "failure_known",
        ):
            if phase.get(key) is not None:
                details[key] = phase.get(key)
        return {
            "phase_id": record.phase_id,
            "attempt": record.attempt,
            "failure_kind": record.last_failure_kind,
            "retry_decision": record.retry_policy_decision,
            "policy_action": phase.get("policy_action"),
            "policy_reason": phase.get("policy_reason"),
            "blocked_reason": record.blocked_reason,
            "evidence_path": record.evidence_path,
            **details,
        }
    return None


def _last_error(status: Mapping[str, Any]) -> str | None:
    for phase in reversed(status.get("phases") or []):
        if not isinstance(phase, Mapping):
            continue
        try:
            record = PhaseRecord.from_mapping(phase)
        except DomainContractError:
            continue
        if record.last_error:
            return record.last_error
    return None


def _recommended_action(run_id: str, status: Mapping[str, Any]) -> str | None:
    value = status.get("status")
    if value == "retry_waiting":
        return f"bin/swarm phases recover {run_id}"
    if value in {"blocked", "needs_input", "retry_exhausted", "failed"}:
        return f"bin/swarm phases status {run_id} --attempts --cost"
    return status.get("recommended_command") if isinstance(status.get("recommended_command"), str) else None


def _recent_events(run_id: str, data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "telemetry" / "run_events.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("run_id") == run_id:
            rows.append(row)
    return rows[-50:]


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _path_value(value: Any, *, root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = root / path
    if candidate.exists():
        return candidate
    return Path(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _archive_key(row: Mapping[str, Any]) -> str:
    value = row.get("archive")
    return value if isinstance(value, str) else ""


def _attempt_sort_key(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (_archive_key(row), str(row.get("phase_id") or ""), int(row.get("attempt") or 0), str(row.get("launch_dir") or ""))


__all__ = ["is_failed_attempt", "summarize_phase_attempts"]
