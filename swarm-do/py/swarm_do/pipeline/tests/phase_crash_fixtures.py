from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swarm_do.pipeline.phase_sessions import (
    claim_next_phase,
    init_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    start_phase,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


CRASH_NOW = datetime(2026, 4, 29, tzinfo=UTC)
EXPIRED_LEASE = "2026-01-01T00:00:00Z"
FUTURE_LEASE = "2026-12-01T00:00:00Z"


def prepared_active_attempt(tmp: Path, *, phase_count: int = 1) -> tuple[Path, Path, str, dict[str, Any]]:
    repo, data, run_id = make_prepared_run(tmp, phase_count=phase_count)
    init_phase_sessions(run_id, data_dir=data, repo_root=repo)
    claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
    started = start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
    return repo, data, run_id, dict(started["phase"])


def load_state(data: Path, run_id: str) -> dict[str, Any]:
    return json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))


def patch_phase(data: Path, run_id: str, updates: dict[str, Any], *, index: int = 0) -> None:
    path = phase_session_path(run_id, data_dir=data)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["phases"][index].update(updates)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_command(data: Path, run_id: str, phase_id: str, attempt: int, payload: dict[str, Any]) -> Path:
    path = data / "runs" / run_id / "phase_launches" / phase_id / f"attempt-{attempt}" / "command.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_partial_invalid_artifact(data: Path, run_id: str, phase: dict[str, Any]) -> Path:
    result_path = phase_result_path(run_id, str(phase["phase_id"]), int(phase["attempt"]), data_dir=data)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"not": "a phase result"}\n', encoding="utf-8")
    return result_path


def write_result(
    data: Path,
    run_id: str,
    phase: dict[str, Any],
    *,
    status: str,
    retryable: bool = False,
    do_not_retry: bool = False,
) -> Path:
    phase_id = str(phase["phase_id"])
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data)
    state = load_state(data, run_id)
    prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    phase_sha = next(item["content_sha"] for item in prepared["phase_map"] if item["phase_id"] == phase_id)
    now = "2026-04-29T00:00:00Z"
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": status,
        "decisions": [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [],
        "do_not_retry": ["fixture requested no retry"] if do_not_retry else [],
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
        "launcher": "claude-print",
        "session_name": phase["session_name"],
        "prepared_plan_sha": state["prepared_plan_sha"],
        "phase_content_sha": phase_sha,
        "started_at": phase["started_at"],
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": status,
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": "fixture_blocked" if status == "blocked" else None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": {"message": status} if status == "failed" else None,
    }
    if status == "failed":
        result["retryable"] = retryable
        result["failure_kind"] = "fixture_retryable_failed" if retryable else "fixture_failed"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result_path
