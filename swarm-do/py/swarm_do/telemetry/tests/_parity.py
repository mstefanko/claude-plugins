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
    """Copy `source` tree contents into `dest` (dest must exist).

    `dot-git/` under a fixture is rewritten as `.git/` at the destination,
    because git refuses to track a nested `.git/HEAD` in the source tree.
    This lets join-outcomes tests ship a fake git repo sentinel inside
    the fixture while keeping the repo-level .gitignore clean.
    """
    if not source.exists():
        raise FileNotFoundError(f"fixture does not exist: {source}")
    for child in source.iterdir():
        # Skip a stray `.git/` that git auto-hides from tracking — only
        # `dot-git/` is canonical in fixtures (renamed to `.git/` on copy).
        if child.name == ".git":
            continue
        target_name = ".git" if child.name == "dot-git" else child.name
        target = dest / target_name
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


def _run_python_cli(
    subcommand: str,
    args_list: List[str],
    tmp: Path,
    env_overrides: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, bytes, int, Dict[str, str]]:
    """Run the Python CLI on a tempdir-materialized fixture.

    Returns (stdout, stderr, exit_code, env) — env is returned so callers can
    reuse it for the legacy run.
    """
    base_env = dict(os.environ)
    for key in ("CLAUDE_PLUGIN_DATA", "SWARM_PHASE0_ROOT", "SWARM_TELEMETRY_NOW"):
        base_env.pop(key, None)
    base_env["CLAUDE_PLUGIN_DATA"] = str(tmp)
    if env_overrides:
        for k, v in env_overrides.items():
            base_env[k] = v.replace("{tempdir}", str(tmp))

    py_env = dict(base_env)
    py_env["PYTHONPATH"] = str(PY_PACKAGE_ROOT) + (
        os.pathsep + py_env["PYTHONPATH"] if "PYTHONPATH" in py_env else ""
    )
    py_cmd = [sys.executable, "-m", "swarm_do.telemetry.cli", subcommand, *args_list]
    stdout, stderr, rc = _run(py_cmd, py_env)
    return stdout, stderr, rc, base_env


def run_golden(
    subcommand: str,
    args: Iterable[str],
    fixture_path: Path,
    golden_stdout_path: Path,
    env_overrides: Optional[Dict[str, str]] = None,
    test_case: Optional[unittest.TestCase] = None,
    golden_exit_path: Optional[Path] = None,
    golden_stderr_path: Optional[Path] = None,
    normalize_tempdir: bool = False,
) -> Tuple[bytes, int]:
    """Run the Python CLI on a copied fixture and assert stdout matches a
    checked-in golden file. Also asserts exit code matches `golden_exit_path`
    (a text file containing the integer) when provided; defaults to 0.

    Bootstrap mode: when env var `SWARM_TEST_WRITE_GOLDEN=1` is set, the
    current Python output is written to `golden_stdout_path` (creating parent
    dirs) instead of asserting. Use this once to capture the Phase-3-frozen
    output, then commit the golden files.

    Use this test mode after `swarm-telemetry.legacy` has been deleted —
    golden files preserve regression coverage without needing the legacy
    script.
    """
    args_list = list(args)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _copy_fixture(fixture_path, tmp)
        args_list = [a.replace("{tempdir}", str(tmp)) for a in args_list]
        py_stdout, py_stderr, py_rc, _env = _run_python_cli(
            subcommand, args_list, tmp, env_overrides
        )

        if normalize_tempdir:
            tmp_bytes = str(tmp).encode("utf-8")
            py_stdout = py_stdout.replace(tmp_bytes, b"{tempdir}")
            py_stderr = py_stderr.replace(tmp_bytes, b"{tempdir}")

    if os.environ.get("SWARM_TEST_WRITE_GOLDEN") == "1":
        golden_stdout_path.parent.mkdir(parents=True, exist_ok=True)
        golden_stdout_path.write_bytes(py_stdout)
        if golden_exit_path is not None:
            golden_exit_path.parent.mkdir(parents=True, exist_ok=True)
            golden_exit_path.write_text(f"{py_rc}\n")
        if golden_stderr_path is not None:
            golden_stderr_path.parent.mkdir(parents=True, exist_ok=True)
            golden_stderr_path.write_bytes(py_stderr)
        return py_stdout, py_rc

    if not golden_stdout_path.exists():
        msg = (
            f"golden file missing: {golden_stdout_path}\n"
            f"Re-run with SWARM_TEST_WRITE_GOLDEN=1 to capture the current "
            f"output, then commit the golden file."
        )
        if test_case is not None:
            test_case.fail(msg)
        raise AssertionError(msg)

    expected_stdout = golden_stdout_path.read_bytes()
    failures: List[str] = []
    if expected_stdout != py_stdout:
        failures.append(
            "stdout drifted from golden:\n"
            + _diff(
                f"golden:{golden_stdout_path.name}",
                expected_stdout,
                "python.stdout",
                py_stdout,
            )
            + f"\npython stderr:\n{py_stderr.decode('utf-8', 'replace')}"
        )

    expected_exit = 0
    if golden_exit_path is not None and golden_exit_path.exists():
        expected_exit = int(golden_exit_path.read_text().strip())
    if expected_exit != py_rc:
        failures.append(
            f"exit code drifted from golden: expected={expected_exit} actual={py_rc}\n"
            f"python stderr:\n{py_stderr.decode('utf-8', 'replace')}"
        )

    if golden_stderr_path is not None and golden_stderr_path.exists():
        expected_stderr = golden_stderr_path.read_bytes()
        if expected_stderr != py_stderr:
            failures.append(
                "stderr drifted from golden:\n"
                + _diff(
                    f"golden:{golden_stderr_path.name}",
                    expected_stderr,
                    "python.stderr",
                    py_stderr,
                )
            )

    if failures:
        message = "\n\n".join(failures)
        if test_case is not None:
            test_case.fail(message)
        raise AssertionError(message)

    return py_stdout, py_rc


def run_parity(
    subcommand: str,
    args: Iterable[str],
    fixture_path: Path,
    env_overrides: Optional[Dict[str, str]] = None,
    compare_stderr: bool = False,
    test_case: Optional[unittest.TestCase] = None,
    golden_stdout_path: Optional[Path] = None,
    golden_exit_path: Optional[Path] = None,
    golden_stderr_path: Optional[Path] = None,
    normalize_tempdir: bool = False,
) -> Tuple[bytes, int]:
    """Run legacy + Python CLI on a copied fixture, assert byte-equal stdout
    and equal exit code. Returns (stdout, exit_code) for further inspection.

    When `golden_stdout_path` is provided and `swarm-telemetry.legacy` is
    absent, the test falls through to `run_golden` — stdout is asserted
    against the committed golden file so regressions are still caught after
    Phase 3 legacy deletion.
    """
    if not LEGACY_SCRIPT.exists():
        if golden_stdout_path is not None:
            return run_golden(
                subcommand=subcommand,
                args=args,
                fixture_path=fixture_path,
                golden_stdout_path=golden_stdout_path,
                env_overrides=env_overrides,
                test_case=test_case,
                golden_exit_path=golden_exit_path,
                golden_stderr_path=golden_stderr_path,
                normalize_tempdir=normalize_tempdir,
            )
        reason = (
            f"swarm-telemetry.legacy deleted and no golden provided; parity "
            f"was proven in Phase 3 commits 1-6. Restore {LEGACY_SCRIPT} or "
            f"pass golden_stdout_path to re-verify."
        )
        if test_case is not None:
            test_case.skipTest(reason)
        raise unittest.SkipTest(reason)

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
