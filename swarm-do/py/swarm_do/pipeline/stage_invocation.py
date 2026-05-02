"""Plan and render per-stage orchestrator invocations."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .engine import topological_layers
from .graph_source import canonical_graph_hash, resolve_preset_graph
from .paths import REPO_ROOT, resolve_data_dir


@dataclasses.dataclass(frozen=True)
class StageInvocation:
    stage_id: str
    agent_role: str
    layer_index: int
    fan_out_key: str | None
    fan_out_index: int | None
    merge_target: str | None
    is_provider_stage: bool
    lens_chain: tuple[str, ...]
    failure_tolerance: str
    role_brief_path: Path
    expected_result_path: Path
    upstream_stage_ids: tuple[str, ...]
    task_prompt_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "agent_role": self.agent_role,
            "layer_index": self.layer_index,
            "fan_out_key": self.fan_out_key,
            "fan_out_index": self.fan_out_index,
            "merge_target": self.merge_target,
            "is_provider_stage": self.is_provider_stage,
            "lens_chain": list(self.lens_chain),
            "failure_tolerance": self.failure_tolerance,
            "role_brief_path": str(self.role_brief_path),
            "expected_result_path": str(self.expected_result_path),
            "upstream_stage_ids": list(self.upstream_stage_ids),
            "task_prompt_path": str(self.task_prompt_path) if self.task_prompt_path else None,
        }


def plan_stage_invocations(
    preset: Mapping[str, Any],
    phase_context: Mapping[str, Any],
    *,
    data_dir: Path | None = None,
) -> tuple[list[StageInvocation], dict[str, Any]]:
    """Resolve the active preset graph into concrete per-agent stage calls."""

    resolved = resolve_preset_graph(preset)
    pipeline = resolved.graph
    layers = topological_layers(pipeline)
    stage_by_id = {
        str(stage.get("id")): stage
        for stage in pipeline.get("stages") or []
        if isinstance(stage, Mapping) and isinstance(stage.get("id"), str)
    }
    base = data_dir or resolve_data_dir()
    run_id = str(phase_context.get("run_id") or "")
    phase_id = str(phase_context.get("phase_id") or "")
    result_dir = base / "runs" / run_id / "phases" / phase_id / "stage_results"
    invocations: list[StageInvocation] = []
    materialized_by_source: dict[str, list[str]] = {}

    for layer_index, layer in enumerate(layers):
        for source_stage_id in layer:
            stage = stage_by_id[source_stage_id]
            upstream = tuple(
                child
                for dep in stage.get("depends_on") or []
                for child in materialized_by_source.get(str(dep), (str(dep),))
            )
            planned = _invocations_for_stage(
                stage,
                layer_index=layer_index,
                result_dir=result_dir,
                upstream_stage_ids=upstream,
            )
            materialized_by_source[source_stage_id] = [item.stage_id for item in planned]
            invocations.extend(planned)

    graph_hash = canonical_graph_hash({"preset": preset.get("name"), "pipeline": pipeline})
    snapshot = {
        "graph_hash": graph_hash,
        "preset_id": preset.get("name") if isinstance(preset.get("name"), str) else resolved.source_name,
        "topological_layers": layers,
        "fan_out_branches": _fan_out_snapshot(pipeline),
        "lenses": _lens_snapshot(pipeline),
        "failure_tolerance": _failure_tolerance_snapshot(pipeline),
        "source_hash": resolved.source_hash,
        "source_name": resolved.source_name,
        "source": resolved.source,
    }
    return invocations, snapshot


def render_orchestrator_brief(
    *,
    base_prompt: str,
    stage_invocations: list[StageInvocation],
    run_id: str,
    phase_id: str,
) -> str:
    """Append the controller-owned stage dispatch contract to a phase brief."""

    lines = [
        base_prompt.rstrip(),
        "",
        "## Controller-Owned Stage Dispatch",
        "",
        "You are the foreground orchestrator. Dispatch stages with Task; do not edit files directly.",
        "After each stage writes its result JSON, print exactly one marker line:",
        'STAGE_COMPLETE {"stage_id":"<stage_id>","result_path":"<absolute path>"}',
        'For failures, print: STAGE_FAILED {"stage_id":"<stage_id>","failure_kind":"<kind>","notes":"<short notes>"}',
        "",
        f"- run_id: {run_id}",
        f"- phase_id: {phase_id}",
        "",
        "### Planned Stages",
    ]
    for invocation in stage_invocations:
        result_path = invocation.expected_result_path
        role_text = _role_brief_excerpt(invocation.role_brief_path)
        stage_payload = {
            "stage_id": invocation.stage_id,
            "agent_role": invocation.agent_role,
            "result_path": str(result_path),
            "upstream_stage_ids": list(invocation.upstream_stage_ids),
            "failure_tolerance": invocation.failure_tolerance,
            "lens_chain": list(invocation.lens_chain),
        }
        prompt = "\n".join(
            [
                f"Stage contract JSON: {json.dumps(stage_payload, sort_keys=True)}",
                "",
                role_text,
                "",
                "Write a stage result JSON to the prescribed result_path. Then return a concise summary.",
            ]
        )
        lines.extend(
            [
                "",
                f"#### {invocation.stage_id}",
                f"- agent_role: {invocation.agent_role}",
                f"- result_path: {result_path}",
                f"- upstream_stage_ids: {', '.join(invocation.upstream_stage_ids) or '-'}",
                "",
                "Dispatch form:",
                "```text",
                f'Task(subagent_type="general-purpose", prompt={json.dumps(prompt)})',
                "```",
                "",
                "Completion marker:",
                "```text",
                "STAGE_COMPLETE "
                + json.dumps({"stage_id": invocation.stage_id, "result_path": str(result_path)}, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _invocations_for_stage(
    stage: Mapping[str, Any],
    *,
    layer_index: int,
    result_dir: Path,
    upstream_stage_ids: tuple[str, ...],
) -> list[StageInvocation]:
    source_stage_id = str(stage["id"])
    tolerance = _failure_tolerance(stage)
    if isinstance(stage.get("fan_out"), Mapping):
        fan = stage["fan_out"]
        count = int(fan.get("count") or 0)
        count = max(1, count)
        role = str(fan.get("role") or "agent-writer")
        variant_mode = str(fan.get("variant") or "same")
        variants = [str(item) for item in fan.get("variants") or [] if isinstance(item, str)]
        invocations: list[StageInvocation] = []
        fanout_ids: list[str] = []
        for index in range(count):
            variant = variants[index] if index < len(variants) else f"{variant_mode}-{index + 1}"
            stage_id = f"{source_stage_id}:fanout-{index + 1}"
            fanout_ids.append(stage_id)
            invocations.append(
                _invocation(
                    stage_id,
                    role,
                    layer_index=layer_index,
                    result_dir=result_dir,
                    fan_out_key=variant,
                    fan_out_index=index,
                    merge_target=None,
                    is_provider_stage=False,
                    lens_chain=(),
                    failure_tolerance=tolerance,
                    upstream_stage_ids=upstream_stage_ids,
                )
            )
        merge = stage.get("merge") if isinstance(stage.get("merge"), Mapping) else None
        if merge is not None and merge.get("strategy") == "synthesize":
            role = str(merge.get("agent") or "agent-analysis-judge")
            invocations.append(
                _invocation(
                    f"{source_stage_id}:merge",
                    role,
                    layer_index=layer_index,
                    result_dir=result_dir,
                    fan_out_key=None,
                    fan_out_index=None,
                    merge_target=source_stage_id,
                    is_provider_stage=False,
                    lens_chain=(),
                    failure_tolerance=tolerance,
                    upstream_stage_ids=tuple(fanout_ids),
                )
            )
        return invocations
    if isinstance(stage.get("provider"), Mapping):
        provider = stage["provider"]
        role = f"provider:{provider.get('type') or 'unknown'}"
        return [
            _invocation(
                source_stage_id,
                role,
                layer_index=layer_index,
                result_dir=result_dir,
                fan_out_key=None,
                fan_out_index=None,
                merge_target=None,
                is_provider_stage=True,
                lens_chain=(),
                failure_tolerance=tolerance,
                upstream_stage_ids=upstream_stage_ids,
            )
        ]
    agents = stage.get("agents") if isinstance(stage.get("agents"), list) else []
    invocations = []
    for index, agent in enumerate(agents):
        if not isinstance(agent, Mapping):
            continue
        role = str(agent.get("role") or "agent-writer")
        stage_id = source_stage_id if len(agents) == 1 else f"{source_stage_id}:{index + 1}"
        lens = agent.get("lens")
        invocations.append(
            _invocation(
                stage_id,
                role,
                layer_index=layer_index,
                result_dir=result_dir,
                fan_out_key=None,
                fan_out_index=None,
                merge_target=None,
                is_provider_stage=False,
                lens_chain=(str(lens),) if isinstance(lens, str) and lens else (),
                failure_tolerance=tolerance,
                upstream_stage_ids=upstream_stage_ids,
            )
        )
    return invocations


def _invocation(
    stage_id: str,
    agent_role: str,
    *,
    layer_index: int,
    result_dir: Path,
    fan_out_key: str | None,
    fan_out_index: int | None,
    merge_target: str | None,
    is_provider_stage: bool,
    lens_chain: tuple[str, ...],
    failure_tolerance: str,
    upstream_stage_ids: tuple[str, ...],
) -> StageInvocation:
    return StageInvocation(
        stage_id=stage_id,
        agent_role=agent_role,
        layer_index=layer_index,
        fan_out_key=fan_out_key,
        fan_out_index=fan_out_index,
        merge_target=merge_target,
        is_provider_stage=is_provider_stage,
        lens_chain=lens_chain,
        failure_tolerance=failure_tolerance,
        role_brief_path=_role_brief_path(agent_role),
        expected_result_path=result_dir / f"{_safe_filename(stage_id)}.result.json",
        upstream_stage_ids=upstream_stage_ids,
    )


def _role_brief_path(agent_role: str) -> Path:
    if agent_role.startswith("provider:"):
        return REPO_ROOT / "role-specs" / "agent-provider-review.md"
    return REPO_ROOT / "role-specs" / f"{agent_role}.md"


def _role_brief_excerpt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"(role brief unavailable: {path})"
    return text[:6000]


def _failure_tolerance(stage: Mapping[str, Any]) -> str:
    tolerance = stage.get("failure_tolerance")
    if isinstance(tolerance, Mapping) and isinstance(tolerance.get("mode"), str):
        return str(tolerance["mode"])
    return "strict"


def _fan_out_snapshot(pipeline: Mapping[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping) or not isinstance(stage.get("fan_out"), Mapping):
            continue
        fan = stage["fan_out"]
        count = int(fan.get("count") or 0)
        variants = [str(item) for item in fan.get("variants") or [] if isinstance(item, str)]
        out[str(stage["id"])] = variants or [f"{fan.get('variant') or 'same'}-{idx + 1}" for idx in range(max(0, count))]
    return out


def _lens_snapshot(pipeline: Mapping[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        lenses = [
            str(agent.get("lens"))
            for agent in stage.get("agents") or []
            if isinstance(agent, Mapping) and isinstance(agent.get("lens"), str)
        ]
        if lenses:
            out[str(stage.get("id"))] = lenses
    return out


def _failure_tolerance_snapshot(pipeline: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(stage.get("id")): _failure_tolerance(stage)
        for stage in pipeline.get("stages") or []
        if isinstance(stage, Mapping) and isinstance(stage.get("id"), str)
    }


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "stage"


__all__ = ["StageInvocation", "plan_stage_invocations", "render_orchestrator_brief"]
