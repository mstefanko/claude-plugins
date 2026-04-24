from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.registry import load_preset
from swarm_do.tui.actions import set_base_route, set_user_preset_pipeline, set_user_preset_route
from swarm_do.tui.state import (
    latest_checkpoint_event,
    latest_observation,
    load_in_flight,
    load_observations,
    load_run_events,
    status_summary,
    token_burn_last_24h,
)


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

    def test_run_events_and_observations_are_structured(self) -> None:
        tel = self.root / "telemetry"
        tel.mkdir()
        (tel / "run_events.jsonl").write_text(
            json.dumps(
                {
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "timestamp": "2026-04-24T12:00:00Z",
                    "event_type": "checkpoint_written",
                    "phase_id": "writer",
                    "schema_ok": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (tel / "observations.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2026-04-24T12:00:00Z",
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "event_type": "writer_exit",
                    "source": "swarm-run-exit",
                    "schema_ok": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual(load_run_events()[0]["event_type"], "checkpoint_written")
        self.assertEqual(load_observations()[0]["event_type"], "writer_exit")
        self.assertEqual(latest_checkpoint_event()["phase_id"], "writer")
        self.assertEqual(latest_observation()["source"], "swarm-run-exit")

        rendered = status_summary(now=datetime(2026, 4, 24, 13, tzinfo=UTC)).render()
        self.assertIn("latest_checkpoint=01ARZ3NDEKTSV4RRFFQ69G5FAV:writer", rendered)
        self.assertIn("latest_observation=writer_exit:swarm-run-exit", rendered)


class TuiActionTests(EnvTestCase):
    def test_config_hash_changes_when_backends_toml_changes(self) -> None:
        before = active_config_hash()
        set_base_route("agent-docs", None, "codex", "gpt-5.4-mini", "medium")
        after = active_config_hash()
        self.assertNotEqual(before, after)

    def test_invariant_rejects_orchestrator_to_codex(self) -> None:
        with self.assertRaisesRegex(ValueError, "orchestrator"):
            set_base_route("orchestrator", None, "codex", "gpt-5.4", "high")

    def test_invalid_pipeline_change_does_not_mutate_user_preset(self) -> None:
        presets = self.root / "presets"
        presets.mkdir()
        preset_path = presets / "user.toml"
        preset_path.write_text(
            """
name = "user"
pipeline = "default"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "pipeline not found"):
            set_user_preset_pipeline("user", "missing")
        self.assertEqual(load_preset(preset_path)["pipeline"], "default")

    def test_user_preset_route_edit_validates_before_write(self) -> None:
        presets = self.root / "presets"
        presets.mkdir()
        preset_path = presets / "user.toml"
        preset_path.write_text(
            """
name = "user"
pipeline = "default"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
            encoding="utf-8",
        )
        set_user_preset_route("user", "agent-docs", "simple", "codex", "gpt-5.4-mini", "medium")
        routing = load_preset(preset_path)["routing"]
        self.assertEqual(routing["roles.agent-docs.simple"]["backend"], "codex")


if __name__ == "__main__":
    unittest.main()
