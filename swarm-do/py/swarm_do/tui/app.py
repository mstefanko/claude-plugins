"""Textual operator console for SwarmDaddy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

try:  # Optional dependency installed by bin/swarm-tui.
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult, SystemCommand
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.reactive import reactive
    from textual.screen import ModalScreen, Screen
    from textual.widget import Widget
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        ListItem,
        ListView,
        Select,
        Static,
    )
except Exception as exc:  # pragma: no cover - exercised when Textual is absent.
    TEXTUAL_IMPORT_ERROR: Exception | None = exc
else:  # pragma: no cover - UI smoke-tested through the wrapper in operator use.
    TEXTUAL_IMPORT_ERROR = None

from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.registry import find_pipeline, find_preset, list_presets, load_pipeline, load_preset, sha256_file
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, ROLE_DEFAULTS, active_preset_name
from swarm_do.pipeline.validation import MCO_PROVIDER_ORDER, schema_lint_pipeline
from swarm_do.pipeline import actions
from swarm_do.pipeline.actions import load_in_flight
from swarm_do.tui.state import (
    PipelineEditDraft,
    PipelineGalleryRow,
    StageRow,
    current_prompt_lens_ids,
    current_mco_provider_config,
    current_provider_review_config,
    current_stage_agent_lens_id,
    draft_add_module_stage,
    draft_remove_stage,
    draft_reset_fan_out_routes,
    draft_reset_stage_agent_route,
    draft_set_prompt_variant_lenses,
    draft_set_fan_out_branch_route,
    draft_set_mco_provider_config,
    draft_set_provider_review_config,
    draft_set_stage_agent_lens,
    draft_set_stage_agent_route,
    draft_status_line,
    draft_validation_lines,
    effective_fan_out_branch_route,
    effective_stage_agent_route,
    load_runs,
    load_run_events,
    load_observations,
    module_palette_rows,
    pipeline_board_model,
    pipeline_board_plain_text,
    pipeline_gallery_rows,
    pipeline_activation_blocker,
    pipeline_critical_stage_ids,
    pipeline_graph_move,
    pipeline_graph_model,
    pipeline_graph_overlay,
    pipeline_live_stage_statuses,
    pipeline_has_provider_stage,
    pipeline_profile_preset,
    pipeline_stage_rows,
    pipeline_validation_report,
    select_source_preset_for_pipeline,
    stage_inspector_text,
    stage_lens_option_rows,
    start_pipeline_draft,
    status_summary,
    suggested_fork_name,
    token_burn_last_24h,
    validate_pipeline_draft,
)


if TEXTUAL_IMPORT_ERROR is None:

    def swarmdaddy_logo() -> Text:
        logo = Text()
        amber = "#c98418"
        ink = "#dfe7e5"
        teal = "#65b8b0"
        logo.append("       __    __          ", style=f"bold {amber}")
        logo.append("Swarm", style=f"bold {ink}")
        logo.append("Daddy\n", style=f"bold {amber}")
        logo.append("    __/  \\__/  \\__\n", style=f"bold {amber}")
        logo.append("   /  \\__/", style=f"bold {amber}")
        logo.append("[]", style=f"bold {teal}")
        logo.append("\\__/  \\\n", style=f"bold {amber}")
        logo.append("   \\__/  \\__/  \\__/\n", style=f"bold {amber}")
        logo.append("   /  \\__/  \\__/  \\\n", style=f"bold {amber}")
        logo.append("   \\__/  \\__/  \\__/", style=f"bold {amber}")
        return logo


    class StatusBar(Static):
        def refresh_status(self) -> None:
            self.update(status_summary().render())


    class AppChrome(Static):
        def __init__(self, section: str, **kwargs: Any):
            super().__init__("", **kwargs)
            self.section = section

        def on_mount(self) -> None:
            self.refresh_chrome()

        def refresh_chrome(self) -> None:
            summary = status_summary()
            validation = _validation_badge(summary.pipeline)
            cost = f"${summary.cost_today:.4f}" if summary.cost_today is not None else "n/a"
            nav = _nav_line(self.section)
            context = (
                f"current={self.section}  preset={summary.preset}  pipeline={summary.pipeline}  "
                f"runs_today={summary.runs_today}  cost_today={cost}  validation={validation}"
            )
            extra = ""
            screen_context = getattr(self.screen, "chrome_context", None)
            if callable(screen_context):
                extra = screen_context()
            self.update(nav + "\n" + (context if not extra else context + "  " + extra))


    class StageInspectorView(Static):
        can_focus = True


    class PipelineStageCard(Static):
        can_focus = True

        def __init__(self, card: Any, **kwargs: Any):
            self.card = card
            self.stage_id = card.stage_id
            super().__init__(_stage_card_text(card), classes=_stage_card_classes(card), **kwargs)

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.focus()
            handler = getattr(self.screen, "select_graph_stage", None)
            if callable(handler):
                handler(self.stage_id)


    class PipelineLayerColumn(Vertical):
        def __init__(self, column: Any, **kwargs: Any):
            super().__init__(classes="layer-column", **kwargs)
            self.column = column

        def compose(self) -> ComposeResult:
            yield Static(self.column.label, classes="layer-column-title")
            with Horizontal(classes="layer-card-row"):
                for card in self.column.cards:
                    yield PipelineStageCard(card)


    class PipelineLayerBoard(Widget):
        can_focus = True
        BINDINGS = [
            Binding("left", "select_left", "Prev layer", show=False),
            Binding("right", "select_right", "Next layer", show=False),
            Binding("up", "select_up", "Prev stage", show=False),
            Binding("down", "select_down", "Next stage", show=False),
            Binding("home", "select_first", "First stage", show=False),
            Binding("end", "select_last", "Last stage", show=False),
            Binding("enter", "open_selected", "Edit", show=False),
            Binding("y", "copy_graph", "Copy", show=False),
        ]

        def __init__(self, **kwargs: Any):
            super().__init__(classes="pipeline-board", **kwargs)
            self.model: Any | None = None
            self.overlay = pipeline_graph_overlay()
            self.board: Any | None = None
            self.message = "No pipeline selected."
            self.message_failed = False

        def on_mount(self) -> None:
            self._rebuild()

        def set_message(self, message: str, *, failed: bool = False) -> None:
            self.model = None
            self.overlay = pipeline_graph_overlay()
            self.board = None
            self.message = message
            self.message_failed = failed
            self._rebuild()

        def set_graph(self, model: Any, overlay: Any, board: Any) -> None:
            self.model = model
            self.overlay = overlay
            self.board = board
            self.message = ""
            self.message_failed = False
            self._rebuild()

        def _rebuild(self) -> None:
            if not self.is_mounted:
                return
            self.remove_children()
            widgets = self._render_widgets()
            if widgets:
                self.mount(*widgets)

        def _render_widgets(self) -> list[Widget]:
            if self.message:
                modifier = "stage-card--failed" if self.message_failed else "stage-card--warning"
                return [Static(self.message, classes=f"stage-card {modifier}")]
            if self.board is None:
                return [Static("No pipeline selected.", classes="stage-card stage-card--warning")]
            if not self.board.columns:
                return [Static("Pipeline has no stages.", classes="stage-card stage-card--warning")]
            if self.board.mode == "board":
                return [PipelineLayerColumn(column) for column in self.board.columns]
            return [
                Static(
                    "\n".join(self.board.fallback_lines),
                    classes=f"pipeline-board-text pipeline-board-text--{self.board.mode}",
                )
            ]

        def _select(self, stage_id: str | None) -> None:
            if not stage_id:
                return
            handler = getattr(self.screen, "select_graph_stage", None)
            if callable(handler):
                handler(stage_id)

        def _move(self, direction: str) -> None:
            if self.model is None:
                return
            stage_id = pipeline_graph_move(self.model, self.overlay.selected_stage_id, direction)
            self._select(stage_id)

        def on_click(self, event: events.Click) -> None:
            self.focus()

        def on_resize(self, event: events.Resize) -> None:
            if self.model is None or self.board is None:
                return
            mode = pipeline_board_model(
                self.model,
                self.overlay,
                width=event.size.width,
                height=event.size.height,
            ).mode
            if mode == self.board.mode:
                return
            self.board = pipeline_board_model(
                self.model,
                self.overlay,
                width=event.size.width,
                height=event.size.height,
            )
            self._rebuild()

        def action_select_left(self) -> None:
            self._move("up")

        def action_select_right(self) -> None:
            self._move("down")

        def action_select_up(self) -> None:
            self._move("left")

        def action_select_down(self) -> None:
            self._move("right")

        def action_select_first(self) -> None:
            if self.model is not None and self.model.nodes:
                self._select(self.model.nodes[0].stage_id)

        def action_select_last(self) -> None:
            if self.model is not None and self.model.nodes:
                self._select(self.model.nodes[-1].stage_id)

        def action_open_selected(self) -> None:
            handler = getattr(self.screen, "action_begin_edit", None)
            if callable(handler):
                handler()

        def action_copy_graph(self) -> None:
            handler = getattr(self.screen, "action_copy_graph", None)
            if callable(handler):
                handler()


    def _stage_card_text(card: Any) -> str:
        title = f"> {card.title}" if card.selected else f"  {card.title}"
        lines = [title]
        if card.subtitle:
            lines.append(str(card.subtitle))
        if card.badges:
            lines.append(" ".join(f"[{badge}]" for badge in card.badges))
        if card.selected:
            if card.dependency_label:
                lines.append(card.dependency_label)
            if card.outgoing_label:
                lines.append(card.outgoing_label)
        if card.warnings:
            lines.append("; ".join(card.warnings))
        return "\n".join(lines)


    def _stage_card_classes(card: Any) -> str:
        classes = ["stage-card"]
        if card.lane == "provider":
            classes.append("stage-card--provider")
        elif card.lane in {"terminal", "output"} or "OUTPUT" in card.badges:
            classes.append("stage-card--terminal")
        else:
            classes.append("stage-card--agents")
        if any(badge.startswith("FAN x") for badge in card.badges):
            classes.append("stage-card--fanout")
        if card.selected:
            classes.append("stage-card--selected")
        if card.dirty:
            classes.append("stage-card--dirty")
        if card.critical:
            classes.append("stage-card--critical")
        if card.warnings or "WARN" in card.badges:
            classes.append("stage-card--warning")
        if "RUN" in card.badges:
            classes.append("stage-card--running")
        if "FAILED" in card.badges:
            classes.append("stage-card--failed")
        if "QUEUED" in card.badges:
            classes.append("stage-card--queued")
        if "DONE" in card.badges:
            classes.append("stage-card--done")
        return " ".join(classes)


    def _nav_line(active: str) -> str:
        sections = (
            ("1", "Dashboard"),
            ("2", "Runs"),
            ("3", "Pipelines"),
            ("4", "Presets"),
            ("5", "Settings"),
        )
        rendered = []
        for key, label in sections:
            token = f"{key} {label}"
            rendered.append(f"[{token}]" if label == active else token)
        return "SwarmDaddy  " + "  ".join(rendered) + "  ^p Commands  ? Help"


    def _validation_badge(pipeline_name: str) -> str:
        try:
            report = pipeline_validation_report(pipeline_name)
        except Exception:
            return "unknown"
        if "\n  ERROR " in report:
            return "ERROR"
        if "\n  WARN " in report:
            return "WARN"
        if "OK structural validation" in report:
            return "OK"
        return "n/a"


    def _refresh_chrome(screen: Screen) -> None:
        try:
            screen.query_one(AppChrome).refresh_chrome()
        except Exception:
            pass


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


    class BranchRouteModal(ModalScreen[tuple[str, str, str, str] | None]):
        def __init__(self, stage_id: str, branch_count: int, current: tuple[str, str, str]):
            super().__init__()
            self.stage_id = stage_id
            self.branch_count = branch_count
            self.current = current

        def compose(self) -> ComposeResult:
            with Container(id="modal"):
                yield Label(f"{self.stage_id} branch route", classes="modal-title")
                yield Static(f"branch index: 0..{max(0, self.branch_count - 1)}")
                yield Input(value="0", placeholder="branch index", id="branch-index")
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
            self.dismiss(
                (
                    self.query_one("#branch-index", Input).value.strip(),
                    str(self.query_one("#backend", Select).value),
                    self.query_one("#model", Input).value.strip(),
                    str(self.query_one("#effort", Select).value),
                )
            )


    class ModuleModal(ModalScreen[tuple[str, str, str] | None]):
        def __init__(self, rows: list[dict[str, str]]):
            super().__init__()
            self.rows = rows

        def compose(self) -> ComposeResult:
            options = [
                (f"{row['category']}: {row['module_id']} ({row['status']})", row["module_id"])
                for row in self.rows
            ]
            default = self.rows[0] if self.rows else {"module_id": "", "suggested_stage_id": ""}
            with Container(id="modal"):
                yield Label("Add Module", classes="modal-title")
                yield Select(options, value=default["module_id"], id="module")
                yield Static(default.get("detail", ""), id="module-detail")
                yield Static("stage id defaults to the suggestion for the selected module")
                yield Input(value=default["suggested_stage_id"], placeholder="stage id", id="stage-id")
                yield Input(value="", placeholder="depends_on, comma separated (optional)", id="depends-on")
                with Horizontal(classes="buttons"):
                    yield Button("Add", id="add", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            self.dismiss(
                (
                    str(self.query_one("#module", Select).value),
                    self.query_one("#stage-id", Input).value.strip(),
                    self.query_one("#depends-on", Input).value.strip(),
                )
            )

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id != "module":
                return
            selected = str(event.value)
            for row in self.rows:
                if row["module_id"] == selected:
                    self.query_one("#stage-id", Input).value = row["suggested_stage_id"]
                    self.query_one("#module-detail", Static).update(row["detail"])
                    break


    class McoConfigModal(ModalScreen[tuple[list[str], str, str, str] | None]):
        def __init__(self, stage_id: str, config: dict[str, Any]):
            super().__init__()
            self.stage_id = stage_id
            self.config = config

        def compose(self) -> ComposeResult:
            selected = set(self.config.get("providers") or ["claude"])
            timeout = str(self.config.get("timeout_seconds") or 1800)
            mode = str(self.config.get("failure_tolerance_mode") or "best-effort")
            min_success = self.config.get("min_success")
            with Container(id="modal"):
                yield Label(f"{self.stage_id} MCO", classes="modal-title")
                yield Static("experimental read-only evidence")
                for provider in MCO_PROVIDER_ORDER:
                    yield Checkbox(provider, value=provider in selected, id=f"mco-provider-{provider}")
                yield Input(value=timeout, placeholder="timeout seconds", id="mco-timeout")
                yield Select(
                    [(label, label) for label in ("best-effort", "strict", "quorum")],
                    value=mode if mode in {"best-effort", "strict", "quorum"} else "best-effort",
                    id="mco-tolerance",
                )
                yield Input(value=str(min_success or ""), placeholder="min_success for quorum", id="mco-min-success")
                with Horizontal(classes="buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            providers = [
                provider
                for provider in MCO_PROVIDER_ORDER
                if self.query_one(f"#mco-provider-{provider}", Checkbox).value
            ]
            self.dismiss(
                (
                    providers,
                    self.query_one("#mco-timeout", Input).value.strip(),
                    str(self.query_one("#mco-tolerance", Select).value),
                    self.query_one("#mco-min-success", Input).value.strip(),
                )
            )


    class ProviderReviewConfigModal(ModalScreen[tuple[str, str, str, str, str, str] | None]):
        def __init__(self, stage_id: str, config: dict[str, Any]):
            super().__init__()
            self.stage_id = stage_id
            self.config = config

        def compose(self) -> ComposeResult:
            selection = str(self.config.get("selection") or "auto")
            providers = ", ".join(str(provider) for provider in self.config.get("providers") or [])
            timeout = str(self.config.get("timeout_seconds") or 1800)
            max_parallel = str(self.config.get("max_parallel") or 4)
            mode = str(self.config.get("failure_tolerance_mode") or "best-effort")
            min_success = self.config.get("min_success")
            with Container(id="modal"):
                yield Label(f"{self.stage_id} Provider Review", classes="modal-title")
                yield Static("internal read-only evidence")
                yield Select(
                    [(label, label) for label in ("auto", "explicit", "off")],
                    value=selection if selection in {"auto", "explicit", "off"} else "auto",
                    id="provider-selection",
                )
                yield Input(value=providers, placeholder="providers for explicit selection", id="provider-list")
                yield Input(value=timeout, placeholder="timeout seconds", id="provider-timeout")
                yield Input(value=max_parallel, placeholder="max parallel", id="provider-max-parallel")
                yield Select(
                    [(label, label) for label in ("best-effort", "strict", "quorum")],
                    value=mode if mode in {"best-effort", "strict", "quorum"} else "best-effort",
                    id="provider-tolerance",
                )
                yield Input(value=str(min_success or ""), placeholder="min_success for quorum", id="provider-min-success")
                with Horizontal(classes="buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            self.dismiss(
                (
                    str(self.query_one("#provider-selection", Select).value),
                    self.query_one("#provider-list", Input).value.strip(),
                    self.query_one("#provider-timeout", Input).value.strip(),
                    self.query_one("#provider-max-parallel", Input).value.strip(),
                    str(self.query_one("#provider-tolerance", Select).value),
                    self.query_one("#provider-min-success", Input).value.strip(),
                )
            )


    class LensModal(ModalScreen[list[str] | None]):
        def __init__(self, stage_id: str, role: str, rows: list[dict[str, str]], current_ids: list[str]):
            super().__init__()
            self.stage_id = stage_id
            self.role = role
            self.rows = rows
            self.current_ids = current_ids

        def compose(self) -> ComposeResult:
            body_lines = []
            for row in self.rows:
                body_lines.extend(
                    [
                        f"{row['lens_id']} [{row['category']}; {row['mode']}; selected={row['selected']}]",
                        f"  variant: {row['variant']}",
                        f"  contract: {row['contract']}",
                        f"  merge: {row['merge_expectation']}",
                        f"  safety: {row['safety']}",
                        "",
                    ]
                )
            body = "\n".join(body_lines).strip() or "No compatible lenses."
            with Container(id="modal"):
                yield Label(f"{self.stage_id} lenses ({self.role})", classes="modal-title")
                yield Static(body, id="lens-detail")
                yield Input(value=", ".join(self.current_ids), placeholder="lens ids, comma separated", id="lens-ids")
                with Horizontal(classes="buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            raw = self.query_one("#lens-ids", Input).value.strip()
            if not raw:
                self.dismiss([])
                return
            self.dismiss([part.strip() for part in raw.split(",") if part.strip()])


    class DashboardScreen(Screen):
        BINDINGS = [
            ("f", "handoff", "Handoff"),
            ("o", "open_issue", "Open issue"),
            ("c", "cancel", "Cancel"),
        ]
        HELP = (
            "Dashboard\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Pipelines, 4 Presets, 5 Settings, Ctrl+P Commands, q Quit.\n"
            "Local: f request handoff, o open selected Beads issue, c cancel selected in-flight run."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Dashboard", id="app-chrome")
            with Vertical():
                with Horizontal(id="dashboard-top"):
                    yield Static("", id="profile-summary")
                    yield Static("", id="event-strip")
                yield Static("", id="dashboard-graph")
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
            self.query_one("#profile-summary", Static).update(_dashboard_profile_text(summary))
            self.query_one("#event-strip", Static).update(_dashboard_event_text())
            self.query_one("#dashboard-graph", Static).update(_dashboard_graph_text(summary.pipeline))
            table = self.query_one("#inflight", DataTable)
            table.clear(columns=True)
            table.add_columns("issue", "role", "backend", "model", "effort", "pid", "status")
            in_flight = load_in_flight()
            for run in in_flight:
                table.add_row(run.issue_id, run.role, run.backend, run.model, run.effort, run.display_pid, run.status)
            if not in_flight:
                table.add_row("none", "no in-flight runs", "", "", "", "", "")
            burns = token_burn_last_24h(load_runs())
            if not burns:
                burn_text = "tokens/hr: n/a"
            else:
                burn_text = " | ".join(f"{backend}={value if value is not None else 'n/a'}" for backend, value in burns.items())
            self.query_one("#burn", Static).update(burn_text)
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

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


    def _dashboard_profile_text(summary: Any) -> str:
        lines = [
            "Active Profile",
            f"preset={summary.preset}  pipeline={summary.pipeline}",
            f"runs_today={summary.runs_today}  validation={_validation_badge(summary.pipeline)}",
        ]
        report_lines = pipeline_validation_report(summary.pipeline).splitlines()
        for line in report_lines:
            stripped = line.strip()
            if stripped.startswith(("OK ", "WARN ", "ERROR ", "budget:", "provider doctor:")):
                lines.append(stripped)
            if len(lines) >= 7:
                break
        return "\n".join(lines)


    def _dashboard_event_text() -> str:
        lines = ["Active Runs / Event Log"]
        in_flight = load_in_flight()
        if in_flight:
            for run in in_flight[:4]:
                lines.append(f"{run.issue_id} {run.role} {run.status}")
        else:
            lines.append("no in-flight runs")
        events = load_run_events()[-3:]
        observations = load_observations()[-3:]
        for row in events:
            lines.append(f"event {row.get('event_type', 'unknown')} {row.get('phase_id') or row.get('run_id') or ''}".rstrip())
        for row in observations:
            lines.append(f"obs {row.get('event_type', 'unknown')} {row.get('source') or ''}".rstrip())
        return "\n".join(lines[:8])


    def _dashboard_graph_text(pipeline_name: str) -> str:
        item = find_pipeline(pipeline_name) or find_pipeline("default")
        if item is None:
            return "Active Pipeline Board\nno active pipeline found; press 3 to open Pipelines"
        try:
            pipeline = load_pipeline(item.path)
            model = pipeline_graph_model(pipeline)
            overlay = pipeline_graph_overlay(
                stage_statuses=pipeline_live_stage_statuses(
                    model,
                    in_flight_runs=load_in_flight(),
                    run_events=load_run_events()[-12:],
                    observations=load_observations()[-12:],
                ),
                critical_stage_ids=pipeline_critical_stage_ids(model),
            )
            board = pipeline_board_model(model, overlay, width=88, height=8)
        except Exception as exc:
            return f"Active Pipeline Board\nERROR {exc}"
        return "Active Pipeline Board\n" + "\n".join(board.fallback_lines)


    class SettingsScreen(Screen):
        BINDINGS = [("enter", "edit_route", "Edit route"), ("ctrl+s", "save_hint", "Save"), ("ctrl+z", "refresh_settings", "Undo")]
        HELP = (
            "Settings\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Pipelines, 4 Presets, 5 Settings, Ctrl+P Commands, q Quit.\n"
            "Local: Enter edit selected route, Ctrl+S save hint, Ctrl+Z refresh."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Settings", id="app-chrome")
            yield Static("Effective Role Routes", id="settings-title")
            yield Static("Editing: backends.toml (base)", id="target")
            yield Static("", id="settings-warning")
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
            if hasattr(table, "fixed_rows"):
                table.fixed_rows = 1
            if hasattr(table, "fixed_columns"):
                table.fixed_columns = 1
            active = active_preset_name()
            item = find_preset(active) if active else None
            if item is None:
                target = "active preset=custom origin=base editing=base routes"
                warning = ""
            elif item.origin == "stock":
                target = f"active preset={item.name} origin=stock editing=read-only fork required"
                warning = "WARN stock preset active; fork before editing effective routes"
            else:
                target = f"active preset={item.name} origin={item.origin} editing=user preset routes"
                warning = ""
            self.query_one("#target", Static).update(target)
            self.query_one("#settings-warning", Static).update(warning)
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
            _refresh_chrome(self)

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
        BINDINGS = [("l", "load_preset", "Load"), ("v", "diff_preset", "View diff"), ("x", "delete_preset", "Delete")]
        HELP = (
            "Presets\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Pipelines, 4 Presets, 5 Settings, Ctrl+P Commands, q Quit.\n"
            "Local: l load selected preset, v view diff, x delete user preset."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Presets", id="app-chrome")
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
            active = active_preset_name()
            for item in self._items():
                marker = "*" if active == item.name else " "
                view.append(ListItem(Label(f"{marker} {item.name} [{item.origin}]")))
            self.preview_selected()
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

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
                _refresh_chrome(self)

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
        selected_stage_id = reactive(None)
        BINDINGS = [
            ("enter", "begin_edit", "Edit"),
            ("f", "begin_edit", "Fork/Edit"),
            ("g", "focus_graph", "Board"),
            ("r", "edit_stage_route", "Route"),
            ("b", "edit_branch_route", "Branch"),
            ("n", "edit_lenses", "Lens"),
            ("o", "edit_provider", "Provider"),
            ("ctrl+d", "provider_doctor", "Doctor"),
            ("m", "add_module", "Module"),
            ("t", "focus_stage_details", "Details"),
            ("y", "copy_graph", "Copy board"),
            ("delete", "remove_stage", "Remove"),
            ("ctrl+r", "reset_selected_route", "Reset route"),
            ("ctrl+z", "undo_draft", "Undo"),
            ("ctrl+y", "redo_draft", "Redo"),
            ("ctrl+s", "save_draft", "Save"),
            ("escape", "discard_draft", "Discard"),
            ("l", "lint_pipeline", "Lint"),
            ("v", "validate_pipeline", "Validate"),
            ("a", "activate_pipeline", "Activate"),
        ]
        HELP = (
            "Pipelines\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Pipelines, 4 Presets, 5 Settings, Ctrl+P Commands, q Quit.\n"
            "Board: g focus layer board, Up/Down move layers, Left/Right move parallel stages, Enter/f edit.\n"
            "Badges: JOIN waits for multiple inputs, FAN fan-out, PROVIDER evidence, OUTPUT terminal output, DIRTY draft.\n"
            "Local: r route, b branch, n lens, o provider, Ctrl+D doctor, m module, "
            "t details, v validate, a activate, Ctrl+S save, Esc discard."
        )

        def __init__(self) -> None:
            super().__init__()
            self._gallery_rows: list[PipelineGalleryRow] = []
            self._stage_rows: list[StageRow] = []
            self._graph_model: Any | None = None
            self._graph_overlay = pipeline_graph_overlay()
            self._selected_pipeline_name: str | None = None
            self._draft: PipelineEditDraft | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Pipelines", id="app-chrome")
            with Vertical(id="pipeline-workbench"):
                with Horizontal(id="pipeline-main"):
                    yield ListView(id="pipeline-gallery")
                    with Vertical(id="pipeline-content"):
                        yield PipelineLayerBoard(id="pipeline-graph")
                        with Horizontal(id="pipeline-details"):
                            yield StageInspectorView("", id="stage-inspector")
                            yield Static("", id="validation-rail")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_pipelines()
            self.set_focus(self.query_one("#pipeline-graph", PipelineLayerBoard))

        def chrome_context(self) -> str:
            if self._draft is None:
                return "draft=none"
            state = "dirty" if self._draft.dirty else self._draft.status
            return f"draft={state}:{self._draft.pipeline_name}"

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
            if self.selected_stage_id:
                for row in self._stage_rows:
                    if row.stage_id == self.selected_stage_id:
                        return row
            self.selected_stage_id = self._stage_rows[0].stage_id
            return self._stage_rows[0]

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
                active_pipeline = status_summary().pipeline
                self._selected_pipeline_name = (
                    active_pipeline
                    if any(row.name == active_pipeline for row in self._gallery_rows)
                    else self._gallery_rows[0].name
                )
            if self._selected_pipeline_name is not None:
                selected_index = next(
                    (idx for idx, row in enumerate(self._gallery_rows) if row.name == self._selected_pipeline_name),
                    0,
                )
                view.index = selected_index
            self.refresh_stages()
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

        def refresh_stages(self) -> None:
            pipeline = self._current_pipeline()
            view = self.query_one("#pipeline-graph", PipelineLayerBoard)
            if pipeline is None:
                self._stage_rows = []
                self._graph_model = None
                self._graph_overlay = pipeline_graph_overlay()
                self.selected_stage_id = None
                view.set_message("No pipeline selected.")
                self.query_one("#stage-inspector", StageInspectorView).update("No pipeline selected.")
                self.query_one("#validation-rail", Static).update("validation: n/a")
                _refresh_chrome(self)
                return
            self._stage_rows = pipeline_stage_rows(pipeline)
            valid_stage_ids = {row.stage_id for row in self._stage_rows}
            if self.selected_stage_id not in valid_stage_ids:
                self.selected_stage_id = self._stage_rows[0].stage_id if self._stage_rows else None
            self.refresh_graph()
            self.refresh_stage_inspector()
            self.refresh_validation_rail()
            _refresh_chrome(self)

        def _graph_render_width(self) -> int:
            try:
                width = self.query_one("#pipeline-graph", PipelineLayerBoard).size.width
            except Exception:
                width = 0
            return width if width and width >= 42 else 112

        def _graph_render_height(self) -> int:
            try:
                height = self.query_one("#pipeline-graph", PipelineLayerBoard).size.height
            except Exception:
                height = 0
            return height if height and height >= 1 else 20

        def _overlay_for_model(self, model: Any) -> Any:
            return pipeline_graph_overlay(
                selected_stage_id=self.selected_stage_id,
                stage_statuses=pipeline_live_stage_statuses(
                    model,
                    in_flight_runs=load_in_flight(),
                    run_events=load_run_events()[-12:],
                    observations=load_observations()[-12:],
                ),
                dirty_stage_ids=self._dirty_stage_ids(),
                critical_stage_ids=pipeline_critical_stage_ids(model),
            )

        def refresh_graph(self) -> None:
            pipeline = self._current_pipeline()
            view = self.query_one("#pipeline-graph", PipelineLayerBoard)
            if pipeline is None:
                self._graph_model = None
                self._graph_overlay = pipeline_graph_overlay()
                view.set_message("No pipeline selected.")
                return
            try:
                model = pipeline_graph_model(pipeline)
                overlay = self._overlay_for_model(model)
            except Exception as exc:
                self._graph_model = None
                self._graph_overlay = pipeline_graph_overlay()
                view.set_message(f"Pipeline failed to load: {str(exc)[:120]}", failed=True)
                return
            self._graph_model = model
            self._graph_overlay = overlay
            view.set_graph(
                model,
                overlay,
                pipeline_board_model(
                    model,
                    overlay,
                    width=self._graph_render_width(),
                    height=self._graph_render_height(),
                ),
            )

        def _dirty_stage_ids(self) -> frozenset[str]:
            if self._draft is None:
                return frozenset()
            original = {
                str(stage.get("id")): stage
                for stage in self._draft.original_pipeline.get("stages") or []
                if isinstance(stage, dict) and stage.get("id")
            }
            changed = set()
            for stage in self._draft.pipeline.get("stages") or []:
                if not isinstance(stage, dict) or not stage.get("id"):
                    continue
                stage_id = str(stage["id"])
                if original.get(stage_id) != stage:
                    changed.add(stage_id)
            return frozenset(changed)

        def refresh_stage_inspector(self) -> None:
            pipeline = self._current_pipeline()
            stage = self._selected_stage_row()
            if pipeline is None:
                body = "No pipeline selected."
            else:
                body = stage_inspector_text(pipeline, stage.stage_id if stage else None, self._graph_overlay)
            self.query_one("#stage-inspector", StageInspectorView).update(body)

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
            _refresh_chrome(self)

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            if event.list_view.id == "pipeline-gallery":
                index = event.list_view.index or 0
                if self._gallery_rows:
                    self._selected_pipeline_name = self._gallery_rows[min(max(index, 0), len(self._gallery_rows) - 1)].name
                    self.selected_stage_id = None
                self.refresh_stages()
                return

        def select_graph_stage(self, stage_id: str) -> None:
            if stage_id == self.selected_stage_id:
                return
            valid_stage_ids = {row.stage_id for row in self._stage_rows}
            if stage_id not in valid_stage_ids:
                return
            self.selected_stage_id = stage_id
            self.refresh_graph()
            self.refresh_stage_inspector()

        def action_focus_graph(self) -> None:
            self.set_focus(self.query_one("#pipeline-graph", PipelineLayerBoard))

        def action_focus_stage_details(self) -> None:
            self.set_focus(self.query_one("#stage-inspector", StageInspectorView))

        def _draft_for_selected(self) -> PipelineEditDraft | None:
            row = self._selected_gallery_row()
            if row is None:
                return None
            if self._draft is not None and self._draft.pipeline_name == row.name:
                return self._draft
            item = find_pipeline(row.name)
            if item is not None and item.origin == "user":
                try:
                    self._draft = start_pipeline_draft(item.name, preset_name=row.preset)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Draft refused", str(exc)))
                    return None
                self.refresh_stages()
                return self._draft
            self.app.push_screen(MessageModal("Fork first", "Press f or Enter to fork this stock pipeline before editing."))
            return None

        def _selected_stage_mapping(self) -> dict[str, Any] | None:
            pipeline = self._current_pipeline()
            stage = self._selected_stage_row()
            if pipeline is None or stage is None:
                return None
            for candidate in pipeline.get("stages") or []:
                if isinstance(candidate, dict) and candidate.get("id") == stage.stage_id:
                    return candidate
            return None

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

        def action_edit_stage_route(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            mapping = self._selected_stage_mapping()
            if mapping is None or not isinstance(mapping.get("agents"), list):
                self.app.push_screen(MessageModal("Route edit", "Select an agents stage to edit its first agent route."))
                return
            try:
                current = effective_stage_agent_route(draft, stage.stage_id, 0)
            except Exception as exc:
                self.app.push_screen(MessageModal("Route unavailable", str(exc)))
                return

            def done(value: tuple[str, str, str] | None) -> None:
                if value is None:
                    return
                backend, model, effort = value
                try:
                    draft_set_stage_agent_route(
                        draft,
                        stage.stage_id,
                        0,
                        backend=backend,
                        model=model,
                        effort=effort,
                    )
                except Exception as exc:
                    self.app.push_screen(MessageModal("Route refused", str(exc)))
                    return
                self.refresh_stages()

            self.app.push_screen(
                RouteModal(stage.stage_id, current.get("source"), (current["backend"], current["model"], current["effort"])),
                done,
            )

        def action_edit_branch_route(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            mapping = self._selected_stage_mapping()
            fan = mapping.get("fan_out") if isinstance(mapping, dict) else None
            if not isinstance(fan, dict):
                self.app.push_screen(MessageModal("Branch route", "Select a fan-out stage to edit branch routes."))
                return
            if fan.get("variant") == "prompt_variants":
                self.app.push_screen(MessageModal("Branch route", "Prompt-variant fan-outs cannot also use model routes."))
                return
            count = fan.get("count")
            if not isinstance(count, int):
                self.app.push_screen(MessageModal("Branch route", "Fan-out count is invalid."))
                return
            try:
                current = effective_fan_out_branch_route(draft, stage.stage_id, 0)
            except Exception as exc:
                self.app.push_screen(MessageModal("Branch route unavailable", str(exc)))
                return

            def done(value: tuple[str, str, str, str] | None) -> None:
                if value is None:
                    return
                branch_text, backend, model, effort = value
                try:
                    branch_index = int(branch_text)
                    draft_set_fan_out_branch_route(
                        draft,
                        stage.stage_id,
                        branch_index,
                        backend=backend,
                        model=model,
                        effort=effort,
                    )
                except Exception as exc:
                    self.app.push_screen(MessageModal("Branch route refused", str(exc)))
                    return
                self.refresh_stages()

            self.app.push_screen(
                BranchRouteModal(stage.stage_id, count, (current["backend"], current["model"], current["effort"])),
                done,
            )

        def action_edit_lenses(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            mapping = self._selected_stage_mapping()
            fan = mapping.get("fan_out") if isinstance(mapping, dict) else None
            agents = mapping.get("agents") if isinstance(mapping, dict) else None
            is_fan_out = isinstance(fan, dict)
            is_agents = isinstance(agents, list)
            if not is_fan_out and not is_agents:
                self.app.push_screen(MessageModal("Lens edit", "Select an agents or fan-out stage to apply prompt lenses."))
                return
            try:
                if is_fan_out and (fan.get("variant") == "models" or "routes" in fan):
                    self.app.push_screen(MessageModal("Lens edit", "Model-route fan-outs cannot also use prompt lenses. Reset routes first."))
                    return
                if is_fan_out:
                    role = fan.get("role")
                    if not isinstance(role, str) or not role:
                        self.app.push_screen(MessageModal("Lens edit", "Fan-out role is invalid."))
                        return
                    current_ids = current_prompt_lens_ids(draft.pipeline, stage.stage_id)
                else:
                    if not agents or not isinstance(agents[0], dict):
                        self.app.push_screen(MessageModal("Lens edit", "The selected agents stage has no editable first agent."))
                        return
                    role = agents[0].get("role")
                    if not isinstance(role, str) or not role:
                        self.app.push_screen(MessageModal("Lens edit", "Agent role is invalid."))
                        return
                    current = current_stage_agent_lens_id(draft.pipeline, stage.stage_id, 0)
                    current_ids = [current] if current else []
                rows = stage_lens_option_rows(draft.pipeline, stage.stage_id)
            except Exception as exc:
                self.app.push_screen(MessageModal("Lens unavailable", str(exc)))
                return
            if not rows:
                self.app.push_screen(MessageModal("Lens edit", f"No compatible lenses for {role}."))
                return

            def done(lens_ids: list[str] | None) -> None:
                if lens_ids is None:
                    return
                try:
                    if is_fan_out:
                        draft_set_prompt_variant_lenses(draft, stage.stage_id, lens_ids)
                    else:
                        if len(lens_ids) > 1:
                            raise ValueError("lens stacking is disabled for normal agents stages; use one lens id")
                        draft_set_stage_agent_lens(draft, stage.stage_id, 0, lens_ids[0] if lens_ids else None)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Lens refused", str(exc)))
                    return
                self.refresh_stages()

            self.app.push_screen(LensModal(stage.stage_id, role, rows, current_ids), done)

        def action_edit_provider(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            mapping = self._selected_stage_mapping()
            provider = mapping.get("provider") if isinstance(mapping, dict) else None
            if not isinstance(provider, dict):
                self.app.push_screen(MessageModal("Provider config", "Select a provider stage."))
                return
            provider_type = provider.get("type")
            if provider_type == "swarm-review":
                try:
                    config = current_provider_review_config(draft.pipeline, stage.stage_id)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Provider review unavailable", str(exc)))
                    return

                def provider_done(value: tuple[str, str, str, str, str, str] | None) -> None:
                    if value is None:
                        return
                    selection, providers_text, timeout_text, max_parallel_text, tolerance_mode, min_success_text = value
                    providers = [part.strip() for part in providers_text.split(",") if part.strip()]
                    try:
                        timeout_seconds = int(timeout_text)
                        max_parallel = int(max_parallel_text)
                        min_success = int(min_success_text) if min_success_text else None
                        draft_set_provider_review_config(
                            draft,
                            stage.stage_id,
                            selection=selection,
                            providers=providers,
                            timeout_seconds=timeout_seconds,
                            max_parallel=max_parallel,
                            failure_tolerance_mode=tolerance_mode,
                            min_success=min_success,
                        )
                    except Exception as exc:
                        self.app.push_screen(MessageModal("Provider review refused", str(exc)))
                        return
                    self.refresh_stages()

                self.app.push_screen(ProviderReviewConfigModal(stage.stage_id, config), provider_done)
                return
            if provider_type != "mco":
                self.app.push_screen(MessageModal("Provider config", "This provider stage is not editable."))
                return
            try:
                config = current_mco_provider_config(draft.pipeline, stage.stage_id)
            except Exception as exc:
                self.app.push_screen(MessageModal("MCO unavailable", str(exc)))
                return

            def done(value: tuple[list[str], str, str, str] | None) -> None:
                if value is None:
                    return
                providers, timeout_text, tolerance_mode, min_success_text = value
                try:
                    timeout_seconds = int(timeout_text)
                    min_success = int(min_success_text) if min_success_text else None
                    draft_set_mco_provider_config(
                        draft,
                        stage.stage_id,
                        providers=providers,
                        timeout_seconds=timeout_seconds,
                        failure_tolerance_mode=tolerance_mode,
                        min_success=min_success,
                    )
                except Exception as exc:
                    self.app.push_screen(MessageModal("MCO config refused", str(exc)))
                    return
                self.refresh_stages()

            self.app.push_screen(McoConfigModal(stage.stage_id, config), done)

        def action_edit_mco(self) -> None:
            self.action_edit_provider()

        def action_provider_doctor(self) -> None:
            row = self._selected_gallery_row()
            pipeline = self._current_pipeline()
            if row is None or pipeline is None:
                return
            if not pipeline_has_provider_stage(pipeline):
                self.app.push_screen(MessageModal("Provider doctor", "The selected pipeline has no provider stage."))
                return
            if self._draft is not None and self._draft.pipeline_name == row.name and self._draft.dirty:
                self.app.push_screen(MessageModal("Provider doctor", "Save the draft before running provider doctor."))
                return
            body = pipeline_validation_report(row.name, include_provider_doctor=True)
            self.app.push_screen(MessageModal(f"Provider doctor: {row.name}", body))

        def action_show_stage_table(self) -> None:
            if not self._stage_rows:
                self.app.push_screen(MessageModal("Stages", "No stages for the selected pipeline."))
                return
            body = "\n".join(row.label for row in self._stage_rows)
            self.app.push_screen(MessageModal("Stages", body))

        def action_copy_graph(self) -> None:
            pipeline = self._current_pipeline()
            if pipeline is None:
                return
            model = pipeline_graph_model(pipeline)
            overlay = self._overlay_for_model(model)
            board = pipeline_board_model(model, overlay, width=0, height=self._graph_render_height())
            text = "\n".join(pipeline_board_plain_text(board))
            copier = getattr(self.app, "copy_to_clipboard", None)
            if callable(copier):
                copier(text)
                self.app.push_screen(MessageModal("Board copied", "Copied the current board as plain text."))
            else:
                self.app.push_screen(MessageModal("Board", text))

        def action_reset_selected_route(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            mapping = self._selected_stage_mapping()
            try:
                if isinstance(mapping, dict) and isinstance(mapping.get("fan_out"), dict):
                    draft_reset_fan_out_routes(draft, stage.stage_id)
                elif isinstance(mapping, dict) and isinstance(mapping.get("agents"), list):
                    draft_reset_stage_agent_route(draft, stage.stage_id, 0)
                else:
                    self.app.push_screen(MessageModal("Reset route", "Select an agents or fan-out stage."))
                    return
            except Exception as exc:
                self.app.push_screen(MessageModal("Reset refused", str(exc)))
                return
            self.refresh_stages()

        def action_add_module(self) -> None:
            draft = self._draft_for_selected()
            if draft is None:
                return
            rows = module_palette_rows(draft.pipeline)

            def done(value: tuple[str, str, str] | None) -> None:
                if value is None:
                    return
                module_id, stage_id, depends_text = value
                depends_on = [part.strip() for part in depends_text.split(",") if part.strip()] or None
                try:
                    draft_add_module_stage(
                        draft,
                        module_id,
                        stage_id=stage_id or None,
                        depends_on=depends_on,
                    )
                except Exception as exc:
                    self.app.push_screen(MessageModal("Module refused", str(exc)))
                    return
                self.refresh_stages()

            self.app.push_screen(ModuleModal(rows), done)

        def action_remove_stage(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            try:
                draft_remove_stage(draft, stage.stage_id)
            except Exception as exc:
                self.app.push_screen(MessageModal("Remove refused", str(exc)))
                return
            self.refresh_stages()

        def action_undo_draft(self) -> None:
            if self._draft is None:
                self.app.push_screen(MessageModal("Undo", "No open draft."))
                return
            if not self._draft.undo():
                self.app.push_screen(MessageModal("Undo", "Nothing to undo."))
                return
            self.refresh_stages()

        def action_redo_draft(self) -> None:
            if self._draft is None:
                self.app.push_screen(MessageModal("Redo", "No open draft."))
                return
            if not self._draft.redo():
                self.app.push_screen(MessageModal("Redo", "Nothing to redo."))
                return
            self.refresh_stages()

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
                path = actions.save_user_pipeline(
                    self._draft.pipeline_name,
                    self._draft.pipeline,
                    expected_hash=self._draft.original_disk_hash,
                )
            except Exception as exc:
                self.app.push_screen(MessageModal("Save failed", str(exc)))
                return
            self._draft.mark_saved("sha256:" + sha256_file(path))
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

        def action_activate_pipeline(self) -> None:
            row = self._selected_gallery_row()
            if row is None:
                return
            pipeline = self._current_pipeline()
            if pipeline is None:
                self.app.push_screen(MessageModal("Pipeline missing", row.name))
                return
            blocker = pipeline_activation_blocker(row.name, pipeline)
            if blocker:
                self.app.push_screen(MessageModal("Preview only", blocker))
                return
            profile_preset = pipeline_profile_preset(row.name, pipeline)
            if profile_preset:
                result = subprocess.run(
                    [str(Path(__file__).resolve().parents[3] / "bin" / "swarm"), "preset", "load", profile_preset],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    body = result.stderr or result.stdout or f"could not load preset {profile_preset}"
                    self.app.push_screen(MessageModal("Activation refused", body))
                    return
                self.query_one("#status", StatusBar).refresh_status()
                _refresh_chrome(self)
                self.app.push_screen(MessageModal("Profile activated", result.stdout.strip()))
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
            _refresh_chrome(self)

        def action_set_pipeline(self) -> None:
            self.action_activate_pipeline()


    class SwarmTui(App):
        CSS_PATH = "app.tcss"
        TITLE = "SwarmDaddy"
        BINDINGS = [
            Binding("1", "dashboard", "Dashboard"),
            Binding("2", "runs", "Runs"),
            Binding("3", "pipelines", "Pipelines"),
            Binding("4", "presets", "Presets"),
            Binding("5", "settings", "Settings"),
            Binding("question_mark", "help_current", "Help", key_display="?"),
            Binding("q", "quit", "Quit"),
        ]

        def on_mount(self) -> None:
            self.install_screen(DashboardScreen(), name="dashboard")
            self.install_screen(SettingsScreen(), name="settings")
            self.install_screen(PresetsScreen(), name="presets")
            self.install_screen(PipelinesScreen(), name="pipelines")
            self.push_screen("dashboard")

        def action_dashboard(self) -> None:
            self.switch_screen("dashboard")

        def action_runs(self) -> None:
            self.switch_screen("dashboard")

        def action_settings(self) -> None:
            self.switch_screen("settings")

        def action_presets(self) -> None:
            self.switch_screen("presets")

        def action_pipelines(self) -> None:
            self.switch_screen("pipelines")

        def action_help_current(self) -> None:
            screen = self.screen
            body = getattr(screen, "HELP", None)
            if not body:
                body = (
                    "SwarmDaddy\n\n"
                    "Global: 1 Dashboard, 2 Runs, 3 Pipelines, 4 Presets, 5 Settings, "
                    "Ctrl+P Commands, q Quit."
                )
            self.push_screen(MessageModal("Help", body))

        def get_system_commands(self, screen: Screen) -> Any:
            yield from super().get_system_commands(screen)
            yield SystemCommand("Go to Dashboard", "Open the operator dashboard", self.action_dashboard)
            yield SystemCommand("Go to Runs", "Open the dashboard runs table", self.action_runs)
            yield SystemCommand("Go to Pipelines", "Open the layer-board pipeline workbench", self.action_pipelines)
            yield SystemCommand("Go to Presets", "Open preset browser", self.action_presets)
            yield SystemCommand("Go to Settings", "Open effective role routes", self.action_settings)
            yield SystemCommand("Show Help", "Show contextual help for the current screen", self.action_help_current)
            if isinstance(screen, PipelinesScreen):
                yield SystemCommand("Focus Pipeline Board", "Move keyboard focus to the board", screen.action_focus_graph)
                yield SystemCommand("Focus Stage Details", "Move keyboard focus to the selected stage details", screen.action_focus_stage_details)
                yield SystemCommand("Show Stage Table", "Show the selected pipeline stages as rows", screen.action_show_stage_table)
                yield SystemCommand("Validate Selected Pipeline", "Validate the selected pipeline", screen.action_validate_pipeline)
                yield SystemCommand("Fork/Edit Selected Pipeline", "Fork or edit the selected pipeline", screen.action_begin_edit)
                yield SystemCommand("Save Pipeline Draft", "Save the current in-memory pipeline draft", screen.action_save_draft)
                yield SystemCommand("Discard Pipeline Draft", "Discard the current in-memory pipeline draft", screen.action_discard_draft)
                yield SystemCommand("Copy Pipeline Board", "Copy the selected pipeline board as text", screen.action_copy_graph)
                yield SystemCommand("Run Provider Doctor", "Check provider readiness for this pipeline", screen.action_provider_doctor)
            if isinstance(screen, SettingsScreen):
                yield SystemCommand("Edit selected route", "Edit the selected effective role route", screen.action_edit_route)
            if isinstance(screen, PresetsScreen):
                yield SystemCommand("Load selected preset", "Activate the selected preset", screen.action_load_preset)
                yield SystemCommand("View selected preset diff", "Open the selected preset diff", screen.action_diff_preset)


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
