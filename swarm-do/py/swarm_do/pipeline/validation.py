"""Validation gates for preset and pipeline loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .engine import BudgetPreview, budget_preview, topological_layers
from .paths import REPO_ROOT
from .registry import find_pipeline, find_preset, load_pipeline, load_preset
from .resolver import BACKENDS, EFFORTS, BackendResolver


VARIANTS = {"same", "prompt_variants", "models"}
MERGE_STRATEGIES = {"synthesize", "vote"}
TOLERANCE_MODES = {"strict", "quorum", "best-effort"}
PIPELINE_TOP_KEYS = {"pipeline_version", "name", "description", "parallelism", "stages"}
PRESET_TOP_KEYS = {"name", "description", "pipeline", "origin", "routing", "budget", "forked_from_hash"}
STAGE_KEYS = {"id", "depends_on", "agents", "fan_out", "merge", "failure_tolerance"}
FAN_OUT_KEYS = {"role", "count", "variant", "variants", "routes"}
MERGE_KEYS = {"strategy", "agent"}
AGENT_KEYS = {"role", "backend", "model", "effort", "route"}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    budget: BudgetPreview | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, message: str) -> None:
        self.errors.append(message)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _role_exists(role: str) -> bool:
    if role == "orchestrator":
        return True
    return (REPO_ROOT / "agents" / f"{role}.md").is_file()


def _all_roles(pipeline: Mapping[str, Any]) -> list[str]:
    roles: list[str] = []
    for stage in pipeline.get("stages") or []:
        for agent in stage.get("agents") or []:
            if isinstance(agent, Mapping) and isinstance(agent.get("role"), str):
                roles.append(agent["role"])
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping) and isinstance(fan.get("role"), str):
            roles.append(fan["role"])
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and isinstance(merge.get("agent"), str):
            roles.append(merge["agent"])
    return roles


def schema_lint_preset(preset: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(preset.keys()) - PRESET_TOP_KEYS)
    if unknown:
        errors.append(f"preset: unknown top-level keys: {', '.join(unknown)}")
    for key in ("name", "pipeline"):
        if not isinstance(preset.get(key), str) or not preset.get(key):
            errors.append(f"preset: {key} must be a non-empty string")
    if "origin" in preset and preset["origin"] not in {"stock", "user", "experiment"}:
        errors.append("preset: origin must be stock, user, or experiment")
    if "routing" in preset and not isinstance(preset["routing"], Mapping):
        errors.append("preset: routing must be a table")
    budget = preset.get("budget")
    if not isinstance(budget, Mapping):
        errors.append("preset: budget table is required")
    else:
        for key in ("max_agents_per_run", "max_wall_clock_seconds"):
            if not isinstance(budget.get(key), int):
                errors.append(f"preset: budget.{key} must be an integer")
        if not isinstance(budget.get("max_estimated_cost_usd"), (int, float)):
            errors.append("preset: budget.max_estimated_cost_usd must be a number")
    return errors


def _lint_route(route: Any, path: str) -> list[str]:
    errors: list[str] = []
    if isinstance(route, str):
        return errors
    if not isinstance(route, Mapping):
        return [f"{path}: route must be an object or named preset route"]
    if route.get("backend") not in BACKENDS:
        errors.append(f"{path}.backend must be one of {sorted(BACKENDS)}")
    if not isinstance(route.get("model"), str) or not route.get("model"):
        errors.append(f"{path}.model must be a non-empty string")
    if route.get("effort") not in EFFORTS:
        errors.append(f"{path}.effort must be one of {sorted(EFFORTS)}")
    return errors


def schema_lint_pipeline(pipeline: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(pipeline.keys()) - PIPELINE_TOP_KEYS)
    if unknown:
        errors.append(f"pipeline: unknown top-level keys: {', '.join(unknown)}")
    if not isinstance(pipeline.get("pipeline_version"), int):
        errors.append("pipeline: pipeline_version must be an integer")
    if not isinstance(pipeline.get("name"), str) or not pipeline.get("name"):
        errors.append("pipeline: name must be a non-empty string")
    if "parallelism" in pipeline:
        parallelism = pipeline.get("parallelism")
        if not isinstance(parallelism, int) or parallelism < 1 or parallelism > 32:
            errors.append("pipeline: parallelism must be an integer from 1 to 32")
    stages = pipeline.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("pipeline: stages must be a non-empty array")
        return errors

    ids: set[str] = set()
    for idx, stage in enumerate(stages):
        path = f"pipeline.stages[{idx}]"
        if not isinstance(stage, Mapping):
            errors.append(f"{path}: stage must be an object")
            continue
        unknown_stage = sorted(set(stage.keys()) - STAGE_KEYS)
        if unknown_stage:
            errors.append(f"{path}: unknown keys: {', '.join(unknown_stage)}")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"{path}.id must be a non-empty string")
        elif stage_id in ids:
            errors.append(f"{path}.id duplicates stage id {stage_id}")
        else:
            ids.add(stage_id)
        deps = stage.get("depends_on", [])
        if deps is None:
            deps = []
        if not _is_str_list(deps):
            errors.append(f"{path}.depends_on must be an array of stage ids")
        has_agents = "agents" in stage
        has_fan = "fan_out" in stage
        if has_agents == has_fan:
            errors.append(f"{path}: exactly one of agents or fan_out is required")
        if has_agents:
            agents = stage.get("agents")
            if not isinstance(agents, list) or not agents:
                errors.append(f"{path}.agents must be a non-empty array")
            else:
                for a_idx, agent in enumerate(agents):
                    a_path = f"{path}.agents[{a_idx}]"
                    if not isinstance(agent, Mapping):
                        errors.append(f"{a_path}: agent must be an object")
                        continue
                    unknown_agent = sorted(set(agent.keys()) - AGENT_KEYS)
                    if unknown_agent:
                        errors.append(f"{a_path}: unknown keys: {', '.join(unknown_agent)}")
                    if not isinstance(agent.get("role"), str) or not agent.get("role"):
                        errors.append(f"{a_path}.role must be a non-empty string")
                    override_keys = {k for k in ("backend", "model", "effort") if k in agent}
                    if override_keys and override_keys != {"backend", "model", "effort"}:
                        errors.append(f"{a_path}: backend/model/effort overrides must be supplied together")
                    if override_keys:
                        errors.extend(_lint_route(agent, a_path))
        if has_fan:
            fan = stage.get("fan_out")
            if not isinstance(fan, Mapping):
                errors.append(f"{path}.fan_out must be an object")
            else:
                unknown_fan = sorted(set(fan.keys()) - FAN_OUT_KEYS)
                if unknown_fan:
                    errors.append(f"{path}.fan_out: unknown keys: {', '.join(unknown_fan)}")
                if not isinstance(fan.get("role"), str) or not fan.get("role"):
                    errors.append(f"{path}.fan_out.role must be a non-empty string")
                count = fan.get("count")
                if not isinstance(count, int) or not (1 <= count <= 10):
                    errors.append(f"{path}.fan_out.count must be an integer from 1 to 10")
                variant = fan.get("variant")
                if variant not in VARIANTS:
                    errors.append(f"{path}.fan_out.variant must be one of {sorted(VARIANTS)}")
                if variant == "prompt_variants":
                    variants = fan.get("variants")
                    if not _is_str_list(variants) or len(variants) != count:
                        errors.append(f"{path}.fan_out.variants must be an array of count strings")
                if variant == "models":
                    routes = fan.get("routes")
                    if not isinstance(routes, list) or len(routes) != count:
                        errors.append(f"{path}.fan_out.routes must be an array with count entries")
                    else:
                        for r_idx, route in enumerate(routes):
                            if isinstance(route, str) and any(ch in route for ch in ("/", ".")):
                                errors.append(f"{path}.fan_out.routes[{r_idx}]: bare model IDs are invalid; use route objects")
                            errors.extend(_lint_route(route, f"{path}.fan_out.routes[{r_idx}]"))
            if "merge" not in stage:
                errors.append(f"{path}: fan_out stages require merge")
        if "merge" in stage:
            merge = stage["merge"]
            if not isinstance(merge, Mapping):
                errors.append(f"{path}.merge must be an object")
            else:
                unknown_merge = sorted(set(merge.keys()) - MERGE_KEYS)
                if unknown_merge:
                    errors.append(f"{path}.merge: unknown keys: {', '.join(unknown_merge)}")
                if merge.get("strategy") not in MERGE_STRATEGIES:
                    errors.append(f"{path}.merge.strategy must be synthesize or vote")
                if merge.get("strategy") == "synthesize" and not isinstance(merge.get("agent"), str):
                    errors.append(f"{path}.merge.agent is required for synthesize")
        tolerance = stage.get("failure_tolerance", {"mode": "strict"})
        if not isinstance(tolerance, Mapping):
            errors.append(f"{path}.failure_tolerance must be a structured object")
        else:
            mode = tolerance.get("mode", "strict")
            if mode not in TOLERANCE_MODES:
                errors.append(f"{path}.failure_tolerance.mode must be one of {sorted(TOLERANCE_MODES)}")
            if mode == "quorum":
                min_success = tolerance.get("min_success")
                count = stage.get("fan_out", {}).get("count", 1) if isinstance(stage.get("fan_out"), Mapping) else 1
                if not isinstance(min_success, int) or not (1 <= min_success <= count):
                    errors.append(f"{path}.failure_tolerance.min_success must be 1..fan_out.count for quorum")
            elif "min_success" in tolerance:
                errors.append(f"{path}.failure_tolerance.min_success is only valid for quorum")

    for idx, stage in enumerate(stages):
        for dep in stage.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"pipeline.stages[{idx}].depends_on references unknown stage {dep}")
    return errors


def validate_preset_and_pipeline(
    preset_name: str,
    plan_path: str | None = None,
    include_budget: bool = False,
) -> tuple[ValidationResult, dict[str, Any], dict[str, Any], Path]:
    result = ValidationResult()
    preset_item = find_preset(preset_name)
    if preset_item is None:
        result.add(f"preset not found: {preset_name}")
        return result, {}, {}, Path()
    try:
        preset = load_preset(preset_item.path)
    except Exception as exc:
        result.add(f"preset parse failed: {exc}")
        return result, {}, {}, preset_item.path
    result, pipeline = validate_preset_mapping(preset, preset_name, plan_path, include_budget)
    return result, preset, pipeline, preset_item.path


def validate_preset_mapping(
    preset: Mapping[str, Any],
    preset_name: str | None = None,
    plan_path: str | None = None,
    include_budget: bool = False,
) -> tuple[ValidationResult, dict[str, Any]]:
    result = ValidationResult()
    result.errors.extend(schema_lint_preset(preset))

    pipeline_item = find_pipeline(str(preset.get("pipeline", "")))
    if pipeline_item is None:
        result.add(f"pipeline not found: {preset.get('pipeline')}")
        return result, {}
    try:
        pipeline = load_pipeline(pipeline_item.path)
    except Exception as exc:
        result.add(f"pipeline parse failed: {exc}")
        return result, {}
    result.errors.extend(schema_lint_pipeline(pipeline))
    result.errors.extend(role_existence_errors(pipeline))
    result.errors.extend(variant_existence_errors(pipeline))
    result.errors.extend(route_resolution_errors(pipeline, preset_name, preset))
    result.errors.extend(invariant_errors(pipeline, preset_name, preset))
    try:
        topological_layers(pipeline)
    except ValueError as exc:
        result.add(str(exc))

    if include_budget:
        try:
            result.budget = budget_preview(preset, pipeline, plan_path)
            result.errors.extend(result.budget.exceeds)
        except Exception as exc:
            result.add(f"budget preview failed: {exc}")
    return result, pipeline


def role_existence_errors(pipeline: Mapping[str, Any]) -> list[str]:
    return [f"role file missing for {role}" for role in sorted(set(_all_roles(pipeline))) if not _role_exists(role)]


def variant_existence_errors(pipeline: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for stage in pipeline.get("stages") or []:
        fan = stage.get("fan_out")
        if not isinstance(fan, Mapping) or fan.get("variant") != "prompt_variants":
            continue
        role = fan.get("role")
        if not isinstance(role, str):
            continue
        for variant in fan.get("variants") or []:
            path = REPO_ROOT / "roles" / role / "variants" / f"{variant}.md"
            if not path.is_file():
                errors.append(f"variant file missing for {role}/{variant}: {path}")
    return errors


def route_resolution_errors(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    for stage in pipeline.get("stages") or []:
        stage_id = stage.get("id", "<unknown>")
        for agent in stage.get("agents") or []:
            if not isinstance(agent, Mapping):
                continue
            role = agent.get("role")
            if not isinstance(role, str):
                continue
            override = agent.get("route")
            if override is None and {"backend", "model", "effort"} <= set(agent.keys()):
                override = agent
            if override is None:
                continue
            try:
                resolver.resolve(role, override=override)
            except Exception as exc:
                errors.append(f"route resolution failed for stage {stage_id} role {role}: {exc}")

        fan = stage.get("fan_out")
        if not isinstance(fan, Mapping) or fan.get("variant") != "models":
            continue
        role = fan.get("role")
        if not isinstance(role, str):
            continue
        routes = fan.get("routes")
        if not isinstance(routes, list):
            continue
        for idx, route in enumerate(routes):
            try:
                resolver.resolve(role, override=route)
            except Exception as exc:
                errors.append(f"route resolution failed for stage {stage_id} fan_out.routes[{idx}]: {exc}")
    return errors


def invariant_errors(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    try:
        if not resolver.is_claude_backed("orchestrator", "hard"):
            errors.append("invariant: orchestrator must resolve to a Claude backend")
    except Exception as exc:
        errors.append(f"invariant: orchestrator route resolution failed: {exc}")
    try:
        if not resolver.is_claude_backed("agent-code-synthesizer", "hard"):
            errors.append("invariant: agent-code-synthesizer must resolve to a Claude backend")
    except Exception as exc:
        errors.append(f"invariant: synthesizer route resolution failed: {exc}")
    for stage in pipeline.get("stages") or []:
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and merge.get("strategy") == "synthesize":
            agent = merge.get("agent")
            if isinstance(agent, str):
                try:
                    if not resolver.is_claude_backed(agent, "hard"):
                        errors.append(f"invariant: synthesize merge agent {agent} must resolve to a Claude backend")
                except Exception as exc:
                    errors.append(f"invariant: merge agent {agent} route resolution failed: {exc}")
    return errors
