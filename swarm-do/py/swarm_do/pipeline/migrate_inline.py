"""One-time migration from user pipeline YAML files to inline preset graphs."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .actions import atomic_write_text, render_toml, validate_preset_name
from .paths import resolve_data_dir, user_presets_dir
from .registry import find_preset, load_preset
from .simple_yaml import load_yaml
from .validation import validate_preset_mapping


SENTINEL_NAME = ".preset-migrate-v1.done"


@dataclasses.dataclass(frozen=True)
class MigrationSummary:
    migrated: int
    archived_orphans: int
    sentinel: Path
    orphans: tuple[tuple[str, Path], ...] = ()

    def lines(self) -> list[str]:
        lines = [
            f"migrated: {self.migrated}, archived-orphans: {self.archived_orphans}, sentinel: {self.sentinel}"
        ]
        for name, path in self.orphans:
            lines.append(f"orphan: {name}; to adopt run: swarm preset adopt {path} --template <stock-preset-name>")
        return lines


def sentinel_path(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / SENTINEL_NAME


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _archive(path: Path, archive_dir: Path, timestamp: str) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{path.name}.{timestamp}"
    idx = 2
    while target.exists():
        target = archive_dir / f"{path.name}.{timestamp}.{idx}"
        idx += 1
    path.replace(target)
    return target


def migrate_user_pipelines(data_dir: Path | None = None) -> MigrationSummary:
    base = data_dir or resolve_data_dir()
    sentinel = sentinel_path(base)
    if sentinel.is_file():
        return MigrationSummary(0, 0, sentinel)

    pipelines_dir = base / "pipelines"
    presets_dir = base / "presets"
    timestamp = _timestamp()
    migrated = 0
    orphan_rows: list[tuple[str, Path]] = []

    if pipelines_dir.is_dir():
        preset_by_pipeline: dict[str, Path] = {}
        if presets_dir.is_dir():
            for preset_path in sorted(presets_dir.glob("*.toml")):
                try:
                    preset = load_preset(preset_path)
                except Exception:
                    continue
                pipeline_name = preset.get("pipeline")
                if isinstance(pipeline_name, str) and pipeline_name:
                    preset_by_pipeline[pipeline_name] = preset_path

        archive_dir = pipelines_dir / ".archived"
        for pipeline_path in sorted(path for path in pipelines_dir.glob("*.yaml") if path.is_file()):
            name = pipeline_path.stem
            preset_path = preset_by_pipeline.get(name)
            archived_path = _archive(pipeline_path, archive_dir, timestamp)
            if preset_path is None:
                orphan_rows.append((name, archived_path))
                continue
            preset = load_preset(preset_path)
            graph = load_yaml(archived_path)
            if not isinstance(graph, dict):
                raise ValueError(f"pipeline root must be a mapping: {archived_path}")
            preset.pop("pipeline", None)
            preset["pipeline_inline"] = graph
            result, _ = validate_preset_mapping(preset, str(preset.get("name") or preset_path.stem))
            if not result.ok:
                raise ValueError(f"migrated preset is invalid: {preset_path}: {'; '.join(result.errors)}")
            atomic_write_text(preset_path, render_toml(preset))
            migrated += 1

    atomic_write_text(sentinel, _timestamp() + "\n")
    return MigrationSummary(migrated, len(orphan_rows), sentinel, tuple(orphan_rows))


def adopt_archived_pipeline(archived_yaml: Path, *, template: str, name: str | None = None) -> Path:
    if not archived_yaml.is_file():
        raise ValueError(f"archived pipeline not found: {archived_yaml}")
    template_item = find_preset(template)
    if template_item is None or template_item.origin != "stock":
        raise ValueError(f"stock template preset not found: {template}")
    new_name = name or archived_yaml.name.split(".yaml", 1)[0]
    validate_preset_name(new_name)
    target = user_presets_dir() / f"{new_name}.toml"
    if target.exists():
        raise ValueError(f"preset already exists: {new_name}")
    graph = load_yaml(archived_yaml)
    if not isinstance(graph, dict):
        raise ValueError(f"pipeline root must be a mapping: {archived_yaml}")
    template_data = load_preset(template_item.path)
    data: dict[str, Any] = {}
    for key in (
        "description",
        "routing",
        "budget",
        "decompose",
        "mem_prime",
        "review_providers",
    ):
        if key in template_data:
            data[key] = template_data[key]
    data.update(
        {
            "name": new_name,
            "origin": "user",
            "forked_from": template_item.name,
            "pipeline_inline": graph,
        }
    )
    result, _ = validate_preset_mapping(data, new_name)
    if not result.ok:
        raise ValueError("; ".join(result.errors))
    atomic_write_text(target, render_toml(data))
    return target
