"""Retention-based purge of telemetry ledgers.

Source-of-truth pointer to ADR 0001 — retention values must match.
Module-level dicts (LEDGER_TIMESTAMP_FIELD, DEFAULT_RETENTION_DAYS) are the
canonical source for purge behavior. Updating either dict requires a matching
ADR 0001 revision.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from swarm_do.telemetry.jsonl import atomic_write, stream_read
from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT


# Maps each ledger name to its canonical timestamp field.
# Source-of-truth pointer to ADR 0001; update in lockstep.
LEDGER_TIMESTAMP_FIELD = {
    "runs": "timestamp_start",
    "findings": "timestamp",
    "outcomes": "timestamp",
    "adjudications": "timestamp",
    "finding_outcomes": "observed_at",
}

# Default retention days per ledger.
# Source-of-truth pointer to ADR 0001; update in lockstep.
DEFAULT_RETENTION_DAYS = {
    "runs": 180,
    "findings": 365,
    "outcomes": 365,
    "adjudications": 365,
    "finding_outcomes": 180,
}


def _resolve_ledger_path(ledger_name: str) -> str:
    """Resolve the filesystem path to a ledger file.

    Respects CLAUDE_PLUGIN_DATA env var if set; otherwise uses PLUGIN_ROOT.
    """
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data_dir:
        data_dir = PLUGIN_ROOT / "data" / "telemetry"
    else:
        data_dir = Path(data_dir)

    ledger = LEDGERS[ledger_name]
    return str(data_dir / ledger.filename)


def run(args: argparse.Namespace) -> int:
    """Purge rows older than the retention window.

    Iterates either [args.ledger] (if specified) or all ledgers in sorted order.
    For each ledger:
      - Reads all rows via stream_read
      - Filters rows where timestamp > cutoff
      - Atomically writes remainder via atomic_write
      - Reports: purge: <ledger>: removed N of M rows (kept M-N)

    On FileNotFoundError: prints 'purge: <ledger>: not present, skipped' and continues.

    Returns 0 on success. --dry-run prints removal counts without modifying files.
    """
    # Determine which ledgers to process.
    if args.ledger:
        ledger_names = [args.ledger]
    else:
        ledger_names = sorted(LEDGERS.keys())

    # Parse --older-than argument.
    retention_days = args.older_than
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    total_removed = 0
    total_kept = 0
    processed_ledgers = 0

    for ledger_name in ledger_names:
        try:
            path = _resolve_ledger_path(ledger_name)
            ts_field = LEDGER_TIMESTAMP_FIELD[ledger_name]

            # Stream and filter rows.
            all_rows = list(stream_read(path))
            kept_rows = []
            for row in all_rows:
                ts_str = row.get(ts_field)
                if ts_str:
                    try:
                        # Parse ISO8601 timestamp, handling both 'Z' and '+00:00' formats.
                        row_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if row_ts > cutoff:
                            kept_rows.append(row)
                    except (ValueError, AttributeError, TypeError):
                        # Malformed timestamp; keep the row to be safe.
                        # TypeError guards against non-string ts_str values
                        # (closes mstefanko-plugins-lka).
                        kept_rows.append(row)
                else:
                    # Missing timestamp; keep the row.
                    kept_rows.append(row)

            removed = len(all_rows) - len(kept_rows)
            kept = len(kept_rows)

            if args.dry_run:
                print(f"purge: {ledger_name}: would remove {removed} of {len(all_rows)} rows (kept {kept})")
            else:
                atomic_write(path, kept_rows)
                print(f"purge: {ledger_name}: removed {removed} of {len(all_rows)} rows (kept {kept})")

            total_removed += removed
            total_kept += kept
            processed_ledgers += 1

        except FileNotFoundError:
            print(f"purge: {ledger_name}: not present, skipped")
            continue

    print(f"purge: total: removed {total_removed} of {total_removed + total_kept} rows across {processed_ledgers} ledgers")
    return 0
