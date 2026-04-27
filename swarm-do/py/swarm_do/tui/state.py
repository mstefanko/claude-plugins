"""Shared state readers for the SwarmDaddy TUI.

This module intentionally has no Textual dependency so it can be unit-tested
without installing the optional TUI stack.
"""

from __future__ import annotations

import dataclasses
import copy
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from swarm_do.pipeline.actions import InFlightRun, in_flight_dir, load_in_flight
from swarm_do.pipeline.catalog import (
    compile_prompt_variant_fan_out,
    get_lens,
    get_module,
    lens_for_variant,
    list_modules,
    list_prompt_lenses,
    pipeline_activation_error,
    pipeline_profile_for,
    validate_prompt_lens_selection,
)
from swarm_do.pipeline.context import current_context
from swarm_do.pipeline.diff import diff_user_pipeline, stock_drift_for_pipeline
from swarm_do.pipeline.editing import (
    find_stage_by_id as _stage_by_id,
    mutable_mco_provider_stage as _mutable_mco_provider_stage,
    mutable_provider_review_stage as _mutable_provider_review_stage,
    mutable_stage_agent as _mutable_stage_agent,
    mutable_stage_by_id as _mutable_stage_by_id,
    mutable_stage_fan_out as _mutable_stage_fan_out,
    normalize_mco_providers as _normalize_mco_providers,
    normalize_review_providers as _normalize_review_providers,
    provider_failure_tolerance as _provider_failure_tolerance,
    validate_mco_timeout as _validate_mco_timeout,
    validate_provider_review_max_parallel as _validate_provider_review_max_parallel,
    validate_provider_review_selection as _validate_provider_review_selection,
)
from swarm_do.pipeline.engine import topological_layers
from swarm_do.pipeline.graph_source import resolve_preset_graph
from swarm_do.pipeline.paths import resolve_data_dir
from swarm_do.pipeline.providers import ProviderDoctorReport, provider_doctor
from swarm_do.pipeline.registry import find_pipeline, list_pipelines, list_presets, load_pipeline, load_preset, sha256_file
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, active_preset_name
from swarm_do.pipeline.validation import (
    MCO_PROVIDERS,
    REVIEW_PROVIDER_SELECTIONS,
    TOLERANCE_MODES,
    ValidationResult,
    invariant_errors,
    role_existence_errors,
    route_resolution_errors,
    schema_lint_pipeline,
    validate_preset_and_pipeline,
    validate_preset_mapping,
    variant_existence_errors,
)


@dataclasses.dataclass(frozen=True)
class StatusSummary:
    preset: str
    pipeline: str
    runs_today: int
    cost_today: float | None
    last_429_claude: str | None
    last_429_codex: str | None
    latest_checkpoint: dict[str, Any] | None = None
    latest_observation: dict[str, Any] | None = None
    getting_started_visible: bool = False

    def render(self) -> str:
        cost = f"${self.cost_today:.4f}" if self.cost_today is not None else "n/a"
        claude = self.last_429_claude or "n/a"
        codex = self.last_429_codex or "n/a"
        rendered = (
            f"preset={self.preset} graph={self.pipeline} runs_today={self.runs_today} "
            f"cost_today={cost} last_429_claude={claude} last_429_codex={codex}"
        )
        if self.latest_checkpoint:
            rendered += (
                " latest_checkpoint="
                f"{self.latest_checkpoint.get('run_id', 'n/a')}:"
                f"{self.latest_checkpoint.get('phase_id') or 'n/a'}"
            )
        if self.latest_observation:
            rendered += (
                " latest_observation="
                f"{self.latest_observation.get('event_type', 'unknown')}:"
                f"{self.latest_observation.get('source') or 'n/a'}"
            )
        return rendered


ACCEPTED_MAINTAINER_ACTIONS = frozenset(
    {"fixed_in_same_pr", "followup_issue", "followup_pr", "hotfix_within_14d"}
)


@dataclasses.dataclass(frozen=True)
class OutcomeDashboardSummary:
    since_days: int
    run_count: int
    successful_runs: int
    findings_count: int
    outcome_count: int
    accepted_findings: int
    ignored_findings: int
    handoff_count: int
    nonzero_exit_count: int
    mean_wall_seconds: float | None
    mean_cost_usd: float | None
    top_accepted_role: str | None
    top_accepted_role_count: int
    top_pipeline: str | None
    top_pipeline_count: int
    report_commands: tuple[str, ...]

    def render(self) -> str:
        accepted = f"{self.accepted_findings}/{self.outcome_count}" if self.outcome_count else "0/0"
        top_role = (
            f"{self.top_accepted_role}({self.top_accepted_role_count})"
            if self.top_accepted_role
            else "n/a"
        )
        top_pipeline = (
            f"{self.top_pipeline}({self.top_pipeline_count})"
            if self.top_pipeline
            else "n/a"
        )
        return "\n".join(
            [
                f"Outcome Signals ({self.since_days}d)",
                (
                    f"findings={self.findings_count} accepted={accepted} "
                    f"ignored_rate={_format_rate(self.ignored_findings, self.outcome_count)} "
                    f"top_role={top_role}"
                ),
                (
                    f"runs={self.run_count} success={_format_rate(self.successful_runs, self.run_count)} "
                    f"rework=handoffs:{self.handoff_count} exits:{self.nonzero_exit_count}"
                ),
                (
                    f"wall_mean={_format_seconds_short(self.mean_wall_seconds)} "
                    f"cost_mean={_format_usd(self.mean_cost_usd)} top_pipeline={top_pipeline}"
                ),
                f"report: {self.report_commands[0]}",
                f"compare: {self.report_commands[1]}",
                f"outcomes: {self.report_commands[-1]}",
            ]
        )


PIPELINE_INTENTS: dict[str, str] = {
    "brainstorm": "brainstorm",
    "codebase-map": "research",
    "default": "implement",
    "design": "design",
    "lightweight": "implement",
    "hybrid-review": "review",
    "repair-loop": "implement",
    "mco-review-lab": "mco-assisted review",
    "compete": "competitive implementation",
    "research": "research",
    "research-orchestrator": "research",
    "review": "review",
    "review-strict": "review",
    "smart-friend": "implement",
    "ultra-plan": "design",
}
PIPELINE_INTENT_ORDER = (
    "brainstorm",
    "research",
    "design",
    "implement",
    "review",
    "competitive implementation",
    "mco-assisted review",
    "custom",
)


@dataclasses.dataclass(frozen=True)
class PipelineGalleryRow:
    intent: str
    name: str
    origin: str
    preset: str | None
    description: str

    @property
    def label(self) -> str:
        preset = f" preset={self.preset}" if self.preset else ""
        return f"{self.intent}: {self.name} [{self.origin}]{preset}"


@dataclasses.dataclass(frozen=True)
class StageRow:
    layer: int
    stage_id: str
    kind: str
    summary: str
    depends_on: tuple[str, ...]

    @property
    def label(self) -> str:
        deps = ",".join(self.depends_on) if self.depends_on else "-"
        return f"L{self.layer} {self.stage_id} [{self.kind}] deps={deps} {self.summary}"


@dataclasses.dataclass(frozen=True)
class PipelineGraphNode:
    stage_id: str
    layer: int
    kind: str
    lane: str
    shape: str
    title: str
    subtitle: str
    depends_on: tuple[str, ...]
    outgoing: tuple[str, ...]
    fan_out_count: int | None
    fan_out_variant: str | None
    merge_agent: str | None
    provider_type: str | None
    tolerance: str | None
    warnings: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class PipelineGraphEdge:
    source: str
    target: str


@dataclasses.dataclass(frozen=True)
class PipelineGraphModel:
    nodes: tuple[PipelineGraphNode, ...]
    edges: tuple[PipelineGraphEdge, ...]
    layers: tuple[tuple[str, ...], ...]
    pipeline_name: str | None = None
    warnings: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class PipelineGraphOverlay:
    selected_stage_id: str | None
    stage_statuses: Mapping[str, str]
    dirty_stage_ids: frozenset[str]
    critical_stage_ids: frozenset[str]
    highlighted_stage_ids: frozenset[str]


@dataclasses.dataclass(frozen=True)
class PipelineBoardCard:
    stage_id: str
    layer: int
    title: str
    subtitle: str
    badges: tuple[str, ...]
    dependency_label: str | None
    outgoing_label: str | None
    kind: str
    lane: str
    selected: bool
    dirty: bool
    critical: bool
    status: str | None
    warnings: tuple[str, ...]
    route_chips: tuple["PipelineRouteChip", ...] = ()


@dataclasses.dataclass(frozen=True)
class PipelineRouteChip:
    label: str
    backend: str
    model: str
    effort: str
    source: str
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class PipelineBoardColumn:
    index: int
    label: str
    cards: tuple[PipelineBoardCard, ...]


@dataclasses.dataclass(frozen=True)
class PipelineBoardModel:
    columns: tuple[PipelineBoardColumn, ...]
    mode: str
    fallback_lines: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class PresetProfilePreview:
    board: PipelineBoardModel
    summary_lines: tuple[str, ...]
    unused_route_lines: tuple[str, ...]


BOARD_MIN_WIDTH = 96
COMPACT_MIN_WIDTH = 72
MIN_BOARD_HEIGHT = 14

STATUS_TO_BADGE = {
    "queued": "QUEUED",
    "running": "RUN",
    "done": "DONE",
    "failed": "FAILED",
}


@dataclasses.dataclass
class PipelineEditDraft:
    pipeline_name: str
    preset_name: str | None
    origin: str
    pipeline: dict[str, Any]
    original_pipeline: dict[str, Any]
    original_disk_hash: str
    status: str = "saved"
    message: str = "draft ready"
    undo_stack: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    redo_stack: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return self.pipeline != self.original_pipeline

    def mark_saved(self, disk_hash: str | None = None) -> None:
        self.original_pipeline = copy.deepcopy(self.pipeline)
        if disk_hash is not None:
            self.original_disk_hash = disk_hash
        self.status = "saved"
        self.message = "saved"
        self.undo_stack.clear()
        self.redo_stack.clear()

    def mark_invalid(self, message: str) -> None:
        self.status = "invalid"
        self.message = message

    def checkpoint(self, message: str) -> None:
        self.undo_stack.append(copy.deepcopy(self.pipeline))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.status = "dirty"
        self.message = message

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(copy.deepcopy(self.pipeline))
        self.pipeline = self.undo_stack.pop()
        self.status = "dirty" if self.dirty else "saved"
        self.message = "undo"
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(copy.deepcopy(self.pipeline))
        self.pipeline = self.redo_stack.pop()
        self.status = "dirty"
        self.message = "redo"
        return True


def pipeline_intent(name: str, pipeline: Mapping[str, Any]) -> str:
    source = pipeline.get("forked_from") if isinstance(pipeline.get("forked_from"), str) else None
    return PIPELINE_INTENTS.get(name) or (PIPELINE_INTENTS.get(source) if source else None) or "custom"


def pipeline_gallery_rows() -> list[PipelineGalleryRow]:
    rows: list[PipelineGalleryRow] = []
    for item in list_presets():
        try:
            preset = load_preset(item.path)
            resolved = resolve_preset_graph(preset)
            pipeline = resolved.graph
        except Exception as exc:
            rows.append(PipelineGalleryRow("custom", item.name, item.origin, item.name, f"unreadable: {exc}"))
            continue
        rows.append(
            PipelineGalleryRow(
                intent=pipeline_intent(resolved.source_name or item.name, pipeline),
                name=item.name,
                origin=item.origin,
                preset=item.name,
                description=str(pipeline.get("description") or ""),
            )
        )
    order = {intent: idx for idx, intent in enumerate(PIPELINE_INTENT_ORDER)}
    origin_order = {"stock": 0, "experiment": 1, "user": 2, "path": 3}
    return sorted(rows, key=lambda row: (order.get(row.intent, 99), row.intent, origin_order.get(row.origin, 9), row.name))


def preset_gallery_rows() -> list[PipelineGalleryRow]:
    return pipeline_gallery_rows()


def _stage_kind(stage: Mapping[str, Any]) -> str:
    if "fan_out" in stage:
        return "fan_out"
    if "provider" in stage:
        return "provider"
    return "agents"


def _stage_summary(stage: Mapping[str, Any]) -> str:
    if isinstance(stage.get("fan_out"), Mapping):
        fan = stage["fan_out"]
        return f"{fan.get('role')} x{fan.get('count')} {fan.get('variant')}"
    if isinstance(stage.get("provider"), Mapping):
        provider = stage["provider"]
        provider_type = provider.get("type")
        if provider_type == "swarm-review":
            return (
                f"{provider_type} {provider.get('command')} "
                f"selection={provider.get('selection', 'auto')} "
                f"max_parallel={provider.get('max_parallel', 4)}"
            )
        return f"{provider_type} {provider.get('command')} providers={provider.get('providers')}"
    roles = [str(agent.get("role") or "<missing-role>") for agent in stage.get("agents") or [] if isinstance(agent, Mapping)]
    return ", ".join(roles) if roles else "no agents"


def pipeline_stage_rows(pipeline: Mapping[str, Any]) -> list[StageRow]:
    stages = [stage for stage in pipeline.get("stages") or [] if isinstance(stage, Mapping)]
    stage_by_id = {str(stage.get("id")): stage for stage in stages if isinstance(stage.get("id"), str)}
    try:
        ordered = [
            (layer_no, stage_id)
            for layer_no, layer in enumerate(topological_layers(pipeline), 1)
            for stage_id in layer
        ]
    except Exception:
        ordered = [(idx + 1, str(stage.get("id") or f"<stage-{idx}>")) for idx, stage in enumerate(stages)]

    rows: list[StageRow] = []
    for layer_no, stage_id in ordered:
        stage = stage_by_id.get(stage_id)
        if stage is None:
            continue
        deps = tuple(str(dep) for dep in (stage.get("depends_on") or []))
        rows.append(StageRow(layer_no, stage_id, _stage_kind(stage), _stage_summary(stage), deps))
    return rows


