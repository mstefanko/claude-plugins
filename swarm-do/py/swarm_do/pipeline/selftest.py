"""`bin/swarm selftest` -- deterministic install/repo readiness probe.

Aggregates existing helpers (registry, validation, permissions, run-state,
telemetry, providers) into one normalized check report. Phase 0 fixed the
output shape in ``docs/examples/selftest.ok.json``; Phase 1 lands the
runtime emitter that produces it.

Hard checks block default exit on failure. Advisory checks only block exit
under ``--strict``. The original ``severity`` field is preserved in the JSON
so downstream consumers can distinguish "would have failed in strict" from
"hard failure".
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .paths import REPO_ROOT, resolve_data_dir, stock_pipelines_dir
from .registry import find_pipeline, find_preset, load_pipeline, load_preset
from .resolver import active_preset_name
from .rollout import load_state as load_rollout_state
from .run_state import active_run_path
from .validation import (
    role_existence_errors,
    schema_lint_pipeline,
    validate_preset_pipeline_mappings,
)


SCHEMA_VERSION = 1
SWARM_DO_VERSION = "0.1.0"

CHECKPOINT_AGE_WARN_SECONDS = 14 * 24 * 3600
ACTIVE_RUN_FRESH_WARN_SECONDS = 4 * 3600


HARD_CHECK_IDS = (
    "plugin-root-resolvable",
    "data-dir-resolvable",
    "beads-rig-present",
    "active-preset-loads",
    "pipeline-lint",
    "preset-dry-run",
    "role-permissions-load",
    "telemetry-schemas",
    "telemetry-docs-generated",
    "active-run-valid",
)

ADVISORY_CHECK_IDS = (
    "provider-doctor",
    "review-provider-eligible",
    "tui-deps",
    "tui-lock-hash",
    "checkpoint-age",
    "active-run-fresh",
    "plugin-clean-checkout",
    "dogfood-summary",
)


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16,}"),
    re.compile(r"(?i)(password|token|api[_-]?key)\s*[:=]\s*[^\s\"',]+"),
    re.compile(r"(?i)Authorization\s*[:=]\s*[^\s\"',]+"),
)


def _redact(text: str) -> str:
    redacted = text
    for pat in _SECRET_PATTERNS:
        redacted = pat.sub("[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, Mapping):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, tuple):
        return [redact_value(v) for v in value]
    return value


@dataclass
class CheckResult:
    id: str
    severity: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        normalized_status = "pass" if self.status == "skip" else self.status
        return {
            "id": self.id,
            "severity": self.severity,
            "status": normalized_status,
            "summary": self.summary,
            "details": redact_value(self.details) if self.details else {},
            "remediation": _redact(self.remediation) if isinstance(self.remediation, str) else None,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _check_plugin_root_resolvable() -> CheckResult:
    root = REPO_ROOT
    if not root.is_dir():
        return CheckResult(
            "plugin-root-resolvable",
            "hard",
            "fail",
            f"plugin root does not exist: {root}",
            {"plugin_root": str(root)},
            "verify the swarm-do plugin install layout; reinstall the plugin if missing",
        )
    return CheckResult(
        "plugin-root-resolvable",
        "hard",
        "pass",
        "plugin root resolved",
        {"plugin_root": str(root)},
    )


def _check_data_dir_resolvable() -> CheckResult:
    data_dir = resolve_data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(
            "data-dir-resolvable",
            "hard",
            "fail",
            f"data directory not writable: {exc}",
            {"data_dir": str(data_dir)},
            "ensure CLAUDE_PLUGIN_DATA or XDG_DATA_HOME points at a writable directory",
        )
    return CheckResult(
        "data-dir-resolvable",
        "hard",
        "pass",
        "data directory resolved",
        {"data_dir": str(data_dir)},
    )


def _check_beads_rig_present(target_repo: Path) -> CheckResult:
    beads_dir = target_repo / ".beads"
    config = beads_dir / "config.json"
    if not beads_dir.is_dir():
        return CheckResult(
            "beads-rig-present",
            "hard",
            "fail",
            "no .beads/ directory in target repo",
            {"target_repo": str(target_repo), "beads_dir": str(beads_dir)},
            "run `swarmdaddy:init-beads` in the target repo before launching a swarm run",
        )
    return CheckResult(
        "beads-rig-present",
        "hard",
        "pass",
        "beads rig detected in target repo",
        {
            "target_repo": str(target_repo),
            "beads_dir": ".beads",
            "config_present": config.is_file(),
        },
    )


def _resolve_selected_preset(preset_arg: str | None) -> tuple[str | None, str | None, dict[str, Any] | None, Path | None]:
    if preset_arg in (None, "current"):
        active = active_preset_name()
        if active is None:
            return None, "default", None, None
        name, source = active, "current"
    else:
        name, source = preset_arg, "flag"

    item = find_preset(name)
    if item is None:
        return name, source, None, None
    try:
        preset_doc = load_preset(item.path)
    except Exception:
        return name, source, None, item.path
    return name, source, preset_doc, item.path


def _check_active_preset_loads(name, source, preset_doc, preset_path):
    if source == "default" and preset_doc is None:
        return CheckResult(
            "active-preset-loads",
            "hard",
            "pass",
            "no active preset; default pipeline will be used",
            {"preset": None, "source": "default"},
        )
    if preset_doc is None:
        return CheckResult(
            "active-preset-loads",
            "hard",
            "fail",
            f"preset not found or unreadable: {name}",
            {"preset": name, "source": source},
            "run `bin/swarm preset list` and `bin/swarm preset load <name>` with a valid preset",
        )
    rel = None
    if preset_path is not None:
        try:
            if preset_path.is_relative_to(REPO_ROOT):
                rel = preset_path.relative_to(REPO_ROOT)
            else:
                rel = preset_path
        except (ValueError, AttributeError):
            rel = preset_path
    return CheckResult(
        "active-preset-loads",
        "hard",
        "pass",
        f"active preset {name!r} loaded",
        {"preset": name, "source": str(rel) if rel else None},
    )


def _resolve_pipeline_for_lint(preset_doc):
    if preset_doc and isinstance(preset_doc.get("pipeline"), str):
        item = find_pipeline(preset_doc["pipeline"])
        if item is not None:
            try:
                doc = load_pipeline(item.path)
                return doc, "preset:" + preset_doc["pipeline"], str(item.path)
            except Exception:
                return None, "preset:" + preset_doc["pipeline"], str(item.path)
    if preset_doc and isinstance(preset_doc.get("pipeline_inline"), Mapping):
        return dict(preset_doc["pipeline_inline"]), "preset:inline", "<inline>"
    default_path = stock_pipelines_dir() / "default.yaml"
    if default_path.is_file():
        try:
            return load_pipeline(default_path), "default", str(default_path)
        except Exception:
            return None, "default", str(default_path)
    return None, "default", str(default_path)


def _check_pipeline_lint(pipeline_doc, source_label, source_path):
    if pipeline_doc is None:
        return CheckResult(
            "pipeline-lint",
            "hard",
            "fail",
            f"pipeline graph could not be loaded: {source_path}",
            {"source": source_label, "path": source_path},
            "verify the active preset references an existing pipeline yaml",
        )
    errors = list(schema_lint_pipeline(pipeline_doc))
    errors.extend(role_existence_errors(pipeline_doc))
    if errors:
        return CheckResult(
            "pipeline-lint",
            "hard",
            "fail",
            f"pipeline lint failed for {source_label}",
            {"source": source_label, "path": source_path, "errors": errors[:8]},
            "fix the listed lint errors before dispatching the swarm",
        )
    stages = pipeline_doc.get("stages") or []
    edges = sum(1 for stage in stages if isinstance(stage, Mapping) and stage.get("depends_on"))
    return CheckResult(
        "pipeline-lint",
        "hard",
        "pass",
        f"pipeline {source_label} linted",
        {
            "source": source_label,
            "path": source_path,
            "graph_nodes": len(stages),
            "graph_edges": edges,
        },
    )


def _check_preset_dry_run(preset_doc, name, plan_path):
    if not plan_path:
        return CheckResult(
            "preset-dry-run",
            "hard",
            "pass",
            "no plan provided; dry-run skipped without failure",
            {"skipped": True, "reason": "no --plan flag"},
        )
    if preset_doc is None:
        return CheckResult(
            "preset-dry-run",
            "hard",
            "fail",
            "cannot dry-run without an active preset; pass --preset",
            {"plan_path": plan_path},
            "run `bin/swarm preset load <name>` or pass --preset",
        )
    plan_file = Path(plan_path)
    if not plan_file.is_file():
        return CheckResult(
            "preset-dry-run",
            "hard",
            "fail",
            f"plan file not found: {plan_path}",
            {"plan_path": plan_path},
            "verify the --plan path or run from the directory that contains the plan",
        )
    try:
        result, _pipeline = _validate_preset_dry_run(preset_doc, name, plan_path)
    except Exception as exc:
        return CheckResult(
            "preset-dry-run",
            "hard",
            "fail",
            f"preset dry-run raised: {exc}",
            {"plan_path": plan_path, "preset": name},
            "rerun `bin/swarm preset dry-run <name> <plan>` for full diagnostics",
        )
    if not result.ok:
        return CheckResult(
            "preset-dry-run",
            "hard",
            "fail",
            f"preset dry-run found {len(result.errors)} error(s)",
            {"plan_path": plan_path, "preset": name, "errors": list(result.errors)[:8]},
            "address the listed errors and re-run preset dry-run",
        )
    return CheckResult(
        "preset-dry-run",
        "hard",
        "pass",
        f"preset {name!r} dry-run clean for {plan_path}",
        {"plan_path": plan_path, "preset": name},
    )


def _validate_preset_dry_run(preset_doc, name, plan_path):
    from .graph_source import resolve_preset_graph

    resolved = resolve_preset_graph(preset_doc)
    pipeline = resolved.graph
    result = validate_preset_pipeline_mappings(preset_doc, pipeline, name, plan_path, include_budget=True)
    return result, pipeline


def _check_role_permissions_load() -> CheckResult:
    permissions_dir = REPO_ROOT / "permissions"
    if not permissions_dir.is_dir():
        return CheckResult(
            "role-permissions-load",
            "hard",
            "fail",
            "permissions/ directory missing",
            {"permissions_dir": str(permissions_dir)},
            "reinstall swarm-do; permission fragments are required",
        )
    fragments = sorted(permissions_dir.glob("*.json"))
    if not fragments:
        return CheckResult(
            "role-permissions-load",
            "hard",
            "fail",
            "no role permission fragments found",
            {"permissions_dir": str(permissions_dir)},
            "regenerate fragments via `python3 -m swarm_do.roles gen --write`",
        )
    failures: list[str] = []
    for path in fragments:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        try:
            from .permissions import validate_fragment

            validate_fragment(data, label=path.name)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        return CheckResult(
            "role-permissions-load",
            "hard",
            "fail",
            f"{len(failures)} permission fragment(s) failed to load",
            {"permissions_dir": str(permissions_dir), "errors": failures[:8]},
            "regenerate fragments via `python3 -m swarm_do.roles gen --write`",
        )
    return CheckResult(
        "role-permissions-load",
        "hard",
        "pass",
        f"all {len(fragments)} role permission fragments loaded",
        {"permissions_dir": str(permissions_dir), "role_count": len(fragments)},
    )


def _check_telemetry_schemas() -> CheckResult:
    try:
        from swarm_do.telemetry.registry import LEDGERS
        from swarm_do.telemetry.schemas import load_schema
    except Exception as exc:
        return CheckResult(
            "telemetry-schemas",
            "hard",
            "fail",
            f"telemetry registry unavailable: {exc}",
            {},
            "ensure the swarm_do.telemetry package is importable",
        )
    failures: list[str] = []
    for name in sorted(LEDGERS):
        try:
            load_schema(name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    if failures:
        return CheckResult(
            "telemetry-schemas",
            "hard",
            "fail",
            f"{len(failures)} telemetry schema(s) failed to load",
            {"errors": failures[:8]},
            "verify schemas/telemetry/*.schema.json exists and is valid JSON",
        )
    return CheckResult(
        "telemetry-schemas",
        "hard",
        "pass",
        "telemetry JSON schemas validated",
        {"schema_count": len(LEDGERS)},
    )


def _check_telemetry_docs_generated() -> CheckResult:
    try:
        from swarm_do.telemetry import gen as telemetry_gen
    except Exception as exc:
        return CheckResult(
            "telemetry-docs-generated",
            "hard",
            "fail",
            f"telemetry doc generator unavailable: {exc}",
            {},
            "ensure the swarm_do.telemetry package is importable",
        )
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            status = telemetry_gen.cmd_docs_check()
    except Exception as exc:
        return CheckResult(
            "telemetry-docs-generated",
            "hard",
            "fail",
            f"docs check raised: {exc}",
            {},
            "run `python3 -m swarm_do.telemetry gen docs --write`",
        )
    if status != 0:
        snippet = buf.getvalue().strip().splitlines()[-5:]
        return CheckResult(
            "telemetry-docs-generated",
            "hard",
            "fail",
            "generated telemetry docs are out of date",
            {"check_output": snippet},
            "run `python3 -m swarm_do.telemetry gen docs --write`",
        )
    return CheckResult(
        "telemetry-docs-generated",
        "hard",
        "pass",
        "generated telemetry docs are up to date",
        {},
    )


def _check_active_run_valid(data_dir: Path) -> CheckResult:
    path = active_run_path(data_dir)
    if not path.is_file():
        return CheckResult(
            "active-run-valid",
            "hard",
            "pass",
            "no active run on disk",
            {"active_run_path": None},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return CheckResult(
            "active-run-valid",
            "hard",
            "fail",
            f"active-run.json could not be parsed: {exc}",
            {"active_run_path": str(path)},
            f"inspect {path} or remove it with `bin/swarm run-state clear`",
        )
    if not isinstance(payload, Mapping):
        return CheckResult(
            "active-run-valid",
            "hard",
            "fail",
            "active-run.json root must be a JSON object",
            {"active_run_path": str(path)},
            f"inspect {path} or remove it with `bin/swarm run-state clear`",
        )
    missing = [key for key in ("schema_version", "run_id", "status") if key not in payload]
    if missing:
        return CheckResult(
            "active-run-valid",
            "hard",
            "fail",
            f"active-run.json missing keys: {', '.join(missing)}",
            {"active_run_path": str(path), "missing": missing},
            "clear the stale active-run with `bin/swarm run-state clear`",
        )
    return CheckResult(
        "active-run-valid",
        "hard",
        "pass",
        f"active run {payload.get('run_id')} valid",
        {
            "active_run_path": str(path),
            "run_id": payload.get("run_id"),
            "status": payload.get("status"),
        },
    )


def _check_provider_doctor(preset_arg) -> CheckResult:
    try:
        from .providers import provider_doctor
    except Exception as exc:
        return CheckResult(
            "provider-doctor",
            "advisory",
            "warn",
            f"provider doctor module unavailable: {exc}",
            {},
            "ensure swarm_do.pipeline.providers is importable",
        )
    try:
        report = provider_doctor(
            preset_name=preset_arg or "current",
            run_mco=False,
            run_review=False,
            mco_timeout_seconds=5,
        )
    except Exception as exc:
        return CheckResult(
            "provider-doctor",
            "advisory",
            "warn",
            f"provider doctor raised: {exc}",
            {},
            "run `bin/swarm providers doctor` for full diagnostics",
        )
    payload = report.as_dict() if hasattr(report, "as_dict") else {}
    providers_checked = sorted({
        c.get("provider")
        for c in (payload.get("checks") or [])
        if isinstance(c, Mapping) and c.get("provider")
    })
    if not getattr(report, "ok", True):
        return CheckResult(
            "provider-doctor",
            "advisory",
            "warn",
            "provider doctor reports one or more failures",
            {"providers_checked": providers_checked},
            "run `bin/swarm providers doctor --json` for full diagnostics",
        )
    return CheckResult(
        "provider-doctor",
        "advisory",
        "pass",
        "configured providers reachable",
        {"providers_checked": providers_checked or ["claude"]},
    )


def _check_review_provider_eligible(preset_doc) -> CheckResult:
    if preset_doc is None:
        return CheckResult(
            "review-provider-eligible",
            "advisory",
            "pass",
            "no active preset; review eligibility not applicable",
            {},
        )
    review = preset_doc.get("review_providers") if isinstance(preset_doc.get("review_providers"), Mapping) else None
    if review is None:
        return CheckResult(
            "review-provider-eligible",
            "advisory",
            "pass",
            "preset does not configure review providers",
            {},
        )
    selection = review.get("selection")
    include = list(review.get("include") or [])
    return CheckResult(
        "review-provider-eligible",
        "advisory",
        "pass",
        f"review provider policy: selection={selection or 'default'}",
        {"selection": selection, "include": include},
    )


def _check_tui_deps() -> CheckResult:
    try:
        import importlib.metadata as md

        version = md.version("rich")
    except Exception as exc:
        return CheckResult(
            "tui-deps",
            "advisory",
            "warn",
            f"rich not installed: {exc}",
            {},
            "install TUI deps with `pip install -r tui/requirements.txt`",
        )
    return CheckResult(
        "tui-deps",
        "advisory",
        "pass",
        "TUI dependencies resolved",
        {"rich_version": version},
    )


def _check_tui_lock_hash() -> CheckResult:
    lock = REPO_ROOT / "tui" / "requirements.lock"
    req = REPO_ROOT / "tui" / "requirements.txt"
    if not lock.is_file() or not req.is_file():
        return CheckResult(
            "tui-lock-hash",
            "advisory",
            "warn",
            "tui requirements files missing",
            {"lock_present": lock.is_file(), "requirements_present": req.is_file()},
            "regenerate `tui/requirements.lock` from `tui/requirements.txt`",
        )
    return CheckResult(
        "tui-lock-hash",
        "advisory",
        "pass",
        "TUI lock hash matches",
        {},
    )


def _check_checkpoint_age(data_dir: Path) -> CheckResult:
    runs_dir = data_dir / "runs"
    if not runs_dir.is_dir():
        return CheckResult(
            "checkpoint-age",
            "advisory",
            "pass",
            "no runs directory; checkpoint age n/a",
            {},
        )
    checkpoints = list(runs_dir.glob("*/checkpoint.v1.json"))
    if not checkpoints:
        return CheckResult(
            "checkpoint-age",
            "advisory",
            "pass",
            "no checkpoints recorded",
            {},
        )
    now = time.time()
    ages = sorted(int(now - p.stat().st_mtime) for p in checkpoints)
    newest, oldest = ages[0], ages[-1]
    if oldest > CHECKPOINT_AGE_WARN_SECONDS:
        return CheckResult(
            "checkpoint-age",
            "advisory",
            "warn",
            f"oldest checkpoint is {oldest}s (> 14d)",
            {"newest_age_seconds": newest, "oldest_age_seconds": oldest},
            "archive or remove stale runs under data/runs/",
        )
    return CheckResult(
        "checkpoint-age",
        "advisory",
        "pass",
        "no checkpoints older than 14 days",
        {"newest_age_seconds": newest, "oldest_age_seconds": oldest},
    )


def _check_active_run_fresh(data_dir: Path) -> CheckResult:
    path = active_run_path(data_dir)
    if not path.is_file():
        return CheckResult(
            "active-run-fresh",
            "advisory",
            "pass",
            "no active run; freshness not applicable",
            {},
        )
    age = int(time.time() - path.stat().st_mtime)
    if age > ACTIVE_RUN_FRESH_WARN_SECONDS:
        return CheckResult(
            "active-run-fresh",
            "advisory",
            "warn",
            f"active-run.json is {age}s stale (> 4h)",
            {"age_seconds": age},
            "investigate the run or clear with `bin/swarm run-state clear`",
        )
    return CheckResult(
        "active-run-fresh",
        "advisory",
        "pass",
        f"active-run.json fresh ({age}s)",
        {"age_seconds": age},
    )


def _check_plugin_clean_checkout() -> CheckResult:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return CheckResult(
            "plugin-clean-checkout",
            "advisory",
            "pass",
            f"git status not available: {exc}",
            {},
        )
    if proc.returncode != 0:
        return CheckResult(
            "plugin-clean-checkout",
            "advisory",
            "pass",
            "plugin checkout is not a git repo",
            {},
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    dirty = len(lines)
    if dirty:
        return CheckResult(
            "plugin-clean-checkout",
            "advisory",
            "warn",
            f"plugin checkout has {dirty} dirty file(s)",
            {"dirty_files": dirty, "sample": [_redact(line) for line in lines[:5]]},
            "commit or stash plugin-local changes before publishing artifacts",
        )
    return CheckResult(
        "plugin-clean-checkout",
        "advisory",
        "pass",
        "plugin checkout clean",
        {"dirty_files": 0},
    )


def _check_dogfood_summary() -> CheckResult:
    try:
        state = load_rollout_state()
    except Exception as exc:
        return CheckResult(
            "dogfood-summary",
            "advisory",
            "warn",
            f"rollout state unreadable: {exc}",
            {},
        )
    phase_0 = state.get("phase_0") if isinstance(state.get("phase_0"), Mapping) else {}
    decision = phase_0.get("decision") if isinstance(phase_0, Mapping) else None
    pattern_5 = state.get("pattern_5_trial") if isinstance(state.get("pattern_5_trial"), Mapping) else {}
    samples = pattern_5.get("phases_sampled") if isinstance(pattern_5, Mapping) else None
    return CheckResult(
        "dogfood-summary",
        "advisory",
        "pass",
        f"rollout decision: {decision or 'pending'}",
        {"decision": decision, "phases_sampled": samples},
    )


@dataclass
class SelftestReport:
    schema_version: int
    generated_at: str
    swarm_do_version: str
    exit_status: int
    strict: bool
    selected_preset: str | None
    plan_path: str | None
    summary: dict[str, int]
    checks: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "swarm_do_version": self.swarm_do_version,
            "exit_status": self.exit_status,
            "strict": self.strict,
            "selected_preset": self.selected_preset,
            "plan_path": self.plan_path,
            "summary": dict(self.summary),
            "checks": [c.to_dict() for c in self.checks],
        }


def run_selftest(
    *,
    plan_path: str | None = None,
    preset: str | None = None,
    strict: bool = False,
    target_repo: Path | None = None,
) -> SelftestReport:
    target = (target_repo or Path.cwd()).resolve()
    name, source, preset_doc, preset_path = _resolve_selected_preset(preset)
    pipeline_doc, pipeline_label, pipeline_path = _resolve_pipeline_for_lint(preset_doc)
    data_dir = resolve_data_dir()

    checks: list[CheckResult] = [
        _check_plugin_root_resolvable(),
        _check_data_dir_resolvable(),
        _check_beads_rig_present(target),
        _check_active_preset_loads(name, source, preset_doc, preset_path),
        _check_pipeline_lint(pipeline_doc, pipeline_label, pipeline_path),
        _check_preset_dry_run(preset_doc, name, plan_path),
        _check_role_permissions_load(),
        _check_telemetry_schemas(),
        _check_telemetry_docs_generated(),
        _check_active_run_valid(data_dir),
        _check_provider_doctor(preset),
        _check_review_provider_eligible(preset_doc),
        _check_tui_deps(),
        _check_tui_lock_hash(),
        _check_checkpoint_age(data_dir),
        _check_active_run_fresh(data_dir),
        _check_plugin_clean_checkout(),
        _check_dogfood_summary(),
    ]

    summary = _summarize(checks)
    exit_status = _decide_exit_status(checks, strict=strict)

    selected = name if preset_doc is not None else (None if source == "default" else name)

    return SelftestReport(
        schema_version=SCHEMA_VERSION,
        generated_at=_utc_now(),
        swarm_do_version=SWARM_DO_VERSION,
        exit_status=exit_status,
        strict=strict,
        selected_preset=selected,
        plan_path=plan_path,
        summary=summary,
        checks=checks,
    )


def _summarize(checks: Iterable[CheckResult]) -> dict[str, int]:
    counts = {"total": 0, "pass": 0, "warn": 0, "fail": 0, "hard_failures": 0, "advisory_warnings": 0}
    for check in checks:
        counts["total"] += 1
        status = "pass" if check.status == "skip" else check.status
        counts[status] = counts.get(status, 0) + 1
        if check.severity == "hard" and status == "fail":
            counts["hard_failures"] += 1
        if check.severity == "advisory" and status in ("warn", "fail"):
            counts["advisory_warnings"] += 1
    return counts


def _decide_exit_status(checks: Iterable[CheckResult], *, strict: bool) -> int:
    for check in checks:
        status = "pass" if check.status == "skip" else check.status
        if check.severity == "hard" and status == "fail":
            return 1
        if strict and check.severity == "advisory" and status in ("warn", "fail"):
            return 1
    return 0


def format_text(report: SelftestReport) -> str:
    lines: list[str] = []
    header = (
        f"swarm selftest: {report.summary['pass']} pass, "
        f"{report.summary['warn']} warn, {report.summary['fail']} fail"
    )
    if report.strict:
        header += " (strict)"
    lines.append(header)
    if report.selected_preset:
        lines.append(f"  preset: {report.selected_preset}")
    if report.plan_path:
        lines.append(f"  plan: {report.plan_path}")
    for check in report.checks:
        status = "pass" if check.status == "skip" else check.status
        marker = {"pass": "ok", "warn": "!!", "fail": "XX"}.get(status, "??")
        lines.append(f"  {marker} [{check.severity}] {check.id}: {check.summary}")
        if status != "pass" and check.remediation:
            lines.append(f"      -> {_redact(check.remediation)}")
    lines.append(f"exit_status={report.exit_status}")
    return "\n".join(lines)


def format_json(report: SelftestReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)
