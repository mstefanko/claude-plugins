#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "parity" / "fixtures"
FAKES_ROOT = ROOT / "tests" / "parity" / "fakes"
RUN_ID_RE = re.compile(r"\b20\d\d-\d\d-\d\d-[0-9a-f]{4}\b")
TIMESTAMP_RE = re.compile(r"\b20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\+00:00|Z)?\b")
TMP_RE = re.compile(r"(?:/(?:private/)?tmp|/var/folders/[^/]+/[^/]+/T)/[^\s\"']+")
SECONDS_RE = re.compile(r"\b\d+\.\d{1,3}s\b")
JSON_WALL_SECONDS_RE = re.compile(r'"wall_seconds": \d+(?:\.\d+)?')
JSON_AGE_RE = re.compile(r'"(last_output_age|last_stdout_age|last_stderr_age|elapsed)": \d+(?:\.\d+)?')
JSON_SHA_RE = re.compile(r'"((?:decision|report|work_order)_sha256)": "[0-9a-f]{64}"')


@dataclass(frozen=True)
class Action:
    argv: list[str]
    expect: set[int] = field(default_factory=lambda: {0})


@dataclass(frozen=True)
class Case:
    name: str
    argv: list[str]
    setup: list[Action] = field(default_factory=list)
    work_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    jsonc_work_orders: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    omit_fake_tools: set[str] = field(default_factory=set)
    expect: set[int] = field(default_factory=lambda: {0})
    interrupt_after: float | None = None


def base_work_order(mode: str, *, facet: str | None = None, budgets: dict[str, int] | None = None) -> dict[str, Any]:
    scopes = ["codebase", "web"] if mode == "gather" else ["mixed", "mixed"]
    facet_obj: dict[str, Any] | None = None
    if facet == "code-review":
        scopes = ["codebase", "codebase"]
        facet_obj = {
            "id": "code-review",
            "kind": "generic",
            "focus": "Find actionable defects introduced or exposed by the change.",
            "include": ["correctness bugs and edge cases"],
            "exclude": ["style-only preferences"],
        }
    elif facet:
        facet_obj = {
            "id": facet,
            "kind": "generic",
            "focus": "Find relevant facet evidence.",
            "include": ["relevant evidence"],
        }
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": f"{mode}-fake",
        "type": mode,
        "goal": "Run fake bakeoff.",
        "background": "Fake context.",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": scopes[0]},
            {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": scopes[1]},
        ],
        "judge": {"backend": "claude", "model": "fake-judge"},
        "budgets": budgets
        or {
            "wall_clock_seconds": 3,
            "max_output_bytes": 20000,
            "heartbeat_seconds": 0,
        },
    }
    if facet_obj:
        data["facet"] = facet_obj
    return data