def pipeline_graph_overlay(
    *,
    selected_stage_id: str | None = None,
    stage_statuses: Mapping[str, str] | None = None,
    dirty_stage_ids: frozenset[str] | set[str] | tuple[str, ...] | list[str] | None = None,
    critical_stage_ids: frozenset[str] | set[str] | tuple[str, ...] | list[str] | None = None,
    highlighted_stage_ids: frozenset[str] | set[str] | tuple[str, ...] | list[str] | None = None,
) -> PipelineGraphOverlay:
    return PipelineGraphOverlay(
        selected_stage_id=selected_stage_id,
        stage_statuses=dict(stage_statuses or {}),
        dirty_stage_ids=frozenset(dirty_stage_ids or ()),
        critical_stage_ids=frozenset(critical_stage_ids or ()),
        highlighted_stage_ids=frozenset(highlighted_stage_ids or ()),
    )


def pipeline_graph_model(pipeline: Mapping[str, Any]) -> PipelineGraphModel:
    stages = [stage for stage in pipeline.get("stages") or [] if isinstance(stage, Mapping)]
    stage_by_id: dict[str, Mapping[str, Any]] = {}
    stage_ids: list[str] = []
    model_warnings: list[str] = []
    node_warnings: dict[str, list[str]] = {}

    for idx, stage in enumerate(stages):
        raw_id = stage.get("id")
        stage_id = raw_id if isinstance(raw_id, str) and raw_id else f"<stage-{idx + 1}>"
        if stage_id in stage_by_id:
            model_warnings.append(f"duplicate stage id: {stage_id}")
            node_warnings.setdefault(stage_id, []).append("duplicate stage id")
            continue
        stage_by_id[stage_id] = stage
        stage_ids.append(stage_id)
        if stage_id != raw_id:
            node_warnings.setdefault(stage_id, []).append("stage id is missing or invalid")

    known_ids = set(stage_ids)
    deps_by_id: dict[str, tuple[str, ...]] = {}
    edges: list[PipelineGraphEdge] = []
    for stage_id in stage_ids:
        stage = stage_by_id[stage_id]
        deps = tuple(str(dep) for dep in (stage.get("depends_on") or []))
        deps_by_id[stage_id] = deps
        for dep in deps:
            if dep in known_ids:
                edges.append(PipelineGraphEdge(dep, stage_id))
            else:
                node_warnings.setdefault(stage_id, []).append(f"depends_on references unknown stage {dep}")

    lane_by_id = {stage_id: _graph_lane(stage_by_id[stage_id]) for stage_id in stage_ids}
    try:
        raw_layers = topological_layers({"stages": [stage_by_id[stage_id] for stage_id in stage_ids]})
        layers = _reorder_graph_layers(raw_layers, deps_by_id, lane_by_id)
    except Exception as exc:
        model_warnings.append(str(exc))
        layers = tuple((stage_id,) for stage_id in stage_ids)

    layer_for_id = {
        stage_id: layer_index
        for layer_index, layer in enumerate(layers, 1)
        for stage_id in layer
    }
    order_for_id = {
        stage_id: (layer_index, node_index)
        for layer_index, layer in enumerate(layers, 1)
        for node_index, stage_id in enumerate(layer)
    }
    outgoing_by_id: dict[str, list[str]] = {stage_id: [] for stage_id in stage_ids}
    for edge in edges:
        outgoing_by_id.setdefault(edge.source, []).append(edge.target)
    for targets in outgoing_by_id.values():
        targets.sort(key=lambda target: order_for_id.get(target, (999, 999, target)))

    nodes: list[PipelineGraphNode] = []
    for stage_id in stage_ids:
        stage = stage_by_id[stage_id]
        fan = stage.get("fan_out") if isinstance(stage.get("fan_out"), Mapping) else None
        provider = stage.get("provider") if isinstance(stage.get("provider"), Mapping) else None
        merge = stage.get("merge") if isinstance(stage.get("merge"), Mapping) else None
        tolerance = stage.get("failure_tolerance")
        tolerance_mode = tolerance.get("mode") if isinstance(tolerance, Mapping) else None
        fan_count = fan.get("count") if isinstance(fan, Mapping) else None
        if fan is not None and not isinstance(fan_count, int):
            node_warnings.setdefault(stage_id, []).append("fan_out count is missing or invalid")
            fan_count = None
        nodes.append(
            PipelineGraphNode(
                stage_id=stage_id,
                layer=layer_for_id.get(stage_id, 0),
                kind=_stage_kind(stage),
                lane=_graph_lane(stage),
                shape=_graph_shape(stage),
                title=stage_id,
                subtitle=_graph_subtitle(stage),
                depends_on=deps_by_id.get(stage_id, ()),
                outgoing=tuple(outgoing_by_id.get(stage_id, ())),
                fan_out_count=fan_count,
                fan_out_variant=(
                    str(fan.get("variant"))
                    if isinstance(fan, Mapping) and fan.get("variant") is not None
                    else None
                ),
                merge_agent=(
                    str(merge.get("agent"))
                    if isinstance(merge, Mapping) and merge.get("agent") is not None
                    else None
                ),
                provider_type=(
                    str(provider.get("type"))
                    if isinstance(provider, Mapping) and provider.get("type") is not None
                    else None
                ),
                tolerance=str(tolerance_mode) if tolerance_mode is not None else None,
                warnings=tuple(node_warnings.get(stage_id, ())),
            )
        )

    return PipelineGraphModel(
        nodes=tuple(sorted(nodes, key=lambda node: order_for_id.get(node.stage_id, (999, 999, node.stage_id)))),
        edges=tuple(edges),
        layers=layers,
        pipeline_name=str(pipeline.get("name")) if pipeline.get("name") is not None else None,
        warnings=tuple(model_warnings),
    )


def pipeline_board_model(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay | None = None,
    width: int | None = None,
    height: int | None = None,
    route_chips_by_stage: Mapping[str, tuple[PipelineRouteChip, ...]] | None = None,
) -> PipelineBoardModel:
    """Return a layer-board view model derived from a graph model."""

    overlay = overlay or pipeline_graph_overlay()
    route_chips_by_stage = route_chips_by_stage or {}
    node_by_id = _node_by_id(model)
    columns: list[PipelineBoardColumn] = []
    warnings = list(model.warnings)

    for column_index, layer in enumerate(model.layers, 1):
        cards: list[PipelineBoardCard] = []
        for stage_id in layer:
            node = node_by_id.get(stage_id)
            if node is None:
                warnings.append(f"layer {column_index} references unknown stage {stage_id}")
                continue
            cards.append(_pipeline_board_card(node, overlay, route_chips_by_stage.get(stage_id, ())))
        columns.append(PipelineBoardColumn(index=column_index, label=f"L{column_index}", cards=tuple(cards)))

    board = PipelineBoardModel(
        columns=tuple(columns),
        mode=pipeline_board_mode(width, height, len(columns)),
        fallback_lines=(),
        warnings=tuple(warnings),
    )
    return dataclasses.replace(board, fallback_lines=tuple(pipeline_board_plain_text(board)))


def pipeline_board_mode(width: int | None, height: int | None, column_count: int) -> str:
    del column_count
    resolved_width = width if width is not None else BOARD_MIN_WIDTH
    resolved_height = height if height is not None else MIN_BOARD_HEIGHT

    if resolved_width < COMPACT_MIN_WIDTH:
        return "linear"
    if resolved_width < BOARD_MIN_WIDTH:
        return "compact"
    if resolved_height < MIN_BOARD_HEIGHT:
        return "compact"
    return "board"


def pipeline_board_plain_text(board: PipelineBoardModel) -> list[str]:
    if not board.columns:
        return ["Pipeline has no stages."]
    if board.mode == "linear":
        return _pipeline_board_linear_lines(board)
    return _pipeline_board_compact_lines(board)


def pipeline_route_chips_by_stage(
    pipeline: Mapping[str, Any],
    resolver: BackendResolver,
) -> dict[str, tuple[PipelineRouteChip, ...]]:
    """Resolve compact route chips for runnable agents represented on the board."""

    chips_by_stage: dict[str, tuple[PipelineRouteChip, ...]] = {}
    for index, stage in enumerate(pipeline.get("stages") or []):
        if not isinstance(stage, Mapping):
            continue
        stage_id = str(stage.get("id") or f"<stage-{index + 1}>")
        chips: list[PipelineRouteChip] = []

        agents = [agent for agent in stage.get("agents") or [] if isinstance(agent, Mapping)]
        if agents:
            for agent_index, agent in enumerate(agents):
                role = agent.get("role")
                if not isinstance(role, str) or not role:
                    continue
                label = f"agent[{agent_index}]" if len(agents) > 1 else ""
                chips.extend(_route_chips_for_role(resolver, role, _agent_route_override(agent), label=label))

        fan = stage.get("fan_out")
        if isinstance(fan, Mapping):
            role = fan.get("role")
            if isinstance(role, str) and role:
                count = fan.get("count")
                branch_count = count if isinstance(count, int) and count > 0 else 0
                routes = fan.get("routes") if fan.get("variant") == "models" else None
                if isinstance(routes, list) and branch_count:
                    for branch_index in range(branch_count):
                        override = routes[branch_index] if branch_index < len(routes) else None
                        chips.append(_route_chip_for_role(resolver, role, override, label=f"b{branch_index}"))
                else:
                    chips.extend(_route_chips_for_role(resolver, role, None, label="each"))
            merge = stage.get("merge")
            merge_agent = merge.get("agent") if isinstance(merge, Mapping) else None
            if isinstance(merge_agent, str) and merge_agent:
                chips.extend(_route_chips_for_role(resolver, merge_agent, None, label="merge"))

        if chips:
            chips_by_stage[stage_id] = tuple(chips)
    return chips_by_stage


def format_route_chip(chip: PipelineRouteChip) -> str:
    prefix = f"{chip.label} " if chip.label else ""
    if chip.error:
        return f"{prefix}ERROR {chip.error}"
    return f"{prefix}({_compact_model_name(chip.model)}/{chip.effort})"


def format_route_chips(chips: tuple[PipelineRouteChip, ...] | list[PipelineRouteChip], *, max_chips: int = 3) -> str:
    if not chips:
        return ""
    visible = list(chips[:max_chips])
    rendered = " | ".join(format_route_chip(chip) for chip in visible)
    if len(chips) > len(visible):
        rendered += f" | +{len(chips) - len(visible)}"
    return rendered


def format_route_chip_summary(chips: tuple[PipelineRouteChip, ...] | list[PipelineRouteChip], *, max_chips: int = 3) -> str:
    if _route_chips_are_complexity_alternatives(chips):
        count = len(_unique_route_chip_keys(chips))
        noun = "model" if count == 1 else "models"
        return f"1 of {count} {noun} by complexity"
    return format_route_chips(chips, max_chips=max_chips)


def preset_profile_preview(
    preset_name: str,
    preset: Mapping[str, Any],
    pipeline: Mapping[str, Any],
    *,
    width: int | None = None,
    height: int | None = None,
) -> PresetProfilePreview:
    """Return a read-only board preview showing how a preset routes a pipeline."""

    model = pipeline_graph_model(pipeline)
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    route_chips_by_stage = pipeline_route_chips_by_stage(pipeline, resolver)
    board = pipeline_board_model(
        model,
        width=width,
        height=height,
        route_chips_by_stage=route_chips_by_stage,
    )
    stage_by_id = {
        str(stage.get("id")): stage
        for stage in pipeline.get("stages") or []
        if isinstance(stage, Mapping) and stage.get("id") is not None
    }
    used_route_keys = _preset_profile_used_route_keys(pipeline)
    columns: list[PipelineBoardColumn] = []
    for column in board.columns:
        cards: list[PipelineBoardCard] = []
        for card in column.cards:
            stage = stage_by_id.get(card.stage_id)
            if stage is None:
                cards.append(card)
                continue
            if isinstance(stage.get("provider"), Mapping):
                cards.append(dataclasses.replace(card, subtitle=_preset_stage_policy_summary(stage, preset)))
            else:
                cards.append(card)
        columns.append(dataclasses.replace(column, cards=tuple(cards)))
    routed_board = dataclasses.replace(board, columns=tuple(columns))
    routed_board = dataclasses.replace(routed_board, fallback_lines=tuple(pipeline_board_plain_text(routed_board)))
    return PresetProfilePreview(
        board=routed_board,
        summary_lines=tuple(_preset_profile_summary_lines(preset_name, preset, pipeline)),
        unused_route_lines=tuple(_unused_preset_route_lines(preset, used_route_keys)),
    )


def pipeline_graph_lines(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay | None = None,
    *,
    width: int | None = None,
    compact: bool = False,
    linear: bool = False,
    ascii_only: bool = False,
) -> list[str]:
    overlay = overlay or pipeline_graph_overlay()
    key = (
        _graph_model_fingerprint(model),
        _graph_overlay_fingerprint(overlay),
        width,
        compact,
        linear,
        ascii_only,
    )
    cached = _GRAPH_RENDER_CACHE.get(key)
    if cached is not None:
        return list(cached)

    if linear or (width is not None and width < 42):
        lines = _linear_graph_lines(model, overlay, ascii_only=ascii_only)
    elif compact:
        lines = _compact_graph_lines(model, overlay, width=width, ascii_only=ascii_only)
    elif width is not None and width < 88:
        lines = _narrow_graph_lines(model, overlay, ascii_only=ascii_only)
    else:
        lines = _wide_graph_lines(model, overlay, ascii_only=ascii_only)
        if width is not None and any(len(line) > width for line in lines):
            lines = _narrow_graph_lines(model, overlay, ascii_only=ascii_only)

    if len(_GRAPH_RENDER_CACHE) > 128:
        _GRAPH_RENDER_CACHE.clear()
    _GRAPH_RENDER_CACHE[key] = tuple(lines)
    return lines


