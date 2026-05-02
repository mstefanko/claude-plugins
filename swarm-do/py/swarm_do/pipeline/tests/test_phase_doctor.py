from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.pipeline.phase_doctor import format_phase_doctor, run_phase_doctor


class PhaseDoctorContractTests(unittest.TestCase):
    def test_doctor_ranks_typed_findings_before_formatting(self) -> None:
        def probe(_run_id: str, _data_dir: Path, _repo_root: Path | None) -> list[dict]:
            return [
                {
                    "id": "later_info",
                    "severity": "info",
                    "detail": "minor",
                },
                {
                    "id": "first_error",
                    "severity": "error",
                    "phase_id": "1",
                    "detail": "major",
                    "recommended_command": "bin/swarm phases status run-1",
                },
            ]

        report = run_phase_doctor("run-1", data_dir=Path("/tmp"), probes=[probe])
        formatted = format_phase_doctor(report)

        self.assertEqual(report["status"], "findings")
        self.assertEqual([item["id"] for item in report["findings"]], ["first_error", "later_info"])
        self.assertIn("ERROR first_error phase=1", formatted)
        self.assertIn("next: bin/swarm phases status run-1", formatted)


if __name__ == "__main__":
    unittest.main()
