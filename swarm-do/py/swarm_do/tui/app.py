"""Textual operator console for SwarmDaddy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

try:  # Optional dependency installed by bin/swarm-tui.
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult, SystemCommand
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.reactive import reactive
    from textual.screen import ModalScreen, Screen
    from textual.theme import Theme
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
        TabbedContent,
        TabPane,
    )
except Exception as exc:  # pragma: no cover - exercised when Textual is absent.
    TEXTUAL_IMPORT_ERROR: Exception | None = exc
else:  # pragma: no cover - UI smoke-tested through the wrapper in operator use.
    TEXTUAL_IMPORT_ERROR = None

from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.graph_source import resolve_preset_graph
from swarm_do.pipeline.registry import find_pipeline, find_preset, list_presets, load_pipeline, load_preset, sha256_file
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, ROLE_DEFAULTS, active_preset_name
from swarm_do.pipeline.validation import MCO_PROVIDER_ORDER, schema_lint_pipeline
from swarm_do.pipeline import actions
from swarm_do.pipeline.actions import load_in_flight
from swarm_do.tui.state import (
    PipelineEditDraft,
    PipelineGalleryRow,
    StageRow,
    BOARD_MIN_WIDTH,
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
    format_route_chips,
    load_runs,
    load_run_events,
    load_observations,
    module_palette_rows,
    outcome_dashboard_summary,
    pipeline_board_model,
    pipeline_board_plain_text,
    pipeline_gallery_rows,
    preset_gallery_rows,
    MIN_BOARD_HEIGHT,
    pipeline_activation_blocker,
    pipeline_critical_stage_ids,
    pipeline_graph_move,
    pipeline_graph_model,
    pipeline_graph_overlay,
    pipeline_live_stage_statuses,
    pipeline_route_chips_by_stage,
    pipeline_has_provider_stage,
    pipeline_profile_preset,
    pipeline_stage_rows,
    pipeline_validation_report,
    preset_profile_preview,
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
    POSTING_GALAXY_THEME_NAME = "posting-galaxy"
    POSTING_GALAXY_COLORS = {
        "primary": "#C45AFF",
        "secondary": "#a684e8",
        "warning": "#FFD700",
        "error": "#FF4500",
        "success": "#00FA9A",
        "accent": "#FF69B4",
        "background": "#0F0F1F",
        "surface": "#1E1E3F",
        "panel": "#2D2B55",
        "text": "#F8F2FF",
    }
    # Ported from Posting's built-in "galaxy" Textual theme.
    POSTING_GALAXY_THEME = Theme(
        name=POSTING_GALAXY_THEME_NAME,
        primary=POSTING_GALAXY_COLORS["primary"],
        secondary=POSTING_GALAXY_COLORS["secondary"],
        warning=POSTING_GALAXY_COLORS["warning"],
        error=POSTING_GALAXY_COLORS["error"],
        success=POSTING_GALAXY_COLORS["success"],
        accent=POSTING_GALAXY_COLORS["accent"],
        background=POSTING_GALAXY_COLORS["background"],
        surface=POSTING_GALAXY_COLORS["surface"],
        panel=POSTING_GALAXY_COLORS["panel"],
        dark=True,
        variables={
            "block-cursor-background": POSTING_GALAXY_COLORS["panel"],
            "block-cursor-foreground": POSTING_GALAXY_COLORS["text"],
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": POSTING_GALAXY_COLORS["panel"],
            "block-cursor-blurred-foreground": POSTING_GALAXY_COLORS["text"],
            "block-cursor-blurred-text-style": "none",
            "block-hover-background": POSTING_GALAXY_COLORS["panel"],
            "input-cursor-background": POSTING_GALAXY_COLORS["primary"],
            "footer-background": "transparent",
        },
    )

    def swarmdaddy_logo() -> Text:
        logo = Text()
        primary = POSTING_GALAXY_COLORS["primary"]
        ink = POSTING_GALAXY_COLORS["text"]
        secondary = POSTING_GALAXY_COLORS["secondary"]
        accent = POSTING_GALAXY_COLORS["accent"]
        logo.append("       __    __          ", style=f"bold {primary}")
        logo.append("Swarm", style=f"bold {ink}")
        logo.append("Daddy\n", style=f"bold {accent}")
        logo.append("    __/  \\__/  \\__\n", style=f"bold {primary}")
        logo.append("   /  \\__/", style=f"bold {primary}")
        logo.append("[]", style=f"bold {secondary}")
        logo.append("\\__/  \\\n", style=f"bold {primary}")
        logo.append("   \\__/  \\__/  \\__/\n", style=f"bold {primary}")
        logo.append("   /  \\__/  \\__/  \\\n", style=f"bold {primary}")
        logo.append("   \\__/  \\__/  \\__/", style=f"bold {primary}")
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
            provider_state = getattr(self.app, "provider_state", "unchecked")
            beads_state = "ok" if actions.has_beads_rig() else "missing"
            active_line = f"Active: {summary.preset} | Beads: {beads_state} | Providers: {provider_state}"
            context = (
                f"current={self.section}  preset={summary.preset}  graph={summary.pipeline}  "
                f"runs_today={summary.runs_today}  cost_today={cost}  validation={validation}"
            )
            extra = ""
            screen_context = getattr(self.screen, "chrome_context", None)
            if callable(screen_context):
                extra = screen_context()
            self.update(nav + "\n" + active_line + "\n" + (context if not extra else context + "  " + extra))


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


    class PipelineJoinBridge(Static):
        pass


    class PipelineOutputBridge(Static):
        pass


    class PipelineLayerColumn(Horizontal):
        def __init__(self, column: Any, *, is_last: bool = False, **kwargs: Any):
            super().__init__(classes="layer-column", **kwargs)
            self.column = column
            self.is_last = is_last

        def compose(self) -> ComposeResult:
            yield Static(_flow_gutter_text(self.column.label, self.is_last), classes="layer-flow-gutter")
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
            self.route_chips_by_stage: Mapping[str, Any] = {}
            self.message = "No graph selected."
            self.message_failed = False

        def on_mount(self) -> None:
            self._rebuild()

        def set_message(self, message: str, *, failed: bool = False) -> None:
            self.model = None
            self.overlay = pipeline_graph_overlay()
            self.board = None
            self.route_chips_by_stage = {}
            self.message = message
            self.message_failed = failed
            self._rebuild()

        def set_graph(
            self,
            model: Any,
            overlay: Any,
            board: Any,
            route_chips_by_stage: Mapping[str, Any] | None = None,
        ) -> None:
            self.model = model
            self.overlay = overlay
            self.board = board
            if route_chips_by_stage is None:
                route_chips_by_stage = {
                    card.stage_id: card.route_chips
                    for column in getattr(board, "columns", ())
                    for card in getattr(column, "cards", ())
                    if getattr(card, "route_chips", ())
                }
            self.route_chips_by_stage = dict(route_chips_by_stage or {})
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
                return [Static("No graph selected.", classes="stage-card stage-card--warning")]
            if not self.board.columns:
                return [Static("Graph has no stages.", classes="stage-card stage-card--warning")]
            if self.board.mode == "board":
                widgets: list[Widget] = []
                for index, column in enumerate(self.board.columns):
                    join_text = _join_bridge_text(column)
                    if join_text is not None:
                        widgets.append(PipelineJoinBridge(join_text, classes="join-bridge"))
                    widgets.append(PipelineLayerColumn(column, is_last=index == len(self.board.columns) - 1))
                    output_text = _output_bridge_text(column)
                    if output_text is not None:
                        widgets.append(PipelineOutputBridge(output_text, classes="output-bridge"))
                return widgets
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
            render_width = max(event.size.width, BOARD_MIN_WIDTH) if event.size.width >= 42 else 112
            render_height = event.size.height if event.size.height >= MIN_BOARD_HEIGHT else 20
            mode = pipeline_board_model(
                self.model,
                self.overlay,
                width=render_width,
                height=render_height,
                route_chips_by_stage=self.route_chips_by_stage,
            ).mode
            if mode == self.board.mode:
                return
            self.board = pipeline_board_model(
                self.model,
                self.overlay,
                width=render_width,
                height=render_height,
                route_chips_by_stage=self.route_chips_by_stage,
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


    def _stage_card_text(card: Any) -> Text:
        text = Text()
        title = f"> {card.title}" if card.selected else f"  {card.title}"
        text.append(title)
        if card.subtitle:
            text.append("\n")
            text.append(str(card.subtitle))
        route_chips = tuple(getattr(card, "route_chips", ()) or ())
        if route_chips:
            text.append("\n")
            _append_route_chips(text, route_chips)
        badges = [badge for badge in card.badges if badge not in {"JOIN", "OUTPUT"}]
        if badges:
            text.append("\n")
            text.append(" ".join(f"[{badge}]" for badge in badges))
        if card.selected:
            if card.dependency_label:
                text.append("\n")
                text.append(card.dependency_label)
            if card.outgoing_label:
                text.append("\n")
                text.append(card.outgoing_label)
        if card.warnings:
            text.append("\n")
            text.append("; ".join(card.warnings))
        return text


    def _append_route_chips(text: Text, chips: tuple[Any, ...], *, max_chips: int = 3) -> None:
        visible = list(chips[:max_chips])
        for index, chip in enumerate(visible):
            if index:
                text.append(" ")
            text.append(format_route_chips([chip]), style=_route_chip_style(getattr(chip, "backend", "")))
        if len(chips) > len(visible):
            text.append(f" +{len(chips) - len(visible)}", style=_muted_style())


    def _route_chip_style(backend: Any) -> str:
        return f"bold {_color('background')} on {_backend_style(backend)}"


    def _flow_gutter_text(label: str, is_last: bool) -> str:
        return label if is_last else f"{label}\n│\n▼"


    def _join_bridge_text(column: Any) -> str | None:
        join_cards = [
            card for card in getattr(column, "cards", ())
            if "JOIN" in card.badges and card.dependency_label
        ]
        if not join_cards:
            return None
        lines = []
        for card in join_cards:
            lines.append(f"JOIN {card.dependency_label.removeprefix('after: ')}")
            lines.append(f"↓ {card.title}")
        return "\n".join(lines)


    def _output_bridge_text(column: Any) -> str | None:
        output_cards = [
            card for card in getattr(column, "cards", ())
            if "OUTPUT" in card.badges
        ]
        if not output_cards:
            return None
        return "\n".join(f"OUTPUT {card.title}" for card in output_cards)


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
            ("3", "Presets"),
            ("4", "Settings"),
        )
        rendered = []
        for key, label in sections:
            token = f"{key} {label}"
            rendered.append(f"[{token}]" if label == active else token)
        return "SwarmDaddy  " + "  ".join(rendered) + "  ^p Commands  ? Help"


    def _validation_badge(pipeline_name: str) -> str:
        if pipeline_name.startswith("inline:"):
            pipeline_name = pipeline_name.removeprefix("inline:")
        try:
            report = pipeline_validation_report(pipeline_name)
        except Exception:
            return "unknown"
        severity = _validation_report_severity(report)
        if severity is not None:
            return severity
        return "n/a"


    _QUIET_VALIDATION_WARNINGS = (
        "provider-review auto selection has no doctor cache; using upper-bound estimate",
    )


    def _is_quiet_validation_warning(line: str) -> bool:
        return any(fragment in line for fragment in _QUIET_VALIDATION_WARNINGS)


    def _validation_report_severity(report: str) -> str | None:
        if "\n  ERROR " in report:
            return "ERROR"
        warning_lines = [
            line.strip()
            for line in report.splitlines()
            if line.strip().startswith("WARN ")
        ]
        if any(not _is_quiet_validation_warning(line) for line in warning_lines):
            return "WARN"
        if "OK structural validation" in report:
            return "OK"
        return None


    def _color(name: str) -> str:
        return POSTING_GALAXY_COLORS[name]


    def _muted_style() -> str:
        return "#8B86A8"


    def _intent_style(intent: str) -> str:
        return {
            "brainstorm": _color("accent"),
            "research": _color("secondary"),
            "design": _color("accent"),
            "implement": _color("primary"),
            "review": _color("warning"),
            "competitive implementation": _color("warning"),
            "mco-assisted review": _color("success"),
            "custom": _muted_style(),
        }.get(intent, _muted_style())


    def _origin_style(origin: str) -> str:
        return {
            "stock": _color("secondary"),
            "experiment": _color("warning"),
            "user": _color("success"),
            "path": _color("accent"),
        }.get(origin, _muted_style())


    def _source_style(source: str) -> str:
        if source == "stock-ref":
            return _color("primary")
        if source == "inline-snapshot":
            return _color("warning")
        return _muted_style()


    def _backend_style(backend: Any) -> str:
        return {
            "claude": _color("secondary"),
            "codex": _color("success"),
            "gpt": _color("success"),
        }.get(str(backend).lower(), _muted_style())


    def _validation_style(status: str) -> str:
        return {
            "OK": _color("success"),
            "WARN": _color("warning"),
            "ERROR": _color("error"),
            "n/a": _muted_style(),
            "unknown": _muted_style(),
        }.get(status, _muted_style())


    def _validation_icon(status: str) -> str:
        return {
            "OK": "✓",
            "WARN": "!",
            "ERROR": "✕",
        }.get(status, "•")


    def _append_badge(text: Text, label: str, style: str) -> None:
        text.append("[", style=style)
        text.append(label, style=f"bold {style}")
        text.append("]", style=style)


    def _append_status(text: Text, status: str, *, label: str | None = None) -> None:
        style = _validation_style(status)
        text.append(_validation_icon(status), style=f"bold {style}")
        text.append(" ")
        _append_badge(text, label or status, style)


    def _clip(value: str, limit: int) -> str:
        normalized = " ".join(value.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 1)].rstrip() + "…"


    def _format_seconds(seconds: Any) -> str:
        if not isinstance(seconds, (int, float)):
            return "n/a"
        seconds = int(seconds)
        if seconds >= 3600 and seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds >= 3600:
            return f"{seconds / 3600:.1f}h"
        if seconds >= 60 and seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"


    def _budget_summary(preset: Mapping[str, Any]) -> str:
        budget = preset.get("budget")
        if not isinstance(budget, Mapping):
            return "budget n/a"
        bits = []
        if budget.get("max_agents_per_run") is not None:
            bits.append(f"agents≤{budget['max_agents_per_run']}")
        if budget.get("max_estimated_cost_usd") is not None:
            bits.append(f"cost≤${float(budget['max_estimated_cost_usd']):.0f}")
        if budget.get("max_wall_clock_seconds") is not None:
            bits.append(f"wall≤{_format_seconds(budget['max_wall_clock_seconds'])}")
        return " ".join(bits) if bits else "budget n/a"


    def _policy_summary(preset: Mapping[str, Any]) -> str:
        bits = []
        review = preset.get("review_providers")
        if isinstance(review, Mapping):
            selection = review.get("selection", "auto")
            bits.append(f"review={selection}")
            if review.get("min_success") is not None:
                bits.append(f"min={review['min_success']}")
            if review.get("max_parallel") is not None:
                bits.append(f"parallel={review['max_parallel']}")
        for section in ("decompose", "mem_prime"):
            value = preset.get(section)
            if isinstance(value, Mapping) and value.get("mode") is not None:
                bits.append(f"{section}={value['mode']}")
        return " ".join(bits) if bits else "policy default"


    def _pipeline_composition(pipeline: Mapping[str, Any]) -> dict[str, int]:
        try:
            model = pipeline_graph_model(pipeline)
        except Exception:
            return {"agents": 0, "fanout": 0, "provider": 0, "output": 0, "joins": 0}
        return {
            "agents": sum(1 for node in model.nodes if node.lane == "agents"),
            "fanout": sum(1 for node in model.nodes if node.lane == "fan-out"),
            "provider": sum(1 for node in model.nodes if node.lane == "provider"),
            "output": sum(1 for node in model.nodes if node.lane in {"terminal", "output"}),
            "joins": sum(1 for node in model.nodes if len(node.depends_on) > 1),
        }


    def _route_counts(preset: Mapping[str, Any], profile: Any | None = None) -> tuple[int, int]:
        routing = preset.get("routing")
        configured = len(routing) if isinstance(routing, Mapping) else 0
        unused = 0
        if profile is not None:
            for line in getattr(profile, "unused_route_lines", ()):
                stripped = str(line).strip()
                if stripped.startswith("roles."):
                    unused += 1
                elif stripped.startswith("..."):
                    parts = stripped.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        unused += int(parts[1])
        return configured, unused


    def _preset_list_renderable(row: PipelineGalleryRow, active: str | None) -> Text:
        text = Text()
        is_active = active == row.name
        status = _validation_badge(row.name)
        icon_style = _color("success") if is_active else _muted_style()
        text.append("● " if is_active else "○ ", style=f"bold {icon_style}")
        text.append(row.name, style=f"bold {_color('text') if is_active else _color('secondary')}")
        text.append("  ")
        _append_badge(text, row.intent, _intent_style(row.intent))
        text.append(" ")
        _append_badge(text, row.origin, _origin_style(row.origin))
        if is_active:
            text.append(" ")
            _append_badge(text, "active", _color("success"))

        description = row.description or "No description."
        text.append("\n  ")
        text.append(_clip(description, 68), style=_muted_style())

        try:
            item = find_preset(row.name)
            if item is None:
                raise ValueError("preset not found")
            preset = load_preset(item.path)
            resolved = resolve_preset_graph(preset)
            pipeline_name = str(preset.get("pipeline") or resolved.source_name or row.name)
            route_count, unused_count = _route_counts(preset)
            unused_suffix = f" unused={unused_count}" if unused_count else ""
            metadata = (
                f"graph={pipeline_name}  routes={route_count}{unused_suffix}  "
                f"{_budget_summary(preset)}"
            )
        except Exception as exc:
            metadata = f"profile unavailable: {_clip(str(exc), 48)}"

        text.append("\n  ")
        _append_status(text, status)
        text.append("  ")
        text.append(_clip(metadata, 76), style=_muted_style())
        return text


    def _append_composition(text: Text, composition: Mapping[str, int]) -> None:
        text.append("Composition\n", style=f"bold {_color('text')}")
        chips = (
            ("●", "agents", composition.get("agents", 0), _color("primary")),
            ("◆", "fan-out", composition.get("fanout", 0), _color("accent")),
            ("◈", "provider", composition.get("provider", 0), _color("warning")),
            ("■", "output", composition.get("output", 0), _color("success")),
            ("⊙", "joins", composition.get("joins", 0), _muted_style()),
        )
        text.append("  ")
        for index, (icon, label, value, style) in enumerate(chips):
            if index:
                text.append("  ")
            text.append(icon, style=f"bold {style}")
            text.append(f" {label} {value}", style=style)
        text.append("\n")


    def _append_validation_report(text: Text, report: str) -> None:
        text.append("Validation\n", style=f"bold {_color('text')}")
        for line in report.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "validation:":
                continue
            if stripped.startswith("OK "):
                style = _color("success")
                prefix = "  ✓ "
                body = stripped.removeprefix("OK ")
            elif stripped.startswith("WARN "):
                body = stripped.removeprefix("WARN ")
                if _is_quiet_validation_warning(stripped):
                    style = _muted_style()
                    prefix = "  • "
                    body = "estimate: " + body
                else:
                    style = _color("warning")
                    prefix = "  ! "
            elif stripped.startswith("ERROR "):
                style = _color("error")
                prefix = "  ✕ "
                body = stripped.removeprefix("ERROR ")
            else:
                style = _muted_style()
                prefix = "    "
                body = stripped
            text.append(prefix, style=f"bold {style}")
            text.append(body, style=style)
            text.append("\n")


    def _preset_overview_renderable(
        row: PipelineGalleryRow | None,
        item: Any,
        preset: Mapping[str, Any],
        resolved: Any,
        pipeline: Mapping[str, Any],
        profile: Any | None,
        validation: str,
    ) -> Text:
        text = Text()
        active = active_preset_name()
        is_active = active == item.name
        status = _validation_badge(item.name)
        text.append("● " if is_active else "○ ", style=f"bold {_color('success') if is_active else _muted_style()}")
        text.append(item.name, style=f"bold {_color('text')}")
        text.append("  ")
        _append_badge(text, "active" if is_active else "available", _color("success") if is_active else _muted_style())
        text.append(" ")
        _append_badge(text, item.origin, _origin_style(item.origin))
        if row is not None:
            text.append(" ")
            _append_badge(text, row.intent, _intent_style(row.intent))
        text.append(" ")
        _append_status(text, status)
        text.append("\n")

        description = preset.get("description")
        if isinstance(description, str) and description.strip():
            text.append(description.strip() + "\n", style=_muted_style())

        text.append("\nGraph\n", style=f"bold {_color('text')}")
        text.append("  ◆ ", style=f"bold {_source_style(resolved.source)}")
        text.append(_graph_source_line(item.name, dict(preset), resolved), style=_source_style(resolved.source))
        text.append("\n")
        lineage = preset.get("forked_from") or getattr(resolved, "lineage_name", None) or "none"
        text.append("  lineage ", style=_muted_style())
        text.append(str(lineage), style=_muted_style())
        text.append("\n\n")

        _append_composition(text, _pipeline_composition(pipeline))
        route_count, unused_count = _route_counts(preset, profile)
        text.append("Routing\n", style=f"bold {_color('text')}")
        text.append("  ● ", style=f"bold {_color('success') if route_count else _muted_style()}")
        text.append(f"{route_count} configured", style=_color("success") if route_count else _muted_style())
        text.append("  ")
        text.append("● ", style=f"bold {_color('warning') if unused_count else _muted_style()}")
        text.append(f"{unused_count} unused", style=_color("warning") if unused_count else _muted_style())
        text.append("\n")

        text.append("Budget & Policy\n", style=f"bold {_color('text')}")
        text.append("  ")
        text.append(_budget_summary(preset), style=_color("accent"))
        text.append("\n  ")
        text.append(_policy_summary(preset), style=_color("secondary"))
        text.append("\n\n")

        if profile is not None and getattr(profile, "unused_route_lines", None):
            text.append("Unused Routes\n", style=f"bold {_color('text')}")
            if tuple(profile.unused_route_lines) == ("Unused routes: none",):
                text.append("  none\n", style=_muted_style())
            else:
                for line in profile.unused_route_lines:
                    stripped = str(line)
                    style = _color("warning") if stripped.strip().startswith("roles.") else _muted_style()
                    text.append("  " + stripped.strip() + "\n", style=style)
            text.append("\n")

        _append_validation_report(text, validation)
        return text


    def _graph_source_line(preset_name: str, preset: dict[str, Any], resolved: Any) -> str:
        del preset
        if resolved.source == "stock-ref":
            return f"Graph: stock-ref to {resolved.source_name}"
        if resolved.lineage_name:
            prefix = (resolved.lineage_hash or resolved.source_hash).removeprefix("sha256:")[:12]
            return f"Graph: inline snapshot (forked from {resolved.lineage_name} at {prefix})"
        return f"Graph: inline snapshot ({preset_name})"


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


    class ConfirmModal(ModalScreen[bool]):
        def __init__(self, title: str, body: str, *, confirm_label: str = "Confirm"):
            super().__init__()
            self.title = title
            self.body = body
            self.confirm_label = confirm_label

        def compose(self) -> ComposeResult:
            with Container(id="modal"):
                yield Label(self.title, classes="modal-title")
                yield Static(self.body)
                with Horizontal(classes="buttons"):
                    yield Button(self.confirm_label, id="confirm", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss(event.button.id == "confirm")


    class PresetValueModal(ModalScreen[str | None]):
        def __init__(self, title: str, current: Any, *, hint: str = ""):
            super().__init__()
            self.title = title
            self.current = current
            self.hint = hint

        def compose(self) -> ComposeResult:
            with Container(id="modal"):
                yield Label(self.title, classes="modal-title")
                if self.hint:
                    yield Static(self.hint)
                yield Input(value="" if self.current is None else str(self.current), id="preset-value")
                with Horizontal(classes="buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Cancel", id="cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "cancel":
                self.dismiss(None)
                return
            self.dismiss(self.query_one("#preset-value", Input).value.strip())


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
                yield Label("New Preset Graph", classes="modal-title")
                yield Static(f"source graph: {self.source_pipeline}\nsource preset: {preset}")
                yield Input(value=self.suggested_name, placeholder="new user preset name", id="fork-name")
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
            ("ctrl+h", "provider_doctor", "Health"),
            ("ctrl+d", "provider_doctor_deprecated", "Health"),
        ]
        HELP = (
            "Dashboard\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, Ctrl+P Commands, q Quit.\n"
            "Local: f request handoff, o open the run's Beads issue, c cancel selected in-flight run, Ctrl+H health."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Dashboard", id="app-chrome")
            with Vertical():
                yield Static("", id="getting-started")
                yield Input(placeholder="Plan path?", id="getting-started-plan")
                with Horizontal(id="dashboard-top"):
                    yield Static("", id="profile-summary")
                    yield Static("", id="event-strip")
                    yield Static("", id="outcome-summary")
                yield Static("", id="dashboard-graph-title")
                yield PipelineLayerBoard(id="dashboard-graph")
                yield Static("Issue Queue", id="queue-title")
                yield DataTable(id="inflight")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#inflight", DataTable).cursor_type = "row"
            self.refresh_dashboard()
            self.set_interval(2.0, self.refresh_dashboard)

        def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
            if action in {"provider_doctor", "provider_doctor_deprecated"}:
                try:
                    graph = _active_provider_graph()
                    return bool(graph and pipeline_has_provider_stage(graph))
                except Exception:
                    return False
            return None

        def refresh_dashboard(self) -> None:
            summary = status_summary()
            panel = self.query_one("#getting-started", Static)
            plan_input = self.query_one("#getting-started-plan", Input)
            if summary.getting_started_visible:
                beads = "ok" if actions.has_beads_rig() else "missing"
                active_name = active_preset_name()
                if active_name and find_preset(active_name) is not None:
                    active = "ok"
                elif active_name:
                    active = "error"
                else:
                    active = "warn"
                providers = getattr(self.app, "provider_state", "unchecked")
                panel.update(
                    "Getting Started\n"
                    f"Beads rig: {beads}\n"
                    f"Active preset: {active}\n"
                    f"Providers: {providers}\n"
                    "Plan path?"
                )
                panel.display = True
                plan_input.display = True
            else:
                panel.display = False
                plan_input.display = False
            provider_state = getattr(self.app, "provider_state", "unchecked")
            beads_state = "ok" if actions.has_beads_rig() else "missing"
            self.query_one("#profile-summary", Static).update(
                _dashboard_profile_text(summary, provider_state=provider_state, beads_state=beads_state)
            )
            self.query_one("#event-strip", Static).update(_dashboard_event_text())
            self.query_one("#outcome-summary", Static).update(_dashboard_outcome_text(outcome_dashboard_summary()))
            self._refresh_dashboard_graph()
            table = self.query_one("#inflight", DataTable)
            table.clear(columns=True)
            table.add_columns("issue", "role", "backend", "model", "effort", "pid", "status")
            in_flight = load_in_flight()
            for run in in_flight:
                table.add_row(run.issue_id, run.role, run.backend, run.model, run.effort, run.display_pid, run.status)
            if not in_flight:
                table.add_row("none", "no in-flight runs", "", "", "", "", "")
            self.query_one("#queue-title", Static).update(_dashboard_queue_title(token_burn_last_24h(load_runs())))
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

        def _dashboard_board_width(self) -> int:
            try:
                width = self.query_one("#dashboard-graph", PipelineLayerBoard).size.width
            except Exception:
                width = 0
            return width if width and width >= 42 else 112

        def _dashboard_board_height(self) -> int:
            try:
                height = self.query_one("#dashboard-graph", PipelineLayerBoard).size.height
            except Exception:
                height = 0
            return height if height and height >= MIN_BOARD_HEIGHT else 20

        def _refresh_dashboard_graph(self) -> None:
            title = self.query_one("#dashboard-graph-title", Static)
            board = self.query_one("#dashboard-graph", PipelineLayerBoard)
            try:
                active = active_preset_name()
                if active:
                    preset_item = find_preset(active)
                    if preset_item is None:
                        raise ValueError(f"active preset not found: {active}")
                    preset = load_preset(preset_item.path)
                    resolved = resolve_preset_graph(preset)
                    pipeline = resolved.graph
                    graph_name = str(preset.get("pipeline") or resolved.source_name or pipeline.get("name") or "inline")
                    preset_name = active
                else:
                    item = find_pipeline("default")
                    if item is None:
                        title.update("Active Preset Board")
                        board.set_message("No default graph found. Press 3 to open Presets.", failed=True)
                        return
                    pipeline = load_pipeline(item.path)
                    preset = {"name": "default-fallback", "pipeline": "default"}
                    graph_name = "default"
                    preset_name = "default fallback"
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
                route_chips_by_stage = pipeline_route_chips_by_stage(
                    pipeline,
                    BackendResolver(preset_name=active, preset_data=preset),
                )
                title.update(_dashboard_graph_title(preset_name, graph_name, model))
                board.set_graph(
                    model,
                    overlay,
                    pipeline_board_model(
                        model,
                        overlay,
                        width=self._dashboard_board_width(),
                        height=self._dashboard_board_height(),
                        route_chips_by_stage=route_chips_by_stage,
                    ),
                    route_chips_by_stage,
                )
            except Exception as exc:
                title.update("Active Preset Board")
                board.set_message(f"Graph failed to load: {str(exc)[:120]}", failed=True)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "getting-started-plan":
                return
            plan = event.value.strip()
            if not plan:
                return
            command = f"/swarmdaddy:do {plan}"
            actions.atomic_write_text(actions.resolve_data_dir() / ".getting-started-dismissed", command + "\n")
            copier = getattr(self.app, "copy_to_clipboard", None)
            if callable(copier):
                copier(command)
            self.query_one("#status", StatusBar).update(command)
            self.refresh_dashboard()

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

        def action_provider_doctor(self) -> None:
            try:
                from swarm_do.pipeline.providers import format_provider_report, provider_doctor

                graph = _active_provider_graph()
                if not graph or not pipeline_has_provider_stage(graph):
                    self.app.push_screen(MessageModal("Provider health", "The active preset has no provider stage."))
                    return
                report = provider_doctor(preset_name="current", run_mco=True, run_review=True)
            except Exception as exc:
                self.app.provider_state = "error"
                self.app.push_screen(MessageModal("Provider health", str(exc)))
                _refresh_chrome(self)
                return
            self.app.provider_state = "ok" if report.ok else "error"
            self.app.push_screen(MessageModal("Provider health", format_provider_report(report)))
            _refresh_chrome(self)

        def action_provider_doctor_deprecated(self) -> None:
            self.query_one("#status", StatusBar).update("Ctrl+D is deprecated; use Ctrl+H")
            self.action_provider_doctor()


    def _state_style(state: str) -> str:
        return {
            "ok": _color("success"),
            "ready": _color("success"),
            "selected": _color("success"),
            "warn": _color("warning"),
            "missing": _color("warning"),
            "unchecked": _muted_style(),
            "error": _color("error"),
        }.get(state, _muted_style())


    def _dashboard_profile_text(summary: Any, *, provider_state: str = "unchecked", beads_state: str = "ok") -> Text:
        status = _validation_badge(summary.pipeline)
        cost = f"${summary.cost_today:.4f}" if summary.cost_today is not None else "n/a"
        text = Text()
        text.append("Active Profile\n", style=f"bold {_color('text')}")
        text.append("  ")
        _append_badge(text, summary.preset, _color("primary"))
        text.append("  ")
        _append_badge(text, summary.pipeline, _source_style("stock-ref"))
        text.append("  ")
        _append_status(text, status)
        text.append("\n  ")
        text.append(f"runs {summary.runs_today}", style=_muted_style())
        text.append("  ")
        text.append(f"cost {cost}", style=_muted_style())
        text.append("  ")
        text.append("beads ", style=_muted_style())
        _append_badge(text, beads_state, _state_style(beads_state))
        text.append("  providers ", style=_muted_style())
        _append_badge(text, provider_state, _state_style(provider_state))
        return text


    def _dashboard_event_text() -> Text:
        text = Text()
        text.append("Activity\n", style=f"bold {_color('text')}")
        in_flight = load_in_flight()
        if in_flight:
            for run in in_flight[:2]:
                text.append("  ")
                _append_badge(text, run.status, _state_style(run.status))
                text.append(f" {run.issue_id} {run.role}\n", style=_color("text"))
        else:
            text.append("  no in-flight runs\n", style=_muted_style())
        events = load_run_events()[-3:]
        observations = load_observations()[-3:]
        for label, row in (("event", events[-1] if events else None), ("obs", observations[-1] if observations else None)):
            if row is None:
                continue
            marker = row.get("phase_id") or row.get("run_id") or row.get("source") or ""
            text.append("  ")
            text.append(label, style=_color("secondary"))
            text.append(f" {row.get('event_type', 'unknown')} {marker}".rstrip(), style=_muted_style())
            text.append("\n")
        return text


    def _dashboard_outcome_text(summary: OutcomeDashboardSummary) -> Text:
        text = Text()
        text.append(f"Outcomes {summary.since_days}d\n", style=f"bold {_color('text')}")
        accepted = f"{summary.accepted_findings}/{summary.outcome_count}" if summary.outcome_count else "0/0"
        text.append("  ✓ ", style=f"bold {_color('success')}")
        text.append(f"accepted {accepted}", style=_color("success"))
        text.append("  ")
        text.append(f"findings {summary.findings_count}\n", style=_muted_style())
        text.append("  ● ", style=f"bold {_color('primary')}")
        text.append(f"success {_format_dashboard_rate(summary.successful_runs, summary.run_count)}", style=_color("primary"))
        text.append("  ")
        text.append(f"rework h:{summary.handoff_count} x:{summary.nonzero_exit_count}\n", style=_muted_style())
        role = (
            f"{summary.top_accepted_role}({summary.top_accepted_role_count})"
            if summary.top_accepted_role
            else "n/a"
        )
        text.append("  ◆ ", style=f"bold {_color('accent')}")
        text.append(f"top role {role}", style=_color("accent") if summary.top_accepted_role else _muted_style())
        return text


    def _format_dashboard_rate(numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "n/a"
        return f"{numerator / denominator:.0%}"


    def _dashboard_graph_title(preset_name: str, graph_name: str, model: Any) -> Text:
        text = Text()
        text.append("Active Preset Board", style=f"bold {_color('text')}")
        text.append("  ")
        _append_badge(text, preset_name, _color("primary"))
        text.append("  ")
        _append_badge(text, f"graph={graph_name}", _source_style("stock-ref"))
        text.append("  ")
        text.append(f"{len(getattr(model, 'nodes', ()))} stages", style=_muted_style())
        return text


    def _dashboard_queue_title(burns: Mapping[str, int | None]) -> Text:
        text = Text()
        text.append("Issue Queue", style=f"bold {_muted_style()}")
        text.append("  tokens/hr ", style=_muted_style())
        if not burns:
            text.append("n/a", style=_muted_style())
            return text
        for index, (backend, value) in enumerate(sorted(burns.items())):
            if index:
                text.append("  ", style=_muted_style())
            text.append(str(backend), style=_backend_style(backend))
            text.append(f"={value if value is not None else 'n/a'}", style=_muted_style())
        return text


    class SettingsScreen(Screen):
        BINDINGS = [("enter", "edit_route", "Edit route"), ("ctrl+s", "save_hint", "Save"), ("ctrl+z", "refresh_settings", "Undo")]
        HELP = (
            "Settings\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, Ctrl+P Commands, q Quit.\n"
            "Local: Enter edit selected route, Ctrl+S save hint, Ctrl+Z refresh."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Settings", id="app-chrome")
            yield Static("Global Route Defaults", id="settings-title")
            yield Static("Editing: backends.toml (applies when no preset overrides a route)", id="target")
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


    class PresetWorkbenchScreen(Screen):
        BINDINGS = [
            ("a", "activate_preset", "Activate"),
            ("A", "activate_preset", "Use"),
            ("v", "diff_preset", "View diff"),
            ("x", "delete_preset", "Delete"),
            ("ctrl+h", "provider_doctor", "Health"),
            ("ctrl+d", "provider_doctor_deprecated", "Health"),
        ]
        HELP = (
            "Presets\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, Ctrl+P Commands, q Quit.\n"
            "Preview: board shows the preset graph with resolved routes; unused routes stay below.\n"
            "Local: A activate for next /swarmdaddy:do, v view diff, x delete user preset, Ctrl+H health."
        )

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Presets", id="app-chrome")
            with Horizontal():
                yield ListView(id="presets")
                with Vertical(id="preset-profile"):
                    yield PipelineLayerBoard(id="preset-board")
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
            board = self.query_one("#preset-board", PipelineLayerBoard)
            preview = self.query_one("#preview", Static)
            if item is None:
                board.set_message("No preset selected.")
                preview.update("No presets found.")
                return
            try:
                data = load_preset(item.path)
                resolved = resolve_preset_graph(data)
                pipeline = resolved.graph
                model = pipeline_graph_model(pipeline)
                profile = preset_profile_preview(
                    item.name,
                    data,
                    pipeline,
                    width=self._preset_board_width(),
                    height=self._preset_board_height(),
                )
            except Exception as exc:
                board.set_message(f"Preset graph failed to load: {str(exc)[:120]}", failed=True)
                preview.update(f"{item.name} [{item.origin}]\nERROR {exc}")
                return
            board.set_graph(model, pipeline_graph_overlay(), profile.board)
            graph_line = _graph_source_line(item.name, data, resolved)
            lines = [f"{item.name} [{item.origin}]", graph_line, *profile.summary_lines, "", *profile.unused_route_lines]
            preview.update("\n".join(lines))

        def _preset_board_width(self) -> int:
            try:
                width = self.query_one("#preset-board", PipelineLayerBoard).size.width
            except Exception:
                width = 0
            return width if width and width >= 42 else 112

        def _preset_board_height(self) -> int:
            try:
                height = self.query_one("#preset-board", PipelineLayerBoard).size.height
            except Exception:
                height = 0
            return height if height and height >= 1 else 18

        def action_activate_preset(self) -> None:
            item = self._selected()
            if not item:
                return
            target_name = item.name
            try:
                if item.origin == "stock":
                    target_name = suggested_fork_name(item.name, suffix="active")
                    actions.fork_preset(item.name, target_name)
                preset_item = find_preset(target_name)
                if preset_item is None:
                    raise ValueError(f"preset not found: {target_name}")
                preset = load_preset(preset_item.path)
                result, _ = actions.validate_preset_mapping(preset, target_name)
                if not result.ok:
                    raise ValueError("\n".join(result.errors))
                resolved = resolve_preset_graph(preset)
                graph = _graph_source_line(target_name, preset, resolved)
                actions.activate_preset(target_name)
            except Exception as exc:
                self.app.push_screen(MessageModal("Activation refused", str(exc)))
                return
            self.refresh_presets()
            self.app.push_screen(
                MessageModal(
                    "Active preset",
                    f"Active: {target_name}\n{graph}\nNext: /swarmdaddy:do <plan-path>",
                )
            )

        def action_load_preset(self) -> None:
            self.action_activate_preset()

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

        def action_provider_doctor(self) -> None:
            item = self._selected()
            if item is None:
                return
            try:
                from swarm_do.pipeline.providers import format_provider_report, provider_doctor

                preset = load_preset(item.path)
                resolved = resolve_preset_graph(preset)
                if not pipeline_has_provider_stage(resolved.graph):
                    self.app.push_screen(MessageModal("Provider health", "The selected preset has no provider stage."))
                    return
                report = provider_doctor(preset_name=item.name, run_mco=True, run_review=True)
            except Exception as exc:
                self.app.provider_state = "error"
                self.app.push_screen(MessageModal("Provider health", str(exc)))
                _refresh_chrome(self)
                return
            self.app.provider_state = "ok" if report.ok else "error"
            self.app.push_screen(MessageModal(f"Provider health: {item.name}", format_provider_report(report)))
            _refresh_chrome(self)

        def action_provider_doctor_deprecated(self) -> None:
            self.query_one("#status", StatusBar).update("Ctrl+D is deprecated; use Ctrl+H")
            self.action_provider_doctor()


    PresetsScreen = PresetWorkbenchScreen


    class _LegacyPipelineEditor(Screen):
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
            "Graph Editor\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, Ctrl+P Commands, q Quit.\n"
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
            yield AppChrome("Graph Editor", id="app-chrome")
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
                view.set_message("No graph selected.")
                self.query_one("#stage-inspector", StageInspectorView).update("No graph selected.")
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
            if not width or width < 42:
                return 112
            return max(width, BOARD_MIN_WIDTH)

        def _graph_render_height(self) -> int:
            try:
                height = self.query_one("#pipeline-graph", PipelineLayerBoard).size.height
            except Exception:
                height = 0
            return height if height and height >= MIN_BOARD_HEIGHT else 20

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

        def _route_chips_for_current_pipeline(self, pipeline: Mapping[str, Any]) -> Mapping[str, Any]:
            del pipeline
            return {}

        def refresh_graph(self) -> None:
            pipeline = self._current_pipeline()
            view = self.query_one("#pipeline-graph", PipelineLayerBoard)
            if pipeline is None:
                self._graph_model = None
                self._graph_overlay = pipeline_graph_overlay()
                view.set_message("No graph selected.")
                return
            try:
                model = pipeline_graph_model(pipeline)
                overlay = self._overlay_for_model(model)
            except Exception as exc:
                self._graph_model = None
                self._graph_overlay = pipeline_graph_overlay()
                view.set_message(f"Graph failed to load: {str(exc)[:120]}", failed=True)
                return
            self._graph_model = model
            self._graph_overlay = overlay
            route_chips_by_stage = self._route_chips_for_current_pipeline(pipeline)
            view.set_graph(
                model,
                overlay,
                pipeline_board_model(
                    model,
                    overlay,
                    width=self._graph_render_width(),
                    height=self._graph_render_height(),
                    route_chips_by_stage=route_chips_by_stage,
                ),
                route_chips_by_stage,
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
                body = "No graph selected."
            else:
                body = stage_inspector_text(
                    pipeline,
                    stage.stage_id if stage else None,
                    self._graph_overlay,
                    route_chips_by_stage=self._route_chips_for_current_pipeline(pipeline),
                )
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
                self.app.push_screen(MessageModal("Graph missing", row.name))
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

        def _fan_out_lens_target(
            self,
            draft: PipelineEditDraft,
            stage_id: str,
            fan: Mapping[str, Any],
        ) -> tuple[str, str, list[str]] | None:
            if fan.get("variant") == "models" or "routes" in fan:
                self.app.push_screen(MessageModal("Lens edit", "Model-route fan-outs cannot also use prompt lenses. Reset routes first."))
                return None
            role = fan.get("role")
            if not isinstance(role, str) or not role:
                self.app.push_screen(MessageModal("Lens edit", "Fan-out role is invalid."))
                return None
            return "fan_out", role, current_prompt_lens_ids(draft.pipeline, stage_id)

        def _agents_lens_target(
            self,
            draft: PipelineEditDraft,
            stage_id: str,
            agents: list[Any],
        ) -> tuple[str, str, list[str]] | None:
            if not agents or not isinstance(agents[0], dict):
                self.app.push_screen(MessageModal("Lens edit", "The selected agents stage has no editable first agent."))
                return None
            role = agents[0].get("role")
            if not isinstance(role, str) or not role:
                self.app.push_screen(MessageModal("Lens edit", "Agent role is invalid."))
                return None
            current = current_stage_agent_lens_id(draft.pipeline, stage_id, 0)
            return "agents", role, [current] if current else []

        def _selected_lens_target(
            self,
            draft: PipelineEditDraft,
            stage_id: str,
        ) -> tuple[str, str, list[str]] | None:
            mapping = self._selected_stage_mapping()
            fan = mapping.get("fan_out") if isinstance(mapping, dict) else None
            agents = mapping.get("agents") if isinstance(mapping, dict) else None
            if isinstance(fan, dict):
                return self._fan_out_lens_target(draft, stage_id, fan)
            if isinstance(agents, list):
                return self._agents_lens_target(draft, stage_id, agents)
            self.app.push_screen(MessageModal("Lens edit", "Select an agents or fan-out stage to apply prompt lenses."))
            return None

        def _apply_lens_selection(
            self,
            draft: PipelineEditDraft,
            stage_id: str,
            target_kind: str,
            lens_ids: list[str],
        ) -> None:
            if target_kind == "fan_out":
                draft_set_prompt_variant_lenses(draft, stage_id, lens_ids)
                return
            if len(lens_ids) > 1:
                raise ValueError("lens stacking is disabled for normal agents stages; use one lens id")
            draft_set_stage_agent_lens(draft, stage_id, 0, lens_ids[0] if lens_ids else None)

        def action_edit_lenses(self) -> None:
            draft = self._draft_for_selected()
            stage = self._selected_stage_row()
            if draft is None or stage is None:
                return
            target = self._selected_lens_target(draft, stage.stage_id)
            if target is None:
                return
            target_kind, role, current_ids = target
            try:
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
                    self._apply_lens_selection(draft, stage.stage_id, target_kind, lens_ids)
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
                self.app.push_screen(MessageModal("Provider doctor", "The selected graph has no provider stage."))
                return
            if self._draft is not None and self._draft.pipeline_name == row.name and self._draft.dirty:
                self.app.push_screen(MessageModal("Provider doctor", "Save the draft before running provider doctor."))
                return
            body = pipeline_validation_report(row.name, include_provider_doctor=True)
            self.app.push_screen(MessageModal(f"Provider doctor: {row.name}", body))

        def action_show_stage_table(self) -> None:
            if not self._stage_rows:
                self.app.push_screen(MessageModal("Stages", "No stages for the selected graph."))
                return
            body = "\n".join(row.label for row in self._stage_rows)
            self.app.push_screen(MessageModal("Stages", body))

        def action_copy_graph(self) -> None:
            pipeline = self._current_pipeline()
            if pipeline is None:
                return
            model = pipeline_graph_model(pipeline)
            overlay = self._overlay_for_model(model)
            route_chips_by_stage = self._route_chips_for_current_pipeline(pipeline)
            board = pipeline_board_model(
                model,
                overlay,
                width=0,
                height=self._graph_render_height(),
                route_chips_by_stage=route_chips_by_stage,
            )
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
                self.app.push_screen(MessageModal("No draft", "Open a user preset graph draft before saving."))
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
            self.app.push_screen(MessageModal(f"Lint: {row.name}", "\n".join(errors) if errors else "graph OK"))

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
                self.app.push_screen(MessageModal("Graph missing", row.name))
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
                self.app.push_screen(MessageModal("Graph refused", str(exc)))
                return
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

        def action_set_pipeline(self) -> None:
            self.action_activate_pipeline()


    def _route_key_parts(key: str) -> tuple[str, str | None]:
        raw = key.removeprefix("roles.")
        role, sep, maybe_complexity = raw.rpartition(".")
        if sep and maybe_complexity in {"simple", "moderate", "hard"}:
            return role, maybe_complexity
        return raw, None


    def _parse_preset_value(raw: str, current: Any) -> Any:
        text = raw.strip()
        if isinstance(current, bool):
            lowered = text.lower()
            if lowered in {"true", "yes", "1", "on"}:
                return True
            if lowered in {"false", "no", "0", "off"}:
                return False
            raise ValueError("value must be true or false")
        if isinstance(current, int) and not isinstance(current, bool):
            return int(text)
        if isinstance(current, float):
            return float(text)
        if isinstance(current, list):
            return [part.strip() for part in text.split(",") if part.strip()]
        return text


    def _load_default_graph() -> dict[str, Any] | None:
        item = find_pipeline("default")
        if item is None:
            return None
        return load_pipeline(item.path)


    def _active_provider_graph() -> dict[str, Any] | None:
        active = active_preset_name()
        if active:
            item = find_preset(active)
            if item is not None:
                return resolve_preset_graph(load_preset(item.path)).graph
        return _load_default_graph()


    class PresetWorkbenchScreen(_LegacyPipelineEditor):
        BINDINGS = [
            Binding("a", "activate_preset", "Activate"),
            Binding("A", "activate_preset", "Use"),
            Binding("enter", "begin_edit", "Edit"),
            Binding("f", "begin_edit", "Edit"),
            Binding("r", "edit_stage_route", "Route"),
            Binding("b", "edit_branch_route", "Branch"),
            Binding("n", "edit_lenses", "Lens"),
            Binding("o", "overview_or_provider", "Overview"),
            Binding("m", "add_module", "Module"),
            Binding("delete", "remove_stage", "Remove"),
            Binding("ctrl+s", "save_draft", "Save"),
            Binding("escape", "discard_draft", "Discard"),
            Binding("ctrl+h", "provider_doctor", "Health"),
            Binding("ctrl+d", "provider_doctor_deprecated", "Health"),
            Binding("g", "show_graph", "Graph", show=False),
            Binding("t", "show_routing", "Routing", show=False),
            Binding("p", "show_policy", "Policy", show=False),
            Binding("v", "diff_preset", "Diff", show=False),
            Binding("x", "delete_preset", "Delete", show=False),
            Binding("ctrl+r", "reset_selected_route", "Reset route", show=False),
            Binding("ctrl+z", "undo_draft", "Undo", show=False),
            Binding("ctrl+y", "redo_draft", "Redo", show=False),
            Binding("y", "copy_graph", "Copy board", show=False),
        ]
        HELP = (
            "Presets\n\n"
            "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, Ctrl+P Commands, q Quit.\n"
            "Tabs: o Overview, g Graph, t Routing, p Budget & Policy.\n"
            "Graph: r route, b branch, n lens, o provider, m module, Delete remove, Ctrl+S save, Esc discard.\n"
            "Local: A activate for next /swarmdaddy:do, Ctrl+H health."
        )

        def __init__(self) -> None:
            super().__init__()
            self._routing_rows: list[tuple[str, Mapping[str, Any]]] = []
            self._policy_rows: list[tuple[str, str, Any]] = []
            self._selected_preset_error: str | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield AppChrome("Presets", id="app-chrome")
            with Horizontal(id="preset-workbench"):
                yield ListView(id="pipeline-gallery")
                with Vertical(id="preset-content"):
                    with TabbedContent(initial="overview", id="preset-tabs"):
                        with TabPane("Overview", id="overview"):
                            yield Static("", id="preset-overview")
                        with TabPane("Graph", id="graph"):
                            yield PipelineLayerBoard(id="pipeline-graph")
                            with Horizontal(id="pipeline-details"):
                                yield StageInspectorView("", id="stage-inspector")
                                yield Static("", id="validation-rail")
                        with TabPane("Routing", id="routing"):
                            yield DataTable(id="preset-routing")
                        with TabPane("Budget & Policy", id="policy"):
                            yield DataTable(id="preset-policy")
                            yield Static("Enter edits the selected value for user presets.", id="preset-policy-help")
            yield StatusBar(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_pipelines()
            self._show_tab("overview")
            self.call_later(self._show_tab, "overview")
            self.call_after_refresh(self._show_tab, "overview")
            self.set_timer(0.01, lambda: self._show_tab("overview"))
            try:
                self.set_focus(self.query_one("#pipeline-gallery", ListView))
            except Exception:
                pass

        def on_screen_resume(self) -> None:
            self.set_timer(0.01, lambda: self._show_tab("overview"))

        def chrome_context(self) -> str:
            if self._draft is None:
                return "draft=none"
            state = "dirty" if self._draft.dirty else self._draft.status
            return f"draft={state}:{self._draft.preset_name or self._draft.pipeline_name}"

        def _active_tab(self) -> str:
            try:
                return str(self.query_one("#preset-tabs", TabbedContent).active)
            except Exception:
                return "overview"

        def _show_tab(self, tab_id: str) -> None:
            try:
                self.query_one("#preset-tabs", TabbedContent).active = tab_id
                if tab_id == "graph":
                    self.call_after_refresh(self.refresh_graph)
            except Exception:
                pass

        def _selected_preset_item(self) -> Any | None:
            row = self._selected_gallery_row()
            if row is None:
                return None
            return next((item for item in list_presets() if item.name == row.name), None)

        def _selected_preset_data(self) -> tuple[Any, dict[str, Any], Any] | None:
            item = self._selected_preset_item()
            if item is None:
                self._selected_preset_error = None
                return None
            try:
                preset = load_preset(item.path)
                resolved = resolve_preset_graph(preset)
            except Exception as exc:
                self._selected_preset_error = f"{item.name}: {exc}"
                return None
            self._selected_preset_error = None
            return item, preset, resolved

        def _current_pipeline(self) -> dict[str, Any] | None:
            row = self._selected_gallery_row()
            if row is None:
                return None
            if self._draft is not None and self._draft.pipeline_name == row.name:
                return self._draft.pipeline
            selected = self._selected_preset_data()
            if selected is None:
                return None
            return selected[2].graph

        def refresh_pipelines(self) -> None:
            self._gallery_rows = preset_gallery_rows()
            view = self.query_one("#pipeline-gallery", ListView)
            view.clear()
            active = active_preset_name()
            for row in self._gallery_rows:
                view.append(ListItem(Static(_preset_list_renderable(row, active), classes="preset-row")))
            if self._selected_pipeline_name is None and self._gallery_rows:
                self._selected_pipeline_name = active if active and any(row.name == active for row in self._gallery_rows) else self._gallery_rows[0].name
            if self._selected_pipeline_name is not None:
                view.index = next((idx for idx, row in enumerate(self._gallery_rows) if row.name == self._selected_pipeline_name), 0)
            self.refresh_preset()

        def refresh_preset(self) -> None:
            self.refresh_stages()
            self.refresh_overview()
            self.refresh_routing()
            self.refresh_policy()
            self.query_one("#status", StatusBar).refresh_status()
            _refresh_chrome(self)

        def _show_selected_preset_error(self) -> None:
            if not self._selected_preset_error:
                return
            message = f"Preset graph failed to load: {self._selected_preset_error}"
            try:
                self.query_one("#pipeline-graph", PipelineLayerBoard).set_message(message, failed=True)
                self.query_one("#stage-inspector", StageInspectorView).update(message)
                self.query_one("#validation-rail", Static).update(f"validation: unavailable\nERROR {self._selected_preset_error}")
            except Exception:
                pass

        def refresh_graph(self) -> None:
            super().refresh_graph()
            self._show_selected_preset_error()

        def _route_chips_for_current_pipeline(self, pipeline: Mapping[str, Any]) -> Mapping[str, Any]:
            selected = self._selected_preset_data()
            if selected is None:
                return {}
            item, preset, _resolved = selected
            return pipeline_route_chips_by_stage(
                pipeline,
                BackendResolver(preset_name=item.name, preset_data=preset),
            )

        def refresh_stages(self) -> None:
            super().refresh_stages()
            self._show_selected_preset_error()
            self.refresh_overview()

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            if event.list_view.id != "pipeline-gallery":
                return
            index = event.list_view.index or 0
            if self._gallery_rows:
                self._selected_pipeline_name = self._gallery_rows[min(max(index, 0), len(self._gallery_rows) - 1)].name
                self.selected_stage_id = None
                self._draft = None
            self.refresh_preset()
            if self._active_tab() == "graph":
                self.call_after_refresh(self.refresh_graph)

        def refresh_overview(self) -> None:
            try:
                overview = self.query_one("#preset-overview", Static)
            except Exception:
                return
            selected = self._selected_preset_data()
            if selected is None:
                if self._selected_preset_error:
                    overview.update(f"ERROR {self._selected_preset_error}")
                else:
                    overview.update("No preset selected.")
                return
            item, preset, resolved = selected
            pipeline = self._current_pipeline() or resolved.graph
            row = self._selected_gallery_row()
            try:
                profile = preset_profile_preview(item.name, preset, pipeline, width=96, height=12)
            except Exception as exc:
                profile = None
                validation = f"ERROR profile unavailable: {exc}"
            else:
                validation = pipeline_validation_report(item.name)
            overview.update(_preset_overview_renderable(row, item, preset, resolved, pipeline, profile, validation))

        def refresh_routing(self) -> None:
            try:
                table = self.query_one("#preset-routing", DataTable)
            except Exception:
                return
            table.clear(columns=True)
            table.add_columns("", "route", "backend", "model", "effort")
            self._routing_rows = []
            selected = self._selected_preset_data()
            if selected is None:
                return
            preset = selected[1]
            routing = preset.get("routing") if isinstance(preset.get("routing"), Mapping) else {}
            for key in sorted(routing):
                value = routing[key]
                if not isinstance(value, Mapping):
                    continue
                self._routing_rows.append((key, value))
                backend = str(value.get("backend", ""))
                table.add_row(
                    Text("●", style=f"bold {_backend_style(backend)}"),
                    key,
                    Text(backend, style=_backend_style(backend)),
                    str(value.get("model", "")),
                    str(value.get("effort", "")),
                )
            if not self._routing_rows:
                table.add_row(Text("○", style=_muted_style()), "none", "", "", "")

        def refresh_policy(self) -> None:
            try:
                table = self.query_one("#preset-policy", DataTable)
            except Exception:
                return
            table.clear(columns=True)
            table.add_columns("section", "key", "value")
            self._policy_rows = []
            selected = self._selected_preset_data()
            if selected is None:
                return
            preset = selected[1]
            for section in ("budget", "decompose", "mem_prime", "review_providers"):
                value = preset.get(section)
                if not isinstance(value, Mapping):
                    continue
                for key in sorted(value):
                    current = value[key]
                    self._policy_rows.append((section, key, current))
                    rendered = ", ".join(str(part) for part in current) if isinstance(current, list) else str(current)
                    table.add_row(section, key, rendered)

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

        def _graph_edit_ready(self, retry: Any) -> bool:
            selected = self._selected_preset_data()
            if selected is None:
                return False
            item, preset, resolved = selected
            if item.origin != "user":
                self.app.push_screen(MessageModal("Stock preset", "Stock preset - use Activate to create a user preset before editing."))
                return False
            if resolved.source == "inline-snapshot":
                return True

            def done(confirmed: bool) -> None:
                if not confirmed:
                    return
                try:
                    actions.detach_preset_graph(item.name)
                    self._draft = start_pipeline_draft(item.name, preset_name=item.name)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Detach refused", str(exc)))
                    return
                self.refresh_preset()
                retry()

            self.app.push_screen(
                ConfirmModal(
                    "Detach graph",
                    f"This preset follows the {resolved.source_name} stock graph. Detach to a local snapshot so you can edit?",
                    confirm_label="Detach",
                ),
                done,
            )
            return False

        def _draft_for_selected(self) -> PipelineEditDraft | None:
            row = self._selected_gallery_row()
            if row is None:
                return None
            if self._draft is not None and self._draft.pipeline_name == row.name:
                return self._draft
            selected = self._selected_preset_data()
            if selected is None:
                return None
            item, _preset, resolved = selected
            if item.origin != "user":
                self.app.push_screen(MessageModal("Stock preset", "Stock preset - use Activate to create a user preset before editing."))
                return None
            if resolved.source != "inline-snapshot":
                return None
            try:
                self._draft = start_pipeline_draft(item.name, preset_name=item.name)
            except Exception as exc:
                self.app.push_screen(MessageModal("Draft refused", str(exc)))
                return None
            self.refresh_stages()
            return self._draft

        def action_show_graph(self) -> None:
            self._show_tab("graph")

        def action_show_routing(self) -> None:
            self._show_tab("routing")

        def action_show_policy(self) -> None:
            self._show_tab("policy")

        def action_overview_or_provider(self) -> None:
            if self._active_tab() == "graph":
                mapping = self._selected_stage_mapping()
                if isinstance(mapping, dict) and isinstance(mapping.get("provider"), dict):
                    self.action_edit_provider()
                    return
                self._show_tab("overview")
            else:
                self._show_tab("overview")

        def action_begin_edit(self) -> None:
            tab = self._active_tab()
            if tab == "routing":
                self.action_edit_route()
                return
            if tab == "policy":
                self.action_edit_policy()
                return
            if tab != "graph":
                self._show_tab("graph")
                return
            if not self._graph_edit_ready(self.action_begin_edit):
                return
            if self._draft_for_selected() is not None:
                self.app.push_screen(MessageModal("Draft ready", "Editing this preset graph in memory. Save writes after validation."))

        def action_edit_stage_route(self) -> None:
            if not self._graph_edit_ready(self.action_edit_stage_route):
                return
            super().action_edit_stage_route()

        def action_edit_branch_route(self) -> None:
            if not self._graph_edit_ready(self.action_edit_branch_route):
                return
            super().action_edit_branch_route()

        def action_edit_lenses(self) -> None:
            if not self._graph_edit_ready(self.action_edit_lenses):
                return
            super().action_edit_lenses()

        def action_edit_provider(self) -> None:
            if not self._graph_edit_ready(self.action_edit_provider):
                return
            super().action_edit_provider()

        def action_add_module(self) -> None:
            if not self._graph_edit_ready(self.action_add_module):
                return
            super().action_add_module()

        def action_remove_stage(self) -> None:
            if not self._graph_edit_ready(self.action_remove_stage):
                return
            super().action_remove_stage()

        def action_reset_selected_route(self) -> None:
            if not self._graph_edit_ready(self.action_reset_selected_route):
                return
            super().action_reset_selected_route()

        def action_save_draft(self) -> None:
            if self._draft is None:
                self.app.push_screen(MessageModal("No draft", "Open a user preset graph draft before saving."))
                return
            result = validate_pipeline_draft(self._draft)
            if result.errors:
                self._draft.mark_invalid("; ".join(result.errors))
                self.refresh_validation_rail()
                self.app.push_screen(MessageModal("Save blocked", "\n".join(result.errors)))
                return
            try:
                path = actions.save_user_preset_graph(
                    self._draft.preset_name or self._draft.pipeline_name,
                    self._draft.pipeline,
                    expected_hash=self._draft.original_disk_hash,
                )
                saved = load_preset(path)
                saved_hash = resolve_preset_graph(saved).source_hash
            except Exception as exc:
                self.app.push_screen(MessageModal("Save failed", str(exc)))
                return
            self._draft.mark_saved(saved_hash)
            self.refresh_pipelines()
            self.app.push_screen(MessageModal("Saved", f"{self._draft.preset_name or self._draft.pipeline_name}.toml passed validation and was written."))

        def action_discard_draft(self) -> None:
            if self._draft is None:
                return
            name = self._draft.preset_name or self._draft.pipeline_name
            self._draft = None
            self.refresh_preset()
            self.app.push_screen(MessageModal("Draft discarded", f"Closed in-memory graph edits for {name}."))

        def _require_user_preset(self) -> Any | None:
            item = self._selected_preset_item()
            if item is None:
                return None
            if item.origin != "user":
                self.app.push_screen(MessageModal("Stock preset", "Stock preset - use Activate to create a user preset before editing."))
                return None
            return item

        def action_edit_route(self) -> None:
            item = self._require_user_preset()
            if item is None or not self._routing_rows:
                return
            table = self.query_one("#preset-routing", DataTable)
            row_index = getattr(table, "cursor_row", 0)
            key, value = self._routing_rows[min(max(row_index, 0), len(self._routing_rows) - 1)]
            role, complexity = _route_key_parts(key)
            current = (str(value.get("backend", "")), str(value.get("model", "")), str(value.get("effort", "medium")))

            def done(route: tuple[str, str, str] | None) -> None:
                if route is None:
                    return
                try:
                    actions.set_user_preset_route(item.name, role, complexity, route[0], route[1], route[2])
                except Exception as exc:
                    self.app.push_screen(MessageModal("Route refused", str(exc)))
                    return
                self.refresh_preset()

            self.app.push_screen(RouteModal(role, complexity, current), done)

        def action_edit_policy(self) -> None:
            item = self._require_user_preset()
            if item is None or not self._policy_rows:
                return
            table = self.query_one("#preset-policy", DataTable)
            row_index = getattr(table, "cursor_row", 0)
            section, key, current = self._policy_rows[min(max(row_index, 0), len(self._policy_rows) - 1)]

            def done(raw: str | None) -> None:
                if raw is None:
                    return
                try:
                    value = _parse_preset_value(raw, current)
                    preset = load_preset(item.path)
                    table_data = preset.setdefault(section, {})
                    if not isinstance(table_data, dict):
                        raise ValueError(f"preset {section} must be a table")
                    table_data[key] = value
                    result, _ = actions.validate_preset_mapping(preset, item.name)
                    if not result.ok:
                        raise ValueError("; ".join(result.errors))
                    actions.atomic_write_text(item.path, actions.render_toml(preset))
                except Exception as exc:
                    self.app.push_screen(MessageModal("Value refused", str(exc)))
                    return
                self.refresh_preset()

            self.app.push_screen(PresetValueModal(f"{section}.{key}", current), done)

        def action_activate_preset(self) -> None:
            row = self._selected_gallery_row()
            item = self._selected_preset_item()
            if row is None or item is None:
                return
            target_name = item.name
            try:
                if item.origin == "stock":
                    target_name = suggested_fork_name(item.name, suffix="active")
                    actions.fork_preset(item.name, target_name)
                preset_item = find_preset(target_name)
                if preset_item is None:
                    raise ValueError(f"preset not found: {target_name}")
                preset = load_preset(preset_item.path)
                result, _ = actions.validate_preset_mapping(preset, target_name)
                if not result.ok:
                    raise ValueError("\n".join(result.errors))
                resolved = resolve_preset_graph(preset)
                graph = _graph_source_line(target_name, preset, resolved)
                actions.activate_preset(target_name)
                self._selected_pipeline_name = target_name
            except Exception as exc:
                self.app.push_screen(MessageModal("Activation refused", str(exc)))
                return
            self.refresh_pipelines()
            self.app.push_screen(MessageModal("Active preset", f"Active: {target_name}\n{graph}\nNext: /swarmdaddy:do <plan-path>"))

        def action_load_preset(self) -> None:
            self.action_activate_preset()

        def action_diff_preset(self) -> None:
            item = self._selected_preset_item()
            if item is None:
                return
            result = subprocess.run(
                [str(Path(__file__).resolve().parents[3] / "bin" / "swarm"), "preset", "diff", item.name],
                check=False,
                capture_output=True,
                text=True,
            )
            self.app.push_screen(MessageModal(f"Diff: {item.name}", result.stdout or result.stderr or "No diff."))

        def action_delete_preset(self) -> None:
            item = self._selected_preset_item()
            if item is None:
                return
            try:
                actions.delete_user_preset(item.name)
            except Exception as exc:
                self.app.push_screen(MessageModal("Delete refused", str(exc)))
                return
            self._draft = None
            self._selected_pipeline_name = None
            self.refresh_pipelines()

        def _reattach_stock_name(self) -> str | None:
            selected = self._selected_preset_data()
            if selected is None:
                return None
            item, _preset, resolved = selected
            if item.origin != "user" or resolved.source != "inline-snapshot" or not resolved.lineage_name:
                return None
            stock = find_pipeline(resolved.lineage_name)
            if stock is None or stock.origin != "stock":
                return None
            return resolved.lineage_name

        def action_reattach_graph(self) -> None:
            item = self._selected_preset_item()
            stock_name = self._reattach_stock_name()
            if item is None or stock_name is None:
                self.app.push_screen(MessageModal("Re-attach unavailable", "The selected preset has no resolvable upstream graph."))
                return
            selected = self._selected_preset_data()
            if selected is None:
                return
            resolved = selected[2]
            stock_item = find_pipeline(stock_name)
            stock_graph = load_pipeline(stock_item.path) if stock_item is not None else {}
            status = "No graph differences detected." if stock_graph == resolved.graph else "Local graph edits will be discarded."

            def done(confirmed: bool) -> None:
                if not confirmed:
                    return
                try:
                    actions.reattach_preset_graph(item.name, stock_name)
                except Exception as exc:
                    self.app.push_screen(MessageModal("Re-attach refused", str(exc)))
                    return
                self._draft = None
                self.refresh_pipelines()
                self.app.push_screen(MessageModal("Graph re-attached", f"{item.name} now follows {stock_name}."))

            self.app.push_screen(
                ConfirmModal(
                    f"Re-attach graph to {stock_name}",
                    f"{status}\n\nRe-attaching restores stock-ref to {stock_name} and removes the inline graph snapshot.",
                    confirm_label="Re-attach",
                ),
                done,
            )

        def action_provider_doctor(self) -> None:
            row = self._selected_gallery_row()
            pipeline = self._current_pipeline()
            if row is None or pipeline is None:
                return
            if not pipeline_has_provider_stage(pipeline):
                self.app.push_screen(MessageModal("Provider health", "The selected preset has no provider stage."))
                return
            if self._draft is not None and self._draft.pipeline_name == row.name and self._draft.dirty:
                self.app.push_screen(MessageModal("Provider health", "Save the draft before running provider health."))
                return
            try:
                from swarm_do.pipeline.providers import format_provider_report, provider_doctor

                report = provider_doctor(preset_name=row.name, run_mco=True, run_review=True)
            except Exception as exc:
                self.app.provider_state = "error"
                self.app.push_screen(MessageModal("Provider health", str(exc)))
                _refresh_chrome(self)
                return
            self.app.provider_state = "ok" if report.ok else "error"
            self.app.push_screen(MessageModal(f"Provider health: {row.name}", format_provider_report(report)))
            _refresh_chrome(self)

        def action_provider_doctor_deprecated(self) -> None:
            self.query_one("#status", StatusBar).update("Ctrl+D is deprecated; use Ctrl+H")
            self.action_provider_doctor()


    PresetsScreen = PresetWorkbenchScreen


    class SwarmTui(App):
        CSS_PATH = "app.tcss"
        TITLE = "SwarmDaddy"
        BINDINGS = [
            Binding("1", "dashboard", "Dashboard"),
            Binding("2", "runs", "Runs"),
            Binding("3", "presets", "Presets"),
            Binding("4", "settings", "Settings"),
            Binding("question_mark", "help_current", "Help", key_display="?"),
            Binding("q", "quit", "Quit"),
        ]

        def on_mount(self) -> None:
            self.register_theme(POSTING_GALAXY_THEME)
            self.theme = POSTING_GALAXY_THEME_NAME
            self.provider_state = "unchecked"
            self.install_screen(DashboardScreen(), name="dashboard")
            self.install_screen(SettingsScreen(), name="settings")
            self.install_screen(PresetWorkbenchScreen(), name="presets")
            self.push_screen("dashboard")

        def on_unmount(self) -> None:
            active = active_preset_name()
            if active:
                print(f"Active: {active}")
            else:
                print("Active: default fallback (no preset chosen - that's fine)")
            print("Next: /swarmdaddy:do <plan-path>")

        def action_dashboard(self) -> None:
            self.switch_screen("dashboard")

        def action_runs(self) -> None:
            self.switch_screen("dashboard")

        def action_settings(self) -> None:
            self.switch_screen("settings")

        def action_presets(self) -> None:
            self.switch_screen("presets")

        def action_pipelines(self) -> None:
            self.switch_screen("presets")

        def action_help_current(self) -> None:
            screen = self.screen
            body = getattr(screen, "HELP", None)
            if not body:
                body = (
                    "SwarmDaddy\n\n"
                    "Global: 1 Dashboard, 2 Runs, 3 Presets, 4 Settings, "
                    "Ctrl+P Commands, q Quit."
                )
            self.push_screen(MessageModal("Help", body))

        def get_system_commands(self, screen: Screen) -> Any:
            yield from super().get_system_commands(screen)
            yield SystemCommand("Go to Dashboard", "Open the operator dashboard", self.action_dashboard)
            yield SystemCommand("Go to Runs", "Open the dashboard runs table", self.action_runs)
            yield SystemCommand("Go to Presets", "Open preset workbench", self.action_presets)
            yield SystemCommand("Go to Settings", "Open effective role routes", self.action_settings)
            yield SystemCommand("Show Help", "Show contextual help for the current screen", self.action_help_current)
            if isinstance(screen, _LegacyPipelineEditor) and not isinstance(screen, PresetWorkbenchScreen):
                yield SystemCommand("Focus Graph Board", "Move keyboard focus to the board", screen.action_focus_graph)
                yield SystemCommand("Focus Stage Details", "Move keyboard focus to the selected stage details", screen.action_focus_stage_details)
                yield SystemCommand("Show Stage Table", "Show the selected graph stages as rows", screen.action_show_stage_table)
                yield SystemCommand("Validate Selected Graph", "Validate the selected graph", screen.action_validate_pipeline)
                yield SystemCommand("Fork/Edit Selected Graph", "Fork or edit the selected graph", screen.action_begin_edit)
                yield SystemCommand("Save Graph Draft", "Save the current in-memory graph draft", screen.action_save_draft)
                yield SystemCommand("Discard Graph Draft", "Discard the current in-memory graph draft", screen.action_discard_draft)
                yield SystemCommand("Copy Graph Board", "Copy the selected graph board as text", screen.action_copy_graph)
                yield SystemCommand("Run Provider Doctor", "Check provider readiness for this graph", screen.action_provider_doctor)
            if isinstance(screen, SettingsScreen):
                yield SystemCommand("Edit selected route", "Edit the selected effective role route", screen.action_edit_route)
            if isinstance(screen, PresetWorkbenchScreen):
                yield SystemCommand("Activate selected preset", "Use this preset for next /swarmdaddy:do", screen.action_activate_preset)
                yield SystemCommand("View selected preset diff", "Open the selected preset diff", screen.action_diff_preset)
                stock_name = screen._reattach_stock_name()
                if stock_name:
                    yield SystemCommand(
                        f"Re-attach graph to upstream {stock_name}",
                        "Discard local graph edits and follow the upstream stock graph",
                        screen.action_reattach_graph,
                    )


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