def pipeline_graph_legend_lines(model: PipelineGraphModel, *, ascii_only: bool = False) -> list[str]:
    shapes = {node.shape for node in model.nodes}
    if not shapes:
        return ["legend: empty graph"]
    lines = ["legend:"]
    if "agent" in shapes:
        lines.append("  [stage] agents" if ascii_only else "  ┌ stage ┐ agents")
    if "fan_out" in shapes:
        lines.append("  [[stage xN]] fan-out + merge" if ascii_only else "  ╔ stage xN ╗ fan-out + merge")
    if "provider" in shapes:
        lines.append("  (stage) provider/evidence" if ascii_only else "  ╭ stage ╮ provider/evidence")
    if "terminal" in shapes:
        lines.append("  [[stage]] terminal answer/docs" if ascii_only else "  ╔ stage ╗ terminal answer/docs")
    lines.append("  >stage< selected  Δ dirty draft  ◆ critical path  [status] live")
    lines.append("  + join/fork" if ascii_only else "  ⊙ join/fork")
    return lines


def pipeline_graph_stage_ids(model: PipelineGraphModel) -> tuple[str, ...]:
    return tuple(node.stage_id for node in model.nodes)


def pipeline_graph_move(
    model: PipelineGraphModel,
    selected_stage_id: str | None,
    direction: str,
) -> str | None:
    """Return the stage selected by moving through the graph in one direction."""

    if not model.nodes:
        return None
    positions = _graph_stage_positions(model)
    node_by_id = _node_by_id(model)
    if selected_stage_id not in positions:
        return model.nodes[0].stage_id

    layer_index, node_index = positions[selected_stage_id]
    layer = model.layers[layer_index]
    if direction == "up":
        return layer[max(0, node_index - 1)]
    if direction == "down":
        return layer[min(len(layer) - 1, node_index + 1)]

    if direction not in {"left", "right"}:
        return selected_stage_id

    target_layer_index = layer_index + (-1 if direction == "left" else 1)
    if target_layer_index < 0 or target_layer_index >= len(model.layers):
        return selected_stage_id
    target_layer = tuple(stage_id for stage_id in model.layers[target_layer_index] if stage_id in positions)
    if not target_layer:
        return selected_stage_id

    selected_node = node_by_id[selected_stage_id]
    connected_ids = selected_node.depends_on if direction == "left" else selected_node.outgoing
    connected = [stage_id for stage_id in connected_ids if stage_id in target_layer]
    candidates = connected or list(target_layer)
    return min(candidates, key=lambda stage_id: abs(positions[stage_id][1] - node_index))


def pipeline_critical_stage_ids(
    model: PipelineGraphModel,
    stage_weights: Mapping[str, int | float] | None = None,
) -> frozenset[str]:
    """Select a deterministic longest dependency path through the pipeline DAG."""

    if not model.nodes:
        return frozenset()
    weights = stage_weights or {}
    node_by_id = _node_by_id(model)
    ordered = sorted(model.nodes, key=lambda node: _graph_stage_positions(model).get(node.stage_id, (999, 999)))
    scores: dict[str, float] = {}
    previous: dict[str, str | None] = {}

    for node in ordered:
        dep_scores = [
            (scores[dep], dep)
            for dep in node.depends_on
            if dep in scores
        ]
        dep_score, dep_id = max(dep_scores, default=(0.0, None), key=lambda item: (item[0], item[1] or ""))
        raw_weight = weights.get(node.stage_id, 1)
        weight = float(raw_weight) if isinstance(raw_weight, (int, float)) else 1.0
        scores[node.stage_id] = dep_score + max(1.0, weight)
        previous[node.stage_id] = dep_id

    end = max(
        (node.stage_id for node in ordered if node.stage_id in node_by_id),
        key=lambda stage_id: (scores.get(stage_id, 0.0), stage_id),
    )
    path: list[str] = []
    while end:
        path.append(end)
        end = previous.get(end)
    return frozenset(reversed(path))


def pipeline_live_stage_statuses(
    model: PipelineGraphModel,
    *,
    in_flight_runs: list[Any] | tuple[Any, ...] = (),
    run_events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    observations: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    aliases = _graph_stage_aliases(model)

    for row in reversed(run_events):
        stage_id = _stage_id_for_alias(aliases, row.get("phase_id"))
        if stage_id:
            event_type = str(row.get("event_type") or "event")
            statuses.setdefault(stage_id, event_type.replace("_", "-"))

    for row in reversed(observations):
        stage_id = _stage_id_for_alias(aliases, row.get("phase_id"))
        if not stage_id:
            continue
        event_type = str(row.get("event_type") or "observation")
        status = "done" if event_type.endswith("_exit") else event_type.replace("_", "-")
        statuses.setdefault(stage_id, status)

    for run in in_flight_runs:
        stage_id = _stage_id_for_alias(aliases, getattr(run, "role", None))
        if not stage_id:
            continue
        status = str(getattr(run, "status", None) or "running").replace("_", "-")
        statuses[stage_id] = status

    return statuses


_GRAPH_RENDER_CACHE: dict[tuple[Any, ...], tuple[str, ...]] = {}
_GRAPH_LANE_ORDER = {"agents": 0, "fan-out": 1, "provider": 2, "terminal": 3}


def _graph_lane(stage: Mapping[str, Any]) -> str:
    if "provider" in stage:
        return "provider"
    if "fan_out" in stage:
        return "fan-out"
    roles = [
        str(agent.get("role") or "")
        for agent in (stage.get("agents") or [])
        if isinstance(agent, Mapping)
    ]
    if any(role in {"agent-review", "agent-docs"} for role in roles):
        return "terminal"
    return "agents"


def _graph_shape(stage: Mapping[str, Any]) -> str:
    lane = _graph_lane(stage)
    if lane == "provider":
        return "provider"
    if lane == "fan-out":
        return "fan_out"
    if lane == "terminal":
        return "terminal"
    return "agent"


def _graph_subtitle(stage: Mapping[str, Any]) -> str:
    summary = _stage_summary(stage)
    if len(summary) <= 72:
        return summary
    return summary[:69].rstrip() + "..."


def _reorder_graph_layers(
    raw_layers: list[list[str]],
    deps_by_id: Mapping[str, tuple[str, ...]],
    lane_by_id: Mapping[str, str],
) -> tuple[tuple[str, ...], ...]:
    ordered_layers: list[tuple[str, ...]] = []
    positions: dict[str, tuple[int, int]] = {}
    for layer_index, layer in enumerate(raw_layers, 1):
        if layer_index == 1:
            ordered = sorted(layer)
        else:
            scored: list[tuple[float, int, str]] = []
            for stage_id in layer:
                deps = [positions[dep][1] for dep in deps_by_id.get(stage_id, ()) if dep in positions]
                barycenter = sum(deps) / len(deps) if deps else 999.0
                scored.append((barycenter, _GRAPH_LANE_ORDER.get(lane_by_id.get(stage_id, ""), 9), stage_id))
            ordered = [stage_id for _score, _lane, stage_id in sorted(scored)]
        for node_index, stage_id in enumerate(ordered):
            positions[stage_id] = (layer_index, node_index)
        ordered_layers.append(tuple(ordered))
    return tuple(ordered_layers)

def _graph_model_fingerprint(model: PipelineGraphModel) -> tuple[Any, ...]:
    nodes = tuple(
        (
            node.stage_id,
            node.layer,
            node.kind,
            node.lane,
            node.shape,
            node.title,
            node.subtitle,
            node.depends_on,
            node.outgoing,
            node.fan_out_count,
            node.fan_out_variant,
            node.merge_agent,
            node.provider_type,
            node.tolerance,
            node.warnings,
        )
        for node in model.nodes
    )
    return (model.pipeline_name, nodes, tuple((edge.source, edge.target) for edge in model.edges), model.layers, model.warnings)


def _graph_overlay_fingerprint(overlay: PipelineGraphOverlay) -> tuple[Any, ...]:
    return (
        overlay.selected_stage_id,
        tuple(sorted((str(key), str(value)) for key, value in overlay.stage_statuses.items())),
        tuple(sorted(overlay.dirty_stage_ids)),
        tuple(sorted(overlay.critical_stage_ids)),
        tuple(sorted(overlay.highlighted_stage_ids)),
    )


def _node_by_id(model: PipelineGraphModel) -> dict[str, PipelineGraphNode]:
    return {node.stage_id: node for node in model.nodes}


def _pipeline_board_card(
    node: PipelineGraphNode,
    overlay: PipelineGraphOverlay,
    route_chips: tuple[PipelineRouteChip, ...] = (),
) -> PipelineBoardCard:
    status = _normalize_board_status(overlay.stage_statuses.get(node.stage_id))
    selected = overlay.selected_stage_id == node.stage_id
    dirty = node.stage_id in overlay.dirty_stage_ids
    critical = node.stage_id in overlay.critical_stage_ids
    title, subtitle = _pipeline_board_labels(node)
    return PipelineBoardCard(
        stage_id=node.stage_id,
        layer=node.layer,
        title=title,
        subtitle=subtitle,
        badges=_pipeline_board_badges(node, overlay, status),
        dependency_label=_dependency_chip(node.depends_on),
        outgoing_label=_outgoing_chip(node.outgoing),
        kind=node.kind,
        lane=node.lane,
        selected=selected,
        dirty=dirty,
        critical=critical,
        status=status,
        warnings=node.warnings,
        route_chips=route_chips,
    )


def _pipeline_board_badges(
    node: PipelineGraphNode,
    overlay: PipelineGraphOverlay,
    status: str | None,
) -> tuple[str, ...]:
    badges: list[str] = []
    if len(node.depends_on) > 1:
        badges.append("JOIN")
    if node.fan_out_count is not None:
        badges.append(f"FAN x{node.fan_out_count}")
    if node.provider_type is not None:
        badges.append("PROVIDER")
    if _is_output_node(node):
        badges.append("OUTPUT")
    if node.warnings:
        badges.append("WARN")
    if node.stage_id in overlay.dirty_stage_ids:
        badges.append("DIRTY")
    status_badge = _status_badge(status)
    if status_badge is not None:
        badges.append(status_badge)
    return tuple(badges)


def _pipeline_board_labels(node: PipelineGraphNode) -> tuple[str, str]:
    if node.provider_type is not None:
        prefix = node.provider_type
        subtitle = node.subtitle.removeprefix(prefix).strip()
        return prefix, subtitle

    if node.fan_out_count is not None:
        role = node.subtitle.split(" ", 1)[0] if node.subtitle else node.title
        details = []
        if node.fan_out_variant:
            details.append(node.fan_out_variant)
        if node.merge_agent:
            details.append(f"merge={node.merge_agent}")
        return f"{role} x{node.fan_out_count}", " ".join(details)

    if node.subtitle and node.subtitle != "no agents":
        return node.subtitle, ""
    return node.title, ""


def _normalize_board_status(status: Any) -> str | None:
    if status is None:
        return None
    normalized = str(status).strip().lower().replace("_", "-")
    return normalized or None


def _status_badge(status: str | None) -> str | None:
    if status is None:
        return None
    badge = STATUS_TO_BADGE.get(status)
    if badge is not None:
        return badge
    if status.endswith("-start"):
        return "RUN"
    return None


def _is_output_node(node: PipelineGraphNode) -> bool:
    return node.shape == "terminal" or node.lane in {"output", "terminal"}


def _dependency_chip(depends_on: tuple[str, ...]) -> str | None:
    if not depends_on:
        return None
    return "after: " + " + ".join(depends_on)


def _outgoing_chip(outgoing: tuple[str, ...]) -> str | None:
    if not outgoing:
        return None
    return "next: " + ", ".join(outgoing)


def _pipeline_board_compact_lines(board: PipelineBoardModel) -> list[str]:
    lines: list[str] = []
    for column in board.columns:
        if not column.cards:
            lines.append(f"{column.label} -")
            continue
        rendered = "  ".join(_pipeline_board_compact_card(card) for card in column.cards)
        lines.append(f"{column.label} {rendered}")
    return lines


def _pipeline_board_compact_card(card: PipelineBoardCard) -> str:
    parts = [card.title]
    if card.route_chips:
        parts.append(format_route_chip_summary(card.route_chips, max_chips=2))
    parts.extend(card.badges)
    if "JOIN" in card.badges and card.dependency_label:
        parts.append(card.dependency_label)
    if card.selected:
        if "JOIN" not in card.badges and card.dependency_label:
            parts.append(card.dependency_label)
        if card.outgoing_label:
            parts.append(card.outgoing_label)
    return " ".join(parts)


def _pipeline_board_linear_lines(board: PipelineBoardModel) -> list[str]:
    lines: list[str] = []
    cards = [card for column in board.columns for card in column.cards]
    for index, card in enumerate(cards, 1):
        parts = [f"{index}. {card.title}", f"[{_pipeline_board_lane_label(card.lane)}]"]
        if card.route_chips:
            parts.append(format_route_chip_summary(card.route_chips, max_chips=2))
        depends_on = _dependency_label_stage_ids(card.dependency_label)
        if depends_on:
            parts.append(f"depends_on={','.join(depends_on)}")
        parts.extend(card.badges)
        lines.append(" ".join(parts))
    return lines


def _pipeline_board_lane_label(lane: str) -> str:
    if lane in {"terminal", "output"}:
        return "output"
    if lane in {"", "tools"}:
        return "agents"
    return lane


def _dependency_label_stage_ids(label: str | None) -> tuple[str, ...]:
    if not label or not label.startswith("after: "):
        return ()
    return tuple(part.strip() for part in label.removeprefix("after: ").split(" + ") if part.strip())


def _preset_stage_policy_summary(stage: Mapping[str, Any], preset: Mapping[str, Any]) -> str:
    provider = stage.get("provider")
    if isinstance(provider, Mapping):
        provider_type = str(provider.get("type") or "provider")
        if provider_type == "swarm-review":
            return _review_provider_policy_summary(preset)
        return provider_type

    return ""


def _agent_route_override(agent: Mapping[str, Any]) -> Mapping[str, Any] | str | None:
    override = agent.get("route")
    if override is None and {"backend", "model", "effort"} <= set(agent.keys()):
        override = agent
    return override if isinstance(override, (Mapping, str)) else None


def _route_chips_for_role(
    resolver: BackendResolver,
    role: str,
    override: Mapping[str, Any] | str | None,
    *,
    label: str = "",
) -> list[PipelineRouteChip]:
    if override is not None:
        return [_route_chip_for_role(resolver, role, override, label=label)]

    resolved = []
    for complexity in ("simple", "moderate", "hard"):
        route = resolver.resolve(role, complexity)
        resolved.append((complexity, route))
    unique = {
        (route.backend, route.model, route.effort, route.setting_source)
        for _complexity, route in resolved
    }
    if len(unique) == 1:
        return [_route_chip_from_route(resolved[0][1], label=label)]
    return [
        _route_chip_from_route(route, label=_route_chip_label(label, complexity))
        for complexity, route in resolved
    ]


def _route_chip_for_role(
    resolver: BackendResolver,
    role: str,
    override: Mapping[str, Any] | str | None,
    *,
    label: str,
) -> PipelineRouteChip:
    try:
        route = resolver.resolve(role, "hard", override=override)
    except Exception as exc:
        return PipelineRouteChip(
            label=label,
            backend="error",
            model=_clip_route_error(str(exc)),
            effort="",
            source="error",
            error=_clip_route_error(str(exc)),
        )
    return _route_chip_from_route(route, label=label)


def _route_chip_from_route(route: Any, *, label: str) -> PipelineRouteChip:
    return PipelineRouteChip(
        label=label,
        backend=str(route.backend),
        model=str(route.model),
        effort=str(route.effort),
        source=str(route.setting_source),
    )


def _route_chip_label(prefix: str, label: str) -> str:
    return f"{prefix}/{label}" if prefix else label


def _route_chips_are_complexity_alternatives(chips: tuple[PipelineRouteChip, ...] | list[PipelineRouteChip]) -> bool:
    labels = [chip.label for chip in chips]
    return labels == ["simple", "moderate", "hard"] and len(_unique_route_chip_keys(chips)) > 1


def _unique_route_chip_keys(chips: tuple[PipelineRouteChip, ...] | list[PipelineRouteChip]) -> set[tuple[str, str, str]]:
    return {
        (chip.backend, chip.model, chip.effort)
        for chip in chips
        if chip.error is None
    }


def _clip_route_error(message: str, limit: int = 48) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def _compact_model_name(model: str) -> str:
    if model.startswith("claude-"):
        parts = model.removeprefix("claude-").split("-")
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            family = " ".join(parts[:-2])
            return f"{family} {parts[-2]}.{parts[-1]}".strip()
        return model.removeprefix("claude-").replace("-", " ")
    if model.startswith("gpt-"):
        return "gpt " + model.removeprefix("gpt-")
    return model.replace("-", " ")


def _route_source_label(source: str) -> str:
    if source == "active-preset" or source.startswith("preset-route:"):
        return "preset"
    if source == "backends.toml":
        return "base"
    if source == "stage-override":
        return "stage"
    return "default"


def _review_provider_policy_summary(preset: Mapping[str, Any]) -> str:
    policy = preset.get("review_providers")
    if not isinstance(policy, Mapping):
        return "providers: default"
    selection = policy.get("selection", "auto")
    parts = [f"providers={selection}"]
    for key in ("min_success", "max_parallel"):
        if policy.get(key) is not None:
            parts.append(f"{key}={policy[key]}")
    if isinstance(policy.get("include"), list):
        parts.append(f"include={len(policy['include'])}")
    if isinstance(policy.get("exclude"), list):
        parts.append(f"exclude={len(policy['exclude'])}")
    return " ".join(parts)


def _preset_profile_summary_lines(
    preset_name: str,
    preset: Mapping[str, Any],
    pipeline: Mapping[str, Any],
) -> list[str]:
    pipeline_name = str(preset.get("pipeline") or pipeline.get("name") or "default")
    lines = [f"Preset profile: {preset_name}", f"pipeline={pipeline_name}"]
    description = preset.get("description")
    if isinstance(description, str) and description:
        lines.append(description)
    budget = preset.get("budget")
    if isinstance(budget, Mapping):
        budget_bits = []
        if budget.get("max_agents_per_run") is not None:
            budget_bits.append(f"agents<={budget['max_agents_per_run']}")
        if budget.get("max_estimated_cost_usd") is not None:
            budget_bits.append(f"cost<=${float(budget['max_estimated_cost_usd']):.2f}")
        if budget.get("max_wall_clock_seconds") is not None:
            budget_bits.append(f"wall<={budget['max_wall_clock_seconds']}s")
        if budget_bits:
            lines.append("budget: " + " ".join(budget_bits))
    review_policy = _review_provider_policy_summary(preset)
    if review_policy != "providers: default":
        lines.append(review_policy)
    decompose = preset.get("decompose")
    if isinstance(decompose, Mapping) and decompose.get("mode") is not None:
        lines.append(f"decompose={decompose['mode']}")
    mem_prime = preset.get("mem_prime")
    if isinstance(mem_prime, Mapping) and mem_prime.get("mode") is not None:
        lines.append(f"mem_prime={mem_prime['mode']}")
    return lines


def _preset_profile_used_route_keys(pipeline: Mapping[str, Any]) -> set[str]:
    roles: set[str] = set()
    explicit_route_names: set[str] = set()
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        for agent in stage.get("agents") or []:
            if not isinstance(agent, Mapping):
                continue
            role = agent.get("role")
            if isinstance(role, str) and role:
                roles.add(role)
            override = agent.get("route")
            if isinstance(override, str):
                explicit_route_names.add(override)
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping):
            role = fan.get("role")
            if isinstance(role, str) and role:
                roles.add(role)
            for route in fan.get("routes") or []:
                if isinstance(route, str):
                    explicit_route_names.add(route)

    keys = set(explicit_route_names)
    for role in roles:
        keys.add(f"roles.{role}")
        for complexity in ("simple", "moderate", "hard"):
            keys.add(f"roles.{role}.{complexity}")
    return keys


