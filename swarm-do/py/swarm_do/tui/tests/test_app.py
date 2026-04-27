from __future__ import annotations

import asyncio
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.tui import app as tui_app

if tui_app.TEXTUAL_IMPORT_ERROR is None:
    from swarm_do.pipeline import recipes as _recipes


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
        self.assertEqual(tui_app.POSTING_GALAXY_COLORS["codex"], "#5CE1E6")
        self.assertNotEqual(tui_app._backend_style("codex"), tui_app._color("success"))
        self.assertEqual(theme.variables["block-cursor-background"], "#2D2B55")
        self.assertEqual(theme.variables["block-cursor-blurred-background"], "#2D2B55")
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

    def test_preset_list_rows_use_multiline_status_rendering(self) -> None:
        row = next(row for row in tui_app.preset_gallery_rows() if row.name == "balanced")

        rendered = tui_app._preset_list_renderable(row, "balanced")
        plain = rendered.plain

        self.assertGreaterEqual(len(plain.splitlines()), 3)
        self.assertTrue(plain.startswith("● balanced"))
        self.assertIn("[active]", plain)
        self.assertIn("[OK]", plain)
        self.assertNotIn("[WARN]", plain)
        self.assertIn("[implement]", plain)
        self.assertIn("graph=default", plain)
        self.assertIn("routes=", plain)

    def test_preset_overview_rendering_promotes_status_and_composition(self) -> None:
        row = next(row for row in tui_app.preset_gallery_rows() if row.name == "balanced")
        item = tui_app.find_preset("balanced")
        self.assertIsNotNone(item)
        preset = tui_app.load_preset(item.path)
        resolved = tui_app.resolve_preset_graph(preset)
        profile = tui_app.preset_profile_preview("balanced", preset, resolved.graph, width=96, height=12)
        validation = tui_app.pipeline_validation_report("balanced")

        rendered = tui_app._preset_overview_renderable(row, item, preset, resolved, resolved.graph, profile, validation)
        plain = rendered.plain

        self.assertIn("Graph", plain)
        self.assertIn("Composition", plain)
        self.assertIn("Routing", plain)
        self.assertIn("Budget & Policy", plain)
        self.assertIn("Validation", plain)
        self.assertIn("agents", plain)
        self.assertIn("configured", plain)

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
                board = app.screen.query_one("#pipeline-graph", tui_app.PipelineLayerBoard)
                self.assertEqual(board.board.mode, "board")
                app.screen.action_show_routing()
                await pilot.pause()
                self.assertEqual(tabs.active, "routing")
                app.screen.action_show_policy()
                await pilot.pause()
                self.assertEqual(tabs.active, "policy")

        asyncio.run(run_app())

    def test_dashboard_uses_layer_board_for_active_preset(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.DashboardScreen)
                board = app.screen.query_one("#dashboard-graph", tui_app.PipelineLayerBoard)
                self.assertIsNotNone(board.board)
                self.assertEqual(board.board.mode, "board")
                title = app.screen.query_one("#dashboard-graph-title", tui_app.Static)
                self.assertIn("Active Preset Board", str(title.content))

        asyncio.run(run_app())

    def test_dashboard_graph_refresh_reuses_unchanged_board_widgets(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.DashboardScreen)
                board = app.screen.query_one("#dashboard-graph", tui_app.PipelineLayerBoard)
                child_ids = [id(child) for child in board.children]

                app.screen._refresh_dashboard_graph()
                await pilot.pause()

                self.assertEqual([id(child) for child in board.children], child_ids)

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

        rendered = tui_app._stage_card_text(card).plain

        self.assertEqual(tui_app._join_bridge_text(column), "JOIN analysis + clarify\n↓ agent-writer")
        self.assertNotIn("[JOIN]", rendered)
        self.assertIn("[RUN]", rendered)

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

        rendered = tui_app._stage_card_text(card).plain

        self.assertEqual(tui_app._output_bridge_text(column), "OUTPUT agent-review")
        self.assertNotIn("[OUTPUT]", rendered)
        self.assertIn("[DONE]", rendered)

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


