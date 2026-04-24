"""`swarm-telemetry dump <ledger>` — pretty-print a JSONL ledger as a JSON array.

Byte-parity with the legacy bash `_cmd_dump` (swarm-telemetry.legacy:157-167):
  - Missing or empty ledger file prints `[]` and exits 0 (fail-open).
  - Otherwise prints `jq -s '.' <path>` output — a 2-space-indented JSON array
    with a trailing newline. Python's `print(json.dumps(rows, indent=2))`
    matches byte-for-byte against jq's default pretty-printer for the JSON
    types we emit (no unicode escaping in our ledgers).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List

from swarm_do.telemetry.jsonl import stream_read
from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT


def _resolve_telemetry_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base) / "telemetry"
    return PLUGIN_ROOT / "data" / "telemetry"


def run(args: argparse.Namespace) -> int:
    ledger_name: str = args.ledger
    if ledger_name not in LEDGERS:
        valid = " ".join(sorted(LEDGERS.keys()))
        print(
            f"swarm-telemetry: unknown ledger '{ledger_name}' — must be one of: {valid}",
            flush=True,
        )
        return 1

    path = _resolve_telemetry_dir() / LEDGERS[ledger_name].filename
    if not path.is_file() or path.stat().st_size == 0:
        print("[]")
        return 0

    rows: List[dict] = list(stream_read(path))
    print(json.dumps(rows, indent=2))
    return 0
