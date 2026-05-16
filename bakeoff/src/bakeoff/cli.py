from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from bakeoff import __version__
from bakeoff.io import copy_file_atomic, write_json_atomic, write_text_atomic
from bakeoff.manifest import MANIFEST_SCHEMA_VERSION, REQUIRED_ARTIFACTS, manifest_row_for_ls, write_run_manifest
from bakeoff.providers import (
    DEFAULT_MODEL_IDS,
    anonymized_worker_output,
    build_judge_prompt,
    build_participant_argv,
    build_scope_execution,
    detect_scope_capabilities,
    ScopeEnforcementError,
    build_triage_prompt,
    build_worker_prompt,
    version_argv,
)
from bakeoff.report import render_report
from bakeoff.review_context import (
    ReviewContextOptions,
    apply_review_context,
    build_review_context,
    format_review_context_summary,
    render_review_context_markdown,
    review_context_metadata,
)
from bakeoff.runner import provider_succeeded, run_provider, run_provider_with_format_retry
from bakeoff.triage import (
    build_finding_index,
    check_citations,
    collect_citation_text,
    compute_input_hashes,
    extract_citations_from_text,
    facet_id,
    render_triage_markdown,
    resolve_citation_cwd,
    select_triage_source_findings,
    should_auto_triage,
    should_recommend_triage,
    summarize_source_finding_filter,
    triage_state,
    triage_state_detail,
)
from bakeoff.work_order import (
    INIT_KINDS,
    MODE_EFFORT_DEFAULTS,
    ValidationError,
    init_template,
    load_work_order,
    review_template,
    validate_analyze_judge_result,
    validate_compare_judge_result,
    validate_gather_judge_result,
    validate_triage_result,
    validate_worker_result,
)

ORIENTATION = """\
bakeoff - run the same research task across multiple agents, then judge.

Four starts. Pick one based on what you want:
  gather   coverage research
  compare  defended pick
  analyze  thorough explanation
  review   code-review recipe

Get started:
  bakeoff init gather
  bakeoff validate gather.work-order.json
  bakeoff research gather.work-order.json

Provider CLIs required on PATH: `claude`, `codex`.
Run `bakeoff doctor` to check.
"""

EXIT_CODE_EPILOG = """\
Exit codes:
  0  success
  1  generic runtime or verification failure
  2  usage, config, validation, or missing-input error
  3  completed run with unresolved judge disagreement
"""

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUMMARY_OK_STATUSES = {"ok", "ok_after_format_retry"}


def _note(message: str) -> None:
    print(f"note: {message}", file=sys.stderr)


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bakeoff",
        description="Tiny research bakeoff harness.",
        epilog=EXIT_CODE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command")

    init = subcommands.add_parser("init", help="write an example work order")
    init.add_argument("type", choices=INIT_KINDS)
    init.add_argument("--force", action="store_true", help="overwrite an existing template")

    validate = subcommands.add_parser("validate", help="validate and dry-run a work order")
    validate.add_argument("work_order")

    research = subcommands.add_parser("research", help="run a research bakeoff")
    research.add_argument("work_order")
    research.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    research.add_argument("--run-id", help="explicit run id")
    research.add_argument("--force", action="store_true", help="replace an existing run directory")
    research.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")
    research.add_argument("--no-triage", action="store_true", help="skip automatic triage for code-review runs")
    research.add_argument("--base", help="capture git review context against REF (default for review context: HEAD)")
    research.add_argument("--diff", action="store_true", help="include a bounded unified patch in generated review context")
    research.add_argument("--changed-files", action="store_true", help="include changed-file context against the base ref")
    research.add_argument("--json", action="store_true", help="emit a final JSON summary")

    rerun = subcommands.add_parser("rerun", help="replay a previous work order with a fresh run id")
    rerun.add_argument("source_run_id")
    rerun.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    rerun.add_argument("--run-id", dest="new_run_id", help="explicit new run id")
    rerun.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")
    rerun.add_argument("--no-triage", action="store_true", help="skip automatic triage for code-review runs")

    triage = subcommands.add_parser("triage", help="triage a completed bakeoff report")
    triage.add_argument("run_id")
    triage.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    triage.add_argument("--force", action="store_true", help="replace an existing triage directory")
    triage.add_argument("--dry-run", action="store_true", help="build triage inputs without invoking a provider")
    triage.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")
    triage.add_argument("--json", action="store_true", help="emit a final JSON summary")

    runs = subcommands.add_parser("runs", help="inspect run ledgers")
    runs_subcommands = runs.add_subparsers(dest="runs_command", required=True)
    runs_verify = runs_subcommands.add_parser("verify", help="verify one run ledger")
    runs_verify.add_argument("run_id")
    runs_verify.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    runs_verify.add_argument("--json", action="store_true", help="emit a parseable JSON verification report")

    ls_cmd = subcommands.add_parser("ls", help="list past runs")
    ls_cmd.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    ls_cmd.add_argument("--json", action="store_true", help="emit a manifest-backed JSON listing")
    ls_cmd.add_argument("--facet", help="filter by facet id")
    ls_cmd.add_argument("--triage-state", choices=("no", "dry_run", "yes", "stale"), help="filter by triage state")

    show = subcommands.add_parser("show", help="print a run report")
    show.add_argument("run_id")
    show.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    show.add_argument("--judge", action="store_true", help="show judge output")
    show.add_argument("--judge-prompt", action="store_true", help="show judge prompt")
    show.add_argument("--triage", action="store_true", help="show triage output")

    doctor = subcommands.add_parser("doctor", help="check provider CLIs, auth, and local readiness")
    doctor.add_argument("--skip-auth-probe", action="store_true", help="skip spendful provider auth probes")
    doctor.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")
    doctor.add_argument("--json", action="store_true", help="emit a parseable JSON readiness report")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        print(ORIENTATION)
        return 0

    parser = build_parser()
    args = parser.parse_args(args_list)
    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "validate":
            return cmd_validate(args)
        if args.command == "research":
            return asyncio.run(cmd_research(args))
        if args.command == "rerun":
            return asyncio.run(cmd_rerun(args))
        if args.command == "triage":
            return asyncio.run(cmd_triage(args))
        if args.command == "runs":
            if args.runs_command == "verify":
                return cmd_runs_verify(args)
        if args.command == "ls":
            return cmd_ls(args)
        if args.command == "show":
            return cmd_show(args)
        if args.command == "doctor":
            return asyncio.run(cmd_doctor(args))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(f"{args.type}.work-order.json")
    if path.exists() and not args.force:
        raise ValidationError(f"{path} already exists; use --force to overwrite")
    if args.type == "review":
        write_text_atomic(path, review_template())
        defaults = MODE_EFFORT_DEFAULTS["gather"]
        print(f"wrote {path}")
        print("recipe: review (mode gather)")
        print(f"effort defaults: workers={defaults['worker']}, judge={defaults['judge']}")
        return 0
    write_text_atomic(path, init_template(args.type))
    print(f"wrote {path}")
    defaults = MODE_EFFORT_DEFAULTS[args.type]
    print(f"effort defaults: workers={defaults['worker']}, judge={defaults['judge']}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    work_order = load_work_order(args.work_order)
    print_validation_summary(work_order)
    return 0


def bakeoff_show_command(run_id: str, out_dir: Path, flag: str | None = None) -> str:
    parts = ["bakeoff", "show", shlex.quote(run_id)]
    if flag:
        parts.append(flag)
    return " ".join(parts) + out_dir_suffix(out_dir)


def bakeoff_triage_command(run_id: str, out_dir: Path, *, force: bool = False) -> str:
    parts = ["bakeoff", "triage", shlex.quote(run_id)]
    if force:
        parts.append("--force")
    return " ".join(parts) + out_dir_suffix(out_dir)


def out_dir_suffix(out_dir: Path) -> str:
    if out_dir == Path("runs"):
        return ""
    return f" --out {shlex.quote(str(out_dir))}"


def codex_final_message_path(participant: dict[str, Any], path: Path) -> Path | None:
    if participant.get("backend") != "codex":
        return None
    return path


def format_stale_inputs(stale_inputs: list[str]) -> str:
    if not stale_inputs:
        return ""
    return f" ({', '.join(stale_inputs)} changed)"


def print_missing_judge_artifacts(run_dir: Path, artifact_label: str) -> None:
    decision = read_json(run_dir / "decision.json") or {}
    decision_kind = decision.get("decision_kind", "?")
    judge_ran = str(decision.get("judge_ran", False)).lower()
    print(f"no {artifact_label} artifacts for {run_dir.name} (decision: {decision_kind}, judge_ran: {judge_ran})")


async def cmd_research(args: argparse.Namespace) -> int:
    return await run_research(
        Path(args.work_order),
        out_dir=Path(args.out),
        run_id=args.run_id,
        force=args.force,
        quiet=args.quiet,
        json_output=args.json,
        no_triage=args.no_triage,
        review_context_options=ReviewContextOptions(
            base_ref=args.base,
            include_patch=args.diff,
            include_changed_files=args.changed_files,
        ),
    )


async def cmd_rerun(args: argparse.Namespace) -> int:
    source_run = resolve_run_dir(Path(args.out), args.source_run_id)
    work_order_path = source_run / "work-order.json"
    if not work_order_path.exists():
        raise ValidationError(f"{source_run} has no work-order.json")
    return await run_research(
        work_order_path,
        out_dir=Path(args.out),
        run_id=args.new_run_id,
        force=False,
        quiet=args.quiet,
        no_triage=args.no_triage,
        replay_source_run_dir=source_run,
    )


def cmd_ls(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if not out_dir.exists():
        if args.json:
            print(json.dumps({"schema_version": 1, "out_dir": str(out_dir), "runs": []}, indent=2, sort_keys=True))
            return 0
        print(f"no runs found under {out_dir}")
        return 0
    rows = [
        manifest_row_for_ls(run_dir)
        for run_dir in sorted((path for path in out_dir.iterdir() if path.is_dir()), reverse=True)
        if run_dir.name != "latest"
    ]
    rows = filter_ls_rows(rows, facet=args.facet, triage_state=args.triage_state)
    if args.json:
        print(json.dumps({"schema_version": 1, "out_dir": str(out_dir), "runs": rows}, indent=2, sort_keys=True))
        return 0
    print("run_id\ttype\tfacet\tdecision\ttriage\tfinished_at")
    for row in rows:
        facet_label = row.get("facet_id") or "-"
        print(
            f"{row.get('run_id')}\t{row.get('type') or '?'}\t{facet_label}\t{row.get('decision_kind') or '?'}\t"
            f"triage:{row.get('triage_state') or 'no'}\t{row.get('finished_at') or '-'}"
        )
    return 0


def filter_ls_rows(rows: list[dict[str, Any]], *, facet: str | None, triage_state: str | None) -> list[dict[str, Any]]:
    filtered = rows
    if facet is not None:
        filtered = [row for row in filtered if row.get("facet_id") == facet]
    if triage_state is not None:
        filtered = [row for row in filtered if row.get("triage_state") == triage_state]
    return filtered


def print_json_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, indent=2, sort_keys=False))


