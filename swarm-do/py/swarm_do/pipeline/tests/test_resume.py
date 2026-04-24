from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.resume import DRIFT_DETECTED, NOTHING_TO_RESUME, build_resume_report, resume_exit_code


class ResumeTests(unittest.TestCase):
    def test_missing_run_event_is_nothing_to_resume(self) -> None:
        with isolated_data_dir():
            report = build_resume_report("swarm-123")
            self.assertIsNone(report.run_id)
            self.assertEqual(resume_exit_code(report), NOTHING_TO_RESUME)

    def test_run_event_maps_epic_to_checkpoint(self) -> None:
        with isolated_data_dir() as root:
            run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
            telemetry = root / "telemetry"
            telemetry.mkdir()
            (telemetry / "run_events.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "timestamp": "2026-04-24T00:00:00Z",
                        "event_type": "checkpoint_written",
                        "bd_epic_id": "swarm-123",
                        "schema_ok": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            checkpoint_dir = root / "runs" / run_id
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "checkpoint.v1.json").write_text(
                json.dumps({"bd_epic_id": "swarm-123", "work_units": []}),
                encoding="utf-8",
            )
            report = build_resume_report("swarm-123")
            self.assertEqual(report.run_id, run_id)
            self.assertEqual(report.drift_keys, [])

    def test_checkpoint_epic_mismatch_is_drift(self) -> None:
        with isolated_data_dir() as root:
            run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
            (root / "telemetry").mkdir()
            (root / "telemetry" / "run_events.jsonl").write_text(
                json.dumps({"run_id": run_id, "bd_epic_id": "swarm-123"}) + "\n",
                encoding="utf-8",
            )
            checkpoint_dir = root / "runs" / run_id
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "checkpoint.v1.json").write_text(
                json.dumps({"bd_epic_id": "other"}),
                encoding="utf-8",
            )
            report = build_resume_report("swarm-123")
            self.assertEqual(report.drift_keys, ["bd_epic_id"])
            self.assertEqual(resume_exit_code(report), DRIFT_DETECTED)


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
