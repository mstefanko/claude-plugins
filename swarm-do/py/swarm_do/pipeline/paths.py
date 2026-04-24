"""Filesystem locations for the preset/pipeline registry."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_data_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base)
    return REPO_ROOT / "data"


def stock_presets_dir() -> Path:
    return REPO_ROOT / "presets"


def stock_pipelines_dir() -> Path:
    return REPO_ROOT / "pipelines"


def user_presets_dir() -> Path:
    return resolve_data_dir() / "presets"


def user_pipelines_dir() -> Path:
    return resolve_data_dir() / "pipelines"


def current_preset_path() -> Path:
    return resolve_data_dir() / "current-preset.txt"
