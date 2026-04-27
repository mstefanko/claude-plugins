"""Resolve the graph source embedded in or referenced by a preset."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from typing import Any, Literal, Mapping

from .registry import find_pipeline, load_pipeline


class PresetGraphError(ValueError):
    """Raised when a preset cannot resolve to a runnable graph."""


@dataclasses.dataclass(frozen=True)
class ResolvedGraph:
    graph: dict[str, Any]
    source: Literal["stock-ref", "inline-snapshot"]
    source_name: str | None
    source_hash: str
    lineage_name: str | None = None
    lineage_hash: str | None = None
    warnings: tuple[str, ...] = ()


def canonical_graph_hash(graph: Mapping[str, Any]) -> str:
    payload = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stock_pipeline(name: str) -> dict[str, Any]:
    item = find_pipeline(name)
    if item is None:
        raise PresetGraphError(f"pipeline not found: {name}")
    if item.origin not in {"stock", "path"}:
        raise PresetGraphError(f"preset pipeline must reference a stock pipeline: {name}")
    try:
        return load_pipeline(item.path)
    except Exception as exc:
        raise PresetGraphError(f"pipeline cannot be loaded: {name}: {exc}") from exc


def resolve_preset_graph(preset: Mapping[str, Any]) -> ResolvedGraph:
    """Return the graph selected by a preset's stock-ref or inline snapshot."""

    has_ref = isinstance(preset.get("pipeline"), str) and bool(str(preset.get("pipeline")).strip())
    has_inline = isinstance(preset.get("pipeline_inline"), Mapping)
    if has_ref and has_inline:
        raise PresetGraphError("preset must define exactly one graph source: pipeline or pipeline_inline")
    if not has_ref and not has_inline:
        raise PresetGraphError("preset must define a graph source: pipeline or pipeline_inline")

    if has_inline:
        graph = copy.deepcopy(dict(preset["pipeline_inline"]))  # type: ignore[index]
        warnings: list[str] = []
        lineage_name: str | None = None
        lineage_hash: str | None = None
        source = preset.get("pipeline_inline_source")
        if isinstance(source, Mapping):
            raw_name = source.get("name")
            raw_hash = source.get("hash")
            lineage_name = str(raw_name) if isinstance(raw_name, str) and raw_name else None
            lineage_hash = str(raw_hash) if isinstance(raw_hash, str) and raw_hash else None
            if lineage_name:
                item = find_pipeline(lineage_name)
                if item is None or item.origin != "stock":
                    warnings.append(f"inline graph upstream stock pipeline is missing: {lineage_name}")
        return ResolvedGraph(
            graph=graph,
            source="inline-snapshot",
            source_name=None,
            source_hash=canonical_graph_hash(graph),
            lineage_name=lineage_name,
            lineage_hash=lineage_hash,
            warnings=tuple(warnings),
        )

    name = str(preset["pipeline"]).strip()
    graph = _stock_pipeline(name)
    return ResolvedGraph(
        graph=copy.deepcopy(graph),
        source="stock-ref",
        source_name=name,
        source_hash=canonical_graph_hash(graph),
    )