@unittest.skipIf(tui_app.TEXTUAL_IMPORT_ERROR is not None, "Textual is not installed")
class NewPresetFlowTests(unittest.TestCase):
    """Coverage for NewPresetModal / GraphStackModal modals + the
    ``N`` and ``M`` bindings on the live :class:`PresetWorkbenchScreen`
    (defined at ``swarm_do/tui/app.py`` near line 3132 — the
    ``_LegacyPipelineEditor`` subclass aliased as ``PresetsScreen``).

    These tests exercise:

    * Modal defaults (recipe id, intent, name).
    * Modal dismiss payloads (``NewPresetRequest`` / ``GraphStackRequest``).
    * Bindings: ``N`` -> NewPresetModal, ``M`` -> GraphStackModal,
      lowercase ``n`` -> existing lens flow, lowercase ``m`` -> existing
      module flow.
    * The three ``action_new_preset`` branches: balanced create-only,
      blank, and create-and-activate (with patched
      ``actions.create_user_preset_graph`` / ``actions.activate_preset``
      to assert call ordering and arguments).
    * The activation-failure path surfaces a "Preset created, activation
      refused" notify.
    """

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------

    def _make_user_preset_dir(self) -> tempfile.TemporaryDirectory:
        """Create a temp ``CLAUDE_PLUGIN_DATA`` root that contains a
        single inline-snapshot user preset named ``mine``.

        ``inline-snapshot`` is required because ``_graph_edit_ready``
        (app.py:3439) only treats user presets with that source as
        directly editable; otherwise it pushes a "detach" confirm.
        """
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "presets").mkdir()
        preset_toml = (
            'name = "mine"\n'
            'origin = "user"\n'
            'description = "fixture"\n'
            "\n"
            "[budget]\n"
            "\n"
            "[pipeline_inline]\n"
            'name = "mine"\n'
            "pipeline_version = 1\n"
            "\n"
            "[[pipeline_inline.stages]]\n"
            'id = "research"\n'
            "\n"
            "[[pipeline_inline.stages.agents]]\n"
            'role = "agent-research"\n'
        )
        (root / "presets" / "mine.toml").write_text(preset_toml, encoding="utf-8")
        return td

    # ------------------------------------------------------------------
    # 1. NewPresetModal defaults
    # ------------------------------------------------------------------

    def test_new_preset_modal_defaults(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                modal = tui_app.NewPresetModal()
                # Default recipe = balanced-default (DEFAULT_RECIPE_ID at
                # app.py:1330).
                self.assertEqual(modal._recipe_id, "balanced-default")
                # Intent for the default recipe is "Implementation".
                spec = _recipes.get_preset_recipe(modal._recipe_id)
                self.assertEqual(spec.intent, "Implementation")
                # Suggested name uses suggest_user_preset_name("balanced").
                from swarm_do.pipeline.actions import suggest_user_preset_name

                self.assertEqual(
                    modal._suggested_name,
                    suggest_user_preset_name("balanced"),
                )

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 2. GraphStackModal dismiss
    # ------------------------------------------------------------------

    def test_graph_stack_modal_dismiss_emits_request(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                captured: list[object] = []

                def on_dismiss(payload: object) -> None:
                    captured.append(payload)

                modal = tui_app.GraphStackModal()
                app.push_screen(modal, on_dismiss)
                await pilot.pause()
                # Force a deterministic stack/mode independent of the
                # widget tree so we exercise dismiss(GraphStackRequest).
                # GraphStackModal exposes confirm via the "apply"
                # Button.Pressed handler (app.py:1625-1629); for a
                # unit-level dismiss test we invoke ``dismiss`` with
                # the same payload the handler builds.
                modal._stack_id = "default-research"
                modal._mode = "append-missing"
                modal.dismiss(
                    tui_app.GraphStackRequest(
                        stack_id=modal._stack_id, mode=modal._mode
                    )
                )
                await pilot.pause()
                await pilot.pause()

                self.assertEqual(len(captured), 1)
                payload = captured[0]
                self.assertIsInstance(payload, tui_app.GraphStackRequest)
                self.assertEqual(payload.stack_id, "default-research")
                self.assertIn(payload.mode, {"empty", "append-missing", "replace"})
                self.assertEqual(payload.mode, "append-missing")

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 3. PresetWorkbenchScreen N binding pushes NewPresetModal
    # ------------------------------------------------------------------

    def test_uppercase_n_binding_pushes_new_preset_modal(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.PresetWorkbenchScreen)
                # Capital N — uppercase keysym.
                await pilot.press("N")
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.NewPresetModal)

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 4. PresetWorkbenchScreen M binding pushes GraphStackModal
    # ------------------------------------------------------------------

    def test_uppercase_m_binding_pushes_graph_stack_modal(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.PresetWorkbenchScreen)
                await pilot.press("M")
                await pilot.pause()
                await pilot.pause()
                self.assertIsInstance(app.screen, tui_app.GraphStackModal)

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 5. Lowercase n / m still trigger the existing lens / module
    # actions (verified by spying on the screen's action methods).
    # ------------------------------------------------------------------

    def test_lowercase_n_still_invokes_action_edit_lenses(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)
                with mock.patch.object(
                    type(screen),
                    "action_edit_lenses",
                    autospec=True,
                ) as spy:
                    await pilot.press("n")
                    await pilot.pause()
                    await pilot.pause()
                self.assertGreaterEqual(spy.call_count, 1)

        asyncio.run(run_app())

    def test_lowercase_m_still_invokes_action_add_module(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)
                with mock.patch.object(
                    type(screen),
                    "action_add_module",
                    autospec=True,
                ) as spy:
                    await pilot.press("m")
                    await pilot.pause()
                    await pilot.pause()
                self.assertGreaterEqual(spy.call_count, 1)

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 6. Balanced create-only flow (blank=False, activate=False) —
    # asserts ``actions.create_user_preset_graph`` is called once with
    # ``activate=False`` and the new preset is selected in the gallery.
    # ------------------------------------------------------------------

    def test_balanced_create_only_calls_create_user_preset_graph(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)

                request = tui_app.NewPresetRequest(
                    recipe_id="balanced-default",
                    routing_package_id=None,
                    name="my-balanced",
                    description="t",
                    blank=False,
                    activate=False,
                )

                # Spy on refresh_pipelines so we can verify the
                # gallery refresh happens after the create call (the
                # screen sets ``_selected_pipeline_name = request.name``
                # before refresh_pipelines is invoked at app.py:3621-
                # 3622). Once the mocked create returns, the new name
                # is absent from disk, so ``_selected_gallery_row``
                # (app.py:2329-2339) eventually resets the selection
                # — that side-effect is not part of the contract.
                refresh_spy = mock.MagicMock(wraps=screen.refresh_pipelines)
                with mock.patch.object(
                    screen, "refresh_pipelines", refresh_spy
                ), mock.patch(
                    "swarm_do.pipeline.actions.create_user_preset_graph",
                    autospec=True,
                ) as create_mock:
                    screen._handle_new_preset_dismiss(request)
                    await pilot.pause()
                    await pilot.pause()

                self.assertEqual(create_mock.call_count, 1)
                _, kwargs = create_mock.call_args
                self.assertEqual(kwargs.get("activate"), False)
                # First positional arg is the preset name.
                self.assertEqual(create_mock.call_args.args[0], "my-balanced")
                # Gallery refresh was triggered (verifies that
                # downstream "select new preset" logic runs).
                self.assertGreaterEqual(refresh_spy.call_count, 1)
                # Overview tab is active afterward (per app.py:3623).
                tabs = screen.query_one("#preset-tabs", tui_app.TabbedContent)
                self.assertEqual(tabs.active, "overview")

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 7. Blank flow — no write; Graph tab active.
    # ------------------------------------------------------------------

    def test_blank_flow_does_not_call_create_user_preset_graph(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)

                request = tui_app.NewPresetRequest(
                    recipe_id=None,
                    routing_package_id=None,
                    name="blank-one",
                    description="from scratch",
                    blank=True,
                    activate=False,
                )

                with mock.patch(
                    "swarm_do.pipeline.actions.create_user_preset_graph",
                    autospec=True,
                ) as create_mock:
                    screen._handle_new_preset_dismiss(request)
                    await pilot.pause()
                    await pilot.pause()

                self.assertEqual(create_mock.call_count, 0)
                # Graph tab is active afterward.
                tabs = screen.query_one("#preset-tabs", tui_app.TabbedContent)
                self.assertEqual(tabs.active, "graph")
                # Creation draft is stored for the screen to consume.
                self.assertIsNotNone(screen._creation_draft)
                self.assertTrue(screen._creation_draft.is_blank)
                # The blank draft surfaces the stages-non-empty schema
                # error (start_blank_preset_draft contract — see
                # state.py:399).
                rail = " ".join(screen._creation_draft.errors)
                self.assertIn("stages must be a non-empty array", rail)

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 8. Create & Activate — call order: create_user_preset_graph(...,
    # activate=False) first, then activate_preset(name).
    # ------------------------------------------------------------------

    def test_create_and_activate_call_order(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)

                request = tui_app.NewPresetRequest(
                    recipe_id="balanced-default",
                    routing_package_id=None,
                    name="active-one",
                    description="",
                    blank=False,
                    activate=True,
                )

                # Use a single parent mock so we can assert
                # cross-mock call ordering deterministically.
                manager = mock.MagicMock()
                with mock.patch(
                    "swarm_do.pipeline.actions.create_user_preset_graph",
                    autospec=True,
                ) as create_mock, mock.patch(
                    "swarm_do.pipeline.actions.activate_preset",
                    autospec=True,
                ) as activate_mock:
                    manager.attach_mock(create_mock, "create")
                    manager.attach_mock(activate_mock, "activate")

                    screen._handle_new_preset_dismiss(request)
                    await pilot.pause()
                    await pilot.pause()

                # Both called exactly once.
                self.assertEqual(create_mock.call_count, 1)
                self.assertEqual(activate_mock.call_count, 1)
                # create_user_preset_graph was called with
                # activate=False (kwarg) — activation is a separate
                # step.
                _, create_kwargs = create_mock.call_args
                self.assertEqual(create_kwargs.get("activate"), False)
                # activate_preset called with the request name.
                self.assertEqual(activate_mock.call_args.args[0], "active-one")
                # Cross-mock order: create before activate.
                ordered = [call[0] for call in manager.mock_calls]
                self.assertLess(ordered.index("create"), ordered.index("activate"))

        asyncio.run(run_app())

    # ------------------------------------------------------------------
    # 9. Activation failure — preset retained; "Preset created,
    # activation refused" surfaced via app.notify.
    # ------------------------------------------------------------------

    def test_activation_failure_surfaces_notify_and_retains_preset(self) -> None:
        async def run_app() -> None:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, tui_app.PresetWorkbenchScreen)

                request = tui_app.NewPresetRequest(
                    recipe_id="balanced-default",
                    routing_package_id=None,
                    name="refused-one",
                    description="",
                    blank=False,
                    activate=True,
                )

                with mock.patch(
                    "swarm_do.pipeline.actions.create_user_preset_graph",
                    autospec=True,
                ) as create_mock, mock.patch(
                    "swarm_do.pipeline.actions.activate_preset",
                    autospec=True,
                    side_effect=RuntimeError("policy refused"),
                ) as activate_mock, mock.patch.object(
                    app, "notify", autospec=True
                ) as notify_mock:
                    # No deletion / rollback helper exists on the
                    # screen — verify that none of the destructive
                    # actions modules are invoked on the
                    # activation-failure path.
                    with mock.patch(
                        "swarm_do.pipeline.actions.delete_user_preset",
                        autospec=True,
                        create=True,
                    ) as delete_mock:
                        screen._handle_new_preset_dismiss(request)
                        await pilot.pause()
                        await pilot.pause()

                # create_user_preset_graph was still called — the
                # preset would exist on disk (here mocked) and is NOT
                # rolled back by the activation-failure path.
                self.assertEqual(create_mock.call_count, 1)
                self.assertEqual(activate_mock.call_count, 1)
                # No delete / rollback helper was invoked — the new
                # preset is retained.
                self.assertEqual(delete_mock.call_count, 0)
                # Notify was called with the activation-refused
                # message (see app.py:3633).
                self.assertGreaterEqual(notify_mock.call_count, 1)
                joined = " ".join(
                    str(call.args[0]) if call.args else ""
                    for call in notify_mock.call_args_list
                )
                self.assertIn("Preset created, activation refused", joined)

        asyncio.run(run_app())


if __name__ == "__main__":
    unittest.main()
