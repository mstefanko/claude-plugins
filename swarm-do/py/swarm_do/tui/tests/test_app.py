from __future__ import annotations

import unittest

from swarm_do.tui import app as tui_app
from swarm_do.pipeline.registry import find_pipeline, load_pipeline
from swarm_do.tui.state import pipeline_graph_model


@unittest.skipIf(tui_app.TEXTUAL_IMPORT_ERROR is not None, "Textual is not installed")
class TuiAppTests(unittest.TestCase):
    def test_global_navigation_bindings_are_numbered(self) -> None:
        bindings = {binding.key: binding.action for binding in tui_app.SwarmTui.BINDINGS}

        self.assertEqual(bindings["1"], "dashboard")
        self.assertEqual(bindings["2"], "runs")
        self.assertEqual(bindings["3"], "pipelines")
        self.assertEqual(bindings["4"], "presets")
        self.assertEqual(bindings["5"], "settings")
        self.assertEqual(bindings["question_mark"], "help_current")
        self.assertNotIn("d", bindings)
        self.assertNotIn("s", bindings)
        self.assertNotIn("p", bindings)
        self.assertNotIn("i", bindings)

    def test_command_palette_includes_global_and_pipeline_commands(self) -> None:
        app = tui_app.SwarmTui()

        dashboard_titles = [command.title for command in app.get_system_commands(tui_app.DashboardScreen())]
        pipeline_titles = [command.title for command in app.get_system_commands(tui_app.PipelinesScreen())]

        self.assertIn("Go to Dashboard", dashboard_titles)
        self.assertIn("Go to Pipelines", dashboard_titles)
        self.assertIn("Show Help", dashboard_titles)
        self.assertIn("Validate Selected Pipeline", pipeline_titles)
        self.assertIn("Copy Pipeline Graph", pipeline_titles)
        self.assertIn("Run Provider Doctor", pipeline_titles)

    def test_graph_line_stage_mapping_does_not_match_stage_id_substrings(self) -> None:
        pipeline = load_pipeline(find_pipeline("default").path)
        model = pipeline_graph_model(pipeline)

        self.assertEqual(
            tui_app._graph_line_stage_id("  ┌ writer ┐ ├──▶ ╭ provider-review ╮", model),
            "provider-review",
        )
        self.assertEqual(
            tui_app._graph_line_stage_id("  ╭ provider-review ╮ ──▶ ╔ review ╗", model),
            "review",
        )

    def test_graph_click_mapping_uses_horizontal_position(self) -> None:
        pipeline = load_pipeline(find_pipeline("default").path)
        model = pipeline_graph_model(pipeline)
        line = "  ┌ research ┐ ├──▶ ┌ analysis ┐ ──▶ ┌ writer ┐"

        self.assertEqual(tui_app._graph_click_stage_id(line, model, line.index("analysis")), "analysis")
        self.assertEqual(tui_app._graph_click_stage_id(line, model, line.index("writer")), "writer")


if __name__ == "__main__":
    unittest.main()