def cases() -> list[Case]:
    gather = {"gather.json": base_work_order("gather")}
    compare = {"compare.json": base_work_order("compare")}
    analyze = {"analyze.json": base_work_order("analyze")}
    review = {"review.json": base_work_order("gather", facet="code-review")}
    low_cap = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 3,
                "max_output_bytes": 120,
                "heartbeat_seconds": 0,
                "output_cap_grace_seconds": 1,
                "max_output_overrun_bytes": 500,
            },
        )
    }
    salvage_cap = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 3,
                "max_output_bytes": 400,
                "heartbeat_seconds": 0,
                "output_cap_grace_seconds": 1,
                "max_output_overrun_bytes": 1000,
            },
        )
    }
    zero_overrun_cap = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 3,
                "max_output_bytes": 120,
                "heartbeat_seconds": 0,
                "output_cap_grace_seconds": 30,
                "max_output_overrun_bytes": 0,
            },
        )
    }
    stderr_cap = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 3,
                "max_output_bytes": 1000,
                "heartbeat_seconds": 0,
            },
        )
    }
    timeout = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 1,
                "max_output_bytes": 2000,
                "heartbeat_seconds": 0,
            },
        )
    }
    interrupted = {
        "gather.json": base_work_order(
            "gather",
            budgets={
                "wall_clock_seconds": 10,
                "max_output_bytes": 2000,
                "heartbeat_seconds": 0,
            },
        )
    }
    scope_required = {"gather.json": base_work_order("gather")}
    scope_required["gather.json"]["scope_policy"] = {"enforcement": "required"}
    jsonc_text = """
    {
      // line comment should strip
      "schema_version": 1,
      "id": "jsonc-edge",
      "type": "gather",
      "goal": "Markers like // and /* */ inside strings survive.",
      "background": "literal // marker and literal /* marker */",
      "providers": [
        {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "codebase"},
        {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": "web"}
      ],
      "judge": {"backend": "claude", "model": "fake-judge"},
      /* block comment should strip */
      "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0}
    }
    """
    return [
        Case("root_orientation", []),
        Case("root_help", ["--help"]),
        Case("init_gather", ["init", "gather"]),
        Case("init_compare", ["init", "compare"]),
        Case("init_analyze", ["init", "analyze"]),
        Case("init_review", ["init", "review"]),
        Case("validate_success", ["validate", "gather.json"], work_orders=gather),
        Case("validate_jsonc_edge", ["validate", "jsonc.work-order.json"], jsonc_work_orders={"jsonc.work-order.json": jsonc_text}),
        Case("validate_failure", ["validate", "missing.json"], expect={2}),
        Case("doctor_skip_auth_json", ["doctor", "--skip-auth-probe", "--json"]),
        Case(
            "doctor_missing_tools_json",
            ["doctor", "--skip-auth-probe", "--json"],
            omit_fake_tools={"claude", "codex"},
            expect={1},
        ),
        Case("doctor_human", ["doctor", "--skip-auth-probe"]),
        Case("research_success", ["research", "gather.json", "--out", "runs", "--run-id", "research-success"], work_orders=gather),
        Case("research_json", ["research", "gather.json", "--out", "runs", "--run-id", "research-json", "--json"], work_orders=gather),
        Case(
            "research_both_failed_json",
            ["research", "gather.json", "--out", "runs", "--run-id", "both-failed", "--json"],
            work_orders=gather,
            env={"BAKEOFF_FAKE_FAIL_PROVIDERS": "claude,codex"},
            expect={1},
        ),
        Case(
            "research_single_provider_only",
            ["research", "gather.json", "--out", "runs", "--run-id", "single-provider"],
            work_orders=gather,
            env={"BAKEOFF_FAKE_FAIL_PROVIDERS": "codex"},
        ),
        Case(
            "research_format_retry",
            ["research", "gather.json", "--out", "runs", "--run-id", "format-retry"],
            work_orders=gather,
            env={"BAKEOFF_FAKE_REPAIR_PROVIDERS": "codex"},
        ),
        Case(
            "research_compare_tie_json",
            ["research", "compare.json", "--out", "runs", "--run-id", "compare-tie", "--json"],
            work_orders=compare,
            env={"BAKEOFF_FAKE_JUDGE_MODE": "compare_tie"},
            expect={3},
        ),
        Case(
            "research_compare_position_swap",
            ["research", "compare.json", "--out", "runs", "--run-id", "compare-swap"],
            work_orders=compare,
            env={"BAKEOFF_FAKE_JUDGE_MODE": "compare_always_a"},
            expect={3},
        ),
        Case("research_analyze", ["research", "analyze.json", "--out", "runs", "--run-id", "analyze-run"], work_orders=analyze),
        Case("research_auto_triage", ["research", "review.json", "--out", "runs", "--run-id", "auto-triage"], work_orders=review),
        Case(
            "triage_dry_run_json",
            ["triage", "triage-source", "--out", "runs", "--dry-run", "--json"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "triage-source"])],
            work_orders=gather,
        ),
        Case(
            "triage_force_json",
            ["triage", "triage-source", "--out", "runs", "--force", "--json"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "triage-source"])],
            work_orders=gather,
        ),
        Case(
            "triage_json",
            ["triage", "triage-source", "--out", "runs", "--json"],
            setup=[Action(["research", "review.json", "--out", "runs", "--run-id", "triage-source", "--no-triage"])],
            work_orders=review,
            env={"BAKEOFF_FAKE_TRIAGE_SOURCE_ID": "F-001"},
        ),
        Case(
            "rerun",
            ["rerun", "rerun-source", "--out", "runs", "--run-id", "rerun-target", "--no-triage"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "rerun-source", "--no-triage"])],
            work_orders=gather,
        ),
        Case(
            "ls_json_filter",
            ["ls", "--out", "runs", "--json", "--facet", "code-review", "--triage-state", "yes"],
            setup=[Action(["research", "review.json", "--out", "runs", "--run-id", "ls-review"])],
            work_orders=review,
        ),
        Case(
            "show_report",
            ["show", "show-source", "--out", "runs"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "show-source"])],
            work_orders=gather,
        ),
        Case(
            "show_judge",
            ["show", "show-source", "--out", "runs", "--judge"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "show-source"])],
            work_orders=gather,
        ),
        Case(
            "show_judge_prompt",
            ["show", "show-source", "--out", "runs", "--judge-prompt"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "show-source"])],
            work_orders=gather,
        ),
        Case(
            "show_triage",
            ["show", "show-review", "--out", "runs", "--triage"],
            setup=[Action(["research", "review.json", "--out", "runs", "--run-id", "show-review"])],
            work_orders=review,
        ),
        Case(
            "runs_verify_json",
            ["runs", "verify", "latest", "--out", "runs", "--json"],
            setup=[Action(["research", "gather.json", "--out", "runs", "--run-id", "verify-source"])],
            work_orders=gather,
        ),
        Case(
            "timeout",
            ["research", "gather.json", "--out", "runs", "--run-id", "timeout", "--json"],
            work_orders=timeout,
            env={"BAKEOFF_FAKE_TIMEOUT_PROVIDERS": "claude,codex", "BAKEOFF_FAKE_TIMEOUT_SECONDS": "5"},
            expect={1},
        ),
        Case(
            "cancelled",
            ["research", "gather.json", "--out", "runs", "--run-id", "cancelled", "--json"],
            work_orders=interrupted,
            env={"BAKEOFF_FAKE_TIMEOUT_PROVIDERS": "claude,codex", "BAKEOFF_FAKE_TIMEOUT_SECONDS": "10"},
            expect={130},
            interrupt_after=0.8,
        ),
        Case(
            "scope_error",
            ["research", "gather.json", "--out", "runs", "--run-id", "scope-error", "--json"],
            work_orders=scope_required,
            env={"BAKEOFF_FAKE_SCOPE_HELP_MODE": "none"},
            expect={1},
        ),
        Case(
            "provider_exit_error",
            ["research", "gather.json", "--out", "runs", "--run-id", "provider-exit-error", "--json"],
            work_orders=gather,
            env={"BAKEOFF_FAKE_FAIL_PROVIDERS": "claude,codex"},
            expect={1},
        ),
        Case(
            "output_cap",
            ["research", "gather.json", "--out", "runs", "--run-id", "output-cap", "--json"],
            work_orders=low_cap,
            env={"BAKEOFF_FAKE_OUTPUT_CAP_PROVIDERS": "claude,codex"},
            expect={1},
        ),
        Case(
            "output_cap_salvage",
            ["research", "gather.json", "--out", "runs", "--run-id", "output-cap-salvage", "--json"],
            work_orders=salvage_cap,
            env={"BAKEOFF_FAKE_OUTPUT_CAP_SALVAGE_PROVIDERS": "claude,codex"},
        ),
        Case(
            "output_cap_zero_overrun",
            ["research", "gather.json", "--out", "runs", "--run-id", "output-cap-zero-overrun", "--json"],
            work_orders=zero_overrun_cap,
            env={"BAKEOFF_FAKE_OUTPUT_CAP_PROVIDERS": "claude,codex"},
            expect={1},
        ),
        Case(
            "stderr_truncation",
            ["research", "gather.json", "--out", "runs", "--run-id", "stderr-truncation", "--json"],
            work_orders=stderr_cap,
            env={"BAKEOFF_FAKE_STDERR_TRUNCATION_PROVIDERS": "claude,codex"},
        ),
        Case(
            "missing_provider",
            ["research", "gather.json", "--out", "runs", "--run-id", "missing-provider", "--json"],
            work_orders=gather,
            omit_fake_tools={"codex"},
        ),
        Case(
            "schema_error",
            ["research", "gather.json", "--out", "runs", "--run-id", "schema-error", "--json"],
            work_orders=gather,
            env={"BAKEOFF_FAKE_SCHEMA_ERROR_PROVIDERS": "claude,codex"},
            expect={1},
        ),
    ]


