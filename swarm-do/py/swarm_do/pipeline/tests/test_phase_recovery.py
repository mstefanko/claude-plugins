from __future__ import annotations

import json
import socket
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from swarm_do.pipeline.phase_recovery import reconcile_phase_sessions
from swarm_do.pipeline.phase_sessions import (
    claim_next_phase,
    init_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    phase_status,
    start_phase,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseRecoveryTests(unittest.TestCase):
    def test_expired_lease_without_artifacts_becomes_retryable_with_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _patch_phase(data, run_id, {"lease_expires_at": "2026-01-01T00:00:00Z"})

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "ready")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "pending")
            self.assertEqual(phase["last_failure_kind"], "lease_expired_no_artifacts")
            self.assertEqual(phase["attempt_history"][0]["retry_decision"], "retry")

    def test_active_lease_without_child_liveness_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "active")
            self.assertEqual(phase_status(run_id, data_dir=data, repo_root=repo)["phases"][0]["status"], "running")

    def test_same_host_dead_child_liveness_allows_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 99999999})

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "ready")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["last_failure_kind"], "child_process_dead_no_artifacts")

    def test_retry_after_is_clamped_and_sets_retry_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="failed", retryable=True, retry_after_seconds=9999)

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "retry_waiting")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "retry_waiting")
            self.assertEqual(phase["attempt_history"][0]["retry_after_seconds"], 1800)
            self.assertEqual(Path(phase["attempt_history"][0]["result_path"]).resolve(strict=False), result_path.resolve(strict=False))

    def test_dry_run_reports_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _patch_phase(data, run_id, {"lease_expires_at": "2026-01-01T00:00:00Z"})

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
                dry_run=True,
            )

            self.assertEqual(result["actions"][0]["action"], "retry_ready")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["status"], "running")

    def test_worktree_baseline_excludes_preexisting_dirty_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            (repo / "preexisting.tmp").write_text("already dirty\n", encoding="utf-8")
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            (repo / "new.tmp").write_text("new dirty\n", encoding="utf-8")
            _patch_phase(data, run_id, {"lease_expires_at": "2026-01-01T00:00:00Z"})

            reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            changed = state["phases"][0]["attempt_history"][0]["changed_files"]
            self.assertIn("new.tmp", changed)
            self.assertNotIn("preexisting.tmp", changed)


def _patch_phase(data: Path, run_id: str, updates: dict) -> None:
    path = phase_session_path(run_id, data_dir=data)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["phases"][0].update(updates)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_result(
    data: Path,
    run_id: str,
    phase: dict,
    *,
    status: str,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
) -> Path:
    phase_id = phase["phase_id"]
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data)
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
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
        "do_not_retry": [],
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
        "blocked_reason": None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": {"message": status} if status == "failed" else None,
        "retryable": retryable,
        "failure_kind": "test_retryable_failed" if retryable else "test_failed",
        "retry_after_seconds": retry_after_seconds,
    }
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result_path


if __name__ == "__main__":
    unittest.main()
