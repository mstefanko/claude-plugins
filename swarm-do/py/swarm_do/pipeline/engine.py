"""Deterministic pipeline graph helpers."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, Mapping

from .provider_review import DEFAULT_MAX_PARALLEL, KNOWN_REVIEW_SHIMS, load_review_doctor_cache


@dataclasses.dataclass(frozen=True)
class BudgetPreview:
    phase_count: int
    agent_count: int
    estimated_tokens: int
    estimated_cost_usd: float
    estimated_wall_clock_seconds: int
    fan_out_width: int
    parallelism: int
    stage_estimates: list[dict[str, Any]]
    exceeds: list[str]
    warnings: list[str] = dataclasses.field(default_factory=list)


def topological_layers(pipeline: Mapping[str, Any]) -> list[list[str]]:
    stages = pipeline.get("stages") or []
    ids = [stage["id"] for stage in stages]
    deps = {stage["id"]: set(stage.get("depends_on") or []) for stage in stages}
    remaining = set(ids)
    layers: list[list[str]] = []
    while remaining:
        ready = sorted(stage_id for stage_id in remaining if deps[stage_id].isdisjoint(remaining))
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise ValueError(f"cycle detected among stages: {cycle}")
        layers.append(ready)
        remaining.difference_update(ready)
    return layers


def stage_agent_count(stage: Mapping[str, Any]) -> int:
    return _stage_agent_estimate(stage, None)[0]


def _stage_agent_estimate(
    stage: Mapping[str, Any],
    doctor_cache: Mapping[str, Any] | None,
) -> tuple[int, str | None]:
    fan = stage.get("fan_out") if isinstance(stage, Mapping) else None
    if isinstance(fan, Mapping):
        raw_count = fan.get("count", 0)
        count = raw_count if isinstance(raw_count, int) and raw_count >= 0 else 0
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and merge.get("strategy") == "synthesize":
            count += 1
        return count, None
    provider = stage.get("provider") if isinstance(stage, Mapping) else None
    if isinstance(provider, Mapping):
        if provider.get("type") == "swarm-review":
            selection = provider.get("selection", "auto")
            if selection == "off":
                return 0, None
            max_parallel = provider.get("max_parallel")
            max_selected = max_parallel if isinstance(max_parallel, int) and max_parallel > 0 else DEFAULT_MAX_PARALLEL
            if selection == "explicit":
                providers = provider.get("providers", [])
                explicit_count = len(providers) if isinstance(providers, list) else 0
                return min(explicit_count, max_selected), None
            if doctor_cache is not None:
                eligible = doctor_cache.get("eligible_review_providers")
                eligible_count = len(eligible) if isinstance(eligible, list) else 0
                return min(max_selected, eligible_count), None
            upper_bound = min(max_selected, len(KNOWN_REVIEW_SHIMS))
            stage_id = stage.get("id") or "provider-review"
            return (
                upper_bound,
                f"{stage_id}: provider-review auto selection has no doctor cache; using upper-bound estimate {upper_bound}",
            )
        providers = provider.get("providers", [])
        return (len(providers) if isinstance(providers, list) else 1), None
    agents = stage.get("agents") if isinstance(stage, Mapping) else None
    return (len(agents) if isinstance(agents, list) else 0), None


def pipeline_agent_count(pipeline: Mapping[str, Any]) -> int:
    return sum(stage_agent_count(stage) for stage in pipeline.get("stages") or [])


def pipeline_parallelism(pipeline: Mapping[str, Any]) -> int:
    value = pipeline.get("parallelism", 1)
    return value if isinstance(value, int) and value >= 1 else 1


def estimate_phase_count(plan_path: str | Path | None) -> int:
    if not plan_path:
        return 1
    path = Path(plan_path)
    if not path.is_file():
        return 1
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"(?m)^###\s+Phase\s+\S+", text)
    return max(1, len(matches))


def budget_preview(preset: Mapping[str, Any], pipeline: Mapping[str, Any], plan_path: str | Path | None) -> BudgetPreview:
    phases = estimate_phase_count(plan_path)
    doctor_cache = _doctor_cache_for_pipeline(pipeline)
    stage_counts: list[tuple[Mapping[str, Any], int, str | None]] = [
        (stage, *_stage_agent_estimate(stage, doctor_cache))
        for stage in pipeline.get("stages") or []
    ]
    agents_per_phase = sum(count for _stage, count, _warning in stage_counts)
    agents = agents_per_phase * phases
    layers = topological_layers(pipeline)
    parallelism = pipeline_parallelism(pipeline)
    fan_out_width = max((count for _stage, count, _warning in stage_counts), default=0)
    stage_estimates = []
    warnings: list[str] = []
    for stage, count, warning in stage_counts:
        row: dict[str, Any] = {
            "stage_id": stage.get("id"),
            "agents_per_phase": count,
            "estimated_tokens_per_phase": count * 18_000,
        }
        if warning:
            row["estimate_warning"] = warning
            warnings.append(warning)
        stage_estimates.append(row)
    estimated_tokens = agents * 18_000
    estimated_cost = round(agents * 0.18, 4)
    effective_layers = sum(max(1, (len(layer) + parallelism - 1) // parallelism) for layer in layers)
    estimated_wall = phases * max(1, effective_layers) * 240

    budget = preset.get("budget") or {}
    exceeds: list[str] = []
    max_agents = budget.get("max_agents_per_run")
    if isinstance(max_agents, int) and agents > max_agents:
        exceeds.append(f"agent count {agents} exceeds max_agents_per_run {max_agents}")
    max_cost = budget.get("max_estimated_cost_usd")
    if isinstance(max_cost, (int, float)) and estimated_cost > float(max_cost):
        exceeds.append(f"estimated cost ${estimated_cost:.4f} exceeds max_estimated_cost_usd ${float(max_cost):.4f}")
    max_wall = budget.get("max_wall_clock_seconds")
    if isinstance(max_wall, int) and estimated_wall > max_wall:
        exceeds.append(f"estimated wall clock {estimated_wall}s exceeds max_wall_clock_seconds {max_wall}s")

    return BudgetPreview(
        phases,
        agents,
        estimated_tokens,
        estimated_cost,
        estimated_wall,
        fan_out_width,
        parallelism,
        stage_estimates,
        exceeds,
        warnings,
    )


def _doctor_cache_for_pipeline(pipeline: Mapping[str, Any]) -> dict[str, Any] | None:
    cache = load_review_doctor_cache()
    if not cache:
        return None
    cached_pipeline = cache.get("pipeline_name")
    current_pipeline = pipeline.get("name")
    if isinstance(cached_pipeline, str) and cached_pipeline and cached_pipeline != current_pipeline:
        return None
    return cache


def graph_lines(pipeline: Mapping[str, Any]) -> list[str]:
    stage_by_id = {stage["id"]: stage for stage in pipeline.get("stages") or []}
    lines: list[str] = [f"parallelism: {pipeline_parallelism(pipeline)}"]
    for layer_no, layer in enumerate(topological_layers(pipeline), 1):
        lines.append(f"layer {layer_no}:")
        for stage_id in layer:
            stage = stage_by_id[stage_id]
            deps = stage.get("depends_on") or []
            if "fan_out" in stage:
                fan = stage["fan_out"]
                merge = stage.get("merge", {})
                lines.append(
                    f"  - {stage_id} depends_on={deps} fan_out={fan.get('count')} role={fan.get('role')} "
                    f"variant={fan.get('variant')} merge={merge.get('strategy')}:{merge.get('agent')}"
                )
            elif "provider" in stage:
                provider = stage["provider"]
                tolerance = stage.get("failure_tolerance", {"mode": "strict"})
                selection = provider.get("selection")
                selection_text = f" selection={selection}" if selection is not None else ""
                lines.append(
                    f"  - {stage_id} depends_on={deps} provider={provider.get('type')} "
                    f"command={provider.get('command')}{selection_text} providers={provider.get('providers')} "
                    f"mode={provider.get('mode', 'review')} output={provider.get('output', 'findings')} "
                    f"memory={provider.get('memory', False)} timeout_seconds={provider.get('timeout_seconds')} "
                    f"failure_tolerance={tolerance.get('mode', 'strict')}"
                )
            else:
                roles = [agent.get("role") for agent in stage.get("agents") or []]
                lines.append(f"  - {stage_id} depends_on={deps} agents={roles}")
    return lines
