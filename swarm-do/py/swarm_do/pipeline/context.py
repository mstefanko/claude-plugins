"""Runtime context for active preset/pipeline telemetry fields."""

from __future__ import annotations

import argparse
import sys

from .graph_source import resolve_preset_graph
from .registry import find_preset, load_preset
from .resolver import active_preset_name


def current_context() -> dict[str, str | None]:
    preset_name = active_preset_name()
    preset = {"name": "default-fallback", "pipeline": "default", "budget": {}}
    if preset_name:
        item = find_preset(preset_name)
        if item:
            preset = load_preset(item.path)
    resolved = resolve_preset_graph(preset)
    pipeline_name = resolved.source_name or (f"inline:{preset_name}" if preset_name else "default")
    return {
        "preset_name": preset_name,
        "pipeline_name": pipeline_name,
        "pipeline_hash": resolved.source_hash,
        "graph_source": resolved.source,
        "graph_source_name": resolved.source_name,
        "graph_lineage_name": resolved.lineage_name,
        "graph_lineage_hash": resolved.lineage_hash,
        "source_hash": resolved.source_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm-pipeline-context")
    parser.add_argument(
        "field",
        choices=[
            "preset_name",
            "pipeline_name",
            "pipeline_hash",
            "graph_source",
            "graph_source_name",
            "graph_lineage_name",
            "graph_lineage_hash",
            "source_hash",
        ],
    )
    args = parser.parse_args(argv)
    value = current_context().get(args.field)
    if value is not None:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
