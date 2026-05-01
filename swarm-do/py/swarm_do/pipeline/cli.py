"""`swarm` CLI for preset and pipeline registry operations."""

from __future__ import annotations

import argparse
import json
import os
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
from .validation import schema_lint_pipeline, schema_lint_work_units, validate_preset_and_pipeline
from .phase_autopilot_policy import ResolvedPolicyUpdate, expand_profile


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

    try:
        result = verify_prepared_for_dispatch(prepared_ref)
        payload = _prepared_dispatch_payload(args, result)
        if _phase_sessions_mode(args) == "auto":
            return _dispatch_with_phase_sessions(args, payload)
        _print_prepared_dispatch(args, payload)
        return 0
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
    return 0 if all(item.get("eligible") for item in report.get("launchers", []) if item.get("name") in {"manual", "fake-test"}) else 1


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
        start_phase,
    )

    try:
        command = args.phases_command
        if command == "init":
            payload = init_phase_sessions(args.run_id, policy_update=policy_update_from_args_and_env(args))
            exit_code = 0
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
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


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
        elif args.worktrees_command == "cleanup-run":
            from .execution_worktree import cleanup_run_worktree

            payload = cleanup_run_worktree(
                args.run_id,
                data_dir=Path(args.data_dir) if args.data_dir else resolve_data_dir(),
                apply=bool(args.apply),
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
        print(f"swarm: worktrees {args.worktrees_command}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if args.worktrees_command == "adopt-run":
            print(_format_worktree_adopt(payload))
        elif args.worktrees_command == "cleanup-run":
            print(_format_worktree_cleanup(payload))
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


def cmd_selftest(args: argparse.Namespace) -> int:
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

    sessions = sub.add_parser("sessions")
    sessions_sub = sessions.add_subparsers(dest="sessions_command")
    p = sessions_sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--live", action="store_true")
    p.set_defaults(func=cmd_sessions)

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
    p = worktrees_sub.add_parser("cleanup-run")
    p.add_argument("run_id")
    p.add_argument("--data-dir")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_worktrees)

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