def _unused_preset_route_lines(preset: Mapping[str, Any], used_route_keys: set[str]) -> list[str]:
    routing = preset.get("routing")
    if not isinstance(routing, Mapping):
        return ["Unused routes: none"]
    unused = [
        key
        for key in sorted(str(key) for key in routing)
        if key not in used_route_keys
    ]
    if not unused:
        return ["Unused routes: none"]
    lines = ["Unused routes:"]
    for key in unused[:8]:
        value = routing.get(key)
        route = _format_route(value) if isinstance(value, Mapping) else str(value)
        lines.append(f"  {key}: {route}")
    if len(unused) > 8:
        lines.append(f"  ... {len(unused) - 8} more")
    return lines


def _graph_stage_positions(model: PipelineGraphModel) -> dict[str, tuple[int, int]]:
    return {
        stage_id: (layer_index, node_index)
        for layer_index, layer in enumerate(model.layers)
        for node_index, stage_id in enumerate(layer)
    }


def _graph_stage_aliases(model: PipelineGraphModel) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in model.nodes:
        normalized = _normalize_stage_alias(node.stage_id)
        aliases[normalized] = node.stage_id
        aliases[_normalize_stage_alias(f"agent-{node.stage_id}")] = node.stage_id
        for role in re.findall(r"\bagent-[A-Za-z0-9._-]+", node.subtitle):
            aliases[_normalize_stage_alias(role)] = node.stage_id
            aliases[_normalize_stage_alias(role.removeprefix("agent-"))] = node.stage_id
    return aliases


