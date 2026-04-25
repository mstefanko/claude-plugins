"""Shared helpers for pipeline composer mutations."""

from __future__ import annotations

from typing import Any, Mapping

from .validation import MCO_PROVIDER_ORDER, MCO_PROVIDERS, REVIEW_PROVIDER_SELECTIONS, TOLERANCE_MODES


def find_stage_by_id(pipeline: Mapping[str, Any], stage_id: str) -> Mapping[str, Any] | None:
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        return None
    for stage in stages:
        if isinstance(stage, Mapping) and stage.get("id") == stage_id:
            return stage
    return None


def mutable_stage_by_id(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        raise ValueError("pipeline stages must be a list")
    for stage in stages:
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    raise ValueError(f"stage not found: {stage_id}")


def mutable_stage_agent(pipeline: Mapping[str, Any], stage_id: str, agent_index: int) -> dict[str, Any]:
    stage = mutable_stage_by_id(pipeline, stage_id)
    agents = stage.get("agents")
    if not isinstance(agents, list):
        raise ValueError(f"stage {stage_id} is not an agents stage")
    if agent_index < 0 or agent_index >= len(agents) or not isinstance(agents[agent_index], dict):
        raise ValueError(f"agent index out of range for stage {stage_id}: {agent_index}")
    return agents[agent_index]


def mutable_stage_fan_out(pipeline: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    stage = mutable_stage_by_id(pipeline, stage_id)
    fan = stage.get("fan_out")
    if not isinstance(fan, dict):
        raise ValueError(f"stage {stage_id} is not a fan_out stage")
    return fan


def mutable_mco_provider_stage(pipeline: Mapping[str, Any], stage_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stage = mutable_stage_by_id(pipeline, stage_id)
    provider = stage.get("provider")
    if not isinstance(provider, dict) or provider.get("type") != "mco":
        raise ValueError(f"stage {stage_id} is not an MCO provider stage")
    return stage, provider


def mutable_provider_review_stage(pipeline: Mapping[str, Any], stage_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stage = mutable_stage_by_id(pipeline, stage_id)
    provider = stage.get("provider")
    if not isinstance(provider, dict) or provider.get("type") != "swarm-review":
        raise ValueError(f"stage {stage_id} is not a swarm-review provider stage")
    return stage, provider


def normalize_mco_providers(providers: list[str]) -> list[str]:
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


def normalize_review_providers(providers: list[str]) -> list[str]:
    if not isinstance(providers, list):
        raise ValueError("providers must be a list")
    selected: list[str] = []
    for provider in providers:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("providers must contain non-empty provider names")
        name = provider.strip()
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"invalid review provider: {name}")
        if name not in selected:
            selected.append(name)
    if not (1 <= len(selected) <= 16):
        raise ValueError("review providers must contain 1..16 unique provider names")
    return selected


def validate_mco_timeout(timeout_seconds: int) -> int:
    if not isinstance(timeout_seconds, int) or not (1 <= timeout_seconds <= 86400):
        raise ValueError("timeout_seconds must be an integer from 1 to 86400")
    return timeout_seconds


def validate_provider_review_selection(selection: str) -> str:
    if selection not in REVIEW_PROVIDER_SELECTIONS:
        raise ValueError(f"selection must be one of {sorted(REVIEW_PROVIDER_SELECTIONS)}")
    return selection


def validate_provider_review_max_parallel(max_parallel: int) -> int:
    if not isinstance(max_parallel, int) or not (1 <= max_parallel <= 32):
        raise ValueError("max_parallel must be an integer from 1 to 32")
    return max_parallel


def provider_failure_tolerance(mode: str, min_success: int | None, *, branch_count: int) -> dict[str, int | str]:
    if mode not in TOLERANCE_MODES:
        raise ValueError(f"failure_tolerance mode must be one of {sorted(TOLERANCE_MODES)}")
    if mode != "quorum":
        return {"mode": mode}
    if not isinstance(min_success, int) or not (1 <= min_success <= branch_count):
        raise ValueError("min_success must be 1..provider count for quorum")
    return {"mode": mode, "min_success": min_success}
