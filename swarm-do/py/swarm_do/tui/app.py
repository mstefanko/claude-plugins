"""Textual operator console for swarm-do."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

try:  # Optional dependency installed by bin/swarm-tui.
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.screen import ModalScreen, Screen
    from textual.widgets import Button, DataTable, Footer, Header, Input, Label, ListItem, ListView, Select, Static
except Exception as exc:  # pragma: no cover - exercised when Textual is absent.
    TEXTUAL_IMPORT_ERROR: Exception | None = exc
else:  # pragma: no cover - UI smoke-tested through the wrapper in operator use.
    TEXTUAL_IMPORT_ERROR = None

from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.registry import find_pipeline, find_preset, list_presets, load_pipeline, load_preset
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, ROLE_DEFAULTS, active_preset_name
from swarm_do.pipeline.validation import schema_lint_pipeline
from swarm_do.pipeline import actions
from swarm_do.pipeline.actions import load_in_flight
from swarm_do.tui.state import (
    PipelineEditDraft,
    PipelineGalleryRow,
    StageRow,
    draft_status_line,
    draft_validation_lines,
    load_runs,
    pipeline_gallery_rows,
    pipeline_stage_rows,
    pipeline_validation_report,
    select_source_preset_for_pipeline,
    stage_inspector_text,
    start_pipeline_draft,
    status_summary,
    suggested_fork_name,
    token_burn_last_24h,
    validate_pipeline_draft,
)


if TEXTUAL_IMPORT_ERROR is None:

    class StatusBar(Static):
        def refresh_status(self) -> None:
            self.update(status_summary().render())


    class MessageModal(ModalScreen[None]):
        def __init__(self, title: str, body: str):
            super().__init__()
            self.title = title
            self.body = body

        def compose(self) -> ComposeResult:
            with Container(id="modal"):
                yield Label(self.title, classes="modal-title")
                yield Static(self.body)
                yield Button("OK", id="ok", variant="primary")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss()


    class RouteModal(ModalScreen[tuple[str, str, str] | None]):
        def __init__(self, role: str, complexity: str | None, current: tuple[str, str, str]):
            super().__init__()
            self.role = role
            self.complexity = complexity
            self.current = current

        def compose(self) -> ComposeResult:
            with Container(id="modal"):
                yield Label(f"{self.role} {self.complexity or 'default'}", classes="modal-title")
                yield Select([(b, b) for b in sorted(BACKENDS)], value=self.current[0], id="backend")
                yield Input(value=self.current[1], placeholder="model", id="model")
                yield Select([(e, e) for e in sorted(EFFORTS - {'none'})], value=self.current[2], id="effort")
                with Horizontal(classes="buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            backend = str(self.query_one("#backend", Select).value)
            model = self.query_one("#model", Input).value.strip()
            effort = str(self.query_one("#effort", Select).value)
            self.dismiss((backend, model, effort))


    class ForkPipelineModal(ModalScreen[str | None]):
        def __init__(self, source_pipeline: str, source_preset: str | None, suggested_name: str):
            super().__init__()
            self.source_pipeline = source_pipeline
            self.source_preset = source_preset
            self.suggested_name = suggested_name

        def compose(self) -> ComposeResult:
            preset = self.source_preset or "none"
            with Container(id="modal"):
                yield Label("Fork Pipeline", classes="modal-title")
                yield Static(f"source pipeline: {self.source_pipeline}\nsource preset: {preset}")
                yield Input(value=self.suggested_name, placeholder="new user preset/pipeline name", id="fork-name")
                with Horizontal(classes="buttons"):
                    yield Button("Fork", id="fork", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            self.dismiss(self.query_one("#fork-name", Input).value.strip())


    class DashboardScreen(Screen):
        BINDINGS = [
            ("f", "handoff", "Handoff"),
            ("o", "open_issue", "Open issue"),
            ("c", "cancel", "Cancel"),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical():
                yield Static("", id="banner")
                yield DataTable(id="inflight")
                yield Static("", id="burn")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#inflight", DataTable).cursor_type = "row"
            self.refresh_dashboard()
            self.set_interval(2.0, self.refresh_dashboard)

        def refresh_dashboard(self) -> None:
            summary = status_summary()
            self.query_one("#banner", Static).update(f"Preset: {summary.preset} | Pipeline: {summary.pipeline}")
            table = self.query_one("#inflight", DataTable)
            table.clear(columns=True)
            table.add_columns("issue", "role", "backend", "model", "effort", "pid", "status")
            for run in load_in_flight():
                table.add_row(run.issue_id, run.role, run.backend, run.model, run.effort, run.display_pid, run.status)
            if not load_in_flight():
                table.add_row("none", "no in-flight runs", "", "", "", "", "")
            burns = token_burn_last_24h(load_runs())
            if not burns:
                burn_text = "tokens/hr: n/a"
            else:
                burn_text = " | ".join(f"{backend}={value if value is not None else 'n/a'}" for backend, value in burns.items())
            self.query_one("#burn", Static).update(burn_text)
            self.query_one("#status", StatusBar).refresh_status()

        def _selected_issue(self) -> str | None:
            runs = load_in_flight()
            if not runs:
                return None
            table = self.query_one("#inflight", DataTable)
            row = getattr(table, "cursor_row", 0)
            return runs[min(max(row, 0), len(runs) - 1)].issue_id

        def action_handoff(self) -> None:
            issue = self._selected_issue()
            if not issue:
                self.app.push_screen(MessageModal("No run selected", "There is no in-flight run to hand off."))
                return
            actions.request_handoff(issue, "codex")
            self.app.push_screen(MessageModal("Handoff requested", f"{issue} marked for codex handoff."))

        def action_open_issue(self) -> None:
            issue = self._selected_issue()
            if not issue:
                return
            subprocess.run(["bd", "show", issue], check=False)

        def action_cancel(self) -> None:
            issue = self._selected_issue()
            run = actions.find_in_flight(issue) if issue else None
            if run is None:
                self.app.push_screen(MessageModal("No run selected", "There is no in-flight run to cancel."))
                return
            try:
                actions.cancel_run(run)
            except Exception as exc:
                self.app.push_screen(MessageModal("Cancel failed", str(exc)))
                return
            self.app.push_screen(MessageModal("Cancel sent", f"Sent SIGTERM to {issue}."))


    class SettingsScreen(Screen):
        BINDINGS = [("enter", "edit_route", "Edit route"), ("ctrl+s", "save_hint", "Save"), ("ctrl+z", "refresh_settings", "Undo")]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("Editing: backends.toml (base)", id="target")
            yield DataTable(id="settings")
            yield Static("", id="hash")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_settings()

        def refresh_settings(self) -> None:
            table = self.query_one("#settings", DataTable)
            table.clear(columns=True)
            table.cursor_type = "cell"
            table.add_columns("role", "simple", "moderate", "hard")
            active = active_preset_name()
            item = find_preset(active) if active else None
            if item is None:
                target = "Editing: backends.toml (base)"
            elif item.origin == "stock":
                target = f"Stock preset active: {item.name} - fork before editing routes"
            else:
                target = f"Editing: {item.name}.toml (routing)"
            self.query_one("#target", Static).update(target)
            resolver = BackendResolver(preset_name="current")
            for role in sorted(ROLE_DEFAULTS):
                cells = [role]
                for complexity in ("simple", "moderate", "hard"):
                    try:
                        route = resolver.resolve(role, complexity)
                        cells.append(f"{route.backend}/{route.model}/{route.effort}")
                    except Exception:
                        cells.append("n/a")
                table.add_row(*cells)
            self.query_one("#hash", Static).update(f"config_hash={active_config_hash()}")
            self.query_one("#status", StatusBar).refresh_status()

        def action_refresh_settings(self) -> None:
            self.refresh_settings()

        def action_save_hint(self) -> None:
            self.app.push_screen(MessageModal("Saved as edited", "Route edits are saved immediately from the edit dialog."))

        def action_edit_route(self) -> None:
            active = active_preset_name()
            item = find_preset(active) if active else None
            if item is not None and item.origin == "stock":
                self.app.push_screen(MessageModal("Stock preset active", "Fork the preset before editing routes."))
                return
            table = self.query_one("#settings", DataTable)
            row_index = getattr(table, "cursor_row", 0)
            col_index = getattr(table, "cursor_column", 1)
            role = sorted(ROLE_DEFAULTS)[min(max(row_index, 0), len(ROLE_DEFAULTS) - 1)]
            complexity = ("simple", "moderate", "hard")[min(max(col_index - 1, 0), 2)]
            route = BackendResolver(preset_name="current").resolve(role, complexity)

            def done(value: tuple[str, str, str] | None) -> None:
                if value is None:
                    return
                backend, model, effort = value
                try:
                    if item is not None and item.origin == "user":
                        actions.set_user_preset_route(item.name, role, complexity, backend, model, effort)
                    else:
                        actions.set_base_route(role, complexity, backend, model, effort)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Route refused", str(exc)))
                    return
                self.refresh_settings()

            self.app.push_screen(RouteModal(role, complexity, (route.backend, route.model, route.effort)), done)


    class PresetsScreen(Screen):
        BINDINGS = [("l", "load_preset", "Load"), ("d", "diff_preset", "Diff"), ("x", "delete_preset", "Delete")]

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield ListView(id="presets")
                yield Static("", id="preview")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_presets()

        def _items(self) -> list[Any]:
            return list_presets()

        def _selected(self) -> Any | None:
            items = self._items()
            if not items:
                return None
            index = self.query_one("#presets", ListView).index or 0
            return items[min(max(index, 0), len(items) - 1)]

        def refresh_presets(self) -> None:
            view = self.query_one("#presets", ListView)
            view.clear()
            for item in self._items():
                view.append(ListItem(Label(f"{item.name} [{item.origin}]")))
            self.preview_selected()
            self.query_one("#status", StatusBar).refresh_status()

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            self.preview_selected()

        def preview_selected(self) -> None:
            item = self._selected()
            if item is None:
                self.query_one("#preview", Static).update("No presets found.")
                return
            data = load_preset(item.path)
            routing = data.get("routing", {})
            lines = [f"{item.name} [{item.origin}]", f"pipeline={data.get('pipeline', 'default')}", ""]
            if isinstance(routing, dict):
                lines.extend(f"{key}: {value}" for key, value in sorted(routing.items()))
            self.query_one("#preview", Static).update("\n".join(lines))

        def action_load_preset(self) -> None:
            item = self._selected()
            if item:
                subprocess.run([str(Path(__file__).resolve().parents[3] / "bin" / "swarm"), "preset", "load", item.name], check=False)
                self.query_one("#status", StatusBar).refresh_status()

        def action_diff_preset(self) -> None:
            item = self._selected()
            if not item:
                return
            result = subprocess.run(
                [str(Path(__file__).resolve().parents[3] / "bin" / "swarm"), "preset", "diff", item.name],
                check=False,
                capture_output=True,
                text=True,
            )
            body = result.stdout or result.stderr or "No diff."
            self.app.push_screen(MessageModal(f"Diff: {item.name}", body))

        def action_delete_preset(self) -> None:
            item = self._selected()
            if not item:
                return
            try:
                actions.delete_user_preset(item.name)
            except Exception as exc:
                self.app.push_screen(MessageModal("Delete refused", str(exc)))
                return
            self.refresh_presets()


    class PipelinesScreen(Screen):
        BINDINGS = [
            ("enter", "begin_edit", "Edit"),
            ("f", "begin_edit", "Fork/Edit"),
            ("ctrl+s", "save_draft", "Save"),
            ("escape", "discard_draft", "Discard"),
            ("l", "lint_pipeline", "Lint"),
            ("v", "validate_pipeline", "Validate"),
            ("s", "set_pipeline", "Set"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._gallery_rows: list[PipelineGalleryRow] = []
            self._stage_rows: list[StageRow] = []
            self._selected_pipeline_name: str | None = None
            self._draft: PipelineEditDraft | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical(id="pipeline-workbench"):
                with Horizontal(id="pipeline-main"):
                    yield ListView(id="pipeline-gallery")
                    yield ListView(id="stage-rows")
                    yield Static("", id="stage-inspector")
                yield Static("", id="validation-rail")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_pipelines()

        def _selected_gallery_row(self) -> PipelineGalleryRow | None:
            if self._selected_pipeline_name:
                for row in self._gallery_rows:
                    if row.name == self._selected_pipeline_name:
                        return row
            if not self._gallery_rows:
                return None
            index = self.query_one("#pipeline-gallery", ListView).index or 0
            row = self._gallery_rows[min(max(index, 0), len(self._gallery_rows) - 1)]
            self._selected_pipeline_name = row.name
            return row

        def _selected_stage_row(self) -> StageRow | None:
            if not self._stage_rows:
                return None
            index = self.query_one("#stage-rows", ListView).index or 0
            return self._stage_rows[min(max(index, 0), len(self._stage_rows) - 1)]

        def _current_pipeline(self) -> dict[str, Any] | None:
            row = self._selected_gallery_row()
            if row is None:
                return None
            if self._draft is not None and self._draft.pipeline_name == row.name:
                return self._draft.pipeline
            item = find_pipeline(row.name)
            if item is None:
                return None
            return load_pipeline(item.path)

        def refresh_pipelines(self) -> None:
            self._gallery_rows = pipeline_gallery_rows()
            view = self.query_one("#pipeline-gallery", ListView)
            view.clear()
            for row in self._gallery_rows:
                view.append(ListItem(Label(row.label)))
            if self._selected_pipeline_name is None and self._gallery_rows:
                self._selected_pipeline_name = self._gallery_rows[0].name
            self.refresh_stages()
            self.query_one("#status", StatusBar).refresh_status()

        def refresh_stages(self) -> None:
            pipeline = self._current_pipeline()
            view = self.query_one("#stage-rows", ListView)
            view.clear()
            if pipeline is None:
                self._stage_rows = []
                self.query_one("#stage-inspector", Static).update("No pipeline selected.")
                self.query_one("#validation-rail", Static).update("validation: n/a")
                return
            self._stage_rows = pipeline_stage_rows(pipeline)
            for row in self._stage_rows:
                view.append(ListItem(Label(row.label)))
            self.refresh_stage_inspector()
            self.refresh_validation_rail()

        def refresh_stage_inspector(self) -> None:
            pipeline = self._current_pipeline()
            stage = self._selected_stage_row()
            if pipeline is None:
                body = "No pipeline selected."
            else:
                body = stage_inspector_text(pipeline, stage.stage_id if stage else None)
            self.query_one("#stage-inspector", Static).update(body)

        def refresh_validation_rail(self) -> None:
            row = self._selected_gallery_row()
            if row is None:
                self.query_one("#validation-rail", Static).update("validation: n/a")
                return
            if self._draft is not None and self._draft.pipeline_name == row.name:
                lines = draft_validation_lines(self._draft)
            else:
                lines = [draft_status_line(None), pipeline_validation_report(row.name)]
            self.query_one("#validation-rail", Static).update("\n".join(lines))

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            if event.list_view.id == "pipeline-gallery":
                index = event.list_view.index or 0
                if self._gallery_rows:
                    self._selected_pipeline_name = self._gallery_rows[min(max(index, 0), len(self._gallery_rows) - 1)].name
                self.refresh_stages()
                return
            if event.list_view.id == "stage-rows":
                self.refresh_stage_inspector()

        def action_begin_edit(self) -> None:
            row = self._selected_gallery_row()
            if row is None:
                return
            item = find_pipeline(row.name)
            if item is None:
                self.app.push_screen(MessageModal("Pipeline missing", row.name))
                return
            if item.origin == "user":
                try:
                    self._draft = start_pipeline_draft(item.name, preset_name=row.preset)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Draft refused", str(exc)))
                    return
                self.refresh_stages()
                self.app.push_screen(MessageModal("Draft ready", f"Editing {item.name} in memory. Save writes after validation."))
                return

            source_preset = select_source_preset_for_pipeline(item.name)
            suggested = suggested_fork_name(item.name)

            def fork_done(new_name: str | None) -> None:
                if not new_name:
                    return
                try:
                    if source_preset:
                        actions.fork_preset_and_pipeline(source_preset, item.name, new_name)
                    else:
                        actions.fork_pipeline(item.name, new_name)
                    self._draft = start_pipeline_draft(new_name)
                    self._selected_pipeline_name = new_name
                except Exception as exc:
                    self.app.push_screen(MessageModal("Fork refused", str(exc)))
                    return
                self.refresh_pipelines()
                self.app.push_screen(MessageModal("Fork ready", f"{new_name} is user-owned and open as an in-memory draft."))

            self.app.push_screen(ForkPipelineModal(item.name, source_preset, suggested), fork_done)

        def action_save_draft(self) -> None:
            if self._draft is None:
                self.app.push_screen(MessageModal("No draft", "Open or fork a user pipeline before saving."))
                return
            result = validate_pipeline_draft(self._draft)
            if result.errors:
                self._draft.mark_invalid("; ".join(result.errors))
                self.refresh_validation_rail()
                self.app.push_screen(MessageModal("Save blocked", "\n".join(result.errors)))
                return
            try:
                actions.save_user_pipeline(self._draft.pipeline_name, self._draft.pipeline)
            except Exception as exc:
                self.app.push_screen(MessageModal("Save failed", str(exc)))
                return
            self._draft.mark_saved()
            self.refresh_pipelines()
            self.app.push_screen(MessageModal("Saved", f"{self._draft.pipeline_name}.yaml passed validation and was written."))

        def action_discard_draft(self) -> None:
            if self._draft is None:
                return
            name = self._draft.pipeline_name
            self._draft = None
            self.refresh_stages()
            self.app.push_screen(MessageModal("Draft discarded", f"Closed in-memory edits for {name}."))

        def action_lint_pipeline(self) -> None:
            row = self._selected_gallery_row()
            pipeline = self._current_pipeline()
            if row is None or pipeline is None:
                return
            errors = schema_lint_pipeline(pipeline)
            self.app.push_screen(MessageModal(f"Lint: {row.name}", "\n".join(errors) if errors else "pipeline OK"))

        def action_validate_pipeline(self) -> None:
            row = self._selected_gallery_row()
            if row is None:
                return
            if self._draft is not None and self._draft.pipeline_name == row.name:
                body = "\n".join(draft_validation_lines(self._draft))
                self.app.push_screen(MessageModal(f"Validate draft: {row.name}", body))
                return
            preset = None
            for candidate in list_presets():
                try:
                    if load_preset(candidate.path).get("pipeline") == row.name:
                        preset = candidate
                        break
                except Exception:
                    continue
            if preset is None:
                self.app.push_screen(MessageModal("Validate", "Full validation needs a preset that references this pipeline."))
                return
            body = pipeline_validation_report(row.name, include_provider_doctor=True)
            self.app.push_screen(MessageModal(f"Validate: {preset.name}", body))

        def action_set_pipeline(self) -> None:
            row = self._selected_gallery_row()
            if row is None:
                return
            from swarm_do.pipeline.resolver import active_preset_name

            preset = active_preset_name()
            if not preset:
                self.app.push_screen(MessageModal("No user preset", "Activate or fork a user preset before changing pipelines."))
                return
            try:
                actions.set_user_preset_pipeline(preset, row.name)
            except Exception as exc:
                self.app.push_screen(MessageModal("Pipeline refused", str(exc)))
                return
            self.query_one("#status", StatusBar).refresh_status()


    class SwarmTui(App):
        CSS_PATH = "app.tcss"
        TITLE = "swarm-do"
        BINDINGS = [
            ("d", "dashboard", "Dashboard"),
            ("s", "settings", "Settings"),
            ("p", "presets", "Presets"),
            ("i", "pipelines", "Pipelines"),
            ("q", "quit", "Quit"),
        ]

        def on_mount(self) -> None:
            self.install_screen(DashboardScreen(), name="dashboard")
            self.install_screen(SettingsScreen(), name="settings")
            self.install_screen(PresetsScreen(), name="presets")
            self.install_screen(PipelinesScreen(), name="pipelines")
            self.push_screen("dashboard")

        def action_dashboard(self) -> None:
            self.switch_screen("dashboard")

        def action_settings(self) -> None:
            self.switch_screen("settings")

        def action_presets(self) -> None:
            self.switch_screen("presets")

        def action_pipelines(self) -> None:
            self.switch_screen("pipelines")


def main(argv: list[str] | None = None) -> int:
    if TEXTUAL_IMPORT_ERROR is not None:
        print(
            "swarm-tui: Textual is not installed. Run bin/swarm-tui so the managed venv can be created.",
            file=sys.stderr,
        )
        print(f"swarm-tui: import error: {TEXTUAL_IMPORT_ERROR}", file=sys.stderr)
        return 1
    SwarmTui().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
