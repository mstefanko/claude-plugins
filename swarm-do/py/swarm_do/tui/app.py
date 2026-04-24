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
from swarm_do.pipeline.engine import graph_lines
from swarm_do.pipeline.registry import list_pipelines, list_presets, load_pipeline, load_preset
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, ROLE_DEFAULTS
from swarm_do.pipeline.validation import schema_lint_pipeline, validate_preset_and_pipeline
from swarm_do.tui import actions
from swarm_do.tui.state import load_in_flight, load_runs, status_summary, token_burn_last_24h


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
        BINDINGS = [("l", "lint_pipeline", "Lint"), ("v", "validate_pipeline", "Validate"), ("s", "set_pipeline", "Set")]

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield ListView(id="pipelines")
                yield Static("", id="preview")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_pipelines()

        def _items(self) -> list[Any]:
            return list_pipelines()

        def _selected(self) -> Any | None:
            items = self._items()
            if not items:
                return None
            index = self.query_one("#pipelines", ListView).index or 0
            return items[min(max(index, 0), len(items) - 1)]

        def refresh_pipelines(self) -> None:
            view = self.query_one("#pipelines", ListView)
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
                self.query_one("#preview", Static).update("No pipelines found.")
                return
            pipeline = load_pipeline(item.path)
            self.query_one("#preview", Static).update("\n".join(graph_lines(pipeline)))

        def action_lint_pipeline(self) -> None:
            item = self._selected()
            if not item:
                return
            errors = schema_lint_pipeline(load_pipeline(item.path))
            self.app.push_screen(MessageModal(f"Lint: {item.name}", "\n".join(errors) if errors else "pipeline OK"))

        def action_validate_pipeline(self) -> None:
            item = self._selected()
            if not item:
                return
            preset = None
            for candidate in list_presets():
                try:
                    if load_preset(candidate.path).get("pipeline") == item.name:
                        preset = candidate
                        break
                except Exception:
                    continue
            if preset is None:
                self.app.push_screen(MessageModal("Validate", "Full validation needs a preset that references this pipeline."))
                return
            result, *_ = validate_preset_and_pipeline(preset.name, include_budget=True)
            body = "\n".join(result.errors or ["validation OK"])
            self.app.push_screen(MessageModal(f"Validate: {preset.name}", body))

        def action_set_pipeline(self) -> None:
            item = self._selected()
            if not item:
                return
            from swarm_do.pipeline.resolver import active_preset_name

            preset = active_preset_name()
            if not preset:
                self.app.push_screen(MessageModal("No user preset", "Activate or fork a user preset before changing pipelines."))
                return
            try:
                actions.set_user_preset_pipeline(preset, item.name)
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
