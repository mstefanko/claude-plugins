from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from swarm_do.tui import app as tui_app

if tui_app.TEXTUAL_IMPORT_ERROR is None:
    from swarm_do.pipeline import recipes as _recipes

pytestmark = pytest.mark.skipif(tui_app.TEXTUAL_IMPORT_ERROR is not None, reason='Textual is not installed')

@pytest.mark.tui
def test_posting_galaxy_theme_uses_source_palette() -> None:
    theme = tui_app.POSTING_GALAXY_THEME
    assert theme.name == 'posting-galaxy'
    assert theme.primary == '#C45AFF'
    assert theme.secondary == '#a684e8'
    assert theme.background == '#0F0F1F'
    assert theme.surface == '#1E1E3F'
    assert theme.panel == '#2D2B55'
    assert theme.accent == '#FF69B4'
    assert tui_app.POSTING_GALAXY_COLORS['codex'] == '#5CE1E6'
    assert tui_app._backend_style('codex') != tui_app._color('success')
    assert theme.variables['block-cursor-background'] == '#2D2B55'
    assert theme.variables['block-cursor-blurred-background'] == '#2D2B55'
    assert theme.variables['footer-background'] == 'transparent'

@pytest.mark.tui
async def test_posting_galaxy_theme_is_selected_on_startup() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)):
        assert app.theme == tui_app.POSTING_GALAXY_THEME_NAME
        assert tui_app.POSTING_GALAXY_THEME_NAME in app.available_themes

@pytest.mark.tui
def test_global_navigation_bindings_are_numbered() -> None:
    bindings = {binding.key: binding.action for binding in tui_app.SwarmTui.BINDINGS}
    assert bindings['1'] == 'dashboard'
    assert bindings['2'] == 'runs'
    assert bindings['3'] == 'presets'
    assert bindings['4'] == 'settings'
    assert '5' not in bindings
    assert bindings['question_mark'] == 'help_current'
    assert 'd' not in bindings
    assert 's' not in bindings
    assert 'p' not in bindings
    assert 'i' not in bindings

@pytest.mark.tui
async def test_runs_navigation_opens_runs_screen() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_runs()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.RunsScreen)

@pytest.mark.tui
def test_command_palette_includes_global_and_preset_commands() -> None:
    app = tui_app.SwarmTui()
    dashboard_titles = [command.title for command in app.get_system_commands(tui_app.DashboardScreen())]
    preset_titles = [command.title for command in app.get_system_commands(tui_app.PresetWorkbenchScreen())]
    assert 'Go to Dashboard' in dashboard_titles
    assert 'Go to Presets' in dashboard_titles
    assert 'Show Help' in dashboard_titles
    assert 'Activate selected preset' in preset_titles
    assert 'View selected preset diff' in preset_titles
    assert 'Focus Pipeline Board' not in preset_titles
    assert 'Save Pipeline Draft' not in preset_titles

@pytest.mark.tui
def test_preset_list_rows_use_multiline_status_rendering() -> None:
    row = next((row for row in tui_app.preset_gallery_rows() if row.name == 'balanced'))
    rendered = tui_app._preset_list_renderable(row, 'balanced')
    plain = rendered.plain
    assert len(plain.splitlines()) >= 3
    assert plain.startswith('● balanced')
    assert '[active]' in plain
    assert '[OK]' in plain
    assert '[WARN]' not in plain
    assert '[implement]' in plain
    assert 'graph=default' in plain
    assert 'routes=' in plain

@pytest.mark.tui
def test_preset_overview_rendering_promotes_status_and_composition() -> None:
    row = next((row for row in tui_app.preset_gallery_rows() if row.name == 'balanced'))
    item = tui_app.find_preset('balanced')
    assert item is not None
    preset = tui_app.load_preset(item.path)
    resolved = tui_app.resolve_preset_graph(preset)
    profile = tui_app.preset_profile_preview('balanced', preset, resolved.graph, width=96, height=12)
    validation = tui_app.pipeline_validation_report('balanced')
    rendered = tui_app._preset_overview_renderable(row, item, preset, resolved, resolved.graph, profile, validation)
    plain = rendered.plain
    assert 'Graph' in plain
    assert 'Composition' in plain
    assert 'Routing' in plain
    assert 'Budget & Policy' in plain
    assert 'Validation' in plain
    assert 'agents' in plain
    assert 'configured' in plain

