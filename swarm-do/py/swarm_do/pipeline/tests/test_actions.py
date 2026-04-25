from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.actions import load_in_flight, request_handoff, validate_preset_name


class PipelineActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.td.name

    def tearDown(self) -> None:
        self.td.cleanup()
        if self._old_data is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_data

    @property
    def root(self) -> Path:
        return Path(self.td.name)

    def test_request_handoff_writes_in_flight_lock(self) -> None:
        path = request_handoff("123", "codex")

        self.assertEqual(path, self.root / "in-flight" / "bd-123.lock")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "handoff-requested")
        self.assertEqual(payload["requested_backend"], "codex")

    def test_request_handoff_refuses_corrupt_lockfile(self) -> None:
        lock_dir = self.root / "in-flight"
        lock_dir.mkdir()
        lock = lock_dir / "bd-123.lock"
        lock.write_text("{not json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            request_handoff("123", "codex")
        self.assertEqual(lock.read_text(encoding="utf-8"), "{not json")

    def test_load_in_flight_round_trips_lockfile(self) -> None:
        lock_dir = self.root / "in-flight"
        lock_dir.mkdir()
        (lock_dir / "bd-123.lock").write_text(
            json.dumps(
                {
                    "issue_id": "123",
                    "role": "agent-writer",
                    "backend": "claude",
                    "model": "claude-opus-4-7",
                    "effort": "high",
                    "pid": 42,
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )

        runs = load_in_flight()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].issue_id, "123")
        self.assertEqual(runs[0].display_pid, "42")

    def test_validate_preset_name_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "preset name"):
            validate_preset_name("../escape")


if __name__ == "__main__":
    unittest.main()