def build_go_binary(out_dir: Path) -> Path:
    binary = out_dir / ("bakeoff.exe" if os.name == "nt" else "bakeoff")
    env = os.environ.copy()
    env.setdefault("GOCACHE", "/tmp/bakeoff-go-cache")
    Path(env["GOCACHE"]).mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/bakeoff"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"go build failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return binary


def cli_argv(target: str, *, go_binary: Path | None = None) -> list[str]:
    if target == "public":
        return [str(ROOT / "bin" / "bakeoff")]
    if go_binary is None:
        raise RuntimeError("go target requires a built bakeoff binary")
    return [str(go_binary)]


def install_fakes(workdir: Path, omit: set[str]) -> Path:
    fake_dir = workdir / "fake-bin"
    fake_dir.mkdir()
    shutil.copy2(FAKES_ROOT / "fake_provider.py", fake_dir / "fake_provider.py")
    os.chmod(fake_dir / "fake_provider.py", 0o755)
    for name in ("claude", "codex"):
        if name in omit:
            continue
        shutil.copy2(FAKES_ROOT / name, fake_dir / name)
        os.chmod(fake_dir / name, 0o755)
    return fake_dir


def prepare_case(workdir: Path, case: Case) -> dict[str, str]:
    fake_dir = install_fakes(workdir, case.omit_fake_tools)
    for relative, data in case.work_orders.items():
        path = workdir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for relative, text in case.jsonc_work_orders.items():
        path = workdir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    env = os.environ.copy()
    env.update(case.env)
    env["PATH"] = str(fake_dir) + os.pathsep + "/usr/bin:/bin:/usr/sbin:/sbin"
    env.setdefault("NO_COLOR", "1")
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    return env