@pytest.mark.tui
async def test_preset_workbench_is_tabbed_screen() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.PresetWorkbenchScreen)
        tabs = app.screen.query_one('#preset-tabs', tui_app.TabbedContent)
        assert tabs.active in {'overview', 'graph'}
        app.screen.action_show_graph()
        await pilot.pause()
        assert tabs.active == 'graph'
        board = app.screen.query_one('#pipeline-graph', tui_app.PipelineLayerBoard)
        assert board.board.mode == 'board'
        app.screen.action_show_routing()
        await pilot.pause()
        assert tabs.active == 'routing'
        app.screen.action_show_policy()
        await pilot.pause()
        assert tabs.active == 'policy'

@pytest.mark.tui
async def test_dashboard_uses_layer_board_for_active_preset() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.DashboardScreen)
        board = app.screen.query_one('#dashboard-graph', tui_app.PipelineLayerBoard)
        assert board.board is not None
        assert board.board.mode == 'board'
        title = app.screen.query_one('#dashboard-graph-title', tui_app.Static)
        assert 'Active Preset Board' in str(title.content)

@pytest.mark.tui
async def test_dashboard_graph_refresh_reuses_unchanged_board_widgets() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.DashboardScreen)
        board = app.screen.query_one('#dashboard-graph', tui_app.PipelineLayerBoard)
        child_ids = [id(child) for child in board.children]
        app.screen._refresh_dashboard_graph()
        await pilot.pause()
        assert [id(child) for child in board.children] == child_ids

@pytest.mark.tui
def test_flow_gutter_marks_downward_board_flow() -> None:
    assert tui_app._flow_gutter_text('L1', False) == 'L1\n│\n▼'
    assert tui_app._flow_gutter_text('L5', True) == 'L5'

@pytest.mark.tui
def test_join_bridge_demotes_join_from_card_badges() -> None:
    card = dataclasses.make_dataclass('Card', ['title', 'subtitle', 'badges', 'selected', 'dependency_label', 'outgoing_label', 'warnings', 'lane', 'dirty', 'critical', 'stage_id'])('agent-writer', '', ('JOIN', 'RUN'), False, 'after: analysis + clarify', None, (), 'agents', False, False, 'writer')
    column = dataclasses.make_dataclass('Column', ['cards'])((card,))
    rendered = tui_app._stage_card_text(card).plain
    assert tui_app._join_bridge_text(column) == 'JOIN analysis + clarify\n↓ agent-writer'
    assert '[JOIN]' not in rendered
    assert '[RUN]' in rendered

@pytest.mark.tui
def test_output_bridge_demotes_output_from_card_badges() -> None:
    card = dataclasses.make_dataclass('Card', ['title', 'subtitle', 'badges', 'selected', 'dependency_label', 'outgoing_label', 'warnings', 'lane', 'dirty', 'critical', 'stage_id'])('agent-review', '', ('JOIN', 'OUTPUT', 'DONE'), False, 'after: spec-review + provider-review', None, (), 'output', False, False, 'review')
    column = dataclasses.make_dataclass('Column', ['cards'])((card,))
    rendered = tui_app._stage_card_text(card).plain
    assert tui_app._output_bridge_text(column) == 'OUTPUT agent-review'
    assert '[OUTPUT]' not in rendered
    assert '[DONE]' in rendered