def _normalize_stage_alias(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _stage_id_for_alias(aliases: Mapping[str, str], value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return aliases.get(_normalize_stage_alias(value))


def _render_node(
    node: PipelineGraphNode,
    overlay: PipelineGraphOverlay,
    *,
    ascii_only: bool,
    compact: bool = False,
) -> str:
    label = node.title
    if node.fan_out_count is not None:
        label += f" x{node.fan_out_count}"
        if node.fan_out_variant and not compact:
            label += f" {node.fan_out_variant}"
    elif node.provider_type and not compact:
        label += f" ({node.provider_type})"
    if node.merge_agent and not compact:
        label += f" merge:{node.merge_agent}"

    if ascii_only:
        if node.shape == "provider":
            rendered = f"({label})"
        elif node.shape in {"fan_out", "terminal"}:
            rendered = f"[[{label}]]"
        else:
            rendered = f"[{label}]"
    elif node.shape == "provider":
        rendered = f"╭ {label} ╮"
    elif node.shape in {"fan_out", "terminal"}:
        rendered = f"╔ {label} ╗"
    else:
        rendered = f"┌ {label} ┐"

    if overlay.selected_stage_id == node.stage_id:
        rendered = f">{rendered}<"
    badges: list[str] = []
    status = overlay.stage_statuses.get(node.stage_id)
    if status:
        badges.append(f"[{_short_graph_status(status)}]")
    if node.stage_id in overlay.dirty_stage_ids:
        badges.append("!d" if ascii_only else "Δ")
    if node.stage_id in overlay.critical_stage_ids:
        badges.append("*" if ascii_only else "◆")
    if node.stage_id in overlay.highlighted_stage_ids:
        badges.append("+")
    if node.warnings:
        badges.append("!")
    if badges:
        rendered += " " + " ".join(badges)
    return rendered


def _short_graph_status(status: str) -> str:
    normalized = status.strip().lower().replace("_", "-")
    aliases = {
        "running": "run",
        "checkpoint-written": "ckpt",
        "writer-exit": "done",
        "queued": "queued",
        "done": "done",
        "failed": "failed",
    }
    return aliases.get(normalized, normalized[:10])


def _join_label(node: PipelineGraphNode, *, first: bool = True, verbose: bool = True) -> str:
    deps = [dep for dep in node.depends_on if dep]
    if len(deps) < 2:
        return ""
    if first and verbose:
        return f" (join: {' + '.join(deps)})"
    return " (join)"


def _warning_lines(model: PipelineGraphModel) -> list[str]:
    lines = [f"ERROR {warning}" for warning in model.warnings]
    for node in model.nodes:
        lines.extend(f"WARN {node.stage_id}: {warning}" for warning in node.warnings)
    return lines


def _linear_graph_lines(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay,
    *,
    ascii_only: bool,
) -> list[str]:
    lines = _warning_lines(model)
    if not model.nodes:
        return lines + ["graph: empty"]
    for index, node in enumerate(model.nodes, 1):
        parts = [f"{index}. {_render_node(node, overlay, ascii_only=ascii_only, compact=True)} [{node.kind}]"]
        if node.depends_on:
            parts.append(f"depends_on={','.join(node.depends_on)}")
        if node.fan_out_count is not None:
            parts.append(f"fan_out={node.fan_out_count}")
        if node.fan_out_variant:
            parts.append(f"variant={node.fan_out_variant}")
        if node.merge_agent:
            parts.append(f"merge={node.merge_agent}")
        if node.provider_type:
            parts.append(f"provider={node.provider_type}")
        if node.tolerance:
            parts.append(f"tolerance={node.tolerance}")
        lines.append(" ".join(parts))
    return lines


def _compact_graph_lines(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay,
    *,
    width: int | None,
    ascii_only: bool,
) -> list[str]:
    node_by_id = _node_by_id(model)
    lines = _warning_lines(model)
    if not model.nodes:
        return lines + ["graph: empty"]
    for layer_index, layer in enumerate(model.layers, 1):
        nodes = [node_by_id[stage_id] for stage_id in layer if stage_id in node_by_id]
        rendered_nodes = [
            _render_node(node, overlay, ascii_only=ascii_only, compact=True) + _join_label(node, verbose=False)
            for node in nodes
        ]
        line = f"L{layer_index}: " + "  ".join(rendered_nodes)
        if width is not None and len(line) > width:
            compact_nodes = [node.stage_id + _join_label(node, verbose=False) for node in nodes]
            line = f"L{layer_index}: " + " | ".join(compact_nodes)
        lines.append(line)
    return lines


def _wide_graph_lines(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay,
    *,
    ascii_only: bool,
) -> list[str]:
    node_by_id = _node_by_id(model)
    lines = _warning_lines(model)
    if not model.nodes:
        return lines + ["graph: empty"]

    rendered_by_id = {
        node.stage_id: _render_node(node, overlay, ascii_only=ascii_only, compact=True)
        for node in model.nodes
    }
    layer_widths = [
        max(
            (len(rendered_by_id[stage_id]) for stage_id in layer if stage_id in rendered_by_id),
            default=1,
        )
        for layer in model.layers
    ]
    gutter = 6 if not ascii_only else 5
    layer_xs: list[int] = []
    cursor = 0
    for width in layer_widths:
        layer_xs.append(cursor)
        cursor += width + gutter

    y_by_id = _layered_graph_y_positions(model)
    height = max(y_by_id.values(), default=0) + 1
    width = max(
        (
            layer_xs[layer_index] + len(rendered_by_id[stage_id])
            for layer_index, layer in enumerate(model.layers)
            for stage_id in layer
            if stage_id in rendered_by_id
        ),
        default=1,
    )
    canvas = [[" " for _column in range(width + 1)] for _row in range(height)]

    placements = {
        stage_id: (layer_xs[layer_index], y_by_id[stage_id], rendered_by_id[stage_id])
        for layer_index, layer in enumerate(model.layers)
        for stage_id in layer
        if stage_id in rendered_by_id and stage_id in y_by_id
    }

    positions = _graph_stage_positions(model)
    for edge in sorted(
        model.edges,
        key=lambda item: (positions.get(item.source, (999, 999)), item.target),
    ):
        if edge.source not in placements or edge.target not in placements:
            continue
        source = node_by_id.get(edge.source)
        target = node_by_id.get(edge.target)
        if source is None or target is None:
            continue
        _draw_layered_edge(
            canvas,
            placements[edge.source],
            placements[edge.target],
            target,
            ascii_only=ascii_only,
        )

    for _stage_id, (x, y, rendered) in placements.items():
        _write_graph_text(canvas, x, y, rendered)

    rendered_lines = ["".join(row).rstrip() for row in canvas]
    return lines + [line for line in rendered_lines if line]


def _layered_graph_y_positions(model: PipelineGraphModel) -> dict[str, int]:
    """Assign stable row coordinates for a compact layered DAG drawing."""

    node_by_id = _node_by_id(model)
    y_by_id: dict[str, int] = {}
    fixed_ids: set[str] = set()

    for layer in model.layers:
        if len(layer) > 1:
            for index, stage_id in enumerate(layer):
                if stage_id in node_by_id:
                    y_by_id[stage_id] = index * 2
                    fixed_ids.add(stage_id)

    for _pass in range(3):
        for layer in model.layers:
            occupied: set[int] = set()
            desired: list[tuple[int, int, str]] = []
            for index, stage_id in enumerate(layer):
                if stage_id not in node_by_id:
                    continue
                if stage_id in fixed_ids:
                    occupied.add(y_by_id[stage_id])
                    continue
                preferred = _preferred_graph_y(node_by_id[stage_id], node_by_id, y_by_id)
                if preferred is None:
                    preferred = y_by_id.get(stage_id, index * 2)
                desired.append((preferred, index, stage_id))
            for preferred, _index, stage_id in sorted(desired):
                y_by_id[stage_id] = _nearest_free_row(preferred, occupied)

    return y_by_id


def _preferred_graph_y(
    node: PipelineGraphNode,
    node_by_id: Mapping[str, PipelineGraphNode],
    y_by_id: Mapping[str, int],
) -> int | None:
    connected_rows = [
        y_by_id[stage_id]
        for stage_id in (*node.depends_on, *node.outgoing)
        if stage_id in node_by_id and stage_id in y_by_id
    ]
    if not connected_rows:
        return None
    return int(round(sum(connected_rows) / len(connected_rows)))


def _nearest_free_row(preferred: int, occupied: set[int]) -> int:
    if preferred not in occupied:
        occupied.add(preferred)
        return preferred
    for delta in range(1, 64):
        for candidate in (preferred + delta, preferred - delta):
            if candidate >= 0 and candidate not in occupied:
                occupied.add(candidate)
                return candidate
    candidate = max(occupied, default=preferred) + 1
    occupied.add(candidate)
    return candidate


def _draw_layered_edge(
    canvas: list[list[str]],
    source: tuple[int, int, str],
    target: tuple[int, int, str],
    target_node: PipelineGraphNode,
    *,
    ascii_only: bool,
) -> None:
    source_x, source_y, source_text = source
    target_x, target_y, _target_text = target
    start_x = source_x + len(source_text)
    arrow_x = max(start_x + 2, target_x - 1)
    has_join = len([dep for dep in target_node.depends_on if dep]) > 1
    join_x = max(start_x + 2, target_x - 4) if has_join else None
    end_x = (join_x - 1) if join_x is not None else (arrow_x - 1)
    mid_x = max(start_x + 1, min(end_x, (start_x + end_x) // 2))

    if source_y == target_y:
        _draw_graph_hline(canvas, source_y, start_x, end_x, ascii_only=ascii_only)
    else:
        _draw_graph_hline(canvas, source_y, start_x, mid_x - 1, ascii_only=ascii_only)
        source_corner = "+" if ascii_only else ("┐" if target_y > source_y else "┘")
        target_corner = "+" if ascii_only else ("└" if target_y > source_y else "┌")
        _put_graph_char(canvas, mid_x, source_y, source_corner, ascii_only=ascii_only)
        _draw_graph_vline(
            canvas,
            mid_x,
            min(source_y, target_y) + 1,
            max(source_y, target_y) - 1,
            ascii_only=ascii_only,
        )
        _put_graph_char(canvas, mid_x, target_y, target_corner, ascii_only=ascii_only)
        _draw_graph_hline(canvas, target_y, mid_x + 1, end_x, ascii_only=ascii_only)

    if join_x is not None:
        _put_graph_char(canvas, join_x, target_y, "+" if ascii_only else "⊙", ascii_only=ascii_only)
        _draw_graph_hline(canvas, target_y, join_x + 1, arrow_x - 1, ascii_only=ascii_only)
    _put_graph_char(canvas, arrow_x, target_y, ">" if ascii_only else "▶", ascii_only=ascii_only)


def _draw_graph_hline(
    canvas: list[list[str]],
    y: int,
    x_start: int,
    x_end: int,
    *,
    ascii_only: bool,
) -> None:
    if x_end < x_start:
        return
    for x in range(x_start, x_end + 1):
        _put_graph_char(canvas, x, y, "-" if ascii_only else "─", ascii_only=ascii_only)


def _draw_graph_vline(
    canvas: list[list[str]],
    x: int,
    y_start: int,
    y_end: int,
    *,
    ascii_only: bool,
) -> None:
    if y_end < y_start:
        return
    for y in range(y_start, y_end + 1):
        _put_graph_char(canvas, x, y, "|" if ascii_only else "│", ascii_only=ascii_only)


def _put_graph_char(
    canvas: list[list[str]],
    x: int,
    y: int,
    char: str,
    *,
    ascii_only: bool,
) -> None:
    if y < 0 or y >= len(canvas) or x < 0 or x >= len(canvas[y]):
        return
    existing = canvas[y][x]
    if existing == " " or existing == char:
        canvas[y][x] = char
        return
    if existing in {"▶", ">", "⊙", "+"}:
        return
    if char in {"▶", ">", "⊙", "+"}:
        canvas[y][x] = char
        return
    horizontal = {"─", "-"}
    vertical = {"│", "|"}
    if ascii_only:
        canvas[y][x] = "+"
    elif (existing in horizontal and char in vertical) or (existing in vertical and char in horizontal):
        canvas[y][x] = "┼"
    elif existing in horizontal and char not in horizontal:
        canvas[y][x] = char
    elif existing in vertical and char not in vertical:
        canvas[y][x] = char
    else:
        canvas[y][x] = char


def _write_graph_text(canvas: list[list[str]], x: int, y: int, text: str) -> None:
    if y < 0 or y >= len(canvas):
        return
    for offset, char in enumerate(text):
        column = x + offset
        if 0 <= column < len(canvas[y]):
            canvas[y][column] = char


def _narrow_graph_lines(
    model: PipelineGraphModel,
    overlay: PipelineGraphOverlay,
    *,
    ascii_only: bool,
) -> list[str]:
    node_by_id = _node_by_id(model)
    lines = _warning_lines(model)
    if not model.nodes:
        return lines + ["graph: empty"]
    roots = [node for node in model.nodes if not any(dep in node_by_id for dep in node.depends_on)]
    if not roots:
        roots = list(model.nodes[:1])
    expanded: set[str] = set()
    for root_index, root in enumerate(roots):
        if root_index:
            lines.append("")
        lines.extend(_narrow_node_lines(root, node_by_id, overlay, expanded, "", ascii_only=ascii_only))
    return lines


def _narrow_node_lines(
    node: PipelineGraphNode,
    node_by_id: Mapping[str, PipelineGraphNode],
    overlay: PipelineGraphOverlay,
    expanded: set[str],
    prefix: str,
    *,
    ascii_only: bool,
) -> list[str]:
    lines = [
        prefix
        + _render_node(node, overlay, ascii_only=ascii_only, compact=True)
        + _join_label(node, verbose=False)
    ]
    if node.stage_id in expanded:
        return lines
    expanded.add(node.stage_id)
    children = [node_by_id[stage_id] for stage_id in node.outgoing if stage_id in node_by_id]
    for index, child in enumerate(children):
        is_last = index == len(children) - 1
        edge = (
            "`--> "
            if ascii_only and is_last
            else "+--> " if ascii_only else "└──▶ " if is_last else "├──▶ "
        )
        child_prefix = prefix + ("    " if is_last else "│   ")
        child_lines = _narrow_node_lines(child, node_by_id, overlay, expanded, child_prefix, ascii_only=ascii_only)
        first_child_line = child_lines[0]
        if first_child_line.startswith(child_prefix):
            first_child_line = first_child_line[len(child_prefix):]
        else:
            first_child_line = first_child_line.lstrip()
        child_lines[0] = prefix + edge + first_child_line
        lines.extend(child_lines)
    return lines


def select_source_preset_for_pipeline(pipeline_name: str) -> str | None:
    active = active_preset_name()
    if active:
        for candidate in list_presets():
            if candidate.name != active:
                continue
            try:
                if load_preset(candidate.path).get("pipeline") == pipeline_name:
                    return candidate.name
            except Exception:
                pass
    same_named = next((candidate for candidate in list_presets() if candidate.name == pipeline_name), None)
    if same_named is not None:
        try:
            if load_preset(same_named.path).get("pipeline") == pipeline_name:
                return same_named.name
        except Exception:
            pass
    return _preset_for_pipeline(pipeline_name)


def suggested_fork_name(source_name: str, *, suffix: str = "edit") -> str:
    base = f"{source_name}-{suffix}"
    if find_pipeline(base) is None and not any(candidate.name == base for candidate in list_presets()):
        return base
    idx = 2
    while True:
        candidate = f"{base}-{idx}"
        if find_pipeline(candidate) is None and not any(item.name == candidate for item in list_presets()):
            return candidate
        idx += 1


def start_pipeline_draft(pipeline_name: str, *, preset_name: str | None = None) -> PipelineEditDraft:
    selected_preset = preset_name or pipeline_name
    preset_item = next((item for item in list_presets() if item.name == selected_preset), None)
    if preset_item is not None:
        preset = load_preset(preset_item.path)
        resolved = resolve_preset_graph(preset)
        pipeline = resolved.graph
        return PipelineEditDraft(
            pipeline_name=selected_preset,
            preset_name=selected_preset,
            origin=preset_item.origin,
            pipeline=copy.deepcopy(pipeline),
            original_pipeline=copy.deepcopy(pipeline),
            original_disk_hash=resolved.source_hash,
        )
    item = find_pipeline(pipeline_name)
    if item is None:
        raise ValueError(f"preset or pipeline not found: {pipeline_name}")
    pipeline = load_pipeline(item.path)
    selected_preset = _preset_for_pipeline(pipeline_name)
    return PipelineEditDraft(
        pipeline_name=item.name,
        preset_name=selected_preset,
        origin=item.origin,
        pipeline=copy.deepcopy(pipeline),
        original_pipeline=copy.deepcopy(pipeline),
        original_disk_hash="sha256:" + sha256_file(item.path),
    )


def _validate_route_parts(backend: str, model: str, effort: str) -> dict[str, str]:
    backend = backend.strip()
    model = model.strip()
    effort = effort.strip()
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    if not model:
        raise ValueError("model must be a non-empty string")
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {sorted(EFFORTS)}")
    return {"backend": backend, "model": model, "effort": effort}


def _route_object_from_resolver(draft: PipelineEditDraft, role: str) -> dict[str, str]:
    route = BackendResolver(preset_name=draft.preset_name).resolve(role, "hard")
    return {"backend": route.backend, "model": route.model, "effort": route.effort}


def effective_stage_agent_route(draft: PipelineEditDraft, stage_id: str, agent_index: int = 0) -> dict[str, str]:
    agent = _mutable_stage_agent(draft.pipeline, stage_id, agent_index)
    role = agent.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"agent[{agent_index}] in {stage_id} has no role")
    override: Any = agent.get("route")
    if override is None and {"backend", "model", "effort"} <= set(agent):
        override = agent
    route = BackendResolver(preset_name=draft.preset_name).resolve(role, "hard", override=override)
    return {
        "backend": route.backend,
        "model": route.model,
        "effort": route.effort,
        "source": route.setting_source,
    }


def effective_fan_out_branch_route(draft: PipelineEditDraft, stage_id: str, branch_index: int = 0) -> dict[str, str]:
    fan = _mutable_stage_fan_out(draft.pipeline, stage_id)
    role = fan.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"fan_out stage {stage_id} has no role")
    count = fan.get("count")
    if not isinstance(count, int) or count < 1:
        raise ValueError(f"fan_out stage {stage_id} has invalid count")
    if branch_index < 0 or branch_index >= count:
        raise ValueError(f"branch index out of range for stage {stage_id}: {branch_index}")
    override: Any = None
    if fan.get("variant") == "models":
        routes = fan.get("routes")
        if isinstance(routes, list) and branch_index < len(routes):
            override = routes[branch_index]
    route = BackendResolver(preset_name=draft.preset_name).resolve(role, "hard", override=override)
    return {
        "backend": route.backend,
        "model": route.model,
        "effort": route.effort,
        "source": route.setting_source,
    }


def draft_set_stage_agent_route(
    draft: PipelineEditDraft,
    stage_id: str,
    agent_index: int,
    *,
    backend: str,
    model: str,
    effort: str,
) -> None:
    route = _validate_route_parts(backend, model, effort)
    agent = _mutable_stage_agent(draft.pipeline, stage_id, agent_index)
    draft.checkpoint(f"set route for {stage_id}.agents[{agent_index}]")
    for key in ("backend", "model", "effort", "route"):
        agent.pop(key, None)
    agent.update(route)


def draft_reset_stage_agent_route(draft: PipelineEditDraft, stage_id: str, agent_index: int) -> None:
    agent = _mutable_stage_agent(draft.pipeline, stage_id, agent_index)
    draft.checkpoint(f"reset route for {stage_id}.agents[{agent_index}]")
    for key in ("backend", "model", "effort", "route"):
        agent.pop(key, None)


def draft_set_fan_out_branch_route(
    draft: PipelineEditDraft,
    stage_id: str,
    branch_index: int,
    *,
    backend: str,
    model: str,
    effort: str,
) -> None:
    route = _validate_route_parts(backend, model, effort)
    fan = _mutable_stage_fan_out(draft.pipeline, stage_id)
    if fan.get("variant") == "prompt_variants" or "variants" in fan:
        raise ValueError("cannot combine prompt-variant lenses and per-branch model routes in one fan-out")
    role = fan.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"fan_out stage {stage_id} has no role")
    count = fan.get("count")
    if not isinstance(count, int) or count < 1:
        raise ValueError(f"fan_out stage {stage_id} has invalid count")
    if branch_index < 0 or branch_index >= count:
        raise ValueError(f"branch index out of range for stage {stage_id}: {branch_index}")
    existing = fan.get("routes") if fan.get("variant") == "models" else None
    if isinstance(existing, list) and len(existing) == count:
        routes: list[Any] = copy.deepcopy(existing)
    else:
        default_route = _route_object_from_resolver(draft, role)
        routes = [copy.deepcopy(default_route) for _ in range(count)]
    draft.checkpoint(f"set route for {stage_id}.fan_out[{branch_index}]")
    routes[branch_index] = route
    fan["variant"] = "models"
    fan["count"] = count
    fan["routes"] = routes
    fan.pop("variants", None)


def draft_reset_fan_out_routes(draft: PipelineEditDraft, stage_id: str) -> None:
    fan = _mutable_stage_fan_out(draft.pipeline, stage_id)
    draft.checkpoint(f"reset fan-out routes for {stage_id}")
    fan["variant"] = "same"
    fan.pop("routes", None)
    fan.pop("variants", None)


def current_mco_provider_config(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    provider = stage.get("provider")
    if not isinstance(provider, Mapping) or provider.get("type") != "mco":
        raise ValueError(f"stage {stage_id} is not an MCO provider stage")
    tolerance = stage.get("failure_tolerance")
    tolerance_mode = tolerance.get("mode", "best-effort") if isinstance(tolerance, Mapping) else "best-effort"
    min_success = tolerance.get("min_success") if isinstance(tolerance, Mapping) else None
    providers = [
        str(name)
        for name in (provider.get("providers") or [])
        if isinstance(name, str) and name in MCO_PROVIDERS
    ]
    return {
        "providers": providers or ["claude"],
        "timeout_seconds": (
            provider.get("timeout_seconds")
            if isinstance(provider.get("timeout_seconds"), int)
            else 1800
        ),
        "failure_tolerance_mode": tolerance_mode if tolerance_mode in TOLERANCE_MODES else "best-effort",
        "min_success": min_success if isinstance(min_success, int) else None,
    }


def draft_set_mco_provider_config(
    draft: PipelineEditDraft,
    stage_id: str,
    *,
    providers: list[str],
    timeout_seconds: int,
    failure_tolerance_mode: str = "best-effort",
    min_success: int | None = None,
) -> None:
    stage, provider = _mutable_mco_provider_stage(draft.pipeline, stage_id)
    normalized = _normalize_mco_providers(providers)
    timeout = _validate_mco_timeout(timeout_seconds)
    tolerance = _provider_failure_tolerance(
        failure_tolerance_mode,
        min_success,
        branch_count=len(normalized),
    )
    draft.checkpoint(f"set MCO provider config for {stage_id}")
    provider["type"] = "mco"
    provider["command"] = "review"
    provider["providers"] = normalized
    provider["mode"] = "review"
    provider["strict_contract"] = True
    provider["output"] = "findings"
    provider["memory"] = False
    provider["timeout_seconds"] = timeout
    stage["failure_tolerance"] = tolerance


def current_provider_review_config(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    provider = stage.get("provider")
    if not isinstance(provider, Mapping):
        raise ValueError(f"stage {stage_id} is not a provider stage")
    provider_type = provider.get("type")
    if provider_type == "mco":
        config = current_mco_provider_config(pipeline, stage_id)
        return {
            **config,
            "provider_type": "mco",
            "selection": "explicit",
            "configured_providers": config["providers"],
            "max_parallel": len(config["providers"]),
        }
    if provider_type != "swarm-review":
        raise ValueError(f"stage {stage_id} is not a provider-review stage")
    tolerance = stage.get("failure_tolerance")
    tolerance_mode = tolerance.get("mode", "best-effort") if isinstance(tolerance, Mapping) else "best-effort"
    min_success = tolerance.get("min_success") if isinstance(tolerance, Mapping) else None
    providers = [
        str(name)
        for name in (provider.get("providers") or [])
        if isinstance(name, str)
    ]
    selection = provider.get("selection", "auto")
    if selection not in REVIEW_PROVIDER_SELECTIONS:
        selection = "auto"
    return {
        "provider_type": "swarm-review",
        "selection": selection,
        "providers": providers,
        "configured_providers": providers if selection == "explicit" else [],
        "timeout_seconds": (
            provider.get("timeout_seconds")
            if isinstance(provider.get("timeout_seconds"), int)
            else 1800
        ),
        "max_parallel": (
            provider.get("max_parallel")
            if isinstance(provider.get("max_parallel"), int)
            else 4
        ),
        "failure_tolerance_mode": tolerance_mode if tolerance_mode in TOLERANCE_MODES else "best-effort",
        "min_success": min_success if isinstance(min_success, int) else None,
    }


def draft_set_provider_review_config(
    draft: PipelineEditDraft,
    stage_id: str,
    *,
    selection: str,
    providers: list[str] | None = None,
    timeout_seconds: int,
    max_parallel: int = 4,
    failure_tolerance_mode: str = "best-effort",
    min_success: int | None = None,
) -> None:
    stage, provider = _mutable_provider_review_stage(draft.pipeline, stage_id)
    normalized_selection = _validate_provider_review_selection(selection)
    timeout = _validate_mco_timeout(timeout_seconds)
    parallel = _validate_provider_review_max_parallel(max_parallel)
    normalized_providers: list[str] = []
    if normalized_selection == "explicit":
        normalized_providers = _normalize_review_providers(providers or [])
        branch_count = len(normalized_providers)
    else:
        branch_count = 0 if normalized_selection == "off" else parallel
    tolerance = _provider_failure_tolerance(
        failure_tolerance_mode,
        min_success,
        branch_count=branch_count,
    )
    draft.checkpoint(f"set provider-review config for {stage_id}")
    provider["type"] = "swarm-review"
    provider["command"] = "review"
    provider["selection"] = normalized_selection
    provider["output"] = "findings"
    provider["memory"] = False
    provider["timeout_seconds"] = timeout
    provider["max_parallel"] = parallel
    if normalized_selection == "explicit":
        provider["providers"] = normalized_providers
    else:
        provider.pop("providers", None)
    stage["failure_tolerance"] = tolerance


def current_stage_agent_lens_id(pipeline: Mapping[str, Any], stage_id: str, agent_index: int = 0) -> str | None:
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    agents = stage.get("agents")
    if not isinstance(agents, list):
        raise ValueError(f"stage {stage_id} is not an agents stage")
    if agent_index < 0 or agent_index >= len(agents) or not isinstance(agents[agent_index], Mapping):
        raise ValueError(f"agent index out of range for stage {stage_id}: {agent_index}")
    lens_id = agents[agent_index].get("lens")
    return lens_id if isinstance(lens_id, str) and lens_id else None


def draft_set_stage_agent_lens(
    draft: PipelineEditDraft,
    stage_id: str,
    agent_index: int,
    lens_id: str | None,
) -> None:
    agent = _mutable_stage_agent(draft.pipeline, stage_id, agent_index)
    role = agent.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"agent[{agent_index}] in {stage_id} has no role")
    if lens_id is None or not lens_id.strip():
        draft.checkpoint(f"clear lens for {stage_id}.agents[{agent_index}]")
        agent.pop("lens", None)
        return
    lens_id = lens_id.strip()
    errors = validate_prompt_lens_selection(role, [lens_id], stage_kind="agents", require_files=True)
    if errors:
        raise ValueError("; ".join(errors))
    draft.checkpoint(f"set lens for {stage_id}.agents[{agent_index}]")
    agent["lens"] = lens_id


def current_prompt_lens_ids(pipeline: Mapping[str, Any], stage_id: str) -> list[str]:
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    fan = stage.get("fan_out")
    if not isinstance(fan, Mapping):
        raise ValueError(f"stage {stage_id} is not a fan_out stage")
    role = fan.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"fan_out stage {stage_id} has no role")
    if fan.get("variant") != "prompt_variants":
        return []
    lens_ids: list[str] = []
    for variant in fan.get("variants") or []:
        if not isinstance(variant, str):
            continue
        lens = lens_for_variant(role, variant)
        lens_ids.append(lens.lens_id if lens is not None else variant)
    return lens_ids


def draft_set_prompt_variant_lenses(draft: PipelineEditDraft, stage_id: str, lens_ids: list[str]) -> None:
    fan = _mutable_stage_fan_out(draft.pipeline, stage_id)
    if fan.get("variant") == "models" or "routes" in fan:
        raise ValueError("cannot combine prompt-variant lenses and per-branch model routes in one fan-out")
    role = fan.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"fan_out stage {stage_id} has no role")
    if not lens_ids:
        count = fan.get("count")
        draft.checkpoint(f"clear prompt lenses for {stage_id}")
        fan["role"] = role
        fan["count"] = count if isinstance(count, int) and count > 0 else 1
        fan["variant"] = "same"
        fan.pop("variants", None)
        return
    compiled = compile_prompt_variant_fan_out(role, lens_ids)
    draft.checkpoint(f"set prompt lenses for {stage_id}")
    fan.clear()
    fan.update(compiled)


