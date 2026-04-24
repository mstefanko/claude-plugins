"""`swarm` CLI for preset and pipeline registry operations."""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
from pathlib import Path

from .engine import graph_lines
from .paths import current_preset_path, resolve_data_dir, user_presets_dir
from .registry import (
    find_pipeline,
    find_preset,
    list_pipelines,
    list_presets,
    load_pipeline,
    load_preset,
    sha256_file,
)
from .rollout import format_status, history_lines, load_state, mark_dogfood, set_field
from .validation import schema_lint_pipeline, validate_preset_and_pipeline


def _ensure_current_file() -> Path:
    path = current_preset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def _print_validation(result) -> None:
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)


def _activate_preset(name: str) -> None:
    path = _ensure_current_file()
    path.write_text(name + "\n", encoding="utf-8")


def cmd_preset_load(args: argparse.Namespace) -> int:
    result, preset, pipeline, _ = validate_preset_and_pipeline(args.name, include_budget=False)
    _print_validation(result)
    if not result.ok:
        return 1
    _activate_preset(args.name)
    print(f"loaded preset {args.name}; budget gate will run during dry-run and run start")
    return 0


def cmd_preset_clear(args: argparse.Namespace) -> int:
    _ensure_current_file().write_text("", encoding="utf-8")
    print("cleared active preset; routing falls back to backends.toml")
    return 0


def cmd_preset_list(args: argparse.Namespace) -> int:
    _ensure_current_file()
    active = current_preset_path().read_text(encoding="utf-8").strip()
    for item in list_presets():
        marker = "*" if item.name == active else " "
        status = ""
        if item.origin == "user":
            try:
                preset = load_preset(item.path)
                expected = str(preset.get("forked_from_hash") or "")
                stock = find_preset(item.name)
                if expected.startswith("sha256:") and stock and stock.origin == "stock":
                    actual = "sha256:" + sha256_file(stock.path)
                    if actual != expected:
                        status = " fork-outdated"
            except Exception:
                status = " unreadable"
        print(f"{marker} {item.name}\t{item.origin}{status}")
    return 0


def cmd_preset_save(args: argparse.Namespace) -> int:
    existing = find_preset(args.name)
    if existing and existing.origin == "stock":
        print(
            f"swarm: preset save: {args.name} is a stock preset; fork it with "
            f"`swarm preset save <new-name> --from {args.name}`",
            file=sys.stderr,
        )
        return 1
    source = args.source
    if source == "current":
        current = _ensure_current_file().read_text(encoding="utf-8").strip()
        if not current:
            print("swarm: preset save: no active preset to save from", file=sys.stderr)
            return 1
        source = current
    item = find_preset(source)
    if item is None:
        print(f"swarm: preset save: source preset not found: {source}", file=sys.stderr)
        return 1
    user_presets_dir().mkdir(parents=True, exist_ok=True)
    target = user_presets_dir() / f"{args.name}.toml"
    text = item.path.read_text(encoding="utf-8")
    text = text.replace(f'name = "{source}"', f'name = "{args.name}"', 1)
    text = text.replace('origin = "stock"', 'origin = "user"', 1)
    if "forked_from_hash" not in text:
        text += f'\nforked_from_hash = "sha256:{sha256_file(item.path)}"\n'
    target.write_text(text, encoding="utf-8")
    print(f"saved user preset {args.name} from {source}")
    return 0


def cmd_preset_diff(args: argparse.Namespace) -> int:
    item = find_preset(args.name)
    if item is None:
        print(f"swarm: preset diff: preset not found: {args.name}", file=sys.stderr)
        return 1
    if item.origin == "stock":
        print(f"stock preset {args.name}: no user fork to diff")
        return 0
    stock_path = next((candidate.path for candidate in list_presets() if candidate.name == args.name and candidate.origin == "stock"), None)
    if not stock_path:
        print(f"user preset {args.name}: no stock preset with the same name")
        return 0
    left = stock_path.read_text(encoding="utf-8").splitlines()
    right = item.path.read_text(encoding="utf-8").splitlines()
    for line in difflib.unified_diff(left, right, fromfile=f"stock/{args.name}", tofile=f"user/{args.name}", lineterm=""):
        print(line)
    return 0


def cmd_preset_rename(args: argparse.Namespace) -> int:
    from swarm_do.tui.actions import rename_user_preset

    try:
        rename_user_preset(args.old_name, args.new_name)
    except ValueError as exc:
        print(f"swarm: preset rename: {exc}", file=sys.stderr)
        return 1
    print(f"renamed user preset {args.old_name} -> {args.new_name}")
    return 0


