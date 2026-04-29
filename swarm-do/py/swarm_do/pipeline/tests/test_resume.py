from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.resume import (
    COMPLETE,
    DRIFT_DETECTED,
    NOT_FOUND,
    READY_TO_RESUME,
    build_resume_report,
    resume_exit_code,
)
from swarm_do.pipeline.run_state import active_run_path, load_active_run, write_active_run, write_checkpoint_from_active


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class ResumeTests(unittest.TestCase):
    def test_missing_run_event_is_not_found(self) -> None:
        with isolated_data_dir():
            report = build_resume_report("swarm-123")
            self.assertIsNone(report.run_id)
            self.assertEqual(report.status, "not-found")
            self.assertEqual(resume_exit_code(report), NOT_FOUND)

    def test_context_overflow_interrupted_run_resumes_first_incomplete_unit(self) -> None:
        with isolated_data_dir() as root:
            write_event(root, {"run_id": RUN_ID, "bd_epic_id": "swarm-123", "event_type": "checkpoint_written"})
            write_checkpoint(
                root,
                {
                    "bd_epic_id": "swarm-123",
                    "phase_id": "writer",
                    "work_units": [
                        {"id": "unit-1", "status": "complete"},
                        {"id": "unit-2", "status": "incomplete"},
                    ],
                    "child_bead_ids": ["bd-a", "bd-b"],
                    "status": "incomplete",
                },
            )
            report = build_resume_report("swarm-123")
            self.assertEqual(report.status, "ready")
            self.assertEqual(report.resume_from, {"phase_id": "writer", "work_unit_id": "unit-2"})
            self.assertEqual(report.completed_units, ["unit-1"])
            self.assertEqual(resume_exit_code(report), READY_TO_RESUME)

    def test_usage_limit_interruption_can_resume_from_valid_run_event_without_checkpoint(self) -> None:
        with isolated_data_dir() as root:
            write_event(
                root,
                {
                    "run_id": RUN_ID,
                    "bd_epic_id": "swarm-123",
                    "event_type": "retry_started",
                    "phase_id": "writer",
                    "work_unit_id": "unit-3",
                },
            )
            report = build_resume_report("swarm-123")
            self.assertEqual(report.status, "ready")
            self.assertEqual(report.checkpoint_path, None)
            self.assertEqual(report.resume_from, {"phase_id": "writer", "work_unit_id": "unit-3"})

    def test_operator_ctrl_c_with_partial_run_events_is_ready_not_drift(self) -> None:
        with isolated_data_dir() as root:
            write_event(root, {"run_id": RUN_ID, "bd_epic_id": "swarm-123", "event_type": "retry_started"})
            report = build_resume_report("swarm-123")
            self.assertEqual(report.status, "ready")
            self.assertEqual(report.drift_keys, [])

    def test_checkpoint_epic_mismatch_is_drift(self) -> None:
        with isolated_data_dir() as root:
            write_event(root, {"run_id": RUN_ID, "bd_epic_id": "swarm-123"})
            write_checkpoint(root, {"bd_epic_id": "other"})
            report = build_resume_report("swarm-123")
            self.assertEqual(report.drift_keys, ["bd_epic_id"])
            self.assertEqual(resume_exit_code(report), DRIFT_DETECTED)

    def test_checkpoint_child_bead_mismatch_is_drift(self) -> None:
        with isolated_data_dir() as root:
            write_event(root, {"run_id": RUN_ID, "bd_epic_id": "swarm-123", "child_bead_ids": ["bd-a"]})
            write_checkpoint(root, {"bd_epic_id": "swarm-123", "child_bead_ids": ["bd-b"]})
            report = build_resume_report("swarm-123")
            self.assertEqual(report.drift_keys, ["child_bead_ids"])
            self.assertEqual(report.status, "drift")

    def test_already_complete_run_is_distinct_noop(self) -> None:
        with isolated_data_dir() as root:
            write_event(root, {"run_id": RUN_ID, "bd_epic_id": "swarm-123", "event_type": "checkpoint_written"})
            write_checkpoint(
                root,
                {
                    "bd_epic_id": "swarm-123",
                    "phase_id": "review",
                    "work_units": [{"id": "unit-1", "status": "approved"}],
                    "status": "complete",
                },
            )
            report = build_resume_report("swarm-123")
            self.assertEqual(report.status, "complete")
            self.assertIsNone(report.resume_from)
            self.assertEqual(resume_exit_code(report), COMPLETE)

    def test_prepared_run_can_resume_from_index_without_run_event(self) -> None:
        with isolated_data_dir() as root:
            run_dir = root / "runs" / RUN_ID
            run_dir.mkdir(parents=True)
            payload = {
                "run_id": RUN_ID,
                "bd_epic_id": "swarm-123",
                "status": "prepared",
                "plan_path": "plan.md",
            }
            (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
            with (root / "runs" / "index.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
            report = build_resume_report("swarm-123")
            self.assertEqual(report.status, "prepared")
            self.assertEqual(report.resume_from, {"phase_id": "plan-prepare", "work_unit_id": None})
            self.assertEqual(resume_exit_code(report), READY_TO_RESUME)

    def test_accepted_prepared_artifact_without_dispatch_event_reports_prepared(self) -> None:
        with isolated_data_dir() as root:
            run_dir = root / "runs" / RUN_ID
            run_dir.mkdir(parents=True)
            artifact_path = run_dir / "prepared_plan.v1.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "run_id": RUN_ID,
                        "status": "accepted",
                        "prepared_plan_path": "data/runs/accepted/prepared.md",
                    }
                ),
                encoding="utf-8",
            )
            index_row = {
                "run_id": RUN_ID,
                "bd_epic_id": "swarm-123",
                "status": "accepted",
                "prepared_artifact_path": str(artifact_path),
            }
            with (root / "runs" / "index.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps(index_row) + "\n")

            report = build_resume_report("swarm-123")

            self.assertEqual(report.status, "prepared")
            self.assertEqual(report.checkpoint_path, artifact_path)
            self.assertEqual(report.resume_from, {"phase_id": "plan-prepare", "work_unit_id": None})
            self.assertEqual(resume_exit_code(report), READY_TO_RESUME)

    def test_accepted_prepared_artifact_with_dispatch_event_is_ready(self) -> None:
        with isolated_data_dir() as root:
            run_dir = root / "runs" / RUN_ID
            run_dir.mkdir(parents=True)
            artifact_path = run_dir / "prepared_plan.v1.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "run_id": RUN_ID,
                        "status": "accepted",
                        "prepared_plan_path": "data/runs/accepted/prepared.md",
                    }
                ),
                encoding="utf-8",
            )
            index_row = {
                "run_id": RUN_ID,
                "bd_epic_id": "swarm-123",
                "status": "accepted",
                "prepared_artifact_path": str(artifact_path),
            }
            with (root / "runs" / "index.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps(index_row) + "\n")
            write_event(
                root,
                {
                    "run_id": RUN_ID,
                    "bd_epic_id": "swarm-123",
                    "event_type": "prepare_dispatch_started",
                    "phase_id": "plan-prepare",
                },
            )

            report = build_resume_report("swarm-123")

            self.assertEqual(report.status, "ready")
            self.assertEqual(report.resume_from, {"phase_id": "plan-prepare", "work_unit_id": None})

    def test_initialized_phase_session_is_reported_read_only(self) -> None:
        with isolated_data_dir() as root:
            run_dir = root / "runs" / RUN_ID
            run_dir.mkdir(parents=True)
            artifact_path = run_dir / "prepared_plan.v1.json"
            artifact_path.write_text(
                json.dumps({"run_id": RUN_ID, "status": "accepted"}),
                encoding="utf-8",
            )
            state = {
                "schema_version": 1,
                "run_id": RUN_ID,
                "prepared_artifact_path": str(artifact_path),
                "prepared_plan_sha": "a" * 64,
                "created_at": "2026-04-29T00:00:00Z",
                "updated_at": "2026-04-29T00:00:00Z",
                "mode": "cli-pump",
                "lease_policy": {
                    "claim_ttl_seconds": 900,
                    "running_ttl_seconds": 14400,
                    "refresh_interval_seconds": 300,
                },
                "phases": [
                    {
                        "phase_id": "1",
                        "phase_index": 0,
                        "title": "One",
                        "depends_on_phase_ids": [],
                        "status": "pending",
                        "lease_owner": None,
                        "lease_host": None,
                        "lease_pid": None,
                        "lease_command": None,
                        "lease_expires_at": None,
                        "attempt": 0,
                        "session_name": None,
                        "started_at": None,
                        "completed_at": None,
                        "result_path": None,
                        "handoff_path": None,
                        "last_error": None,
                    }
                ],
            }
            (run_dir / "phase_sessions.v1.json").write_text(json.dumps(state), encoding="utf-8")
            index_row = {
                "run_id": RUN_ID,
                "bd_epic_id": "swarm-123",
                "status": "accepted",
                "prepared_artifact_path": str(artifact_path),
            }
            with (root / "runs" / "index.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps(index_row) + "\n")

            report = build_resume_report("swarm-123")

            self.assertEqual(report.status, "ready")
            self.assertEqual(report.resume_from, {"phase_id": "1", "work_unit_id": None})
            self.assertEqual(report.phase_session["status"], "ready")

    def test_retry_waiting_phase_session_is_reported_read_only(self) -> None:
        with isolated_data_dir() as root:
            run_dir = root / "runs" / RUN_ID
            run_dir.mkdir(parents=True)
            artifact_path = run_dir / "prepared_plan.v1.json"
            artifact_path.write_text(
                json.dumps({"run_id": RUN_ID, "status": "accepted"}),
                encoding="utf-8",
            )
            state = {
                "schema_version": 1,
                "run_id": RUN_ID,
                "prepared_artifact_path": str(artifact_path),
                "prepared_plan_sha": "a" * 64,
                "created_at": "2026-04-29T00:00:00Z",
                "updated_at": "2026-04-29T00:00:00Z",
                "mode": "cli-pump",
                "lease_policy": {
                    "claim_ttl_seconds": 900,
                    "running_ttl_seconds": 14400,
                    "refresh_interval_seconds": 300,
                },
                "retry_policy": {
                    "max_session_attempts": 3,
                    "max_recovery_attempts": 1,
                    "recovery_timeout_threshold_seconds": 600,
                    "retry_sleep_threshold_seconds": 60,
                    "short_retry_backoff_seconds": 0,
                    "max_retry_after_seconds": 1800,
                    "worktree_baseline_path": None,
                    "worktree_baseline_warning": None,
                },
                "phases": [
                    {
                        "phase_id": "1",
                        "phase_index": 0,
                        "title": "One",
                        "depends_on_phase_ids": [],
                        "status": "retry_waiting",
                        "lease_owner": None,
                        "lease_host": None,
                        "lease_pid": None,
                        "lease_command": None,
                        "lease_expires_at": None,
                        "attempt": 1,
                        "session_name": "s",
                        "started_at": "2026-04-29T00:00:00Z",
                        "completed_at": None,
                        "result_path": None,
                        "handoff_path": None,
                        "last_error": "rate_limit",
                        "next_retry_at": "2026-04-29T01:00:00Z",
                        "last_failure_kind": "rate_limit",
                        "last_launcher_error": "rate_limit",
                        "attempt_history": [],
                    }
                ],
            }
            (run_dir / "phase_sessions.v1.json").write_text(json.dumps(state), encoding="utf-8")
            with (root / "runs" / "index.jsonl").open("w", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "run_id": RUN_ID,
                            "bd_epic_id": "swarm-123",
                            "status": "accepted",
                            "prepared_artifact_path": str(artifact_path),
                        }
                    )
                    + "\n"
                )

            report = build_resume_report("swarm-123")

            self.assertEqual(report.status, "ready")
            self.assertEqual(report.phase_session["status"], "retry_waiting")
            self.assertEqual(report.resume_from, {"phase_id": "1", "work_unit_id": None})


