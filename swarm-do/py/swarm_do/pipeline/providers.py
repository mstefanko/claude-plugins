"""Provider and local backend health checks for the swarm CLI."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any, Mapping

from .registry import find_pipeline, load_pipeline
from .resolver import BackendResolver, active_preset_name, load_preset_by_name


STATUS_ORDER = {"ok": 0, "skipped": 1, "warning": 2, "error": 3}


@dataclasses.dataclass(frozen=True)
class ProviderCheck:
    name: str
    status: str
    detail: str
    data: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.data is not None:
            row["data"] = dict(self.data)
        return row


@dataclasses.dataclass(frozen=True)
class ProviderDoctorReport:
    active_preset: str | None
    pipeline_name: str | None
    required_backends: tuple[str, ...]
    required_providers: tuple[str, ...]
    checks: tuple[ProviderCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status != "error" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "active_preset": self.active_preset,
            "pipeline_name": self.pipeline_name,
            "required_backends": list(self.required_backends),
            "required_providers": list(self.required_providers),
            "checks": [check.as_dict() for check in self.checks],
        }


def _stage_roles(pipeline: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any] | str | None]]:
    roles: list[tuple[str, Mapping[str, Any] | str | None]] = []
    for stage in pipeline.get("stages") or []:
        for agent in stage.get("agents") or []:
            if not isinstance(agent, Mapping) or not isinstance(agent.get("role"), str):
                continue
            override: Mapping[str, Any] | str | None = agent.get("route")
            if override is None and {"backend", "model", "effort"} <= set(agent.keys()):
                override = agent
            roles.append((agent["role"], override))
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping) and isinstance(fan.get("role"), str):
            roles.append((fan["role"], None))
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and isinstance(merge.get("agent"), str):
            roles.append((merge["agent"], None))
    return roles


def _resolve_pipeline_for_doctor(
    preset_name: str | None,
) -> tuple[str | None, str | None, Mapping[str, Any] | None, Mapping[str, Any] | None, ProviderCheck | None]:
    active = active_preset_name() if preset_name == "current" else preset_name
    pipeline_name = "default"
    preset_data: Mapping[str, Any] | None = None
    if active:
        try:
            preset_data, _ = load_preset_by_name(active)
        except Exception as exc:
            return active, None, None, None, ProviderCheck(
                "preset",
                "error",
                f"active preset cannot be loaded: {exc}",
            )
        pipeline_name = str(preset_data.get("pipeline") or "default")

    item = find_pipeline(pipeline_name)
    if item is None:
        return active, pipeline_name, preset_data, None, ProviderCheck(
            "pipeline",
            "error",
            f"pipeline not found: {pipeline_name}",
        )
    try:
        return active, pipeline_name, preset_data, load_pipeline(item.path), None
    except Exception as exc:
        return active, pipeline_name, preset_data, None, ProviderCheck(
            "pipeline",
            "error",
            f"pipeline cannot be loaded: {exc}",
        )


def _required_backends(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset_data: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset_data)
    backends: set[str] = set()
    for role, override in _stage_roles(pipeline):
        route = resolver.resolve(role, "hard", override=override)
        backends.add(route.backend)
    return tuple(sorted(backends))


def _required_stage_providers(pipeline: Mapping[str, Any]) -> tuple[str, ...]:
    providers: set[str] = set()
    for stage in pipeline.get("stages") or []:
        provider = stage.get("provider")
        if isinstance(provider, Mapping) and isinstance(provider.get("type"), str):
            providers.add(provider["type"])
    return tuple(sorted(providers))


def _required_mco_providers(pipeline: Mapping[str, Any]) -> tuple[str, ...]:
    providers: set[str] = set()
    for stage in pipeline.get("stages") or []:
        provider = stage.get("provider")
        if not isinstance(provider, Mapping) or provider.get("type") != "mco":
            continue
        for name in provider.get("providers") or []:
            if isinstance(name, str) and name:
                providers.add(name)
    return tuple(sorted(providers))


def _local_backend_checks(
    backends: tuple[str, ...],
    which: Callable[[str], str | None],
) -> list[ProviderCheck]:
    checks: list[ProviderCheck] = []
    for backend in backends:
        executable = {"claude": "claude", "codex": "codex"}.get(backend)
        if executable is None:
            checks.append(ProviderCheck(f"backend:{backend}", "warning", "no local executable check is registered"))
            continue
        path = which(executable)
        if path:
            checks.append(ProviderCheck(f"backend:{backend}", "ok", f"{executable} found", {"path": path}))
        else:
            checks.append(ProviderCheck(f"backend:{backend}", "error", f"{executable} not found on PATH"))
    if not checks:
        checks.append(ProviderCheck("backend", "warning", "no pipeline backends were resolved"))
    return checks


def _mco_check(
    requested: bool,
    timeout_seconds: int,
    which: Callable[[str], str | None],
    runner: Callable[..., subprocess.CompletedProcess[str]],
    required_provider_names: tuple[str, ...] = (),
) -> ProviderCheck:
    path = which("mco")
    if not requested:
        detail = "mco doctor not requested"
        if path:
            detail += f"; mco found at {path}"
        return ProviderCheck("provider:mco", "skipped", detail)
    if not path:
        return ProviderCheck("provider:mco", "error", "mco not found on PATH")
    try:
        completed = runner(
            ["mco", "doctor", "--json"],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ProviderCheck("provider:mco", "error", f"mco doctor timed out after {timeout_seconds}s")
    except OSError as exc:
        return ProviderCheck("provider:mco", "error", f"mco doctor failed to start: {exc}")

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError as exc:
        return ProviderCheck(
            "provider:mco",
            "error",
            f"mco doctor returned malformed JSON: {exc}",
            {"exit_code": completed.returncode, "stderr": stderr},
        )
    if completed.returncode != 0:
        return ProviderCheck(
            "provider:mco",
            "error",
            f"mco doctor failed with exit code {completed.returncode}",
            {"exit_code": completed.returncode, "payload": payload, "stderr": stderr},
        )
    not_ready = _not_ready_mco_providers(payload, required_provider_names)
    if not_ready:
        return ProviderCheck(
            "provider:mco",
            "error",
            "selected MCO provider(s) not ready: " + ", ".join(not_ready),
            {"path": path, "payload": payload, "selected_providers": required_provider_names},
        )
    return ProviderCheck(
        "provider:mco",
        "ok",
        "mco doctor --json completed",
        {"path": path, "payload": payload},
    )


def _not_ready_mco_providers(payload: Any, required_provider_names: tuple[str, ...]) -> list[str]:
    if not required_provider_names:
        return []
    rows = payload.get("providers") if isinstance(payload, Mapping) else None
    if not isinstance(rows, (Mapping, list)):
        return list(required_provider_names)
    not_ready: list[str] = []
    for name in required_provider_names:
        row: Any
        if isinstance(rows, Mapping):
            row = rows.get(name)
        else:
            row = next((item for item in rows if isinstance(item, Mapping) and item.get("name") == name), None)
        if not isinstance(row, Mapping):
            not_ready.append(f"{name}=missing")
            continue
        ready = row.get("ready")
        status = row.get("status")
        if ready is True or status == "ok":
            continue
        reason = row.get("reason") or status or "not_ready"
        not_ready.append(f"{name}={reason}")
    return not_ready


def provider_doctor(
    *,
    preset_name: str | None = "current",
    run_mco: bool = False,
    mco_timeout_seconds: int = 30,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProviderDoctorReport:
    active, pipeline_name, preset_data, pipeline, load_error = _resolve_pipeline_for_doctor(preset_name)
    checks: list[ProviderCheck] = []
    required: tuple[str, ...] = ()
    required_providers: tuple[str, ...] = ()
    required_mco_providers: tuple[str, ...] = ()
    if load_error:
        checks.append(load_error)
    elif pipeline is not None:
        try:
            required = _required_backends(pipeline, active, preset_data)
            required_providers = _required_stage_providers(pipeline)
            required_mco_providers = _required_mco_providers(pipeline)
            checks.extend(_local_backend_checks(required, which))
        except Exception as exc:
            checks.append(ProviderCheck("backend-resolution", "error", f"backend resolution failed: {exc}"))
    checks.append(
        _mco_check(
            run_mco or "mco" in required_providers,
            mco_timeout_seconds,
            which,
            runner,
            required_mco_providers,
        )
    )
    checks.sort(key=lambda check: (STATUS_ORDER.get(check.status, 99), check.name))
    return ProviderDoctorReport(active, pipeline_name, required, required_providers, tuple(checks))


def format_provider_report(report: ProviderDoctorReport) -> str:
    lines = [
        "Provider doctor",
        f"  active_preset: {report.active_preset or 'none'}",
        f"  pipeline: {report.pipeline_name or 'unknown'}",
        f"  required_backends: {', '.join(report.required_backends) or 'none'}",
        f"  required_providers: {', '.join(report.required_providers) or 'none'}",
        "  checks:",
    ]
    for check in report.checks:
        lines.append(f"    {check.status.upper():7} {check.name} - {check.detail}")
    return "\n".join(lines)
