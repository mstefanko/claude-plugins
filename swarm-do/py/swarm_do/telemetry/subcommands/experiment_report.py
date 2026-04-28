"""`swarm-telemetry experiment-report` — scorecard-oriented dogfood report.

This command joins the low-level ledgers needed by the prepare-gate promotion
scorecard: `runs.jsonl`, `observations.jsonl`, and `run_events.jsonl`. It stays
read-only and intentionally computes only deterministic aggregate facts; manual
safety notes remain in the committed eval batch manifest.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from swarm_do.telemetry.registry import resolve_ledger_path


_SPEC_MISMATCH_VERDICTS = {"SPEC_MISMATCH"}
_REVIEW_FAILURE_VERDICTS = {"NEEDS_CHANGES", "BLOCKED", "FAILED", "FAIL", "REJECTED"}
_DOC_SKIP_EVENTS = {
    "doc_stage_skipped",
    "docs_skipped",
    "docs_stage_skipped",
}


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


def _variant(row: dict[str, Any]) -> str:
    value = row.get("variant")
    return value if isinstance(value, str) and value else "(none)"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 6)


def _add_number(bucket: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        bucket[key].append(number)


def _sum_repeated_reads(histogram: Any) -> tuple[int, int]:
    if not isinstance(histogram, list):
        return (0, 0)
    file_count = 0
    extra_count = 0
    for item in histogram:
        if not isinstance(item, dict):
            continue
        count = _integer(item.get("count"))
        if count is None or count <= 1:
            continue
        file_count += 1
        extra_count += count - 1
    return (file_count, extra_count)


def _is_doc_skip(row: dict[str, Any]) -> bool:
    event_type = str(row.get("event_type") or "").lower().replace("-", "_")
    if event_type in _DOC_SKIP_EVENTS or ("doc" in event_type and "skip" in event_type):
        return True
    details = row.get("details")
    if not isinstance(details, dict):
        return False
    if details.get("doc_stage_skipped") is True or details.get("docs_skipped") is True:
        return True
    stage = str(details.get("stage_id") or row.get("phase_id") or "").lower()
    return details.get("doc_impact") is False and "doc" in stage


def _verdict_counts(row: dict[str, Any]) -> tuple[int, int]:
    verdicts = [
        row.get("review_verdict"),
        row.get("unit_spec_review_verdict"),
    ]
    spec = 0
    review = 0
    for raw in verdicts:
        verdict = str(raw or "").upper()
        if verdict in _SPEC_MISMATCH_VERDICTS:
            spec += 1
        elif verdict in _REVIEW_FAILURE_VERDICTS:
            review += 1
    return spec, review


def aggregate_experiment_report(
    runs: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]],
    run_events: Iterable[dict[str, Any]],
    *,
    variant: str | None = None,
    batch: str | None = None,
) -> dict[str, Any]:
    run_rows = [
        row for row in runs
        if variant is None or row.get("variant") == variant
    ]
    run_ids = {row.get("run_id") for row in run_rows if isinstance(row.get("run_id"), str)}

    observations_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    observation_rows = 0
    for row in observations:
        run_id = row.get("run_id")
        if not isinstance(run_id, str):
            continue
        if run_id not in run_ids:
            continue
        observations_by_run[run_id].append(row)
        observation_rows += 1

    events_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    event_rows = 0
    for row in run_events:
        run_id = row.get("run_id")
        if not isinstance(run_id, str):
            continue
        if run_id not in run_ids:
            continue
        events_by_run[run_id].append(row)
        event_rows += 1

    buckets: dict[str, dict[str, Any]] = defaultdict(_new_variant_bucket)
    event_counts: Counter[str] = Counter()

    for row in run_rows:
        key = _variant(row)
        bucket = buckets[key]
        bucket["variant"] = key
        bucket["run_count"] += 1
        bucket["roles"].add(row.get("role") or "")
        if isinstance(row.get("work_unit_id"), str):
            bucket["work_unit_ids"].add(row["work_unit_id"])
        if isinstance(row.get("base_sha"), str):
            bucket["base_shas"].add(row["base_sha"])
        else:
            bucket["null_base_sha_count"] += 1
        if not row.get("phase_kind") or not row.get("phase_complexity"):
            bucket["null_phase_tag_count"] += 1

        tool_calls = row.get("unit_tool_call_count")
        if tool_calls is None:
            tool_calls = row.get("tool_call_count")
        _add_number(bucket, "tool_calls", tool_calls)
        _add_number(bucket, "wall_seconds", row.get("wall_clock_seconds"))
        _add_number(bucket, "input_tokens", row.get("input_tokens"))
        _add_number(bucket, "cached_input_tokens", row.get("cached_input_tokens"))
        _add_number(bucket, "output_tokens", row.get("output_tokens"))

        handoff = _integer(row.get("unit_handoff_count"))
        if handoff is not None:
            bucket["handoff_count"] += handoff
        if row.get("writer_status") == "HANDOFF_REQUESTED":
            bucket["handoff_count"] += 1
        needs_context = _integer(row.get("unit_needs_context_count"))
        count_observation_needs_context = needs_context is None
        if needs_context is not None:
            bucket["needs_context_count"] += needs_context
        retry = _integer(row.get("unit_retry_count"))
        if retry is not None:
            bucket["retry_count"] += retry

        spec, review = _verdict_counts(row)
        bucket["spec_mismatch_count"] += spec
        bucket["review_failure_count"] += review

        for obs in observations_by_run.get(row.get("run_id"), []):
            _fold_observation(
                bucket,
                obs,
                count_needs_context=count_observation_needs_context,
            )
        for event in events_by_run.get(row.get("run_id"), []):
            _fold_run_event(bucket, event)
            event_counts[str(event.get("event_type") or "(none)")] += 1

    reports = [_finalize_variant_bucket(bucket) for _, bucket in sorted(buckets.items())]
    null_phase_tags = sum(item["null_phase_tag_count"] for item in reports)
    null_base_shas = sum(item["null_base_sha_count"] for item in reports)
    unknown_metrics: list[str] = []
    if not run_rows:
        unknown_metrics.append("runs")
    if null_phase_tags:
        unknown_metrics.append("phase_tags")
    if null_base_shas:
        unknown_metrics.append("base_sha")
    if run_rows and observation_rows == 0:
        unknown_metrics.append("observations")
    if run_rows and event_rows == 0:
        unknown_metrics.append("run_events")

    return {
        "batch": batch,
        "filter": {"variant": variant},
        "summary": {
            "run_count": len(run_rows),
            "observation_count": observation_rows,
            "run_event_count": event_rows,
            "variant_count": len(reports),
            "variants": [item["variant"] for item in reports],
            "null_phase_tag_count": null_phase_tags,
            "null_base_sha_count": null_base_shas,
            "prepare_event_counts": dict(sorted(event_counts.items())),
            "unknown_safety_metrics": unknown_metrics,
            "manual_safety_notes_required": True,
            "controlled_comparison_ready": bool(run_rows) and not unknown_metrics,
        },
        "by_variant": reports,
    }


def _new_variant_bucket() -> dict[str, Any]:
    return {
        "variant": "(none)",
        "run_count": 0,
        "roles": set(),
        "work_unit_ids": set(),
        "base_shas": set(),
        "null_base_sha_count": 0,
        "null_phase_tag_count": 0,
        "tool_calls": [],
        "wall_seconds": [],
        "input_tokens": [],
        "cached_input_tokens": [],
        "output_tokens": [],
        "cache_hit_ratios": [],
        "first_test_positions": [],
        "source_read_count": 0,
        "repeated_read_file_count": 0,
        "repeated_read_extra_count": 0,
        "needs_context_count": 0,
        "needs_research_count": 0,
        "retry_count": 0,
        "handoff_count": 0,
        "spec_mismatch_count": 0,
        "review_failure_count": 0,
        "prepare_stale_rejected_count": 0,
        "prepare_dispatch_started_count": 0,
        "doc_stage_skip_count": 0,
    }


def _fold_observation(
    bucket: dict[str, Any],
    row: dict[str, Any],
    *,
    count_needs_context: bool = True,
) -> None:
    details = row.get("details")
    if not isinstance(details, dict):
        if _is_doc_skip(row):
            bucket["doc_stage_skip_count"] += 1
        return

    bucket["source_read_count"] += _integer(details.get("source_read_count")) or 0
    files, extra = _sum_repeated_reads(details.get("repeated_read_histogram"))
    bucket["repeated_read_file_count"] += files
    bucket["repeated_read_extra_count"] += extra
    _add_number(bucket, "first_test_positions", details.get("first_test_tool_call_index"))

    markers = details.get("markers")
    if isinstance(markers, dict):
        if count_needs_context:
            bucket["needs_context_count"] += _integer(markers.get("needs_context_count")) or 0
        bucket["needs_research_count"] += _integer(markers.get("needs_research_count")) or 0
        bucket["handoff_count"] += _integer(markers.get("handoff_count")) or 0

    token_usage = details.get("token_usage")
    if isinstance(token_usage, dict):
        _add_number(bucket, "cache_hit_ratios", token_usage.get("cache_hit_ratio"))

    if _is_doc_skip(row):
        bucket["doc_stage_skip_count"] += 1


def _fold_run_event(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    event_type = str(row.get("event_type") or "")
    if event_type == "prepare_stale_rejected":
        bucket["prepare_stale_rejected_count"] += 1
    elif event_type == "prepare_dispatch_started":
        bucket["prepare_dispatch_started_count"] += 1
    elif event_type == "handoff_triggered":
        bucket["handoff_count"] += 1
    elif event_type.startswith("retry_"):
        bucket["retry_count"] += 1
    if _is_doc_skip(row):
        bucket["doc_stage_skip_count"] += 1


def _finalize_variant_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant": bucket["variant"],
        "run_count": bucket["run_count"],
        "roles": sorted(role for role in bucket["roles"] if role),
        "work_unit_count": len(bucket["work_unit_ids"]),
        "base_sha_count": len(bucket["base_shas"]),
        "null_base_sha_count": bucket["null_base_sha_count"],
        "null_phase_tag_count": bucket["null_phase_tag_count"],
        "mean_tool_calls": _mean(bucket["tool_calls"]),
        "p95_tool_calls": _p95(bucket["tool_calls"]),
        "mean_wall_seconds": _mean(bucket["wall_seconds"]),
        "mean_input_tokens": _mean(bucket["input_tokens"]),
        "mean_cached_input_tokens": _mean(bucket["cached_input_tokens"]),
        "mean_output_tokens": _mean(bucket["output_tokens"]),
        "mean_cache_hit_ratio": _mean(bucket["cache_hit_ratios"]),
        "mean_first_test_position": _mean(bucket["first_test_positions"]),
        "source_read_count": bucket["source_read_count"],
        "repeated_read_file_count": bucket["repeated_read_file_count"],
        "repeated_read_extra_count": bucket["repeated_read_extra_count"],
        "needs_context_count": bucket["needs_context_count"],
        "needs_research_count": bucket["needs_research_count"],
        "retry_count": bucket["retry_count"],
        "handoff_count": bucket["handoff_count"],
        "spec_mismatch_count": bucket["spec_mismatch_count"],
        "review_failure_count": bucket["review_failure_count"],
        "prepare_stale_rejected_count": bucket["prepare_stale_rejected_count"],
        "prepare_dispatch_started_count": bucket["prepare_dispatch_started_count"],
        "doc_stage_skip_count": bucket["doc_stage_skip_count"],
    }


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = ["# Swarm Experiment Report", ""]
    if report.get("batch"):
        lines.append(f"Batch: `{report['batch']}`")
    if report["filter"].get("variant"):
        lines.append(f"Variant filter: `{report['filter']['variant']}`")
    lines.extend(
        [
            f"Runs: {summary['run_count']}; observations: {summary['observation_count']}; run events: {summary['run_event_count']}.",
            f"Controlled comparison ready: {'yes' if summary['controlled_comparison_ready'] else 'no'}.",
            "",
            "| variant | runs | null_phase_tags | base_shas | mean_tool_calls | p95_tool_calls | mean_wall_s | mean_cache_hit | repeated_reads | needs_context | needs_research | spec_mismatch | review_failures | stale_rejects | dispatch_started | doc_skips |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["by_variant"]:
        lines.append(
            "| {variant} | {runs} | {null_tags} | {base_shas} | {mean_tools} | {p95_tools} | {mean_wall} | {cache} | {reads} | {needs_context} | {needs_research} | {spec} | {review} | {stale} | {dispatch} | {doc_skips} |".format(
                variant=f"`{row['variant']}`",
                runs=row["run_count"],
                null_tags=row["null_phase_tag_count"],
                base_shas=row["base_sha_count"],
                mean_tools=_fmt(row["mean_tool_calls"]),
                p95_tools=_fmt(row["p95_tool_calls"]),
                mean_wall=_fmt(row["mean_wall_seconds"]),
                cache=_fmt(row["mean_cache_hit_ratio"]),
                reads=row["repeated_read_extra_count"],
                needs_context=row["needs_context_count"],
                needs_research=row["needs_research_count"],
                spec=row["spec_mismatch_count"],
                review=row["review_failure_count"],
                stale=row["prepare_stale_rejected_count"],
                dispatch=row["prepare_dispatch_started_count"],
                doc_skips=row["doc_stage_skip_count"],
            )
        )
    if summary["unknown_safety_metrics"]:
        lines.extend(["", "Unknown safety metrics: " + ", ".join(summary["unknown_safety_metrics"]) + "."])
    lines.extend(["", "Manual safety notes remain required in the batch manifest."])
    return "\n".join(lines) + "\n"


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "experiment-report",
        add_help=True,
        help="Join runs, observations, and run_events for controlled dogfood scorecards.",
    )
    parser.add_argument("--batch", default=None, help="Batch id to label the report output.")
    parser.add_argument("--variant", default=None, help="Filter to one SWARM_VARIANT label.")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Output format (default: markdown).",
    )


def run(ns: argparse.Namespace) -> int:
    report = aggregate_experiment_report(
        _iter_rows(resolve_ledger_path("runs")),
        _iter_rows(resolve_ledger_path("observations")),
        _iter_rows(resolve_ledger_path("run_events")),
        variant=getattr(ns, "variant", None),
        batch=getattr(ns, "batch", None),
    )
    if ns.format == "json":
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_markdown(report))
    return 0
