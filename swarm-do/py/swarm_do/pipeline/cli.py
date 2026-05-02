"""`swarm` CLI for preset and pipeline registry operations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .actions import (
    cancel_run,
    delete_user_preset,
    find_in_flight,
    fork_pipeline,
    fork_preset_and_pipeline,
    rename_user_preset,
    request_handoff,
    set_user_preset_pipeline,
    validate_preset_name,
)
from .catalog import pipeline_activation_error, pipeline_profile_for
from .diff import diff_user_pipeline, diff_user_preset, stock_drift_for_pipeline
from .engine import graph_lines
from .graph_source import resolve_preset_graph
from .migrate_inline import adopt_archived_pipeline, migrate_user_pipelines
from .paths import REPO_ROOT, current_preset_path, resolve_data_dir, user_presets_dir
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
from .validation import schema_lint_pipeline, schema_lint_work_units, validate_preset_and_pipeline, validate_preset_mapping
from .policies import ResolvedPolicyUpdate, expand_profile


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
    resolved = resolve_preset_graph(preset)
    graph_name = resolved.source_name or f"inline:{args.name}"
    activation_error = pipeline_activation_error(graph_name, pipeline)
    if activation_error:
        print(f"swarm: preset load: {activation_error}", file=sys.stderr)
        return 1
    _activate_preset(args.name)
    print(f"loaded preset {args.name}; budget gate will run during dry-run and run start")
    return 0


def cmd_preset_show(args: argparse.Namespace) -> int:
    item = find_preset(args.name)
    if item is None:
        print(f"swarm: preset show: preset not found: {args.name}", file=sys.stderr)
        return 1
    try:
        preset = load_preset(item.path)
        resolved = resolve_preset_graph(preset)
    except Exception as exc:
        print(f"swarm: preset show: {exc}", file=sys.stderr)
        return 1
    graph_name = resolved.source_name or f"inline:{args.name}"
    print(f"{preset.get('name', args.name)} ({item.origin})")
    print(f"graph: {resolved.source}" + (f" {graph_name}" if graph_name else ""))
    if resolved.lineage_name:
        print(f"lineage: {resolved.lineage_name} {resolved.lineage_hash or ''}".rstrip())
    for warning in resolved.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print("\n".join(graph_lines(resolved.graph)))
    return 0


def cmd_preset_resolve(args: argparse.Namespace) -> int:
    item = find_preset(args.name)
    try:
        if item is None:
            pipeline_item = find_pipeline(args.name)
            if pipeline_item is None:
                print(f"swarm: preset resolve: preset not found: {args.name}", file=sys.stderr)
                return 1
            preset = {
                "name": args.name,
                "pipeline": args.name,
                "origin": "stock",
                "budget": {
                    "max_agents_per_run": 20,
                    "max_estimated_cost_usd": 5.0,
                    "max_wall_clock_seconds": 1800,
                },
            }
            preset_origin = "synthetic-stock"
            preset_path = pipeline_item.path
        else:
            preset = load_preset(item.path)
            preset_origin = item.origin
            preset_path = item.path
        resolved = resolve_preset_graph(preset)
        result, pipeline = validate_preset_mapping(preset, args.name, include_budget=False)
    except Exception as exc:
        print(f"swarm: preset resolve: {exc}", file=sys.stderr)
        return 1
    payload = {
        "preset_name": args.name,
        "preset_origin": preset_origin,
        "preset_path": str(preset_path),
        "graph_source": resolved.source,
        "graph_source_name": resolved.source_name,
        "graph_source_hash": resolved.source_hash,
        "lineage_name": resolved.lineage_name,
        "lineage_hash": resolved.lineage_hash,
        "warnings": list(dict.fromkeys([*resolved.warnings, *result.warnings])),
        "validation": {
            "ok": result.ok,
            "errors": list(result.errors),
            "warnings": list(dict.fromkeys(result.warnings)),
        },
        "role_routes": _resolved_role_routes(pipeline, args.name, preset),
        "synthesize_merges": _synthesize_merge_routes(pipeline, args.name, preset),
        "graph": resolved.graph,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{args.name} ({preset_origin})")
        print(f"graph: {resolved.source}" + (f" {resolved.source_name}" if resolved.source_name else ""))
        if resolved.lineage_name:
            print(f"lineage: {resolved.lineage_name} {resolved.lineage_hash or ''}".rstrip())
        for warning in payload["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        print("routes:")
        for route in payload["role_routes"]:
            route_value = route.get("route") if isinstance(route, Mapping) else None
            backend = route_value.get("backend") if isinstance(route_value, Mapping) else "error"
            model = route_value.get("model") if isinstance(route_value, Mapping) else route.get("error")
            print(f"  {route.get('stage_id')} {route.get('kind')} {route.get('role')}: {backend} {model}")
        print("graph:")
        print("\n".join(graph_lines(resolved.graph)))
    return 0 if result.ok else 1


def cmd_preset_clear(args: argparse.Namespace) -> int:
    _ensure_current_file().write_text("", encoding="utf-8")
    print("cleared active preset; routing falls back to backends.toml")
    return 0


def _agent_override(agent: Mapping[str, Any]) -> Mapping[str, Any] | str | None:
    override = agent.get("route")
    if override is None and {"backend", "model", "effort"} <= set(agent.keys()):
        override = agent
    return override


def _resolved_role_routes(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from .resolver import BackendResolver

    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    rows: list[dict[str, Any]] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        stage_id = str(stage.get("id") or "<unknown>")
        for idx, agent in enumerate(stage.get("agents") or []):
            if not isinstance(agent, Mapping) or not isinstance(agent.get("role"), str):
                continue
            rows.append(_route_row(resolver, stage_id, "agent", agent["role"], _agent_override(agent), index=idx))
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping) and isinstance(fan.get("role"), str):
            role = str(fan["role"])
            if fan.get("variant") == "models" and isinstance(fan.get("routes"), list):
                for idx, route in enumerate(fan["routes"]):
                    rows.append(_route_row(resolver, stage_id, "fan_out.models", role, route, index=idx))
            else:
                rows.append(_route_row(resolver, stage_id, f"fan_out.{fan.get('variant')}", role, None))
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and isinstance(merge.get("agent"), str):
            rows.append(_route_row(resolver, stage_id, f"merge.{merge.get('strategy')}", str(merge["agent"]), None))
    return rows


def _route_row(
    resolver: Any,
    stage_id: str,
    kind: str,
    role: str,
    override: Mapping[str, Any] | str | None,
    *,
    index: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"stage_id": stage_id, "kind": kind, "role": role}
    if index is not None:
        row["index"] = index
    try:
        row["route"] = resolver.resolve(role, "hard", override=override).as_dict()
    except Exception as exc:
        row["error"] = str(exc)
    return row


def _synthesize_merge_routes(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _resolved_role_routes(pipeline, preset_name, preset)
        if isinstance(row.get("kind"), str) and str(row["kind"]).startswith("merge.synthesize")
    ]
    for row in rows:
        route = row.get("route")
        row["claude_backed"] = isinstance(route, Mapping) and route.get("backend") == "claude"
    return rows


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
    try:
        validate_preset_name(args.name)
    except ValueError as exc:
        print(f"swarm: preset save: {exc}", file=sys.stderr)
        return 1
    existing = find_preset(args.name)
    if existing and existing.origin == "stock":
        print(
            f"swarm: preset save: {args.name} is a stock preset; fork it with "
            f"`swarm preset save <new-name> --from {args.name}`",
            file=sys.stderr,
        )
        return 1
    if existing and existing.origin == "user":
        print(f"swarm: preset save: user preset already exists: {args.name}", file=sys.stderr)
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
    try:
        diff = diff_user_preset(args.name)
    except ValueError:
        item = find_preset(args.name)
        if item and item.origin == "stock":
            print(f"stock preset {args.name}: no user fork to diff")
            return 0
        print(f"swarm: preset diff: preset not found: {args.name}", file=sys.stderr)
        return 1
    if not diff.source_name:
        print(f"user preset {args.name}: no recorded stock source")
        return 0
    if not diff.has_changes:
        print(f"user preset {args.name}: no diff against {diff.source_name}")
        return 0
    print(diff.text())
    return 0


def cmd_preset_rename(args: argparse.Namespace) -> int:
    try:
        rename_user_preset(args.old_name, args.new_name)
    except ValueError as exc:
        print(f"swarm: preset rename: {exc}", file=sys.stderr)
        return 1
    print(f"renamed user preset {args.old_name} -> {args.new_name}")
    return 0


def cmd_preset_delete(args: argparse.Namespace) -> int:
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
            line = (
                f"    - {stage['stage_id']}: agents_per_phase={stage['agents_per_phase']} "
                f"estimated_tokens_per_phase={stage['estimated_tokens_per_phase']}"
            )
            if stage.get("estimate_warning"):
                line += f" warning={stage['estimate_warning']}"
            print(line)
    if pipeline:
        print("Stage graph")
        print("\n".join(graph_lines(pipeline)))
    _print_validation(result)
    return 0 if result.ok else 1


def cmd_preset_migrate(args: argparse.Namespace) -> int:
    try:
        summary = migrate_user_pipelines()
    except Exception as exc:
        print(f"swarm: preset migrate: {exc}", file=sys.stderr)
        return 1
    print("\n".join(summary.lines()))
    return 0


def cmd_preset_adopt(args: argparse.Namespace) -> int:
    try:
        target = adopt_archived_pipeline(Path(args.archived_yaml), template=args.template, name=args.name)
    except Exception as exc:
        print(f"swarm: preset adopt: {exc}", file=sys.stderr)
        return 1
    print(f"adopted inline preset {target.stem}: {target}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(format_status(load_state()))
    data_dir = resolve_data_dir()
    event_path = data_dir / "telemetry" / "run_events.jsonl"
    event_rows = _jsonl_rows(event_path)
    print(f"  run_events: {len(event_rows)}")
    latest_checkpoint = next((row for row in reversed(event_rows) if row.get("event_type") == "checkpoint_written"), None)
    if latest_checkpoint:
        details = latest_checkpoint.get("details") if isinstance(latest_checkpoint.get("details"), dict) else {}
        print(
            "  latest_checkpoint: "
            f"run_id={latest_checkpoint.get('run_id') or 'n/a'} "
            f"phase={latest_checkpoint.get('phase_id') or 'n/a'} "
            f"source={details.get('source') or latest_checkpoint.get('reason') or 'n/a'} "
            f"path={details.get('checkpoint_path') or 'n/a'}"
        )
    observation_path = data_dir / "telemetry" / "observations.jsonl"
    observation_rows = _jsonl_rows(observation_path)
    print(f"  observations: {len(observation_rows)}")
    if observation_rows:
        latest = observation_rows[-1]
        print(
            "  latest_observation: "
            f"{latest.get('event_type', 'unknown')} "
            f"run_id={latest.get('run_id') or 'n/a'} "
            f"source={latest.get('source') or 'n/a'}"
        )
    return 0


def cmd_test(args: argparse.Namespace, extras: list[str]) -> int:
    """Dispatch to pytest and/or the bats shell layer."""
    import subprocess

    repo_root = REPO_ROOT
    passthrough = [item for item in extras if item != "--"]
    explicit_k = ["-k", args.k_expr] if args.k_expr else []
    explicit_m = ["-m", args.m_expr] if args.m_expr else []
    coverage_args = ["--cov=swarm_do", "--cov-report=term-missing"] if args.coverage else []

    def _run_pytest(default_marker: list[str]) -> int:
        marker = explicit_m if explicit_m else default_marker
        return subprocess.call(
            ["pytest", *marker, *explicit_k, *coverage_args, *passthrough],
            cwd=repo_root,
        )

    def _shellcheck_targets() -> list[str]:
        targets: list[str] = []
        for path in sorted((repo_root / "bin").iterdir()):
            if path.is_file():
                targets.append(str(path))
        targets.extend(str(path) for path in sorted((repo_root / "bin" / "_lib").glob("*.sh")))
        targets.extend(str(path) for path in sorted((repo_root / "hooks").glob("*.sh")))
        return targets

    def _run_shell() -> int:
        bats_dir = repo_root / "tests" / "shell"
        if not bats_dir.is_dir():
            print("swarm test shell: no shell tests yet (Phase 3 not done)", file=sys.stderr)
            return 0
        if not shutil.which("shellcheck"):
            print(
                "swarm test shell: `shellcheck` not found on PATH "
                "(install with `brew install shellcheck`)",
                file=sys.stderr,
            )
            return 127
        if not shutil.which("bats"):
            print(
                "swarm test shell: `bats` not found on PATH "
                "(install with `brew install bats-core`)",
                file=sys.stderr,
            )
            return 127
        rc_sc = subprocess.call(
            ["shellcheck", "--severity=warning", "-e", "SC1090,SC1091", *_shellcheck_targets()],
            cwd=repo_root,
        )
        rc_bats = subprocess.call(["bats", "-r", str(bats_dir)], cwd=repo_root)
        return rc_sc or rc_bats

    mode = args.mode or "all"
    if mode == "unit":
        return _run_pytest(["-m", "unit or not (tui or shell or live_provider or slow)"])
    if mode == "tui":
        return _run_pytest(["-m", "tui"])
    if mode == "shell":
        return _run_shell()
    if mode == "all":
        rc_py = _run_pytest([])
        rc_sh = _run_shell()
        return rc_py or rc_sh
    print(f"swarm test: unknown mode {mode!r}", file=sys.stderr)
    return 2


def cmd_trace(args: argparse.Namespace) -> int:
    from .run_trace import build_run_trace, trace_to_dict, trace_to_json

    if args.trace_command != "build":
        print("swarm: trace: missing command", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir) if args.data_dir else None
    try:
        trace = build_run_trace(args.run_id, data_dir=data_dir)
    except FileNotFoundError as exc:
        print(f"swarm: trace build: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"swarm: trace build: {exc}", file=sys.stderr)
        return 2
    payload = trace_to_json(trace)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    elif args.json:
        print(payload, end="")
    else:
        data = trace_to_dict(trace)
        print(f"run trace: {data['run_id']}")
        print(f"  phases: {data['summary']['phases']}")
        print(f"  attempts: {data['summary']['attempts']}")
        print(f"  warnings: {data['summary']['warnings']}")
        print(f"  unrecognized: {data['summary']['unrecognized']}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from .run_eval import (
        FixtureLoadError,
        discover_fixtures,
        expectation_from_trace,
        expectation_to_yaml,
        load_expectation,
        result_to_json,
        run_fixtures,
    )
    from .run_trace import build_trace_from_run_dir

    if args.eval_command == "run":
        if args.include_trace and not args.json:
            print("swarm eval: --include-trace requires --json", file=sys.stderr)
            return 2
        try:
            result = run_fixtures(Path(args.fixture_dir), include_trace=bool(args.json and args.include_trace))
        except FileNotFoundError as exc:
            payload = {"fixture_dir": args.fixture_dir, "status": "error", "error": str(exc)}
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"swarm eval: {exc}", file=sys.stderr)
            return 3
        except FixtureLoadError as exc:
            payload = {"fixture_dir": args.fixture_dir, "status": "error", "error": str(exc)}
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"swarm eval: {exc}", file=sys.stderr)
            return 2
        if getattr(args, "use_mirror", False):
            mirror_error = _eval_mirror_parity_error(
                Path(args.fixture_dir),
                discover_fixtures=discover_fixtures,
                load_expectation=load_expectation,
            )
            if mirror_error is not None and result.first_mismatch is None:
                payload = {
                    "fixture_dir": args.fixture_dir,
                    "status": "failed",
                    "error": mirror_error,
                    "first_mismatch": {
                        "kind": "mirror_parity",
                        "expected": "clean mirror projection",
                        "actual": mirror_error,
                        "path": "state.mirror.sqlite",
                    },
                }
                if args.json:
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(f"swarm eval: failed mirror_parity actual={mirror_error!r} path=state.mirror.sqlite", file=sys.stderr)
                return 1
        if args.json:
            print(result_to_json(result), end="")
        elif result.first_mismatch is None:
            print(f"swarm eval: passed {len(result.results)} fixture(s)")
        else:
            mismatch = result.first_mismatch
            print(
                f"swarm eval: failed {mismatch.kind} "
                f"expected={mismatch.expected!r} actual={mismatch.actual!r} path={mismatch.path}",
                file=sys.stderr,
            )
        return 0 if result.first_mismatch is None else 1

    if args.eval_command == "record":
        run_dir = Path(args.run_dir)
        fixture_dir = Path(args.to)
        try:
            trace = build_trace_from_run_dir(run_dir)
        except (FileNotFoundError, OSError, ValueError) as exc:
            print(f"swarm eval record: {exc}", file=sys.stderr)
            return 3
        fixture_dir.mkdir(parents=True, exist_ok=True)
        target_run = fixture_dir / "run"
        if not target_run.exists():
            shutil.copytree(run_dir, target_run)
        expectation = expectation_from_trace(trace)
        (fixture_dir / "expectation.yaml").write_text(expectation_to_yaml(expectation), encoding="utf-8")
        print(f"swarm eval record: wrote {fixture_dir / 'expectation.yaml'}")
        return 0

    print("swarm: eval: missing command", file=sys.stderr)
    return 2


def _eval_mirror_parity_error(
    fixture_dir: Path,
    *,
    discover_fixtures: Any,
    load_expectation: Any,
) -> str | None:
    import sqlite3

    from .state_projector import ProjectionError, diff_mirror, project_run

    try:
        fixtures = discover_fixtures(fixture_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return str(exc)
    for fixture in fixtures:
        try:
            expectation = load_expectation(fixture / "expectation.yaml")
            run_id = str(expectation.get("run_id") or _fixture_run_id(fixture))
            with tempfile.TemporaryDirectory(prefix="swarm-eval-mirror-") as tmp:
                data_dir = Path(tmp)
                _materialize_fixture_data_dir(fixture, run_id, data_dir)
                project_run(run_id, data_dir=data_dir)
                diffs = diff_mirror(run_id, data_dir=data_dir)
                if diffs:
                    return f"{fixture.name}: {diffs[0].to_dict()}"
        except (FileNotFoundError, OSError, ProjectionError, sqlite3.DatabaseError, ValueError) as exc:
            return f"{fixture.name}: {exc}"
    return None


def _fixture_run_id(fixture: Path) -> str:
    for name in ("phase_sessions.v1.json", "prepared_plan.v1.json"):
        path = fixture / "run" / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping) and isinstance(payload.get("run_id"), str):
            return str(payload["run_id"])
    return "run"


def _materialize_fixture_data_dir(fixture: Path, run_id: str, data_dir: Path) -> None:
    run_source = fixture / "run"
    run_target = data_dir / "runs" / run_id
    shutil.copytree(run_source, run_target)
    events = fixture / "events.jsonl"
    if events.is_file():
        telemetry = data_dir / "telemetry"
        telemetry.mkdir(parents=True, exist_ok=True)
        shutil.copy2(events, telemetry / "run_events.jsonl")
    active = fixture / "active-run.json"
    if active.is_file():
        shutil.copy2(active, data_dir / "active-run.json")
    worktree = fixture / "worktrees" / run_id
    if worktree.is_dir():
        shutil.copytree(worktree, data_dir / "worktrees" / run_id)


def cmd_state(args: argparse.Namespace) -> int:
    import sqlite3

    from .state_projector import ProjectionError, diff_mirror, project_run, query_mirror

    data_dir = Path(args.data_dir) if getattr(args, "data_dir", None) else None
    try:
        if args.state_command == "project":
            result = project_run(args.run_id, data_dir=data_dir)
            if args.json:
                print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
            else:
                print(f"state mirror: {result.mirror_path}")
                print(f"  sources: {result.source_count}")
                print(f"  warnings: {result.warning_count}")
            return 0
        if args.state_command == "mirror":
            rows = query_mirror(args.run_id, args.query, data_dir=data_dir)
            print(json.dumps(rows, indent=2, sort_keys=True))
            return 0
        if args.state_command == "diff-mirror":
            diffs = diff_mirror(args.run_id, data_dir=data_dir)
            if args.json:
                print(json.dumps([diff.to_dict() for diff in diffs], indent=2, sort_keys=True))
            elif not diffs:
                print(f"state mirror: {args.run_id} clean")
            else:
                diff = diffs[0]
                print(
                    f"state mirror: {args.run_id} differs "
                    f"table={diff.table} key={diff.primary_key} column={diff.column}"
                )
            return 0 if not diffs else 1
    except (FileNotFoundError, OSError, ProjectionError, sqlite3.DatabaseError, ValueError) as exc:
        print(f"swarm: state {args.state_command}: {exc}", file=sys.stderr)
        return 1
    print("swarm: state: missing command", file=sys.stderr)
    return 1


def _jsonl_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


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
    _print_budget_and_graph(result, pipeline)
    _print_validation(result)
    if not result.ok:
        return 1
    if args.dry_run:
        print(f"competitive preset {preset_name} is valid for {args.plan_path}")
        return 0
    _activate_preset(preset_name)
    print(f"loaded preset {preset_name}; run /swarmdaddy:do {args.plan_path} to start Pattern 5")
    return 0


def _preset_graph_name(preset_name: str, preset: dict[str, Any]) -> str:
    try:
        resolved = resolve_preset_graph(preset)
    except Exception:
        return str(preset.get("pipeline") or f"inline:{preset_name}")
    return resolved.source_name or f"inline:{preset_name}"


def _optional_existing_target_path(target: list[str]) -> str | None:
    if not target:
        return None
    joined = " ".join(target)
    candidates = [joined]
    if len(target) == 1:
        candidates.append(target[0])
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return candidate
    return None


def _print_budget_and_graph(result: Any, pipeline: dict[str, Any]) -> None:
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


def _cmd_output_profile(args: argparse.Namespace, *, profile_id: str) -> int:
    preset_name = args.preset
    plan_path = _optional_existing_target_path(args.target)
    result, preset, pipeline, _ = validate_preset_and_pipeline(preset_name, plan_path, include_budget=True)
    _print_budget_and_graph(result, pipeline)
    _print_validation(result)
    if not result.ok:
        return 1
    graph_name = _preset_graph_name(preset_name, preset)
    actual_profile = pipeline_profile_for(graph_name, pipeline)
    if actual_profile.profile_id != profile_id:
        print(
            f"swarm: {profile_id}: preset {preset_name} uses profile {actual_profile.profile_id}, expected {profile_id}",
            file=sys.stderr,
        )
        return 1
    activation_error = pipeline_activation_error(graph_name, pipeline)
    if activation_error:
        print(f"swarm: {profile_id}: {activation_error}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"{profile_id} preset {preset_name} is valid")
        return 0
    _activate_preset(preset_name)
    command = actual_profile.command_name or f"/swarmdaddy:{profile_id}"
    print(f"loaded preset {preset_name}; run {command} to dispatch the {actual_profile.label.lower()} profile")
    return 0


def cmd_brainstorm(args: argparse.Namespace) -> int:
    return _cmd_output_profile(args, profile_id="brainstorm")


def cmd_research(args: argparse.Namespace) -> int:
    return _cmd_output_profile(args, profile_id="research")


def cmd_design(args: argparse.Namespace) -> int:
    return _cmd_output_profile(args, profile_id="design")


def cmd_review(args: argparse.Namespace) -> int:
    return _cmd_output_profile(args, profile_id="review")


def cmd_prepare(args: argparse.Namespace) -> int:
    from .prepare import accept_prepared, prepare_plan_run, prepared_acceptance_summary, reject_prepared

    try:
        prepare_args = list(getattr(args, "prepare_args", []) or [])
        if not prepare_args and getattr(args, "plan_path", None):
            prepare_args = [str(args.plan_path)]
        if prepare_args and prepare_args[0] == "refresh-base":
            if len(prepare_args) != 2:
                print("swarm: prepare refresh-base: run_id is required", file=sys.stderr)
                return 1
            if getattr(args, "to_head", False) and getattr(args, "to_sha", None):
                print("swarm: prepare refresh-base: choose only one of --to-head or --to-sha", file=sys.stderr)
                return 1
            from .prepared_artifact_writer import PreparedArtifactWriter

            reason = "explicit-sha" if getattr(args, "to_sha", None) else "to-head"
            result = PreparedArtifactWriter().refresh_base(
                prepare_args[1],
                to_sha=getattr(args, "to_sha", None),
                to_head=bool(getattr(args, "to_head", False)),
                phase_id=getattr(args, "phase", None),
                dry_run=bool(getattr(args, "dry_run", False)),
                operator_id=getattr(args, "operator_id", None),
                reason=reason,
            )
            payload = result.to_dict()
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_format_prepare_refresh_base(payload))
            return 0
        if args.accept:
            summary = prepared_acceptance_summary(args.accept)
            try:
                path = accept_prepared(args.accept, accepted_by=args.accepted_by)
            except ValueError:
                if summary["stale_reasons"]:
                    print(
                        f"swarm: prepare accept: prepared artifact is stale: {', '.join(summary['stale_reasons'])}",
                        file=sys.stderr,
                    )
                    return 1
                raise
            summary["status"] = "accepted"
            summary["artifact_path"] = str(path)
            if args.json:
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                _print_prepare_acceptance_summary(summary)
                print(f"Status: ACCEPTED")
            return 0
        if args.reject:
            path = reject_prepared(args.reject, reason=args.reason or "")
            payload = {"run_id": args.reject, "status": "rejected", "artifact_path": str(path)}
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"prepared artifact rejected: {path}")
                print("Status: REJECTED")
            return 0
        plan_path = prepare_args[0] if prepare_args else None
        if len(prepare_args) > 1:
            print("swarm: prepare: only one plan_path may be supplied", file=sys.stderr)
            return 1
        if not plan_path:
            print("swarm: prepare: plan_path is required unless --accept or --reject is used", file=sys.stderr)
            return 1
        result = prepare_plan_run(
            plan_path,
            dry_run=args.dry_run,
            write=not args.dry_run,
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        else:
            _print_prepare_result(result)
        return 0 if result.status != "needs_input" else 1
    except Exception as exc:
        print(f"swarm: prepare: {exc}", file=sys.stderr)
        return 1


def _format_prepare_refresh_base(payload: Mapping[str, Any]) -> str:
    status = "dry-run" if payload.get("dry_run") else ("changed" if payload.get("changed") else "unchanged")
    lines = [
        f"prepare refresh-base: {payload.get('run_id')} {status}",
        f"  git_base_sha: {payload.get('previous_git_base_sha')} -> {payload.get('target_git_base_sha')}",
        f"  phases: {', '.join(payload.get('phase_ids') or []) or '-'}",
    ]
    for path in payload.get("touched_paths") or []:
        lines.append(f"  touched: {path}")
    for path in payload.get("backups") or []:
        lines.append(f"  backup: {path}")
    return "\n".join(lines)


def _print_prepare_result(result: Any) -> None:
    print(f"prepared run: {result.run_id}")
    print(f"prepared plan: {result.prepared_plan_path}")
    if result.artifact_path:
        print(f"artifact: {result.artifact_path}")
    print(f"findings: {len(result.lint_findings)}")
    print(f"work_unit_errors: {len(result.work_unit_errors)}")
    print(f"cache_hits: {result.cache_hits}")
    print(f"Status: {result.to_dict()['status_label']}")


def _print_prepare_acceptance_summary(summary: Mapping[str, Any]) -> None:
    print(f"prepared plan: {summary.get('prepared_plan_path')}")
    print(f"findings: {summary.get('review_finding_count')}")
    print(f"safe_fix proposals: {summary.get('safe_fix_count')}")
    print(f"work units: {summary.get('work_unit_count')}")
    print(f"allowed files: {summary.get('allowed_file_count')}")
    print(f"validation commands: {summary.get('validation_command_count')}")
    print(f"source sha: {summary.get('source_plan_sha')}")
    print(f"prepared sha: {summary.get('prepared_plan_sha')}")
    print(f"git base: {summary.get('git_base_ref')} {summary.get('git_base_sha')}")


def cmd_do(args: argparse.Namespace) -> int:
    if getattr(args, "prepare", False) or getattr(args, "prepare_continue", False):
        return _cmd_do_prepare_continue(args)
    if not args.prepared:
        print(
            "swarm: do: the helper CLI currently supports prepared dispatch only; "
            "use /swarmdaddy:do <plan-path> for legacy orchestration",
            file=sys.stderr,
        )
        return 1
    if isinstance(args.prepared, str) and args.target:
        print(
            "swarm: do: pass the prepared run id or artifact path either with "
            "--prepared=RUN_ID_OR_PATH or as the positional target, not both",
            file=sys.stderr,
        )
        return 1
    prepared_ref = args.prepared if isinstance(args.prepared, str) else args.target
    if not prepared_ref:
        print("swarm: do: --prepared requires a run id or artifact path", file=sys.stderr)
        return 1

    return _dispatch_prepared(args, prepared_ref, error_prefix="swarm: do --prepared")


def _cmd_do_prepare_continue(args: argparse.Namespace) -> int:
    if getattr(args, "prepared", None):
        print("swarm: do --prepare --continue: cannot combine with --prepared", file=sys.stderr)
        return 1
    if not getattr(args, "prepare", False) or not getattr(args, "prepare_continue", False):
        print("swarm: do --prepare: --continue is required for auto-continue", file=sys.stderr)
        return 1
    if not args.target:
        print("swarm: do --prepare --continue: plan path is required", file=sys.stderr)
        return 1

    from .prepare import (
        InvalidPreparedTransition,
        StalePreparedArtifactError,
        accept_prepared,
        auto_continue_decision,
        prepare_plan_run,
        record_prepare_continue_decision,
    )

    result: Any | None = None
    try:
        result = prepare_plan_run(
            args.target,
            dry_run=False,
            write=True,
            bd_epic_id=args.bd_epic_id,
        )
        decision = auto_continue_decision(
            result.payload,
            work_unit_errors=result.work_unit_errors,
        )
        record_prepare_continue_decision(
            result.run_id,
            allowed=decision.allowed,
            reasons=decision.reasons,
            bd_epic_id=getattr(args, "bd_epic_id", None) or getattr(result, "bd_epic_id", None),
        )
        if not decision.allowed:
            payload = result.to_dict()
            payload["auto_continue"] = decision.to_dict()
            payload["status_label"] = "NEEDS_INPUT"
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                _print_prepare_result(result)
                print(f"auto-continue blocked: {', '.join(decision.reasons)}")
                print("Status: NEEDS_INPUT")
            return 1
        accept_prepared(result.run_id, accepted_by="auto-continue")
        return _dispatch_prepared(args, result.run_id, error_prefix="swarm: do --prepare --continue")
    except StalePreparedArtifactError as exc:
        _record_prepare_continue_failure(args, result, failure_type="stale", exc=exc)
        print(f"swarm: do --prepare --continue: {exc}", file=sys.stderr)
        return 3
    except InvalidPreparedTransition as exc:
        _record_prepare_continue_failure(args, result, failure_type="transition", exc=exc)
        print(f"swarm: do --prepare --continue: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        _record_prepare_continue_failure(args, result, failure_type="validation", exc=exc)
        print(f"swarm: do --prepare --continue: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        _record_prepare_continue_failure(args, result, failure_type="unexpected", exc=exc)
        print(f"swarm: do --prepare --continue: {exc}", file=sys.stderr)
        return 1


def _record_prepare_continue_failure(
    args: argparse.Namespace,
    result: Any | None,
    *,
    failure_type: str,
    exc: BaseException,
) -> None:
    if result is None or not isinstance(getattr(result, "run_id", None), str):
        return
    from .prepare import record_prepare_continue_failed

    record_prepare_continue_failed(
        result.run_id,
        failure_type=failure_type,
        message=str(exc),
        bd_epic_id=getattr(args, "bd_epic_id", None) or getattr(result, "bd_epic_id", None),
    )


def _dispatch_prepared(
    args: argparse.Namespace,
    prepared_ref: str,
    *,
    error_prefix: str,
) -> int:
    from .prepare import (
        InvalidPreparedTransition,
        StalePreparedArtifactError,
        verify_prepared_for_dispatch,
    )
    from .run_preflight import RunPreflightError

    try:
        result = verify_prepared_for_dispatch(prepared_ref)
        preflight = _dispatch_preflight(args, result)
        payload = _prepared_dispatch_payload(args, result)
        payload["preflight"] = preflight.as_dict()
        if _phase_sessions_mode(args) == "auto":
            return _dispatch_with_phase_sessions(args, payload)
        _print_prepared_dispatch(args, payload)
        return 0
    except RunPreflightError as exc:
        if args.json:
            print(json.dumps({"error": "run_preflight_failed", "preflight": exc.report.as_dict()}, indent=2, sort_keys=True))
        print(f"{error_prefix}: {exc}", file=sys.stderr)
        return 2
    except StalePreparedArtifactError as exc:
        print(f"{error_prefix}: {exc}", file=sys.stderr)
        return 3
    except (InvalidPreparedTransition, FileNotFoundError, ValueError) as exc:
        print(f"{error_prefix}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{error_prefix}: {exc}", file=sys.stderr)
        return 1


def _prepared_dispatch_payload(args: argparse.Namespace, result: Any) -> dict[str, Any]:
    from .run_state import active_run_path, write_active_run

    payload = result.to_dict()
    if not getattr(args, "no_write_state", False):
        state_path = write_active_run(
            active_run_path(resolve_data_dir()),
            result.to_run_state(bd_epic_id=getattr(args, "bd_epic_id", None)),
        )
        payload["active_run_path"] = str(state_path)
    return payload


def _dispatch_preflight(args: argparse.Namespace, result: Any):
    from .run_preflight import record_run_preflight_completed, run_preflight

    graph = _active_graph_source_summary()
    launchers = ("claude-print",) if _phase_sessions_mode(args) == "auto" else ()
    report = run_preflight(
        run_id=result.run_id,
        target_repo=getattr(result, "repo_root", None),
        data_dir=resolve_data_dir(),
        preset=graph.get("preset"),
        graph_source=graph.get("graph_source"),
        graph_source_name=graph.get("graph_source_name"),
        launchers=launchers,
        require_provider_tier="version",
        git_base_sha=getattr(result, "git_base_sha", None),
    )
    record_run_preflight_completed(
        run_id=result.run_id,
        report=report,
        data_dir=resolve_data_dir(),
        bd_epic_id=getattr(args, "bd_epic_id", None) or getattr(result, "bd_epic_id", None),
    )
    report.raise_or_continue()
    return report


def _active_graph_source_summary() -> dict[str, str | None]:
    from .resolver import active_preset_name, load_preset_by_name

    preset_name = active_preset_name()
    if preset_name is None:
        preset = {"name": "default-fallback", "pipeline": "default", "budget": {}}
        preset_label = "default"
    else:
        preset, _path = load_preset_by_name(preset_name)
        preset_label = preset_name
    resolved = resolve_preset_graph(preset)
    return {
        "preset": preset_label,
        "graph_source": resolved.source,
        "graph_source_name": resolved.source_name,
    }


def _phase_sessions_mode(args: argparse.Namespace) -> str:
    value = getattr(args, "phase_sessions", "off") or "off"
    if value not in {"auto", "off"}:
        raise ValueError(f"unsupported phase-sessions mode: {value}")
    return value


def policy_update_from_args_and_env(args: argparse.Namespace) -> ResolvedPolicyUpdate:
    forced: dict[str, Any] = {}
    profile = getattr(args, "policy_profile", None)
    if profile:
        forced.update(expand_profile(str(profile)))
    attempt_budget = getattr(args, "max_phase_attempt_budget_usd", None)
    legacy_budget = getattr(args, "max_budget_usd", None)
    if attempt_budget is not None:
        forced["max_phase_attempt_budget_usd"] = attempt_budget
    elif legacy_budget is not None:
        forced["max_phase_attempt_budget_usd"] = legacy_budget
    for arg_name, policy_key in (
        ("max_failed_attempt_cost_usd", "max_failed_attempt_cost_usd"),
        ("max_failed_run_cost_usd", "max_failed_run_cost_usd"),
    ):
        value = getattr(args, arg_name, None)
        if value is not None:
            forced[policy_key] = value

    defaults: dict[str, Any] = {}
    env_profile = os.environ.get("SWARM_PHASE_AUTOPILOT_PROFILE")
    if env_profile:
        defaults.update(expand_profile(env_profile))
    for env_name, policy_key in (
        ("SWARM_MAX_FAILED_ATTEMPT_COST_USD", "max_failed_attempt_cost_usd"),
        ("SWARM_MAX_FAILED_RUN_COST_USD", "max_failed_run_cost_usd"),
        ("SWARM_MAX_PHASE_ATTEMPT_BUDGET_USD", "max_phase_attempt_budget_usd"),
    ):
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            defaults[policy_key] = float(raw)
    return ResolvedPolicyUpdate(forced_overrides=forced, default_overrides=defaults)


def _phase_attempt_budget_cli_value(args: argparse.Namespace) -> float | None:
    value = getattr(args, "max_phase_attempt_budget_usd", None)
    if value is not None:
        return value
    return getattr(args, "max_budget_usd", None)


def _policy_payload_for_run(run_id: str) -> dict[str, Any] | None:
    try:
        from .phase_sessions import load_phase_sessions

        retry_policy = load_phase_sessions(run_id).get("retry_policy")
    except Exception:
        return None
    if not isinstance(retry_policy, Mapping):
        return None
    return {
        "autopilot_profile": retry_policy.get("autopilot_profile"),
        "max_failed_attempt_cost_usd": retry_policy.get("max_failed_attempt_cost_usd"),
        "max_failed_run_cost_usd": retry_policy.get("max_failed_run_cost_usd"),
        "max_phase_attempt_budget_usd": retry_policy.get("max_phase_attempt_budget_usd"),
    }


def _print_prepared_dispatch(args: argparse.Namespace, payload: Mapping[str, Any]) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"prepared dispatch: {payload.get('run_id')}")
    print(f"prepared plan: {payload.get('prepared_plan_path')}")
    print(f"work-unit artifacts: {payload.get('work_unit_artifact_count')}")
    if "active_run_path" in payload:
        print(f"active run: {payload['active_run_path']}")
    print("Status: READY_FOR_DISPATCH")


def _dispatch_with_phase_sessions(args: argparse.Namespace, dispatch_payload: Mapping[str, Any]) -> int:
    from .phase_pump import format_pump_result, pump_phases

    launcher = "claude-print"
    run_id = str(dispatch_payload["run_id"])
    pump_payload = pump_phases(
        run_id,
        launcher=launcher,
        max_phases=None,
        init_if_missing=True,
        max_budget_usd=_phase_attempt_budget_cli_value(args),
        policy_update=policy_update_from_args_and_env(args),
    )
    payload = dict(dispatch_payload)
    payload["phase_sessions"] = {
        "mode": "auto",
        "launcher": launcher,
        "status": pump_payload.get("status"),
        "completed_phase_count": len(pump_payload.get("completed_phases") or []),
        "pump": pump_payload,
    }
    policy = _policy_payload_for_run(run_id)
    if policy is not None:
        payload["phase_sessions"]["policy"] = policy
    payload["status_label"] = _phase_session_status_label(str(pump_payload.get("status") or "unknown"))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_prepared_dispatch(argparse.Namespace(json=False), dispatch_payload)
        print(format_pump_result(pump_payload))
        print(f"Status: {payload['status_label']}")
    return 0 if pump_payload.get("status") == "complete" else 2


def _phase_session_status_label(status: str) -> str:
    if status == "complete":
        return "PHASES_COMPLETE"
    if status == "needs_input":
        return "NEEDS_INPUT"
    if status == "blocked":
        return "BLOCKED"
    if status == "failed":
        return "FAILED"
    if status == "failed_nonretryable":
        return "FAILED_NONRETRYABLE"
    if status == "retry_waiting":
        return "RETRY_WAITING"
    if status == "retry_exhausted":
        return "RETRY_EXHAUSTED"
    if status == "adopted_completion":
        return "ADOPTED_COMPLETION"
    if status == "ineligible":
        return "PHASE_LAUNCHER_INELIGIBLE"
    if status == "launcher_error":
        return "PHASE_LAUNCHER_ERROR"
    if status == "stale":
        return "STALE"
    return status.upper()


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


def cmd_pipeline_fork(args: argparse.Namespace) -> int:
    try:
        if args.with_preset:
            preset_path, pipeline_path = fork_preset_and_pipeline(args.with_preset, args.source, args.name)
            print(f"forked preset {args.with_preset} -> {args.name}: {preset_path}")
            if pipeline_path != Path():
                print(f"forked pipeline {args.source} -> {args.name}: {pipeline_path}")
            else:
                print(f"preset {args.name} follows stock graph {args.source}")
        else:
            path = fork_pipeline(args.source, args.name)
            print(f"forked pipeline {args.source} -> {args.name}: {path}")
    except (RuntimeError, ValueError) as exc:
        print(f"swarm: pipeline fork: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_pipeline_diff(args: argparse.Namespace) -> int:
    try:
        diff = diff_user_pipeline(args.name)
    except ValueError as exc:
        print(f"swarm: pipeline diff: {exc}", file=sys.stderr)
        return 1
    if not diff.source_name:
        print(f"user pipeline {args.name}: no recorded stock source")
        return 0
    if not diff.has_changes:
        print(f"user pipeline {args.name}: no diff against {diff.source_name}")
        return 0
    print(diff.text())
    return 0


def cmd_pipeline_drift(args: argparse.Namespace) -> int:
    try:
        drift = stock_drift_for_pipeline(args.name)
    except ValueError as exc:
        print(f"swarm: pipeline drift: {exc}", file=sys.stderr)
        return 1
    if not drift.tracked:
        print(f"user pipeline {args.name}: no tracked stock hash")
        return 0
    if drift.drifted:
        print(
            f"user pipeline {args.name}: source {drift.source_name} drifted "
            f"{drift.stored_hash} -> {drift.current_hash}"
        )
        return 1
    print(f"user pipeline {args.name}: source {drift.source_name} unchanged")
    return 0


def cmd_providers_doctor(args: argparse.Namespace) -> int:
    from .providers import format_provider_report, provider_doctor
    from .provider_review import write_review_doctor_cache

    if args.mco_timeout_seconds < 1:
        print("swarm: providers doctor: --mco-timeout-seconds must be >= 1", file=sys.stderr)
        return 1
    report = provider_doctor(
        preset_name=args.preset,
        run_mco=args.mco,
        run_review=args.review,
        backend_tier=args.backend_tier,
        mco_timeout_seconds=args.mco_timeout_seconds,
    )
    if report.review_selection is not None:
        try:
            write_review_doctor_cache(report.as_dict())
        except OSError as exc:
            print(f"warning: provider doctor cache not written: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(format_provider_report(report))
    return 0 if report.ok else 1


def cmd_providers_evidence(args: argparse.Namespace) -> int:
    from .provider_evidence import provider_evidence_summary_from_file

    try:
        print(
            provider_evidence_summary_from_file(
                args.artifact,
                max_findings=args.max_findings,
                max_errors=args.max_errors,
            )
        )
    except Exception as exc:
        print(f"swarm: providers evidence: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_providers_calibrate_consensus(args: argparse.Namespace) -> int:
    from .provider_review import calibrate_consensus_samples, format_consensus_calibration_report

    try:
        sample_path = Path(args.samples)
        samples = json.loads(sample_path.read_text(encoding="utf-8"))
        if not isinstance(samples, dict):
            raise ValueError("calibration sample root must be an object")
        report = calibrate_consensus_samples(samples)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_consensus_calibration_report(report))
            if args.output:
                print(f"  report: {args.output}")
    except Exception as exc:
        print(f"swarm: providers calibrate-consensus: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    print(f"swarm mode is deprecated; use 'swarm preset load {args.name}'", file=sys.stderr)
    if args.name == "custom":
        return cmd_preset_clear(args)
    mapped = "competitive" if args.name == "balanced-competitive" else args.name
    args.name = mapped
    return cmd_preset_load(args)


def cmd_handoff(args: argparse.Namespace) -> int:
    try:
        path = request_handoff(args.issue_id, args.to)
    except ValueError as exc:
        print(f"swarm: handoff: {exc}", file=sys.stderr)
        return 1
    print(f"handoff requested for {args.issue_id} -> {args.to} ({path})")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    run = find_in_flight(args.issue_id)
    if run is None:
        try:
            from .phase_sessions import cancel_phase_session_run, phase_session_path

            if phase_session_path(args.issue_id).is_file():
                payload = cancel_phase_session_run(args.issue_id)
                print(f"cancelled phase-session run {args.issue_id} phase={payload.get('phase_id')}")
                return 0
        except Exception as exc:
            print(f"swarm: cancel: {exc}", file=sys.stderr)
            return 1
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
    """Validate the permission contract.

    Four orthogonal checks (per the proven plugin pattern — per-agent tool
    restrictions live in agent-file YAML frontmatter; the dispatcher's
    settings.local.json holds only a minimum coordinator allowlist):

      (a) Every ``role-specs/agent-<name>.md`` parses cleanly.
      (b) Every spec that lists ``permissions`` in its consumers has a
          matching ``permissions/<short-name>.json`` derived artifact, and the
          generator reports no drift (``swarm_do.roles gen --check``).
      (c) The dispatcher settings file contains the coordinator minimum
          allowlist (``Bash(bd:*)``, ``Read``). The merge-conflict gate that
          previously tried to fold every role into one settings file is
          intentionally absent — role tools are spawn-time restrictions read
          from agent frontmatter, not install-time merges.
      (d) ``ROLE_NAMES`` (derived from the filesystem) and the role-specs
          with the ``permissions`` consumer agree.
    """

    from .permissions import (
        COORDINATOR_MINIMUM_ALLOW,
        COORDINATOR_MINIMUM_DENY,
        ROLE_NAMES,
        default_settings_path,
        load_settings,
    )

    repo_root = REPO_ROOT
    role_specs_dir = repo_root / "role-specs"
    target = Path(args.path) if args.path else default_settings_path(args.scope)

    failures: list[str] = []
    notes: list[str] = []

    notes.append(f"target: {target.resolve()}")

    # (a) role-spec parse
    spec_paths = sorted(role_specs_dir.glob("agent-*.md"))
    permissions_specs: list[str] = []
    if not spec_paths:
        failures.append(f"no role-specs found under {role_specs_dir}")
    else:
        from swarm_do.roles.spec import load as load_spec

        for spec_path in spec_paths:
            try:
                spec = load_spec(spec_path)
            except Exception as exc:
                failures.append(f"role-spec parse: {spec_path.name}: {exc}")
                continue
            if "permissions" in spec.consumers:
                permissions_specs.append(spec.name[len("agent-"):])
        notes.append(f"role-specs parsed: {len(spec_paths)}")
        notes.append(f"role-specs with permissions consumer: {len(permissions_specs)}")

    # (b) generator drift
    try:
        from swarm_do.roles.cli import _cmd_gen

        gen_args = argparse.Namespace(
            command="gen",
            write=False,
            check=True,
            force=False,
            readme_section=None,
        )
        # _cmd_gen prints to stdout when there is drift; capture status only.
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            gen_status = _cmd_gen(gen_args)
        if gen_status != 0:
            failures.append("generator drift detected (run `python3 -m swarm_do.roles gen --write`)")
            failures.append(buf.getvalue().rstrip())
    except Exception as exc:
        failures.append(f"generator check failed: {exc}")
    else:
        notes.append("generator: in sync")

    # (c) coordinator minimum allowlist
    try:
        settings = load_settings(target)
    except ValueError as exc:
        failures.append(f"settings load: {exc}")
        settings = {}
    permissions = settings.get("permissions") or {}
    allow = set(permissions.get("allow") or [])
    deny = set(permissions.get("deny") or [])
    missing_allow = [rule for rule in COORDINATOR_MINIMUM_ALLOW if rule not in allow]
    missing_deny = [rule for rule in COORDINATOR_MINIMUM_DENY if rule not in deny]
    if missing_allow or missing_deny:
        failures.append(
            "coordinator minimum allowlist not present in settings: "
            f"missing allow={missing_allow}, missing deny={missing_deny}"
        )
    else:
        notes.append("coordinator allowlist: ok")

    # (d) registry/filesystem agree
    if set(permissions_specs) != ROLE_NAMES:
        only_specs = sorted(set(permissions_specs) - ROLE_NAMES)
        only_disk = sorted(ROLE_NAMES - set(permissions_specs))
        failures.append(
            "registry drift: role-specs with permissions consumer vs permissions/*.json: "
            f"only-in-specs={only_specs}, only-in-fragments={only_disk}"
        )
    else:
        notes.append(f"role registry: in sync ({len(ROLE_NAMES)} roles)")

    print("\n".join(notes))
    if failures:
        print()
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    print("OK — permissions contract is consistent.")
    return 0


def cmd_permissions_install(args: argparse.Namespace) -> int:
    """Write the dispatcher's coordinator minimum allowlist.

    The legacy ``--role <X>`` merge-mode is intentionally removed — per-agent
    tool restrictions live in agent-file YAML frontmatter, not in this
    settings file. Use ``python3 -m swarm_do.roles gen --write`` to refresh
    derived artifacts under ``permissions/``.
    """

    from .permissions import (
        COORDINATOR_MINIMUM_ALLOW,
        COORDINATOR_MINIMUM_DENY,
        default_settings_path,
        load_settings,
        write_settings_atomic,
    )

    if args.role:
        print(
            "swarm: permissions install: --role is no longer supported. "
            "Per-agent tool restrictions live in role-specs/agent-<role>.md "
            "frontmatter and propagate via `python3 -m swarm_do.roles gen --write`. "
            "Use `swarm permissions install --scope coordinator` to write the "
            "dispatcher's minimum allowlist.",
            file=sys.stderr,
        )
        return 1

    target = Path(args.path) if args.path else default_settings_path(args.scope)
    try:
        settings = load_settings(target)
    except ValueError as exc:
        print(f"swarm: permissions install: {exc}", file=sys.stderr)
        return 1

    merged: dict[str, Any] = dict(settings)
    permissions = merged.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        print(
            "swarm: permissions install: settings.permissions must be an object",
            file=sys.stderr,
        )
        return 1
    existing_allow = list(permissions.get("allow") or [])
    existing_deny = list(permissions.get("deny") or [])
    permissions["allow"] = sorted({*existing_allow, *COORDINATOR_MINIMUM_ALLOW})
    permissions["deny"] = sorted({*existing_deny, *COORDINATOR_MINIMUM_DENY})

    print(f"target: {target.resolve()}")
    print(json.dumps(permissions, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    backup = write_settings_atomic(target, merged)
    print(f"wrote {target.resolve()}")
    if backup.exists():
        print(f"backup: {backup.resolve()}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from .resume import build_resume_report, format_resume_report, resume_exit_code

    report = build_resume_report(args.bd_id)
    if args.json:
        print(json.dumps(report.to_manifest(), indent=2, sort_keys=True))
    else:
        print(format_resume_report(report, merge=args.merge))
    if report.drift_keys and args.merge:
        print("swarm: resume: refusing to merge while drift is present", file=sys.stderr)
    return resume_exit_code(report)


def cmd_run_state(args: argparse.Namespace) -> int:
    from .run_state import active_run_path, clear_active_run, load_active_run, write_active_run, write_checkpoint_from_active

    data_dir = resolve_data_dir()
    path = active_run_path(data_dir)
    if args.run_state_command == "write":
        if args.json_file == "-":
            payload = json.loads(sys.stdin.read())
        else:
            payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        write_active_run(path, payload)
        print(path)
        return 0
    if args.run_state_command == "clear":
        clear_active_run(path)
        print(path)
        return 0
    if args.run_state_command == "checkpoint":
        state = load_active_run(path)
        if state is None:
            print("swarm: run-state checkpoint: no active run", file=sys.stderr)
            return 1
        checkpoint = write_checkpoint_from_active(data_dir, state, source=args.source, reason=args.reason)
        if checkpoint is None:
            print("swarm: run-state checkpoint: active run is missing run_id", file=sys.stderr)
            return 1
        print(checkpoint)
        return 0
    print("swarm: run-state: missing command", file=sys.stderr)
    return 1


def cmd_sessions(args: argparse.Namespace) -> int:
    from .session_capabilities import doctor_report, format_doctor_report

    if args.sessions_command != "doctor":
        print("swarm: sessions: missing command", file=sys.stderr)
        return 1
    report = doctor_report(live=args.live)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_doctor_report(report))
    requested = [args.launcher] if getattr(args, "launcher", None) else ["manual", "fake-test", "claude-print"]
    by_name = {
        item.get("name"): item
        for item in report.get("launchers", [])
        if isinstance(item, Mapping)
    }
    return 0 if all(bool(by_name.get(name, {}).get("eligible")) for name in requested) else 1


def cmd_beads(args: argparse.Namespace) -> int:
    from .beads_health import beads_where

    if args.beads_command != "check":
        print("swarm: beads: missing command", file=sys.stderr)
        return 1
    result = beads_where(Path(args.repo))
    payload = result.as_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"beads: {payload['status']} {payload['summary']}")
        if payload.get("rig"):
            print(f"rig: {payload['rig']}")
    return 0 if result.ok else 1


def cmd_context(args: argparse.Namespace) -> int:
    from .context_bundle import render_context_bundle

    if args.context_command != "render":
        print("swarm: context: missing command", file=sys.stderr)
        return 1
    try:
        result = render_context_bundle(
            run_id=args.run_id,
            phase_id=args.phase,
            role=args.role,
            unit_id=args.unit,
            max_prompt_bytes=args.max_prompt_bytes,
        )
    except Exception as exc:
        print(f"swarm: context render: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"context: {result['context_path']}")
        print(f"prompt: {result['prompt_path']}")
        warnings = result["context"].get("warnings") or []
        if warnings:
            print(f"warnings: {', '.join(warnings)}")
    return 0


def cmd_operator_decision(args: argparse.Namespace) -> int:
    from .operator_decisions import (
        OperatorDecisionError,
        apply as apply_operator_decision,
        list_decisions,
        record as record_operator_decision,
        show_decision,
    )

    try:
        command = args.operator_decision_command
        if command == "record":
            payload_arg = json.loads(args.payload)
            if not isinstance(payload_arg, dict):
                raise OperatorDecisionError(
                    "invalid-payload",
                    "operator decision payload must be a JSON object",
                )
            payload = record_operator_decision(
                args.run_id,
                args.kind,
                payload_arg,
                operator=args.operator,
            )
            exit_code = 0
        elif command == "apply":
            payload = apply_operator_decision(
                args.run_id,
                args.decision_id,
                confirm_token=args.confirm,
            )
            exit_code = 0
        elif command == "list":
            payload = list_decisions(args.run_id, status=args.status, kind=args.kind)
            exit_code = 0
        elif command == "show":
            payload = show_decision(args.run_id, args.decision_id)
            exit_code = 0
        else:
            print("swarm: operator decision: missing command", file=sys.stderr)
            return 1
    except json.JSONDecodeError as exc:
        payload = {"error": "invalid-payload-json", "message": f"operator decision payload JSON is invalid: {exc}"}
        exit_code = 2
    except OperatorDecisionError as exc:
        payload = exc.to_payload()
        exit_code = exc.exit_code
    except Exception as exc:
        payload = {"error": "operator-decision-failed", "message": f"operator decision failed: {exc}"}
        exit_code = 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif exit_code == 0:
        print(_format_operator_decision(args.operator_decision_command, payload))
    else:
        print(f"swarm: operator decision {args.operator_decision_command}: {payload.get('message')}", file=sys.stderr)
        if payload.get("confirm_token"):
            print(f"swarm: operator decision confirm token: {payload.get('confirm_token')}", file=sys.stderr)
    return exit_code


def _format_operator_decision(command: str, payload: Mapping[str, Any]) -> str:
    if command == "list":
        lines = [f"operator decision list: {payload.get('run_id')}"]
        for item in payload.get("decisions") or []:
            if isinstance(item, Mapping):
                lines.append(f"  - {item.get('decision_id')} {item.get('kind')} {item.get('status')}")
        if len(lines) == 1:
            lines.append("  no operator decisions")
        return "\n".join(lines)
    decision = payload.get("decision")
    if isinstance(decision, Mapping):
        lines = [
            f"operator decision {command}: {decision.get('decision_id')}",
            f"  kind: {decision.get('kind')}",
            f"  status: {decision.get('status')}",
        ]
        if payload.get("confirm_token"):
            lines.append(f"  confirm_token: {payload.get('confirm_token')}")
        if payload.get("path"):
            lines.append(f"  path: {payload.get('path')}")
        return "\n".join(lines)
    return json.dumps(payload, indent=2, sort_keys=True)


def cmd_phases(args: argparse.Namespace) -> int:
    from .phase_pump import format_pump_result, pump_phases
    from .phase_recovery import reconcile_phase_sessions
    from .phase_sessions import (
        archive_phase_session_evidence,
        claim_next_phase,
        init_phase_sessions,
        cancel_phase_session_run,
        cleanup_phase_generated_artifacts,
        phase_status,
        reap_expired_phases,
        record_phase_result,
        refresh_phase,
        reset_phase_session,
        start_phase,
    )

    try:
        command = args.phases_command
        if command == "init":
            payload = init_phase_sessions(args.run_id, policy_update=policy_update_from_args_and_env(args))
            exit_code = 0
        elif command == "doctor":
            from .phase_doctor import run_phase_doctor

            payload = run_phase_doctor(args.run_id)
            exit_code = 0 if not any(item.get("severity") == "error" for item in payload.get("findings") or []) else 2
        elif command == "status":
            payload = phase_status(args.run_id)
            if args.cost or args.attempts or args.events or args.include_archived:
                from .phase_attempts import summarize_phase_attempts

                evidence = summarize_phase_attempts(
                    args.run_id,
                    include_archived=args.include_archived,
                    include_events=args.events,
                )
                if args.cost:
                    payload["cost"] = evidence["cost"]
                    payload["tokens"] = evidence["tokens"]
                    payload["permission_denial_count"] = evidence["permission_denial_count"]
                if args.attempts:
                    payload["attempts"] = evidence["attempts"]
                    payload["last_failure"] = evidence["last_failure"]
                    payload["last_error"] = evidence["last_error"]
                    payload["recommended_action"] = evidence["recommended_action"]
                if args.events:
                    payload["events"] = evidence.get("events", [])
            exit_code = 0 if payload.get("status") != "drift" else 3
        elif command == "claim":
            payload = claim_next_phase(
                args.run_id,
                reclaim_stale=args.reclaim_stale,
                lease_command="bin/swarm phases claim",
            )
            exit_code = 0 if payload.get("claimed") else 2
        elif command == "start":
            payload = start_phase(
                args.run_id,
                args.phase,
                launcher=args.launcher,
                lease_owner=args.lease_owner,
                session_name=args.session_name,
                lease_command=f"bin/swarm phases start --launcher {args.launcher}",
            )
            exit_code = 0
        elif command == "refresh":
            payload = refresh_phase(args.run_id, args.phase, lease_owner=args.lease_owner)
            exit_code = 0
        elif command == "reset":
            payload = reset_phase_session(args.run_id, args.phase, hard=args.hard)
            exit_code = 0
        elif command == "redo":
            doctor = None
            worktree_reset = None
            phase_reset = None
            operator_decision = None
            if not args.no_doctor:
                from .phase_doctor import run_phase_doctor

                doctor = run_phase_doctor(args.run_id)
            if args.rebuild_worktree:
                from .execution_worktree import reset_run_worktree

                worktree_reset = reset_run_worktree(
                    args.run_id,
                    data_dir=resolve_data_dir(),
                    discard=not args.archive_branch,
                    archive_branch=bool(args.archive_branch),
                    force=bool(args.force),
                )
            if args.phase:
                if not args.rebuild_worktree:
                    from .operator_decisions import record as record_operator_decision

                    operator_decision = record_operator_decision(
                        args.run_id,
                        "retry_phase",
                        {
                            "phase_id": args.phase,
                            "reason": "phases redo requested phase repump",
                        },
                    )
                phase_reset = reset_phase_session(args.run_id, args.phase, hard=args.hard)
            max_phases = None if args.max_phases == "all" else int(args.max_phases)
            pump = pump_phases(
                args.run_id,
                launcher=args.launcher,
                max_phases=max_phases,
                init_if_missing=args.init,
                max_budget_usd=_phase_attempt_budget_cli_value(args),
                policy_update=policy_update_from_args_and_env(args),
            )
            payload = {
                "run_id": args.run_id,
                "doctor": doctor,
                "operator_decision": operator_decision,
                "worktree_reset": worktree_reset,
                "phase_reset": phase_reset,
                "pump": pump,
                "status": phase_status(args.run_id),
            }
            exit_code = 0 if pump.get("status") in {"complete", "max_phases", "manual_waiting", "checkpoint"} else 2
        elif command == "reap":
            payload = reap_expired_phases(args.run_id)
            exit_code = 0
        elif command == "recover":
            payload = reconcile_phase_sessions(args.run_id, dry_run=args.dry_run)
            exit_code = 0 if payload.get("status") not in {"drift"} else 3
        elif command == "cancel":
            payload = cancel_phase_session_run(args.run_id, phase_id=args.phase, kill_child=not args.no_kill)
            exit_code = 0
        elif command == "cleanup":
            if not args.generated_artifacts:
                raise ValueError("cleanup requires --generated-artifacts")
            payload = cleanup_phase_generated_artifacts(args.run_id, phase_id=args.phase, apply=args.apply)
            exit_code = 0
        elif command == "archive":
            payload = archive_phase_session_evidence(args.run_id, label=args.label)
            exit_code = 0
        elif command == "evidence":
            if args.attempt is not None and not args.phase:
                print("swarm: phases evidence: --attempt requires --phase", file=sys.stderr)
                return 1
            if args.raw_local and not args.json:
                print("swarm: phases evidence: --raw-local requires --json", file=sys.stderr)
                return 1
            payload, exit_code = _phase_evidence_payload(
                args.run_id,
                phase_id=args.phase,
                attempt=args.attempt,
                raw_local=args.raw_local,
            )
        elif command in {"complete", "fail", "block", "needs-input"}:
            expected = {
                "complete": "complete",
                "fail": "failed",
                "block": "blocked",
                "needs-input": "needs_input",
            }[command]
            payload = record_phase_result(
                args.run_id,
                args.phase,
                json_file=args.json_file,
                expected_status=expected,
            )
            exit_code = 0
        elif command == "pump":
            max_phases = None if args.max_phases == "all" else int(args.max_phases)
            payload = pump_phases(
                args.run_id,
                launcher=args.launcher,
                max_phases=max_phases,
                init_if_missing=args.init,
                stop_on_checkpoint=args.stop_on_checkpoint,
                fake_statuses=args.fake_status or (),
                synthetic_writes=_json_arg_list(args.synthetic_write or ()),
                synthetic_stage_complete_markers=_json_arg_list(args.synthetic_stage_complete or ()),
                max_budget_usd=_phase_attempt_budget_cli_value(args),
                policy_update=policy_update_from_args_and_env(args),
            )
            exit_code = 0 if payload.get("status") in {"complete", "max_phases", "manual_waiting", "checkpoint"} else 2
        elif command == "decisions":
            from .phase_decisions import add_shared_decision

            if args.phases_decisions_command != "add":
                print("swarm: phases decisions: missing command", file=sys.stderr)
                return 1
            applies = ["*"] if args.global_decision else list(args.applies_to or [])
            payload = add_shared_decision(
                args.run_id,
                source_phase_id=args.source_phase,
                text=args.text,
                applies_to_phase_ids=applies,
                reason=args.reason,
            )
            exit_code = 0
        else:
            print("swarm: phases: missing command", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"swarm: phases {args.phases_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.phases_command == "doctor":
        from .phase_doctor import format_phase_doctor

        print(format_phase_doctor(payload))
    elif args.phases_command == "pump":
        print(format_pump_result(payload))
    elif args.phases_command == "status":
        print(_format_phase_status(payload))
    elif args.phases_command == "recover":
        print(_format_phase_recovery(payload))
    elif args.phases_command == "cancel":
        print(_format_phase_cancel(payload))
    elif args.phases_command == "cleanup":
        print(_format_phase_cleanup(payload))
    elif args.phases_command == "archive":
        print(_format_phase_archive(payload))
    elif args.phases_command == "evidence":
        print(_format_phase_evidence(payload))
    elif args.phases_command == "redo":
        print(_format_phase_redo(payload))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


def _format_phase_redo(payload: Mapping[str, Any]) -> str:
    lines = [f"phases redo: {payload.get('run_id')}"]
    doctor = payload.get("doctor")
    if isinstance(doctor, Mapping):
        lines.append(f"  doctor: {doctor.get('status')} findings={doctor.get('finding_count')}")
        if doctor.get("recommended_command"):
            lines.append(f"  doctor_next: {doctor.get('recommended_command')}")
    if payload.get("worktree_reset"):
        lines.append("  worktree: reset")
    operator_decision = payload.get("operator_decision")
    if isinstance(operator_decision, Mapping):
        decision = operator_decision.get("decision")
        if isinstance(decision, Mapping):
            lines.append(f"  operator_decision: {decision.get('decision_id')} {decision.get('status')}")
    if payload.get("phase_reset"):
        phase_reset = payload["phase_reset"]
        if isinstance(phase_reset, Mapping):
            lines.append(f"  phase: reset {phase_reset.get('phase_id')}")
    pump = payload.get("pump")
    if isinstance(pump, Mapping):
        lines.append("  " + _indent_block(format_pump_result(pump), prefix="  ").lstrip())
    status = payload.get("status")
    if isinstance(status, Mapping):
        lines.append(f"  status: {status.get('status')}")
    return "\n".join(lines)


def _indent_block(text: str, *, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _format_phase_status(payload: Mapping[str, Any]) -> str:
    lines = [f"phase sessions: {payload.get('run_id')} status={payload.get('status')}"]
    cost = payload.get("cost")
    if isinstance(cost, Mapping):
        total = _format_optional_usd(cost.get("total_usd"))
        failed = _format_optional_usd(cost.get("failed_usd"))
        lines[0] += f" cost={total} failed={failed}"
        unknown = cost.get("unknown_attempt_count")
        if unknown:
            lines[0] += f" unknown_cost_attempts={unknown}"
    if payload.get("state_path"):
        lines.append(f"  state: {payload.get('state_path')}")
    next_phase = payload.get("next_phase")
    if isinstance(next_phase, Mapping):
        lines.append(f"  next: {next_phase.get('phase_id')} ({next_phase.get('status')})")
    active = payload.get("active_phase")
    if isinstance(active, Mapping):
        lines.append(f"  active: {active.get('phase_id')} ({active.get('status')})")
    for phase in payload.get("phases") or []:
        if isinstance(phase, Mapping):
            lines.append(
                f"  - {phase.get('phase_id')}: {phase.get('status')} "
                f"attempt={phase.get('attempt')} depends={','.join(phase.get('depends_on_phase_ids') or []) or '-'}"
            )
            if phase.get("last_failure_kind"):
                lines.append(f"      failure: {phase.get('last_failure_kind')}")
            if phase.get("retry_policy_decision"):
                lines.append(f"      retry_decision: {phase.get('retry_policy_decision')}")
            if phase.get("blocked_reason"):
                lines.append(f"      blocked_reason: {phase.get('blocked_reason')}")
            if phase.get("next_retry_at"):
                lines.append(f"      next_retry_at: {phase.get('next_retry_at')}")
            if phase.get("launch_dir"):
                lines.append(f"      launch_dir: {phase.get('launch_dir')}")
            if phase.get("recovery_context_path"):
                lines.append(f"      recovery: {phase.get('recovery_context_path')}")
    attempts = payload.get("attempts")
    if isinstance(attempts, Mapping):
        rows = [row for row in attempts.get("rows") or [] if isinstance(row, Mapping)]
        if rows:
            lines.append("  attempts:")
        for row in rows:
            cost_value = _format_attempt_cost(row)
            bits = [
                f"phase={row.get('phase_id')}",
                f"attempt={row.get('attempt')}",
                f"status={row.get('status')}",
            ]
            if row.get("failure_kind"):
                bits.append(f"failure={row.get('failure_kind')}")
            if row.get("failure_category"):
                bits.append(f"category={row.get('failure_category')}")
            if row.get("failure_retry_class"):
                bits.append(f"retry_class={row.get('failure_retry_class')}")
            if row.get("retry_decision"):
                bits.append(f"retry_decision={row.get('retry_decision')}")
            if row.get("policy_reason"):
                bits.append(f"policy_reason={row.get('policy_reason')}")
            if row.get("failure_operator_title"):
                bits.append(f"message={row.get('failure_operator_title')}")
            if row.get("evidence_path"):
                bits.append(f"evidence={row.get('evidence_path')}")
            bits.append(f"cost={cost_value}")
            if row.get("archived"):
                bits.append(f"archive={row.get('archive')}")
            lines.append("    - " + " ".join(bits))
            cleanup = row.get("cleanup")
            if isinstance(cleanup, Mapping) and cleanup.get("untracked_artifact_count"):
                lines.append(f"        untracked_artifacts={cleanup.get('untracked_artifact_count')}")
    last_failure = payload.get("last_failure")
    if isinstance(last_failure, Mapping):
        lines.append(
            "  last_failure: "
            f"phase={last_failure.get('phase_id')} "
            f"attempt={last_failure.get('attempt')} "
            f"failure={last_failure.get('failure_kind')} "
            f"category={last_failure.get('failure_category') or 'n/a'} "
            f"retry={last_failure.get('retry_decision') or 'n/a'}"
        )
    if payload.get("last_error"):
        lines.append(f"  last_error: {payload.get('last_error')}")
    if payload.get("recommended_action"):
        lines.append(f"  recommended_action: {payload.get('recommended_action')}")
    events = payload.get("events")
    if isinstance(events, list):
        lines.append("  events:")
        for row in events[-12:]:
            if isinstance(row, Mapping):
                lines.append(f"    - {row.get('timestamp')} {row.get('event_type')} {row.get('phase_id') or '-'}")
    if payload.get("recommended_command"):
        lines.append(f"  next_command: {payload.get('recommended_command')}")
    dependencies = payload.get("dependency_status") or []
    for item in dependencies:
        if isinstance(item, Mapping):
            lines.append(f"  dependency: {item.get('phase_id')} ({item.get('status')})")
    drift = payload.get("drift") or []
    for item in drift:
        lines.append(f"  drift: {item}")
    return "\n".join(lines)


def _format_optional_usd(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"${float(value):.2f}"
    return "unknown"


def _format_attempt_cost(row: Mapping[str, Any]) -> str:
    value = row.get("total_cost_usd")
    if row.get("cost_confidence") == "provider_reported" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"${float(value):.2f}"
    if row.get("cost_confidence") == "conflict":
        return "conflict"
    return "unknown"


def _format_phase_recovery(payload: Mapping[str, Any]) -> str:
    lines = [f"phase recovery: {payload.get('status')}"]
    if payload.get("blocked_reason"):
        lines.append(f"  reason: {payload.get('blocked_reason')}")
    for action in payload.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        bits = [
            f"phase={action.get('phase_id')}",
            f"attempt={action.get('attempt')}",
            f"action={action.get('action')}",
        ]
        if action.get("failure_kind"):
            bits.append(f"failure={action.get('failure_kind')}")
        if action.get("policy_reason"):
            bits.append(f"policy_reason={action.get('policy_reason')}")
        if action.get("next_retry_at"):
            bits.append(f"next_retry_at={action.get('next_retry_at')}")
        lines.append("  - " + " ".join(bits))
    status = payload.get("phase_status")
    if isinstance(status, Mapping) and status.get("recommended_command"):
        lines.append(f"  next_command: {status.get('recommended_command')}")
    return "\n".join(lines)


def _format_phase_cancel(payload: Mapping[str, Any]) -> str:
    lines = [f"phase cancel: {payload.get('run_id')} phase={payload.get('phase_id')}"]
    child = payload.get("child_process")
    if isinstance(child, Mapping):
        target = child.get("kill_target") or "none"
        attempted = "yes" if child.get("kill_attempted") else "no"
        lines.append(f"  child_alive: {child.get('child_alive_before_cancel')} kill_attempted={attempted} target={target}")
        if child.get("kill_error"):
            lines.append(f"  kill_error: {child.get('kill_error')}")
    cleanup = payload.get("cleanup")
    if isinstance(cleanup, Mapping):
        by_phase = cleanup.get("untracked_artifacts_by_phase")
        if not isinstance(by_phase, Mapping):
            by_phase = {}
        lines.append(f"  untracked_artifacts: {cleanup.get('untracked_artifact_count') or 0}")
        for cleanup_phase, paths in by_phase.items():
            if isinstance(paths, list):
                for path in paths:
                    lines.append(f"    - phase={cleanup_phase} {path}")
        commands = cleanup.get("commands")
        if isinstance(commands, Mapping):
            lines.append("  cleanup:")
            for name, command in commands.items():
                lines.append(f"    {name}: {command}")
    return "\n".join(lines)


def _format_phase_cleanup(payload: Mapping[str, Any]) -> str:
    action = "removed" if payload.get("applied") else "would remove"
    lines = [f"phase cleanup: {payload.get('run_id')} {action} {len(payload.get('existing_targets') or [])} generated artifact targets"]
    for target in payload.get("existing_targets") or []:
        lines.append(f"  - {target}")
    if not payload.get("applied"):
        lines.append("  rerun with --apply to delete these generated run artifacts")
    return "\n".join(lines)


def _format_phase_archive(payload: Mapping[str, Any]) -> str:
    lines = [f"phase archive: {payload.get('run_id')} -> {payload.get('archive_dir')}"]
    for target in payload.get("copied") or []:
        lines.append(f"  - {target}")
    return "\n".join(lines)


def _phase_evidence_payload(
    run_id: str,
    *,
    phase_id: str | None,
    attempt: int | None,
    raw_local: bool,
) -> tuple[dict[str, Any], int]:
    from .phase_evidence import attempt_evidence_path, read_attempt_evidence_manifest, redacted_attempt_evidence
    from .phase_sessions import load_phase_sessions

    base = resolve_data_dir()
    try:
        state = load_phase_sessions(run_id, data_dir=base)
    except Exception as exc:
        return {"run_id": run_id, "count": 0, "error": str(exc), "manifests": []}, 3
    paths: list[Path] = []
    for phase in state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        current_phase_id = str(phase.get("phase_id") or "")
        if phase_id is not None and current_phase_id != phase_id:
            continue
        for value in (phase.get("evidence_path"),):
            path = _phase_cli_path(value, base=base, run_id=run_id)
            if path is not None:
                paths.append(path)
        for item in phase.get("attempt_history") or []:
            if not isinstance(item, Mapping):
                continue
            item_attempt = int(item.get("attempt") or 0)
            if attempt is not None and item_attempt != attempt:
                continue
            path = _phase_cli_path(item.get("evidence_path"), base=base, run_id=run_id)
            if path is not None:
                paths.append(path)
        if attempt is not None:
            paths.append(attempt_evidence_path(base, run_id, current_phase_id, attempt))
    launch_root = base / "runs" / run_id / "phase_launches"
    if attempt is None:
        pattern = f"{phase_id}/attempt-*/evidence.json" if phase_id is not None else "*/attempt-*/evidence.json"
        paths.extend(sorted(launch_root.glob(pattern)))
    selected = _dedupe_existing_paths(paths)
    selector_specific = phase_id is not None and attempt is not None
    if selector_specific and not selected:
        return {"run_id": run_id, "phase_id": phase_id, "attempt": attempt, "count": 0, "manifests": []}, 2
    manifests: list[dict[str, Any]] = []
    try:
        for path in selected:
            manifest = read_attempt_evidence_manifest(path)
            if raw_local:
                manifests.append(manifest)
            else:
                manifests.append(redacted_attempt_evidence(manifest))
    except Exception as exc:
        return {"run_id": run_id, "count": 0, "error": str(exc), "manifests": []}, 3
    if phase_id is not None and not manifests:
        return {"run_id": run_id, "phase_id": phase_id, "attempt": attempt, "count": 0, "manifests": []}, 2
    return {"run_id": run_id, "phase_id": phase_id, "attempt": attempt, "count": len(manifests), "manifests": manifests}, 0


def _phase_cli_path(value: Any, *, base: Path, run_id: str) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = (path, REPO_ROOT / path, base / path, base / "runs" / run_id / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def _dedupe_existing_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return sorted(result, key=lambda item: str(item))


def _format_phase_evidence(payload: Mapping[str, Any]) -> str:
    lines = [f"phase evidence: {payload.get('run_id')} count={payload.get('count') or 0}"]
    if payload.get("error"):
        lines.append(f"  error: {payload.get('error')}")
    for item in payload.get("manifests") or []:
        if not isinstance(item, Mapping):
            continue
        bits = [
            f"phase={item.get('phase_id')}",
            f"attempt={item.get('attempt')}",
            f"status={item.get('status')}",
            f"launcher={item.get('launcher') or '-'}",
        ]
        if item.get("failure_kind"):
            bits.append(f"failure={item.get('failure_kind')}")
        if item.get("failure_category"):
            bits.append(f"category={item.get('failure_category')}")
        if item.get("failure_retry_class"):
            bits.append(f"retry_class={item.get('failure_retry_class')}")
        if item.get("retry_decision"):
            bits.append(f"retry_decision={item.get('retry_decision')}")
        if item.get("policy_reason"):
            bits.append(f"policy_reason={item.get('policy_reason')}")
        if item.get("changed_file_count") is not None:
            bits.append(f"changed={item.get('changed_file_count')}")
        if item.get("evidence_path"):
            bits.append(f"evidence={item.get('evidence_path')}")
        lines.append("  - " + " ".join(bits))
        if item.get("recovery_context_path"):
            lines.append(f"      recovery={item.get('recovery_context_path')}")
    return "\n".join(lines)


def cmd_plan(args: argparse.Namespace) -> int:
    from .decompose import decompose_plan_phase
    from .plan import inspect_plan, write_inspect_run
    from .prepare import accept_prepared, prepare_plan_run, reject_prepared

    try:
        if args.plan_command == "prepare":
            result = prepare_plan_run(
                args.plan_path,
                dry_run=args.dry_run,
                write=bool(args.write and not args.dry_run),
            )
            if args.json:
                print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
            else:
                _print_prepare_result(result)
            return 0 if result.status != "needs_input" else 1
        if args.plan_command == "inspect":
            reports = inspect_plan(args.plan_path, phase_id=args.phase)
            payload: dict[str, Any] = {"schema_version": 1, "reports": [report.to_dict() for report in reports]}
            if not args.no_write:
                payload["run"] = write_inspect_run(args.plan_path, reports)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                if "run" in payload:
                    run = payload["run"]
                    print(f"prepared run: {run['run_id']}")
                    print(f"inspect: {run['inspect_path']}")
                for report in reports:
                    files = "unknown" if report.estimated_files is None else str(report.estimated_files)
                    decompose = "yes" if report.requires_decomposition else "no"
                    print(
                        f"{report.phase_id}: {report.complexity} "
                        f"({report.complexity_source}); files={files}; "
                        f"bullets={report.implementation_bullets}; decompose={decompose}; {report.reason}"
                    )
            return 0
        if args.plan_command == "decompose":
            result = decompose_plan_phase(
                args.plan_path,
                args.phase,
                write_to=args.write,
                bd_epic_id=args.bd_epic_id,
                allow_rejected=args.allow_rejected,
            )
            payload = {
                "artifact": result.artifact,
                "warnings": result.lint.warnings,
                "errors": result.lint.errors,
                "retry_count": result.retry_count,
                "escalated": result.escalated,
                "rejected_path": result.rejected_path,
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for warning in result.lint.warnings:
                    print(f"warning: {warning}", file=sys.stderr)
                for error in result.lint.errors:
                    print(f"error: {error}", file=sys.stderr)
                if args.write:
                    print(args.write)
                else:
                    print(json.dumps(result.artifact, indent=2, sort_keys=True))
            return 0 if not result.lint.errors or args.allow_rejected else 1
        if args.plan_command == "accept":
            path = accept_prepared(args.run_id, accepted_by=args.accepted_by)
            msg = {"status": "accepted", "run_id": args.run_id, "path": str(path)}
            if args.json:
                print(json.dumps(msg, indent=2, sort_keys=True))
            else:
                print(f"swarm: plan accept: {path}")
            return 0
        if args.plan_command == "reject":
            path = reject_prepared(args.run_id, reason=args.reason)
            msg = {"status": "rejected", "run_id": args.run_id, "path": str(path)}
            if args.json:
                print(json.dumps(msg, indent=2, sort_keys=True))
            else:
                print(f"swarm: plan reject: {path}")
            return 0
    except Exception as exc:
        print(f"swarm: plan {args.plan_command}: {exc}", file=sys.stderr)
        return 1
    print("swarm: plan: missing command", file=sys.stderr)
    return 1


def _load_unit_state_arg(args: argparse.Namespace) -> dict[str, Any]:
    if not getattr(args, "state_json_file", None):
        return {}
    if args.state_json_file == "-":
        value = json.loads(sys.stdin.read())
    else:
        value = json.loads(Path(args.state_json_file).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("unit state must be a JSON object")
    return value


def _load_writer_return_arg(args: argparse.Namespace) -> str:
    if getattr(args, "writer_return_file", None):
        if args.writer_return_file == "-":
            return sys.stdin.read()
        return Path(args.writer_return_file).read_text(encoding="utf-8")
    value = getattr(args, "writer_return", None)
    return value if isinstance(value, str) else ""


def _migrate_work_units_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(artifact)
    migrated["schema_version"] = 2
    units = []
    for item in artifact.get("work_units") or []:
        if not isinstance(item, dict):
            continue
        unit = dict(item)
        if "allowed_files" not in unit and "files" in unit:
            unit["allowed_files"] = unit.pop("files")
        unit.setdefault("title", unit.get("id", "unit"))
        unit.setdefault("goal", "")
        unit.setdefault("context_files", [])
        unit.setdefault("blocked_files", [])
        unit.setdefault("validation_commands", [])
        unit.setdefault("expected_results", [])
        unit.setdefault("risk_tags", [])
        unit.setdefault("handoff_notes", "")
        unit.setdefault("failure_reason", None)
        units.append(unit)
    migrated["work_units"] = units
    return migrated


def cmd_work_units(args: argparse.Namespace) -> int:
    from .executor import execution_batches, load_work_units, next_resume_point, ready_work_units
    from .post_writer import build_post_writer_report, format_post_writer_report

    try:
        if args.work_units_command == "migrate":
            source = Path(args.artifact)
            artifact = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(artifact, dict):
                raise ValueError("work-unit artifact root must be an object")
            migrated = _migrate_work_units_artifact(artifact)
            lint = schema_lint_work_units(migrated)
            if lint.errors:
                raise ValueError("migrated artifact is invalid: " + "; ".join(lint.errors))
            text = json.dumps(migrated, indent=2, sort_keys=True) + "\n"
            if args.in_place:
                source.write_text(text, encoding="utf-8")
                print(source)
            else:
                print(text, end="")
            return 0
        if args.work_units_command == "lint":
            source = Path(args.artifact)
            value = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("work-unit artifact root must be an object")
            lint = schema_lint_work_units(value)
            for warning in lint.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            for error in lint.errors:
                print(f"error: {error}", file=sys.stderr)
            if lint.errors:
                return 1
            print(f"work-units OK: {args.artifact}")
            return 0
        artifact = load_work_units(args.artifact)
        if args.work_units_command == "ready":
            state = _load_unit_state_arg(args)
            payload: Any = {"ready": ready_work_units(artifact, state)}
            exit_code = 0
        elif args.work_units_command == "batches":
            state = _load_unit_state_arg(args)
            payload = {"batches": execution_batches(artifact, state, args.parallelism)}
            exit_code = 0
        elif args.work_units_command == "resume-point":
            state = _load_unit_state_arg(args)
            payload = {"resume_point": next_resume_point(artifact, state)}
            exit_code = 0
        elif args.work_units_command == "post-writer":
            payload = build_post_writer_report(
                artifact,
                args.unit_id,
                repo=args.repo,
                base_ref=args.base_ref,
                writer_return=_load_writer_return_arg(args),
                max_writer_tool_calls=args.max_writer_tool_calls,
                max_writer_output_bytes=args.max_writer_output_bytes,
                max_handoffs=args.max_handoffs,
                telemetry_tool_call_count=args.telemetry_tool_call_count,
                validation_timeout_seconds=args.validation_timeout_seconds,
            )
            if getattr(args, "emit_run_event", False):
                _emit_post_writer_run_event(args, artifact, payload)
            gate = payload.get("gate") if isinstance(payload, Mapping) else {}
            exit_code = 0 if isinstance(gate, Mapping) and gate.get("status") == "passed" else 1
        else:
            print("swarm: work-units: missing command", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"swarm: work-units {args.work_units_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if isinstance(payload, dict) and "ready" in payload:
            print("\n".join(payload["ready"]))
        elif isinstance(payload, dict) and "batches" in payload:
            for idx, batch in enumerate(payload["batches"], 1):
                print(f"batch {idx}: {', '.join(batch)}")
        elif isinstance(payload, dict) and payload.get("schema_version") == "post_writer_report.v1":
            print(format_post_writer_report(payload))
        else:
            point = payload.get("resume_point") if isinstance(payload, dict) else None
            if point:
                print(f"resume_point: {point['work_unit_id']} status={point['status']}")
            else:
                print("resume_point: complete")
    return exit_code


def _emit_post_writer_run_event(
    args: argparse.Namespace,
    artifact: Mapping[str, Any],
    report: Mapping[str, Any],
) -> None:
    from .paths import resolve_data_dir
    from .run_state import append_run_event

    run_id = getattr(args, "run_id", None) or artifact.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("--emit-run-event requires --run-id or artifact.run_id")
    unit_id = report.get("work_unit_id")
    if not isinstance(unit_id, str):
        unit_id = getattr(args, "unit_id", None)
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    diff_stat = report.get("diff_stat") if isinstance(report.get("diff_stat"), Mapping) else {}
    test_summary = report.get("test_summary") if isinstance(report.get("test_summary"), Mapping) else {}
    budget = report.get("budget_status") if isinstance(report.get("budget_status"), Mapping) else {}
    append_run_event(
        Path(args.data_dir) if getattr(args, "data_dir", None) else resolve_data_dir(),
        {
            "run_id": run_id,
            "event_type": "post_writer_report",
            "bd_epic_id": getattr(args, "bd_epic_id", None) or artifact.get("bd_epic_id"),
            "phase_id": getattr(args, "phase_id", None) or _phase_id_from_unit_id(unit_id),
            "work_unit_id": unit_id,
            "child_bead_ids": None,
            "reason": None,
            "retry_count": None,
            "handoff_count": None,
            "integration_branch_head": None,
            "details": {
                "base_ref": report.get("base_ref"),
                "gate_status": gate.get("status"),
                "failure_reasons": gate.get("failure_reasons") if isinstance(gate.get("failure_reasons"), list) else [],
                "changed_file_count": len(report.get("changed_files") or []),
                "blocked_file_violation_count": len(report.get("blocked_file_violations") or []),
                "validation_status": test_summary.get("status"),
                "budget_status": budget.get("status"),
                "files_changed": diff_stat.get("files_changed"),
            },
            "schema_ok": True,
        },
    )


def _phase_id_from_unit_id(unit_id: Any) -> str | None:
    if not isinstance(unit_id, str) or ":" not in unit_id:
        return None
    phase_id, _sep, _rest = unit_id.partition(":")
    return phase_id or None


def cmd_worktrees(args: argparse.Namespace) -> int:
    from .worktrees import (
        WorktreeMergeConflict,
        add_unit_worktree,
        ensure_integration_branch,
        integration_branch_name,
        merge_unit_branch,
        unit_branch_name,
        unit_worktree_path,
    )

    if _legacy_worktree_sensitive_repo_refused(args):
        return 1

    try:
        if args.worktrees_command == "adopt-run":
            from .execution_worktree import adopt_run_worktree

            payload = adopt_run_worktree(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                apply=bool(args.apply),
            )
        elif args.worktrees_command == "status":
            from .execution_worktree import run_worktree_status

            payload = run_worktree_status(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                include_units=bool(getattr(args, "units", False)),
            )
        elif args.worktrees_command == "reset":
            from .execution_worktree import reset_run_worktree

            payload = reset_run_worktree(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                discard=bool(args.discard),
                archive_branch=bool(args.archive_branch),
                force=bool(args.force),
            )
        elif args.worktrees_command == "cleanup-run":
            from .execution_worktree import cleanup_run_worktree

            payload = cleanup_run_worktree(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                apply=bool(args.apply),
            )
        elif args.worktrees_command == "integrate-run":
            from .execution_worktree import integrate_run_worktree

            payload = integrate_run_worktree(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                apply=bool(args.apply),
            )
        elif args.worktrees_command == "record-post-writer":
            from .execution_worktree import record_unit_post_writer_report

            payload = record_unit_post_writer_report(
                args.run_id,
                args.phase,
                args.unit,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                report_path=Path(args.report_path),
            )
        elif args.worktrees_command == "record-spec-review":
            from .execution_worktree import record_unit_spec_review_verdict

            payload = record_unit_spec_review_verdict(
                args.run_id,
                args.phase,
                args.unit,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                verdict=args.verdict,
                report_path=Path(args.report_path) if args.report_path else None,
            )
        elif args.worktrees_command == "names":
            repo = Path(args.repo)
            payload = {
                "integration_branch": integration_branch_name(args.run_id),
                "unit_branch": unit_branch_name(args.run_id, args.unit_id) if args.unit_id else None,
                "worktree_path": str(unit_worktree_path(repo, args.run_id, args.unit_id)) if args.unit_id else None,
            }
        elif args.worktrees_command == "ensure-integration":
            repo = Path(args.repo)
            payload = {"integration_branch": ensure_integration_branch(repo, args.run_id, base_ref=args.base_ref)}
        elif args.worktrees_command == "add-unit":
            repo = Path(args.repo)
            path, branch = add_unit_worktree(repo, args.run_id, args.unit_id, base_ref=args.base_ref)
            payload = {"unit_branch": branch, "worktree_path": str(path)}
        elif args.worktrees_command == "merge":
            repo = Path(args.repo)
            result = merge_unit_branch(repo, args.integration_branch, args.unit_branch)
            payload = {
                "integration_branch": result.integration_branch,
                "unit_branch": result.unit_branch,
                "head_sha": result.head_sha,
            }
        else:
            print("swarm: worktrees: missing command", file=sys.stderr)
            return 1
    except WorktreeMergeConflict as exc:
        print(f"swarm: worktrees merge: {exc}", file=sys.stderr)
        if args.json:
            print(
                json.dumps(
                    {
                        "error": "worktree_merge_conflict",
                        "integration_branch": exc.integration_branch,
                        "unit_branch": exc.unit_branch,
                        "conflicted_files": exc.conflicted_files,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 2
    except Exception as exc:
        payload = getattr(exc, "payload", None)
        if isinstance(payload, Mapping):
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif args.worktrees_command == "adopt-run":
                print(_format_worktree_adopt(payload))
            elif args.worktrees_command == "integrate-run":
                print(_format_worktree_integrate(payload))
            elif args.worktrees_command == "reset":
                print(_format_worktree_status(payload))
        print(f"swarm: worktrees {args.worktrees_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if args.worktrees_command == "adopt-run":
            print(_format_worktree_adopt(payload))
        elif args.worktrees_command == "integrate-run":
            print(_format_worktree_integrate(payload))
        elif args.worktrees_command == "cleanup-run":
            print(_format_worktree_cleanup(payload))
        elif args.worktrees_command == "status":
            print(_format_worktree_status(payload))
        elif args.worktrees_command == "reset":
            print(_format_worktree_reset(payload))
        else:
            for key, value in payload.items():
                if value is not None:
                    print(f"{key}: {value}")
    return 0


def _legacy_worktree_sensitive_repo_refused(args: argparse.Namespace) -> bool:
    if args.worktrees_command not in {"ensure-integration", "add-unit", "merge"}:
        return False
    if bool(getattr(args, "allow_source_worktree", False)):
        return False
    from .execution_workspace import is_sensitive_path

    repo = Path(args.repo).resolve(strict=False)
    if not is_sensitive_path(repo):
        return False
    print(
        "swarm: worktrees: legacy source-checkout worktrees are disabled for sensitive repos",
        file=sys.stderr,
    )
    return True


def _format_worktree_adopt(payload: Mapping[str, Any]) -> str:
    action = "applied" if payload.get("applied") else "dry-run"
    lines = [f"worktrees adopt-run: {payload.get('run_id')} {action}"]
    lines.append(f"  safe_project_root: {payload.get('safe_project_root')}")
    lines.append(f"  source_project_root: {payload.get('source_project_root')}")
    lines.append(f"  changed_files: {len(payload.get('changed_files') or [])}")
    scope_check = payload.get("scope_check") if isinstance(payload.get("scope_check"), Mapping) else {}
    decisions = scope_check.get("decisions") if isinstance(scope_check.get("decisions"), Mapping) else {}
    if decisions:
        lines.append(
            "  scope_check: "
            f"allow={decisions.get('allow', 0)} warn={decisions.get('warn', 0)} block={decisions.get('block', 0)}"
        )
    if payload.get("scope_check_path"):
        lines.append(f"  scope_check_path: {payload.get('scope_check_path')}")
    for operation in payload.get("copyback_operations") or []:
        if isinstance(operation, Mapping):
            lines.append(f"    - {operation.get('action')} {operation.get('path')} -> {operation.get('destination_path')}")
    blocked = payload.get("blocked_paths") or []
    if blocked:
        lines.append(f"  blocked_paths: {len(blocked)}")
        for item in blocked:
            if isinstance(item, Mapping):
                lines.append(f"    - {item.get('path')}: {item.get('reason')}")
    if not payload.get("applied"):
        lines.append(f"  apply: {payload.get('apply_command')}")
    return "\n".join(lines)


def _format_worktree_integrate(payload: Mapping[str, Any]) -> str:
    action = str(payload.get("status") or ("applied" if payload.get("applied") else "dry-run"))
    lines = [f"worktrees integrate-run: {payload.get('run_id')} {action}"]
    lines.append(f"  source_branch: {payload.get('source_branch')}")
    lines.append(f"  execution_branch: {payload.get('execution_branch')}")
    lines.append(f"  integration_branch: {payload.get('integration_branch')}")
    lines.append(f"  integration_project_root: {payload.get('integration_project_root')}")
    lines.append(f"  changed_files: {len(payload.get('changed_files') or [])}")
    scope_check = payload.get("scope_check") if isinstance(payload.get("scope_check"), Mapping) else {}
    decisions = scope_check.get("decisions") if isinstance(scope_check.get("decisions"), Mapping) else {}
    if decisions:
        lines.append(
            "  scope_check: "
            f"allow={decisions.get('allow', 0)} warn={decisions.get('warn', 0)} block={decisions.get('block', 0)}"
        )
    if payload.get("validation_commands"):
        lines.append(f"  validation_commands: {len(payload.get('validation_commands') or [])}")
        for command in payload.get("validation_commands") or []:
            lines.append(f"    - {command}")
    if payload.get("integration_manifest_path"):
        lines.append(f"  integration_manifest_path: {payload.get('integration_manifest_path')}")
    if payload.get("conflict_manifest_path"):
        lines.append(f"  conflict_manifest_path: {payload.get('conflict_manifest_path')}")
    blocked = payload.get("blocked_paths") or []
    if blocked:
        lines.append(f"  blocked_paths: {len(blocked)}")
        for item in blocked:
            if isinstance(item, Mapping):
                lines.append(f"    - {item.get('path')}: {item.get('reason')}")
    if payload.get("predicted_merge_command"):
        lines.append(f"  merge: {payload.get('predicted_merge_command')}")
    if not payload.get("applied"):
        lines.append(f"  apply: {payload.get('apply_command')}")
    return "\n".join(lines)


def _format_worktree_cleanup(payload: Mapping[str, Any]) -> str:
    action = "removed" if payload.get("applied") else "dry-run"
    lines = [f"worktrees cleanup-run: {payload.get('run_id')} {action}"]
    lines.append(f"  safe_git_worktree_root: {payload.get('safe_git_worktree_root')}")
    if payload.get("preserved_reason"):
        lines.append(f"  preserved: {payload.get('preserved_reason')}")
    for target in payload.get("targets") or []:
        lines.append(f"    - {target}")
    if not payload.get("applied"):
        lines.append(f"  apply: {payload.get('apply_command')}")
    return "\n".join(lines)


def _format_worktree_status(payload: Mapping[str, Any]) -> str:
    lines = [f"worktrees status: {payload.get('run_id')} status={payload.get('status')}"]
    if payload.get("manifest_path"):
        lines.append(f"  manifest: {payload.get('manifest_path')}")
    if payload.get("branch"):
        lines.append(f"  branch: {payload.get('branch')}")
    if payload.get("manifest_base_sha") or payload.get("source_base_sha"):
        lines.append(f"  base: manifest={payload.get('manifest_base_sha')} source={payload.get('source_base_sha')}")
    if payload.get("base_drift_safe"):
        lines.append("  base_drift: safe_rebuild_available")
    if payload.get("adoption_state"):
        lines.append(f"  adoption_state: {payload.get('adoption_state')}")
    commits = payload.get("unadopted_commits") or []
    if commits:
        lines.append(f"  unadopted_commits: {len(commits)}")
        for sha in commits[:8]:
            lines.append(f"    - {sha}")
    dirty = payload.get("dirty_paths") or []
    if dirty:
        lines.append(f"  dirty_paths: {len(dirty)}")
        for path in dirty[:12]:
            lines.append(f"    - {path}")
    if payload.get("recommended_command"):
        lines.append(f"  next: {payload.get('recommended_command')}")
    if payload.get("unit_drift"):
        lines.append(
            "  unit_drift: "
            f"dirty={payload.get('unit_dirty_count') or 0} "
            f"conflicted={payload.get('unit_conflict_count') or 0} "
            f"ready_unmerged={payload.get('unit_unmerged_ready_count') or 0}"
        )
    for unit in payload.get("units") or []:
        if isinstance(unit, Mapping):
            lines.append(
                "  unit: "
                f"{unit.get('phase_id')}/{unit.get('unit_id')} "
                f"merge={unit.get('merge_state')} "
                f"post_writer={unit.get('post_writer_status')} "
                f"spec_review={unit.get('spec_review_status')} "
                f"dirty={unit.get('dirty_file_count') or 0} "
                f"ahead={unit.get('branch_ahead_count') or 0}"
            )
    return "\n".join(lines)


def _format_worktree_reset(payload: Mapping[str, Any]) -> str:
    lines = [f"worktrees reset: {payload.get('run_id')} status={payload.get('status')}"]
    if payload.get("deleted_branch"):
        lines.append(f"  deleted_branch: {payload.get('deleted_branch')}")
    if payload.get("archived_branch"):
        lines.append(f"  archived_branch: {payload.get('archived_branch')}")
    if payload.get("safe_git_worktree_root"):
        lines.append(f"  removed: {payload.get('safe_git_worktree_root')}")
    for path in payload.get("removed_unit_worktrees") or []:
        lines.append(f"  removed_unit: {path}")
    for branch in payload.get("archived_unit_branches") or []:
        lines.append(f"  archived_unit_branch: {branch}")
    for branch in payload.get("deleted_unit_branches") or []:
        lines.append(f"  deleted_unit_branch: {branch}")
    return "\n".join(lines)


def cmd_stages(args: argparse.Namespace) -> int:
    from .stage_sessions import (
        load_stage_sessions,
        record_stage_adopted,
        record_stage_failed,
        stage_session_path,
    )

    try:
        if args.stages_command == "list":
            payload = load_stage_sessions(args.run_id, args.phase)
            exit_code = 0
        elif args.stages_command == "signal-complete":
            payload = record_stage_adopted(
                args.run_id,
                args.phase,
                args.stage_id,
                commit_sha=None,
                result_path=args.result,
            )
            payload["marker"] = {
                "stage_id": args.stage_id,
                "result_path": args.result,
            }
            exit_code = 0
        elif args.stages_command == "signal-failed":
            payload = record_stage_failed(
                args.run_id,
                args.phase,
                args.stage_id,
                args.failure_kind,
                args.notes,
            )
            payload["marker"] = {
                "stage_id": args.stage_id,
                "failure_kind": args.failure_kind,
                "notes": args.notes,
            }
            exit_code = 0
        else:
            print("swarm: stages: missing command", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"swarm: stages {args.stages_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.stages_command == "signal-complete":
        print("STAGE_COMPLETE " + json.dumps(payload["marker"], sort_keys=True))
    elif args.stages_command == "signal-failed":
        print("STAGE_FAILED " + json.dumps(payload["marker"], sort_keys=True))
    else:
        print(f"stages: {payload.get('run_id')} {payload.get('phase_id')}")
        print(f"state: {stage_session_path(args.run_id, args.phase)}")
        for stage in payload.get("stages") or []:
            print(f"- {stage.get('stage_id')} {stage.get('status')} {stage.get('agent_role')}")
    return exit_code


def cmd_selftest(args: argparse.Namespace) -> int:
    if getattr(args, "selftest_command", None) == "writer-phase":
        from .writer_phase_selftest import run_writer_phase_selftest

        payload = run_writer_phase_selftest()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"writer-phase selftest: {payload.get('status')}")
            for line in payload.get("summary") or []:
                print(f"  {line}")
        return 0 if payload.get("status") == "pass" else 1
    if getattr(args, "selftest_command", None) == "capability-probe":
        from .capability_probe import run_capability_probe

        payload = run_capability_probe()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"capability-probe: {payload.get('status')}")
            if payload.get("reason"):
                print(payload["reason"])
        return 0 if payload.get("status") in {"pass", "skip"} else 1
    from .selftest import format_json, format_text, run_selftest

    report = run_selftest(
        plan_path=args.plan,
        preset=args.preset,
        strict=args.strict,
    )
    if args.json:
        print(format_json(report))
    else:
        print(format_text(report))
    return report.exit_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm")
    sub = parser.add_subparsers(dest="subcommand")

    preset = sub.add_parser("preset")
    preset_sub = preset.add_subparsers(dest="preset_command")
    p = preset_sub.add_parser("load"); p.add_argument("name"); p.set_defaults(func=cmd_preset_load)
    p = preset_sub.add_parser("clear"); p.set_defaults(func=cmd_preset_clear)
    p = preset_sub.add_parser("list"); p.set_defaults(func=cmd_preset_list)
    p = preset_sub.add_parser("show"); p.add_argument("name"); p.set_defaults(func=cmd_preset_show)
    p = preset_sub.add_parser("resolve"); p.add_argument("name"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_preset_resolve)
    p = preset_sub.add_parser("save"); p.add_argument("name"); p.add_argument("--from", dest="source", required=True); p.set_defaults(func=cmd_preset_save)
    p = preset_sub.add_parser("diff"); p.add_argument("name"); p.set_defaults(func=cmd_preset_diff)
    p = preset_sub.add_parser("rename"); p.add_argument("old_name"); p.add_argument("new_name"); p.set_defaults(func=cmd_preset_rename)
    p = preset_sub.add_parser("delete"); p.add_argument("name"); p.set_defaults(func=cmd_preset_delete)
    p = preset_sub.add_parser("dry-run"); p.add_argument("name"); p.add_argument("plan_path"); p.set_defaults(func=cmd_preset_dry_run)
    p = preset_sub.add_parser("migrate"); p.set_defaults(func=cmd_preset_migrate)
    p = preset_sub.add_parser("adopt")
    p.add_argument("archived_yaml")
    p.add_argument("--template", required=True)
    p.add_argument("--name")
    p.set_defaults(func=cmd_preset_adopt)

    pipeline = sub.add_parser("pipeline")
    pipeline_sub = pipeline.add_subparsers(dest="pipeline_command")
    p = pipeline_sub.add_parser("list"); p.set_defaults(func=cmd_pipeline_list)
    p = pipeline_sub.add_parser("show"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_show)
    p = pipeline_sub.add_parser("lint"); p.add_argument("path"); p.set_defaults(func=cmd_pipeline_lint)
    p = pipeline_sub.add_parser("set"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_set)
    p = pipeline_sub.add_parser("fork")
    p.add_argument("source")
    p.add_argument("name")
    p.add_argument("--with-preset", help="fork this source preset and point it at the new pipeline name")
    p.set_defaults(func=cmd_pipeline_fork)
    p = pipeline_sub.add_parser("diff"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_diff)
    p = pipeline_sub.add_parser("drift"); p.add_argument("name"); p.set_defaults(func=cmd_pipeline_drift)

    providers = sub.add_parser("providers")
    providers_sub = providers.add_subparsers(dest="providers_command")
    p = providers_sub.add_parser("doctor")
    p.add_argument("--preset", default="current", help="preset to inspect; default is the active preset, falling back to default pipeline")
    p.add_argument("--mco", action="store_true", help="also run mco doctor --json")
    p.add_argument("--review", action="store_true", help="run internal swarm-review provider shim diagnostics")
    p.add_argument("--backend-tier", choices=["path", "version", "handshake"], default="path")
    p.add_argument("--mco-timeout-seconds", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_providers_doctor)
    p = providers_sub.add_parser("evidence")
    p.add_argument("artifact", help="provider-findings.json artifact path")
    p.add_argument("--max-findings", type=int, default=5)
    p.add_argument("--max-errors", type=int, default=5)
    p.set_defaults(func=cmd_providers_evidence)
    p = providers_sub.add_parser("calibrate-consensus")
    p.add_argument("samples", help="provider-review consensus calibration sample JSON")
    p.add_argument("--output", help="write the full calibration report JSON to this path")
    p.add_argument("--json", action="store_true", help="print the full calibration report JSON")
    p.set_defaults(func=cmd_providers_calibrate_consensus)

    mode = sub.add_parser("mode")
    mode.add_argument("name", choices=["claude-only", "codex-only", "balanced", "brainstorm", "research", "design", "review", "custom"])
    mode.set_defaults(func=cmd_mode)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    test = sub.add_parser(
        "test",
        help="run the swarm-do test suites",
        description=(
            "Run pytest and/or the bats shell layer. Use `-k`/`-m` for selection, "
            "or place raw pytest args after `--`."
        ),
    )
    test.add_argument("mode", nargs="?", choices=["unit", "tui", "shell", "all"], default=None)
    test.add_argument("--coverage", action="store_true", help="enable coverage measurement (needs dev extras)")
    test.add_argument("-k", dest="k_expr", default=None, help="pytest -k expression")
    test.add_argument("-m", dest="m_expr", default=None, help="pytest -m expression (overrides default mode marker)")
    test.set_defaults(func=cmd_test)

    trace = sub.add_parser("trace")
    trace_sub = trace.add_subparsers(dest="trace_command")
    p = trace_sub.add_parser("build")
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.add_argument("--data-dir")
    p.set_defaults(func=cmd_trace)

    eval_cmd = sub.add_parser("eval")
    eval_sub = eval_cmd.add_subparsers(dest="eval_command")
    p = eval_sub.add_parser("run")
    p.add_argument("fixture_dir")
    p.add_argument("--json", action="store_true")
    p.add_argument("--include-trace", action="store_true", help="include full trace payloads in --json output")
    p.add_argument("--use-mirror", action="store_true")
    p.set_defaults(func=cmd_eval)
    p = eval_sub.add_parser("record")
    p.add_argument("run_dir")
    p.add_argument("--to", required=True)
    p.set_defaults(func=cmd_eval)

    operator_decision = sub.add_parser(
        "operator-decision",
        description=(
            "Record, apply, and inspect operator decision recovery artifacts. "
            "Operator decisions are not authenticated; do not use this artifact as a security boundary. "
            "operator_decisions.v1.json grows monotonically until the run directory is archived."
        ),
        help="record or apply an operator decision recovery artifact",
    )
    operator_decision_sub = operator_decision.add_subparsers(dest="operator_decision_command")
    p = operator_decision_sub.add_parser(
        "record",
        help="record an operator decision without mutating happy-path pump state",
        description=(
            "Record an operator decision. Operator decisions are not authenticated; "
            "do not use this artifact as a security boundary."
        ),
    )
    p.add_argument("run_id")
    p.add_argument("--kind", required=True)
    p.add_argument("--payload", required=True, help="operator decision payload JSON object")
    p.add_argument("--operator", help="operator decision identity as local:<id> or ci:<id>; emails are rejected")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_operator_decision)
    p = operator_decision_sub.add_parser(
        "apply",
        help="apply an integrated operator decision recovery command",
        description=(
            "Apply an operator decision. Destructive operator decisions require "
            "--confirm with the first 8 chars of the decision id."
        ),
    )
    p.add_argument("run_id")
    p.add_argument("decision_id")
    p.add_argument("--confirm", help="first 8 chars of the operator decision id for destructive kinds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_operator_decision)
    p = operator_decision_sub.add_parser("list", help="list operator decision recovery records")
    p.add_argument("run_id")
    p.add_argument("--status")
    p.add_argument("--kind")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_operator_decision)
    p = operator_decision_sub.add_parser("show", help="show one operator decision recovery record")
    p.add_argument("run_id")
    p.add_argument("decision_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_operator_decision)

    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_command")
    p = state_sub.add_parser("project")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_state)
    p = state_sub.add_parser("mirror")
    p.add_argument("run_id")
    p.add_argument("--query", required=True)
    p.add_argument("--data-dir")
    p.set_defaults(func=cmd_state)
    p = state_sub.add_parser("diff-mirror")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_state)

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

    brainstorm = sub.add_parser("brainstorm")
    brainstorm.add_argument("target", nargs="*", help="optional topic or existing file path for budget estimation")
    brainstorm.add_argument("--preset", default="brainstorm")
    brainstorm.add_argument("--dry-run", action="store_true")
    brainstorm.set_defaults(func=cmd_brainstorm)

    research = sub.add_parser("research")
    research.add_argument("target", nargs="*", help="optional research question or existing file path for budget estimation")
    research.add_argument("--preset", default="research")
    research.add_argument("--dry-run", action="store_true")
    research.set_defaults(func=cmd_research)

    design = sub.add_parser("design")
    design.add_argument("target", nargs="*", help="optional design prompt or existing file path for budget estimation")
    design.add_argument("--preset", default="design")
    design.add_argument("--dry-run", action="store_true")
    design.set_defaults(func=cmd_design)

    review = sub.add_parser("review")
    review.add_argument("target", nargs="*", help="optional branch, PR, diff, or existing file path for budget estimation")
    review.add_argument("--preset", default="review")
    review.add_argument("--dry-run", action="store_true")
    review.set_defaults(func=cmd_review)

    do = sub.add_parser("do")
    do.add_argument("target", nargs="?", help="legacy plan path, plan path with --prepare --continue, or prepared artifact path with --prepared")
    do.add_argument("--prepared", nargs="?", const=True, metavar="RUN_ID_OR_PATH")
    do.add_argument("--prepare", action="store_true", help="run the prepare gate before dispatch")
    do.add_argument("--continue", dest="prepare_continue", action="store_true", help="auto-accept safe prepared output and continue dispatch")
    do.add_argument("--phase-sessions", choices=["auto", "off"], default="off", help="run accepted prepared phases through the fresh-session pump")
    do.add_argument("--max-budget-usd", type=float, help="forwarded to the claude-print phase-session launcher")
    _add_phase_policy_flags(do)
    do.add_argument("--bd-epic-id")
    do.add_argument("--no-write-state", action="store_true")
    do.add_argument("--json", action="store_true")
    do.set_defaults(func=cmd_do)

    prepare = sub.add_parser("prepare")
    prepare.add_argument(
        "prepare_args",
        nargs="*",
        help="plan path to prepare, or `refresh-base RUN_ID`",
    )
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument(
        "--auto-mechanical-fixes",
        action="store_true",
        help="reserved for slash-command policy; deterministic fixes are always summarized",
    )
    prepare.add_argument("--accept", metavar="RUN_ID")
    prepare.add_argument("--reject", metavar="RUN_ID")
    prepare.add_argument("--accepted-by", default="human")
    prepare.add_argument("--reason", default="")
    prepare.add_argument("--to-head", action="store_true", help="refresh-base: resolve the prepared base to the current git_base_ref")
    prepare.add_argument("--to-sha", help="refresh-base: set the prepared base to an explicit commit sha")
    prepare.add_argument("--phase", help="refresh-base: refresh one phase id instead of every phase")
    prepare.add_argument("--operator-id", help="refresh-base: operator id to record in the audit event")
    prepare.add_argument("--json", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

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
    resume.add_argument("--json", action="store_true", help="emit the machine-readable resume manifest")
    resume.set_defaults(func=cmd_resume)

    run_state = sub.add_parser("run-state")
    run_state_sub = run_state.add_subparsers(dest="run_state_command")
    p = run_state_sub.add_parser("write")
    p.add_argument("--json-file", required=True, help="active-run JSON payload file, or - for stdin")
    p.set_defaults(func=cmd_run_state)
    p = run_state_sub.add_parser("clear")
    p.set_defaults(func=cmd_run_state)
    p = run_state_sub.add_parser("checkpoint")
    p.add_argument("--source", default="dispatcher-fallback")
    p.add_argument("--reason", default="end-of-unit")
    p.set_defaults(func=cmd_run_state)

    sessions = sub.add_parser("sessions")
    sessions_sub = sessions.add_subparsers(dest="sessions_command")
    p = sessions_sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--launcher", choices=["manual", "fake-test", "claude-print", "interactive"])
    p.set_defaults(func=cmd_sessions)

    beads = sub.add_parser("beads")
    beads_sub = beads.add_subparsers(dest="beads_command")
    p = beads_sub.add_parser("check")
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_beads)

    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="context_command")
    p = context_sub.add_parser("render")
    p.add_argument("--run-id", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--role", required=True, choices=["dispatcher", "agent-writer", "agent-spec-review", "agent-review", "agent-docs"])
    p.add_argument("--unit")
    p.add_argument("--max-prompt-bytes", type=int, default=24000)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_context)

    phases = sub.add_parser("phases")
    phases_sub = phases.add_subparsers(dest="phases_command")
    p = phases_sub.add_parser("init")
    p.add_argument("run_id")
    _add_phase_policy_flags(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("doctor")
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("status")
    p.add_argument("run_id")
    p.add_argument("--cost", action="store_true")
    p.add_argument("--attempts", action="store_true")
    p.add_argument("--events", action="store_true")
    p.add_argument("--include-archived", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("claim")
    p.add_argument("run_id")
    p.add_argument("--reclaim-stale", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("start")
    p.add_argument("run_id")
    p.add_argument("--phase", required=True)
    p.add_argument("--launcher", required=True)
    p.add_argument("--lease-owner")
    p.add_argument("--session-name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("refresh")
    p.add_argument("run_id")
    p.add_argument("--phase", required=True)
    p.add_argument("--lease-owner", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("reset")
    p.add_argument("run_id")
    p.add_argument("--phase", required=True)
    p.add_argument("--hard", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("redo")
    p.add_argument("run_id")
    p.add_argument("--phase")
    p.add_argument("--hard", action="store_true")
    p.add_argument("--rebuild-worktree", action="store_true")
    p.add_argument("--archive-branch", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--launcher", default="claude-print", choices=["manual", "fake-test", "claude-print"])
    p.add_argument("--max-phases", default="1")
    p.add_argument("--init", action="store_true")
    p.add_argument("--no-doctor", action="store_true")
    p.add_argument("--max-budget-usd", type=float)
    _add_phase_policy_flags(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    for name in ("complete", "fail", "block", "needs-input"):
        p = phases_sub.add_parser(name)
        p.add_argument("run_id")
        p.add_argument("--phase", required=True)
        p.add_argument("--json-file", required=True)
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("reap")
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("recover")
    p.add_argument("run_id")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("cancel")
    p.add_argument("run_id")
    p.add_argument("--phase")
    p.add_argument("--no-kill", action="store_true", help="mark cancelled without signalling the child process")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("cleanup")
    p.add_argument("run_id")
    p.add_argument("--phase")
    p.add_argument("--generated-artifacts", action="store_true")
    p.add_argument("--apply", action="store_true", help="delete the listed generated run artifacts")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("archive")
    p.add_argument("run_id")
    p.add_argument("--label")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("evidence")
    p.add_argument("run_id")
    p.add_argument("--phase")
    p.add_argument("--attempt", type=int)
    p.add_argument("--raw-local", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("pump")
    p.add_argument("run_id")
    p.add_argument("--launcher", required=True, choices=["manual", "fake-test", "claude-print"])
    p.add_argument("--max-phases", default="1")
    p.add_argument("--init", action="store_true", help="initialize phase-session state when missing")
    p.add_argument("--stop-on-checkpoint", action="store_true")
    p.add_argument("--fake-status", action="append", choices=["complete", "failed", "blocked", "needs_input"], help=argparse.SUPPRESS)
    p.add_argument("--synthetic-write", action="append", help=argparse.SUPPRESS)
    p.add_argument("--synthetic-stage-complete", action="append", help=argparse.SUPPRESS)
    p.add_argument("--max-budget-usd", type=float)
    _add_phase_policy_flags(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phases)
    p = phases_sub.add_parser("decisions")
    p.add_argument("run_id")
    decisions_sub = p.add_subparsers(dest="phases_decisions_command")
    d = decisions_sub.add_parser("add")
    d.add_argument("--source-phase", required=True)
    d.add_argument("--text", required=True)
    d.add_argument("--applies-to", action="append")
    d.add_argument("--global", dest="global_decision", action="store_true")
    d.add_argument("--reason")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_phases)

    plan = sub.add_parser("plan")
    plan_sub = plan.add_subparsers(dest="plan_command")
    p = plan_sub.add_parser("prepare")
    p.add_argument("plan_path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)
    p = plan_sub.add_parser("inspect")
    p.add_argument("plan_path")
    p.add_argument("--phase")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true", help="skip prepared run artifact writes")
    p.set_defaults(func=cmd_plan)
    p = plan_sub.add_parser("decompose")
    p.add_argument("plan_path")
    p.add_argument("--phase", required=True)
    p.add_argument("--write")
    p.add_argument("--bd-epic-id")
    p.add_argument("--allow-rejected", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)
    p = plan_sub.add_parser("accept")
    p.add_argument("run_id")
    p.add_argument("--accepted-by", default="human")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)
    p = plan_sub.add_parser("reject")
    p.add_argument("run_id")
    p.add_argument("--reason", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    work_units = sub.add_parser("work-units")
    work_units_sub = work_units.add_subparsers(dest="work_units_command")
    p = work_units_sub.add_parser("lint")
    p.add_argument("artifact")
    p.set_defaults(func=cmd_work_units)
    p = work_units_sub.add_parser("migrate")
    p.add_argument("artifact")
    p.add_argument("--in-place", action="store_true")
    p.set_defaults(func=cmd_work_units)
    p = work_units_sub.add_parser("ready")
    p.add_argument("artifact")
    p.add_argument("--state-json-file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_work_units)
    p = work_units_sub.add_parser("batches")
    p.add_argument("artifact")
    p.add_argument("--state-json-file")
    p.add_argument("--parallelism", type=int, default=1)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_work_units)
    p = work_units_sub.add_parser("resume-point")
    p.add_argument("artifact")
    p.add_argument("--state-json-file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_work_units)
    p = work_units_sub.add_parser("post-writer")
    p.add_argument("artifact")
    p.add_argument("--unit-id", required=True)
    p.add_argument("--repo", default=".")
    p.add_argument("--base-ref")
    p.add_argument("--writer-return-file")
    p.add_argument("--writer-return")
    p.add_argument("--max-writer-tool-calls", type=int, default=60)
    p.add_argument("--max-writer-output-bytes", type=int, default=60_000)
    p.add_argument("--max-handoffs", type=int, default=1)
    p.add_argument("--telemetry-tool-call-count", type=int)
    p.add_argument("--validation-timeout-seconds", type=int)
    p.add_argument("--emit-run-event", action="store_true")
    p.add_argument("--run-id")
    p.add_argument("--bd-epic-id")
    p.add_argument("--phase-id")
    p.add_argument("--data-dir")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_work_units)

    worktrees = sub.add_parser("worktrees")
    worktrees_sub = worktrees.add_subparsers(dest="worktrees_command")
    p = worktrees_sub.add_parser("names")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--unit-id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("ensure-integration")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--allow-source-worktree", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("add-unit")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--unit-id", required=True)
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--allow-source-worktree", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("merge")
    p.add_argument("--repo", default=".")
    p.add_argument("--integration-branch", required=True)
    p.add_argument("--unit-branch", required=True)
    p.add_argument("--allow-source-worktree", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("adopt-run")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("status")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--units", action="store_true", help="include per-unit worktree details")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("reset")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--discard", action="store_true")
    mode.add_argument("--archive-branch", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("integrate-run")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("record-post-writer")
    p.add_argument("run_id")
    p.add_argument("--phase", required=True)
    p.add_argument("--unit", required=True)
    p.add_argument("--report-path", required=True)
    p.add_argument("--data-dir")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("record-spec-review")
    p.add_argument("run_id")
    p.add_argument("--phase", required=True)
    p.add_argument("--unit", required=True)
    p.add_argument("--verdict", required=True, choices=["approved", "rejected", "skipped"])
    p.add_argument("--report-path")
    p.add_argument("--data-dir")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("cleanup-run")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)

    stages = sub.add_parser("stages")
    stages_sub = stages.add_subparsers(dest="stages_command")
    p = stages_sub.add_parser("list")
    p.add_argument("run_id")
    p.add_argument("phase")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stages)
    p = stages_sub.add_parser("signal-complete")
    p.add_argument("run_id")
    p.add_argument("phase")
    p.add_argument("stage_id")
    p.add_argument("--result", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stages)
    p = stages_sub.add_parser("signal-failed")
    p.add_argument("run_id")
    p.add_argument("phase")
    p.add_argument("stage_id")
    p.add_argument("--failure-kind", required=True)
    p.add_argument("--notes")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stages)

    permissions = sub.add_parser("permissions")
    permissions_sub = permissions.add_subparsers(dest="permissions_command")
    p = permissions_sub.add_parser("check")
    p.add_argument("--scope", choices=["repo", "user"], default="repo")
    p.add_argument("--path")
    # --role kept for back-compat; ignored by the new check semantics.
    p.add_argument("--role", action="append")
    p.set_defaults(func=cmd_permissions_check)
    p = permissions_sub.add_parser("install")
    p.add_argument("--scope", choices=["repo", "user"], default="repo")
    p.add_argument("--path")
    p.add_argument("--dry-run", action="store_true")
    # --role retained so legacy invocations error out with a useful message.
    p.add_argument("--role", action="append")
    p.set_defaults(func=cmd_permissions_install)
    selftest = sub.add_parser("selftest")
    selftest.add_argument("selftest_command", nargs="?", choices=["writer-phase", "capability-probe"])
    selftest.add_argument("--plan", help="optional plan path; enables preset-dry-run check")
    selftest.add_argument("--preset", help="preset to inspect; defaults to active preset (or stock default pipeline)")
    selftest.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    selftest.add_argument("--strict", action="store_true", help="upgrade advisory failures to non-zero exit")
    selftest.set_defaults(func=cmd_selftest)

    return parser


def _add_phase_policy_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--policy-profile", choices=["standard", "dogfood", "strict"])
    parser.add_argument("--max-failed-attempt-cost-usd", type=float)
    parser.add_argument("--max-failed-run-cost-usd", type=float)
    parser.add_argument("--max-phase-attempt-budget-usd", type=float)


def _json_arg_list(values: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for value in values:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("synthetic JSON arguments must be objects")
        out.append(parsed)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, extras = parser.parse_known_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    resolve_data_dir().mkdir(parents=True, exist_ok=True)
    if args.func is cmd_test:
        return args.func(args, extras)
    if extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
