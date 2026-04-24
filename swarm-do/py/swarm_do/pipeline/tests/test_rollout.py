from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.rollout import format_status, history_lines, load_state, mark_dogfood, set_field


class RolloutTests(unittest.TestCase):
    def test_default_state_is_pending(self) -> None:
        with isolated_data_dir():
            state = load_state()
            self.assertEqual(state["phase_0"]["decision"], "pending")
            self.assertIn("phase_0: pending", format_status(state))

    def test_mark_dogfood_persists_and_audits(self) -> None:
        with isolated_data_dir() as root:
            state = mark_dogfood("use the plugin now")
            self.assertEqual(state["phase_0"]["decision"], "DOGFOOD")
            self.assertEqual(state["phase_0"]["selected_mode"], "plugin")
            saved = load_state()
            self.assertEqual(saved["phase_0"]["notes"], "use the plugin now")
            self.assertTrue((root / "state" / "rollout-status.json").is_file())
            self.assertTrue(any("phase_0.decision=DOGFOOD" in line for line in history_lines()))

    def test_set_field_validates_enums(self) -> None:
        with isolated_data_dir():
            with self.assertRaisesRegex(ValueError, "phase_0.decision"):
                set_field("phase_0.decision", "MAYBE")
            state = set_field("pattern_5_trial.phases_sampled", "3")
            self.assertEqual(state["pattern_5_trial"]["phases_sampled"], 3)

    def test_set_field_handles_role_names_with_dots(self) -> None:
        with isolated_data_dir():
            state = set_field("role_promotions.agent-writer.simple.primary", "codex")
            self.assertEqual(state["role_promotions"]["agent-writer.simple"]["primary"], "codex")


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
