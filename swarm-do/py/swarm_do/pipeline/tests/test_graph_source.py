from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from swarm_do.pipeline.actions import atomic_write_text, render_toml
from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.graph_source import PresetGraphError, resolve_preset_graph
from swarm_do.pipeline.registry import find_pipeline, list_presets, load_pipeline, load_preset


class GraphSourceTests(unittest.TestCase):
    def test_stock_presets_resolve_to_stock_graphs(self) -> None:
        for item in list_presets():
            if item.origin != "stock":
                continue
            with self.subTest(item=item.name):
                preset = load_preset(item.path)
                resolved = resolve_preset_graph(preset)
                pipeline = load_pipeline(find_pipeline(preset["pipeline"]).path)

                self.assertEqual(resolved.source, "stock-ref")
                self.assertEqual(resolved.source_name, preset["pipeline"])
                self.assertEqual(resolved.graph, pipeline)
                self.assertTrue(resolved.source_hash.startswith("sha256:"))

    def test_inline_preset_resolves_embedded_graph_and_lineage(self) -> None:
        stock = load_pipeline(find_pipeline("default").path)
        preset = {
            "name": "inline",
            "origin": "user",
            "budget": {
                "max_agents_per_run": 20,
                "max_estimated_cost_usd": 5.0,
                "max_wall_clock_seconds": 1800,
            },
            "pipeline_inline": stock,
            "pipeline_inline_source": {"name": "default", "hash": "sha256:" + "0" * 64},
        }

        resolved = resolve_preset_graph(preset)

        self.assertEqual(resolved.source, "inline-snapshot")
        self.assertEqual(resolved.graph, stock)
        self.assertEqual(resolved.lineage_name, "default")
        self.assertEqual(resolved.lineage_hash, "sha256:" + "0" * 64)

    def test_user_pipeline_ref_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pipelines").mkdir()
            (root / "pipelines" / "local.yaml").write_text(
                """
pipeline_version: 1
name: local
stages:
  - id: research
    agents:
      - role: agent-research
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                with self.assertRaisesRegex(PresetGraphError, "stock pipeline"):
                    resolve_preset_graph({"name": "bad", "pipeline": "local", "budget": {}})
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

    def test_render_toml_round_trips_inline_graph(self) -> None:
        graph = load_pipeline(find_pipeline("default").path)
        preset = {
            "name": "inline",
            "origin": "user",
            "budget": {
                "max_agents_per_run": 20,
                "max_estimated_cost_usd": 5.0,
                "max_wall_clock_seconds": 1800,
            },
            "pipeline_inline": graph,
            "pipeline_inline_source": {"name": "default", "hash": "sha256:" + "1" * 64},
        }

        parsed = tomllib.loads(render_toml(preset))

        self.assertEqual(parsed, preset)

    def test_config_hash_distinguishes_stock_ref_and_inline_snapshot(self) -> None:
        graph = load_pipeline(find_pipeline("default").path)
        budget = {
            "max_agents_per_run": 20,
            "max_estimated_cost_usd": 5.0,
            "max_wall_clock_seconds": 1800,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "presets").mkdir()
            atomic_write_text(root / "presets" / "stock.toml", render_toml({"name": "stock", "origin": "user", "pipeline": "default", "budget": budget}))
            atomic_write_text(root / "presets" / "inline.toml", render_toml({"name": "inline", "origin": "user", "pipeline_inline": graph, "budget": budget}))
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                atomic_write_text(root / "current-preset.txt", "stock\n")
                stock_hash = active_config_hash()
                atomic_write_text(root / "current-preset.txt", "inline\n")
                inline_hash = active_config_hash()
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

        self.assertNotEqual(stock_hash, inline_hash)


if __name__ == "__main__":
    unittest.main()
