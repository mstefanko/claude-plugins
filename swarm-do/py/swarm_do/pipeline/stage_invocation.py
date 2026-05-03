"""Plan and render per-stage orchestrator invocations.

``StageInvocation`` bridges preset graph stages to prepared work units. Writer
fan-out stages may map one invocation per prepared work unit; merge/provider
stages intentionally carry ``work_unit_id = None`` because they operate on the
phase workspace rather than one unit worktree.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .engine import topological_layers
from .graph_source import canonical_graph_hash, resolve_preset_graph
from .paths import REPO_ROOT, resolve_data_dir
from .work_units import unit_file_scope


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
    subagent_type: str = ""
    worktree_path: Path | None = None
    bead_id: str | None = None
    allowed_files: tuple[str, ...] = ()
    acceptance_criteria: str = ""
    work_unit_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "agent_role": self.agent_role,
            "subagent_type": self.subagent_type or _subagent_type_for_role(self.agent_role),
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
            "worktree_path": str(self.worktree_path) if self.worktree_path else None,
            "bead_id": self.bead_id,
            "allowed_files": list(self.allowed_files),
            "acceptance_criteria": self.acceptance_criteria,
            "work_unit_id": self.work_unit_id,
        }


def plan_stage_invocations(
    preset: Mapping[str, Any],
    phase_context: Mapping[str, Any],
    *,
    data_dir: Path | None = None,
    prepared: Mapping[str, Any] | None = None,
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

    invocations = _attach_work_unit_metadata(invocations, prepared or {}, phase_id=phase_id)

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
    phase_sessions_mode: str = "auto",
    parallelism_cap: int = 8,
    status_protocol: str = "binary-structured",
) -> str:
    """Append the controller-owned stage dispatch contract to a phase brief."""

    if phase_sessions_mode == "fanout":
        return _render_fanout_orchestrator_brief(
            base_prompt=base_prompt,
            stage_invocations=stage_invocations,
            run_id=run_id,
            phase_id=phase_id,
            parallelism_cap=parallelism_cap,
            status_protocol=status_protocol,
        )

    lines = [
        base_prompt.rstrip(),
        "",
        "## Controller-Owned Stage Dispatch",
        "",
        "You are the foreground orchestrator. Dispatch stages with Agent; do not edit files directly.",
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
                f'Agent(subagent_type="general-purpose", prompt={json.dumps(prompt)})',
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
        subagent_type=_subagent_type_for_role(agent_role),
    )


def with_runtime_fields(
    invocations: list[StageInvocation],
    *,
    bead_ids: Mapping[str, str | None] | None = None,
    worktree_paths: Mapping[str, Path | str] | None = None,
) -> list[StageInvocation]:
    """Return invocations enriched with controller-created runtime handles."""

    bead_ids = bead_ids or {}
    worktree_paths = worktree_paths or {}
    enriched: list[StageInvocation] = []
    for invocation in invocations:
        path_value = worktree_paths.get(invocation.work_unit_id or "")
        enriched.append(
            dataclasses.replace(
                invocation,
                bead_id=bead_ids.get(invocation.stage_id, invocation.bead_id),
                worktree_path=Path(path_value) if path_value is not None else invocation.worktree_path,
            )
        )
    return enriched


def _render_fanout_orchestrator_brief(
    *,
    base_prompt: str,
    stage_invocations: list[StageInvocation],
    run_id: str,
    phase_id: str,
    parallelism_cap: int,
    status_protocol: str,
) -> str:
    lines = [
        base_prompt.rstrip(),
        "",
        "## Role",
        "",
        _role_brief_excerpt(REPO_ROOT / "role-specs" / "agent-dispatcher.md").rstrip(),
        "",
        "## Work Units To Dispatch",
        "",
        f"- run_id: {run_id}",
        f"- phase_id: {phase_id}",
        f"- status_protocol: {status_protocol}",
    ]
    for invocation in stage_invocations:
        result_path = invocation.expected_result_path
        role_text = _role_brief_excerpt(invocation.role_brief_path)
        allowed_files = list(invocation.allowed_files) or ["**/*"]
        worktree_path = str(invocation.worktree_path) if invocation.worktree_path else None
        bash_cwd = (
            "Every Bash command for this unit must self-establish cwd with "
            f"`cd {worktree_path} && ...`, use `git -C {worktree_path} ...`, "
            "or use absolute paths. Do not rely on Bash cwd persisting between tool calls."
            if worktree_path
            else "This stage has no per-unit worktree; use only the controller-prescribed paths."
        )
        stage_payload = {
            "stage_id": invocation.stage_id,
            "work_unit_id": invocation.work_unit_id,
            "agent_role": invocation.agent_role,
            "subagent_type": invocation.subagent_type or _subagent_type_for_role(invocation.agent_role),
            "worktree_path": worktree_path,
            "result_path": str(result_path),
            "allowed_files": allowed_files,
            "acceptance_criteria": invocation.acceptance_criteria,
            "bead_id": invocation.bead_id,
            "upstream_stage_ids": list(invocation.upstream_stage_ids),
            "failure_tolerance": invocation.failure_tolerance,
            "lens_chain": list(invocation.lens_chain),
            "prompt_prefix": f"cd {worktree_path} && " if worktree_path else "",
            "fresh_reviewer": {
                "required_on_retry": True,
                "retry_cycle_cap": 3,
                "prior_findings": "exclude from retry prompts",
            },
        }
        prompt = "\n".join(
            [
                f"Stage contract JSON: {json.dumps(stage_payload, sort_keys=True)}",
                "",
                f"Prompt prefix for Bash commands: {stage_payload['prompt_prefix'] or '(none)'}",
                "Before finishing, write a stage result JSON to the prescribed result_path exactly.",
                "Use `status: complete` for success, `status: complete_with_concerns` for adopted work with follow-up notes, `status: blocked` for non-retryable blockers, or `status: needs_input` for missing context.",
                bash_cwd,
                "On retry after a retryable failure, launch a fresh_reviewer sub-agent and do not include prior_findings from the failed attempt. Stop after 3 cycles and report blocked.",
                "",
                role_text,
                "",
                "Return a concise final summary after the result JSON exists on disk.",
            ]
        )
        lines.extend(
            [
                "",
                f"### {invocation.stage_id}",
                f"- work_unit_id: {invocation.work_unit_id or '-'}",
                f"- subagent_type: {stage_payload['subagent_type']}",
                f"- worktree_path: {worktree_path or '-'}",
                f"- expected_result_path: {result_path}",
                f"- bead_id: {invocation.bead_id or '-'}",
                f"- allowed_files: {', '.join(allowed_files)}",
                f"- acceptance_criteria: {invocation.acceptance_criteria or '-'}",
                f"- prompt_prefix: {stage_payload['prompt_prefix'] or '-'}",
                f"- bash_cwd_discipline: {bash_cwd}",
                "- fresh_reviewer: required on retry; prior_findings excluded; retry_cycle_cap: 3",
                "",
                "Dispatch form:",
                "```text",
                f'Agent(subagent_type="{stage_payload["subagent_type"]}", prompt={json.dumps(prompt)})',
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Marker Contract",
            "",
            "After each Agent tool_result, print exactly one controller marker on your assistant text channel.",
            'Success marker: STAGE_COMPLETE {"stage_id":"<stage_id>","result_path":"<absolute path>"}',
            'Failure marker: STAGE_FAILED {"stage_id":"<stage_id>","failure_kind":"<kind>","notes":"<short notes>"}',
            "For the binary structured protocol, route complete_with_concerns, blocked, failed, and needs_input through the result JSON status field; keep marker parsing binary.",
            "",
            "## Parallelism Rules",
            "",
            f"- Dispatch at most {max(1, parallelism_cap)} Agent calls in one assistant message.",
            "- Fan-out stages with no upstream dependency between them may run concurrently.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _attach_work_unit_metadata(
    invocations: list[StageInvocation],
    prepared: Mapping[str, Any],
    *,
    phase_id: str,
) -> list[StageInvocation]:
    units = _phase_work_units(prepared, phase_id)
    if not units:
        return invocations
    by_id = {str(unit.get("id")): unit for unit in units if isinstance(unit.get("id"), str)}
    enriched: list[StageInvocation] = []
    for invocation in invocations:
        unit_id = _work_unit_id_for_invocation(invocation, units)
        unit = by_id.get(unit_id or "")
        if unit is None:
            enriched.append(invocation)
            continue
        criteria = unit.get("acceptance_criteria")
        acceptance = "\n".join(str(item) for item in criteria if isinstance(item, str)) if isinstance(criteria, list) else ""
        enriched.append(
            dataclasses.replace(
                invocation,
                work_unit_id=unit_id,
                allowed_files=tuple(unit_file_scope(unit)),
                acceptance_criteria=acceptance,
            )
        )
    return enriched


def _work_unit_id_for_invocation(invocation: StageInvocation, units: list[Mapping[str, Any]]) -> str | None:
    if invocation.is_provider_stage or invocation.merge_target:
        return None
    unit_ids = [str(unit.get("id")) for unit in units if isinstance(unit.get("id"), str)]
    if not unit_ids:
        return None
    if len(unit_ids) == 1:
        return unit_ids[0]
    if invocation.fan_out_index is not None and invocation.agent_role in _UNIT_WRITER_ROLES:
        if 0 <= invocation.fan_out_index < len(unit_ids):
            return unit_ids[invocation.fan_out_index]
        raise ValueError(
            f"stage {invocation.stage_id} fan_out_index {invocation.fan_out_index} has no matching work unit"
        )
    if invocation.agent_role in _UNIT_WRITER_ROLES:
        raise ValueError(
            f"stage {invocation.stage_id} is ambiguous across {len(unit_ids)} work units; use fan_out or explicit mapping"
        )
    return None


def _phase_work_units(prepared: Mapping[str, Any], phase_id: str) -> list[Mapping[str, Any]]:
    descriptor = (prepared.get("work_unit_artifacts") or {}).get(phase_id)
    artifact = descriptor.get("artifact") if isinstance(descriptor, Mapping) and isinstance(descriptor.get("artifact"), Mapping) else None
    if artifact is None and isinstance(descriptor, Mapping) and isinstance(descriptor.get("path"), str):
        try:
            artifact_path = Path(str(prepared.get("repo_root") or REPO_ROOT)) / str(descriptor["path"])
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception:
            artifact = None
    if not isinstance(artifact, Mapping):
        return []
    return [unit for unit in artifact.get("work_units") or [] if isinstance(unit, Mapping)]


_UNIT_WRITER_ROLES = {"agent-writer"}


def _subagent_type_for_role(agent_role: str) -> str:
    if agent_role.startswith("provider:"):
        return "general-purpose"
    return f"swarmdaddy:{agent_role}"


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


__all__ = ["StageInvocation", "plan_stage_invocations", "render_orchestrator_brief", "with_runtime_fields"]
