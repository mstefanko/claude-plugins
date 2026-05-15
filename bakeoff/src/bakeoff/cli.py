from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from bakeoff import __version__
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
from bakeoff.runner import provider_succeeded, run_provider, run_provider_with_format_retry
from bakeoff.triage import (
    build_finding_index,
    check_citations,
    collect_citation_text,
    compute_input_hashes,
    extract_citations_from_text,
    render_triage_markdown,
    resolve_citation_cwd,
    select_triage_source_findings,
    should_recommend_triage,
    triage_state,
)
from bakeoff.work_order import (
    MODE_EFFORT_DEFAULTS,
    MODES,
    ValidationError,
    init_template,
    load_work_order,
    validate_analyze_judge_result,
    validate_compare_judge_result,
    validate_gather_judge_result,
    validate_triage_result,
    validate_worker_result,
)

ORIENTATION = """\
bakeoff - run the same research task across multiple agents, then judge.

Three modes. Pick one based on what you want:
  gather   coverage research
  compare  defended pick
  analyze  thorough explanation

Get started:
  bakeoff init gather
  bakeoff validate gather.work-order.json
  bakeoff research gather.work-order.json

Provider CLIs required on PATH: `claude`, `codex`.
Run `bakeoff doctor` to check.
"""

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bakeoff", description="Tiny research bakeoff harness.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command")

    init = subcommands.add_parser("init", help="write an example work order")
    init.add_argument("type", choices=MODES)
    init.add_argument("--force", action="store_true", help="overwrite an existing template")

    validate = subcommands.add_parser("validate", help="validate and dry-run a work order")
    validate.add_argument("work_order")

    research = subcommands.add_parser("research", help="run a research bakeoff")
    research.add_argument("work_order")
    research.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    research.add_argument("--run-id", help="explicit run id")
    research.add_argument("--force", action="store_true", help="replace an existing run directory")
    research.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")

    rerun = subcommands.add_parser("rerun", help="replay a previous work order with a fresh run id")
    rerun.add_argument("source_run_id")
    rerun.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    rerun.add_argument("--run-id", dest="new_run_id", help="explicit new run id")
    rerun.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")

    triage = subcommands.add_parser("triage", help="triage a completed bakeoff report")
    triage.add_argument("run_id")
    triage.add_argument("--out", default="runs", help="run ledger directory (default: runs)")
    triage.add_argument("--force", action="store_true", help="replace an existing triage directory")
    triage.add_argument("--dry-run", action="store_true", help="build triage inputs without invoking a provider")
    triage.add_argument("--quiet", action="store_true", help="suppress provider heartbeat lines")

    ls_cmd = subcommands.add_parser("ls", help="list past runs")
    ls_cmd.add_argument("--out", default="runs", help="run ledger directory (default: runs)")

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
        if args.command == "ls":
            return cmd_ls(args)
        if args.command == "show":
            return cmd_show(args)
        if args.command == "doctor":
            return asyncio.run(cmd_doctor(args))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(f"{args.type}.work-order.json")
    if path.exists() and not args.force:
        raise ValidationError(f"{path} already exists; use --force to overwrite")
    path.write_text(init_template(args.type), encoding="utf-8")
    print(f"wrote {path}")
    defaults = MODE_EFFORT_DEFAULTS[args.type]
    print(f"effort defaults: workers={defaults['worker']}, judge={defaults['judge']}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    work_order = load_work_order(args.work_order)
    print_validation_summary(work_order)
    return 0


async def cmd_research(args: argparse.Namespace) -> int:
    return await run_research(Path(args.work_order), out_dir=Path(args.out), run_id=args.run_id, force=args.force, quiet=args.quiet)


async def cmd_rerun(args: argparse.Namespace) -> int:
    source_run = resolve_run_dir(Path(args.out), args.source_run_id)
    work_order_path = source_run / "work-order.json"
    if not work_order_path.exists():
        raise ValidationError(f"{source_run} has no work-order.json")
    return await run_research(work_order_path, out_dir=Path(args.out), run_id=args.new_run_id, force=False, quiet=args.quiet)


def cmd_ls(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if not out_dir.exists():
        return 0
    for run_dir in sorted((path for path in out_dir.iterdir() if path.is_dir()), reverse=True):
        if run_dir.name == "latest":
            continue
        meta = read_json(run_dir / "meta.json") or {}
        decision = read_json(run_dir / "decision.json") or {}
        print(
            f"{run_dir.name}\t{meta.get('type', '?')}\t{decision.get('decision_kind', '?')}\t"
            f"triage:{triage_state(run_dir)}\t{meta.get('finished_at', '-')}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    if sum(1 for value in (args.judge, args.judge_prompt, args.triage) if value) > 1:
        raise ValidationError("show artifact flags are mutually exclusive: --judge, --judge-prompt, --triage")
    run_dir = resolve_run_dir(Path(args.out), args.run_id)
    if args.triage:
        triage_report = run_dir / "triage" / "triage.md"
        if not triage_report.exists():
            raise ValidationError(f"triage has not been run for {run_dir.name}")
        print(triage_report.read_text(encoding="utf-8"), end="")
        return 0
    if args.judge_prompt:
        for path in sorted((run_dir / "judge").glob("prompt*.txt")):
            print(f"===== {path.relative_to(run_dir)} =====")
            print(path.read_text(encoding="utf-8"))
        return 0
    if args.judge:
        for path in sorted((run_dir / "judge").glob("result*.json")):
            print(f"===== {path.relative_to(run_dir)} =====")
            print(path.read_text(encoding="utf-8"))
        return 0
    report = run_dir / "report.md"
    if not report.exists():
        raise ValidationError(f"{run_dir} has no report.md")
    report_text = report.read_text(encoding="utf-8")
    print(report_text, end="")
    if triage_state(run_dir) == "yes":
        print(f"\ntriage available: bakeoff show {args.run_id} --triage")
    elif should_recommend_triage({"type": (read_json(run_dir / "meta.json") or {}).get("type")}, read_json(run_dir / "decision.json") or {}, report_text):
        print(f"\ntriage not yet run: bakeoff triage {args.run_id}")
    return 0


async def cmd_triage(args: argparse.Namespace) -> int:
    return await run_triage(resolve_run_dir(Path(args.out), args.run_id), force=args.force, dry_run=args.dry_run, quiet=args.quiet)


async def cmd_doctor(args: argparse.Namespace) -> int:
    failed = False
    report: dict[str, Any] = {
        "status": "ok",
        "tools": {},
        "defaults": DEFAULT_MODEL_IDS,
        "scope_policy": {
            "default_enforcement": "best_effort",
            "status_artifacts": ["provider status.json", "meta.json"],
        },
        "scope_capabilities": {},
        "auth_probes": {},
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
            report["auth_probes"][backend] = status_without_payload(result)
            if not args.json:
                print(f"- {backend} auth probe: {result['status']}")
            failed = failed or result["status"] != "ok"
    report["status"] = "failed" if failed else "ok"
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failed else 0


async def run_research(work_order_path: Path, *, out_dir: Path, run_id: str | None, force: bool, quiet: bool = False) -> int:
    work_order = load_work_order(work_order_path)
    actual_run_id = run_id or make_run_id()
    validate_run_id(actual_run_id)
    run_dir = out_dir / actual_run_id
    if run_dir.exists():
        if not force:
            raise ValidationError(f"{run_dir} already exists; use --force to replace")
        ensure_child_path(out_dir, run_dir)
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    update_latest_symlink(out_dir, actual_run_id)

    started_at = utc_now()
    (run_dir / "work-order.json").write_text(work_order_path.read_text(encoding="utf-8"), encoding="utf-8")
    print_run_header(work_order, run_dir, actual_run_id)

    worker_results = await run_workers(work_order, run_dir, quiet=quiet)
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
        exit_code = 2
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
        decision, judge_results, exit_code = await run_judge_phase(work_order, worker_results, run_dir, quiet=quiet)

    write_json(run_dir / "decision.json", decision)
    report = render_report(work_order, decision, worker_results, judge_results=judge_results)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    write_meta(run_dir, work_order, actual_run_id, started_at, worker_results=worker_results)
    print(f"report: {run_dir / 'report.md'}")
    print(f"next:   bakeoff show {actual_run_id}")
    recommendation = should_recommend_triage(work_order, decision, report)
    if recommendation:
        print(f"recommended: bakeoff triage {actual_run_id}  ({recommendation})")
    return exit_code


async def run_triage(run_dir: Path, *, force: bool, dry_run: bool, quiet: bool = False) -> int:
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
            raise ValidationError(f"{triage_dir} already exists; use --force to replace")
        ensure_child_path(run_dir, triage_dir)
        shutil.rmtree(triage_dir)
    triage_dir.mkdir(parents=True)

    finding_index, synthesized = build_finding_index(report_text)
    source_findings, skipped_findings = select_triage_source_findings(finding_index)
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
        "meta": meta,
        "decision": decision,
        "report_md": report_text,
        "source_findings": source_findings,
        "source_finding_filter": {
            "included": len(source_findings),
            "skipped_non_actionable": len(skipped_findings),
        },
        "citation_checks": citation_checks,
        "caveats": caveats,
        "input_hashes": input_hashes,
    }
    prompt = build_triage_prompt(payload)
    (triage_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    participant = {
        "backend": work_order["judge"]["backend"],
        "model": work_order["judge"]["model"],
        "effort": work_order["judge"]["effort"],
    }
    print(f"triage participant: {participant['backend']} {participant['model']} (effort {participant['effort']})")
    print("note: triage invokes one provider call; use --dry-run to inspect inputs only")
    if dry_run:
        write_json(triage_dir / "status.json", {"status": "dry_run", "triage_participant": participant, "input_hashes": input_hashes})
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
        return final

    result = await run_provider_with_format_retry(
        build_participant_argv(work_order["judge"], cwd=citation_cwd),
        prompt,
        work_order["budgets"],
        cwd=citation_cwd,
        validator=validator,
        on_tick=make_tick_printer("triage", quiet=quiet),
    )
    (triage_dir / "stdout.txt").write_text(result["stdout"], encoding="utf-8")
    (triage_dir / "stderr.txt").write_text(result["stderr"], encoding="utf-8")
    write_format_retry_artifacts(triage_dir, result)
    status = status_without_payload(result)
    status["triage_participant"] = participant
    status["input_hashes"] = input_hashes
    write_json(triage_dir / "status.json", status)
    if not provider_succeeded(result):
        return 2
    write_json(triage_dir / "final.json", result["final_json"])
    (triage_dir / "triage.md").write_text(render_triage_markdown(result["final_json"], caveats), encoding="utf-8")
    print(f"triage: {triage_dir / 'triage.md'}")
    print(f"next:   bakeoff show {run_dir.name} --triage")
    return 0


async def run_workers(work_order: dict[str, Any], run_dir: Path, *, quiet: bool = False) -> dict[str, dict[str, Any]]:
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
        try:
            scope_execution = build_scope_execution(
                provider,
                work_order["scope_policy"],
                workspace_cwd=Path.cwd(),
                run_dir=run_dir,
                capabilities=capabilities.get(provider["backend"]),
            )
        except ScopeEnforcementError as exc:
            provider_dir = run_dir / "providers" / provider_id
            provider_dir.mkdir(parents=True, exist_ok=True)
            (provider_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            result = scope_error_result(exc, provider, work_order["scope_policy"])
            write_provider_artifacts(provider_dir, result)
            print(f"[{provider_id}] {result['status']} {result['wall_seconds']}s {result['output_bytes']} bytes")
            return provider_id, result
        argv = scope_execution["argv"]
        execution_cwd = Path(scope_execution["cwd"])
        cleanup_paths = [Path(path) for path in scope_execution.get("cleanup_paths", [])]
        provider_dir = run_dir / "providers" / provider_id
        try:
            provider_dir.mkdir(parents=True, exist_ok=True)
            (provider_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            print(f"[{provider_id}] launching...")
            validator = lambda data: validate_worker_result(data, mode=work_order["type"])
            result = await run_provider_with_format_retry(
                argv,
                prompt,
                work_order["budgets"],
                cwd=execution_cwd,
                validator=validator,
                on_tick=make_tick_printer(provider_id, quiet=quiet),
            )
            result["scope_enforcement"] = scope_execution["metadata"]
            write_provider_artifacts(provider_dir, result)
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
            print(f"warning: failed to clean scope workspace {path}: {exc}", file=sys.stderr)


async def run_judge_phase(
    work_order: dict[str, Any], worker_results: dict[str, dict[str, Any]], run_dir: Path, *, quiet: bool = False
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], int]:
    mode = work_order["type"]
    provider_ids = [provider["id"] for provider in work_order["providers"]]
    base = decision_base(work_order, worker_results, run_dir)
    if mode == "gather":
        order = {"A": provider_ids[0], "B": provider_ids[1]}
        judge_result = await run_single_judge(work_order, worker_results, order, run_dir, "gather", quiet=quiet)
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
            return decision, judge_results, 2
        return decision, judge_results, 0

    pass1_order = {"A": provider_ids[0], "B": provider_ids[1]}
    pass2_order = {"A": provider_ids[1], "B": provider_ids[0]}
    pass1 = await run_single_judge(work_order, worker_results, pass1_order, run_dir, "pass1", quiet=quiet)
    pass2 = await run_single_judge(work_order, worker_results, pass2_order, run_dir, "pass2", quiet=quiet)
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
        return decision, judge_results, 2
    if mode == "compare":
        return resolve_compare_decision(base, judge_results, pass1_order, pass2_order), judge_results, 0
    return resolve_analyze_decision(base, worker_results, judge_results, pass1_order, pass2_order), judge_results, 0


async def run_single_judge(
    work_order: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    order_map: dict[str, str],
    run_dir: Path,
    label: str,
    *,
    quiet: bool = False,
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
    prompt_path.write_text(prompt, encoding="utf-8")
    validator = judge_validator(mode)
    print(f"[judge:{label}] running...")
    result = await run_provider_with_format_retry(
        build_participant_argv(work_order["judge"], cwd=Path.cwd()),
        prompt,
        work_order["budgets"],
        cwd=Path.cwd(),
        validator=validator,
        on_tick=make_tick_printer(f"judge:{label}", quiet=quiet),
    )
    stdout_path.write_text(result["stdout"], encoding="utf-8")
    stderr_path.write_text(result["stderr"], encoding="utf-8")
    write_format_retry_artifacts(judge_dir, result, suffix=None if label == "gather" else label)
    write_json(status_path, status_without_payload(result))
    if provider_succeeded(result):
        write_json(result_path, result["final_json"])
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
    (provider_dir / "stdout.txt").write_text(result["stdout"], encoding="utf-8")
    (provider_dir / "stderr.txt").write_text(result["stderr"], encoding="utf-8")
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


def write_format_retry_artifacts(directory: Path, result: dict[str, Any], *, suffix: str | None = None) -> None:
    artifacts = result.get("repair_artifacts")
    if not isinstance(artifacts, dict):
        return
    suffix_part = f"-{suffix}" if suffix else ""
    (directory / f"repair-prompt{suffix_part}.txt").write_text(str(artifacts.get("prompt", "")), encoding="utf-8")
    (directory / f"repair-stdout{suffix_part}.txt").write_text(str(artifacts.get("stdout", "")), encoding="utf-8")
    (directory / f"repair-stderr{suffix_part}.txt").write_text(str(artifacts.get("stderr", "")), encoding="utf-8")
    write_json(directory / f"repair-status{suffix_part}.json", artifacts.get("status", {}))


def make_tick_printer(label: str, *, quiet: bool) -> Callable[[dict[str, Any]], None] | None:
    if quiet:
        return None

    def on_tick(tick: dict[str, Any]) -> None:
        elapsed = int(float(tick.get("elapsed", 0)))
        quiet_for = int(float(tick.get("last_output_age", 0)))
        total = int(tick.get("total_bytes", 0))
        print(f"[provider={label} t={elapsed}s out={format_kb(total)} quiet={quiet_for}s]", file=sys.stderr)

    return on_tick


def format_kb(byte_count: int) -> str:
    return f"{byte_count / 1024:.1f}KB"


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        latest.write_text(run_id + "\n", encoding="utf-8")


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
