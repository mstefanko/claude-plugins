"""Mutation helpers shared by the pipeline CLI and optional TUI."""

from __future__ import annotations

import dataclasses
import copy
import json
import os
import re
import signal
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Mapping

from swarm_do.pipeline.catalog import compile_prompt_variant_fan_out, get_module, pipeline_activation_error
from swarm_do.pipeline.engine import topological_layers
from swarm_do.pipeline.paths import current_preset_path, resolve_data_dir, user_pipelines_dir, user_presets_dir
from swarm_do.pipeline.registry import find_pipeline, find_preset, load_pipeline, load_preset, sha256_file
from swarm_do.pipeline.render_yaml import render_pipeline_yaml
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, ROLE_DEFAULTS
from swarm_do.pipeline.validation import (
    invariant_errors,
    role_existence_errors,
    route_resolution_errors,
    schema_lint_pipeline,
    schema_lint_preset,
    validate_preset_mapping,
    variant_existence_errors,
)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclasses.dataclass(frozen=True)
class InFlightRun:
    issue_id: str
    role: str
    backend: str
    model: str
    effort: str
    pid: int | None
    started_at: str | None
    status: str
    path: Path

    @property
    def display_pid(self) -> str:
        return str(self.pid) if self.pid is not None else "n/a"


def in_flight_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "in-flight"


