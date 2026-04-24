"""`swarm-telemetry query <sql>` — run SQL against in-memory SQLite.

Byte-parity port of swarm-telemetry.legacy:399-497. Loads all five ledgers
into a `:memory:` sqlite3 connection as TEXT columns, serializing list/dict
values to JSON. Tab-separated output on stdout: header row first, then data
rows (None becomes empty string). SELECT-less statements (DDL/DML) exit 0
silently. sqlite3 errors print to stderr and exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT

_LEDGER_COLS: Dict[str, List[str]] = {
    "runs": [
        "run_id", "timestamp_start", "timestamp_end", "backend", "model", "effort",
        "prompt_bundle_hash", "config_hash", "role", "phase_kind", "phase_complexity",
        "issue_id", "repo", "base_sha", "head_sha", "diff_size_bytes", "input_tokens",
        "cached_input_tokens", "output_tokens", "estimated_cost_usd", "wall_clock_seconds",
        "tool_call_count", "cap_hit", "budget_breach", "schema_ok", "exit_code",
        "setting_source", "writer_status", "review_verdict", "last_429_at",
        "risk_tags",
    ],
    "findings": [
        "finding_id", "run_id", "timestamp", "role", "issue_id", "severity",
        "category", "summary", "file_path", "line_start", "line_end", "schema_ok",
        "stable_finding_hash_v1", "duplicate_cluster_id", "short_summary",
    ],
    "outcomes": [
        "outcome_id", "issue_id", "timestamp", "writer_run_id", "review_run_id",
        "verdict", "schema_ok",
    ],
    "adjudications": [
        "adjudication_id", "outcome_id", "issue_id", "timestamp", "adjudicator",
        "decision", "schema_ok",
    ],
    "finding_outcomes": [
        "finding_outcome_id", "finding_id", "observed_at", "maintainer_action",
        "followup_ref", "time_to_action_hours", "time_to_fix_hours",
        "recurrence_of", "schema_ok",
    ],
}


def _resolve_telemetry_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base) / "telemetry"
    return PLUGIN_ROOT / "data" / "telemetry"


def _load_ledger(tel_dir: Path, name: str, cols: List[str]) -> List[Dict[str, object]]:
    path = tel_dir / f"{name}.jsonl"
    if not path.is_file() or path.stat().st_size == 0:
        return []
    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    f"swarm-telemetry: query: {name}.jsonl line {lineno} parse error: {e}",
                    file=sys.stderr,
                )
                continue
            row: Dict[str, object] = {}
            for col in cols:
                val = obj.get(col)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val)
                row[col] = val
            rows.append(row)
    return rows


def run(args: argparse.Namespace) -> int:
    sql = args.sql
    if not sql:
        print("swarm-telemetry: query requires a SQL argument", file=sys.stderr)
        return 1

    tel_dir = _resolve_telemetry_dir()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    for tbl, cols in _LEDGER_COLS.items():
        col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
        conn.execute(f'CREATE TABLE "{tbl}" ({col_defs})')
        rows = _load_ledger(tel_dir, tbl, cols)
        if rows:
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(f'"{c}"' for c in cols)
            conn.executemany(
                f'INSERT INTO "{tbl}" ({col_names}) VALUES ({placeholders})',
                [[r.get(c) for c in cols] for r in rows],
            )
    conn.commit()

    try:
        cur = conn.execute(sql)
        if cur.description is None:
            conn.commit()
            return 0
        headers = [d[0] for d in cur.description]
        print("\t".join(headers))
        for row in cur.fetchall():
            print("\t".join("" if v is None else str(v) for v in row))
    except sqlite3.Error as e:
        print(f"swarm-telemetry: query error: {e}", file=sys.stderr)
        return 1
    return 0
