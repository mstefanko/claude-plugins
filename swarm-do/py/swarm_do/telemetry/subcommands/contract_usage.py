"""`swarm-telemetry contract-usage` — role-contract violation report.

Joins observations.jsonl (per-run tool-category counts) with the on-disk
permission fragment for the run's role and emits violations: categories
used but either denied or outside the allow set. Pure post-hoc — no
runtime instrumentation needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from swarm_do.telemetry.permissions_contract import compute_contract_usage
from swarm_do.telemetry.registry import resolve_ledger_path


def _iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or not stripped.startswith("{"):
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def aggregate_contract_usage(
    observations: Iterable[dict[str, Any]],
    *,
    role: str | None = None,
    include_unknown: bool = False,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    violation_counts: dict[str, dict[str, int]] = {}

    for row in observations:
        details = row.get("details") or {}
        if not isinstance(details, dict):
            continue
        row_role = details.get("role") or row.get("phase_id")
        if not isinstance(row_role, str):
            continue
        if role is not None and row_role != role:
            continue
        category_counts = details.get("tool_category_counts") or {}
        if not isinstance(category_counts, dict):
            continue

        usage = compute_contract_usage(row_role, category_counts)
        if usage["unknown_contract"] and not include_unknown:
            continue

        run_record = {
            "run_id": row.get("run_id"),
            "role": row_role,
            "stage_id": details.get("stage_id"),
            "unit_id": details.get("unit_id"),
            "violations": usage["violations"],
            "unknown_contract": usage["unknown_contract"],
        }
        runs.append(run_record)

        bucket = violation_counts.setdefault(row_role, {})
        for v in usage["violations"]:
            key = f"{v['reason']}:{v['category']}"
            bucket[key] = bucket.get(key, 0) + v["count"]

    summary_by_role = []
    for r, buckets in sorted(violation_counts.items()):
        if not buckets:
            continue
        summary_by_role.append(
            {
                "role": r,
                "violation_categories": [
                    {"key": key, "count": count}
                    for key, count in sorted(buckets.items())
                ],
                "total_violation_count": sum(buckets.values()),
            }
        )

    return {
        "summary": {
            "run_count": len(runs),
            "violating_run_count": sum(1 for r in runs if r["violations"]),
            "roles_with_violations": [s["role"] for s in summary_by_role],
        },
        "by_role": summary_by_role,
        "runs": runs,
    }


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "contract-usage",
        add_help=True,
        help="Role-contract violation report from observations.jsonl × permissions/<role>.json.",
    )
    parser.add_argument("--role", default=None, help="Filter to a single role (e.g. 'agent-clarify').")
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Include runs whose role has no permission fragment on disk.",
    )


def run(ns: argparse.Namespace) -> int:
    obs_path = resolve_ledger_path("observations")
    rows = list(_iter_rows(obs_path))
    report = aggregate_contract_usage(
        rows,
        role=ns.role,
        include_unknown=getattr(ns, "include_unknown", False),
    )
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0
