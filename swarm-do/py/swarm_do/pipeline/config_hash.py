"""Deterministic hash for the active swarm routing surface."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .context import current_context
from .paths import resolve_data_dir
from .resolver import active_preset_name, preset_path


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def active_config_payload() -> dict[str, object]:
    preset_name = active_preset_name()
    preset_file = preset_path(preset_name) if preset_name else None
    context = current_context()
    return {
        "backends_toml": _file_digest(resolve_data_dir() / "backends.toml"),
        "preset_name": preset_name,
        "preset_file": str(preset_file) if preset_file else None,
        "preset_hash": _file_digest(preset_file) if preset_file else None,
        "pipeline_name": context.get("pipeline_name"),
        "pipeline_hash": context.get("pipeline_hash"),
    }


def active_config_hash() -> str:
    payload = json.dumps(active_config_payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm-config-hash")
    parser.parse_args(argv)
    print(active_config_hash())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
