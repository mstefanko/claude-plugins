from __future__ import annotations

import asyncio
import dataclasses
import unittest

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
        self.assertIn("Copy Pipeline Board", pipeline_titles)
        self.assertIn("Run Provider Doctor", pipeline_titles)

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


if __name__ == "__main__":
    unittest.main()
