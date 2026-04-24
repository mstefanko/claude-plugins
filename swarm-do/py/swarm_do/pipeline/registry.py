"""Preset and pipeline registry loading."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import stock_pipelines_dir, stock_presets_dir, user_pipelines_dir, user_presets_dir
from .simple_yaml import load_yaml


@dataclass(frozen=True)
class RegistryItem:
    name: str
    path: Path
    origin: str


def _items(user_dir: Path, stock_dir: Path, suffix: str) -> list[RegistryItem]:
    found: list[RegistryItem] = []
    for origin, base in (("stock", stock_dir), ("user", user_dir)):
        if not base.is_dir():
            continue
        for path in sorted(base.glob(f"*{suffix}")):
            found.append(RegistryItem(path.stem, path, origin))
    return found


def list_presets() -> list[RegistryItem]:
    return _items(user_presets_dir(), stock_presets_dir(), ".toml")


def list_pipelines() -> list[RegistryItem]:
    return _items(user_pipelines_dir(), stock_pipelines_dir(), ".yaml")


def find_preset(name: str) -> RegistryItem | None:
    for item in list_presets():
        if item.name == name:
            return item
    return None


def find_pipeline(name_or_path: str) -> RegistryItem | None:
    path = Path(name_or_path)
    if path.is_file():
        return RegistryItem(path.stem, path, "path")
    for item in list_pipelines():
        if item.name == name_or_path:
            return item
    return None


def load_preset(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_pipeline(path: Path) -> dict[str, Any]:
    value = load_yaml(path)
    if not isinstance(value, dict):
        raise ValueError(f"pipeline root must be a mapping: {path}")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