def command_status(exit_code: int) -> str:
    if exit_code == 0:
        return "ok"
    if exit_code == 3:
        return "judge_disagreement"
    return "failed"


def compact_status(raw_status: Any) -> str:
    raw = str(raw_status) if raw_status is not None else "missing_status"
    return raw if raw in SUMMARY_OK_STATUSES else "failed"


def provider_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    raw_status = status.get("status")
    summary: dict[str, Any] = {"status": compact_status(raw_status)}
    if raw_status is not None:
        summary["raw_status"] = raw_status
    for key in ("wall_seconds", "output_bytes", "stdout_bytes", "stderr_bytes"):
        if key in status:
            summary[key] = status[key]
    return summary


def judge_json_summary(run_dir: Path, decision: dict[str, Any]) -> dict[str, Any]:
    if not decision.get("judge_ran"):
        return {"status": "not_run", "raw_status": "not_run"}
    judge_dir = run_dir / "judge"
    status_paths = sorted(judge_dir.glob("status*.json"))
    if not status_paths:
        return {"status": "failed", "raw_status": "missing_status"}
    passes = {}
    raw_statuses = []
    for path in status_paths:
        status = read_json(path)
        raw_status = status.get("status") if isinstance(status, dict) else "invalid_status"
        label = path.stem.removeprefix("status-")
        if label == "status":
            label = "gather"
        passes[label] = raw_status
        raw_statuses.append(raw_status)
    if all(raw_status in SUMMARY_OK_STATUSES for raw_status in raw_statuses):
        status = "ok_after_format_retry" if "ok_after_format_retry" in raw_statuses else "ok"
    else:
        status = "failed"
    summary: dict[str, Any] = {
        "status": status,
        "raw_status": raw_statuses[0] if len(set(raw_statuses)) == 1 else ", ".join(str(value) for value in raw_statuses),
    }
    if len(passes) > 1:
        summary["passes"] = passes
    return summary


def research_artifact_paths(run_dir: Path) -> dict[str, str]:
    candidates = {
        "work_order": "work-order.json",
        "decision": "decision.json",
        "meta": "meta.json",
        "manifest": "manifest.json",
        "report": "report.md",
        "source_work_order": "source-work-order.json",
        "review_context_md": "review-context.md",
        "review_context_json": "review-context.json",
    }
    return {key: str(run_dir / relative) for key, relative in candidates.items() if (run_dir / relative).exists()}


def triage_artifact_paths(run_dir: Path) -> dict[str, str]:
    triage_dir = run_dir / "triage"
    candidates = {
        "prompt": "prompt.txt",
        "status": "status.json",
        "citation_checks": "citation_checks.json",
        "source_finding_filter": "source_finding_filter.json",
        "finding_index": "finding_index.json",
        "final": "final.json",
        "triage": "triage.md",
    }
    return {key: str(triage_dir / relative) for key, relative in candidates.items() if (triage_dir / relative).exists()}


def research_triage_summary(
    run_dir: Path,
    *,
    auto_started: bool,
    triage_exit_code: int | None,
) -> dict[str, Any]:
    state, stale_inputs = triage_state_detail(run_dir)
    status_data = read_json(run_dir / "triage" / "status.json")
    raw_status = status_data.get("status") if isinstance(status_data, dict) else None
    status = None if raw_status is None else ("dry_run" if raw_status == "dry_run" else compact_status(raw_status))
    summary: dict[str, Any] = {
        "auto_started": auto_started,
        "state": state,
        "status": status,
        "exit_code": triage_exit_code,
        "artifacts": triage_artifact_paths(run_dir),
    }
    if raw_status is not None and raw_status != status:
        summary["raw_status"] = raw_status
    if stale_inputs:
        summary["stale_inputs"] = stale_inputs
    return summary


def build_research_json_summary(
    run_dir: Path,
    run_id: str,
    out_dir: Path,
    decision: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    *,
    exit_code: int,
    auto_triage_started: bool,
    triage_exit_code: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command": "research",
        "status": command_status(exit_code),
        "exit_code": exit_code,
        "warnings": [],
        "run_id": run_id,
        "run_dir": str(run_dir),
        "decision_kind": decision.get("decision_kind"),
        "canonical_winner": decision.get("canonical_winner"),
        "judge_ran": bool(decision.get("judge_ran")),
        "providers": {
            provider_id: provider_status_summary(result)
            for provider_id, result in worker_results.items()
        },
        "judge": judge_json_summary(run_dir, decision),
        "triage": research_triage_summary(
            run_dir,
            auto_started=auto_triage_started,
            triage_exit_code=triage_exit_code,
        ),
        "artifacts": research_artifact_paths(run_dir),
        "next": bakeoff_show_command(run_id, out_dir),
    }


def build_triage_json_summary(
    run_dir: Path,
    run_id: str,
    out_dir: Path,
    *,
    exit_code: int,
    dry_run: bool,
) -> dict[str, Any]:
    triage_dir = run_dir / "triage"
    status_data = read_json(triage_dir / "status.json")
    status_data = status_data if isinstance(status_data, dict) else {}
    raw_status = status_data.get("status")
    filter_summary = status_data.get("source_finding_filter")
    if not isinstance(filter_summary, dict):
        final = read_json(triage_dir / "final.json")
        filter_summary = final.get("source_finding_filter") if isinstance(final, dict) else {}
    if not isinstance(filter_summary, dict):
        filter_summary = {}
    triage_status = "dry_run" if raw_status == "dry_run" else compact_status(raw_status)
    if dry_run:
        next_command = bakeoff_triage_command(run_id, out_dir, force=True)
    elif exit_code == 0:
        next_command = bakeoff_show_command(run_id, out_dir, "--triage")
    else:
        next_command = bakeoff_triage_command(run_id, out_dir, force=True)
    return {
        "schema_version": 1,
        "command": "triage",
        "status": command_status(exit_code),
        "exit_code": exit_code,
        "warnings": [],
        "run_id": run_id,
        "run_dir": str(run_dir),
        "dry_run": dry_run,
        "triage": {
            "state": triage_state(run_dir),
            "status": triage_status,
            "raw_status": raw_status,
            "selected_findings": filter_summary.get("included", 0),
            "skipped_non_actionable": filter_summary.get("skipped_non_actionable", 0),
            "skipped_out_of_facet": filter_summary.get("skipped_out_of_facet", 0),
        },
        "artifacts": triage_artifact_paths(run_dir),
        "next": next_command,
    }