def stage_lens_option_rows(pipeline: Mapping[str, Any], stage_id: str) -> list[dict[str, str]]:
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    fan = stage.get("fan_out")
    agents = stage.get("agents")
    stage_kind = "fan_out" if isinstance(fan, Mapping) else "agents"
    selected: set[str]
    if isinstance(fan, Mapping):
        role = fan.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"fan_out stage {stage_id} has no role")
        selected = set(current_prompt_lens_ids(pipeline, stage_id))
    elif isinstance(agents, list):
        if not agents or not isinstance(agents[0], Mapping):
            raise ValueError(f"stage {stage_id} has no editable agent")
        role = agents[0].get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"agent[0] in {stage_id} has no role")
        current = current_stage_agent_lens_id(pipeline, stage_id, 0)
        selected = {current} if current else set()
    else:
        raise ValueError(f"stage {stage_id} is not an agents or fan_out stage")
    rows: list[dict[str, str]] = []
    for lens in list_prompt_lenses(role=role, stage_kind=stage_kind):
        contract = lens.output_contract_for_role(role)
        rows.append(
            {
                "lens_id": lens.lens_id,
                "label": lens.label,
                "category": lens.category,
                "mode": lens.execution_mode,
                "selected": "yes" if lens.lens_id in selected else "no",
                "variant": lens.variant_for_role(role) or "",
                "stage_kind": stage_kind,
                "contract": contract.schema_rule,
                "merge_expectation": lens.merge_expectation,
                "conflicts": ", ".join(lens.conflicts) if lens.conflicts else "none",
                "safety": ", ".join(lens.safety_notes) if lens.safety_notes else "none",
            }
        )
    return rows


def suggest_stage_id(pipeline: Mapping[str, Any], base: str) -> str:
    existing = {str(stage.get("id")) for stage in pipeline.get("stages") or [] if isinstance(stage, Mapping)}
    if base not in existing:
        return base
    idx = 2
    while f"{base}-{idx}" in existing:
        idx += 1
    return f"{base}-{idx}"


def draft_add_module_stage(
    draft: PipelineEditDraft,
    module_id: str,
    *,
    stage_id: str | None = None,
    depends_on: list[str] | None = None,
) -> None:
    module = get_module(module_id)
    if module is None:
        raise ValueError(f"unknown module: {module_id}")
    default_id = str(module.stage_template.get("id") or module.module_id)
    resolved_stage_id = stage_id.strip() if stage_id else suggest_stage_id(draft.pipeline, default_id)
    if not resolved_stage_id:
        raise ValueError("stage id must be a non-empty string")
    existing = {str(stage.get("id")) for stage in draft.pipeline.get("stages") or [] if isinstance(stage, Mapping)}
    if resolved_stage_id in existing:
        raise ValueError(f"stage already exists: {resolved_stage_id}")
    stage = module.instantiate_stage(stage_id=resolved_stage_id)
    if depends_on is not None:
        stage["depends_on"] = depends_on
    stages = draft.pipeline.setdefault("stages", [])
    if not isinstance(stages, list):
        raise ValueError("pipeline stages must be a list")
    draft.checkpoint(f"add module {module_id} as {resolved_stage_id}")
    stages.append(stage)


def draft_remove_stage(draft: PipelineEditDraft, stage_id: str) -> None:
    stages = draft.pipeline.get("stages")
    if not isinstance(stages, list):
        raise ValueError("pipeline stages must be a list")
    _mutable_stage_by_id(draft.pipeline, stage_id)
    dependents = [
        str(stage.get("id"))
        for stage in stages
        if isinstance(stage, Mapping) and stage_id in (stage.get("depends_on") or [])
    ]
    if dependents:
        raise ValueError(f"stage {stage_id} is still required by: {', '.join(sorted(dependents))}")
    draft.checkpoint(f"remove stage {stage_id}")
    draft.pipeline["stages"] = [
        stage for stage in stages if not (isinstance(stage, Mapping) and stage.get("id") == stage_id)
    ]


