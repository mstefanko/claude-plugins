"""`swarm-telemetry roundtrips` — per-unit writer/review iteration counts.

Reads runs.jsonl, groups rows by ``work_unit_id``, and emits per-unit
aggregates (writer attempts, review verdicts, retry/handoff counters,
wall-clock totals). Pure post-hoc analysis — no schema changes, no new
ledger writes. Used to detect units that round-tripped through writer ↔
review repeatedly without converging.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from swarm_do.telemetry.registry import resolve_ledger_path


_WRITER_ROLES = {"agent-writer", "writer"}
_SPEC_REVIEW_ROLES = {"agent-spec-review", "spec-review"}
_REVIEW_ROLES = {"agent-review", "review", "agent-code-review", "code-review"}


def _parse_ts(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _classify_role(role: str | None) -> str:
    if not role:
        return "other"
    if role in _WRITER_ROLES:
        return "writer"
    if role in _SPEC_REVIEW_ROLES:
        return "spec_review"
    if role in _REVIEW_ROLES:
        return "review"
    return "other"


def aggregate_roundtrips(
    rows: Iterable[dict[str, Any]],
    *,
    variant: str | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    by_unit: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "unit_id": None,
            "runs_total": 0,
            "writer_runs": 0,
            "spec_review_runs": 0,
            "review_runs": 0,
            "other_runs": 0,
            "writer_statuses": [],
            "spec_review_verdicts": [],
            "review_verdicts": [],
            "max_retry_count": 0,
            "max_handoff_count": 0,
            "needs_context_total": 0,
            "wall_seconds_total": 0.0,
            "first_run_ts": None,
            "last_run_ts": None,
            "variants": set(),
            "roles": set(),
        }
    )

    for row in rows:
        if variant is not None and row.get("variant") != variant:
            continue
        row_unit = row.get("work_unit_id")
        if not isinstance(row_unit, str):
            continue
        if unit_id is not None and row_unit != unit_id:
            continue

        bucket = by_unit[row_unit]
        bucket["unit_id"] = row_unit
        bucket["runs_total"] += 1

        role_class = _classify_role(row.get("role"))
        bucket[f"{role_class}_runs"] += 1
        bucket["roles"].add(row.get("role") or "")

        if role_class == "writer":
            bucket["writer_statuses"].append(row.get("writer_status"))
        elif role_class == "spec_review":
            bucket["spec_review_verdicts"].append(row.get("review_verdict"))
        elif role_class == "review":
            bucket["review_verdicts"].append(row.get("review_verdict"))

        retry = row.get("unit_retry_count")
        if isinstance(retry, int):
            bucket["max_retry_count"] = max(bucket["max_retry_count"], retry)
        handoff = row.get("unit_handoff_count")
        if isinstance(handoff, int):
            bucket["max_handoff_count"] = max(bucket["max_handoff_count"], handoff)
        needs = row.get("unit_needs_context_count")
        if isinstance(needs, int):
            bucket["needs_context_total"] += needs

        wall = row.get("wall_clock_seconds")
        if isinstance(wall, (int, float)):
            bucket["wall_seconds_total"] += float(wall)

        ts = _parse_ts(row.get("timestamp_start"))
        if ts:
            ts_iso = ts.isoformat()
            if bucket["first_run_ts"] is None or ts_iso < bucket["first_run_ts"]:
                bucket["first_run_ts"] = ts_iso
            if bucket["last_run_ts"] is None or ts_iso > bucket["last_run_ts"]:
                bucket["last_run_ts"] = ts_iso

        v = row.get("variant")
        if isinstance(v, str):
            bucket["variants"].add(v)

    units: list[dict[str, Any]] = []
    for bucket in by_unit.values():
        bucket["variants"] = sorted(bucket["variants"])
        bucket["roles"] = sorted(role for role in bucket["roles"] if role)
        bucket["wall_seconds_total"] = round(bucket["wall_seconds_total"], 3)
        units.append(bucket)
    units.sort(key=lambda u: (u["first_run_ts"] or "", u["unit_id"]))

    summary = {
        "unit_count": len(units),
        "writer_runs_total": sum(u["writer_runs"] for u in units),
        "spec_review_runs_total": sum(u["spec_review_runs"] for u in units),
        "review_runs_total": sum(u["review_runs"] for u in units),
        "max_retry_count": max((u["max_retry_count"] for u in units), default=0),
        "max_handoff_count": max((u["max_handoff_count"] for u in units), default=0),
    }
    return {"summary": summary, "units": units}


def _build_parser(subparsers: argparse._SubParsersAction | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser() if subparsers is None else subparsers.add_parser(
        "roundtrips",
        add_help=True,
        help="Per-unit writer/review iteration counts derived from runs.jsonl.",
    )
    parser.add_argument("--variant", default=None, help="Filter to runs with this variant tag.")
    parser.add_argument("--unit-id", dest="unit_id", default=None, help="Filter to one work unit.")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json).",
    )
    return parser


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    _build_parser(subparsers)


def _render_markdown(report: dict[str, Any]) -> str:
    lines = ["| unit_id | writer | spec | review | retries | handoffs | wall_s |", "|---|---:|---:|---:|---:|---:|---:|"]
    for unit in report["units"]:
        lines.append(
            "| {unit_id} | {writer} | {spec} | {review} | {retries} | {handoffs} | {wall:.1f} |".format(
                unit_id=unit["unit_id"],
                writer=unit["writer_runs"],
                spec=unit["spec_review_runs"],
                review=unit["review_runs"],
                retries=unit["max_retry_count"],
                handoffs=unit["max_handoff_count"],
                wall=unit["wall_seconds_total"],
            )
        )
    summary = report["summary"]
    lines.append("")
    lines.append(
        f"Units: {summary['unit_count']}; writer runs: {summary['writer_runs_total']}; "
        f"max retries: {summary['max_retry_count']}; max handoffs: {summary['max_handoff_count']}."
    )
    return "\n".join(lines) + "\n"


def run(ns: argparse.Namespace) -> int:
    runs_path = resolve_ledger_path("runs")
    rows = list(_iter_rows(runs_path))
    report = aggregate_roundtrips(rows, variant=ns.variant, unit_id=ns.unit_id)
    if ns.format == "markdown":
        sys.stdout.write(_render_markdown(report))
    else:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
