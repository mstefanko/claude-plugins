"""`swarm-telemetry report [--since Nd] [--role R] [--bucket K]` — stratified markdown.

Python port of the legacy report command. Emits a stratified
markdown table (role | complexity | phase_kind | risk_tag) computed only
WITHIN each bucket — never a global mean. This phase-9c anti-pattern guard
is preserved verbatim ("do not aggregate across buckets").

Environment:
  SWARM_TELEMETRY_NOW   ISO-8601 UTC override for deterministic testing.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm_do.telemetry.registry import LEDGERS, resolve_telemetry_dir




def _parse_ts(s: Any) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def _resolve_now() -> datetime.datetime:
    override = (os.environ.get("SWARM_TELEMETRY_NOW") or "").strip()
    if not override:
        return datetime.datetime.now(datetime.timezone.utc)
    parsed = _parse_ts(override)
    if parsed is None:
        print(
            f"swarm-telemetry: report: invalid SWARM_TELEMETRY_NOW '{override}'",
            file=sys.stderr,
        )
        sys.exit(1)
    return parsed


def run(args: argparse.Namespace) -> int:
    since_days: str = args.since or ""
    filter_role: str = args.role or ""
    bucket: str = args.bucket or "role"

    if bucket not in ("role", "complexity", "phase_kind", "risk_tag", "decompose_complexity", "decompose_source"):
        print(
            f"swarm-telemetry: report: --bucket must be one of: role complexity phase_kind risk_tag decompose_complexity decompose_source",
            file=sys.stderr,
        )
        return 1

    runs_path = resolve_telemetry_dir() / LEDGERS["runs"].filename
    if not runs_path.is_file() or runs_path.stat().st_size == 0:
        print(
            f"swarm-telemetry: report: runs.jsonl absent or empty at {runs_path} — no data to report",
            file=sys.stderr,
        )
        return 1

    now = _resolve_now()

    cutoff: Optional[datetime.datetime] = None
    if since_days:
        n_str = since_days.rstrip("d").strip()
        try:
            n = int(n_str)
            cutoff = now - datetime.timedelta(days=n)
        except ValueError:
            print(
                f"swarm-telemetry: report: invalid --since value '{since_days}' — expected Nd (e.g. 30d)",
                file=sys.stderr,
            )
            return 1

    rows: List[Dict[str, Any]] = []
    with runs_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    f"swarm-telemetry: report: runs.jsonl line {lineno} parse error: {e} — skipping",
                    file=sys.stderr,
                )
                continue
            rows.append(obj)

    filtered: List[Dict[str, Any]] = []
    excluded_window = 0
    excluded_role = 0

    for r in rows:
        ts = _parse_ts(r.get("timestamp_start") or r.get("timestamp_end"))
        if cutoff and ts and ts < cutoff:
            excluded_window += 1
            continue
        role = r.get("role", "")
        if filter_role and role != filter_role:
            excluded_role += 1
            continue
        filtered.append(r)

    def get_bucket_keys(row: Dict[str, Any]) -> List[str]:
        if bucket == "role":
            return [row.get("role") or "(none)"]
        if bucket == "complexity":
            return [row.get("phase_complexity") or "(none)"]
        if bucket == "phase_kind":
            return [row.get("phase_kind") or "(none)"]
        if bucket == "risk_tag":
            tags = row.get("risk_tags")
            if isinstance(tags, list) and len(tags) > 0:
                return list(tags)
            return ["(untagged)"]
        if bucket == "decompose_complexity":
            return [row.get("decompose_complexity") or "(none)"]
        if bucket == "decompose_source":
            return [row.get("decompose_source") or "(none)"]
        return ["(unknown)"]

    buckets: Dict[str, Dict[str, Any]] = collections.defaultdict(lambda: {
        "count": 0,
        "success_count": 0,
        "wall_secs": [],
        "cost": [],
        "budget_breach_count": 0,
        "cap_hit_count": 0,
    })

    for row in filtered:
        for key in get_bucket_keys(row):
            b = buckets[key]
            b["count"] += 1
            if row.get("exit_code") == 0:
                b["success_count"] += 1
            ws = row.get("wall_clock_seconds")
            if ws is not None:
                b["wall_secs"].append(float(ws))
            cost = row.get("estimated_cost_usd")
            if cost is not None:
                b["cost"].append(float(cost))
            if row.get("budget_breach") is True:
                b["budget_breach_count"] += 1
            if row.get("cap_hit") is True:
                b["cap_hit_count"] += 1

    filter_desc_parts: List[str] = []
    if cutoff:
        filter_desc_parts.append(f"since {since_days}")
    if filter_role:
        filter_desc_parts.append(f"role={filter_role}")
    filter_desc = ", ".join(filter_desc_parts) if filter_desc_parts else "all time, all roles"

    print("# Swarm Telemetry Report")
    print("")
    print(f"**Bucket:** `{bucket}` | **Filter:** {filter_desc}")
    print(f"**Runs matched:** {len(filtered)} of {len(rows)} total")
    if excluded_window > 0:
        print(f"**Excluded (outside window):** {excluded_window}")
    if excluded_role > 0:
        print(f"**Excluded (other roles):** {excluded_role}")
    print("")

    if not buckets:
        print("_No runs matched the current filters._")
        return 0

    sorted_keys = sorted(buckets.keys())

    print(f"| {bucket} | count | success_rate | mean_wall_s | mean_cost_usd | budget_breach | cap_hit |")
    print(f"|{'-' * max(len(bucket) + 2, 10)}|------:|-------------:|------------:|--------------:|--------------:|--------:|")

    for key in sorted_keys:
        b = buckets[key]
        count = b["count"]
        success_rt = b["success_count"] / count if count > 0 else 0.0
        mean_wall = sum(b["wall_secs"]) / len(b["wall_secs"]) if b["wall_secs"] else None
        mean_cost = sum(b["cost"]) / len(b["cost"]) if b["cost"] else None
        bb_count = b["budget_breach_count"]
        cap_count = b["cap_hit_count"]

        success_str = f"{success_rt:.0%}"
        wall_str = f"{mean_wall:.1f}" if mean_wall is not None else "n/a"
        cost_str = f"{mean_cost:.4f}" if mean_cost is not None else "n/a"

        print(f"| `{key}` | {count} | {success_str} | {wall_str} | {cost_str} | {bb_count} | {cap_count} |")

    print("")
    pipeline_cutoff = now - datetime.timedelta(days=30)
    pipeline_rows = []
    for r in filtered:
        if not r.get("pipeline_name"):
            continue
        ts = _parse_ts(r.get("timestamp_start") or r.get("timestamp_end"))
        if ts and ts < pipeline_cutoff:
            continue
        pipeline_rows.append(r)
    if pipeline_rows:
        print("## Pipeline comparison — last 30d")
        print("")
        pipeline_buckets: Dict[tuple, Dict[str, Any]] = collections.defaultdict(lambda: {
            "count": 0,
            "success_count": 0,
            "wall_secs": [],
            "cost": [],
        })
        for row in pipeline_rows:
            key = (
                row.get("pipeline_name") or "(none)",
                row.get("phase_kind") or "(none)",
                row.get("phase_complexity") or "(none)",
            )
            b = pipeline_buckets[key]
            b["count"] += 1
            if row.get("exit_code") == 0:
                b["success_count"] += 1
            ws = row.get("wall_clock_seconds")
            if ws is not None:
                b["wall_secs"].append(float(ws))
            cost = row.get("estimated_cost_usd")
            if cost is not None:
                b["cost"].append(float(cost))

        print("| pipeline | phase_kind | complexity | count | success_rate | mean_wall_s | mean_cost_usd |")
        print("|----------|------------|------------|------:|-------------:|------------:|--------------:|")
        for (pipeline, phase_kind, complexity), b in sorted(pipeline_buckets.items()):
            count = b["count"]
            success_rt = b["success_count"] / count if count > 0 else 0.0
            mean_wall = sum(b["wall_secs"]) / len(b["wall_secs"]) if b["wall_secs"] else None
            mean_cost = sum(b["cost"]) / len(b["cost"]) if b["cost"] else None
            wall_str = f"{mean_wall:.1f}" if mean_wall is not None else "n/a"
            cost_str = f"{mean_cost:.4f}" if mean_cost is not None else "n/a"
            print(
                f"| `{pipeline}` | `{phase_kind}` | `{complexity}` | {count} | "
                f"{success_rt:.0%} | {wall_str} | {cost_str} |"
            )
        print("")
    decompose_rows = [row for row in filtered if row.get("decompose_complexity") or row.get("work_unit_id")]
    if decompose_rows:
        print("## Decomposition impact")
        print("")
        impact: Dict[tuple, Dict[str, Any]] = collections.defaultdict(lambda: {
            "count": 0,
            "tool_calls": [],
            "output_bytes": [],
            "handoffs": [],
            "needs_context": [],
        })
        for row in decompose_rows:
            key = (
                row.get("phase_complexity") or row.get("decompose_complexity") or "(none)",
                row.get("phase_kind") or "(none)",
            )
            b = impact[key]
            b["count"] += 1
            for field, bucket_name in (
                ("unit_tool_call_count", "tool_calls"),
                ("unit_output_bytes", "output_bytes"),
                ("unit_handoff_count", "handoffs"),
                ("unit_needs_context_count", "needs_context"),
            ):
                value = row.get(field)
                if isinstance(value, (int, float)):
                    b[bucket_name].append(float(value))
        print("| complexity | phase_kind | count | mean_unit_tool_calls | mean_unit_output_bytes | mean_handoffs | mean_needs_context |")
        print("|------------|------------|------:|---------------------:|-----------------------:|--------------:|-------------------:|")
        for (complexity, phase_kind), b in sorted(impact.items()):
            print(
                f"| `{complexity}` | `{phase_kind}` | {b['count']} | "
                f"{_mean_or_na(b['tool_calls'])} | {_mean_or_na(b['output_bytes'])} | "
                f"{_mean_or_na(b['handoffs'])} | {_mean_or_na(b['needs_context'])} |"
            )
        print("")
    print(f"> _Report generated by swarm-telemetry. Stratified per `{bucket}` — do not aggregate across buckets._")
    return 0


def _mean_or_na(values: list[float]) -> str:
    if not values:
        return "n/a"
    return f"{sum(values) / len(values):.1f}"
