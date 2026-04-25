"""Stable YAML rendering for generated pipeline files."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


TOP_ORDER = (
    "pipeline_version",
    "name",
    "description",
    "origin",
    "forked_from",
    "forked_from_hash",
    "generated_by",
    "parallelism",
    "stages",
)
STAGE_ORDER = ("id", "depends_on", "agents", "fan_out", "provider", "merge", "failure_tolerance")
AGENT_ORDER = ("role", "route", "backend", "model", "effort")
FAN_OUT_ORDER = ("role", "count", "variant", "variants", "routes")
ROUTE_ORDER = ("backend", "model", "effort")
MERGE_ORDER = ("strategy", "agent")
PROVIDER_ORDER = (
    "type",
    "command",
    "providers",
    "mode",
    "strict_contract",
    "output",
    "memory",
    "timeout_seconds",
)
FAILURE_TOLERANCE_ORDER = ("mode", "min_success")

PLAIN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RESERVED = {"true", "false", "null", "~"}
NUMERIC_RE = re.compile(r"-?[0-9]+(\.[0-9]+)?")


def render_pipeline_yaml(pipeline: Mapping[str, Any]) -> str:
    return render_yaml(pipeline).rstrip() + "\n"


def render_yaml(value: Any) -> str:
    lines = _render_value(value, 0)
    return "\n".join(lines) + ("\n" if lines else "")


def _render_value(value: Any, indent: int) -> list[str]:
    if isinstance(value, Mapping):
        return _render_mapping(value, indent)
    if isinstance(value, list):
        return _render_list(value, indent)
    return [" " * indent + _format_scalar(value)]


def _render_mapping(mapping: Mapping[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    for key, value in _ordered_items(mapping):
        prefix = " " * indent + f"{key}:"
        if _is_scalar(value) or _is_inline_scalar_list(value):
            lines.append(prefix + " " + _format_scalar(value))
        else:
            lines.append(prefix)
            lines.extend(_render_value(value, indent + 2))
    return lines


def _render_list(items: list[Any], indent: int) -> list[str]:
    lines: list[str] = []
    for item in items:
        prefix = " " * indent + "-"
        if _is_scalar(item) or _is_inline_scalar_list(item):
            lines.append(prefix + " " + _format_scalar(item))
        elif isinstance(item, Mapping):
            ordered = list(_ordered_items(item))
            if not ordered:
                lines.append(prefix + " {}")
                continue
            first_key, first_value = ordered[0]
            first_prefix = prefix + f" {first_key}:"
            if _is_scalar(first_value) or _is_inline_scalar_list(first_value):
                lines.append(first_prefix + " " + _format_scalar(first_value))
            else:
                lines.append(first_prefix)
                lines.extend(_render_value(first_value, indent + 4))
            for key, value in ordered[1:]:
                child_prefix = " " * (indent + 2) + f"{key}:"
                if _is_scalar(value) or _is_inline_scalar_list(value):
                    lines.append(child_prefix + " " + _format_scalar(value))
                else:
                    lines.append(child_prefix)
                    lines.extend(_render_value(value, indent + 4))
        else:
            lines.append(prefix)
            lines.extend(_render_value(item, indent + 2))
    return lines


def _ordered_items(mapping: Mapping[str, Any]) -> list[tuple[str, Any]]:
    keys = list(mapping.keys())
    order = _order_for_mapping(mapping)
    ordered = [key for key in order if key in mapping]
    ordered.extend(sorted(key for key in keys if key not in set(ordered)))
    return [(key, mapping[key]) for key in ordered]


def _order_for_mapping(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    keys = set(mapping.keys())
    if {"pipeline_version", "stages"} & keys:
        return TOP_ORDER
    if "id" in keys and ("agents" in keys or "fan_out" in keys or "provider" in keys):
        return STAGE_ORDER
    if "role" in keys and keys <= set(AGENT_ORDER):
        return AGENT_ORDER
    if {"role", "count", "variant"} & keys:
        return FAN_OUT_ORDER
    if {"backend", "model", "effort"} & keys:
        return ROUTE_ORDER
    if {"strategy", "agent"} & keys:
        return MERGE_ORDER
    if "type" in keys and "providers" in keys:
        return PROVIDER_ORDER
    if "mode" in keys and keys <= set(FAILURE_TOLERANCE_ORDER):
        return FAILURE_TOLERANCE_ORDER
    return ()


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_inline_scalar_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_scalar(item) for item in value)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    text = str(value)
    if text and PLAIN_RE.fullmatch(text) and text not in RESERVED and not NUMERIC_RE.fullmatch(text):
        return text
    return json.dumps(text)
