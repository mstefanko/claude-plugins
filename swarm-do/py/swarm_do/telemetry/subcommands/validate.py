"""`swarm-telemetry validate [<ledger>]` — draft-07 validate every JSONL row.

Byte-parity with legacy `_cmd_validate` + `_validate_ledger` (swarm-telemetry.legacy
lines 173-392). The legacy implementation:
  1. Emits `swarm-telemetry: validate — checking ledgers in <dir>` on stderr.
  2. Iterates ledgers in fixed order: runs, findings, outcomes, adjudications,
     finding_outcomes — or only the named ledger if an argument was given.
  3. For each ledger:
       a. Absent / empty file -> `swarm-telemetry: validate: <name> — ledger
          absent|empty (skipped)` on stderr, continue.
       b. Otherwise run embedded python validator producing per-row error
          messages on stderr and exit `min(fail_count, 255)`.
  4. Final stderr line: `swarm-telemetry: validate — all ledgers OK` or
     `swarm-telemetry: validate — FAILED (<N> validation error(s))`.
  5. Top-level exit: 0 if total_fail == 0 else 1.

The per-row "FAIL row ..." / "  OK  ..." format, the 3-errors-per-row cap,
and the min(fail_count, 255) per-ledger exit are ported verbatim.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT
from swarm_do.telemetry.schemas import validate_value

_SELF = "swarm-telemetry"
_LEDGER_ORDER: Tuple[str, ...] = (
    "runs",
    "findings",
    "outcomes",
    "adjudications",
    "finding_outcomes",
)


def _resolve_telemetry_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base) / "telemetry"
    return PLUGIN_ROOT / "data" / "telemetry"


def _schema_candidates_for_ledger(name: str) -> List[Path]:
    ledger = LEDGERS[name]
    return list(ledger.fallback_order)


def _validate_ledger(name: str, path: Path) -> int:
    """Validate one ledger. Returns min(fail_count, 255) matching legacy exit."""
    if not path.is_file():
        print(f"{_SELF}: validate: {name} — ledger absent (skipped)", file=sys.stderr)
        return 0
    if path.stat().st_size == 0:
        print(f"{_SELF}: validate: {name} — ledger empty (skipped)", file=sys.stderr)
        return 0

    schema_paths = _schema_candidates_for_ledger(name)
    for sp in schema_paths:
        if not sp.is_file():
            print(f"{_SELF}: validate: schema file missing for {name}: {sp}", file=sys.stderr)
            sys.exit(1)

    schemas: List[Tuple[Path, dict]] = []
    for sp in schema_paths:
        with sp.open("r", encoding="utf-8") as f:
            schemas.append((sp, json.load(f)))

    row_num = 0
    fail_count = 0
    bad_json = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row_num += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"  FAIL row {row_num}: JSON parse error in {name}.jsonl: {exc}",
                    file=sys.stderr,
                )
                bad_json += 1
                fail_count += 1
                continue

            validation_errors: List[Tuple[Path, List[str]]] = []
            for schema_path, schema in schemas:
                errors = validate_value(obj, schema)
                if not errors:
                    validation_errors = []
                    break
                validation_errors.append((schema_path, errors))

            if validation_errors:
                fail_count += 1
                best_schema_path, best_errors = min(
                    validation_errors, key=lambda item: len(item[1])
                )
                print(
                    f"  FAIL row {row_num} in {name}.jsonl: schema mismatch against "
                    f"{os.path.basename(str(best_schema_path))}: {best_errors[0]}",
                    file=sys.stderr,
                )
                for extra in best_errors[1:3]:
                    print(f"    {extra}", file=sys.stderr)

    if fail_count == 0:
        print(f"  OK  {name}.jsonl — {row_num} row(s) valid", file=sys.stderr)
    else:
        print(
            f"  FAIL {name}.jsonl — {fail_count} of {row_num} row(s) failed "
            f"({bad_json} JSON parse error(s))",
            file=sys.stderr,
        )

    return min(fail_count, 255)


def run(args: argparse.Namespace) -> int:
    target_ledger = getattr(args, "ledger", None)
    tel_dir = _resolve_telemetry_dir()

    print(f"{_SELF}: validate — checking ledgers in {tel_dir}", file=sys.stderr)

    total_fail = 0

    if target_ledger:
        if target_ledger not in LEDGERS:
            print(
                f"{_SELF}: unknown ledger '{target_ledger}' — must be one of: "
                "runs findings outcomes adjudications finding_outcomes",
                file=sys.stderr,
            )
            return 1
        path = tel_dir / LEDGERS[target_ledger].filename
        total_fail += _validate_ledger(target_ledger, path)
    else:
        for name in _LEDGER_ORDER:
            path = tel_dir / LEDGERS[name].filename
            total_fail += _validate_ledger(name, path)

    if total_fail == 0:
        print(f"{_SELF}: validate — all ledgers OK", file=sys.stderr)
        return 0
    print(
        f"{_SELF}: validate — FAILED ({total_fail} validation error(s))",
        file=sys.stderr,
    )
    return 1
