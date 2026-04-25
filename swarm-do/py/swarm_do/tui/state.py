"""Shared state readers for the swarm-do TUI.

This module intentionally has no Textual dependency so it can be unit-tested
without installing the optional TUI stack.
"""

from __future__ import annotations

import dataclasses
import copy
import json
import os
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
from swarm_do.pipeline.engine import graph_lines, topological_layers
from swarm_do.pipeline.paths import resolve_data_dir
from swarm_do.pipeline.providers import ProviderDoctorReport, provider_doctor
from swarm_do.pipeline.registry import find_pipeline, list_pipelines, list_presets, load_pipeline, load_preset
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, BackendResolver, active_preset_name
from swarm_do.pipeline.validation import (
    MCO_PROVIDER_ORDER,
    MCO_PROVIDERS,
    TOLERANCE_MODES,
    ValidationResult,
    invariant_errors,
    role_existence_errors,
    route_resolution_errors,
    schema_lint_pipeline,
    validate_preset_and_pipeline,
    validate_preset_pipeline_mappings,
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

    def render(self) -> str:
        cost = f"${self.cost_today:.4f}" if self.cost_today is not None else "n/a"
        claude = self.last_429_claude or "n/a"
        codex = self.last_429_codex or "n/a"
        rendered = (
            f"preset={self.preset} pipeline={self.pipeline} runs_today={self.runs_today} "
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


PIPELINE_INTENTS: dict[str, str] = {
    "brainstorm": "brainstorm",
    "default": "implement",
    "design": "design",
    "lightweight": "implement",
    "hybrid-review": "review",
    "mco-review-lab": "mco-assisted review",
    "compete": "competitive implementation",
    "research": "research",
    "review": "review",
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


@dataclasses.dataclass
class PipelineEditDraft:
    pipeline_name: str
    preset_name: str | None
    origin: str
    pipeline: dict[str, Any]
    original_pipeline: dict[str, Any]
    status: str = "saved"
    message: str = "draft ready"
    undo_stack: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    redo_stack: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return self.pipeline != self.original_pipeline

    def mark_saved(self) -> None:
        self.original_pipeline = copy.deepcopy(self.pipeline)
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
    for item in list_pipelines():
        try:
            pipeline = load_pipeline(item.path)
        except Exception as exc:
            rows.append(PipelineGalleryRow("custom", item.name, item.origin, None, f"unreadable: {exc}"))
            continue
        rows.append(
            PipelineGalleryRow(
                intent=pipeline_intent(item.name, pipeline),
                name=item.name,
                origin=item.origin,
                preset=_preset_for_pipeline(item.name),
                description=str(pipeline.get("description") or ""),
            )
        )
    order = {intent: idx for idx, intent in enumerate(PIPELINE_INTENT_ORDER)}
    origin_order = {"stock": 0, "experiment": 1, "user": 2, "path": 3}
    return sorted(rows, key=lambda row: (order.get(row.intent, 99), row.intent, origin_order.get(row.origin, 9), row.name))


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
        return f"{provider.get('type')} {provider.get('command')} {provider.get('providers')}"
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


def _stage_by_id(pipeline: Mapping[str, Any], stage_id: str) -> Mapping[str, Any] | None:
    for stage in pipeline.get("stages") or []:
        if isinstance(stage, Mapping) and stage.get("id") == stage_id:
            return stage
    return None


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
    item = find_pipeline(pipeline_name)
    if item is None:
        raise ValueError(f"pipeline not found: {pipeline_name}")
    pipeline = load_pipeline(item.path)
    selected_preset = preset_name if preset_name is not None else _preset_for_pipeline(pipeline_name)
    return PipelineEditDraft(
        pipeline_name=item.name,
        preset_name=selected_preset,
        origin=item.origin,
        pipeline=copy.deepcopy(pipeline),
        original_pipeline=copy.deepcopy(pipeline),
    )


def _mutable_stage_by_id(pipeline: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in pipeline.get("stages") or []:
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    raise ValueError(f"stage not found: {stage_id}")


def _mutable_stage_agent(pipeline: dict[str, Any], stage_id: str, agent_index: int) -> dict[str, Any]:
    stage = _mutable_stage_by_id(pipeline, stage_id)
    agents = stage.get("agents")
    if not isinstance(agents, list):
        raise ValueError(f"stage {stage_id} is not an agents stage")
    if agent_index < 0 or agent_index >= len(agents) or not isinstance(agents[agent_index], dict):
        raise ValueError(f"agent index out of range for stage {stage_id}: {agent_index}")
    return agents[agent_index]


def _mutable_stage_fan_out(pipeline: dict[str, Any], stage_id: str) -> dict[str, Any]:
    stage = _mutable_stage_by_id(pipeline, stage_id)
    fan = stage.get("fan_out")
    if not isinstance(fan, dict):
        raise ValueError(f"stage {stage_id} is not a fan_out stage")
    return fan


def _mutable_mco_provider_stage(pipeline: dict[str, Any], stage_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stage = _mutable_stage_by_id(pipeline, stage_id)
    provider = stage.get("provider")
    if not isinstance(provider, dict) or provider.get("type") != "mco":
        raise ValueError(f"stage {stage_id} is not an MCO provider stage")
    return stage, provider


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


def _normalize_mco_providers(providers: list[str]) -> list[str]:
    if not isinstance(providers, list):
        raise ValueError("providers must be a list")
    selected: list[str] = []
    for provider in providers:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("providers must contain non-empty provider names")
        name = provider.strip()
        if name not in MCO_PROVIDERS:
            raise ValueError(f"unsupported MCO provider: {name}")
        if name not in selected:
            selected.append(name)
    if not (1 <= len(selected) <= 5):
        raise ValueError("MCO providers must contain 1..5 unique provider names")
    return [name for name in MCO_PROVIDER_ORDER if name in selected]


def _validate_mco_timeout(timeout_seconds: int) -> int:
    if not isinstance(timeout_seconds, int) or not (1 <= timeout_seconds <= 86400):
        raise ValueError("timeout_seconds must be an integer from 1 to 86400")
    return timeout_seconds


def _provider_failure_tolerance(mode: str, min_success: int | None, *, branch_count: int) -> dict[str, int | str]:
    if mode not in TOLERANCE_MODES:
        raise ValueError(f"failure_tolerance mode must be one of {sorted(TOLERANCE_MODES)}")
    if mode != "quorum":
        return {"mode": mode}
    if not isinstance(min_success, int) or not (1 <= min_success <= branch_count):
        raise ValueError("min_success must be 1..provider count for quorum")
    return {"mode": mode, "min_success": min_success}


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


def status_summary(data_dir: Path | None = None, now: datetime | None = None) -> StatusSummary:
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
    preset = active_preset_name() or "custom"
    pipeline = str(context.get("pipeline_name") or "default")
    return StatusSummary(
        preset=preset,
        pipeline=pipeline,
        runs_today=runs_today,
        cost_today=sum(cost_values) if cost_values else None,
        last_429_claude=last_429.get("claude").isoformat().replace("+00:00", "Z") if "claude" in last_429 else None,
        last_429_codex=last_429.get("codex").isoformat().replace("+00:00", "Z") if "codex" in last_429 else None,
        latest_checkpoint=latest_checkpoint_event(data_dir),
        latest_observation=latest_observation(data_dir),
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


def latest_mco_provider_artifact(stage_id: str, data_dir: Path | None = None) -> Path | None:
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


def mco_provider_result_preview(stage_id: str, data_dir: Path | None = None) -> list[str]:
    artifact = latest_mco_provider_artifact(stage_id, data_dir)
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
    selected = payload.get("selected_providers")
    findings_count = len(findings) if isinstance(findings, list) else 0
    error_rows = errors if isinstance(errors, list) else []
    selected_text = ", ".join(str(item) for item in selected) if isinstance(selected, list) else "n/a"
    lines = [
        f"provider-result: {artifact}",
        (
            f"  status={payload.get('status', 'unknown')} "
            f"provider_count={payload.get('provider_count', 'n/a')} "
            f"selected={selected_text} findings={findings_count} errors={len(error_rows)}"
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
        lines.append(
            f"{prefix}  provider: type={provider.get('type')} command={provider.get('command')} "
            f"providers={provider.get('providers')}"
        )
        if provider.get("type") == "mco":
            lines.append(
                f"{prefix}  provider-boundary: experimental read-only evidence; "
                "no merge, approval, memory, or repo writes"
            )
        lines.append(
            f"{prefix}  provider-config: mode={provider.get('mode', 'review')} "
            f"output={provider.get('output', 'findings')} memory={provider.get('memory', False)} "
            f"timeout_seconds={provider.get('timeout_seconds')}"
        )
        if provider.get("type") == "mco":
            lines.extend(f"{prefix}  {line}" for line in mco_provider_result_preview(stage_id))
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


def stage_inspector_text(pipeline: Mapping[str, Any], stage_id: str | None) -> str:
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
        preset["pipeline"] = draft.pipeline_name
        return validate_preset_pipeline_mappings(preset, draft.pipeline, draft.preset_name, plan_path, include_budget)

    result = ValidationResult()
    result.errors.extend(schema_lint_pipeline(draft.pipeline))
    result.errors.extend(role_existence_errors(draft.pipeline))
    result.errors.extend(variant_existence_errors(draft.pipeline))
    result.errors.extend(route_resolution_errors(draft.pipeline, None, None))
    result.errors.extend(invariant_errors(draft.pipeline, None, None))
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
    for stage in pipeline.get("stages") or []:
        provider = stage.get("provider") if isinstance(stage, Mapping) else None
        if isinstance(provider, Mapping) and provider.get("type") == "mco":
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
    preset_name = _preset_for_pipeline(pipeline_name)
    lines: list[str] = ["validation:"]
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
    if preset_name is None:
        lines.append("  full validation needs a preset that references this pipeline")
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
    if _pipeline_has_provider(pipeline_name, "mco"):
        if include_provider_doctor:
            report = provider_doctor_fn(preset_name=preset_name, run_mco=True)
            status = "OK" if report.ok else "ERROR"
            lines.append(f"  provider doctor: {status} required={', '.join(report.required_providers) or 'none'}")
            for check in report.checks:
                lines.append(f"    {check.status.upper()} {check.name}: {check.detail}")
        else:
            lines.append("  provider doctor: required for mco (run Validate for readiness)")
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
    lines.extend(graph_lines(pipeline))
    return "\n".join(lines)
