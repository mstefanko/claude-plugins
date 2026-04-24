"""Mutation helpers shared by the TUI and small CLI affordances."""

from __future__ import annotations

import os
import signal
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Mapping

from swarm_do.pipeline.paths import current_preset_path, resolve_data_dir, user_presets_dir
from swarm_do.pipeline.registry import find_preset, load_preset
from swarm_do.pipeline.resolver import BACKENDS, EFFORTS, ROLE_DEFAULTS
from swarm_do.pipeline.validation import validate_preset_and_pipeline
from swarm_do.tui.state import InFlightRun, in_flight_dir, load_in_flight


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
    for key in ("name", "description", "pipeline", "origin", "forked_from_hash"):
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
        for key in ("max_agents_per_run", "max_estimated_cost_usd", "max_wall_clock_seconds"):
            if key in budget:
                lines.append(f"{key} = {budget[key]}")
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


def rename_user_preset(old: str, new: str) -> Path:
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
    data = load_preset(item.path)
    data["pipeline"] = pipeline_name
    atomic_write_text(item.path, render_toml(data))
    result, *_ = validate_preset_and_pipeline(preset_name)
    if not result.ok:
        raise ValueError("; ".join(result.errors))


def cancel_run(run: InFlightRun) -> None:
    if run.pid is None:
        raise ValueError("lockfile has no pid")
    os.kill(run.pid, signal.SIGTERM)


def request_handoff(issue_id: str, backend: str) -> Path:
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    lock = in_flight_dir() / f"bd-{issue_id}.lock"
    data: dict[str, Any] = {}
    if lock.is_file():
        data = load_toml_file(lock) if lock.suffix == ".toml" else {}
        try:
            import json

            data = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update({"issue_id": issue_id, "status": "handoff-requested", "requested_backend": backend})
    import json

    atomic_write_text(lock, json.dumps(data, sort_keys=True) + "\n")
    return lock


def find_in_flight(issue_id: str) -> InFlightRun | None:
    for run in load_in_flight():
        if run.issue_id == issue_id:
            return run
    return None


def editable_roles() -> list[str]:
    return sorted(ROLE_DEFAULTS)
