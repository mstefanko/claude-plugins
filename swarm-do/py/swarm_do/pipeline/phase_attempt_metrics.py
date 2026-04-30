"""Shared phase-attempt stdout and cost metric parsing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def stdout_metrics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return unknown_metrics()
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        result = unknown_metrics()
        result["stdout_parse_error"] = "stdout is empty"
        return result
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        result = unknown_metrics()
        result["stdout_parse_error"] = str(exc)
        return result
    if not isinstance(payload, Mapping):
        result = unknown_metrics()
        result["stdout_parse_error"] = "stdout JSON is not an object"
        return result
    metrics = cost_metrics(payload)
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    for field in TOKEN_FIELDS:
        metrics[field] = int_or_none(usage.get(field))
    metrics["duration_ms"] = int_or_none(payload.get("duration_ms"))
    metrics["duration_api_ms"] = int_or_none(payload.get("duration_api_ms"))
    metrics["num_turns"] = int_or_none(payload.get("num_turns"))
    denials = payload.get("permission_denials")
    metrics["permission_denial_count"] = len(denials) if isinstance(denials, list) else (int_or_none(denials) or 0)
    metrics["stdout_parse_error"] = None
    return metrics


def unknown_metrics() -> dict[str, Any]:
    return {
        "total_cost_usd": None,
        "cost_confidence": "unknown",
        "cost_source": "unknown",
        "provider_reported_total_cost_usd": None,
        "model_usage_cost_usd": None,
        "permission_denial_count": 0,
        **{field: None for field in TOKEN_FIELDS},
        "duration_ms": None,
        "duration_api_ms": None,
        "num_turns": None,
    }


def cost_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    direct = number_or_none(payload.get("total_cost_usd"))
    model_cost = model_usage_cost(payload.get("modelUsage"))
    if direct is not None and model_cost is not None and abs(direct - model_cost) > 0.000001:
        return {
            "total_cost_usd": None,
            "cost_confidence": "conflict",
            "cost_source": "conflict",
            "provider_reported_total_cost_usd": direct,
            "model_usage_cost_usd": model_cost,
        }
    if direct is not None:
        return {
            "total_cost_usd": direct,
            "cost_confidence": "provider_reported",
            "cost_source": "total_cost_usd",
            "provider_reported_total_cost_usd": direct,
            "model_usage_cost_usd": model_cost,
        }
    if model_cost is not None:
        return {
            "total_cost_usd": model_cost,
            "cost_confidence": "provider_reported",
            "cost_source": "modelUsage.costUSD",
            "provider_reported_total_cost_usd": None,
            "model_usage_cost_usd": model_cost,
        }
    return unknown_metrics() | {"stdout_parse_error": None}


def model_usage_cost(value: Any) -> float | None:
    costs: list[float] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            cost = number_or_none(obj.get("costUSD"))
            if cost is not None:
                costs.append(cost)
            for child in obj.values():
                walk(child)
        elif isinstance(obj, list):
            for child in obj:
                walk(child)

    walk(value)
    return sum(costs) if costs else None


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = [
    "TOKEN_FIELDS",
    "cost_metrics",
    "int_or_none",
    "model_usage_cost",
    "number_or_none",
    "stdout_metrics",
    "unknown_metrics",
]
