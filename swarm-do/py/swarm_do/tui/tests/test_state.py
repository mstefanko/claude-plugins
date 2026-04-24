from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.tui.actions import set_base_route
from swarm_do.tui.state import load_in_flight, status_summary, token_burn_last_24h


class EnvTestCase(unittest.TestCase):
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


class TuiStateTests(EnvTestCase):
    def test_status_summary_renders_na_for_unobserved_cost_and_429(self) -> None:
        tel = self.root / "telemetry"
        tel.mkdir()
        (tel / "runs.jsonl").write_text(
            json.dumps(
                {
                    "timestamp_start": "2026-04-24T12:00:00Z",
                    "backend": "claude",
                    "estimated_cost_usd": None,
                    "last_429_at": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        summary = status_summary(now=datetime(2026, 4, 24, 13, tzinfo=UTC))
        rendered = summary.render()
        self.assertIn("runs_today=1", rendered)
        self.assertIn("cost_today=n/a", rendered)
        self.assertIn("last_429_claude=n/a", rendered)

    def test_token_burn_keeps_backend_na_when_tokens_are_null(self) -> None:
        rows = [
            {
                "timestamp_start": "2026-04-24T12:00:00Z",
                "backend": "codex",
                "input_tokens": None,
                "output_tokens": None,
            }
        ]
        burn = token_burn_last_24h(rows, now=datetime(2026, 4, 24, 13, tzinfo=UTC))
        self.assertIsNone(burn["codex"])

    def test_in_flight_lockfiles_load(self) -> None:
        locks = self.root / "in-flight"
        locks.mkdir()
        (locks / "bd-abc.lock").write_text(
            json.dumps(
                {
                    "issue_id": "abc",
                    "role": "agent-writer",
                    "backend": "claude",
                    "model": "claude-opus-4-7",
                    "effort": "high",
                    "pid": 123,
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )
        runs = load_in_flight()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].issue_id, "abc")
        self.assertEqual(runs[0].display_pid, "123")


class TuiActionTests(EnvTestCase):
    def test_config_hash_changes_when_backends_toml_changes(self) -> None:
        before = active_config_hash()
        set_base_route("agent-docs", None, "codex", "gpt-5.4-mini", "medium")
        after = active_config_hash()
        self.assertNotEqual(before, after)

    def test_invariant_rejects_orchestrator_to_codex(self) -> None:
        with self.assertRaisesRegex(ValueError, "orchestrator"):
            set_base_route("orchestrator", None, "codex", "gpt-5.4", "high")


if __name__ == "__main__":
    unittest.main()
