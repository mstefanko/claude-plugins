from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.domain import PhaseStatusReport
from swarm_do.pipeline.phase_sessions import init_phase_sessions, phase_status
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseStatusContractTests(unittest.TestCase):
    def test_phase_status_output_parses_as_domain_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            payload = phase_status(run_id, data_dir=data, repo_root=repo)
            report = PhaseStatusReport.from_mapping(payload)

            self.assertIs(report.validate(), report)
            self.assertEqual(report.to_dict(), payload)
            self.assertEqual(report.phases[0].phase_id, "1")

    def test_phase_status_report_preserves_future_mirror_columns(self) -> None:
        payload = {
            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "status": "ready",
            "phases": [
                {
                    "phase_id": "1",
                    "status": "pending",
                    "attempt": 0,
                    "future_phase_column": "kept",
                }
            ],
            "future_report_column": "kept",
        }

        report = PhaseStatusReport.from_mapping(payload)

        self.assertEqual(report.extra["future_report_column"], "kept")
        self.assertEqual(report.phases[0].extra["future_phase_column"], "kept")
        self.assertEqual(report.to_dict(), payload)


if __name__ == "__main__":
    unittest.main()
