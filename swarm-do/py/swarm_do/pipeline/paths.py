"""Filesystem locations for the preset/pipeline registry."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_data_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base)
    # The dispatcher launches writer subprocesses with `claude -p
    # --permission-mode dontAsk`. Claude Code auto-denies Write/Edit to any
    # path inside the user's `~/.claude/` tree in that mode, regardless of
    # allow rules in --settings, --allowedTools, or --setting-sources. The
    # historical fallback `<REPO_ROOT>/data` lives inside
    # `~/.claude/plugins/...`, so writer phase artifacts (result.json,
    # handoff.json) cannot land there in the dontAsk launcher path.
    # Default to the XDG user data dir, which is outside `~/.claude/`.
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "swarmdaddy"


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
