"""Per-attempt evidence manifest builder for phase sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .failure_taxonomy import failure_kind_details
from .paths import REPO_ROOT
from .phase_attempt_metrics import stdout_metrics
from .run_state import _atomic_json_write


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "evidence.json"


def attempt_launch_dir(data_dir: Path, run_id: str, phase_id: str, attempt: int) -> Path:
    return data_dir / "runs" / run_id / "phase_launches" / str(phase_id) / f"attempt-{int(attempt)}"


def attempt_evidence_path(data_dir: Path, run_id: str, phase_id: str, attempt: int) -> Path:
    return attempt_launch_dir(data_dir, run_id, phase_id, attempt) / MANIFEST_FILENAME


def build_attempt_evidence_manifest(
    run_id: str,
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None,
    attempt_record: Mapping[str, Any] | None,
    data_dir: Path,
) -> dict[str, Any]:
    record = attempt_record if isinstance(attempt_record, Mapping) else {}
    phase_id = str(phase.get("phase_id") or record.get("phase_id") or "")
    attempt = int(record.get("attempt") or phase.get("attempt") or 0)
    launch_dir = _path_value(record.get("launch_dir") or phase.get("launch_dir"), data_dir=data_dir, run_id=run_id)
    if launch_dir is None and attempt > 0:
        launch_dir = attempt_launch_dir(data_dir, run_id, phase_id, attempt)
    evidence_path = (launch_dir / MANIFEST_FILENAME) if launch_dir is not None else attempt_evidence_path(data_dir, run_id, phase_id, attempt)
    command_path = _path_value(record.get("command_path") or phase.get("command_path"), data_dir=data_dir, run_id=run_id)
    if command_path is None and launch_dir is not None:
        command_path = launch_dir / "command.json"
    command = _read_json_object(command_path)
    prompt_path = _path_value(command.get("prompt_path"), data_dir=data_dir, run_id=run_id)
    if prompt_path is None and launch_dir is not None:
        prompt_path = launch_dir / "dispatcher.launcher.prompt.md"
    source_prompt_path = _path_value(command.get("source_prompt_path"), data_dir=data_dir, run_id=run_id)
    stdout_path = (launch_dir / "stdout.txt") if launch_dir is not None and (launch_dir / "stdout.txt").is_file() else None
    stderr_path = (launch_dir / "stderr.txt") if launch_dir is not None and (launch_dir / "stderr.txt").is_file() else None
    result_path = _path_value(
        record.get("result_path") or phase.get("result_path") or phase.get("expected_result_path") or command.get("result_path"),
        data_dir=data_dir,
        run_id=run_id,
    )
    handoff_path = _path_value(
        record.get("handoff_path") or phase.get("handoff_path") or phase.get("expected_handoff_path") or command.get("handoff_path"),
        data_dir=data_dir,
        run_id=run_id,
    )
    metrics = stdout_metrics(stdout_path)
    failure_kind = record.get("failure_kind") or phase.get("last_failure_kind")
    failure = failure_kind_details(failure_kind)
    failure = _prefer_persisted_failure_fields(failure, record, phase)
    recovery = _recovery_projection(record)
    artifact_error_kinds = _string_list(record.get("artifact_error_kinds"))
    partial_artifacts = bool(record.get("partial_artifacts"))
    changed_files = _changed_files(record, handoff_path)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "phase_id": phase_id,
        "attempt": attempt,
        "generated_at": _utc_now(),
        "session_name": record.get("session_name") or phase.get("session_name"),
        "launcher": record.get("launcher") or command.get("launcher") or _launcher_from_command(phase.get("lease_command")),
        "status": str(record.get("status") or phase.get("status") or "unknown"),
        "paths": {
            "launch_dir": str(launch_dir) if launch_dir is not None else "",
            "evidence_path": str(evidence_path),
            "command_path": str(command_path) if command_path is not None and command_path.exists() else None,
            "prompt_path": str(prompt_path) if prompt_path is not None and prompt_path.exists() else None,
            "source_prompt_path": str(source_prompt_path) if source_prompt_path is not None and source_prompt_path.exists() else None,
            "stdout_path": str(stdout_path) if stdout_path is not None else None,
            "stderr_path": str(stderr_path) if stderr_path is not None else None,
            "result_path": str(result_path) if result_path is not None else None,
            "handoff_path": str(handoff_path) if handoff_path is not None else None,
        },
        "hashes": {
            "prompt_sha": _sha_from_command_or_file(command, "prompt_sha", prompt_path),
            "source_prompt_sha": _sha_from_command_or_file(command, "source_prompt_sha", source_prompt_path),
            "settings_sha": _string_or_none(command.get("settings_sha")),
        },
        "process": {
            "parent_pid": _int_or_none(record.get("parent_pid") or phase.get("parent_pid") or command.get("parent_pid")),
            "child_pid": _int_or_none(record.get("child_pid") or phase.get("child_pid") or command.get("child_pid")),
            "process_group_id": _int_or_none(record.get("process_group_id") or phase.get("process_group_id") or command.get("process_group_id")),
            "returncode": _int_or_none(record.get("returncode") if record.get("returncode") is not None else command.get("returncode")),
            "started_at": _string_or_none(record.get("started_at") or phase.get("started_at") or command.get("started_at")),
            "completed_at": _string_or_none(record.get("completed_at") or phase.get("completed_at") or command.get("completed_at")),
            "elapsed_seconds": _number_or_none(record.get("elapsed_seconds") or command.get("elapsed_seconds")),
        },
        "workspace": {
            "execution_workspace_mode": _string_or_none(command.get("execution_workspace_mode")),
            "safe_cwd_enabled": command.get("safe_cwd_enabled") if isinstance(command.get("safe_cwd_enabled"), bool) else None,
            "launcher_cwd": _string_or_none(command.get("launcher_cwd")),
            "launcher_repo_root": _string_or_none(command.get("launcher_repo_root")),
            "source_git_top_level": _string_or_none(command.get("source_git_top_level")),
            "source_project_root": _string_or_none(command.get("source_project_root")),
            "safe_git_worktree_root": _string_or_none(command.get("safe_git_worktree_root")),
            "safe_project_root": _string_or_none(command.get("safe_project_root")),
            "project_subdir": command.get("project_subdir") if isinstance(command.get("project_subdir"), str) else None,
            "run_execution_branch": _string_or_none(command.get("run_execution_branch")),
            "git_base_sha": _string_or_none(command.get("git_base_sha")),
            "git_base_ref": _string_or_none(command.get("git_base_ref")),
            "run_worktree_manifest_path": _string_or_none(command.get("run_worktree_manifest_path")),
            "copied_ignored_artifacts": (
                command.get("copied_ignored_artifacts")
                if isinstance(command.get("copied_ignored_artifacts"), list)
                else None
            ),
            "real_repo_root_recorded": isinstance(command.get("real_repo_root"), str),
        },
        "artifacts": {
            "result_valid": _artifact_valid(result_path, partial_artifacts, artifact_error_kinds),
            "handoff_valid": _artifact_valid(handoff_path, partial_artifacts, artifact_error_kinds),
            "partial_artifacts": partial_artifacts,
            "artifact_error_kinds": artifact_error_kinds,
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
        },
        "metrics": {
            "total_cost_usd": metrics.get("total_cost_usd"),
            "cost_confidence": metrics.get("cost_confidence"),
            "input_tokens": metrics.get("input_tokens"),
            "cache_creation_input_tokens": metrics.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": metrics.get("cache_read_input_tokens"),
            "output_tokens": metrics.get("output_tokens"),
            "duration_ms": metrics.get("duration_ms"),
            "duration_api_ms": metrics.get("duration_api_ms"),
            "num_turns": metrics.get("num_turns"),
            "permission_denial_count": int(metrics.get("permission_denial_count") or 0),
        },
        "failure": {
            "failure_kind": failure.get("failure_kind"),
            "failure_category": failure.get("failure_category"),
            "failure_retry_class": failure.get("failure_retry_class"),
            "failure_operator_title": failure.get("failure_operator_title"),
            "failure_operator_message": failure.get("failure_operator_message"),
            "failure_known": bool(failure.get("failure_known")),
            "retry_decision": record.get("retry_decision") or phase.get("retry_policy_decision"),
            "retry_after_seconds": _int_or_none(record.get("retry_after_seconds")),
            "policy_action": _string_or_none(record.get("policy_action")),
            "policy_reason": _string_or_none(record.get("policy_reason")),
            "policy_inputs": record.get("policy_inputs") if isinstance(record.get("policy_inputs"), Mapping) else None,
            "blocked_reason": record.get("blocked_reason") or phase.get("blocked_reason"),
            "diagnostic_last_error": _string_or_none(record.get("diagnostic_last_error")),
        },
        "recovery": recovery,
        "redaction": {
            "contains_raw_prompt": False,
            "contains_raw_stdout": False,
            "contains_raw_stderr": False,
            "contains_raw_transcript": False,
            "contains_env": False,
            "path_values_may_be_local": True,
        },
    }
    return manifest


def write_attempt_evidence_manifest(
    run_id: str,
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None,
    attempt_record: Mapping[str, Any] | None,
    data_dir: Path,
) -> Path:
    manifest = build_attempt_evidence_manifest(
        run_id,
        phase,
        state=state,
        attempt_record=attempt_record,
        data_dir=data_dir,
    )
    _validate_manifest(manifest)
    path = Path(str(manifest["paths"]["evidence_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, manifest)
    return path


def read_attempt_evidence_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"attempt evidence is not readable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"attempt evidence is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"attempt evidence must be a JSON object: {path}")
    _validate_manifest(payload)
    return payload


def redacted_attempt_evidence(manifest: Mapping[str, Any]) -> dict[str, Any]:
    paths = manifest.get("paths") if isinstance(manifest.get("paths"), Mapping) else {}
    failure = manifest.get("failure") if isinstance(manifest.get("failure"), Mapping) else {}
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), Mapping) else {}
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), Mapping) else {}
    recovery = manifest.get("recovery") if isinstance(manifest.get("recovery"), Mapping) else {}
    return {
        "run_id": manifest.get("run_id"),
        "phase_id": manifest.get("phase_id"),
        "attempt": manifest.get("attempt"),
        "status": manifest.get("status"),
        "launcher": manifest.get("launcher"),
        "failure_kind": failure.get("failure_kind"),
        "failure_category": failure.get("failure_category"),
        "failure_retry_class": failure.get("failure_retry_class"),
        "failure_operator_title": failure.get("failure_operator_title"),
        "retry_decision": failure.get("retry_decision"),
        "policy_action": failure.get("policy_action"),
        "policy_reason": failure.get("policy_reason"),
        "total_cost_usd": metrics.get("total_cost_usd"),
        "cost_confidence": metrics.get("cost_confidence"),
        "num_turns": metrics.get("num_turns"),
        "permission_denial_count": metrics.get("permission_denial_count"),
        "changed_file_count": artifacts.get("changed_file_count"),
        "evidence_path": paths.get("evidence_path"),
        "recovery_context_path": recovery.get("recovery_context_path"),
        "diff_summary_path": recovery.get("diff_summary_path"),
        "transcript_diagnostics_path": recovery.get("transcript_diagnostics_path"),
    }


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads((REPO_ROOT / "schemas" / "phase_attempt_evidence.schema.json").read_text(encoding="utf-8"))
    errors = validate_value(dict(manifest), schema)
    if errors:
        raise ValueError("schema validation failed: " + "; ".join(errors))


def _prefer_persisted_failure_fields(
    details: dict[str, Any],
    record: Mapping[str, Any],
    phase: Mapping[str, Any],
) -> dict[str, Any]:
    out = dict(details)
    for key in (
        "failure_category",
        "failure_retry_class",
        "failure_operator_title",
        "failure_operator_message",
        "failure_known",
    ):
        if key in record and record.get(key) is not None:
            out[key] = record.get(key)
        elif key in phase and phase.get(key) is not None:
            out[key] = phase.get(key)
    return out


def _recovery_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stdout_tail_path": _string_or_none(record.get("stdout_tail_path")),
        "stderr_tail_path": _string_or_none(record.get("stderr_tail_path")),
        "diff_summary_path": _string_or_none(record.get("diff_summary_path")),
        "recovery_context_path": _string_or_none(record.get("recovery_context_path")),
        "transcript_diagnostics_path": _string_or_none(record.get("transcript_diagnostics_path")),
        "transcript_found": record.get("transcript_found") if isinstance(record.get("transcript_found"), bool) else None,
        "tool_errors_count": _int_or_none(record.get("tool_errors_count")),
    }


def _path_value(value: Any, *, data_dir: Path, run_id: str) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = (
        data_dir / "runs" / run_id / path,
        data_dir / path,
        REPO_ROOT / path,
        path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _sha_from_command_or_file(command: Mapping[str, Any], key: str, path: Path | None) -> str | None:
    value = command.get(key)
    if isinstance(value, str) and value:
        return value
    if path is not None and path.is_file():
        return _sha256_file(path)
    return None


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact_valid(path: Path | None, partial_artifacts: bool, artifact_error_kinds: list[str]) -> bool:
    return bool(path is not None and path.is_file() and not partial_artifacts and not artifact_error_kinds)


def _changed_files(record: Mapping[str, Any], handoff_path: Path | None) -> list[str]:
    values = _string_list(record.get("changed_files"))
    if values:
        return values
    handoff = _read_json_object(handoff_path)
    return _string_list(handoff.get("changed_files"))


def _launcher_from_command(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if ":" in value:
        return value.rsplit(":", 1)[-1]
    return value or None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "attempt_evidence_path",
    "attempt_launch_dir",
    "build_attempt_evidence_manifest",
    "read_attempt_evidence_manifest",
    "redacted_attempt_evidence",
    "write_attempt_evidence_manifest",
]
