"""Backend route resolution shared by validation and runtime helpers."""

from __future__ import annotations

import dataclasses
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from .paths import current_preset_path, resolve_data_dir, stock_presets_dir, user_presets_dir


EFFORTS = {"none", "low", "medium", "high", "xhigh"}
BACKENDS = {"claude", "codex"}


@dataclasses.dataclass(frozen=True)
class Route:
    backend: str
    model: str
    effort: str
    setting_source: str

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


HARDCODED_DEFAULT = Route("claude", "claude-opus-4-7", "high", "hardcoded-default")


ROLE_DEFAULTS: dict[str, dict[str, Route] | Route] = {
    "orchestrator": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-brainstorm": Route("claude", "claude-sonnet-4-6", "high", "role-default"),
    "agent-brainstorm-merge": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-research": Route("claude", "claude-sonnet-4-6", "high", "role-default"),
    "agent-analysis": Route("claude", "claude-opus-4-7", "xhigh", "role-default"),
    "agent-implementation-advisor": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-debug": Route("claude", "claude-opus-4-7", "xhigh", "role-default"),
    "agent-clarify": Route("claude", "claude-sonnet-4-6", "medium", "role-default"),
    "agent-writer": {
        "simple": Route("claude", "claude-haiku-4-5", "medium", "role-default"),
        "moderate": Route("claude", "claude-sonnet-4-6", "high", "role-default"),
        "hard": Route("claude", "claude-opus-4-7", "high", "role-default"),
    },
    "agent-spec-review": Route("claude", "claude-sonnet-4-6", "medium", "role-default"),
    "agent-clean-review": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-review": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-docs": Route("claude", "claude-sonnet-4-6", "medium", "role-default"),
    "agent-codex-review": Route("codex", "gpt-5.4", "high", "role-default"),
    "agent-analysis-judge": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-writer-judge": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-code-synthesizer": Route("claude", "claude-opus-4-7", "xhigh", "role-default"),
    "agent-research-merge": Route("claude", "claude-opus-4-7", "high", "role-default"),
    "agent-code-review": Route("claude", "claude-opus-4-7", "xhigh", "role-default"),
}


def route_from_mapping(data: Mapping[str, Any], source: str) -> Route:
    backend = str(data.get("backend", "")).strip()
    model = str(data.get("model", "")).strip()
    effort = str(data.get("effort", "")).strip()
    if backend not in BACKENDS:
        raise ValueError(f"{source}: backend must be one of {sorted(BACKENDS)}")
    if not model:
        raise ValueError(f"{source}: model is required")
    if effort not in EFFORTS:
        raise ValueError(f"{source}: effort must be one of {sorted(EFFORTS)}")
    return Route(backend, model, effort, source)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def active_preset_name() -> str | None:
    path = current_preset_path()
    if not path.is_file():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


def preset_path(name: str) -> Path | None:
    for base in (user_presets_dir(), stock_presets_dir()):
        candidate = base / f"{name}.toml"
        if candidate.is_file():
            return candidate
    return None


def load_preset_by_name(name: str | None) -> tuple[dict[str, Any], Path | None]:
    if not name:
        return {}, None
    path = preset_path(name)
    if path is None:
        raise FileNotFoundError(f"preset not found: {name}")
    return load_toml(path), path


def _routing_key_candidates(role: str, complexity: str | None) -> list[str]:
    keys = []
    if complexity:
        keys.append(f"roles.{role}.{complexity}")
    keys.append(f"roles.{role}")
    return keys


def _route_from_routing_table(routing: Mapping[str, Any], role: str, complexity: str | None, source: str) -> Route | None:
    for key in _routing_key_candidates(role, complexity):
        value = routing.get(key)
        if isinstance(value, Mapping):
            return route_from_mapping(value, source)
    return None


def _route_from_roles_table(roles: Mapping[str, Any], role: str, complexity: str | None, source: str) -> Route | None:
    value = roles.get(role)
    if not isinstance(value, Mapping):
        return None
    if complexity and isinstance(value.get(complexity), Mapping):
        return route_from_mapping(value[complexity], source)
    if {"backend", "model", "effort"} <= set(value.keys()):
        return route_from_mapping(value, source)
    return None


def _role_default(role: str, complexity: str | None) -> Route:
    value = ROLE_DEFAULTS.get(role)
    if isinstance(value, dict):
        return value.get(complexity or "", value.get("moderate", HARDCODED_DEFAULT))
    if isinstance(value, Route):
        return value
    return HARDCODED_DEFAULT


class BackendResolver:
    def __init__(
        self,
        preset_name: str | None = None,
        base_backends_path: Path | None = None,
        preset_data: Mapping[str, Any] | None = None,
    ):
        self.preset_name = active_preset_name() if preset_name == "current" else preset_name
        if preset_data is None:
            self.preset, self.preset_file = load_preset_by_name(self.preset_name)
        else:
            self.preset = dict(preset_data)
            self.preset_file = None
        self.base_backends_path = base_backends_path or (resolve_data_dir() / "backends.toml")
        self.base = load_toml(self.base_backends_path)

    def resolve(
        self,
        role: str,
        complexity: str | None = None,
        override: Mapping[str, Any] | str | None = None,
    ) -> Route:
        if isinstance(override, Mapping):
            return route_from_mapping(override, "stage-override")
        if isinstance(override, str):
            routing = self.preset.get("routing", {})
            value = routing.get(override) if isinstance(routing, Mapping) else None
            if isinstance(value, Mapping):
                return route_from_mapping(value, f"preset-route:{override}")
            raise ValueError(f"named route not found in preset routing: {override}")

        routing = self.preset.get("routing", {})
        if isinstance(routing, Mapping):
            route = _route_from_routing_table(routing, role, complexity, "active-preset")
            if route:
                return route

        roles = self.base.get("roles", {})
        if isinstance(roles, Mapping):
            route = _route_from_roles_table(roles, role, complexity, "backends.toml")
            if route:
                return route

        default = _role_default(role, complexity)
        return dataclasses.replace(default, setting_source=default.setting_source)

    def is_claude_backed(self, role: str, complexity: str | None = None, override: Mapping[str, Any] | str | None = None) -> bool:
        return self.resolve(role, complexity, override).backend == "claude"
