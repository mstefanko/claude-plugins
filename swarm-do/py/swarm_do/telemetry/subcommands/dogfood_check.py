"""Advisory dogfood gate for subagent-efficiency telemetry.

The check is intentionally read-only by default. It turns the current
experiment-report facts into a short HOLD/PROMOTE_CANDIDATE recommendation, but
never mutates rollout status; operators still make promotion decisions from the
batch manifest plus manual notes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from swarm_do.pipeline.run_state import append_run_event
from swarm_do.telemetry.registry import resolve_ledger_path, resolve_telemetry_dir
from swarm_do.telemetry.subcommands.experiment_report import (
    _iter_rows,
    aggregate_experiment_report,
)


REQUIRED_PREPARE_EVENTS = (
    "prepare_started",
    "prepare_lint_findings",
    "prepare_review_findings",
    "prepare_safe_fixes_accepted",
    "prepare_safe_fixes_proposed_unaccepted",
    "prepare_accepted",
    "prepare_dispatch_started",
)
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def build_dogfood_check_report(
    runs: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]],
    run_events: Iterable[dict[str, Any]],
    *,
    batch: str | None = None,
    variant: str | None = None,
    min_runs: int = 10,
    min_variants: int = 1,
    max_p95_tool_calls: int = 60,
    max_repeated_read_extra: int = 20,
    require_prepare_events: bool = True,
) -> dict[str, Any]:
    run_rows = list(runs)
    observation_rows = list(observations)
    event_rows = list(run_events)
    experiment = aggregate_experiment_report(
        run_rows,
        observation_rows,
        event_rows,
        batch=batch,
        variant=variant,
    )
    findings: list[dict[str, Any]] = []
    summary = experiment["summary"]

    if summary["run_count"] < min_runs:
        findings.append(
            _finding(
                "hold",
                "insufficient_runs",
                f"Only {summary['run_count']} run(s) found; need at least {min_runs}.",
            )
        )
    if summary["variant_count"] < min_variants:
        findings.append(
            _finding(
                "hold",
                "insufficient_variants",
                f"Only {summary['variant_count']} variant(s) found; need at least {min_variants}.",
            )
        )
    for metric in summary["unknown_safety_metrics"]:
        findings.append(_finding("hold", f"unknown_{metric}", f"Safety metric is unknown: {metric}."))

    selected_run_ids = _run_ids_for_filter(run_rows, variant)
    post_writer_count = sum(
        1
        for row in event_rows
        if row.get("event_type") == "post_writer_report"
        and _run_matches(row.get("run_id"), selected_run_ids)
    )
    writer_run_count = sum(1 for row in _filtered_runs(run_rows, variant) if row.get("role") == "agent-writer")
    if writer_run_count and post_writer_count == 0:
        findings.append(
            _finding(
                "hold",
                "missing_post_writer_report",
                "Writer runs exist but no post_writer_report event was recorded.",
            )
        )

    prepare_event_counts = Counter(
        str(row.get("event_type") or "")
        for row in event_rows
        if str(row.get("event_type") or "").startswith("prepare_")
        and _run_matches(row.get("run_id"), selected_run_ids)
    )
    if require_prepare_events and summary["run_count"] and not prepare_event_counts:
        findings.append(
            _finding(
                "hold",
                "missing_prepare_events",
                "No prepare lifecycle events were recorded for the selected evidence set.",
            )
        )
    if prepare_event_counts:
        for event_type in REQUIRED_PREPARE_EVENTS:
            if prepare_event_counts[event_type] == 0:
                findings.append(
                    _finding(
                        "hold",
                        "missing_prepare_event",
                        f"Prepare lifecycle event missing from this evidence set: {event_type}.",
                    )
                )
        if (
            prepare_event_counts["prepare_ready_for_acceptance"] == 0
            and prepare_event_counts["prepare_blocking_findings"] == 0
        ):
            findings.append(
                _finding(
                    "hold",
                    "missing_prepare_decision_event",
                    "Prepare lifecycle needs prepare_ready_for_acceptance or prepare_blocking_findings.",
                )
            )
    for row in event_rows:
        if row.get("event_type") != "prepare_stale_rejected":
            continue
        if not _run_matches(row.get("run_id"), selected_run_ids):
            continue
        details = row.get("details")
        has_reason = bool(row.get("reason")) or (
            isinstance(details, Mapping) and bool(details.get("stale_reasons"))
        )
        if not has_reason:
            findings.append(
                _finding(
                    "issue",
                    "stale_reject_without_reason",
                    f"prepare_stale_rejected event lacks an operator-visible reason for run {row.get('run_id')}.",
                )
            )

    for row in experiment["by_variant"]:
        if row["p95_tool_calls"] is not None and row["p95_tool_calls"] > max_p95_tool_calls:
            findings.append(
                _finding(
                    "issue",
                    "p95_tool_calls_high",
                    f"Variant {row['variant']} p95 tool calls {row['p95_tool_calls']} exceeds {max_p95_tool_calls}.",
                )
            )
        if row["repeated_read_extra_count"] > max_repeated_read_extra:
            findings.append(
                _finding(
                    "observe",
                    "repeated_reads_high",
                    f"Variant {row['variant']} has {row['repeated_read_extra_count']} repeated source reads.",
                )
            )
        for key in ("needs_context_count", "spec_mismatch_count", "review_failure_count", "prepare_stale_rejected_count"):
            if row[key]:
                findings.append(
                    _finding("issue", key, f"Variant {row['variant']} recorded {row[key]} {key}.")
                )
        if row["doc_stage_skip_count"] and post_writer_count == 0:
            findings.append(
                _finding(
                    "hold",
                    "docs_skip_without_post_writer",
                    "Docs were skipped without a deterministic post-writer report in evidence.",
                )
            )

    blocking = [item for item in findings if item["severity"] in {"hold", "issue"}]
    recommendation = "HOLD" if blocking else "PROMOTE_CANDIDATE"
    return {
        "schema_version": "dogfood_check.v1",
        "batch": batch,
        "filter": {"variant": variant},
        "recommendation": recommendation,
        "advisory_only": True,
        "manual_promotion_required": True,
        "thresholds": {
            "min_runs": min_runs,
            "min_variants": min_variants,
            "max_p95_tool_calls": max_p95_tool_calls,
            "max_repeated_read_extra": max_repeated_read_extra,
            "require_prepare_events": require_prepare_events,
        },
        "summary": {
            **summary,
            "post_writer_report_count": post_writer_count,
            "writer_run_count": writer_run_count,
            "finding_count": len(findings),
            "blocking_finding_count": len(blocking),
        },
        "findings": findings,
        "experiment_report": experiment,
        "next_actions": _next_actions(recommendation, batch),
    }


def _filtered_runs(rows: list[dict[str, Any]], variant: str | None) -> list[dict[str, Any]]:
    return [row for row in rows if variant is None or row.get("variant") == variant]


def _run_ids_for_filter(rows: list[dict[str, Any]], variant: str | None) -> set[str]:
    return {
        row["run_id"]
        for row in _filtered_runs(rows, variant)
        if isinstance(row.get("run_id"), str)
    }


def _run_matches(run_id: Any, run_ids: set[str]) -> bool:
    return isinstance(run_id, str) and run_id in run_ids


def _finding(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _next_actions(recommendation: str, batch: str | None) -> list[str]:
    target = f"docs/eval-batches/{batch}.md" if batch else "docs/eval-batches/<batch-id>.md"
    if recommendation == "PROMOTE_CANDIDATE":
        return [
            f"Review manual safety notes in {target}.",
            "Promote rollout stages manually only after the batch manifest is accepted.",
        ]
    return [
        f"Keep the stage at HOLD and update {target} with the blocking evidence.",
        "Tune thresholds only after a follow-up batch reproduces the signal.",
    ]


def _render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Swarm Dogfood Check",
        "",
        f"Recommendation: **{report['recommendation']}**",
        "Mode: advisory only; rollout status is not mutated.",
        "",
        f"Runs: {summary['run_count']}; variants: {summary['variant_count']}; observations: {summary['observation_count']}; run events: {summary['run_event_count']}.",
        f"Post-writer reports: {summary['post_writer_report_count']}; writer runs: {summary['writer_run_count']}.",
    ]
    if report.get("batch"):
        lines.insert(2, f"Batch: `{report['batch']}`")
    findings = report.get("findings") or []
    if findings:
        lines.extend(["", "Findings:"])
        for item in findings:
            lines.append(f"- `{item['severity']}` `{item['code']}`: {item['message']}")
    else:
        lines.extend(["", "Findings: none."])
    lines.extend(["", "Next actions:"])
    lines.extend(f"- {action}" for action in report.get("next_actions") or [])
    return "\n".join(lines) + "\n"


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "dogfood-check",
        add_help=True,
        help="Advisory HOLD/PROMOTE_CANDIDATE check from dogfood telemetry.",
    )
    parser.add_argument("--batch", default=None)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--min-runs", type=int, default=10)
    parser.add_argument("--min-variants", type=int, default=1)
    parser.add_argument("--max-p95-tool-calls", type=int, default=60)
    parser.add_argument("--max-repeated-read-extra", type=int, default=20)
    parser.add_argument("--no-require-prepare-events", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", help="Optional path to write the rendered report.")
    parser.add_argument("--append-run-event", action="store_true")
    parser.add_argument("--run-id", help="Run id for --append-run-event; defaults to latest matching run.")
    parser.add_argument("--source", default="dogfood-check")


def run(ns: argparse.Namespace) -> int:
    runs = list(_iter_rows(resolve_ledger_path("runs")))
    observations = list(_iter_rows(resolve_ledger_path("observations")))
    run_events = list(_iter_rows(resolve_ledger_path("run_events")))
    report = build_dogfood_check_report(
        runs,
        observations,
        run_events,
        batch=getattr(ns, "batch", None),
        variant=getattr(ns, "variant", None),
        min_runs=ns.min_runs,
        min_variants=ns.min_variants,
        max_p95_tool_calls=ns.max_p95_tool_calls,
        max_repeated_read_extra=ns.max_repeated_read_extra,
        require_prepare_events=not ns.no_require_prepare_events,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n" if ns.format == "json" else _render_markdown(report)
    if ns.output:
        target = Path(ns.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if ns.append_run_event:
        _append_check_event(ns, report, runs)
    return 0


def _append_check_event(ns: argparse.Namespace, report: Mapping[str, Any], runs: list[dict[str, Any]]) -> None:
    run_id = ns.run_id or _latest_run_id(runs, getattr(ns, "variant", None))
    if not isinstance(run_id, str) or not _ULID_RE.match(run_id):
        raise ValueError("--append-run-event requires a valid ULID run id")
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    append_run_event(
        resolve_telemetry_dir().parent,
        {
            "run_id": run_id,
            "event_type": "dogfood_check",
            "bd_epic_id": None,
            "phase_id": "dogfood-check",
            "work_unit_id": None,
            "child_bead_ids": None,
            "reason": str(report.get("recommendation")),
            "retry_count": None,
            "handoff_count": None,
            "integration_branch_head": None,
            "details": {
                "source": ns.source,
                "batch": report.get("batch"),
                "recommendation": report.get("recommendation"),
                "finding_count": summary.get("finding_count"),
                "blocking_finding_count": summary.get("blocking_finding_count"),
                "advisory_only": True,
            },
            "schema_ok": True,
        },
    )


def _latest_run_id(runs: list[dict[str, Any]], variant: str | None) -> str | None:
    for row in reversed(runs):
        if variant is not None and row.get("variant") != variant:
            continue
        value = row.get("run_id")
        if isinstance(value, str):
            return value
    return None
