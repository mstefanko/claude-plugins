"""Phase-session attempt evidence reader.

The reader is deliberately best-effort: unreadable attempt payloads should make
one row noisy, never make the whole run invisible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_data_dir
from .phase_sessions import load_phase_sessions, phase_status


TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


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
        phase_id = str(phase.get("phase_id") or "")
        title = str(phase.get("title") or phase_id)
        for item in phase.get("attempt_history") or []:
            if isinstance(item, Mapping):
                rows.append(_row_from_mapping(run_id, root, phase, item, title=title, archived_label=archived_label))
        attempt = int(phase.get("attempt") or 0)
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
    metrics = _stdout_metrics((launch_dir / "stdout.txt") if launch_dir else None)
    row = {
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_title": title,
        "attempt": attempt,
        "status": item.get("status") or phase.get("status"),
        "failure_kind": item.get("failure_kind") or phase.get("last_failure_kind"),
        "retry_decision": item.get("retry_decision") or phase.get("retry_policy_decision"),
        "adopted": item.get("adopted"),
        "started_at": item.get("started_at") or phase.get("started_at"),
        "completed_at": item.get("completed_at") or phase.get("completed_at"),
        "elapsed_seconds": item.get("elapsed_seconds"),
        "launcher_returncode": item.get("returncode") if item.get("returncode") is not None else command.get("returncode"),
        "session_name": item.get("session_name") or phase.get("session_name"),
        "child_pid": item.get("child_pid") or phase.get("child_pid") or command.get("child_pid"),
        "process_group_id": item.get("process_group_id") or phase.get("process_group_id") or command.get("process_group_id"),
        "launch_dir": str(launch_dir) if launch_dir else None,
        "result_path": item.get("result_path") or phase.get("result_path") or phase.get("expected_result_path") or command.get("result_path"),
        "handoff_path": item.get("handoff_path") or phase.get("handoff_path") or phase.get("expected_handoff_path") or command.get("handoff_path"),
        "recovery_context_path": item.get("recovery_context_path") or phase.get("recovery_context_path"),
        "stdout_tail_path": item.get("stdout_tail_path"),
        "stderr_tail_path": item.get("stderr_tail_path"),
        "archived": archived_label is not None,
        "archive": archived_label,
    }
    row.update(metrics)
    return row


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
        metrics = _stdout_metrics(attempt_dir / "stdout.txt")
        if row is None:
            row = {
                "phase_id": phase_id,
                "phase_title": phase_id,
                "attempt": attempt,
                "status": "unknown",
                "failure_kind": None,
                "retry_decision": None,
                "started_at": None,
                "completed_at": None,
                "elapsed_seconds": None,
                "launcher_returncode": command.get("returncode"),
                "session_name": None,
                "child_pid": command.get("child_pid"),
                "process_group_id": command.get("process_group_id"),
                "launch_dir": str(attempt_dir),
                "result_path": command.get("result_path"),
                "handoff_path": command.get("handoff_path"),
                "recovery_context_path": None,
                "stdout_tail_path": None,
                "stderr_tail_path": None,
                "archived": archived_label is not None,
                "archive": archived_label,
            }
            row.update(metrics)
            rows.append(row)
            by_key[key] = row
            continue
        for key_name, value in {
            "launch_dir": str(attempt_dir),
            "launcher_returncode": command.get("returncode"),
            "child_pid": command.get("child_pid"),
            "process_group_id": command.get("process_group_id"),
            "result_path": command.get("result_path"),
            "handoff_path": command.get("handoff_path"),
        }.items():
            if row.get(key_name) is None and value is not None:
                row[key_name] = value
        row.update(metrics)


def _stdout_metrics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return _unknown_metrics()
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        result = _unknown_metrics()
        result["stdout_parse_error"] = "stdout is empty"
        return result
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        result = _unknown_metrics()
        result["stdout_parse_error"] = str(exc)
        return result
    if not isinstance(payload, Mapping):
        result = _unknown_metrics()
        result["stdout_parse_error"] = "stdout JSON is not an object"
        return result
    metrics = _cost_metrics(payload)
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    for field in TOKEN_FIELDS:
        metrics[field] = _int_or_none(usage.get(field))
    metrics["duration_ms"] = _int_or_none(payload.get("duration_ms"))
    metrics["duration_api_ms"] = _int_or_none(payload.get("duration_api_ms"))
    metrics["num_turns"] = _int_or_none(payload.get("num_turns"))
    denials = payload.get("permission_denials")
    metrics["permission_denial_count"] = len(denials) if isinstance(denials, list) else (_int_or_none(denials) or 0)
    metrics["stdout_parse_error"] = None
    return metrics


def _unknown_metrics() -> dict[str, Any]:
    return {
        "total_cost_usd": None,
        "cost_confidence": "unknown",
        "cost_source": "unknown",
        "provider_reported_total_cost_usd": None,
        "model_usage_cost_usd": None,
        "permission_denial_count": 0,
        **{field: None for field in TOKEN_FIELDS},
        "duration_ms": None,
        "duration_api_ms": None,
        "num_turns": None,
    }


def _cost_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    direct = _number_or_none(payload.get("total_cost_usd"))
    model_usage_cost = _model_usage_cost(payload.get("modelUsage"))
    if direct is not None and model_usage_cost is not None and abs(direct - model_usage_cost) > 0.000001:
        return {
            "total_cost_usd": None,
            "cost_confidence": "conflict",
            "cost_source": "conflict",
            "provider_reported_total_cost_usd": direct,
            "model_usage_cost_usd": model_usage_cost,
        }
    if direct is not None:
        return {
            "total_cost_usd": direct,
            "cost_confidence": "provider_reported",
            "cost_source": "total_cost_usd",
            "provider_reported_total_cost_usd": direct,
            "model_usage_cost_usd": model_usage_cost,
        }
    if model_usage_cost is not None:
        return {
            "total_cost_usd": model_usage_cost,
            "cost_confidence": "provider_reported",
            "cost_source": "modelUsage.costUSD",
            "provider_reported_total_cost_usd": None,
            "model_usage_cost_usd": model_usage_cost,
        }
    return _unknown_metrics() | {"stdout_parse_error": None}


def _model_usage_cost(value: Any) -> float | None:
    costs: list[float] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            cost = _number_or_none(obj.get("costUSD"))
            if cost is not None:
                costs.append(cost)
            for child in obj.values():
                walk(child)
        elif isinstance(obj, list):
            for child in obj:
                walk(child)

    walk(value)
    return sum(costs) if costs else None


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
            if _is_failed_attempt(row):
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


def _is_failed_attempt(row: Mapping[str, Any]) -> bool:
    if row.get("adopted") is True or row.get("retry_decision") == "adopted":
        return False
    if row.get("failure_kind"):
        return True
    if row.get("retry_decision") in {"retry", "recovery_retry", "retry_exhausted", "same_failure_limit", "deterministic_contract_failure"}:
        return True
    return row.get("status") in {"failed", "blocked", "needs_input", "retry_waiting", "retry_exhausted"}


def _last_failure(status: Mapping[str, Any]) -> dict[str, Any] | None:
    for phase in reversed(status.get("phases") or []):
        if isinstance(phase, Mapping) and phase.get("last_failure_kind"):
            return {
                "phase_id": phase.get("phase_id"),
                "attempt": phase.get("attempt"),
                "failure_kind": phase.get("last_failure_kind"),
                "retry_decision": phase.get("retry_policy_decision"),
                "blocked_reason": phase.get("blocked_reason"),
            }
    return None


def _last_error(status: Mapping[str, Any]) -> str | None:
    for phase in reversed(status.get("phases") or []):
        if isinstance(phase, Mapping) and isinstance(phase.get("last_error"), str):
            return str(phase["last_error"])
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


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _archive_key(row: Mapping[str, Any]) -> str:
    value = row.get("archive")
    return value if isinstance(value, str) else ""


def _attempt_sort_key(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (_archive_key(row), str(row.get("phase_id") or ""), int(row.get("attempt") or 0), str(row.get("launch_dir") or ""))


__all__ = ["summarize_phase_attempts"]