@pytest.mark.tui
async def test_preset_workbench_handles_invalid_selected_preset() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'presets').mkdir()
        (root / 'pipelines').mkdir()
        (root / 'presets' / 'local.toml').write_text('name = "local"\norigin = "user"\npipeline = "local"\n\n[budget]\n', encoding='utf-8')
        (root / 'pipelines' / 'local.yaml').write_text('pipeline_version: 1\nname: local\nstages:\n  - id: research\n    agents:\n      - role: agent-research\n', encoding='utf-8')
        old = os.environ.get('CLAUDE_PLUGIN_DATA')
        os.environ['CLAUDE_PLUGIN_DATA'] = td
        try:
            app = tui_app.SwarmTui()
            async with app.run_test(size=(120, 40)) as pilot:
                app.action_presets()
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, tui_app.PresetWorkbenchScreen)
                screen._selected_pipeline_name = 'local'
                screen.refresh_pipelines()
                screen.refresh_preset()
                assert 'local: preset pipeline must reference' in (screen._selected_preset_error or '')
                assert 'Preset graph failed to load' in screen.query_one('#pipeline-graph', tui_app.PipelineLayerBoard).message
        finally:
            if old is None:
                os.environ.pop('CLAUDE_PLUGIN_DATA', None)
            else:
                os.environ['CLAUDE_PLUGIN_DATA'] = old

def _make_user_preset_dir() -> tempfile.TemporaryDirectory:
    """Create a temp ``CLAUDE_PLUGIN_DATA`` root that contains a
        single inline-snapshot user preset named ``mine``.

        ``inline-snapshot`` is required because ``_graph_edit_ready``
        (app.py:3439) only treats user presets with that source as
        directly editable; otherwise it pushes a "detach" confirm.
        """
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    (root / 'presets').mkdir()
    preset_toml = 'name = "mine"\norigin = "user"\ndescription = "fixture"\n\n[budget]\n\n[pipeline_inline]\nname = "mine"\npipeline_version = 1\n\n[[pipeline_inline.stages]]\nid = "research"\n\n[[pipeline_inline.stages.agents]]\nrole = "agent-research"\n'
    (root / 'presets' / 'mine.toml').write_text(preset_toml, encoding='utf-8')
    return td

@pytest.mark.tui
async def test_new_preset_modal_defaults() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = tui_app.NewPresetModal()
        assert modal._recipe_id == 'balanced-default'
        spec = _recipes.get_preset_recipe(modal._recipe_id)
        assert spec.intent == 'Implementation'
        from swarm_do.pipeline.actions import suggest_user_preset_name
        assert modal._suggested_name == suggest_user_preset_name('balanced')

@pytest.mark.tui
async def test_graph_stack_modal_dismiss_emits_request() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        captured: list[object] = []

        def on_dismiss(payload: object) -> None:
            captured.append(payload)
        modal = tui_app.GraphStackModal()
        app.push_screen(modal, on_dismiss)
        await pilot.pause()
        modal._stack_id = 'default-research'
        modal._mode = 'append-missing'
        modal.dismiss(tui_app.GraphStackRequest(stack_id=modal._stack_id, mode=modal._mode))
        await pilot.pause()
        await pilot.pause()
        assert len(captured) == 1
        payload = captured[0]
        assert isinstance(payload, tui_app.GraphStackRequest)
        assert payload.stack_id == 'default-research'
        assert payload.mode in {'empty', 'append-missing', 'replace'}
        assert payload.mode == 'append-missing'

@pytest.mark.tui
async def test_uppercase_n_binding_pushes_new_preset_modal() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.PresetWorkbenchScreen)
        await pilot.press('N')
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.NewPresetModal)

@pytest.mark.tui
async def test_uppercase_m_binding_pushes_graph_stack_modal() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.PresetWorkbenchScreen)
        await pilot.press('M')
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, tui_app.GraphStackModal)

@pytest.mark.tui
async def test_lowercase_n_still_invokes_action_edit_lenses() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        with mock.patch.object(type(screen), 'action_edit_lenses', autospec=True) as spy:
            await pilot.press('n')
            await pilot.pause()
            await pilot.pause()
        assert spy.call_count >= 1

@pytest.mark.tui
async def test_lowercase_m_still_invokes_action_add_module() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        with mock.patch.object(type(screen), 'action_add_module', autospec=True) as spy:
            await pilot.press('m')
            await pilot.pause()
            await pilot.pause()
        assert spy.call_count >= 1

