"""Byte-parity harness for Phase 3 subcommand migration.

`run_parity(subcommand, args, fixture_path, env_overrides=None)` invokes both
the legacy bash implementation and the new Python CLI against an identical
fixture and asserts stdout/stderr/exit are byte-equal.

Design (per Phase 3 analysis mstefanko-plugins-5oz):
- Fixture is copied to a tempdir so writes (if any) don't leak into source.
- CLAUDE_PLUGIN_DATA is pointed at the tempdir root so legacy and Python
  resolve identical ledger paths via the same env var.
- env_overrides lets individual subcommand tests inject additional env vars
  (e.g. SWARM_PHASE0_ROOT, SWARM_TELEMETRY_NOW) required for deterministic
  comparison.
- Mismatch emits a unified diff in the assertion message — never normalized
  or hidden, so parity regressions are load-bearing in the failure.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

# Resolve repo root (four parents up from this file: tests -> telemetry ->
# swarm_do -> py -> swarm-do -> <plugin-root>).
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[4]
LEGACY_SCRIPT = _REPO_ROOT / "swarm-do" / "bin" / "swarm-telemetry.legacy"
PY_PACKAGE_ROOT = _REPO_ROOT / "swarm-do" / "py"
FIXTURES_DIR = _TESTS_DIR / "fixtures"


def _copy_fixture(source: Path, dest: Path) -> None:
    """Copy `source` tree contents into `dest` (dest must exist)."""
    if not source.exists():
        raise FileNotFoundError(f"fixture does not exist: {source}")
    for child in source.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _run(
    cmd: List[str],
    env: Mapping[str, str],
    cwd: Optional[Path] = None,
) -> Tuple[bytes, bytes, int]:
    result = subprocess.run(
        cmd,
        env=dict(env),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.stdout, result.stderr, result.returncode


def _diff(label_a: str, a: bytes, label_b: str, b: bytes) -> str:
    try:
        a_text = a.decode("utf-8")
    except UnicodeDecodeError:
        a_text = repr(a)
    try:
        b_text = b.decode("utf-8")
    except UnicodeDecodeError:
        b_text = repr(b)
    return "\n".join(
        difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile=label_a,
            tofile=label_b,
            lineterm="",
        )
    )


def run_parity(
    subcommand: str,
    args: Iterable[str],
    fixture_path: Path,
    env_overrides: Optional[Dict[str, str]] = None,
    compare_stderr: bool = False,
    test_case: Optional[unittest.TestCase] = None,
) -> Tuple[bytes, int]:
    """Run legacy + Python CLI on a copied fixture, assert byte-equal stdout
    and equal exit code. Returns (stdout, exit_code) for further inspection.

    When `test_case` is provided, uses its assert helpers so failures surface
    with the test-method name. Otherwise raises AssertionError directly.
    """
    args_list = list(args)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _copy_fixture(fixture_path, tmp)

        # Substitute `{tempdir}` in args so tests can reference the copied
        # fixture (e.g. --repo {tempdir}).
        args_list = [a.replace("{tempdir}", str(tmp)) for a in args_list]

        base_env = dict(os.environ)
        # Purge host telemetry env so parity is reproducible.
        for key in (
            "CLAUDE_PLUGIN_DATA",
            "SWARM_PHASE0_ROOT",
            "SWARM_TELEMETRY_NOW",
        ):
            base_env.pop(key, None)
        base_env["CLAUDE_PLUGIN_DATA"] = str(tmp)
        if env_overrides:
            # Allow test overrides to reference the tempdir (useful for
            # subcommands that write into SWARM_PHASE0_ROOT). Substitute
            # `{tempdir}` in every value.
            for k, v in env_overrides.items():
                base_env[k] = v.replace("{tempdir}", str(tmp))

        legacy_cmd = ["bash", str(LEGACY_SCRIPT), subcommand, *args_list]
        legacy_stdout, legacy_stderr, legacy_rc = _run(legacy_cmd, base_env)

        py_env = dict(base_env)
        py_env["PYTHONPATH"] = str(PY_PACKAGE_ROOT) + (
            os.pathsep + py_env["PYTHONPATH"] if "PYTHONPATH" in py_env else ""
        )
        py_cmd = [
            sys.executable,
            "-m",
            "swarm_do.telemetry.cli",
            subcommand,
            *args_list,
        ]
        py_stdout, py_stderr, py_rc = _run(py_cmd, py_env)

    failures: List[str] = []
    if legacy_stdout != py_stdout:
        failures.append(
            "stdout mismatch:\n"
            + _diff("legacy.stdout", legacy_stdout, "python.stdout", py_stdout)
        )
    if legacy_rc != py_rc:
        failures.append(
            f"exit code mismatch: legacy={legacy_rc} python={py_rc}\n"
            f"legacy stderr:\n{legacy_stderr.decode('utf-8', 'replace')}\n"
            f"python stderr:\n{py_stderr.decode('utf-8', 'replace')}"
        )
    if compare_stderr and legacy_stderr != py_stderr:
        failures.append(
            "stderr mismatch:\n"
            + _diff("legacy.stderr", legacy_stderr, "python.stderr", py_stderr)
        )

    if failures:
        message = "\n\n".join(failures)
        if test_case is not None:
            test_case.fail(message)
        raise AssertionError(message)

    return py_stdout, py_rc
