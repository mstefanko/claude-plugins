#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FAKES = ROOT / "tests" / "parity" / "fakes"
SYSTEM_TMPDIR = "/tmp"


@dataclass
class CommandResult:
    label: str
    argv: list[str]
    cwd: Path | None
    exit_code: int
    stdout_path: str
    stderr_path: str
    wall_seconds: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 6 competitive-build dogfood cases.")
    parser.add_argument("--work-root", type=Path, help="directory for temporary repos, logs, and run ledgers")
    parser.add_argument("--ledger-rows", type=int, default=600, help="large-ledger rows for the ls performance metric")
    args = parser.parse_args()

    os.environ["TMPDIR"] = SYSTEM_TMPDIR
    tempfile.tempdir = None
    work_root = args.work_root or Path(tempfile.mkdtemp(prefix="bakeoff-phase6-dogfood-"))
    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    logs = work_root / "logs"
    logs.mkdir(exist_ok=True)
    runs_dir = work_root / "runs"
    runs_dir.mkdir(exist_ok=True)

    env = fake_env(work_root, args.ledger_rows)
    binary = work_root / "bakeoff"
    run_command("go-build", ["go", "build", "-o", str(binary), "./cmd/bakeoff"], ROOT, logs, env)

    cases: list[dict[str, Any]] = []
    cases.append(case_worktree_patch_capture(work_root, runs_dir, binary, logs, env))
    cases.append(case_verifier_runner(work_root, runs_dir, binary, logs, env))
    cases.append(case_manifest_runs_verify(work_root, runs_dir, binary, logs, env))
    cases.append(case_provider_permissions(work_root, runs_dir, binary, logs, env))
    cases.append(case_large_ledger_metric(work_root, runs_dir, binary, logs, env))
    negative = negative_no_gate(work_root, binary, logs, env)

    artifact_bytes = directory_size(runs_dir)
    scratch_dir = work_root / "large-ledger-metric-scratch"
    scratch_bytes = directory_size(scratch_dir) if scratch_dir.exists() else 0
    judge_prompt = first_existing(
        [
            runs_dir / "phase6-manifest-runs-verify" / "judge" / "prompt-pass1.txt",
            runs_dir / "phase6-large-ledger-metric" / "judge" / "prompt-pass1.txt",
        ]
    )
    prompt_text = judge_prompt.read_text(encoding="utf-8") if judge_prompt else ""
    summary = {
        "schema_version": 1,
        "work_root": str(work_root),
        "runs_dir": str(runs_dir),
        "binary": str(binary),
        "cases": cases,
        "negative_cases": [negative],
        "artifact_size": {
            "bytes": artifact_bytes,
            "kilobytes": round(artifact_bytes / 1024, 1),
        },
        "scratch_size": {
            "bytes": scratch_bytes,
            "kilobytes": round(scratch_bytes / 1024, 1),
        },
        "judge_prompt_audit": {
            "prompt_path": str(judge_prompt) if judge_prompt else None,
            "bytes": len(prompt_text.encode("utf-8")),
            "anti_verbosity_rule_present": "Do not let style, verbosity, or patch size alone override failing verifier evidence." in prompt_text,
            "position_swap_rule_present": "The harness will call you TWICE with candidates swapped." in prompt_text,
            "patch_excerpt_present": "patch_excerpt" in prompt_text,
        },
    }
    summary_path = work_root / "phase6-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def fake_env(work_root: Path, ledger_rows: int) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(FAKES) + os.pathsep + env.get("PATH", "")
    env["TMPDIR"] = SYSTEM_TMPDIR
    env["GOCACHE"] = env.get("GOCACHE", str(Path(env["TMPDIR"]) / "bakeoff-go-cache"))
    env["BAKEOFF_PHASE6_WORK_ROOT"] = str(work_root)
    env["BAKEOFF_PHASE6_LEDGER_ROWS"] = str(ledger_rows)
    return env


