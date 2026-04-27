from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.migrate_inline import adopt_archived_pipeline, migrate_user_pipelines
from swarm_do.pipeline.registry import load_preset


PIPELINE_YAML = """
pipeline_version: 1
name: paired
stages:
  - id: research
    agents:
      - role: agent-research
"""


PRESET_TOML = """
name = "paired"
pipeline = "paired"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
"""


class MigrateInlineTests(unittest.TestCase):
    def test_fresh_data_dir_writes_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary = migrate_user_pipelines(Path(td))

            self.assertEqual(summary.migrated, 0)
            self.assertEqual(summary.archived_orphans, 0)
            self.assertTrue(summary.sentinel.is_file())

    def test_paired_user_pipeline_is_embedded_and_archived(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "presets").mkdir()
            (root / "pipelines").mkdir()
            (root / "presets" / "paired.toml").write_text(PRESET_TOML, encoding="utf-8")
            (root / "pipelines" / "paired.yaml").write_text(PIPELINE_YAML, encoding="utf-8")

            summary = migrate_user_pipelines(root)
            preset = load_preset(root / "presets" / "paired.toml")

            self.assertEqual(summary.migrated, 1)
            self.assertNotIn("pipeline", preset)
            self.assertEqual(preset["pipeline_inline"]["name"], "paired")
            self.assertFalse((root / "pipelines" / "paired.yaml").exists())
            self.assertTrue(list((root / "pipelines" / ".archived").glob("paired.yaml.*")))
            rerun = migrate_user_pipelines(root)
            self.assertEqual(rerun.migrated, 0)

    def test_orphan_user_pipeline_is_archived_with_adopt_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pipelines").mkdir()
            (root / "pipelines" / "orphan.yaml").write_text(PIPELINE_YAML.replace("paired", "orphan"), encoding="utf-8")

            summary = migrate_user_pipelines(root)

            self.assertEqual(summary.migrated, 0)
            self.assertEqual(summary.archived_orphans, 1)
            self.assertEqual(summary.orphans[0][0], "orphan")
            self.assertIn("swarm preset adopt", "\n".join(summary.lines()))

    def test_adopt_archived_pipeline_uses_stock_template_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "paired.yaml.archived"
            archive.write_text(PIPELINE_YAML, encoding="utf-8")
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                target = adopt_archived_pipeline(archive, template="balanced", name="adopted")
                preset = load_preset(target)
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

            self.assertEqual(preset["name"], "adopted")
            self.assertEqual(preset["forked_from"], "balanced")
            self.assertEqual(preset["pipeline_inline"]["name"], "paired")
            self.assertEqual(preset["budget"]["max_agents_per_run"], 80)


if __name__ == "__main__":
    unittest.main()
