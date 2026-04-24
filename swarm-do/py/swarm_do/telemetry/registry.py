"""Telemetry ledger registry — single source of truth for ledger names, filenames,
canonical schema paths, and schema fallback order.

Downstream modules (schemas, cli, sub-command writers in later phases) resolve
everything through this registry. No other file in swarm_do.telemetry should
hardcode schema paths or ledger filenames.

PLUGIN_ROOT points at the repository root (4 parents up from this file):
    registry.py -> telemetry -> swarm_do -> py -> swarm-do (repo root component)
We use parents[4] so PLUGIN_ROOT resolves to the marketplace/worktree root
that owns the `swarm-do/` directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


# Four parents up from this file lands on:
#   .../<plugin-root>/swarm-do/py/swarm_do/telemetry/registry.py
#     parents[0] = telemetry
#     parents[1] = swarm_do
#     parents[2] = py
#     parents[3] = swarm-do
#     parents[4] = <plugin-root>
PLUGIN_ROOT: Path = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Ledger:
    """Metadata describing one telemetry ledger.

    fallback_order: tuple of candidate schema paths ordered from preferred
    (v2, v3, ...) to legacy (v1). `schemas.load_schema` returns the first
    entry that exists on disk.
    """

    name: str
    filename: str
    schema_path: Path
    fallback_order: Tuple[Path, ...]


_TELEMETRY_SCHEMA_DIR: Path = PLUGIN_ROOT / "swarm-do" / "schemas" / "telemetry"


LEDGERS: Dict[str, Ledger] = {
    "runs": Ledger(
        name="runs",
        filename="runs.jsonl",
        schema_path=_TELEMETRY_SCHEMA_DIR / "runs.schema.json",
        fallback_order=(_TELEMETRY_SCHEMA_DIR / "runs.schema.json",),
    ),
    "findings": Ledger(
        name="findings",
        filename="findings.jsonl",
        schema_path=_TELEMETRY_SCHEMA_DIR / "findings.v2.schema.json",
        fallback_order=(
            _TELEMETRY_SCHEMA_DIR / "findings.v2.schema.json",
            _TELEMETRY_SCHEMA_DIR / "findings.schema.json",
        ),
    ),
    "outcomes": Ledger(
        name="outcomes",
        filename="outcomes.jsonl",
        schema_path=_TELEMETRY_SCHEMA_DIR / "outcomes.schema.json",
        fallback_order=(_TELEMETRY_SCHEMA_DIR / "outcomes.schema.json",),
    ),
    "adjudications": Ledger(
        name="adjudications",
        filename="adjudications.jsonl",
        schema_path=_TELEMETRY_SCHEMA_DIR / "adjudications.v2.schema.json",
        fallback_order=(
            _TELEMETRY_SCHEMA_DIR / "adjudications.v2.schema.json",
            _TELEMETRY_SCHEMA_DIR / "adjudications.schema.json",
        ),
    ),
    "finding_outcomes": Ledger(
        name="finding_outcomes",
        filename="finding_outcomes.jsonl",
        schema_path=_TELEMETRY_SCHEMA_DIR / "finding_outcomes.schema.json",
        fallback_order=(_TELEMETRY_SCHEMA_DIR / "finding_outcomes.schema.json",),
    ),
}


def resolve_telemetry_dir() -> Path:
    """Return the directory containing ledger JSONL files.

    CLAUDE_PLUGIN_DATA (when set) is the plugin's writable data root;
    ledgers live under its `telemetry/` subdirectory — same layout
    swarm-run and bin/swarm-telemetry.legacy used. When unset, fall
    back to the in-repo development data tree.
    """
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base) / "telemetry"
    return PLUGIN_ROOT / "data" / "telemetry"


def resolve_ledger_path(ledger_name: str) -> Path:
    """Return the absolute path to a named ledger's JSONL file."""
    return resolve_telemetry_dir() / LEDGERS[ledger_name].filename