def run_command(
    label: str,
    argv: list[str],
    cwd: Path | None,
    logs: Path,
    env: dict[str, str],
    expect: set[int] | None = None,
) -> CommandResult:
    expect = expect or {0}
    start = time.perf_counter()
    completed = subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.perf_counter() - start
    stdout_path = logs / f"{label}.stdout.txt"
    stderr_path = logs / f"{label}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = CommandResult(
        label=label,
        argv=argv,
        cwd=cwd,
        exit_code=completed.returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        wall_seconds=elapsed,
    )
    if completed.returncode not in expect:
        raise RuntimeError(
            f"{label} exited {completed.returncode}, expected {sorted(expect)}\n"
            f"stdout:\n{completed.stdout[-2000:]}\n"
            f"stderr:\n{completed.stderr[-2000:]}"
        )
    return result


def init_repo(work_root: Path, name: str, files: dict[str, tuple[str, int]] | None = None) -> Path:
    repo = work_root / "repos" / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    run_simple(["git", "init"], repo)
    run_simple(["git", "config", "core.hooksPath", ".git/hooks"], repo)
    run_simple(["git", "config", "user.email", "bakeoff@example.com"], repo)
    run_simple(["git", "config", "user.name", "Bakeoff Dogfood"], repo)
    write_file(repo / "README.md", "phase6 dogfood fixture\n", 0o644)
    for rel, (contents, mode) in (files or {}).items():
        write_file(repo / rel, contents, mode)
    run_simple(["git", "add", "."], repo)
    run_simple(["git", "commit", "-m", "initial"], repo)
    return repo


def run_simple(argv: list[str], cwd: Path) -> None:
    completed = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed in {cwd}:\n{completed.stdout}")


