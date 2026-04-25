"""Diff and stock-drift helpers for user preset/pipeline forks."""

from __future__ import annotations

import dataclasses
import difflib
from pathlib import Path
from typing import Any, Callable, Mapping

from .registry import (
    RegistryItem,
    list_pipelines,
    list_presets,
    load_pipeline,
    load_preset,
    sha256_file,
)


@dataclasses.dataclass(frozen=True)
class ArtifactDiff:
    kind: str
    name: str
    source_name: str | None
    lines: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.lines)

    def text(self) -> str:
        return "\n".join(self.lines)


@dataclasses.dataclass(frozen=True)
class DriftStatus:
    kind: str
    name: str
    source_name: str | None
    stored_hash: str | None
    current_hash: str | None

    @property
    def tracked(self) -> bool:
        return bool(self.stored_hash and self.current_hash)

    @property
    def drifted(self) -> bool:
        return self.tracked and self.stored_hash != self.current_hash


def diff_user_preset(name: str) -> ArtifactDiff:
    return _diff_user_artifact(
        kind="preset",
        name=name,
        items=list_presets,
        load=load_preset,
    )


def diff_user_pipeline(name: str) -> ArtifactDiff:
    return _diff_user_artifact(
        kind="pipeline",
        name=name,
        items=list_pipelines,
        load=load_pipeline,
    )


def stock_drift_for_preset(name: str) -> DriftStatus:
    return _stock_drift(
        kind="preset",
        name=name,
        items=list_presets,
        load=load_preset,
    )


def stock_drift_for_pipeline(name: str) -> DriftStatus:
    return _stock_drift(
        kind="pipeline",
        name=name,
        items=list_pipelines,
        load=load_pipeline,
    )


def _diff_user_artifact(
    *,
    kind: str,
    name: str,
    items: Callable[[], list[RegistryItem]],
    load: Callable[[Path], dict[str, Any]],
) -> ArtifactDiff:
    user_item = _find_item(items(), name, "user")
    if user_item is None:
        raise ValueError(f"user {kind} not found: {name}")
    user_data = load(user_item.path)
    source_name = _source_name(user_data, fallback=name)
    source_item = _find_item(items(), source_name, "stock") if source_name else None
    if source_item is None:
        return ArtifactDiff(kind, name, source_name, ())

    left = source_item.path.read_text(encoding="utf-8").splitlines()
    right = user_item.path.read_text(encoding="utf-8").splitlines()
    lines = tuple(
        difflib.unified_diff(
            left,
            right,
            fromfile=f"stock/{source_item.name}",
            tofile=f"user/{user_item.name}",
            lineterm="",
        )
    )
    return ArtifactDiff(kind, name, source_name, lines)


def _stock_drift(
    *,
    kind: str,
    name: str,
    items: Callable[[], list[RegistryItem]],
    load: Callable[[Path], dict[str, Any]],
) -> DriftStatus:
    user_item = _find_item(items(), name, "user")
    if user_item is None:
        raise ValueError(f"user {kind} not found: {name}")
    data = load(user_item.path)
    source_name = _source_name(data, fallback=name)
    stored = data.get("forked_from_hash")
    stored_hash = str(stored) if isinstance(stored, str) and stored else None
    source_item = _find_item(items(), source_name, "stock") if source_name else None
    current = "sha256:" + sha256_file(source_item.path) if source_item else None
    return DriftStatus(kind, name, source_name, stored_hash, current)


def _find_item(items: list[RegistryItem], name: str | None, origin: str) -> RegistryItem | None:
    if not name:
        return None
    return next((item for item in items if item.name == name and item.origin == origin), None)


def _source_name(data: Mapping[str, Any], *, fallback: str) -> str | None:
    source = data.get("forked_from")
    if isinstance(source, str) and source:
        return source
    return fallback