def module_palette_rows(pipeline: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for module in list_modules():
        default_id = str(module.stage_template.get("id") or module.module_id)
        suggested = suggest_stage_id(pipeline, default_id)
        status = "ready"
        notes: list[str] = []
        if suggested != default_id:
            notes.append(f"default id exists; suggested {suggested}")
        if module.experimental:
            status = "experimental"
            notes.append("experimental")
        if module.requires_provider_doctor:
            notes.append("provider doctor required before activation")
        rows.append(
            {
                "module_id": module.module_id,
                "label": module.label,
                "category": module.category,
                "status": status,
                "suggested_stage_id": suggested,
                "detail": "; ".join(notes) if notes else module.description,
            }
        )
    return rows


def telemetry_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "telemetry"


def runs_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "runs.jsonl"


def run_events_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "run_events.jsonl"


def observations_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "observations.jsonl"


def findings_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "findings.jsonl"


def finding_outcomes_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "finding_outcomes.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_runs(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(runs_path(data_dir))


def load_run_events(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(run_events_path(data_dir))


def load_observations(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(observations_path(data_dir))


def load_findings(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(findings_path(data_dir))


def load_finding_outcomes(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(finding_outcomes_path(data_dir))


def outcome_dashboard_summary(
    data_dir: Path | None = None,
    now: datetime | None = None,
    since_days: int = 30,
) -> OutcomeDashboardSummary:
    data_dir = data_dir or resolve_data_dir()
    since_days = max(1, since_days)
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=since_days)
    runs = _rows_since(load_runs(data_dir), cutoff, ("timestamp_start", "timestamp_end"))
    all_findings = load_findings(data_dir)
    findings = _rows_since(all_findings, cutoff, ("timestamp",))
    outcomes = _rows_since(load_finding_outcomes(data_dir), cutoff, ("observed_at",))

    successful_runs = 0
    nonzero_exit_count = 0
    handoff_count = 0
    wall_values: list[float] = []
    cost_values: list[float] = []
    pipeline_counts: dict[str, int] = {}
    for row in runs:
        exit_code = row.get("exit_code")
        if _is_zero_exit(exit_code):
            successful_runs += 1
        elif exit_code is not None:
            nonzero_exit_count += 1
        if row.get("writer_status") == "HANDOFF_REQUESTED":
            handoff_count += 1
        wall = row.get("wall_clock_seconds")
        if isinstance(wall, (int, float)) and not isinstance(wall, bool):
            wall_values.append(float(wall))
        cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cost_values.append(float(cost))
        pipeline_name = str(row.get("pipeline_name") or "(none)")
        pipeline_counts[pipeline_name] = pipeline_counts.get(pipeline_name, 0) + 1

    findings_by_id = {
        str(row["finding_id"]): row
        for row in all_findings
        if isinstance(row.get("finding_id"), str)
    }
    accepted_findings = 0
    ignored_findings = 0
    accepted_by_role: dict[str, int] = {}
    for row in outcomes:
        action = row.get("maintainer_action")
        finding_id = row.get("finding_id")
        if action == "ignored":
            ignored_findings += 1
        if action not in ACCEPTED_MAINTAINER_ACTIONS:
            continue
        accepted_findings += 1
        finding = findings_by_id.get(str(finding_id))
        role = str((finding or {}).get("role") or "(unknown)")
        accepted_by_role[role] = accepted_by_role.get(role, 0) + 1

    top_role, top_role_count = _top_count(accepted_by_role)
    top_pipeline, top_pipeline_count = _top_count(pipeline_counts)
    return OutcomeDashboardSummary(
        since_days=since_days,
        run_count=len(runs),
        successful_runs=successful_runs,
        findings_count=len(findings),
        outcome_count=len(outcomes),
        accepted_findings=accepted_findings,
        ignored_findings=ignored_findings,
        handoff_count=handoff_count,
        nonzero_exit_count=nonzero_exit_count,
        mean_wall_seconds=_mean(wall_values),
        mean_cost_usd=_mean(cost_values),
        top_accepted_role=top_role,
        top_accepted_role_count=top_role_count,
        top_pipeline=top_pipeline,
        top_pipeline_count=top_pipeline_count,
        report_commands=(
            f"bin/swarm-telemetry report --since {since_days}d --bucket phase_kind",
            f"bin/swarm-telemetry report --since {since_days}d --bucket complexity",
            f"bin/swarm-telemetry join-outcomes --since {since_days}d --dry-run",
        ),
    )


def latest_checkpoint_event(data_dir: Path | None = None) -> dict[str, Any] | None:
    for row in reversed(load_run_events(data_dir)):
        if row.get("event_type") == "checkpoint_written":
            return row
    return None


def latest_observation(data_dir: Path | None = None) -> dict[str, Any] | None:
    rows = load_observations(data_dir)
    return rows[-1] if rows else None


def token_burn_last_24h(rows: list[dict[str, Any]], now: datetime | None = None) -> dict[str, int | None]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=24)
    totals: dict[str, int] = {}
    observed: set[str] = set()
    for row in rows:
        ts = _parse_ts(row.get("timestamp_start"))
        if ts is None or ts < cutoff:
            continue
        backend = str(row.get("backend") or "unknown")
        total = 0
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            value = row.get(key)
            if isinstance(value, int):
                total += value
                observed.add(backend)
        totals[backend] = totals.get(backend, 0) + total
    result: dict[str, int | None] = {}
    for backend in sorted({str(r.get("backend") or "unknown") for r in rows} | set(totals)):
        result[backend] = totals.get(backend, 0) if backend in observed else None
    return result


def _rows_since(
    rows: list[dict[str, Any]],
    cutoff: datetime,
    timestamp_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        timestamp = None
        for field in timestamp_fields:
            timestamp = _parse_ts(row.get(field))
            if timestamp is not None:
                break
        if timestamp is None or timestamp >= cutoff:
            filtered.append(row)
    return filtered


def _is_zero_exit(value: Any) -> bool:
    return value == 0 or value == "0"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _top_count(counts: Mapping[str, int]) -> tuple[str | None, int]:
    if not counts:
        return None, 0
    name, count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return name, count


def _format_rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{numerator / denominator:.0%}"


def _format_seconds_short(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    return f"{seconds:.1f}s"


def _format_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.4f}"


def status_summary(data_dir: Path | None = None, now: datetime | None = None) -> StatusSummary:
    data_dir = data_dir or resolve_data_dir()
    rows = load_runs(data_dir)
    now = now or datetime.now(UTC)
    today = now.date()
    runs_today = 0
    cost_values: list[float] = []
    last_429: dict[str, datetime] = {}
    for row in rows:
        ts = _parse_ts(row.get("timestamp_start"))
        if ts is not None and ts.date() == today:
            runs_today += 1
            cost = row.get("estimated_cost_usd")
            if isinstance(cost, (int, float)):
                cost_values.append(float(cost))
        rate_ts = _parse_ts(row.get("last_429_at"))
        if rate_ts is not None:
            backend = str(row.get("backend") or "unknown")
            if backend not in last_429 or rate_ts > last_429[backend]:
                last_429[backend] = rate_ts

    context = current_context()
    preset = active_preset_name() or "default-fallback"
    pipeline = str(context.get("pipeline_name") or "default")
    getting_started_visible = (
        active_preset_name() is None
        and not load_in_flight(data_dir)
        and not rows
        and not (data_dir / ".getting-started-dismissed").exists()
    )
    return StatusSummary(
        preset=preset,
        pipeline=pipeline,
        runs_today=runs_today,
        cost_today=sum(cost_values) if cost_values else None,
        last_429_claude=last_429.get("claude").isoformat().replace("+00:00", "Z") if "claude" in last_429 else None,
        last_429_codex=last_429.get("codex").isoformat().replace("+00:00", "Z") if "codex" in last_429 else None,
        latest_checkpoint=latest_checkpoint_event(data_dir),
        latest_observation=latest_observation(data_dir),
        getting_started_visible=getting_started_visible,
    )


def pid_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pipeline_lens_rows(pipeline: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        agents = stage.get("agents")
        if isinstance(agents, list):
            for idx, agent in enumerate(agents):
                if not isinstance(agent, Mapping):
                    continue
                role = str(agent.get("role") or "")
                lens_id = agent.get("lens")
                if not isinstance(lens_id, str) or not lens_id:
                    continue
                lens = get_lens(lens_id)
                if lens is None:
                    rows.append(
                        {
                            "stage": str(stage.get("id") or "<unknown>"),
                            "target": f"agent[{idx}]",
                            "variant": "(unknown)",
                            "lens_id": lens_id,
                            "label": lens_id,
                            "mode": "single_agent",
                            "compatibility": f"{role} agents",
                            "contract": "unknown lens; validation will fail",
                        }
                    )
                    continue
                rows.append(
                    {
                        "stage": str(stage.get("id") or "<unknown>"),
                        "target": f"agent[{idx}]",
                        "variant": lens.variant_for_role(role) or "(unmapped)",
                        "lens_id": lens.lens_id,
                        "label": lens.label,
                        "mode": "single_agent",
                        "compatibility": f"{', '.join(lens.roles)} / agents",
                        "contract": lens.output_contract_for_role(role).schema_rule,
                    }
                )
        fan = stage.get("fan_out")
        if not isinstance(fan, dict) or fan.get("variant") != "prompt_variants":
            continue
        role = str(fan.get("role") or "")
        for idx, variant in enumerate(fan.get("variants") or []):
            if not isinstance(variant, str):
                continue
            lens = lens_for_variant(role, variant)
            if lens is None:
                rows.append(
                    {
                        "stage": str(stage.get("id") or "<unknown>"),
                        "target": f"branch[{idx}]",
                        "variant": variant,
                        "lens_id": "(untyped)",
                        "label": variant,
                        "mode": "prompt_variants",
                        "compatibility": f"{role} fan_out",
                        "contract": "variant file only; no catalog metadata",
                    }
                )
                continue
            rows.append(
                {
                    "stage": str(stage.get("id") or "<unknown>"),
                    "target": f"branch[{idx}]",
                    "variant": variant,
                    "lens_id": lens.lens_id,
                    "label": lens.label,
                    "mode": lens.execution_mode,
                    "compatibility": f"{', '.join(lens.roles)} / {', '.join(lens.stage_kinds)}",
                    "contract": lens.output_contract_for_role(role).schema_rule,
                }
            )
    return rows


def latest_provider_artifact(stage_id: str, data_dir: Path | None = None) -> Path | None:
    runs_dir = (data_dir or resolve_data_dir()) / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = [
        path
        for path in runs_dir.glob(f"*/stages/{stage_id}/provider-findings.json")
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_mco_provider_artifact(stage_id: str, data_dir: Path | None = None) -> Path | None:
    return latest_provider_artifact(stage_id, data_dir)


def provider_result_preview(stage_id: str, data_dir: Path | None = None) -> list[str]:
    artifact = latest_provider_artifact(stage_id, data_dir)
    if artifact is None:
        return []
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"provider-result: unreadable {artifact} ({exc})"]
    if not isinstance(payload, Mapping):
        return [f"provider-result: invalid root {artifact}"]
    findings = payload.get("findings")
    errors = payload.get("provider_errors")
    configured = payload.get("configured_providers")
    selected = payload.get("selected_providers")
    findings_count = len(findings) if isinstance(findings, list) else 0
    error_rows = errors if isinstance(errors, list) else []
    configured_text = ", ".join(str(item) for item in configured) if isinstance(configured, list) else "n/a"
    selected_text = ", ".join(str(item) for item in selected) if isinstance(selected, list) else "n/a"
    lines = [
        f"provider-result: {artifact}",
        (
            f"  status={payload.get('status', 'unknown')} "
            f"provider_count={payload.get('provider_count', 'n/a')} "
            f"configured={configured_text} selected={selected_text} "
            f"findings={findings_count} errors={len(error_rows)}"
        ),
    ]
    for idx, item in enumerate(error_rows[:3]):
        if not isinstance(item, Mapping):
            continue
        provider = item.get("provider") or "unknown"
        error_class = item.get("provider_error_class") or item.get("error_class") or "error"
        message = item.get("message") or item.get("detail") or ""
        lines.append(f"  error[{idx}]: {provider}:{error_class} {message}".rstrip())
    if len(error_rows) > 3:
        lines.append(f"  ... {len(error_rows) - 3} more provider error(s)")
    return lines


def mco_provider_result_preview(stage_id: str, data_dir: Path | None = None) -> list[str]:
    return provider_result_preview(stage_id, data_dir)


def _format_route(route: Any) -> str:
    if isinstance(route, str):
        return f"named:{route}"
    if not isinstance(route, Mapping):
        return "default resolver"
    if {"backend", "model", "effort"} <= set(route):
        return f"{route['backend']}/{route['model']}/{route['effort']}"
    return str(dict(route))


def _stage_detail_lines(stage: Mapping[str, Any], *, prefix: str = "  ") -> list[str]:
    stage_id = str(stage.get("id") or "<unknown>")
    tolerance = stage.get("failure_tolerance")
    tolerance_mode = tolerance.get("mode", "strict") if isinstance(tolerance, Mapping) else "strict"
    lines = [f"{prefix}- {stage_id} tolerance={tolerance_mode}"]
    deps = stage.get("depends_on") or []
    if deps:
        lines.append(f"{prefix}  depends_on: {', '.join(str(dep) for dep in deps)}")
    agents = stage.get("agents")
    if isinstance(agents, list):
        for idx, agent in enumerate(agents):
            if not isinstance(agent, Mapping):
                continue
            override: Any = agent.get("route")
            if override is None and {"backend", "model", "effort"} <= set(agent):
                override = agent
            role = str(agent.get("role") or "<missing-role>")
            lens_id = agent.get("lens")
            lens_text = ""
            if isinstance(lens_id, str) and lens_id:
                lens = get_lens(lens_id)
                variant = lens.variant_for_role(role) if lens is not None else None
                lens_text = f" lens={lens_id}"
                if variant:
                    lens_text += f" variant={variant}"
            lines.append(
                f"{prefix}  agent[{idx}]: {role} "
                f"route={_format_route(override)}{lens_text}"
            )
    fan = stage.get("fan_out")
    if isinstance(fan, Mapping):
        lines.append(
            f"{prefix}  fan_out: role={fan.get('role')} count={fan.get('count')} "
            f"variant={fan.get('variant')}"
        )
        if fan.get("variant") == "models":
            for idx, route in enumerate(fan.get("routes") or []):
                lines.append(f"{prefix}  branch[{idx}]: route={_format_route(route)}")
        elif fan.get("variant") == "prompt_variants":
            role = str(fan.get("role") or "")
            for idx, variant in enumerate(fan.get("variants") or []):
                lens = lens_for_variant(role, variant) if isinstance(variant, str) else None
                lens_id = lens.lens_id if lens else "(untyped)"
                lines.append(f"{prefix}  branch[{idx}]: variant={variant} lens={lens_id}")
    provider = stage.get("provider")
    if isinstance(provider, Mapping):
        selection_text = ""
        if provider.get("type") == "swarm-review":
            selection_text = (
                f" selection={provider.get('selection', 'auto')}"
                f" max_parallel={provider.get('max_parallel', 4)}"
            )
        lines.append(
            f"{prefix}  provider: type={provider.get('type')} command={provider.get('command')} "
            f"providers={provider.get('providers')}{selection_text}"
        )
        if provider.get("type") == "mco":
            lines.append(
                f"{prefix}  provider-boundary: experimental read-only evidence; "
                "no merge, approval, memory, or repo writes"
            )
        elif provider.get("type") == "swarm-review":
            lines.append(
                f"{prefix}  provider-boundary: internal read-only evidence; "
                "real shims require green R2/R3/R4 eligibility gates"
            )
        lines.append(
            f"{prefix}  provider-config: mode={provider.get('mode', 'review')} "
            f"output={provider.get('output', 'findings')} memory={provider.get('memory', False)} "
            f"timeout_seconds={provider.get('timeout_seconds')}"
        )
        lines.extend(f"{prefix}  {line}" for line in provider_result_preview(stage_id))
    merge = stage.get("merge")
    if isinstance(merge, Mapping):
        lines.append(f"{prefix}  merge: {merge.get('strategy')}:{merge.get('agent')}")
    return lines


def pipeline_inspector_lines(pipeline: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        lines.extend(_stage_detail_lines(stage))
    return lines


def stage_inspector_text(
    pipeline: Mapping[str, Any],
    stage_id: str | None,
    overlay: PipelineGraphOverlay | None = None,
    route_chips_by_stage: Mapping[str, tuple[PipelineRouteChip, ...]] | None = None,
) -> str:
    if not stage_id:
        return "Select a stage."
    stage = _stage_by_id(pipeline, stage_id)
    if stage is None:
        return f"Stage not found: {stage_id}"
    lines = [
        f"stage: {stage_id}",
        f"kind: {_stage_kind(stage)}",
        f"summary: {_stage_summary(stage)}",
        "",
        "details:",
    ]
    if overlay is not None:
        status = overlay.stage_statuses.get(stage_id)
        if status:
            lines.insert(3, f"live status: {status}")
        markers = []
        if stage_id in overlay.dirty_stage_ids:
            markers.append("changed draft")
        if stage_id in overlay.critical_stage_ids:
            markers.append("critical path")
        if stage_id in overlay.highlighted_stage_ids:
            markers.append("highlighted")
        if markers:
            insert_at = 4 if status else 3
            lines.insert(insert_at, "markers: " + ", ".join(markers))
    route_chips = tuple((route_chips_by_stage or {}).get(stage_id, ()))
    if route_chips:
        lines.extend(["", "routes:"])
        lines.extend(f"  - {format_route_chip(chip)}" for chip in route_chips)
    lines.extend(_stage_detail_lines(stage))
    return "\n".join(lines)


def validate_pipeline_draft(draft: PipelineEditDraft, *, plan_path: str | None = None, include_budget: bool = True) -> ValidationResult:
    if draft.preset_name:
        preset_item = next((item for item in list_presets() if item.name == draft.preset_name), None)
        if preset_item is None:
            result = ValidationResult()
            result.add(f"preset not found: {draft.preset_name}")
            return result
        preset = load_preset(preset_item.path)
        preset = copy.deepcopy(preset)
        preset.pop("pipeline", None)
        preset["pipeline_inline"] = copy.deepcopy(draft.pipeline)
        result, _ = validate_preset_mapping(preset, draft.preset_name, plan_path, include_budget)
        activation_error = pipeline_activation_error(draft.pipeline_name, draft.pipeline)
        if activation_error:
            result.add(activation_error)
        return result

    result = ValidationResult()
    result.errors.extend(schema_lint_pipeline(draft.pipeline))
    result.errors.extend(role_existence_errors(draft.pipeline))
    result.errors.extend(variant_existence_errors(draft.pipeline))
    result.errors.extend(route_resolution_errors(draft.pipeline, None, None))
    result.errors.extend(invariant_errors(draft.pipeline, None, None))
    activation_error = pipeline_activation_error(draft.pipeline_name, draft.pipeline)
    if activation_error:
        result.add(activation_error)
    try:
        topological_layers(draft.pipeline)
    except ValueError as exc:
        result.add(str(exc))
    return result


def draft_status_line(draft: PipelineEditDraft | None) -> str:
    if draft is None:
        return "draft: none"
    state = "dirty" if draft.dirty else draft.status
    return (
        f"draft: {state} pipeline={draft.pipeline_name} preset={draft.preset_name or 'none'} "
        f"undo={len(draft.undo_stack)} redo={len(draft.redo_stack)} message={draft.message}"
    )


def draft_validation_lines(draft: PipelineEditDraft) -> list[str]:
    result = validate_pipeline_draft(draft)
    lines = [draft_status_line(draft), "validation:"]
    if result.errors:
        lines.extend(f"  ERROR {error}" for error in result.errors)
        lines.append("  save blocked")
    else:
        lines.append("  OK structural validation")
    lines.extend(f"  WARN {warning}" for warning in result.warnings)
    if result.budget is not None:
        b = result.budget
        lines.append(
            f"  budget: agents={b.agent_count} cost=${b.estimated_cost_usd:.4f} "
            f"wall={b.estimated_wall_clock_seconds}s fan_out_width={b.fan_out_width}"
        )
    return lines


def pipeline_profile_summary(pipeline_name: str, pipeline: Mapping[str, Any]) -> str:
    profile = pipeline_profile_for(pipeline_name, pipeline)
    status = "preview-only" if profile.preview_only else "runnable"
    command = profile.command_name or "none"
    return f"profile: {profile.profile_id} status={status} command={command} terminal={profile.terminal_behavior}"


def pipeline_activation_blocker(pipeline_name: str, pipeline: Mapping[str, Any] | None = None) -> str | None:
    if pipeline is None:
        item = find_pipeline(pipeline_name)
        if item is None:
            return f"pipeline not found: {pipeline_name}"
        pipeline = load_pipeline(item.path)
    return pipeline_activation_error(pipeline_name, pipeline)


def pipeline_has_mco_provider(pipeline: Mapping[str, Any]) -> bool:
    return pipeline_has_provider_stage(pipeline, "mco")


def pipeline_has_provider_stage(pipeline: Mapping[str, Any], provider_type: str | None = None) -> bool:
    for stage in pipeline.get("stages") or []:
        provider = stage.get("provider") if isinstance(stage, Mapping) else None
        if not isinstance(provider, Mapping):
            continue
        if provider_type is None or provider.get("type") == provider_type:
            return True
    return False


def pipeline_profile_preset(pipeline_name: str, pipeline: Mapping[str, Any] | None = None) -> str | None:
    if pipeline is None:
        item = find_pipeline(pipeline_name)
        if item is None:
            return None
        pipeline = load_pipeline(item.path)
    profile = pipeline_profile_for(pipeline_name, pipeline)
    if pipeline_name in profile.pipeline_names and profile.preset_names:
        if pipeline_name in profile.preset_names:
            return pipeline_name
        return profile.preset_names[0]
    return None


def _preset_for_pipeline(pipeline_name: str) -> str | None:
    for candidate in list_presets():
        try:
            if load_preset(candidate.path).get("pipeline") == pipeline_name:
                return candidate.name
        except Exception:
            continue
    return None


def _pipeline_has_provider(pipeline_name: str, provider_name: str) -> bool:
    item = find_pipeline(pipeline_name)
    if item is None:
        return False
    try:
        pipeline = load_pipeline(item.path)
    except Exception:
        return False
    for stage in pipeline.get("stages") or []:
        provider = stage.get("provider") if isinstance(stage, Mapping) else None
        if isinstance(provider, Mapping) and provider.get("type") == provider_name:
            return True
    return False


def pipeline_diff_lines(pipeline_name: str, *, max_lines: int = 12) -> list[str]:
    item = find_pipeline(pipeline_name)
    if item is None:
        return [f"diff: pipeline not found: {pipeline_name}"]
    if item.origin != "user":
        return [f"diff: stock pipeline {pipeline_name}; no user fork diff"]
    try:
        diff = diff_user_pipeline(pipeline_name)
        drift = stock_drift_for_pipeline(pipeline_name)
    except ValueError as exc:
        return [f"diff: {exc}"]
    lines = [f"source={diff.source_name or 'none'} changed={str(diff.has_changes).lower()}"]
    if drift.tracked:
        status = "drifted" if drift.drifted else "source unchanged"
        lines.append(f"drift: {status}")
    else:
        lines.append("drift: no tracked stock hash")
    if diff.has_changes:
        lines.extend(f"  {line}" for line in diff.lines[:max_lines])
        if len(diff.lines) > max_lines:
            lines.append(f"  ... {len(diff.lines) - max_lines} more diff lines")
    return lines


def pipeline_validation_report(
    pipeline_name: str,
    *,
    plan_path: str | None = None,
    include_provider_doctor: bool = False,
    provider_doctor_fn: Callable[..., ProviderDoctorReport] = provider_doctor,
) -> str:
    preset_item = next((item for item in list_presets() if item.name == pipeline_name), None)
    preset_name = preset_item.name if preset_item is not None else _preset_for_pipeline(pipeline_name)
    lines: list[str] = ["validation:"]
    pipeline_for_profile: dict[str, Any] | None = None
    graph_name = pipeline_name
    if preset_item is not None:
        try:
            preset = load_preset(preset_item.path)
            resolved = resolve_preset_graph(preset)
            pipeline_for_profile = resolved.graph
            graph_name = resolved.source_name or f"inline:{preset_item.name}"
            lines.append("  " + pipeline_profile_summary(graph_name, pipeline_for_profile))
            activation_error = pipeline_activation_blocker(graph_name, pipeline_for_profile)
            if activation_error:
                lines.append(f"  ERROR {activation_error}")
        except Exception as exc:
            lines.append(f"  ERROR profile unavailable: {exc}")
    else:
        item = find_pipeline(pipeline_name)
        if item is not None:
            try:
                pipeline_for_profile = load_pipeline(item.path)
                lines.append("  " + pipeline_profile_summary(pipeline_name, pipeline_for_profile))
                activation_error = pipeline_activation_blocker(pipeline_name, pipeline_for_profile)
                if activation_error:
                    lines.append(f"  ERROR {activation_error}")
            except Exception as exc:
                lines.append(f"  ERROR profile unavailable: {exc}")
    if preset_item is None and pipeline_for_profile is None:
        try:
            item = find_pipeline(pipeline_name)
            if item is not None:
                pipeline_for_profile = load_pipeline(item.path)
        except Exception as exc:
            lines.append(f"  ERROR profile unavailable: {exc}")
    if preset_name is None:
        lines.append("  full validation needs a preset")
        return "\n".join(lines)
    result, *_ = validate_preset_and_pipeline(preset_name, plan_path, include_budget=True)
    if result.errors:
        lines.extend(f"  ERROR {error}" for error in result.errors)
    else:
        lines.append("  OK structural validation")
    lines.extend(f"  WARN {warning}" for warning in result.warnings)
    if result.budget is not None:
        b = result.budget
        lines.append(
            f"  budget: agents={b.agent_count} cost=${b.estimated_cost_usd:.4f} "
            f"wall={b.estimated_wall_clock_seconds}s fan_out_width={b.fan_out_width}"
        )
    pipeline_for_provider = pipeline_for_profile
    has_mco = pipeline_has_provider_stage(pipeline_for_provider, "mco") if pipeline_for_provider else _pipeline_has_provider(pipeline_name, "mco")
    has_swarm_review = (
        pipeline_has_provider_stage(pipeline_for_provider, "swarm-review")
        if pipeline_for_provider
        else _pipeline_has_provider(pipeline_name, "swarm-review")
    )
    if has_mco or has_swarm_review:
        if include_provider_doctor:
            report = provider_doctor_fn(
                preset_name=preset_name,
                run_mco=has_mco,
                run_review=has_swarm_review,
            )
            status = "OK" if report.ok else "ERROR"
            lines.append(f"  provider doctor: {status} required={', '.join(report.required_providers) or 'none'}")
            payload = report.as_dict()
            if payload.get("configured_review_providers") is not None:
                configured = ", ".join(payload.get("configured_review_providers") or []) or "none"
                selected = ", ".join(payload.get("selected_review_providers") or []) or "none"
                lines.append(f"    review configured={configured} selected={selected}")
            for check in report.checks:
                lines.append(f"    {check.status.upper()} {check.name}: {check.detail}")
        else:
            provider_names = []
            if has_swarm_review:
                provider_names.append("swarm-review")
            if has_mco:
                provider_names.append("mco")
            lines.append(f"  provider doctor: required for {', '.join(provider_names)} (run Validate for readiness)")
    return "\n".join(lines)


def pipeline_workbench_preview(
    pipeline: dict[str, Any],
    *,
    pipeline_name: str | None = None,
    include_validation: bool = False,
) -> str:
    lines: list[str] = []
    if pipeline_name and include_validation:
        lines.append(pipeline_validation_report(pipeline_name))
    inspector = pipeline_inspector_lines(pipeline)
    if inspector:
        if lines:
            lines.append("")
        lines.append("inspector:")
        lines.extend(inspector)
    lens_rows = pipeline_lens_rows(pipeline)
    if lens_rows:
        if lines:
            lines.append("")
        lines.append("lenses:")
        for row in lens_rows:
            lines.append(
                "  - "
                f"{row['stage']}:{row.get('target', row['variant'])} -> {row['lens_id']} "
                f"({row['label']}; {row['mode']}; {row['compatibility']})"
            )
            lines.append(f"    variant: {row['variant']}")
            lines.append(f"    contract: {row['contract']}")
    if pipeline_name:
        if lines:
            lines.append("")
        lines.append("diff:")
        lines.extend("  " + line for line in pipeline_diff_lines(pipeline_name))
    if lines:
        lines.append("")
    lines.append("graph:")
    model = pipeline_graph_model(pipeline)
    lines.extend(pipeline_graph_lines(model, width=100))
    return "\n".join(lines)


# Preset-facing aliases kept at the module boundary; the implementation still
# reuses the mature graph helpers internally.
preset_graph_board_model = pipeline_board_model
preset_graph_stage_rows = pipeline_stage_rows
preset_validation_report = pipeline_validation_report
start_preset_draft = start_pipeline_draft
validate_preset_draft = validate_pipeline_draft
