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
        details={"test_only": True, "spend_required": False},
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
    fixtures = sorted(path for path in fixture_dir.glob("*.json") if path.is_file())
    details["fixture_dir"] = str(fixture_dir)
    details["fixture_count"] = len(fixtures)
    if not fixtures:
        blockers.append("claude_print_fixtures_missing")

    claude_path = shutil.which("claude")
    details["claude_path"] = claude_path
    if claude_path is None:
        blockers.append("claude_cli_missing")

    if live and claude_path is not None:
        proc = _run(runner, [claude_path, "--version"])
        details["version_exit_code"] = proc.returncode
        details["version_stdout"] = (proc.stdout or "").strip()
        details["version_stderr"] = (proc.stderr or "").strip()
        if proc.returncode != 0:
            blockers.append("claude_version_probe_failed")
    elif not live:
        warnings.append("live_probe_skipped")

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


__all__ = [
    "LauncherCapability",
    "doctor_report",
    "format_doctor_report",
    "parse_claude_print_json",
]
