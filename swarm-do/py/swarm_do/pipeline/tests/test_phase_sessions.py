from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.phase_sessions import (
    PhaseSessionError,
    claim_next_phase,
    init_phase_sessions,
    load_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    phase_status,
    reap_expired_phases,
    record_phase_result,
    start_phase,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseSessionTests(unittest.TestCase):
    def test_status_reports_not_initialized_for_accepted_prepared_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["status"], "not_initialized")
            self.assertIn("phases init", status["recommended_command"])

    def test_init_copies_exact_phase_ids_and_sequential_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            result = init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            phases = result["state"]["phases"]
            self.assertEqual([phase["phase_id"] for phase in phases], ["1", "2", "3"])
            self.assertEqual(phases[0]["depends_on_phase_ids"], [])
            self.assertEqual(phases[1]["depends_on_phase_ids"], ["1"])
            self.assertEqual(phases[2]["depends_on_phase_ids"], ["2"])

    def test_claim_start_complete_then_claims_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            self.assertTrue(claim["claimed"])
            self.assertEqual(claim["phase"]["phase_id"], "1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)
            self.assertEqual(recorded["phase"]["status"], "complete")

            claim2 = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-2")
            self.assertTrue(claim2["claimed"])
            self.assertEqual(claim2["phase"]["phase_id"], "2")

    def test_completion_requires_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            phase_handoff_path(run_id, "1", int(started["phase"]["attempt"]), data_dir=data).unlink()
            with self.assertRaises(PhaseSessionError):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_reap_marks_expired_lease_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["phases"][0]["lease_expires_at"] = "2026-01-01T00:00:00Z"
            path.write_text(json.dumps(state), encoding="utf-8")

            result = reap_expired_phases(run_id, data_dir=data)
            self.assertEqual(result["reaped"][0]["status"], "stale")
            self.assertEqual(load_phase_sessions(run_id, data_dir=data)["phases"][0]["status"], "stale")


def _write_result(data: Path, run_id: str, phase: dict, *, status: str) -> Path:
    phase_id = phase["phase_id"]
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data)
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
    prepared_sha = state["prepared_plan_sha"]
    phase_sha = "0" * 64
    prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    for item in prepared["phase_map"]:
        if item["phase_id"] == phase_id:
            phase_sha = item["content_sha"]
            break
    now = "2026-04-29T00:00:00Z"
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": "done",
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
        "launcher": "manual",
        "session_name": phase["session_name"],
        "prepared_plan_sha": prepared_sha,
        "phase_content_sha": phase_sha,
        "started_at": phase["started_at"],
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": "done",
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": None,
    }
    handoff_path.parent.mkdir(parents=True)
    result_path.parent.mkdir(parents=True)
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path


if __name__ == "__main__":
    unittest.main()