@pytest.mark.tui
async def test_balanced_create_only_calls_create_user_preset_graph() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        request = tui_app.NewPresetRequest(recipe_id='balanced-default', routing_package_id=None, name='my-balanced', description='t', blank=False, activate=False)
        refresh_spy = mock.MagicMock(wraps=screen.refresh_pipelines)
        with mock.patch.object(screen, 'refresh_pipelines', refresh_spy), mock.patch('swarm_do.pipeline.actions.create_user_preset_graph', autospec=True) as create_mock:
            screen._handle_new_preset_dismiss(request)
            await pilot.pause()
            await pilot.pause()
        assert create_mock.call_count == 1
        _, kwargs = create_mock.call_args
        assert kwargs.get('activate') == False
        assert create_mock.call_args.args[0] == 'my-balanced'
        assert refresh_spy.call_count >= 1
        tabs = screen.query_one('#preset-tabs', tui_app.TabbedContent)
        assert tabs.active == 'overview'

@pytest.mark.tui
async def test_blank_flow_does_not_call_create_user_preset_graph() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        request = tui_app.NewPresetRequest(recipe_id=None, routing_package_id=None, name='blank-one', description='from scratch', blank=True, activate=False)
        with mock.patch('swarm_do.pipeline.actions.create_user_preset_graph', autospec=True) as create_mock:
            screen._handle_new_preset_dismiss(request)
            await pilot.pause()
            await pilot.pause()
        assert create_mock.call_count == 0
        tabs = screen.query_one('#preset-tabs', tui_app.TabbedContent)
        assert tabs.active == 'graph'
        assert screen._creation_draft is not None
        assert screen._creation_draft.is_blank
        rail = ' '.join(screen._creation_draft.errors)
        assert 'stages must be a non-empty array' in rail

@pytest.mark.tui
async def test_create_and_activate_call_order() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        request = tui_app.NewPresetRequest(recipe_id='balanced-default', routing_package_id=None, name='active-one', description='', blank=False, activate=True)
        manager = mock.MagicMock()
        with mock.patch('swarm_do.pipeline.actions.create_user_preset_graph', autospec=True) as create_mock, mock.patch('swarm_do.pipeline.actions.activate_preset', autospec=True) as activate_mock:
            manager.attach_mock(create_mock, 'create')
            manager.attach_mock(activate_mock, 'activate')
            screen._handle_new_preset_dismiss(request)
            await pilot.pause()
            await pilot.pause()
        assert create_mock.call_count == 1
        assert activate_mock.call_count == 1
        _, create_kwargs = create_mock.call_args
        assert create_kwargs.get('activate') == False
        assert activate_mock.call_args.args[0] == 'active-one'
        ordered = [call[0] for call in manager.mock_calls]
        assert ordered.index('create') < ordered.index('activate')

@pytest.mark.tui
async def test_activation_failure_surfaces_notify_and_retains_preset() -> None:
    app = tui_app.SwarmTui()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_presets()
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, tui_app.PresetWorkbenchScreen)
        request = tui_app.NewPresetRequest(recipe_id='balanced-default', routing_package_id=None, name='refused-one', description='', blank=False, activate=True)
        with mock.patch('swarm_do.pipeline.actions.create_user_preset_graph', autospec=True) as create_mock, mock.patch('swarm_do.pipeline.actions.activate_preset', autospec=True, side_effect=RuntimeError('policy refused')) as activate_mock, mock.patch.object(app, 'notify', autospec=True) as notify_mock:
            with mock.patch('swarm_do.pipeline.actions.delete_user_preset', autospec=True, create=True) as delete_mock:
                screen._handle_new_preset_dismiss(request)
                await pilot.pause()
                await pilot.pause()
        assert create_mock.call_count == 1
        assert activate_mock.call_count == 1
        assert delete_mock.call_count == 0
        assert notify_mock.call_count >= 1
        joined = ' '.join((str(call.args[0]) if call.args else '' for call in notify_mock.call_args_list))
        assert 'Preset created, activation refused' in joined