def cmd_preset_delete(args: argparse.Namespace) -> int:
    from swarm_do.tui.actions import delete_user_preset

    try:
        delete_user_preset(args.name)
    except ValueError as exc:
        print(f"swarm: preset delete: {exc}", file=sys.stderr)
        return 1
    print(f"deleted user preset {args.name}")
    return 0


def cmd_preset_dry_run(args: argparse.Namespace) -> int:
    result, preset, pipeline, _ = validate_preset_and_pipeline(args.name, args.plan_path, include_budget=True)
    if result.budget:
        b = result.budget
        print("Budget preview")
        print(f"  phases: {b.phase_count}")
        print(f"  agents: {b.agent_count}")
        print(f"  estimated_tokens: {b.estimated_tokens}")
        print(f"  estimated_cost_usd: {b.estimated_cost_usd:.4f}")
        print(f"  estimated_wall_clock_seconds: {b.estimated_wall_clock_seconds}")
        print(f"  fan_out_width: {b.fan_out_width}")
        print(f"  parallelism: {b.parallelism}")
        print("  stages:")
        for stage in b.stage_estimates:
            print(
                f"    - {stage['stage_id']}: agents_per_phase={stage['agents_per_phase']} "
                f"estimated_tokens_per_phase={stage['estimated_tokens_per_phase']}"
            )
    if pipeline:
        print("Stage graph")
        print("\n".join(graph_lines(pipeline)))
    _print_validation(result)
    return 0 if result.ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    print(format_status(load_state()))
    observation_path = resolve_data_dir() / "telemetry" / "observations.jsonl"
    if observation_path.is_file():
        lines = observation_path.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"  observations: {len(lines)}")
        if lines:
            try:
                latest = json.loads(lines[-1])
                print(f"  latest_observation: {latest.get('event_type', 'unknown')} run_id={latest.get('run_id') or 'n/a'}")
            except json.JSONDecodeError:
                print("  latest_observation: invalid-json")
    return 0


def cmd_rollout_show(args: argparse.Namespace) -> int:
    state = load_state()
    if args.json:
        import json

        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(format_status(state))
    return 0


def cmd_rollout_set(args: argparse.Namespace) -> int:
    try:
        state = set_field(args.path, args.value)
    except ValueError as exc:
        print(f"swarm: rollout set: {exc}", file=sys.stderr)
        return 1
    print(format_status(state))
    return 0


def cmd_rollout_dogfood(args: argparse.Namespace) -> int:
    try:
        state = mark_dogfood(args.notes)
    except ValueError as exc:
        print(f"swarm: rollout dogfood: {exc}", file=sys.stderr)
        return 1
    print(format_status(state))
    return 0


def cmd_rollout_history(args: argparse.Namespace) -> int:
    lines = history_lines()
    if not lines:
        print("no rollout history")
        return 0
    print("\n".join(lines))
    return 0


def cmd_compete(args: argparse.Namespace) -> int:
    preset_name = args.preset
    result, preset, pipeline, _ = validate_preset_and_pipeline(preset_name, args.plan_path, include_budget=True)
    if result.budget:
        b = result.budget
        print("Budget preview")
        print(f"  phases: {b.phase_count}")
        print(f"  agents: {b.agent_count}")
        print(f"  estimated_tokens: {b.estimated_tokens}")
        print(f"  estimated_cost_usd: {b.estimated_cost_usd:.4f}")
        print(f"  estimated_wall_clock_seconds: {b.estimated_wall_clock_seconds}")
        print(f"  fan_out_width: {b.fan_out_width}")
        print(f"  parallelism: {b.parallelism}")
    if pipeline:
        print("Stage graph")
        print("\n".join(graph_lines(pipeline)))
    _print_validation(result)
    if not result.ok:
        return 1
    if args.dry_run:
        print(f"competitive preset {preset_name} is valid for {args.plan_path}")
        return 0
    _activate_preset(preset_name)
    print(f"loaded preset {preset_name}; run /swarm-do:do {args.plan_path} to start Pattern 5")
    return 0


def cmd_pipeline_list(args: argparse.Namespace) -> int:
    for item in list_pipelines():
        print(f"{item.name}\t{item.origin}")
    return 0


def cmd_pipeline_show(args: argparse.Namespace) -> int:
    item = find_pipeline(args.name)
    if item is None:
        print(f"swarm: pipeline show: pipeline not found: {args.name}", file=sys.stderr)
        return 1
    pipeline = load_pipeline(item.path)
    print(f"{pipeline.get('name')} v{pipeline.get('pipeline_version')} ({item.origin})")
    print("\n".join(graph_lines(pipeline)))
    return 0