def copy_replay_context_artifacts(source_run_dir: Path, run_dir: Path) -> None:
    for name in ("source-work-order.json", "review-context.md", "review-context.json"):
        source = source_run_dir / name
        if source.exists():
            copy_file_atomic(source, run_dir / name)


def cmd_show(args: argparse.Namespace) -> int:
    if sum(1 for value in (args.judge, args.judge_prompt, args.triage) if value) > 1:
        raise ValidationError("show artifact flags are mutually exclusive: --judge, --judge-prompt, --triage")
    out_dir = Path(args.out)
    run_dir = resolve_run_dir(out_dir, args.run_id)
    if args.triage:
        triage_report = run_dir / "triage" / "triage.md"
        state, stale_inputs = triage_state_detail(run_dir)
        if state == "stale":
            raise ValidationError(
                f"triage is stale for {run_dir.name}{format_stale_inputs(stale_inputs)}; "
                f"run {bakeoff_triage_command(args.run_id, out_dir, force=True)}"
            )
        if state == "dry_run":
            raise ValidationError(
                f"triage has only a dry run for {run_dir.name}; run "
                f"{bakeoff_triage_command(args.run_id, out_dir, force=True)}"
            )
        if state != "yes" or not triage_report.exists():
            raise ValidationError(
                f"triage has not been run for {run_dir.name}; run {bakeoff_triage_command(args.run_id, out_dir)}"
            )
        print(triage_report.read_text(encoding="utf-8"), end="")
        return 0
    if args.judge_prompt:
        paths = sorted((run_dir / "judge").glob("prompt*.txt"))
        if not paths:
            print_missing_judge_artifacts(run_dir, "judge prompt")
            return 0
        for path in paths:
            print(f"===== {path.relative_to(run_dir)} =====")
            print(path.read_text(encoding="utf-8"))
        return 0
    if args.judge:
        paths = sorted((run_dir / "judge").glob("result*.json"))
        if not paths:
            print_missing_judge_artifacts(run_dir, "judge result")
            return 0
        for path in paths:
            print(f"===== {path.relative_to(run_dir)} =====")
            print(path.read_text(encoding="utf-8"))
        return 0
    report = run_dir / "report.md"
    if not report.exists():
        raise ValidationError(f"{run_dir} has no report.md")
    report_text = report.read_text(encoding="utf-8")
    print(report_text, end="")
    state, stale_inputs = triage_state_detail(run_dir)
    if state == "yes":
        print(f"\ntriage available: {bakeoff_show_command(args.run_id, out_dir, '--triage')}")
        return 0
    if state == "stale":
        print(f"\ntriage stale{format_stale_inputs(stale_inputs)}: {bakeoff_triage_command(args.run_id, out_dir, force=True)}")
        return 0
    if state == "dry_run":
        print(f"\ntriage dry run only: {bakeoff_triage_command(args.run_id, out_dir, force=True)}")
        return 0
    try:
        work_order_like = load_work_order(run_dir / "work-order.json")
    except ValidationError:
        meta = read_json(run_dir / "meta.json") or {}
        work_order_like = {"type": meta.get("type"), "facet": meta.get("facet")}
    recommendation = should_recommend_triage(work_order_like, read_json(run_dir / "decision.json") or {}, report_text)
    if recommendation:
        print(f"\ntriage not yet run: {bakeoff_triage_command(args.run_id, out_dir)}")
    return 0


