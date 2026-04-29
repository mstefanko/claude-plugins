from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_sessions import init_phase_sessions, phase_status
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhasePumpTests(unittest.TestCase):
    def test_fake_test_completes_three_phase_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["completed_phases"]), 3)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["status"], "complete")

    def test_failed_fake_phase_stops_with_resume_point(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, fake_statuses=["failed"], data_dir=data)

            self.assertEqual(result["status"], "failed")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "failed")
            self.assertEqual(status["phases"][1]["status"], "pending")

    def test_manual_launcher_returns_prompt_and_followup_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="manual", max_phases=1, data_dir=data)

            self.assertEqual(result["status"], "manual_waiting")
            self.assertTrue(Path(result["manual"]["prompt_path"]).is_file())
            self.assertIn("phases complete", result["manual"]["follow_up_command"])


if __name__ == "__main__":
    unittest.main()