def write_file(path: Path, contents: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(mode)


def write_work_order(path: Path, work_id: str, goal: str, background: str, comparison_goal: str, verify: list[dict[str, Any]]) -> Path:
    data = {
        "schema_version": 1,
        "id": work_id,
        "type": "build",
        "goal": goal,
        "background": background,
        "providers": [
            {"id": "claude", "backend": "claude", "model": "fake-claude", "effort": "high", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "fake-codex", "effort": "high", "scope": "codebase"},
        ],
        "scope_policy": {"enforcement": "best_effort"},
        "judge": {"backend": "claude", "model": "fake-judge", "effort": "xhigh"},
        "build": {
            "base_ref": "HEAD",
            "comparison_goal": comparison_goal,
            "patch_max_bytes": 100000,
            "verify": verify,
        },
        "budgets": {
            "wall_clock_seconds": 10,
            "max_output_bytes": 30000,
            "heartbeat_seconds": 0,
            "output_cap_grace_seconds": 1,
            "max_output_overrun_bytes": 30000,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def build_case(
    case_name: str,
    repo: Path,
    work_order: Path,
    runs_dir: Path,
    binary: Path,
    logs: Path,
    env: dict[str, str],
    extra_env: dict[str, str] | None = None,
    expect: set[int] | None = None,
) -> tuple[CommandResult, dict[str, Any]]:
    case_env = env.copy()
    case_env["BAKEOFF_PHASE6_BIN"] = str(binary)
    if extra_env:
        case_env.update(extra_env)
    result = run_command(
        case_name,
        [str(binary), "build", str(work_order), "--out", str(runs_dir), "--run-id", case_name, "--json", "--quiet", "--force"],
        repo,
        logs,
        case_env,
        expect=expect,
    )
    decision_path = runs_dir / case_name / "decision.json"
    decision = read_json(decision_path) if decision_path.exists() else {}
    return result, decision


def verify_case(case_name: str, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> CommandResult:
    return run_command(
        f"{case_name}-runs-verify",
        [str(binary), "runs", "verify", case_name, "--out", str(runs_dir), "--json"],
        ROOT,
        logs,
        env,
    )


def case_worktree_patch_capture(work_root: Path, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    repo = init_repo(
        work_root,
        "worktree-patch-capture",
        {
            "metric-score.sh": (
                "#!/bin/sh\n"
                "if [ -f claude-build.txt ]; then\n"
                "  printf '{\"score\":1}\\n'\n"
                "else\n"
                "  printf '{\"score\":2}\\n'\n"
                "fi\n",
                0o755,
            )
        },
    )
    work_order = write_work_order(
        work_root / "work-orders" / "worktree-patch-capture.json",
        "phase6-worktree-patch-capture",
        "Exercise worktree isolation, patch capture, cleanup, and metric selection.",
        "Fake providers mutate their detached worktrees; the source checkout must remain clean.",
        "Prefer simpler captured patches with lower fake score.",
        [
            gate("readme", ["test", "-f", "README.md"]),
            metric("score", ["./metric-score.sh"], "score", "lower", 10),
        ],
    )
    _, decision = build_case("phase6-worktree-patch-capture", repo, work_order, runs_dir, binary, logs, env)
    verify_case("phase6-worktree-patch-capture", runs_dir, binary, logs, env)
    assert_equal(decision.get("selection_basis"), "metric", "case1 selection basis")
    assert_equal(decision.get("canonical_winner"), "claude", "case1 winner")
    if (repo / "claude-build.txt").exists() or (repo / "codex-build.txt").exists():
        raise AssertionError("source checkout was mutated by provider output")
    return case_summary("phase6-worktree-patch-capture", decision, runs_dir, notes={"source_checkout_mutated": False})


def case_verifier_runner(work_root: Path, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    repo = init_repo(
        work_root,
        "verifier-runner",
        {
            "metric-log-json.sh": (
                "#!/bin/sh\n"
                "echo 'metric warmup log line'\n"
                "if [ -f claude-build.txt ]; then\n"
                "  printf '{\"elapsed_ms\":110}\\n'\n"
                "else\n"
                "  printf '{\"elapsed_ms\":125}\\n'\n"
                "fi\n",
                0o755,
            )
        },
    )
    work_order = write_work_order(
        work_root / "work-orders" / "verifier-runner.json",
        "phase6-verifier-runner",
        "Exercise raw verifier runner artifacts and last-line metric parsing.",
        "The metric command prints a log line before the final JSON metric line.",
        "Prefer lower elapsed_ms when it clears the threshold.",
        [
            gate("readme", ["test", "-f", "README.md"]),
            metric("elapsed", ["./metric-log-json.sh"], "elapsed_ms", "lower", 5, 1),
        ],
    )
    _, decision = build_case("phase6-verifier-runner", repo, work_order, runs_dir, binary, logs, env)
    verify_case("phase6-verifier-runner", runs_dir, binary, logs, env)
    assert_equal(decision.get("selection_basis"), "metric", "case2 selection basis")
    for rel in [
        "baseline/verify/elapsed/metric.json",
        "providers/claude/build/verify/elapsed/metric.json",
        "providers/codex/build/verify/elapsed/metric.json",
    ]:
        if not (runs_dir / "phase6-verifier-runner" / rel).exists():
            raise AssertionError(f"missing metric artifact: {rel}")
    return case_summary("phase6-verifier-runner", decision, runs_dir, notes={"metric_artifacts_present": True})


def case_manifest_runs_verify(work_root: Path, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    repo = init_repo(work_root, "manifest-runs-verify")
    work_order = write_work_order(
        work_root / "work-orders" / "manifest-runs-verify.json",
        "phase6-manifest-runs-verify",
        "Exercise build manifests, show, ls, and runs verify on a judge-selected build.",
        "Both fake providers pass gates, forcing the swapped build judge path.",
        "Prefer the candidate with clearer maintainability evidence.",
        [gate("readme", ["test", "-f", "README.md"])],
    )
    _, decision = build_case(
        "phase6-manifest-runs-verify",
        repo,
        work_order,
        runs_dir,
        binary,
        logs,
        env,
        extra_env={"BAKEOFF_FAKE_JUDGE_MODE": "build_pick_claude"},
    )
    verify_case("phase6-manifest-runs-verify", runs_dir, binary, logs, env)
    run_command("phase6-manifest-runs-verify-ls", [str(binary), "ls", "--json", "--out", str(runs_dir)], ROOT, logs, env)
    run_command("phase6-manifest-runs-verify-show", [str(binary), "show", "phase6-manifest-runs-verify", "--out", str(runs_dir)], ROOT, logs, env)
    manifest = read_json(runs_dir / "phase6-manifest-runs-verify" / "manifest.json")
    artifacts = manifest.get("artifacts", {})
    assert_equal(artifacts.get("build_context"), "build-context.json", "manifest build context")
    assert_equal(decision.get("selection_basis"), "judge", "case3 selection basis")
    return case_summary("phase6-manifest-runs-verify", decision, runs_dir, notes={"build_context_in_manifest": True})


def case_provider_permissions(work_root: Path, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    doctor = run_command(
        "phase6-doctor-build-fake",
        [str(binary), "doctor", "--build", "--skip-auth-probe", "--json", "--quiet"],
        ROOT,
        logs,
        env,
    )
    doctor_report = json.loads(Path(doctor.stdout_path).read_text(encoding="utf-8"))
    if doctor_report.get("status") != "ok" or not doctor_report.get("build_preflight", {}).get("ok"):
        raise AssertionError(f"fake doctor build preflight failed: {doctor_report}")

    repo = init_repo(work_root, "provider-permissions")
    work_order = write_work_order(
        work_root / "work-orders" / "provider-permissions.json",
        "phase6-provider-permissions",
        "Exercise build-specific provider permission handling.",
        "Codex advertises no workspace-write support in this run; Claude should remain eligible.",
        "Prefer a provider that can edit the worktree under enforced build controls.",
        [gate("readme", ["test", "-f", "README.md"])],
    )
    _, decision = build_case(
        "phase6-provider-permissions",
        repo,
        work_order,
        runs_dir,
        binary,
        logs,
        env,
        extra_env={"BAKEOFF_FAKE_SCOPE_HELP_MODE": "none"},
    )
    verify_case("phase6-provider-permissions", runs_dir, binary, logs, env)
    codex_status = read_json(runs_dir / "phase6-provider-permissions" / "providers" / "codex" / "status.json")
    assert_equal(codex_status.get("status"), "scope_error", "codex scope status")
    assert_equal(decision.get("decision_kind"), "single_provider_only", "case4 decision kind")
    assert_equal(decision.get("selection_basis"), "gate", "case4 selection basis")
    assert_equal(decision.get("canonical_winner"), "claude", "case4 winner")
    return case_summary("phase6-provider-permissions", decision, runs_dir, notes={"fake_doctor_build_ok": True, "codex_scope_error": True})


def case_large_ledger_metric(work_root: Path, runs_dir: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    repo = init_repo(
        work_root,
        "large-ledger-metric",
        {
            "measure-ls.py": (
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, shutil, subprocess, time\n"
                "count = int(os.environ.get('BAKEOFF_PHASE6_LEDGER_ROWS', '600'))\n"
                "bin_path = os.environ['BAKEOFF_PHASE6_BIN']\n"
                "root = pathlib.Path(os.environ['BAKEOFF_PHASE6_WORK_ROOT']) / 'large-ledger-metric-scratch' / pathlib.Path.cwd().name\n"
                "ledger = root / 'runs'\n"
                "if root.exists():\n"
                "    shutil.rmtree(root)\n"
                "ledger.mkdir(parents=True)\n"
                "for i in range(count):\n"
                "    run = ledger / f'run-{i:04d}'\n"
                "    run.mkdir(parents=True)\n"
                "    (run / 'report.md').write_text('ok\\n', encoding='utf-8')\n"
                "    manifest = {\n"
                "        'schema_version': 1,\n"
                "        'run_id': run.name,\n"
                "        'type': 'build',\n"
                "        'facet_id': None,\n"
                "        'decision_kind': 'pick_winner',\n"
                "        'triage': {'state': 'no'},\n"
                "        'finished_at': '2026-05-18T00:00:00Z',\n"
                "        'artifacts': {'report': 'report.md'},\n"
                "    }\n"
                "    (run / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')\n"
                "start = time.perf_counter()\n"
                "completed = subprocess.run([bin_path, 'ls', '--json', '--out', str(ledger)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n"
                "elapsed_ms = (time.perf_counter() - start) * 1000\n"
                "if completed.returncode != 0:\n"
                "    raise SystemExit(completed.stderr)\n"
                "rows = json.loads(completed.stdout)['runs']\n"
                "if len(rows) != count:\n"
                "    raise SystemExit(f'expected {count} rows, got {len(rows)}')\n"
                "print(json.dumps({'elapsed_ms': elapsed_ms}))\n",
                0o755,
            )
        },
    )
    work_order = write_work_order(
        work_root / "work-orders" / "large-ledger-metric.json",
        "phase6-large-ledger-metric",
        "Exercise large-ledger ls performance as a metric verifier.",
        "The metric creates hundreds of manifest-backed runs and times bakeoff ls --json.",
        "Prefer lower elapsed_ms only if the difference is far beyond noise.",
        [
            gate("readme", ["test", "-f", "README.md"]),
            metric("ls-elapsed", ["./measure-ls.py"], "elapsed_ms", "lower", 100000),
        ],
    )
    _, decision = build_case(
        "phase6-large-ledger-metric",
        repo,
        work_order,
        runs_dir,
        binary,
        logs,
        env,
        extra_env={"BAKEOFF_FAKE_JUDGE_MODE": "build_pick_claude"},
    )
    verify_case("phase6-large-ledger-metric", runs_dir, binary, logs, env)
    metric_doc = read_json(runs_dir / "phase6-large-ledger-metric" / "providers" / "claude" / "build" / "verify" / "ls-elapsed" / "metric.json")
    value = metric_doc.get("value")
    if not isinstance(value, (int, float)):
        raise AssertionError(f"large-ledger metric did not record numeric elapsed_ms: {metric_doc}")
    assert_equal(decision.get("selection_basis"), "judge", "case5 selection basis")
    return case_summary("phase6-large-ledger-metric", decision, runs_dir, notes={"ledger_rows": int(env["BAKEOFF_PHASE6_LEDGER_ROWS"]), "claude_elapsed_ms": value})


def negative_no_gate(work_root: Path, binary: Path, logs: Path, env: dict[str, str]) -> dict[str, Any]:
    work_order = write_work_order(
        work_root / "work-orders" / "no-gate-negative.json",
        "phase6-no-gate-negative",
        "This work order intentionally omits gate verifiers.",
        "It must fail validation instead of running a judge-only build.",
        "No judge-only fallback is allowed.",
        [metric("score", ["true"], "score", "lower", 10)],
    )
    result = run_command("phase6-no-gate-negative", [str(binary), "validate", str(work_order)], ROOT, logs, env, expect={2})
    stderr = Path(result.stderr_path).read_text(encoding="utf-8")
    if "at least one gate verifier" not in stderr:
        raise AssertionError(f"negative validation did not mention missing gate:\n{stderr}")
    return {
        "id": "phase6-no-gate-negative",
        "status": "passed",
        "expected_exit_code": 2,
        "stderr_path": result.stderr_path,
    }


def gate(verifier_id: str, argv: list[str]) -> dict[str, Any]:
    return {"id": verifier_id, "kind": "gate", "argv": argv, "wall_clock_seconds": 5, "max_output_bytes": 4000}


def metric(verifier_id: str, argv: list[str], name: str, direction: str, min_delta_percent: float, noise_floor_percent: float = 0) -> dict[str, Any]:
    return {
        "id": verifier_id,
        "kind": "metric",
        "argv": argv,
        "wall_clock_seconds": 10,
        "max_output_bytes": 8000,
        "metric": {
            "name": name,
            "direction": direction,
            "min_delta_percent": min_delta_percent,
            "noise_floor_percent": noise_floor_percent,
        },
    }


def case_summary(case_name: str, decision: dict[str, Any], runs_dir: Path, notes: dict[str, Any]) -> dict[str, Any]:
    run_dir = runs_dir / case_name
    return {
        "id": case_name,
        "status": "passed",
        "run_dir": str(run_dir),
        "decision_kind": decision.get("decision_kind"),
        "selection_basis": decision.get("selection_basis"),
        "winner": decision.get("canonical_winner"),
        "judge_ran": decision.get("judge_ran"),
        "manifest": str(run_dir / "manifest.json"),
        "report": str(run_dir / "report.md"),
        "notes": notes,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_equal(got: Any, want: Any, label: str) -> None:
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(textwrap.dedent(str(exc)).strip(), file=sys.stderr)
        raise SystemExit(1)
