from __future__ import annotations

import json
import socket
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.claude_transcript_diagnostics import encode_project_path
from swarm_do.pipeline.paths import REPO_ROOT
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

            self.assertEqual(result["status"], "retry_waiting")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "retry_waiting")
            self.assertEqual(phase["attempt_history"][0]["retry_after_seconds"], 60)
            self.assertEqual(phase["last_failure_kind"], "lease_expired_no_artifacts")
            self.assertEqual(phase["attempt_history"][0]["retry_decision"], "retry")
            self.assertEqual(phase["attempt_history"][0]["failure_category"], "lifecycle")
            self.assertEqual(phase["attempt_history"][0]["failure_retry_class"], "retry")
            self.assertTrue(Path(phase["attempt_history"][0]["evidence_path"]).is_file())
            events = _run_events(data)
            retry = [row for row in events if row["event_type"] == "phase_attempt_retry_scheduled"][-1]
            self.assertEqual(retry["details"]["failure_category"], "lifecycle")
            self.assertTrue(Path(retry["details"]["evidence_path"]).is_file())

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

            self.assertEqual(result["status"], "retry_waiting")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["last_failure_kind"], "child_process_dead_no_artifacts")

    def test_same_host_process_group_mismatch_allows_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _patch_phase(data, run_id, {"lease_host": socket.gethostname(), "child_pid": 12345, "process_group_id": 111})

            from unittest import mock

            with mock.patch("swarm_do.pipeline.phase_recovery.os.kill", return_value=None), mock.patch(
                "swarm_do.pipeline.phase_recovery.os.getpgid",
                return_value=222,
            ):
                result = reconcile_phase_sessions(
                    run_id,
                    data_dir=data,
                    repo_root=repo,
                    now=datetime(2026, 4, 29, tzinfo=UTC),
                )

            self.assertEqual(result["status"], "retry_waiting")
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

    def test_same_failure_kind_twice_blocks_instead_of_retry_exhausting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)

            reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 1, "stdout": "", "stderr": "boom"},
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )
            _patch_phase(data, run_id, {"status": "pending", "next_retry_at": None})
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-2")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-2", data_dir=data)

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 1, "stdout": "", "stderr": "boom again"},
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "blocked")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "blocked")
            self.assertEqual(phase["blocked_reason"], "retry_policy_human_gate")
            self.assertEqual(phase["retry_policy_decision"], "same_failure_limit")
            self.assertEqual(phase["last_failure_kind"], "launcher_nonzero_no_artifacts")
            events = _run_events(data)
            self.assertIn("phase_session_blocked", [row["event_type"] for row in events])
            blocked = [row for row in events if row["event_type"] == "phase_session_blocked"][-1]
            self.assertEqual(blocked["reason"], "retry_policy_human_gate")
            self.assertEqual(blocked["details"]["retry_policy_decision"], "same_failure_limit")

    def test_zero_returncode_contract_failure_blocks_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            stdout = json.dumps({"type": "result", "result": "{}"})

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 0, "stdout": stdout, "stderr": ""},
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "blocked")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "blocked")
            self.assertEqual(phase["blocked_reason"], "retry_policy_human_gate")
            self.assertEqual(phase["retry_policy_decision"], "deterministic_contract_failure")
            self.assertEqual(phase["last_failure_kind"], "outer_artifacts_missing")
            self.assertEqual(phase["attempt_history"][0]["failure_category"], "artifact_contract")

    def test_zero_returncode_empty_result_with_turns_blocks_as_silent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _write_command(data, run_id, "1", 1, {"argv": ["claude"], "launcher_cwd": "/tmp/missing"})
            stdout = json.dumps(
                {
                    "type": "result",
                    "session_id": "missing-session",
                    "result": "",
                    "num_turns": 14,
                    "total_cost_usd": 0.73,
                }
            )

            result = reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                launcher_result={"status": "launched", "returncode": 0, "stdout": stdout, "stderr": ""},
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            self.assertEqual(result["status"], "blocked")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["last_failure_kind"], "writer_silent_with_turns")
            self.assertIn("14 turns", phase["last_error"])
            history = phase["attempt_history"][0]
            self.assertEqual(history["failure_kind"], "writer_silent_with_turns")
            self.assertEqual(history["failure_category"], "writer_runtime")
            self.assertEqual(history["transcript_found"], False)
            self.assertTrue(Path(history["transcript_diagnostics_path"]).is_file())
            recovery = Path(history["recovery_context_path"]).read_text(encoding="utf-8")
            self.assertIn("## Transcript Diagnostics", recovery)

    def test_write_disabled_transcript_blocks_as_tool_denied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_home = root / "home"
            projects = fake_home / ".claude" / "projects"
            cwd = "/tmp/swarm-do-launcher"
            session_id = "session-tool-denied"
            transcript = projects / encode_project_path(cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                (REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_transcripts" / "write-disabled.jsonl").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            repo, data, run_id = make_prepared_run(root, phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _write_command(data, run_id, "1", 1, {"argv": ["claude"], "launcher_cwd": cwd})
            stdout = json.dumps({"type": "result", "session_id": session_id, "result": "", "num_turns": 14})

            with mock.patch("swarm_do.pipeline.claude_transcript_diagnostics.Path.home", return_value=fake_home):
                result = reconcile_phase_sessions(
                    run_id,
                    data_dir=data,
                    repo_root=repo,
                    launcher_result={"status": "launched", "returncode": 0, "stdout": stdout, "stderr": ""},
                    now=datetime(2026, 4, 29, tzinfo=UTC),
                )

            self.assertEqual(result["status"], "blocked")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            phase = state["phases"][0]
            self.assertEqual(phase["last_failure_kind"], "writer_tool_denied_no_artifacts")
            self.assertIn("Write tool_disabled", phase["last_error"])
            history = phase["attempt_history"][0]
            self.assertEqual(history["tool_name"], "Write")
            self.assertEqual(history["tool_error_kind"], "tool_disabled")
            self.assertEqual(history["failure_category"], "writer_runtime")
            self.assertTrue(Path(history["transcript_diagnostics_path"]).is_file())

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

            self.assertEqual(result["actions"][0]["action"], "retry_scheduled")
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

    def test_worktree_diff_summary_is_baseline_relative(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            (repo / "seed.txt").write_text("preexisting dirty\n", encoding="utf-8")
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            (repo / "attempt.tmp").write_text("attempt dirt\n", encoding="utf-8")
            _patch_phase(data, run_id, {"lease_expires_at": "2026-01-01T00:00:00Z"})

            reconcile_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                now=datetime(2026, 4, 29, tzinfo=UTC),
            )

            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            summary_path = Path(state["phases"][0]["attempt_history"][0]["diff_summary_path"])
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("attempt.tmp", summary)
            self.assertNotIn("seed.txt", summary)


def _patch_phase(data: Path, run_id: str, updates: dict) -> None:
    path = phase_session_path(run_id, data_dir=data)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["phases"][0].update(updates)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_events(data: Path) -> list[dict]:
    path = data / "telemetry" / "run_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_command(data: Path, run_id: str, phase_id: str, attempt: int, payload: dict) -> Path:
    path = data / "runs" / run_id / "phase_launches" / phase_id / f"attempt-{attempt}" / "command.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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