def cmd_pipeline_lint(args: argparse.Namespace) -> int:
    item = find_pipeline(args.path)
    if item is None:
        print(f"swarm: pipeline lint: pipeline not found: {args.path}", file=sys.stderr)
        return 1
    try:
        pipeline = load_pipeline(item.path)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = schema_lint_pipeline(pipeline)
    from .validation import role_existence_errors, variant_existence_errors
    errors.extend(role_existence_errors(pipeline))
    errors.extend(variant_existence_errors(pipeline))
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"pipeline OK: {item.name}")
    return 0


def cmd_pipeline_set(args: argparse.Namespace) -> int:
    from .resolver import active_preset_name
    from swarm_do.tui.actions import set_user_preset_pipeline

    preset = active_preset_name()
    if not preset:
        print("swarm: pipeline set: no active user preset", file=sys.stderr)
        return 1
    try:
        set_user_preset_pipeline(preset, args.name)
    except ValueError as exc:
        print(f"swarm: pipeline set: {exc}", file=sys.stderr)
        return 1
    print(f"set active preset {preset} pipeline to {args.name}")
    return 0


def cmd_providers_doctor(args: argparse.Namespace) -> int:
    from .providers import format_provider_report, provider_doctor

    if args.mco_timeout_seconds < 1:
        print("swarm: providers doctor: --mco-timeout-seconds must be >= 1", file=sys.stderr)
        return 1
    report = provider_doctor(
        preset_name=args.preset,
        run_mco=args.mco,
        mco_timeout_seconds=args.mco_timeout_seconds,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(format_provider_report(report))
    return 0 if report.ok else 1


def cmd_mode(args: argparse.Namespace) -> int:
    if args.name == "custom":
        return cmd_preset_clear(args)
    mapped = "competitive" if args.name == "balanced-competitive" else args.name
    args.name = mapped
    return cmd_preset_load(args)


def cmd_handoff(args: argparse.Namespace) -> int:
    from swarm_do.tui.actions import request_handoff

    try:
        path = request_handoff(args.issue_id, args.to)
    except ValueError as exc:
        print(f"swarm: handoff: {exc}", file=sys.stderr)
        return 1
    print(f"handoff requested for {args.issue_id} -> {args.to} ({path})")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    from swarm_do.tui.actions import cancel_run, find_in_flight

    run = find_in_flight(args.issue_id)
    if run is None:
        print(f"swarm: cancel: no in-flight run for {args.issue_id}", file=sys.stderr)
        return 1
    try:
        cancel_run(run)
    except OSError as exc:
        print(f"swarm: cancel: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"swarm: cancel: {exc}", file=sys.stderr)
        return 1
    print(f"sent SIGTERM to {args.issue_id} pid={run.display_pid}")
    return 0


def cmd_permissions_check(args: argparse.Namespace) -> int:
    from .permissions import ROLE_NAMES, default_settings_path, diff_role, format_diff, load_fragment, load_settings

    target = Path(args.path) if args.path else default_settings_path(args.scope)
    try:
        settings = load_settings(target)
        roles = args.role or sorted(ROLE_NAMES)
        diffs = [diff_role(settings, load_fragment(role)) for role in roles]
    except ValueError as exc:
        print(f"swarm: permissions check: {exc}", file=sys.stderr)
        return 1
    print(f"target: {target.resolve()}")
    print("\n".join(format_diff(diff) for diff in diffs))
    return 0 if all(diff.ok for diff in diffs) else 1


def cmd_permissions_install(args: argparse.Namespace) -> int:
    from .permissions import (
        default_settings_path,
        diff_role,
        format_diff,
        load_fragment,
        load_settings,
        merge_role,
        uninstall_role,
        write_settings_atomic,
    )

    target = Path(args.path) if args.path else default_settings_path(args.scope)
    try:
        settings = load_settings(target)
        fragments = [load_fragment(role) for role in args.role]
        before_diffs = [diff_role(settings, fragment) for fragment in fragments]
        merged = settings
        for fragment in fragments:
            merged = uninstall_role(merged, fragment) if args.rollback else merge_role(merged, fragment)
    except ValueError as exc:
        print(f"swarm: permissions install: {exc}", file=sys.stderr)
        return 1
    print(f"target: {target.resolve()}")
    print("\n".join(format_diff(diff) for diff in before_diffs))
    print(json.dumps(merged.get("permissions", {}), indent=2, sort_keys=True))
    if args.dry_run:
        return 0 if not any(diff.conflicts for diff in before_diffs) else 1
    backup = write_settings_atomic(target, merged)
    print(f"wrote {target.resolve()}")
    if backup.exists():
        print(f"backup: {backup.resolve()}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from .resume import build_resume_report, format_resume_report, resume_exit_code

    report = build_resume_report(args.bd_id)
    print(format_resume_report(report, merge=args.merge))
    if report.drift_keys and args.merge:
        print("swarm: resume: refusing to merge while drift is present", file=sys.stderr)
    return resume_exit_code(report)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm")
    sub = parser.add_subparsers(dest="subcommand")

    preset = sub.add_parser("preset")
    preset_sub = preset.add_subparsers(dest="preset_command")
    p = preset_sub.add_parser("load"); p.add_argument("name"); p.set_defaults(func=cmd_preset_load)
    p = preset_sub.add_parser("clear"); p.set_defaults(func=cmd_preset_clear)
    p = preset_sub.add_parser("list"); p.set_defaults(func=cmd_preset_list)
    p = preset_sub.add_parser("save"); p.add_argument("name"); p.add_argument("--from", dest="source", required=True); p.set_defaults(func=cmd_preset_save)
    p = preset_sub.add_parser("diff"); p.add_argument("name"); p.set_defaults(func=cmd_preset_diff)
    p = preset_sub.add_parser("rename"); p.add_argument("old_name"); p.add_argument("new_name"); p.set_defaults(func=cmd_preset_rename)
    p = preset_sub.add_parser("delete"); p.add_argument("name"); p.set_defaults(func=cmd_preset_delete)
    p = preset_sub.add_parser("dry-run"); p.add_argument("name"); p.add_argument("plan_path"); p.set_defaults(func=cmd_preset_dry_run)

    pipeline = sub.add_parser("pipeline")
    pipeline_sub = pipeline.add_subparsers(dest="pipeline_command")
    p = pipeline_sub.add_parser("list"); p.set_defaults(func=cmd_pipeline_list)
    p = pipeline_sub.add_parser("show"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_show)
    p = pipeline_sub.add_parser("lint"); p.add_argument("path"); p.set_defaults(func=cmd_pipeline_lint)
    p = pipeline_sub.add_parser("set"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_set)

    providers = sub.add_parser("providers")
    providers_sub = providers.add_subparsers(dest="providers_command")
    p = providers_sub.add_parser("doctor")
    p.add_argument("--preset", default="current", help="preset to inspect; default is the active preset, falling back to default pipeline")
    p.add_argument("--mco", action="store_true", help="also run mco doctor --json")
    p.add_argument("--mco-timeout-seconds", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_providers_doctor)

    mode = sub.add_parser("mode")
    mode.add_argument("name", choices=["claude-only", "codex-only", "balanced", "custom"])
    mode.set_defaults(func=cmd_mode)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    rollout = sub.add_parser("rollout")
    rollout_sub = rollout.add_subparsers(dest="rollout_command")
    p = rollout_sub.add_parser("show"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_rollout_show)
    p = rollout_sub.add_parser("set"); p.add_argument("path"); p.add_argument("value"); p.set_defaults(func=cmd_rollout_set)
    p = rollout_sub.add_parser("dogfood"); p.add_argument("--notes"); p.set_defaults(func=cmd_rollout_dogfood)
    p = rollout_sub.add_parser("history"); p.set_defaults(func=cmd_rollout_history)

    compete = sub.add_parser("compete")
    compete.add_argument("plan_path")
    compete.add_argument("--preset", default="competitive")
    compete.add_argument("--dry-run", action="store_true")
    compete.set_defaults(func=cmd_compete)

    handoff = sub.add_parser("handoff")
    handoff.add_argument("issue_id")
    handoff.add_argument("--to", required=True, choices=["claude", "codex"])
    handoff.set_defaults(func=cmd_handoff)

    cancel = sub.add_parser("cancel")
    cancel.add_argument("issue_id")
    cancel.set_defaults(func=cmd_cancel)

    resume = sub.add_parser("resume")
    resume.add_argument("bd_id")
    resume.add_argument("--merge", action="store_true", help="allow merge only after a clean APPROVED completed-unit set")
    resume.set_defaults(func=cmd_resume)

    permissions = sub.add_parser("permissions")
    permissions_sub = permissions.add_subparsers(dest="permissions_command")
    p = permissions_sub.add_parser("check")
    p.add_argument("--role", action="append", choices=["writer", "spec-review", "review", "research", "clarify", "codex-review"])
    p.add_argument("--scope", choices=["repo", "user"], default="repo")
    p.add_argument("--path")
    p.set_defaults(func=cmd_permissions_check)
    p = permissions_sub.add_parser("install")
    p.add_argument("--role", action="append", required=True, choices=["writer", "spec-review", "review", "research", "clarify", "codex-review"])
    p.add_argument("--scope", choices=["repo", "user"], default="repo")
    p.add_argument("--path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rollback", action="store_true")
    p.set_defaults(func=cmd_permissions_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    resolve_data_dir().mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