class RunStateTests(unittest.TestCase):
    def test_active_run_write_and_checkpoint_round_trip(self) -> None:
        with isolated_data_dir() as root:
            state = {
                "run_id": RUN_ID,
                "bd_epic_id": "swarm-123",
                "phase_id": "writer",
                "work_units": [{"id": "unit-1", "status": "incomplete"}],
            }
            path = write_active_run(active_run_path(root), state)
            loaded = load_active_run(path)
            self.assertIsNotNone(loaded)
            checkpoint = write_checkpoint_from_active(root, loaded or {}, source="test", reason="unit")
            self.assertTrue(checkpoint and checkpoint.is_file())
            events = (root / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("checkpoint_written", events)


def write_event(root: Path, row: dict) -> None:
    telemetry = root / "telemetry"
    telemetry.mkdir(exist_ok=True)
    payload = {
        "run_id": RUN_ID,
        "timestamp": "2026-04-24T00:00:00Z",
        "event_type": "checkpoint_written",
        "schema_ok": True,
    }
    payload.update(row)
    with (telemetry / "run_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def write_checkpoint(root: Path, payload: dict) -> None:
    checkpoint_dir = root / "runs" / RUN_ID
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "checkpoint.v1.json").write_text(json.dumps(payload), encoding="utf-8")


class isolated_data_dir:
    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = self.tmp.name
        return Path(self.tmp.name)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.old is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self.old
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