async def cmd_triage(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    return await run_triage(
        resolve_run_dir(out_dir, args.run_id),
        force=args.force,
        dry_run=args.dry_run,
        quiet=args.quiet,
        json_output=args.json,
        out_dir=out_dir,
        display_run_id=args.run_id,
    )


def cmd_runs_verify(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    validate_verify_run_id(args.run_id)
    run_dir = resolve_run_dir(out_dir, args.run_id)
    if is_path_like_run_id(args.run_id):
        ensure_verify_path_inside_out(out_dir, run_dir)
    display_out_dir = output_dir_for_resolved_run(out_dir, run_dir)
    result = verify_run_ledger(run_dir, display_out_dir=display_out_dir)
    if args.json:
        print_json_summary(result)
    else:
        print_runs_verify_human(result)
    return int(result["exit_code"])


def validate_verify_run_id(run_id: str) -> None:
    if run_id == "latest":
        return
    if is_path_like_run_id(run_id):
        parts = Path(run_id).parts
        if "." in parts or ".." in parts:
            raise ValidationError("run-id path must not contain . or .. segments")
        return
    validate_run_id(run_id)


def is_path_like_run_id(run_id: str) -> bool:
    return os.sep in run_id or bool(os.altsep and os.altsep in run_id)


def ensure_verify_path_inside_out(out_dir: Path, run_dir: Path) -> None:
    out_resolved = out_dir.resolve()
    run_resolved = run_dir.resolve()
    if out_resolved not in (run_resolved, *run_resolved.parents):
        raise ValidationError("run-id path must stay inside --out")


def output_dir_for_resolved_run(out_dir: Path, run_dir: Path) -> Path:
    try:
        if out_dir.resolve() == run_dir.parent.resolve():
            return out_dir
    except OSError:
        pass
    return run_dir.parent


def verify_run_ledger(run_dir: Path, *, display_out_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    problems: list[str] = []
    manifest: dict[str, Any] | None = None
    manifest_status = "ok"
    if not manifest_path.exists():
        manifest_status = "failed"
        problems.append(f"missing manifest: {manifest_path}")
    else:
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(loaded_manifest, dict):
                raise ValidationError("manifest must be a JSON object")
            manifest = loaded_manifest
            if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
                manifest_status = "failed"
                problems.append(f"invalid manifest schema_version: {manifest.get('schema_version')!r}")
            if manifest.get("run_id") != run_dir.name:
                manifest_status = "failed"
                problems.append(f"manifest run_id {manifest.get('run_id')!r} does not match {run_dir.name!r}")
        except (json.JSONDecodeError, OSError, ValidationError) as exc:
            manifest_status = "failed"
            problems.append(f"invalid manifest: {exc}")

    missing_required = [
        relative
        for relative in REQUIRED_ARTIFACTS
        if not (run_dir / relative).exists() or not (run_dir / relative).is_file()
    ]
    for relative in missing_required:
        problems.append(f"missing artifact: {run_dir / relative}")

    fingerprint_mismatches: list[dict[str, str]] = []
    checked_count = 0
    fingerprints_status = "ok"
    if isinstance(manifest, dict):
        fingerprints = manifest.get("artifact_fingerprints")
        if not isinstance(fingerprints, dict):
            fingerprints_status = "failed"
            problems.append("invalid manifest: artifact_fingerprints must be an object")
        else:
            for relative, expected in fingerprints.items():
                checked_count += 1
                mismatch_reason = verify_fingerprint_entry(run_dir, relative, expected)
                if mismatch_reason:
                    fingerprints_status = "failed"
                    fingerprint_mismatches.append({"path": str(relative), "reason": mismatch_reason})
                    if mismatch_reason == "missing":
                        problems.append(f"missing artifact: {run_dir / str(relative)}")
                    else:
                        problems.append(f"fingerprint mismatch: {run_dir / str(relative)}")
    elif manifest_status == "failed":
        fingerprints_status = "failed"

    if missing_required:
        required_status = "failed"
    else:
        required_status = "ok"
    state, stale_inputs = triage_state_detail(run_dir)
    exit_code = 1 if problems else 0
    next_command = runs_verify_next(run_dir, display_out_dir, exit_code=exit_code, triage_state_value=state)
    return {
        "schema_version": 1,
        "command": "runs verify",
        "status": command_status(exit_code),
        "exit_code": exit_code,
        "warnings": [],
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "manifest": {"status": manifest_status, "path": str(manifest_path)},
        "required_artifacts": {
            "status": required_status,
            "checked": list(REQUIRED_ARTIFACTS),
            "missing": missing_required,
        },
        "fingerprints": {
            "status": fingerprints_status,
            "checked_count": checked_count,
            "mismatches": fingerprint_mismatches,
        },
        "triage": {"state": state, "stale_inputs": stale_inputs},
        "problems": problems,
        "next": next_command,
    }


def verify_fingerprint_entry(run_dir: Path, relative: Any, expected: Any) -> str | None:
    if not isinstance(relative, str) or not isinstance(expected, dict):
        return "invalid"
    path = run_dir / relative
    if not path.exists() or not path.is_file():
        return "missing"
    current_size = path.stat().st_size
    current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected.get("size_bytes") != current_size or expected.get("sha256") != current_sha:
        return "sha256_or_size"
    return None


def runs_verify_next(run_dir: Path, out_dir: Path, *, exit_code: int, triage_state_value: str) -> str:
    run_id = run_dir.name
    if exit_code == 0:
        if triage_state_value == "stale":
            return bakeoff_triage_command(run_id, out_dir, force=True)
        if triage_state_value == "yes":
            return bakeoff_show_command(run_id, out_dir, "--triage")
        return bakeoff_show_command(run_id, out_dir)
    if (run_dir / "work-order.json").exists():
        return bakeoff_rerun_command(run_id, out_dir)
    return "restore the listed artifacts or rerun the original work order"


def bakeoff_rerun_command(run_id: str, out_dir: Path) -> str:
    return f"bakeoff rerun {shlex.quote(run_id)}" + out_dir_suffix(out_dir)


def print_runs_verify_human(result: dict[str, Any]) -> None:
    fingerprints = result["fingerprints"]
    checked_count = fingerprints["checked_count"]
    triage = result["triage"]
    stale_inputs = triage.get("stale_inputs") or []
    print(f"run verify: {result['run_id']}")
    print(f"  run dir: {result['run_dir']}")
    print(f"  manifest: {result['manifest']['status']}")
    print(f"  required artifacts: {result['required_artifacts']['status']}")
    print(f"  fingerprints: {fingerprints['status']} ({checked_count} checked)")
    print(f"  triage: {triage['state']}{format_stale_inputs(stale_inputs)}")
    if result["problems"]:
        print("problems:")
        for problem in result["problems"]:
            print(f"  - {problem}")
    print(f"next: {result['next']}")


async def cmd_doctor(args: argparse.Namespace) -> int:
    failed = False
    report: dict[str, Any] = {
        "command": "doctor",
        "status": "ok",
        "tools": {},
        "defaults": DEFAULT_MODEL_IDS,
        "scope_policy": {
            "default_enforcement": "best_effort",
            "status_artifacts": ["provider status.json", "meta.json"],
        },
        "scope_capabilities": {},
        "auth_probes": {},
        "warnings": [],
    }
    for tool in ("claude", "codex", "git"):
        path = shutil.which(tool)
        if path is None:
            report["tools"][tool] = {"ok": False, "path": None, "version": None}
            failed = True
            continue
        version = tool_version(tool)
        report["tools"][tool] = {"ok": True, "path": path, "version": version}

    for backend in ("claude", "codex"):
        report["scope_capabilities"][backend] = detect_scope_capabilities(backend)
        if not report["scope_capabilities"][backend].get("available"):
            failed = True

    writable, writable_detail = check_cwd_writable()
    report["cwd_writable"] = {"ok": writable, "detail": writable_detail, "cwd": str(Path.cwd())}
    failed = failed or not writable
    report["bias"] = (
        "Default judge is claude/opus alongside claude/sonnet workers. "
        "Position-swap is the primary bias mitigation; same-family bias is an accepted v1 risk."
    )

    if not args.json:
        print("bakeoff doctor")
        for tool in ("claude", "codex", "git"):
            tool_status = report["tools"][tool]
            if not tool_status["ok"]:
                print(f"- {tool}: missing")
            else:
                print(f"- {tool}: {tool_status['path']} ({tool_status['version']})")
        print("- defaults:")
        for key, value in DEFAULT_MODEL_IDS.items():
            print(f"  {key}: {value}")
        print("- scope policy: best_effort by default; provider status records enforcement and advisory fallback.")
        print("- scope capabilities:")
        for backend in ("claude", "codex"):
            caps = report["scope_capabilities"][backend]
            if not caps.get("available"):
                print(f"  {backend}: unavailable ({caps.get('probe_error', 'probe failed')})")
                continue
            supported = [name for name, ok in caps.get("supports", {}).items() if ok]
            missing = [name for name, ok in caps.get("supports", {}).items() if not ok]
            print(f"  {backend}: supports {', '.join(supported) if supported else 'none'}")
            if missing:
                print(f"    missing: {', '.join(missing)}")
        print(f"- cwd writable: {'ok' if writable else 'failed'} ({writable_detail})")
        print(f"- bias: {report['bias']}")

    if not args.skip_auth_probe and not failed:
        budgets = {"wall_clock_seconds": 30, "max_output_bytes": 10000}
        prompt = (
            "Auth probe. Reply exactly with "
            '<final_json>{"status":"complete","claims":[],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>'
        )
        participants = [
            {"backend": "claude", "model": DEFAULT_MODEL_IDS["claude_sonnet"], "effort": "low"},
            {"backend": "codex", "model": DEFAULT_MODEL_IDS["codex"], "effort": "low"},
        ]
        for participant in participants:
            backend = participant["backend"]
            result = await run_provider(
                build_participant_argv(participant, cwd=Path.cwd()),
                prompt,
                budgets,
                on_tick=make_tick_printer(f"{backend}:auth", quiet=args.quiet),
            )
            probe_status = auth_probe_status(result)
            report["auth_probes"][backend] = probe_status
            if not args.json:
                print(f"- {backend} auth probe: {result['status']}")
            if result["status"] != "ok":
                warning = f"{backend} auth probe failed with {result['status']}"
                if probe_status.get("reason"):
                    warning += f": {probe_status['reason']}"
                report["warnings"].append(warning)
                if not args.json:
                    _warn(warning)
    report["status"] = "failed" if failed else "ok"
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failed else 0


async def run_research(
    work_order_path: Path,
    *,
    out_dir: Path,
    run_id: str | None,
    force: bool,
    quiet: bool = False,
    json_output: bool = False,
    no_triage: bool = False,
    review_context_options: ReviewContextOptions | None = None,
    replay_source_run_dir: Path | None = None,
) -> int:
    human_output = not json_output
    effective_quiet = quiet or json_output
    work_order = load_work_order(work_order_path)
    source_work_order_text = work_order_path.read_text(encoding="utf-8")
    actual_run_id = run_id or make_run_id()
    validate_run_id(actual_run_id)
    run_dir = out_dir / actual_run_id
    if run_dir.exists():
        if not force:
            raise ValidationError(f"{run_dir} already exists; use --force to replace")
        ensure_child_path(out_dir, run_dir)

    started_at = utc_now()
    review_context = None
    if review_context_options is not None and review_context_options.enabled:
        review_context = build_review_context(review_context_options, Path.cwd(), started_at)
        if facet_id(work_order) != "code-review":
            _note("generated review context was requested for a non-code-review facet")
        work_order = apply_review_context(work_order, review_context)

    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    update_latest_symlink(out_dir, actual_run_id)

    if review_context is not None:
        write_text_atomic(run_dir / "source-work-order.json", source_work_order_text)
        write_json_atomic(run_dir / "work-order.json", work_order)
        write_text_atomic(run_dir / "review-context.md", render_review_context_markdown(review_context))
        write_json_atomic(run_dir / "review-context.json", review_context_metadata(review_context))
    else:
        write_text_atomic(run_dir / "work-order.json", source_work_order_text)
        if replay_source_run_dir is not None:
            copy_replay_context_artifacts(replay_source_run_dir, run_dir)
    if human_output:
        print_run_header(work_order, run_dir, actual_run_id)
    if review_context is not None:
        if human_output:
            print(format_review_context_summary(review_context))
    elif (run_dir / "review-context.md").exists():
        if human_output:
            print(f"review context: replayed from {replay_source_run_dir}")

    worker_results = await run_workers(work_order, run_dir, quiet=effective_quiet, human_output=human_output)
    ok_results = {pid: result for pid, result in worker_results.items() if provider_succeeded(result)}

    judge_results: dict[str, dict[str, Any]] = {}
    exit_code = 0
    if len(ok_results) == 0:
        decision = decision_base(work_order, worker_results, run_dir)
        decision.update(
            {
                "decision_kind": "both_failed",
                "judge_ran": False,
                "canonical_winner": None,
                "caveats": ["both providers failed; judge skipped"],
            }
        )
        exit_code = 1
    elif len(ok_results) == 1:
        survivor = next(iter(ok_results))
        decision = decision_base(work_order, worker_results, run_dir)
        failed = [pid for pid in worker_results if pid != survivor][0]
        decision.update(
            {
                "decision_kind": "single_provider_only",
                "judge_ran": False,
                "canonical_winner": survivor,
                "caveats": [single_provider_caveat(work_order["type"], survivor, failed, worker_results[failed]["status"])],
            }
        )
    else:
        decision, judge_results, exit_code = await run_judge_phase(
            work_order,
            worker_results,
            run_dir,
            quiet=effective_quiet,
            human_output=human_output,
        )

    write_json(run_dir / "decision.json", decision)
    report = render_report(work_order, decision, worker_results, judge_results=judge_results)
    write_text_atomic(run_dir / "report.md", report)
    write_meta(run_dir, work_order, actual_run_id, started_at, worker_results=worker_results)
    write_run_manifest(run_dir)
    if human_output:
        if (run_dir / "review-context.md").exists():
            print(f"context-md: {run_dir / 'review-context.md'}")
        print(f"manifest: {run_dir / 'manifest.json'}")
        print(f"report: {run_dir / 'report.md'}")
        print(f"next:   {bakeoff_show_command(actual_run_id, out_dir)}")
    auto_triage_reason = None if no_triage or exit_code != 0 else should_auto_triage(work_order, decision)
    auto_triage_started = False
    triage_exit_code = None
    if auto_triage_reason:
        auto_triage_started = True
        if human_output:
            print(f"auto-triage starting: {auto_triage_reason}")
        triage_exit_code = await run_triage(
            run_dir,
            force=False,
            dry_run=False,
            quiet=effective_quiet,
            json_output=False,
            human_output=human_output,
            out_dir=out_dir,
            display_run_id=actual_run_id,
        )
        if triage_exit_code != 0:
            exit_code = 1
    if not no_triage and not auto_triage_started:
        recommendation = should_recommend_triage(work_order, decision, report)
        if recommendation and human_output:
            print(f"recommended: {bakeoff_triage_command(actual_run_id, out_dir)}  ({recommendation})")
    if json_output:
        print_json_summary(
            build_research_json_summary(
                run_dir,
                actual_run_id,
                out_dir,
                decision,
                worker_results,
                exit_code=exit_code,
                auto_triage_started=auto_triage_started,
                triage_exit_code=triage_exit_code,
            )
        )
    return exit_code


async def run_triage(
    run_dir: Path,
    *,
    force: bool,
    dry_run: bool,
    quiet: bool = False,
    json_output: bool = False,
    human_output: bool | None = None,
    out_dir: Path | None = None,
    display_run_id: str | None = None,
) -> int:
    if human_output is None:
        human_output = not json_output
    effective_quiet = quiet or json_output or not human_output
    display_out_dir = out_dir or run_dir.parent
    command_run_id = display_run_id or run_dir.name
    work_order = load_work_order(run_dir / "work-order.json")
    decision = read_json(run_dir / "decision.json")
    if not isinstance(decision, dict):
        raise ValidationError(f"{run_dir} has no valid decision.json")
    report_path = run_dir / "report.md"
    if not report_path.exists():
        raise ValidationError(f"{run_dir} has no report.md")
    meta = read_json(run_dir / "meta.json") or {}
    report_text = report_path.read_text(encoding="utf-8")
    input_hashes = compute_input_hashes(run_dir)
    citation_cwd, caveats = resolve_citation_cwd(meta if isinstance(meta, dict) else {})

    triage_dir = run_dir / "triage"
    if triage_dir.exists():
        if not force:
            raise ValidationError(
                f"{triage_dir} already exists; run "
                f"{bakeoff_triage_command(command_run_id, display_out_dir, force=True)} to replace"
            )
        ensure_child_path(run_dir, triage_dir)
        shutil.rmtree(triage_dir)
    triage_dir.mkdir(parents=True)

    finding_index, synthesized = build_finding_index(report_text)
    source_findings, skipped_findings = select_triage_source_findings(finding_index, facet_id=facet_id(work_order))
    source_finding_filter = summarize_source_finding_filter(source_findings, skipped_findings)
    write_json(
        triage_dir / "source_finding_filter.json",
        {
            "schema_version": 1,
            "summary": source_finding_filter,
            "selected": source_findings,
            "skipped": skipped_findings,
        },
    )
    if synthesized:
        caveats.append("source finding IDs were synthesized from report display order")
        write_json(triage_dir / "finding_index.json", {"schema_version": 1, "findings": finding_index})
    citation_text = collect_citation_text(run_dir, report_text, decision)
    citation_checks = check_citations(extract_citations_from_text(citation_text), citation_cwd)
    write_json(triage_dir / "citation_checks.json", citation_checks)
    payload = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "work_order_json": (run_dir / "work-order.json").read_text(encoding="utf-8"),
        "facet": work_order.get("facet"),
        "meta": meta,
        "decision": decision,
        "report_md": report_text,
        "source_findings": source_findings,
        "source_finding_filter": source_finding_filter,
        "citation_checks": citation_checks,
        "caveats": caveats,
        "input_hashes": input_hashes,
    }
    prompt = build_triage_prompt(payload, work_order["budgets"])
    write_text_atomic(triage_dir / "prompt.txt", prompt)
    participant = {
        "backend": work_order["judge"]["backend"],
        "model": work_order["judge"]["model"],
        "effort": work_order["judge"]["effort"],
    }
    if human_output:
        print(f"triage participant: {participant['backend']} {participant['model']} (effort {participant['effort']})")
        _note("triage invokes one provider call; use --dry-run to inspect inputs only")
        print(
            "source findings: "
            f"selected {source_finding_filter['included']}; "
            f"skipped {source_finding_filter['skipped_non_actionable']} non-actionable; "
            f"skipped {source_finding_filter['skipped_out_of_facet']} out-of-facet"
        )
        print(f"source filter: {triage_dir / 'source_finding_filter.json'}")
    if dry_run:
        write_json(
            triage_dir / "status.json",
            {
                "status": "dry_run",
                "triage_participant": participant,
                "input_hashes": input_hashes,
                "source_finding_filter": source_finding_filter,
            },
        )
        if human_output:
            print(f"triage dry run: {triage_dir / 'prompt.txt'}")
            print(f"triage status:  {triage_dir / 'status.json'}")
            print(f"next:           {bakeoff_triage_command(command_run_id, display_out_dir, force=True)}")
        write_run_manifest(run_dir)
        if json_output:
            print_json_summary(
                build_triage_json_summary(run_dir, command_run_id, display_out_dir, exit_code=0, dry_run=True)
            )
        return 0

    selected_source_ids = {finding["id"] for finding in source_findings}

    def validator(data: Any) -> dict[str, Any]:
        final = dict(validate_triage_result(data))
        unknown_source_ids = sorted(
            item["source_finding_id"]
            for item in final.get("items", [])
            if item.get("source_finding_id") not in selected_source_ids
        )
        if unknown_source_ids:
            raise ValidationError(
                "triage final_json.items source_finding_id must reference selected source_findings "
                f"(unknown: {', '.join(unknown_source_ids)})"
            )
        final["run_id"] = run_dir.name
        final["input_hashes"] = input_hashes
        final["triage_participant"] = participant
        final["source_finding_filter"] = source_finding_filter
        return final

    final_message_path = codex_final_message_path(work_order["judge"], triage_dir / "last-message.txt")
    result = await run_provider_with_format_retry(
        build_participant_argv(work_order["judge"], cwd=citation_cwd, final_message_path=final_message_path),
        prompt,
        work_order["budgets"],
        cwd=citation_cwd,
        validator=validator,
        on_tick=make_tick_printer("triage", quiet=effective_quiet),
        final_message_path=final_message_path,
    )
    write_text_atomic(triage_dir / "stdout.txt", result["stdout"])
    write_text_atomic(triage_dir / "stderr.txt", result["stderr"])
    write_format_retry_artifacts(triage_dir, result)
    status = status_without_payload(result)
    status["triage_participant"] = participant
    status["input_hashes"] = input_hashes
    status["source_finding_filter"] = source_finding_filter
    write_json(triage_dir / "status.json", status)
    if not provider_succeeded(result):
        write_run_manifest(run_dir)
        if human_output:
            print(f"triage failed: {status.get('status')}")
            print(f"retry:  {bakeoff_triage_command(command_run_id, display_out_dir, force=True)}")
        if json_output:
            print_json_summary(
                build_triage_json_summary(run_dir, command_run_id, display_out_dir, exit_code=1, dry_run=False)
            )
        return 1
    write_json(triage_dir / "final.json", result["final_json"])
    write_text_atomic(triage_dir / "triage.md", render_triage_markdown(result["final_json"], caveats))
    write_run_manifest(run_dir)
    if human_output:
        print(f"triage: {triage_dir / 'triage.md'}")
        print(f"next:   {bakeoff_show_command(command_run_id, display_out_dir, '--triage')}")
    if json_output:
        print_json_summary(
            build_triage_json_summary(run_dir, command_run_id, display_out_dir, exit_code=0, dry_run=False)
        )
    return 0


async def run_workers(
    work_order: dict[str, Any],
    run_dir: Path,
    *,
    quiet: bool = False,
    human_output: bool = True,
) -> dict[str, dict[str, Any]]:
    capabilities = {}
    if work_order["scope_policy"]["enforcement"] != "advisory":
        capabilities = {
            backend: detect_scope_capabilities(backend)
            for backend in sorted({provider["backend"] for provider in work_order["providers"]})
        }

    async def run_one(provider: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        provider_id = provider["id"]
        prompt = build_worker_prompt(work_order, provider)
        cleanup_paths: list[Path] = []
        provider_dir = run_dir / "providers" / provider_id
        final_message_path = codex_final_message_path(provider, provider_dir / "last-message.txt")
        try:
            scope_execution = build_scope_execution(
                provider,
                work_order["scope_policy"],
                workspace_cwd=Path.cwd(),
                run_dir=run_dir,
                capabilities=capabilities.get(provider["backend"]),
                final_message_path=final_message_path,
            )
        except ScopeEnforcementError as exc:
            provider_dir.mkdir(parents=True, exist_ok=True)
            write_text_atomic(provider_dir / "prompt.txt", prompt)
            result = scope_error_result(exc, provider, work_order["scope_policy"])
            write_provider_artifacts(provider_dir, result)
            if human_output:
                print(f"[{provider_id}] {result['status']} {result['wall_seconds']}s {result['output_bytes']} bytes")
            return provider_id, result
        argv = scope_execution["argv"]
        execution_cwd = Path(scope_execution["cwd"])
        cleanup_paths = [Path(path) for path in scope_execution.get("cleanup_paths", [])]
        try:
            provider_dir.mkdir(parents=True, exist_ok=True)
            write_text_atomic(provider_dir / "prompt.txt", prompt)
            if human_output:
                print(f"[{provider_id}] launching...")
            validator = lambda data: validate_worker_result(data, mode=work_order["type"])
            result = await run_provider_with_format_retry(
                argv,
                prompt,
                work_order["budgets"],
                cwd=execution_cwd,
                validator=validator,
                on_tick=make_tick_printer(provider_id, quiet=quiet),
                final_message_path=final_message_path,
            )
            result["scope_enforcement"] = scope_execution["metadata"]
            write_provider_artifacts(provider_dir, result)
            if human_output:
                print(f"[{provider_id}] {result['status']} {result['wall_seconds']}s {result['output_bytes']} bytes")
            return provider_id, result
        finally:
            cleanup_scope_paths(cleanup_paths)

    raw_results = await asyncio.gather(*(run_one(provider) for provider in work_order["providers"]), return_exceptions=True)
    pairs: list[tuple[str, dict[str, Any]]] = []
    for provider, raw in zip(work_order["providers"], raw_results):
        provider_id = provider["id"]
        if isinstance(raw, BaseException):
            result = internal_error_result(raw)
            provider_dir = run_dir / "providers" / provider_id
            provider_dir.mkdir(parents=True, exist_ok=True)
            write_provider_artifacts(provider_dir, result)
            pairs.append((provider_id, result))
        else:
            pairs.append(raw)
    return dict(pairs)


def cleanup_scope_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            _warn(f"failed to clean scope workspace {path}: {exc}")


async def run_judge_phase(
    work_order: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    run_dir: Path,
    *,
    quiet: bool = False,
    human_output: bool = True,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], int]:
    mode = work_order["type"]
    provider_ids = [provider["id"] for provider in work_order["providers"]]
    base = decision_base(work_order, worker_results, run_dir)
    if mode == "gather":
        order = {"A": provider_ids[0], "B": provider_ids[1]}
        judge_result = await run_single_judge(
            work_order,
            worker_results,
            order,
            run_dir,
            "gather",
            quiet=quiet,
            human_output=human_output,
        )
        judge_results = {"pass1": judge_result.get("final_json") or {}}
        decision = {
            **base,
            "decision_kind": "structured_union",
            "judge_ran": True,
            "order_maps": {"pass1": order},
            "canonical_winner": None,
            "judge_rationale": [],
            "caveats": [],
        }
        if not provider_succeeded(judge_result):
            decision["caveats"] = [f"gather judge failed with {judge_result['status']}"]
            return decision, judge_results, 1
        return decision, judge_results, 0

    pass1_order = {"A": provider_ids[0], "B": provider_ids[1]}
    pass2_order = {"A": provider_ids[1], "B": provider_ids[0]}
    pass1 = await run_single_judge(
        work_order,
        worker_results,
        pass1_order,
        run_dir,
        "pass1",
        quiet=quiet,
        human_output=human_output,
    )
    pass2 = await run_single_judge(
        work_order,
        worker_results,
        pass2_order,
        run_dir,
        "pass2",
        quiet=quiet,
        human_output=human_output,
    )
    judge_results = {"pass1": pass1.get("final_json") or {}, "pass2": pass2.get("final_json") or {}}
    if not provider_succeeded(pass1) or not provider_succeeded(pass2):
        decision = {
            **base,
            "decision_kind": "tie",
            "judge_ran": True,
            "order_maps": {"pass1": pass1_order, "pass2": pass2_order},
            "canonical_winner": None,
            "judge_rationale": [],
            "caveats": [f"judge failed: pass1={pass1['status']}, pass2={pass2['status']}"],
        }
        return decision, judge_results, 1
    if mode == "compare":
        decision = resolve_compare_decision(base, judge_results, pass1_order, pass2_order)
        return decision, judge_results, 3 if decision.get("decision_kind") == "tie" else 0
    return resolve_analyze_decision(base, worker_results, judge_results, pass1_order, pass2_order), judge_results, 0


async def run_single_judge(
    work_order: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    order_map: dict[str, str],
    run_dir: Path,
    label: str,
    *,
    quiet: bool = False,
    human_output: bool = True,
) -> dict[str, Any]:
    mode = work_order["type"]
    worker_a = anonymized_worker_output(worker_results[order_map["A"]])
    worker_b = anonymized_worker_output(worker_results[order_map["B"]])
    prompt = build_judge_prompt(work_order, worker_a, worker_b)
    judge_dir = run_dir / "judge"
    judge_dir.mkdir(exist_ok=True)
    if label == "gather":
        prompt_path = judge_dir / "prompt.txt"
        result_path = judge_dir / "result.json"
        status_path = judge_dir / "status.json"
        stdout_path = judge_dir / "stdout.txt"
        stderr_path = judge_dir / "stderr.txt"
    else:
        prompt_path = judge_dir / f"prompt-{label}.txt"
        result_path = judge_dir / f"result-{label}.json"
        status_path = judge_dir / f"status-{label}.json"
        stdout_path = judge_dir / f"stdout-{label}.txt"
        stderr_path = judge_dir / f"stderr-{label}.txt"
    last_message_name = "last-message.txt" if label == "gather" else f"last-message-{label}.txt"
    final_message_path = codex_final_message_path(work_order["judge"], judge_dir / last_message_name)
    write_text_atomic(prompt_path, prompt)
    validator = judge_validator(mode)
    if human_output:
        print(f"[judge:{label}] running...")
    result = await run_provider_with_format_retry(
        build_participant_argv(work_order["judge"], cwd=Path.cwd(), final_message_path=final_message_path),
        prompt,
        work_order["budgets"],
        cwd=Path.cwd(),
        validator=validator,
        on_tick=make_tick_printer(f"judge:{label}", quiet=quiet),
        final_message_path=final_message_path,
    )
    write_text_atomic(stdout_path, result["stdout"])
    write_text_atomic(stderr_path, result["stderr"])
    write_format_retry_artifacts(judge_dir, result, suffix=None if label == "gather" else label)
    write_json(status_path, status_without_payload(result))
    if provider_succeeded(result):
        write_json(result_path, result["final_json"])
    if human_output:
        print(f"[judge:{label}] {result['status']} {result['wall_seconds']}s")
    return result


def resolve_compare_decision(
    base: dict[str, Any],
    judge_results: dict[str, dict[str, Any]],
    pass1_order: dict[str, str],
    pass2_order: dict[str, str],
) -> dict[str, Any]:
    pass1 = judge_results["pass1"]
    pass2 = judge_results["pass2"]
    decision = {
        **base,
        "judge_ran": True,
        "order_maps": {"pass1": pass1_order, "pass2": pass2_order},
        "judge_passes": {
            "pass1": judge_pass_summary(pass1, pass1_order, verdict_key="winner"),
            "pass2": judge_pass_summary(pass2, pass2_order, verdict_key="winner"),
        },
        "canonical_winner": None,
        "judge_rationale": [_rationale(pass1), _rationale(pass2)],
        "caveats": [],
    }
    if pass1.get("relation") == "consensus" and pass2.get("relation") == "consensus":
        decision.update(
            {
                "decision_kind": "consensus",
                "consensus_strongest": merge_items(
                    pass1.get("consensus_strongest", []), pass2.get("consensus_strongest", [])
                ),
                "consensus_disagreements": merge_items(
                    pass1.get("consensus_disagreements", []), pass2.get("consensus_disagreements", [])
                ),
            }
        )
        return decision
    winner1 = canonical_winner(pass1.get("winner"), pass1_order)
    winner2 = canonical_winner(pass2.get("winner"), pass2_order)
    if winner1 and winner1 == winner2:
        loser1 = next(provider for provider in pass1_order.values() if provider != winner1)
        loser2 = next(provider for provider in pass2_order.values() if provider != winner1)
        decision.update(
            {
                "decision_kind": "pick_winner",
                "canonical_winner": winner1,
                "kept_from_nonwinner": merge_items(
                    annotate_source(pass1.get("kept_from_nonwinner", []), loser1),
                    annotate_source(pass2.get("kept_from_nonwinner", []), loser2),
                ),
            }
        )
    else:
        preserved = merge_items(
            preserved_compare_material(pass1, pass1_order),
            preserved_compare_material(pass2, pass2_order),
        )
        decision.update(
            {
                "decision_kind": "tie",
                "caveats": ["position swap did not produce a stable winner"],
            }
        )
        if preserved:
            decision["kept_from_nonwinner"] = preserved
    return decision


def resolve_analyze_decision(
    base: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    judge_results: dict[str, dict[str, Any]],
    pass1_order: dict[str, str],
    pass2_order: dict[str, str],
) -> dict[str, Any]:
    pass1 = judge_results["pass1"]
    pass2 = judge_results["pass2"]
    spine1 = canonical_winner(pass1.get("spine_winner"), pass1_order)
    spine2 = canonical_winner(pass2.get("spine_winner"), pass2_order)
    provider_ids = list(worker_results)
    if spine1 and spine1 == spine2:
        spine = spine1
        tiebreak = "swap_agreement"
    else:
        counts = {pid: len((worker_results[pid].get("final_json") or {}).get("claims", [])) for pid in provider_ids}
        if counts[provider_ids[0]] != counts[provider_ids[1]]:
            spine = max(counts, key=counts.get)
            tiebreak = "atomic_count"
        else:
            spine = provider_ids[0]
            tiebreak = "position_a"

    chosen = pass1 if canonical_winner(pass1.get("spine_winner"), pass1_order) == spine else pass2
    loser = next(pid for pid in provider_ids if pid != spine)
    return {
        **base,
        "decision_kind": "pick_winner",
        "judge_ran": True,
        "order_maps": {"pass1": pass1_order, "pass2": pass2_order},
        "judge_passes": {
            "pass1": judge_pass_summary(pass1, pass1_order, verdict_key="spine_winner"),
            "pass2": judge_pass_summary(pass2, pass2_order, verdict_key="spine_winner"),
        },
        "canonical_winner": spine,
        "spine_tiebreak": tiebreak,
        "judge_rationale": [_rationale(pass1), _rationale(pass2)],
        "claim_verdicts": chosen.get("claim_verdicts", []),
        "additions_from_loser": annotate_source(chosen.get("additions_from_loser", []), loser),
        "actionable_followups": chosen.get("actionable_followups", []),
        "caveats": [] if tiebreak == "swap_agreement" else [f"spine chosen by {tiebreak} after swap disagreement"],
    }


def decision_base(work_order: dict[str, Any], worker_results: dict[str, dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    statuses = {}
    for provider_id, result in worker_results.items():
        status = status_without_payload(result)
        status["stderr_path"] = f"providers/{provider_id}/stderr.txt"
        statuses[provider_id] = status
    return {
        "mode": work_order["type"],
        "provider_statuses": statuses,
        "canonical_winner": None,
        "judge_rationale": [],
        "caveats": [],
    }


def judge_pass_summary(result: dict[str, Any], order_map: dict[str, str], *, verdict_key: str) -> dict[str, Any]:
    positional = result.get(verdict_key)
    summary = {
        "A": order_map.get("A"),
        "B": order_map.get("B"),
        "positional_winner": positional,
        "canonical_winner": canonical_winner(positional, order_map),
    }
    if result.get("relation"):
        summary["relation"] = result["relation"]
    return summary


def print_validation_summary(work_order: dict[str, Any]) -> None:
    budgets = work_order["budgets"]
    print("valid work order")
    print(f"  id:      {work_order['id']}")
    print(f"  mode:    {work_order['type']}")
    if work_order.get("facet"):
        print(f"  facet:   {work_order['facet']['id']}")
    print(f"  budgets: {format_budget_summary(budgets)}")
    print(f"  scope:   {work_order['scope_policy']['enforcement']}")
    print("  providers:")
    for provider in work_order["providers"]:
        print(f"    - {provider['id']}: {provider['backend']} {provider['model']} ({provider['scope']}, {provider['effort']})")
    judge = work_order["judge"]
    print(f"  judge:   {judge['backend']} {judge['model']} ({judge.get('effort', 'high')})")


def print_run_header(work_order: dict[str, Any], run_dir: Path, run_id: str) -> None:
    budgets = work_order["budgets"]
    providers = ", ".join(
        f"{p['id']} ({p['model']}, {p['scope']})" for p in work_order["providers"]
    )
    judge = work_order["judge"]
    print(f"bakeoff research  run-id: {run_id}")
    print(f"  mode:           {work_order['type']}")
    if work_order.get("facet"):
        print(f"  facet:          {work_order['facet']['id']}")
    print(f"  run dir:        {run_dir}/")
    print(f"  providers:      {providers}")
    print(f"  budgets:        {format_budget_summary(budgets)}")
    print(f"  scope policy:   {work_order['scope_policy']['enforcement']}")
    print(f"  judge:          {judge['backend']} {judge['model']}")


def format_budget_summary(budgets: dict[str, Any]) -> str:
    return (
        f"{budgets['wall_clock_seconds']}s wall, {budgets['max_output_bytes']} bytes out, "
        f"{budgets.get('output_cap_grace_seconds', 10)}s cap grace"
    )


def judge_validator(mode: str):
    if mode == "gather":
        return validate_gather_judge_result
    if mode == "compare":
        return validate_compare_judge_result
    return validate_analyze_judge_result


def canonical_winner(verdict: Any, order_map: dict[str, str]) -> str | None:
    if verdict in ("A", "B"):
        return order_map[verdict]
    return None


def annotate_source(items: list[Any], source_provider: str) -> list[Any]:
    annotated = []
    for item in items:
        if isinstance(item, dict):
            annotated.append({**item, "source_provider": source_provider})
        else:
            annotated.append({"claim": str(item), "source_provider": source_provider})
    return annotated


def preserved_compare_material(result: dict[str, Any], order_map: dict[str, str]) -> list[Any]:
    items = result.get("kept_from_nonwinner", [])
    if not items:
        return []
    winner = canonical_winner(result.get("winner"), order_map)
    if winner is None:
        source_provider = "unknown"
    else:
        source_provider = next(provider for provider in order_map.values() if provider != winner)
    return annotate_source(items, source_provider)


def merge_items(*groups: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen_keys: set[str] = set()
    seen_texts: list[tuple[str, str | None]] = []
    for group in groups:
        for item in group:
            key = merge_item_key(item)
            text, source = merge_item_text_and_source(item)
            if key in seen_keys or is_near_duplicate(text, source, seen_texts):
                continue
            seen_keys.add(key)
            if text:
                seen_texts.append((text, source))
            merged.append(item)
    return merged


def merge_item_key(item: Any) -> str:
    if isinstance(item, dict):
        text, source = merge_item_text_and_source(item)
        return json.dumps({"text": normalize_merge_text(text), "source": source}, sort_keys=True)
    return normalize_merge_text(str(item))


def merge_item_text_and_source(item: Any) -> tuple[str, str | None]:
    if isinstance(item, dict):
        text = item.get("claim") or item.get("description") or item.get("loser_note") or str(item)
        source = item.get("source_provider")
        return str(text), str(source) if source else None
    return str(item), None


def is_near_duplicate(text: str, source: str | None, seen_texts: list[tuple[str, str | None]]) -> bool:
    if not text:
        return False
    for existing, existing_source in seen_texts:
        if source != existing_source:
            continue
        if numeric_tokens(text) != numeric_tokens(existing):
            continue
        if token_similarity(text, existing) >= 0.95:
            return True
    return False


def token_similarity(left: str, right: str) -> float:
    left_tokens = merge_tokens(left)
    right_tokens = merge_tokens(right)
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def merge_tokens(text: str) -> set[str]:
    stopwords = {"a", "an", "are", "can", "is", "s", "the", "to", "via", "while", "with"}
    tokens = set()
    for token in normalize_merge_text(text).split():
        if token in stopwords:
            continue
        tokens.add(token)
    return tokens


def numeric_tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def normalize_merge_text(text: str) -> str:
    normalized = re.sub(r"\([AB]/R-\d{3}\)", "", text.lower())
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def single_provider_caveat(mode: str, survivor: str, failed: str, status: str) -> str:
    if mode == "gather":
        return f"single_provider_only: {failed} {status}; rendering {survivor} findings without dedupe"
    if mode == "compare":
        return f"single_provider_only: {failed} {status}; no comparison possible - surfacing {survivor} result only"
    return f"single_provider_only: {failed} {status}; no overlay possible - surfacing {survivor} analysis only"


def internal_error_result(exc: BaseException) -> dict[str, Any]:
    return {
        "status": "exit_error",
        "exit_code": None,
        "wall_seconds": 0,
        "output_bytes": 0,
        "stdout": "",
        "stderr": f"internal provider task error: {exc.__class__.__name__}: {exc}",
        "final_json": None,
    }


def scope_error_result(exc: BaseException, provider: dict[str, Any], scope_policy: dict[str, Any]) -> dict[str, Any]:
    requested_scope = provider.get("scope", "mixed")
    return {
        "status": "scope_error",
        "exit_code": None,
        "wall_seconds": 0,
        "output_bytes": 0,
        "stdout_bytes": 0,
        "stderr_bytes": len(str(exc).encode("utf-8")),
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout": "",
        "stderr": str(exc),
        "final_json": None,
        "scope_enforcement": {
            "requested_scope": requested_scope,
            "policy": scope_policy.get("enforcement", "best_effort"),
            "effective_scope": "advisory",
            "enforcement_level": "failed",
            "mechanisms": [],
            "fallback_reason": str(exc),
            "cwd": str(Path.cwd()),
        },
    }


def _rationale(result: dict[str, Any]) -> str:
    value = result.get("rationale") or result.get("spine_rationale") or ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def write_provider_artifacts(provider_dir: Path, result: dict[str, Any]) -> None:
    write_text_atomic(provider_dir / "stdout.txt", result["stdout"])
    write_text_atomic(provider_dir / "stderr.txt", result["stderr"])
    write_format_retry_artifacts(provider_dir, result)
    write_json(provider_dir / "status.json", status_without_payload(result))
    if provider_succeeded(result):
        write_json(provider_dir / "final.json", result["final_json"])


def write_meta(
    run_dir: Path,
    work_order: dict[str, Any],
    run_id: str,
    started_at: str,
    *,
    worker_results: dict[str, dict[str, Any]] | None = None,
) -> None:
    versions = {backend: tool_version(backend) for backend in ("claude", "codex", "git")}
    worker_results = worker_results or {}
    meta = {
        "run_id": run_id,
        "type": work_order["type"],
        "facet": work_order.get("facet"),
        "started_at": started_at,
        "finished_at": utc_now(),
        "cwd": str(Path.cwd()),
        "bakeoff_version": __version__,
        "scope_policy": work_order["scope_policy"],
        "provider_cli_versions": versions,
        "input_hashes": compute_input_hashes(run_dir),
        "resolved_models": {
            "providers": {
                provider["id"]: {
                    "backend": provider["backend"],
                    "model": provider["model"],
                    "scope": provider["scope"],
                    "effort": provider["effort"],
                    "scope_enforcement": worker_results.get(provider["id"], {}).get("scope_enforcement"),
                }
                for provider in work_order["providers"]
            },
            "judge": {
                "backend": work_order["judge"]["backend"],
                "model": work_order["judge"]["model"],
                "effort": work_order["judge"]["effort"],
            },
        },
    }
    write_json(run_dir / "meta.json", meta)


def status_without_payload(result: dict[str, Any]) -> dict[str, Any]:
    status = {
        key: result[key]
        for key in (
            "status",
            "exit_code",
            "wall_seconds",
            "output_bytes",
            "stdout_bytes",
            "stderr_bytes",
            "stdout_observed_bytes",
            "stderr_observed_bytes",
            "stdout_truncated",
            "stderr_truncated",
            "final_json_source",
        )
        if key in result
    }
    if "io" in result:
        status["io"] = result["io"]
    if "output_cap" in result:
        status["output_cap"] = result["output_cap"]
    if "format_retry" in result:
        status["format_retry"] = result["format_retry"]
    if "scope_enforcement" in result:
        status["scope_enforcement"] = result["scope_enforcement"]
    return status


def auth_probe_status(result: dict[str, Any]) -> dict[str, Any]:
    status = status_without_payload(result)
    if result.get("status") == "ok":
        return status
    reason = last_nonempty_line(result.get("stderr", "")) or last_nonempty_line(result.get("stdout", ""))
    tail = diagnostic_tail(result.get("stderr", "") or result.get("stdout", ""))
    if reason:
        status["reason"] = reason
    if tail:
        status["diagnostic_tail"] = tail
    return status


def last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def diagnostic_tail(text: str, *, max_chars: int = 1000, max_lines: int = 5) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def write_format_retry_artifacts(directory: Path, result: dict[str, Any], *, suffix: str | None = None) -> None:
    artifacts = result.get("repair_artifacts")
    if not isinstance(artifacts, dict):
        return
    suffix_part = f"-{suffix}" if suffix else ""
    write_text_atomic(directory / f"repair-prompt{suffix_part}.txt", str(artifacts.get("prompt", "")))
    write_text_atomic(directory / f"repair-stdout{suffix_part}.txt", str(artifacts.get("stdout", "")))
    write_text_atomic(directory / f"repair-stderr{suffix_part}.txt", str(artifacts.get("stderr", "")))
    write_json(directory / f"repair-status{suffix_part}.json", artifacts.get("status", {}))


def make_tick_printer(label: str, *, quiet: bool) -> Callable[[dict[str, Any]], None] | None:
    if quiet:
        return None

    def on_tick(tick: dict[str, Any]) -> None:
        print(format_heartbeat_line(label, tick), file=sys.stderr)

    return on_tick


def format_heartbeat_line(label: str, tick: dict[str, Any]) -> str:
    elapsed = int(float(tick.get("elapsed", 0)))
    wall_seconds = int(float(tick.get("wall_seconds", 0)))
    last_output_age = int(float(tick.get("last_output_age", 0)))
    stdout_bytes = int(tick.get("stdout_bytes", 0))
    stderr_bytes = int(tick.get("stderr_bytes", 0))
    phase = str(tick.get("phase", "running"))
    return (
        f"[{label}] {phase} t={elapsed}s/{wall_seconds}s "
        f"out={format_kb(stdout_bytes)} err={format_kb(stderr_bytes)} last={last_output_age}s"
    )


def format_kb(byte_count: int) -> str:
    return f"{byte_count / 1024:.1f}KB"


def write_json(path: Path, data: Any) -> None:
    write_json_atomic(path, data)


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def make_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid4().hex[:4]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def update_latest_symlink(out_dir: Path, run_id: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "latest"
    tmp = out_dir / ".latest.tmp"
    try:
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        tmp.symlink_to(run_id, target_is_directory=True)
        os.replace(tmp, latest)
    except OSError:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        write_text_atomic(latest, run_id + "\n")


def resolve_run_dir(out_dir: Path, run_id: str) -> Path:
    if run_id == "latest":
        latest = out_dir / "latest"
        if latest.is_symlink():
            return latest.resolve()
        if latest.is_file():
            target = latest.read_text(encoding="utf-8").strip()
            if target:
                return resolve_run_dir(out_dir, target)
    candidate = out_dir / run_id
    if candidate.exists() and candidate.is_dir():
        return candidate
    if os.sep in run_id or (os.altsep and os.altsep in run_id):
        path = Path(run_id)
        if path.exists() and path.is_dir():
            return path
    raise ValidationError(f"run not found: {run_id}")


def validate_run_id(run_id: str) -> None:
    if run_id in ("latest", ".", "..") or not RUN_ID_RE.match(run_id):
        raise ValidationError("run-id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$ and not latest")


def ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved not in (child_resolved, *child_resolved.parents):
        raise ValidationError(f"refusing to remove run directory outside {parent}")


def check_cwd_writable() -> tuple[bool, str]:
    probe = Path.cwd() / f".bakeoff-doctor-write-test-{uuid4().hex}"
    try:
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, str(exc)
    return True, str(Path.cwd())


def tool_version(tool: str) -> str:
    try:
        completed = subprocess.run(version_argv(tool), text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return text[0] if text else f"exit {completed.returncode}"


if __name__ == "__main__":
    raise SystemExit(main())
