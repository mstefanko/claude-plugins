"""Launcher capability probes for phase-session execution."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .paths import REPO_ROOT


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LauncherCapability:
    name: str
    eligible: bool
    hard_blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "eligible": self.eligible,
            "hard_blockers": list(self.hard_blockers),
            "warnings": list(self.warnings),
            "details": dict(self.details or {}),
        }


def doctor_report(
    *,
    live: bool = False,
    runner: Runner | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return launcher eligibility without spending agent turns by default."""

    root = repo_root or REPO_ROOT
    launchers = [
        _manual_capability(),
        _fake_test_capability(),
        _claude_print_capability(live=live, runner=runner, repo_root=root),
        _interactive_capability(live=live, runner=runner),
    ]
    return {
        "schema_version": 1,
        "live": bool(live),
        "launchers": [launcher.to_dict() for launcher in launchers],
    }


def format_doctor_report(report: Mapping[str, Any]) -> str:
    lines = ["session launcher capabilities"]
    for launcher in report.get("launchers") or []:
        if not isinstance(launcher, Mapping):
            continue
        marker = "eligible" if launcher.get("eligible") else "ineligible"
        lines.append(f"  {launcher.get('name')}: {marker}")
        blockers = launcher.get("hard_blockers") or []
        warnings = launcher.get("warnings") or []
        if blockers:
            lines.append(f"    blockers: {', '.join(str(item) for item in blockers)}")
        if warnings:
            lines.append(f"    warnings: {', '.join(str(item) for item in warnings)}")
    return "\n".join(lines)