def load_in_flight(data_dir: Path | None = None) -> list[InFlightRun]:
    base = in_flight_dir(data_dir)
    if not base.is_dir():
        return []
    runs: list[InFlightRun] = []
    for path in sorted(base.glob("*.lock")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = value.get("pid")
        runs.append(
            InFlightRun(
                issue_id=str(value.get("issue_id") or path.stem.removeprefix("bd-")),
                role=str(value.get("role") or "unknown"),
                backend=str(value.get("backend") or "unknown"),
                model=str(value.get("model") or "unknown"),
                effort=str(value.get("effort") or "unknown"),
                pid=pid if isinstance(pid, int) else None,
                started_at=value.get("started_at") if isinstance(value.get("started_at"), str) else None,
                status=str(value.get("status") or "running"),
                path=path,
            )
        )
    return runs


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _route_inline(route: Mapping[str, Any]) -> str:
    return (
        "{ backend = "
        + _quote(str(route["backend"]))
        + ", model = "
        + _quote(str(route["model"]))
        + ", effort = "
        + _quote(str(route["effort"]))
        + " }"
    )


def render_toml(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key in ("name", "description", "pipeline", "origin", "forked_from", "forked_from_hash", "generated_by"):
        value = data.get(key)
        if isinstance(value, str):
            lines.append(f"{key} = {_quote(value)}")
    routing = data.get("routing")
    if isinstance(routing, Mapping) and routing:
        lines.extend(["", "[routing]"])
        for key in sorted(routing):
            value = routing[key]
            if isinstance(value, Mapping):
                lines.append(f"{_quote(str(key))} = {_route_inline(value)}")
    budget = data.get("budget")
    if isinstance(budget, Mapping) and budget:
        lines.extend(["", "[budget]"])
        for key in (
            "max_agents_per_run",
            "max_estimated_cost_usd",
            "max_wall_clock_seconds",
            "max_writer_tool_calls",
            "max_writer_output_bytes",
            "max_handoffs",
        ):
            if key in budget:
                lines.append(f"{key} = {budget[key]}")
    decompose = data.get("decompose")
    if isinstance(decompose, Mapping) and decompose:
        lines.extend(["", "[decompose]"])
        for key in ("mode",):
            if isinstance(decompose.get(key), str):
                lines.append(f"{key} = {_quote(str(decompose[key]))}")
    mem_prime = data.get("mem_prime")
    if isinstance(mem_prime, Mapping) and mem_prime:
        lines.extend(["", "[mem_prime]"])
        for key in ("mode", "adapter"):
            if isinstance(mem_prime.get(key), str):
                lines.append(f"{key} = {_quote(str(mem_prime[key]))}")
        for key in ("max_tokens", "recency_days", "min_relevance"):
            if key in mem_prime:
                lines.append(f"{key} = {mem_prime[key]}")
    roles = data.get("roles")
    if isinstance(roles, Mapping):
        for role in sorted(roles):
            value = roles[role]
            if isinstance(value, Mapping):
                lines.extend(["", f"[roles.{role}]"])
                if {"backend", "model", "effort"} <= set(value):
                    lines.extend(
                        [
                            f"backend = {_quote(str(value['backend']))}",
                            f"model = {_quote(str(value['model']))}",
                            f"effort = {_quote(str(value['effort']))}",
                        ]
                    )
                else:
                    for complexity in ("simple", "moderate", "hard"):
                        route = value.get(complexity)
                        if isinstance(route, Mapping):
                            lines.append(f"{complexity} = {_route_inline(route)}")
    return "\n".join(lines).rstrip() + "\n"


def load_toml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def backends_path() -> Path:
    return resolve_data_dir() / "backends.toml"


def validate_preset_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError("preset name must be 1-64 chars of letters, numbers, dot, underscore, or dash")


def validate_pipeline_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError("pipeline name must be 1-64 chars of letters, numbers, dot, underscore, or dash")


def validate_issue_id(issue_id: str) -> None:
    if not ISSUE_ID_RE.fullmatch(issue_id):
        raise ValueError("issue id must not contain path separators or whitespace")


def set_base_route(role: str, complexity: str | None, backend: str, model: str, effort: str) -> None:
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {sorted(EFFORTS)}")
    if role in {"orchestrator", "agent-code-synthesizer"} and backend != "claude":
        raise ValueError(f"invariant: {role} must use a Claude backend")
    data = load_toml_file(backends_path())
    roles = data.setdefault("roles", {})
    if not isinstance(roles, dict):
        raise ValueError("backends.toml roles table must be a table")
    route = {"backend": backend, "model": model, "effort": effort}
    if complexity:
        role_table = roles.setdefault(role, {})
        if not isinstance(role_table, dict):
            raise ValueError(f"roles.{role} must be a table")
        role_table[complexity] = route
    else:
        roles[role] = route
    atomic_write_text(backends_path(), render_toml(data))


def _route_key(role: str, complexity: str | None) -> str:
    return f"roles.{role}.{complexity}" if complexity else f"roles.{role}"


def set_user_preset_route(preset_name: str, role: str, complexity: str | None, backend: str, model: str, effort: str) -> None:
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {sorted(EFFORTS)}")
    item = find_preset(preset_name)
    if item is None:
        raise ValueError(f"preset not found: {preset_name}")
    if item.origin != "user":
        raise ValueError("stock presets are read-only; fork before editing routes")
    data = load_preset(item.path)
    routing = data.setdefault("routing", {})
    if not isinstance(routing, dict):
        raise ValueError("preset routing must be a table")
    routing[_route_key(role, complexity)] = {"backend": backend, "model": model, "effort": effort}
    result, _ = validate_preset_mapping(data, preset_name)
    if not result.ok:
        raise ValueError("; ".join(result.errors))
    atomic_write_text(item.path, render_toml(data))


def rename_user_preset(old: str, new: str) -> Path:
    validate_preset_name(old)
    validate_preset_name(new)
    item = find_preset(old)
    if item is None:
        raise ValueError(f"preset not found: {old}")
    if item.origin != "user":
        raise ValueError("stock presets are read-only")
    target = user_presets_dir() / f"{new}.toml"
    if target.exists():
        raise ValueError(f"preset already exists: {new}")
    data = load_preset(item.path)
    data["name"] = new
    atomic_write_text(target, render_toml(data))
    item.path.unlink()
    active = current_preset_path()
    if active.is_file() and active.read_text(encoding="utf-8").strip() == old:
        atomic_write_text(active, new + "\n")
    return target


def delete_user_preset(name: str) -> None:
    validate_preset_name(name)
    item = find_preset(name)
    if item is None:
        raise ValueError(f"preset not found: {name}")
    if item.origin != "user":
        raise ValueError("stock presets are read-only")
    item.path.unlink()
    active = current_preset_path()
    if active.is_file() and active.read_text(encoding="utf-8").strip() == name:
        atomic_write_text(active, "")


def set_user_preset_pipeline(preset_name: str, pipeline_name: str) -> None:
    item = find_preset(preset_name)
    if item is None:
        raise ValueError(f"preset not found: {preset_name}")
    if item.origin != "user":
        raise ValueError("stock presets are read-only; fork before changing pipeline")
    pipeline_item = find_pipeline(pipeline_name)
    if pipeline_item is not None:
        activation_error = pipeline_activation_error(pipeline_name, load_pipeline(pipeline_item.path))
        if activation_error:
            raise ValueError(activation_error)
    data = load_preset(item.path)
    data["pipeline"] = pipeline_name
    result, _ = validate_preset_mapping(data, preset_name)
    if not result.ok:
        raise ValueError("; ".join(result.errors))
    atomic_write_text(item.path, render_toml(data))


def fork_preset(source_name: str, new_name: str) -> Path:
    validate_preset_name(new_name)
    if find_preset(new_name) is not None:
        raise ValueError(f"preset already exists: {new_name}")
    source = find_preset(source_name)
    if source is None:
        raise ValueError(f"source preset not found: {source_name}")
    data = load_preset(source.path)
    data["name"] = new_name
    data["origin"] = "user"
    data["forked_from"] = source.name
    data["forked_from_hash"] = "sha256:" + sha256_file(source.path)
    data.setdefault("generated_by", "swarm-do pipeline composer")
    errors = schema_lint_preset(data)
    if errors:
        raise ValueError("; ".join(errors))
    target = user_presets_dir() / f"{new_name}.toml"
    atomic_write_text(target, render_toml(data))
    return target


def fork_pipeline(source_name: str, new_name: str) -> Path:
    validate_pipeline_name(new_name)
    if find_pipeline(new_name) is not None:
        raise ValueError(f"pipeline already exists: {new_name}")
    source = find_pipeline(source_name)
    if source is None:
        raise ValueError(f"source pipeline not found: {source_name}")
    data = load_pipeline(source.path)
    data["name"] = new_name
    data["origin"] = "user"
    data["forked_from"] = source.name
    data["forked_from_hash"] = "sha256:" + sha256_file(source.path)
    data.setdefault("generated_by", "swarm-do pipeline composer")
    _raise_pipeline_errors(data)
    target = user_pipelines_dir() / f"{new_name}.yaml"
    atomic_write_text(target, render_pipeline_yaml(data))
    return target


def fork_preset_and_pipeline(
    source_preset: str,
    source_pipeline: str,
    new_name: str,
    *,
    _simulate_failure_after_pipeline: bool = False,
) -> tuple[Path, Path]:
    validate_preset_name(new_name)
    validate_pipeline_name(new_name)
    if find_preset(new_name) is not None:
        raise ValueError(f"preset already exists: {new_name}")
    if find_pipeline(new_name) is not None:
        raise ValueError(f"pipeline already exists: {new_name}")
    preset_item = find_preset(source_preset)
    if preset_item is None:
        raise ValueError(f"source preset not found: {source_preset}")
    pipeline_item = find_pipeline(source_pipeline)
    if pipeline_item is None:
        raise ValueError(f"source pipeline not found: {source_pipeline}")

    preset = load_preset(preset_item.path)
    pipeline = load_pipeline(pipeline_item.path)
    pipeline["name"] = new_name
    pipeline["origin"] = "user"
    pipeline["forked_from"] = pipeline_item.name
    pipeline["forked_from_hash"] = "sha256:" + sha256_file(pipeline_item.path)
    pipeline.setdefault("generated_by", "swarm-do pipeline composer")

    preset["name"] = new_name
    preset["pipeline"] = new_name
    preset["origin"] = "user"
    preset["forked_from"] = preset_item.name
    preset["forked_from_hash"] = "sha256:" + sha256_file(preset_item.path)
    preset.setdefault("generated_by", "swarm-do pipeline composer")

    errors = schema_lint_preset(preset)
    errors.extend(_pipeline_errors(pipeline, preset_name=new_name, preset=preset))
    if errors:
        raise ValueError("; ".join(errors))

    pipeline_target = user_pipelines_dir() / f"{new_name}.yaml"
    preset_target = user_presets_dir() / f"{new_name}.toml"
    atomic_write_text(pipeline_target, render_pipeline_yaml(pipeline))
    if _simulate_failure_after_pipeline:
        raise RuntimeError("simulated failure after pipeline replace")
    atomic_write_text(preset_target, render_toml(preset))
    return preset_target, pipeline_target


def save_user_pipeline(name: str, pipeline_mapping: Mapping[str, Any]) -> Path:
    validate_pipeline_name(name)
    existing = find_pipeline(name)
    if existing is not None and existing.origin != "user":
        raise ValueError("stock pipelines are read-only; fork before editing")
    data = copy.deepcopy(dict(pipeline_mapping))
    data["name"] = name
    data.setdefault("origin", "user")
    data.setdefault("generated_by", "swarm-do pipeline composer")
    _raise_pipeline_errors(data)
    target = user_pipelines_dir() / f"{name}.yaml"
    atomic_write_text(target, render_pipeline_yaml(data))
    return target


def set_stage_agent_route(
    pipeline_name: str,
    stage_id: str,
    agent_index: int,
    *,
    backend: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    route: str | None = None,
) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    agent = _stage_agent(pipeline, stage_id, agent_index)
    for key in ("backend", "model", "effort", "route"):
        agent.pop(key, None)
    if route is not None:
        agent["route"] = route
    else:
        if backend not in BACKENDS:
            raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
        if not model:
            raise ValueError("model must be a non-empty string")
        if effort not in EFFORTS:
            raise ValueError(f"effort must be one of {sorted(EFFORTS)}")
        agent.update({"backend": backend, "model": model, "effort": effort})
    return save_user_pipeline(item.name, pipeline)


def reset_stage_agent_route(pipeline_name: str, stage_id: str, agent_index: int) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    agent = _stage_agent(pipeline, stage_id, agent_index)
    for key in ("backend", "model", "effort", "route"):
        agent.pop(key, None)
    return save_user_pipeline(item.name, pipeline)


def set_stage_agent_lens(pipeline_name: str, stage_id: str, agent_index: int, lens_id: str) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    agent = _stage_agent(pipeline, stage_id, agent_index)
    lens_id = lens_id.strip()
    if not lens_id:
        raise ValueError("lens must be a non-empty string")
    agent["lens"] = lens_id
    return save_user_pipeline(item.name, pipeline)


def reset_stage_agent_lens(pipeline_name: str, stage_id: str, agent_index: int) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    agent = _stage_agent(pipeline, stage_id, agent_index)
    agent.pop("lens", None)
    return save_user_pipeline(item.name, pipeline)


def set_fan_out_routes(pipeline_name: str, stage_id: str, routes: list[Mapping[str, Any] | str]) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    fan = _stage_fan_out(pipeline, stage_id)
    if fan.get("variant") == "prompt_variants" or "variants" in fan:
        raise ValueError("cannot combine prompt-variant lenses and per-branch model routes in one fan-out")
    if not routes:
        raise ValueError("routes must not be empty")
    for idx, route in enumerate(routes):
        if isinstance(route, Mapping):
            _validate_route_values(route, f"routes[{idx}]")
        elif not isinstance(route, str) or not route:
            raise ValueError(f"routes[{idx}] must be a named route or route object")
    fan["variant"] = "models"
    fan["count"] = len(routes)
    fan["routes"] = [copy.deepcopy(route) if isinstance(route, Mapping) else route for route in routes]
    return save_user_pipeline(item.name, pipeline)


def reset_fan_out_routes(pipeline_name: str, stage_id: str) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    fan = _stage_fan_out(pipeline, stage_id)
    fan["variant"] = "same"
    fan.pop("routes", None)
    fan.pop("variants", None)
    return save_user_pipeline(item.name, pipeline)


def set_prompt_variant_lenses(pipeline_name: str, stage_id: str, lens_ids: list[str]) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    fan = _stage_fan_out(pipeline, stage_id)
    if fan.get("variant") == "models" or "routes" in fan:
        raise ValueError("cannot combine prompt-variant lenses and per-branch model routes in one fan-out")
    role = fan.get("role")
    if not isinstance(role, str) or not role:
        raise ValueError(f"stage {stage_id} fan_out.role must be a non-empty string")
    fan.clear()
    fan.update(compile_prompt_variant_fan_out(role, lens_ids))
    return save_user_pipeline(item.name, pipeline)


def add_pipeline_stage_from_module(
    pipeline_name: str,
    module_id: str,
    *,
    stage_id: str | None = None,
    depends_on: list[str] | None = None,
) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    module = get_module(module_id)
    if module is None:
        raise ValueError(f"unknown module: {module_id}")
    stage = module.instantiate_stage(stage_id=stage_id)
    existing_ids = {stage.get("id") for stage in pipeline.get("stages") or []}
    if stage.get("id") in existing_ids:
        raise ValueError(f"stage already exists: {stage.get('id')}")
    if depends_on is not None:
        stage["depends_on"] = depends_on
    stages = pipeline.setdefault("stages", [])
    if not isinstance(stages, list):
        raise ValueError("pipeline stages must be a list")
    stages.append(stage)
    return save_user_pipeline(item.name, pipeline)


def remove_pipeline_stage(pipeline_name: str, stage_id: str) -> Path:
    item, pipeline = _load_user_pipeline(pipeline_name)
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        raise ValueError("pipeline stages must be a list")
    dependents = [
        str(stage.get("id"))
        for stage in stages
        if isinstance(stage, Mapping) and stage_id in (stage.get("depends_on") or [])
    ]
    if dependents:
        raise ValueError(f"stage {stage_id} is still required by: {', '.join(sorted(dependents))}")
    next_stages = [stage for stage in stages if not (isinstance(stage, Mapping) and stage.get("id") == stage_id)]
    if len(next_stages) == len(stages):
        raise ValueError(f"stage not found: {stage_id}")
    pipeline["stages"] = next_stages
    return save_user_pipeline(item.name, pipeline)


def _pipeline_errors(
    pipeline: Mapping[str, Any],
    *,
    preset_name: str | None = None,
    preset: Mapping[str, Any] | None = None,
) -> list[str]:
    errors = schema_lint_pipeline(pipeline)
    errors.extend(role_existence_errors(pipeline))
    errors.extend(variant_existence_errors(pipeline))
    if preset is not None or preset_name is not None:
        errors.extend(route_resolution_errors(pipeline, preset_name, preset))
    errors.extend(invariant_errors(pipeline, preset_name, preset))
    try:
        topological_layers(pipeline)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def _raise_pipeline_errors(pipeline: Mapping[str, Any]) -> None:
    errors = _pipeline_errors(pipeline)
    if errors:
        raise ValueError("; ".join(errors))


def _load_user_pipeline(name: str) -> tuple[Any, dict[str, Any]]:
    item = find_pipeline(name)
    if item is None:
        raise ValueError(f"pipeline not found: {name}")
    if item.origin != "user":
        raise ValueError("stock pipelines are read-only; fork before editing")
    return item, load_pipeline(item.path)


def _stage_by_id(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in pipeline.get("stages") or []:
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    raise ValueError(f"stage not found: {stage_id}")


def _stage_agent(pipeline: Mapping[str, Any], stage_id: str, agent_index: int) -> dict[str, Any]:
    stage = _stage_by_id(pipeline, stage_id)
    agents = stage.get("agents")
    if not isinstance(agents, list):
        raise ValueError(f"stage {stage_id} is not an agents stage")
    if agent_index < 0 or agent_index >= len(agents) or not isinstance(agents[agent_index], dict):
        raise ValueError(f"agent index out of range for stage {stage_id}: {agent_index}")
    return agents[agent_index]


def _stage_fan_out(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stage = _stage_by_id(pipeline, stage_id)
    fan = stage.get("fan_out")
    if not isinstance(fan, dict):
        raise ValueError(f"stage {stage_id} is not a fan_out stage")
    return fan


def _validate_route_values(route: Mapping[str, Any], path: str) -> None:
    if route.get("backend") not in BACKENDS:
        raise ValueError(f"{path}.backend must be one of {sorted(BACKENDS)}")
    if not isinstance(route.get("model"), str) or not route.get("model"):
        raise ValueError(f"{path}.model must be a non-empty string")
    if route.get("effort") not in EFFORTS:
        raise ValueError(f"{path}.effort must be one of {sorted(EFFORTS)}")


def cancel_run(run: InFlightRun) -> None:
    if run.pid is None:
        raise ValueError("lockfile has no pid")
    command = _pid_command(run.pid)
    if command is None:
        raise ValueError(f"pid {run.pid} is not running")
    if "swarm-run" not in command:
        raise ValueError(f"refusing to cancel non-swarm-run pid {run.pid}")
    os.kill(run.pid, signal.SIGTERM)


def request_handoff(issue_id: str, backend: str) -> Path:
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    validate_issue_id(issue_id)
    lock = in_flight_dir() / f"bd-{issue_id}.lock"
    data: dict[str, Any] = {}
    if lock.is_file():
        data = load_toml_file(lock) if lock.suffix == ".toml" else {}
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update({"issue_id": issue_id, "status": "handoff-requested", "requested_backend": backend})
    atomic_write_text(lock, json.dumps(data, sort_keys=True) + "\n")
    return lock


def find_in_flight(issue_id: str) -> InFlightRun | None:
    for run in load_in_flight():
        if run.issue_id == issue_id:
            return run
    return None


def editable_roles() -> list[str]:
    return sorted(ROLE_DEFAULTS)


def _pid_command(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    command = result.stdout.strip()
    return command if result.returncode == 0 and command else None
