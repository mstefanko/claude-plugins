"""`swarm` CLI for preset and pipeline registry operations."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
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
from .validation import schema_lint_pipeline, schema_lint_work_units, validate_preset_and_pipeline


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
        if args.accept:
            summary = prepared_acceptance_summary(args.accept)
            if summary["stale_reasons"]:
                print(
                    f"swarm: prepare accept: prepared artifact is stale: {', '.join(summary['stale_reasons'])}",
                    file=sys.stderr,
                )
                return 1
            path = accept_prepared(args.accept, accepted_by=args.accepted_by)
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
        if not args.plan_path:
            print("swarm: prepare: plan_path is required unless --accept or --reject is used", file=sys.stderr)
            return 1
        result = prepare_plan_run(
            args.plan_path,
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
    if not args.prepared:
        print(
            "swarm: do: the helper CLI currently supports prepared dispatch only; "
            "use /swarmdaddy:do <plan-path> for legacy orchestration",
            file=sys.stderr,
        )
        return 1
    prepared_ref = args.prepared if isinstance(args.prepared, str) else args.target
    if not prepared_ref:
        print("swarm: do: --prepared requires a run id or artifact path", file=sys.stderr)
        return 1

    from .prepare import verify_prepared_for_dispatch
    from .run_state import active_run_path, write_active_run

    try:
        result = verify_prepared_for_dispatch(prepared_ref)
        payload = result.to_dict()
        if not args.no_write_state:
            state_path = write_active_run(
                active_run_path(resolve_data_dir()),
                result.to_run_state(bd_epic_id=args.bd_epic_id),
            )
            payload["active_run_path"] = str(state_path)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"prepared dispatch: {result.run_id}")
            print(f"prepared plan: {result.prepared_plan_path}")
            print(f"work-unit artifacts: {len(result.work_unit_artifacts)}")
            if "active_run_path" in payload:
                print(f"active run: {payload['active_run_path']}")
            print("Status: READY_FOR_DISPATCH")
        return 0
    except Exception as exc:
        print(f"swarm: do --prepared: {exc}", file=sys.stderr)
        return 1


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
        mco_timeout_seconds=args.mco_timeout_seconds,
    )
    if report.review_selection is not None:
        write_review_doctor_cache(report.as_dict())
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
        state = _load_unit_state_arg(args)
        if args.work_units_command == "ready":
            payload: Any = {"ready": ready_work_units(artifact, state)}
        elif args.work_units_command == "batches":
            payload = {"batches": execution_batches(artifact, state, args.parallelism)}
        elif args.work_units_command == "resume-point":
            payload = {"resume_point": next_resume_point(artifact, state)}
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
        else:
            point = payload.get("resume_point") if isinstance(payload, dict) else None
            if point:
                print(f"resume_point: {point['work_unit_id']} status={point['status']}")
            else:
                print("resume_point: complete")
    return 0


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

    repo = Path(args.repo)
    try:
        if args.worktrees_command == "names":
            payload = {
                "integration_branch": integration_branch_name(args.run_id),
                "unit_branch": unit_branch_name(args.run_id, args.unit_id) if args.unit_id else None,
                "worktree_path": str(unit_worktree_path(repo, args.run_id, args.unit_id)) if args.unit_id else None,
            }
        elif args.worktrees_command == "ensure-integration":
            payload = {"integration_branch": ensure_integration_branch(repo, args.run_id, base_ref=args.base_ref)}
        elif args.worktrees_command == "add-unit":
            path, branch = add_unit_worktree(repo, args.run_id, args.unit_id, base_ref=args.base_ref)
            payload = {"unit_branch": branch, "worktree_path": str(path)}
        elif args.worktrees_command == "merge":
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
        print(f"swarm: worktrees {args.worktrees_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            if value is not None:
                print(f"{key}: {value}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm")
    sub = parser.add_subparsers(dest="subcommand")

    preset = sub.add_parser("preset")
    preset_sub = preset.add_subparsers(dest="preset_command")
    p = preset_sub.add_parser("load"); p.add_argument("name"); p.set_defaults(func=cmd_preset_load)
    p = preset_sub.add_parser("clear"); p.set_defaults(func=cmd_preset_clear)
    p = preset_sub.add_parser("list"); p.set_defaults(func=cmd_preset_list)
    p = preset_sub.add_parser("show"); p.add_argument("name"); p.set_defaults(func=cmd_preset_show)
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
    do.add_argument("target", nargs="?", help="legacy plan path, or prepared artifact path with --prepared")
    do.add_argument("--prepared", nargs="?", const=True, metavar="RUN_ID_OR_PATH")
    do.add_argument("--bd-epic-id")
    do.add_argument("--no-write-state", action="store_true")
    do.add_argument("--json", action="store_true")
    do.set_defaults(func=cmd_do)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("plan_path", nargs="?", help="plan path to prepare")
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
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("add-unit")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--unit-id", required=True)
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)
    p = worktrees_sub.add_parser("merge")
    p.add_argument("--repo", default=".")
    p.add_argument("--integration-branch", required=True)
    p.add_argument("--unit-branch", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)

    permissions = sub.add_parser("permissions")
    permissions_sub = permissions.add_subparsers(dest="permissions_command")
    p = permissions_sub.add_parser("check")
    from .permissions import ROLE_NAMES

    permission_roles = sorted(ROLE_NAMES)
    p.add_argument("--role", action="append", choices=permission_roles)
    p.add_argument("--scope", choices=["repo", "user"], default="repo")
    p.add_argument("--path")
    p.set_defaults(func=cmd_permissions_check)
    p = permissions_sub.add_parser("install")
    p.add_argument("--role", action="append", required=True, choices=permission_roles)
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