def parse_claude_print_json(text: str) -> dict[str, Any]:
    """Parse a captured ``claude -p --output-format json`` payload."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("claude-print output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("claude-print output must be a JSON object")
    return value


SUPPORTED_CLAUDE_PRINT_STATUSES = {"complete", "failed", "blocked", "needs_input"}
_STREAM_JSON_SUPPORT_CACHE: dict[str, tuple[bool, str | None]] = {}


def extract_claude_print_artifacts(payload: Mapping[str, Any], *, run_dir: Path) -> dict[str, Any]:
    """Normalize artifact pointers from a Claude print outer JSON payload."""

    if not isinstance(payload, Mapping):
        raise ValueError("claude-print payload must be an object")
    inner = _find_artifact_object(payload)
    if inner is None:
        raise ValueError("claude-print payload is missing artifact object")
    status = inner.get("status")
    if not isinstance(status, str) or not status:
        raise ValueError("claude-print artifact status is required")
    if status not in SUPPORTED_CLAUDE_PRINT_STATUSES:
        raise ValueError(f"unsupported claude-print status: {status}")
    result_path = _artifact_path_within_run(inner.get("result_path"), run_dir=run_dir, label="result_path")
    handoff_path = _artifact_path_within_run(inner.get("handoff_path"), run_dir=run_dir, label="handoff_path")
    session_name = inner.get("session_name") or payload.get("session_name") or payload.get("session_id")
    return {
        "status": status,
        "result_path": str(result_path),
        "handoff_path": str(handoff_path),
        "session_name": session_name if isinstance(session_name, str) else None,
        "raw": dict(payload),
    }


def _manual_capability() -> LauncherCapability:
    return LauncherCapability(
        name="manual",
        eligible=True,
        details={"spend_required": False},
    )


def _fake_test_capability() -> LauncherCapability:
    return LauncherCapability(
        name="fake-test",
        eligible=True,
        details={
            "test_only": True,
            "spend_required": False,
            "synthetic_writes": True,
            "synthetic_task_dispatches": True,
            "synthetic_stage_complete_markers": True,
        },
    )


def _claude_print_capability(
    *,
    live: bool,
    runner: Runner | None,
    repo_root: Path,
) -> LauncherCapability:
    blockers: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"spend_required": bool(live)}

    fixture_dir = repo_root / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print"
    required_fixture_names = ("success.json", "failed.json", "blocked.json", "needs_input.json")
    fixtures = [fixture_dir / name for name in required_fixture_names]
    present_fixtures = [path for path in fixtures if path.is_file()]
    details["fixture_dir"] = str(fixture_dir)
    details["fixture_count"] = len(present_fixtures)
    missing = [path.name for path in fixtures if not path.is_file()]
    if missing:
        blockers.append("claude_print_fixtures_missing")
        details["missing_fixtures"] = missing
    for fixture in present_fixtures:
        try:
            payload = parse_claude_print_json(fixture.read_text(encoding="utf-8"))
            extract_claude_print_artifacts(payload, run_dir=fixture_dir)
        except Exception as exc:
            blockers.append("claude_print_fixture_parse_failed")
            details.setdefault("fixture_errors", {})[fixture.name] = str(exc)

    claude_path = shutil.which("claude")
    details["claude_path"] = claude_path
    if claude_path is None:
        blockers.append("claude_cli_missing")
        details["stream_json_supported"] = False

    if live and claude_path is not None:
        proc = _run(runner, [claude_path, "--version"])
        details["version_exit_code"] = proc.returncode
        details["version_stdout"] = (proc.stdout or "").strip()
        details["version_stderr"] = (proc.stderr or "").strip()
        if proc.returncode != 0:
            blockers.append("claude_version_probe_failed")
        supported, error = _probe_stream_json_support(claude_path, runner=runner)
        details["stream_json_supported"] = supported
        if error:
            details["stream_json_probe_error"] = error
    elif not live:
        warnings.append("live_probe_skipped")
        details.setdefault("stream_json_supported", False)

    return LauncherCapability(
        name="claude-print",
        eligible=not blockers,
        hard_blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(warnings),
        details=details,
    )


def _interactive_capability(
    *,
    live: bool,
    runner: Runner | None,
) -> LauncherCapability:
    blockers: list[str] = ["interactive_adapter_not_implemented"]
    warnings: list[str] = []
    details: dict[str, Any] = {"spend_required": bool(live)}
    claude_path = shutil.which("claude")
    details["claude_path"] = claude_path
    if claude_path is None:
        blockers.append("claude_cli_missing")
    if live and claude_path is not None:
        proc = _run(runner, [claude_path, "--version"])
        details["version_exit_code"] = proc.returncode
        if proc.returncode != 0:
            blockers.append("claude_version_probe_failed")
    elif not live:
        warnings.append("live_probe_skipped")
    return LauncherCapability(
        name="interactive",
        eligible=False,
        hard_blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(warnings),
        details=details,
    )


def _run(runner: Runner | None, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(argv)
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
    )


def _probe_stream_json_support(claude_path: str, *, runner: Runner | None) -> tuple[bool, str | None]:
    if claude_path in _STREAM_JSON_SUPPORT_CACHE:
        return _STREAM_JSON_SUPPORT_CACHE[claude_path]
    try:
        if runner is not None:
            proc = runner([claude_path, "--help"])
        else:
            proc = subprocess.run(
                [claude_path, "--help"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        result = ("stream-json" in text, None)
    except Exception as exc:
        result = (False, str(exc))
    _STREAM_JSON_SUPPORT_CACHE[claude_path] = result
    return result


def _find_artifact_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        if "status" in value and ("result_path" in value or "handoff_path" in value):
            return value
        for key in ("result", "message", "content", "text", "output"):
            candidate = value.get(key)
            parsed = _parse_embedded_json(candidate)
            found = _find_artifact_object(parsed)
            if found is not None:
                return found
        for candidate in value.values():
            found = _find_artifact_object(candidate)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_artifact_object(item)
            if found is not None:
                return found
    return None


def _parse_embedded_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped.startswith("{"):
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _artifact_path_within_run(value: Any, *, run_dir: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"claude-print artifact {label} is required")
    text = value.replace("<RUN_DIR>", str(run_dir.resolve(strict=False)))
    path = Path(text)
    if not path.is_absolute():
        path = run_dir / path
    resolved = path.resolve(strict=False)
    root = run_dir.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"claude-print artifact {label} is outside the run directory") from exc
    return resolved


__all__ = [
    "LauncherCapability",
    "doctor_report",
    "extract_claude_print_artifacts",
    "format_doctor_report",
    "parse_claude_print_json",
]