def run_cli(
    target: str,
    argv: list[str],
    *,
    workdir: Path,
    env: dict[str, str],
    go_binary: Path | None = None,
    interrupt_after: float | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [*cli_argv(target, go_binary=go_binary), *argv]
    if interrupt_after is None:
        return subprocess.run(
            command,
            cwd=workdir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    process = subprocess.Popen(
        command,
        cwd=workdir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(interrupt_after)
    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=15)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_case(target: str, case: Case, *, go_binary: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"bakeoff-parity-{case.name}-") as tmp:
        workdir = Path(tmp)
        env = prepare_case(workdir, case)
        if target == "public" and go_binary is not None:
            env["BAKEOFF_GO_BINARY"] = str(go_binary)
        for action in case.setup:
            completed = run_cli(target, action.argv, workdir=workdir, env=env, go_binary=go_binary)
            if completed.returncode not in action.expect:
                raise RuntimeError(
                    f"{case.name} setup failed: {' '.join(action.argv)} exited {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
        completed = run_cli(
            target,
            case.argv,
            workdir=workdir,
            env=env,
            go_binary=go_binary,
            interrupt_after=case.interrupt_after,
        )
        if completed.returncode not in case.expect:
            raise RuntimeError(
                f"{case.name} failed: {' '.join(case.argv)} exited {completed.returncode}, expected {sorted(case.expect)}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        snapshot = snapshot_workspace(workdir)
        return {
            "name": case.name,
            "target": target,
            "argv": case.argv,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "workspace": snapshot,
            "normalized": normalize(
                {
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "workspace": snapshot,
                },
                workdir=workdir,
            ),
        }


def snapshot_workspace(workdir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted(workdir.rglob("*")):
        if path.is_dir() or "fake-bin" in path.parts:
            continue
        relative = path.relative_to(workdir).as_posix()
        if path.is_symlink():
            out[relative] = {"type": "symlink", "target": os.readlink(path)}
            continue
        if path.stat().st_size > 512_000:
            out[relative] = {"type": "large", "size": path.stat().st_size}
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            out[relative] = {"type": "json", "value": json.loads(text)}
        except json.JSONDecodeError:
            out[relative] = {"type": "text", "value": text}
    return out


def normalize(value: Any, *, workdir: Path) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"started_at", "finished_at", "generated_at"}:
                normalized[key] = "<TIMESTAMP>"
            elif key in {"wall_seconds", "last_stdout_age", "last_stderr_age", "last_output_age", "elapsed"}:
                normalized[key] = 0
            elif key == "cwd":
                normalized[key] = "<CWD>"
            elif key == "bakeoff_version":
                normalized[key] = "<BAKEOFF_VERSION>"
            elif key == "mtime_ns":
                normalized[key] = 0
            elif key == "sha256" or key.endswith("_sha256"):
                normalized[key] = "<SHA256>"
            elif key == "size_bytes":
                normalized[key] = 0
            else:
                normalized[key] = normalize(item, workdir=workdir)
        return normalized
    if isinstance(value, list):
        return [normalize(item, workdir=workdir) for item in value]
    if isinstance(value, str):
        text = value.replace(str(workdir), "<WORKDIR>").replace(str(ROOT), "<REPO>")
        text = RUN_ID_RE.sub("<RUN_ID>", text)
        text = TIMESTAMP_RE.sub("<TIMESTAMP>", text)
        text = TMP_RE.sub("<TMPPATH>", text)
        text = SECONDS_RE.sub("<SECONDS>s", text)
        text = JSON_WALL_SECONDS_RE.sub('"wall_seconds": 0', text)
        text = JSON_AGE_RE.sub(r'"\1": 0', text)
        text = JSON_SHA_RE.sub(r'"\1": "<SHA256>"', text)
        return text
    return value


def compare_snapshot(case: Case, result: dict[str, Any]) -> str | None:
    expected_path = FIXTURE_ROOT / case.name / "normalized.json"
    if not expected_path.exists():
        return f"missing fixture: {expected_path}"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    if expected == result["normalized"]:
        return None
    with tempfile.TemporaryDirectory(prefix="bakeoff-parity-diff-") as tmp:
        actual_path = Path(tmp) / "actual.json"
        expected_tmp = Path(tmp) / "expected.json"
        actual_path.write_text(json.dumps(result["normalized"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        expected_tmp.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        diff = subprocess.run(["diff", "-u", str(expected_tmp), str(actual_path)], text=True, capture_output=True, check=False)
        return diff.stdout or f"normalized snapshot differs for {case.name}"


def selected_cases(names: list[str]) -> list[Case]:
    all_cases = cases()
    if not names:
        return all_cases
    wanted = set(names)
    unknown = wanted - {case.name for case in all_cases}
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(sorted(unknown))}")
    return [case for case in all_cases if case.name in wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bakeoff Go parity harness.")
    parser.add_argument("cases", nargs="*", help="optional fixture case names")
    parser.add_argument("--go-only", action="store_true", help="run a temporary compiled Go binary directly")
    parser.add_argument("--public", action="store_true", help="run bin/bakeoff, the default cutover launcher")
    parser.add_argument("--list", action="store_true", help="list fixture case names")
    args = parser.parse_args()

    if args.list:
        for case in cases():
            print(case.name)
        return 0

    selected_targets = [args.go_only, args.public]
    if sum(1 for selected in selected_targets if selected) > 1:
        parser.error("--go-only and --public are mutually exclusive")

    target = "public"
    if args.go_only:
        target = "go"
    failures: list[str] = []
    go_temp = tempfile.TemporaryDirectory(prefix="bakeoff-bin-")
    go_binary = build_go_binary(Path(go_temp.name))

    try:
        for case in selected_cases(args.cases):
            result = run_case(target, case, go_binary=go_binary)
            failure = compare_snapshot(case, result)
            if failure:
                failures.append(f"== {case.name} ==\n{failure}")
            else:
                print(f"ok {case.name}")
    finally:
        if go_temp is not None:
            go_temp.cleanup()

    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
