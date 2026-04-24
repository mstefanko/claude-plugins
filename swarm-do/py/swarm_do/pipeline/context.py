"""Runtime context for active preset/pipeline telemetry fields."""

from __future__ import annotations

import argparse
import sys

from .registry import find_pipeline, find_preset, load_preset, sha256_file
from .resolver import active_preset_name


def current_context() -> dict[str, str | None]:
    preset_name = active_preset_name()
    pipeline_name = "default"
    if preset_name:
        item = find_preset(preset_name)
        if item:
            preset = load_preset(item.path)
            pipeline_name = str(preset.get("pipeline") or "default")
    pipeline_hash = None
    pipeline_item = find_pipeline(pipeline_name)
    if pipeline_item:
        pipeline_hash = sha256_file(pipeline_item.path)
    return {
        "preset_name": preset_name,
        "pipeline_name": pipeline_name,
        "pipeline_hash": pipeline_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm-pipeline-context")
    parser.add_argument("field", choices=["preset_name", "pipeline_name", "pipeline_hash"])
    args = parser.parse_args(argv)
    value = current_context().get(args.field)
    if value is not None:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
