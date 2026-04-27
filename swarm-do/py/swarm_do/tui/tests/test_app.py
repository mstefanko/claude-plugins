from __future__ import annotations

import asyncio
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.tui import app as tui_app


@unittest.skipIf(tui_app.TEXTUAL_IMPORT_ERROR is not None, "Textual is not installed")
class TuiAppTests(unittest.TestCase):
    def test_posting_galaxy_theme_uses_source_palette(self) -> None:
        theme = tui_app.POSTING_GALAXY_THEME

        self.assertEqual(theme.name, "posting-galaxy")
        self.assertEqual(theme.primary, "#C45AFF")
        self.assertEqual(theme.secondary, "#a684e8")
        self.assertEqual(theme.background, "#0F0F1F")
        self.assertEqual(theme.surface, "#1E1E3F")
        self.assertEqual(theme.panel, "#2D2B55")
        self.assertEqual(theme.accent, "#FF69B4")
        self.assertEqual(theme.variables["footer-background"], "transparent")

    def test_posting_galaxy_theme_is_selected_on_startup(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)):
                self.assertEqual(app.theme, tui_app.POSTING_GALAXY_THEME_NAME)
                self.assertIn(tui_app.POSTING_GALAXY_THEME_NAME, app.available_themes)

        asyncio.run(run_app())

    def test_global_navigation_bindings_are_numbered(self) -> None:
        bindings = {binding.key: binding.action for binding in tui_app.SwarmTui.BINDINGS}

        self.assertEqual(bindings["1"], "dashboard")
        self.assertEqual(bindings["2"], "runs")
        self.assertEqual(bindings["3"], "presets")
        self.assertEqual(bindings["4"], "settings")
        self.assertNotIn("5", bindings)
        self.assertEqual(bindings["question_mark"], "help_current")
        self.assertNotIn("d", bindings)
        self.assertNotIn("s", bindings)
        self.assertNotIn("p", bindings)
        self.assertNotIn("i", bindings)

    def test_command_palette_includes_global_and_preset_commands(self) -> None:
        app = tui_app.SwarmTui()

        dashboard_titles = [command.title for command in app.get_system_commands(tui_app.DashboardScreen())]
        preset_titles = [command.title for command in app.get_system_commands(tui_app.PresetWorkbenchScreen())]

        self.assertIn("Go to Dashboard", dashboard_titles)
        self.assertIn("Go to Presets", dashboard_titles)
        self.assertIn("Show Help", dashboard_titles)
        self.assertIn("Activate selected preset", preset_titles)
        self.assertIn("View selected preset diff", preset_titles)
        self.assertNotIn("Focus Pipeline Board", preset_titles)
        self.assertNotIn("Save Pipeline Draft", preset_titles)

    def test_preset_workbench_is_tabbed_screen(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.PresetWorkbenchScreen)
                tabs = app.screen.query_one("#preset-tabs", tui_app.TabbedContent)
                self.assertIn(tabs.active, {"overview", "graph"})
                app.screen.action_show_graph()
                await pilot.pause()
                self.assertEqual(tabs.active, "graph")
                app.screen.action_show_routing()
                await pilot.pause()
                self.assertEqual(tabs.active, "routing")
                app.screen.action_show_policy()
                await pilot.pause()
                self.assertEqual(tabs.active, "policy")

        asyncio.run(run_app())

    def test_flow_gutter_marks_downward_board_flow(self) -> None:
        self.assertEqual(tui_app._flow_gutter_text("L1", False), "L1\n│\n▼")
        self.assertEqual(tui_app._flow_gutter_text("L5", True), "L5")

    def test_join_bridge_demotes_join_from_card_badges(self) -> None:
        card = dataclasses.make_dataclass(
            "Card",
            [
                "title",
                "subtitle",
                "badges",
                "selected",
                "dependency_label",
                "outgoing_label",
                "warnings",
                "lane",
                "dirty",
                "critical",
                "stage_id",
            ],
        )(
            "agent-writer",
            "",
            ("JOIN", "RUN"),
            False,
            "after: analysis + clarify",
            None,
            (),
            "agents",
            False,
            False,
            "writer",
        )
        column = dataclasses.make_dataclass("Column", ["cards"])((card,))

        self.assertEqual(tui_app._join_bridge_text(column), "JOIN analysis + clarify\n↓ agent-writer")
        self.assertNotIn("[JOIN]", tui_app._stage_card_text(card))
        self.assertIn("[RUN]", tui_app._stage_card_text(card))

    def test_output_bridge_demotes_output_from_card_badges(self) -> None:
        card = dataclasses.make_dataclass(
            "Card",
            [
                "title",
                "subtitle",
                "badges",
                "selected",
                "dependency_label",
                "outgoing_label",
                "warnings",
                "lane",
                "dirty",
                "critical",
                "stage_id",
            ],
        )(
            "agent-review",
            "",
            ("JOIN", "OUTPUT", "DONE"),
            False,
            "after: spec-review + provider-review",
            None,
            (),
            "output",
            False,
            False,
            "review",
        )
        column = dataclasses.make_dataclass("Column", ["cards"])((card,))

        self.assertEqual(tui_app._output_bridge_text(column), "OUTPUT agent-review")
        self.assertNotIn("[OUTPUT]", tui_app._stage_card_text(card))
        self.assertIn("[DONE]", tui_app._stage_card_text(card))

    def test_preset_workbench_handles_invalid_selected_preset(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)
                screen._selected_pipeline_name = "local"
                screen.refresh_pipelines()
                screen.refresh_preset()
                self.assertIn("local: preset pipeline must reference", screen._selected_preset_error or "")
                self.assertIn(
                    "Preset graph failed to load",
                    screen.query_one("#pipeline-graph", tui_app.PipelineLayerBoard).message,
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "presets").mkdir()
            (root / "pipelines").mkdir()
            (root / "presets" / "local.toml").write_text(
                'name = "local"\norigin = "user"\npipeline = "local"\n\n[budget]\n',
                encoding="utf-8",
            )
            (root / "pipelines" / "local.yaml").write_text(
                "pipeline_version: 1\nname: local\nstages:\n  - id: research\n    agents:\n      - role: agent-research\n",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                asyncio.run(run_app())
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old


if __name__ == "__main__":
    unittest.main()
