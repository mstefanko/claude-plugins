from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.phase_recovery import reconcile_phase_sessions
from swarm_do.pipeline.phase_sessions import phase_session_path
from swarm_do.pipeline.tests.phase_crash_fixtures import (
    CRASH_NOW,
    EXPIRED_LEASE,
    FUTURE_LEASE,
    load_state,
    patch_phase,
    prepared_active_attempt,
    write_partial_invalid_artifact,
    write_result,
)


class PhaseCrashResumeMatrixTests(unittest.TestCase):
    def test_parent_death_complete_artifacts_adopts_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=2)
            write_result(data, run_id, phase, status="complete")

            first = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            second = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(first["status"], "ready")
            state = load_state(data, run_id)
            self.assertEqual(state["phases"][0]["status"], "complete")
            self.assertEqual(state["phases"][1]["status"], "pending")
            self.assertEqual(len(state["phases"][0]["attempt_history"]), 1)
            self.assertEqual(second["actions"], [])

    def test_parent_death_blocked_artifacts_adopts_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=1)
            write_result(data, run_id, phase, status="blocked")

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "blocked")
            state = load_state(data, run_id)
            self.assertEqual(state["phases"][0]["status"], "blocked")
            self.assertEqual(state["phases"][0]["blocked_reason"], "child_reported_blocked")
            self.assertEqual(len(state["phases"][0]["attempt_history"]), 1)

    def test_parent_death_retryable_failed_artifacts_uses_policy_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=1)
            write_result(data, run_id, phase, status="failed", retryable=True)

            first = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            second = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(first["status"], "retry_waiting")
            self.assertEqual(second["status"], "retry_waiting")
            state = load_state(data, run_id)
            self.assertEqual(len(state["phases"][0]["attempt_history"]), 1)
            self.assertEqual(state["phases"][0]["attempt_history"][0]["failure_kind"], "fixture_retryable_failed")

    def test_nonzero_launcher_with_valid_artifacts_adopts_with_launcher_failure_kind(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=1)
            write_result(data, run_id, phase, status="complete")

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 1, "stdout": "", "stderr": "late failure"},
                now=CRASH_NOW,
            )

            self.assertEqual(result["status"], "complete")
            state = load_state(data, run_id)
            self.assertEqual(state["phases"][0]["attempt_history"][0]["failure_kind"], "launcher_nonzero_with_artifacts")

    def test_child_dead_no_artifacts_records_retryable_lifecycle_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 12345, "lease_expires_at": FUTURE_LEASE})

            with mock.patch("swarm_do.pipeline.phase_recovery._pid_alive", return_value=False):
                result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "retry_waiting")
            self.assertEqual(result["actions"][0]["active_attempt_action"], "child_dead")
            state = load_state(data, run_id)
            history = state["phases"][0]["attempt_history"][0]
            self.assertEqual(history["failure_kind"], "child_process_dead_no_artifacts")
            self.assertEqual(history["failure_category"], "lifecycle")

    def test_child_dead_partial_artifacts_uses_recovery_retry_or_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=1)
            write_partial_invalid_artifact(data, run_id, phase)
            patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 12345, "lease_expires_at": FUTURE_LEASE})

            with mock.patch("swarm_do.pipeline.phase_recovery._pid_alive", return_value=False):
                result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertIn(result["status"], {"retry_waiting", "blocked"})
            state = load_state(data, run_id)
            history = state["phases"][0]["attempt_history"][0]
            self.assertTrue(history["partial_artifacts"])
            self.assertEqual(history["failure_kind"], "child_process_dead_no_artifacts")

    def test_zero_returncode_no_artifacts_human_gates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            stdout = json.dumps({"type": "result", "result": "{}"})

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 0, "stdout": stdout, "stderr": ""},
                now=CRASH_NOW,
            )

            self.assertEqual(result["status"], "blocked")
            state = load_state(data, run_id)
            self.assertEqual(state["phases"][0]["retry_policy_decision"], "deterministic_contract_failure")

    def test_expired_same_host_live_child_preserves_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 12345, "lease_expires_at": EXPIRED_LEASE})

            with mock.patch("swarm_do.pipeline.phase_recovery._pid_alive", return_value=True):
                result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "active")
            self.assertEqual(result["actions"][0]["action"], "active_preserved_child_alive")
            self.assertTrue(result["actions"][0]["lease_expired"])
            self.assertEqual(load_state(data, run_id)["phases"][0]["attempt_history"], [])

    def test_same_host_live_child_unknown_process_group_preserves_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(
                data,
                run_id,
                {
                    "lease_host": socket.gethostname(),
                    "child_pid": 12345,
                    "process_group_id": 999,
                    "lease_expires_at": EXPIRED_LEASE,
                },
            )

            with mock.patch("swarm_do.pipeline.phase_recovery._pid_alive", return_value=True), mock.patch(
                "swarm_do.pipeline.phase_recovery._process_group_matches",
                return_value=None,
            ):
                result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "active")
            self.assertEqual(result["actions"][0]["action"], "active_preserved_child_unknown")
            self.assertEqual(load_state(data, run_id)["phases"][0]["attempt_history"], [])

    def test_expired_same_host_unknown_child_liveness_recovers_by_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 12345, "lease_expires_at": EXPIRED_LEASE})

            with mock.patch("swarm_do.pipeline.phase_recovery._pid_alive", return_value=None):
                result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "retry_waiting")
            self.assertEqual(result["actions"][0]["active_attempt_action"], "lease_expired")
            self.assertEqual(load_state(data, run_id)["phases"][0]["last_failure_kind"], "lease_expired_no_artifacts")

    def test_expired_cross_host_active_lease_recovers_by_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_host": "other-host", "child_pid": 12345, "lease_expires_at": EXPIRED_LEASE})

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "retry_waiting")
            self.assertEqual(result["actions"][0]["active_attempt_action"], "lease_expired_cross_host")
            self.assertEqual(load_state(data, run_id)["phases"][0]["last_failure_kind"], "lease_expired_no_artifacts")

    def test_unexpired_cross_host_active_lease_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_host": "other-host", "child_pid": 12345, "lease_expires_at": FUTURE_LEASE})

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "active")
            self.assertEqual(result["actions"][0]["action"], "active_preserved_cross_host")
            self.assertEqual(load_state(data, run_id)["phases"][0]["attempt_history"], [])

    def test_retry_waiting_future_reports_wait_without_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(
                data,
                run_id,
                {
                    "status": "retry_waiting",
                    "next_retry_at": "2026-04-29T00:10:00Z",
                    "last_failure_kind": "lease_expired_no_artifacts",
                },
            )
            before = phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8")

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "retry_waiting")
            self.assertEqual(result["actions"][0]["action"], "retry_waiting")
            self.assertEqual(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"), before)

    def test_retry_waiting_past_due_releases_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(
                data,
                run_id,
                {
                    "status": "retry_waiting",
                    "next_retry_at": "2026-04-28T00:00:00Z",
                    "last_failure_kind": "lease_expired_no_artifacts",
                },
            )

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)

            self.assertEqual(result["status"], "ready")
            state = load_state(data, run_id)
            self.assertEqual(state["phases"][0]["status"], "pending")
            self.assertEqual(result["actions"][0]["action"], "retry_ready")

    def test_recover_dry_run_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_expires_at": EXPIRED_LEASE})
            before = phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8")

            result = reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW, dry_run=True)

            self.assertEqual(result["status"], "retry_waiting")
            self.assertEqual(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"), before)

    def test_recovery_after_retry_decision_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, _phase = prepared_active_attempt(Path(td), phase_count=1)
            patch_phase(data, run_id, {"lease_expires_at": EXPIRED_LEASE})

            reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            first = load_state(data, run_id)
            reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            second = load_state(data, run_id)

            self.assertEqual(len(first["phases"][0]["attempt_history"]), 1)
            self.assertEqual(len(second["phases"][0]["attempt_history"]), 1)

    def test_recovery_after_artifact_adoption_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id, phase = prepared_active_attempt(Path(td), phase_count=1)
            write_result(data, run_id, phase, status="complete")

            reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            first = load_state(data, run_id)
            reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=CRASH_NOW)
            second = load_state(data, run_id)

            self.assertEqual(first["phases"][0]["status"], "complete")
            self.assertEqual(len(first["phases"][0]["attempt_history"]), 1)
            self.assertEqual(len(second["phases"][0]["attempt_history"]), 1)


if __name__ == "__main__":
    unittest.main()
