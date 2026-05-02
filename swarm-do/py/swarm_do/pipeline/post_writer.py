"""Deterministic post-writer reporting for work-unit execution."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .executor import writer_budget_status
from .validation import unit_blocked_file_violations


SCHEMA_VERSION = "post_writer_report.v1"


def build_post_writer_report(
    artifact: Mapping[str, Any],
    unit_id: str,
    *,
    repo: str | Path = ".",
    base_ref: str | None = None,
    writer_return: str = "",
    max_writer_tool_calls: int = 60,
    max_writer_output_bytes: int = 60_000,
    max_handoffs: int = 1,
    telemetry_tool_call_count: int | None = None,
    validation_timeout_seconds: int | None = None,
    run_validation: bool = True,
) -> dict[str, Any]:
    """Build the objective report attached after a writer finishes."""

    unit = _find_unit(artifact, unit_id)
    repo_path = Path(repo)
    resolved_base_ref = _resolve_base_ref(artifact, base_ref)
    changed_files = changed_files_since(repo_path, resolved_base_ref)
    diff_stat = diff_stat_since(repo_path, resolved_base_ref)
    blocked_violations = unit_blocked_file_violations(unit, changed_files)
    out_of_scope_files = unit_out_of_scope_violations(unit, changed_files)
    validation_results = (
        run_validation_commands(unit, repo=repo_path, timeout_seconds=validation_timeout_seconds)
        if run_validation
        else []
    )
    test_summary = summarize_validation_results(validation_results, skipped=not run_validation)
    budget = writer_budget_status(
        unit,
        writer_return,
        diff_size_bytes=diff_stat["diff_size_bytes"],
        max_writer_tool_calls=max_writer_tool_calls,
        max_writer_output_bytes=max_writer_output_bytes,
        max_handoffs=max_handoffs,
        telemetry_tool_call_count=telemetry_tool_call_count,
    )
    gate = _gate_status(blocked_violations, out_of_scope_files, validation_results, budget)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": artifact.get("run_id") if isinstance(artifact.get("run_id"), str) else None,
        "phase_id": artifact.get("phase_id") if isinstance(artifact.get("phase_id"), str) else None,
        "work_unit_id": unit_id,
        "base_ref": resolved_base_ref,
        "base_sha": _rev_parse_or_none(repo_path, resolved_base_ref),
        "unit_contract": _unit_contract(unit),
        "acceptance_matrix": _acceptance_matrix(unit, test_summary),
        "changed_files": changed_files,
        "diff_stat": diff_stat,
        "blocked_file_violations": blocked_violations,
        "out_of_scope_files": out_of_scope_files,
        "validation_results": validation_results,
        "test_summary": test_summary,
        "budget_status": budget,
        "gate": gate,
    }


def format_post_writer_report(report: Mapping[str, Any]) -> str:
    """Render a compact human summary of a post-writer report."""

    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    diff_stat = report.get("diff_stat") if isinstance(report.get("diff_stat"), Mapping) else {}
    test_summary = report.get("test_summary") if isinstance(report.get("test_summary"), Mapping) else {}
    budget = report.get("budget_status") if isinstance(report.get("budget_status"), Mapping) else {}
    lines = [
        f"post-writer report: {report.get('work_unit_id', '<unknown>')}",
        f"  gate: {gate.get('status', 'unknown')}",
        f"  changed_files: {len(report.get('changed_files') or [])}",
        (
            "  diff_stat: "
            f"files={diff_stat.get('files_changed', 0)} "
            f"insertions={diff_stat.get('insertions', 0)} "
            f"deletions={diff_stat.get('deletions', 0)}"
        ),
        f"  blocked_file_violations: {len(report.get('blocked_file_violations') or [])}",
        f"  out_of_scope_files: {len(report.get('out_of_scope_files') or [])}",
        (
            "  validation: "
            f"{test_summary.get('passed', 0)}/{test_summary.get('total', 0)} passed "
            f"({test_summary.get('status', 'unknown')})"
        ),
        f"  budget: {budget.get('status', 'unknown')}",
    ]
    reasons = gate.get("failure_reasons") if isinstance(gate.get("failure_reasons"), list) else []
    if reasons:
        lines.append("  failure_reasons: " + ", ".join(str(reason) for reason in reasons))
    return "\n".join(lines)


def changed_files_since(repo: str | Path, base_ref: str) -> list[str]:
    tracked = _git_lines(repo, "diff", "--name-only", "--relative", base_ref, "--")
    untracked = _git_lines(repo, "ls-files", "--others", "--exclude-standard")
    return sorted({path for path in tracked + untracked if path})


def worktree_diff_summary(
    safe_git_root: Path,
    *,
    base_sha: str,
    project_subdir: str,
    extra_excludes: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Return {committed, staged, unstaged, untracked} paths for a worktree.

    Returned paths are git-root relative. ``project_subdir`` limits results to
    the prepared project checkout. ``extra_excludes`` accepts git-root-relative
    paths or prefixes such as ``data/runs/<run_id>``.
    """

    root = Path(safe_git_root)
    subdir = _normalize_diff_path(project_subdir)
    excludes = tuple(_normalize_diff_path(item) for item in extra_excludes if str(item).strip())
    pathspec = subdir or "."
    committed = _git_name_status_paths(root, "diff", "--name-status", "-z", f"{base_sha}..HEAD", "--", pathspec)
    staged = _git_name_status_paths(root, "diff", "--cached", "--name-status", "-z", "--", pathspec)
    unstaged = _git_name_status_paths(root, "diff", "--name-status", "-z", "--", pathspec)
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard", "-z", "--", pathspec, split_null=True)
    return {
        "committed": _filter_diff_paths(committed, project_subdir=subdir, excludes=excludes),
        "staged": _filter_diff_paths(staged, project_subdir=subdir, excludes=excludes),
        "unstaged": _filter_diff_paths(unstaged, project_subdir=subdir, excludes=excludes),
        "untracked": _filter_diff_paths(untracked, project_subdir=subdir, excludes=excludes),
    }


def changed_files_from_worktree_diff(summary: Mapping[str, Any]) -> list[str]:
    """Compatibility wrapper for legacy ``changed_files`` consumers."""

    values: set[str] = set()
    for key in ("committed", "staged", "unstaged", "untracked"):
        items = summary.get(key)
        if isinstance(items, list):
            values.update(str(item) for item in items if isinstance(item, str) and item)
    return sorted(values)


def diff_stat_since(repo: str | Path, base_ref: str) -> dict[str, Any]:
    shortstat = _git_stdout(repo, "diff", "--shortstat", base_ref, "--")
    raw_numstat = _git_stdout(repo, "diff", "--numstat", base_ref, "--")
    raw_diff = _git_stdout(repo, "diff", "--binary", base_ref, "--")
    parsed = _parse_shortstat(shortstat)
    untracked_stats = [_untracked_file_stat(Path(repo), path) for path in _git_lines(repo, "ls-files", "--others", "--exclude-standard")]
    untracked_stats = [stat for stat in untracked_stats if stat is not None]
    files_changed = parsed["files_changed"] + len(untracked_stats)
    insertions = parsed["insertions"] + sum(int(stat["insertions"]) for stat in untracked_stats)
    deletions = parsed["deletions"]
    untracked_numstat = "\n".join(str(stat["numstat"]) for stat in untracked_stats)
    combined_numstat = "\n".join(part for part in (raw_numstat, untracked_numstat) if part)
    untracked_size = sum(int(stat["size_bytes"]) for stat in untracked_stats)
    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
        "raw_shortstat": _format_shortstat(files_changed, insertions, deletions),
        "raw_git_shortstat": shortstat,
        "raw_numstat": combined_numstat,
        "untracked_files": [str(stat["path"]) for stat in untracked_stats],
        "diff_size_bytes": len(raw_diff.encode("utf-8")) + untracked_size,
    }


def run_validation_commands(
    unit: Mapping[str, Any],
    *,
    repo: str | Path,
    timeout_seconds: int | None = None,
) -> list[dict[str, Any]]:
    commands = unit.get("validation_commands")
    if not isinstance(commands, list):
        return []
    return [
        _run_validation_command(str(command), repo=repo, timeout_seconds=timeout_seconds)
        for command in commands
        if isinstance(command, str) and command.strip()
    ]


def summarize_validation_results(results: list[Mapping[str, Any]], *, skipped: bool = False) -> dict[str, Any]:
    if skipped:
        return {"status": "skipped", "total": 0, "passed": 0, "failed": 0, "failed_commands": []}
    failed_commands = [
        str(result.get("command", ""))
        for result in results
        if result.get("timed_out") is True or result.get("exit_code") != 0
    ]
    passed = len(results) - len(failed_commands)
    status = "not_run" if not results else ("passed" if not failed_commands else "failed")
    return {
        "status": status,
        "total": len(results),
        "passed": passed,
        "failed": len(failed_commands),
        "failed_commands": failed_commands,
    }


def unit_out_of_scope_violations(unit: Mapping[str, Any], changed_files: list[str]) -> list[str]:
    allowed = _str_list(unit.get("allowed_files", unit.get("files")))
    if not allowed:
        return sorted(set(changed_files))
    out_of_scope: list[str] = []
    for changed in changed_files:
        path = Path(changed).as_posix()
        if not any(fnmatch.fnmatch(changed, pattern) or fnmatch.fnmatch(path, pattern) for pattern in allowed):
            out_of_scope.append(changed)
    return sorted(set(out_of_scope))


def _find_unit(artifact: Mapping[str, Any], unit_id: str) -> Mapping[str, Any]:
    units = artifact.get("work_units")
    if not isinstance(units, list):
        raise ValueError("work-unit artifact requires work_units array")
    for unit in units:
        if isinstance(unit, Mapping) and unit.get("id") == unit_id:
            return unit
    raise ValueError(f"work unit not found: {unit_id}")


def _resolve_base_ref(artifact: Mapping[str, Any], base_ref: str | None) -> str:
    if isinstance(base_ref, str) and base_ref.strip():
        return base_ref.strip()
    for key in ("git_base_sha", "git_base_ref"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "HEAD"


def _unit_contract(unit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": unit.get("id"),
        "title": unit.get("title"),
        "goal": unit.get("goal"),
        "depends_on": _str_list(unit.get("depends_on")),
        "allowed_files": _str_list(unit.get("allowed_files", unit.get("files"))),
        "context_files": _str_list(unit.get("context_files")),
        "blocked_files": _str_list(unit.get("blocked_files")),
        "validation_commands": _str_list(unit.get("validation_commands")),
        "expected_results": _str_list(unit.get("expected_results")),
        "risk_tags": _str_list(unit.get("risk_tags")),
        "handoff_notes": unit.get("handoff_notes") if isinstance(unit.get("handoff_notes"), str) else "",
    }


def _acceptance_matrix(unit: Mapping[str, Any], test_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    criteria = _str_list(unit.get("acceptance_criteria"))
    expected_results = _str_list(unit.get("expected_results"))
    validation_commands = _str_list(unit.get("validation_commands"))
    validation_status = test_summary.get("status") if isinstance(test_summary.get("status"), str) else "unknown"
    return [
        {
            "criterion": criterion,
            "expected_result": expected_results[idx] if idx < len(expected_results) else None,
            "validation_commands": validation_commands,
            "validation_status": validation_status,
            "spec_review_status": "requires_review",
        }
        for idx, criterion in enumerate(criteria)
    ]


def _gate_status(
    blocked_file_violations: list[str],
    out_of_scope_files: list[str],
    validation_results: list[Mapping[str, Any]],
    budget_status: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if blocked_file_violations:
        reasons.append("blocked_file_violation")
    if out_of_scope_files:
        reasons.append("unit_out_of_scope")
    if any(result.get("timed_out") is True for result in validation_results):
        reasons.append("validation_timeout")
    if any(result.get("exit_code") != 0 for result in validation_results):
        reasons.append("validation_failed")
    if budget_status.get("status") != "ok":
        reason = budget_status.get("failure_reason")
        reasons.append(str(reason or "budget_status_failed"))
    return {"status": "failed" if reasons else "passed", "failure_reasons": sorted(set(reasons))}


def _rev_parse_or_none(repo: Path, ref: str) -> str | None:
    try:
        return _git_stdout(repo, "rev-parse", ref).strip()
    except Exception:
        return None


def _str_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _run_validation_command(command: str, *, repo: str | Path, timeout_seconds: int | None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(repo),
            shell=True,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": None,
            "timed_out": True,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": _timeout_text(exc.stdout),
            "stderr": _timeout_text(exc.stderr),
        }
    return {
        "command": command,
        "exit_code": result.returncode,
        "timed_out": False,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _parse_shortstat(shortstat: str) -> dict[str, int]:
    return {
        "files_changed": _shortstat_count(shortstat, r"(\d+) files? changed"),
        "insertions": _shortstat_count(shortstat, r"(\d+) insertions?\(\+\)"),
        "deletions": _shortstat_count(shortstat, r"(\d+) deletions?\(-\)"),
    }


def _format_shortstat(files_changed: int, insertions: int, deletions: int) -> str:
    parts: list[str] = []
    if files_changed:
        parts.append(f"{files_changed} {'file' if files_changed == 1 else 'files'} changed")
    if insertions:
        parts.append(f"{insertions} {'insertion' if insertions == 1 else 'insertions'}(+)")
    if deletions:
        parts.append(f"{deletions} {'deletion' if deletions == 1 else 'deletions'}(-)")
    return ", ".join(parts)


def _untracked_file_stat(repo: Path, path: str) -> dict[str, Any] | None:
    target = repo / path
    if not target.is_file():
        return None
    data = target.read_bytes()
    if b"\0" in data:
        return {"path": path, "insertions": 0, "size_bytes": len(data), "numstat": f"-\t-\t{path}"}
    insertions = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return {"path": path, "insertions": insertions, "size_bytes": len(data), "numstat": f"{insertions}\t0\t{path}"}


def _shortstat_count(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def _git_name_status_paths(repo: str | Path, *args: str) -> list[str]:
    fields = _git_lines(repo, *args, split_null=True)
    paths: list[str] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith("R") or status.startswith("C"):
            if index < len(fields):
                paths.append(fields[index])
                index += 1
            if index < len(fields):
                paths.append(fields[index])
                index += 1
            continue
        if index < len(fields):
            paths.append(fields[index])
            index += 1
    return paths


def _filter_diff_paths(
    paths: Iterable[str],
    *,
    project_subdir: str,
    excludes: tuple[str, ...],
) -> list[str]:
    values: set[str] = set()
    for raw in paths:
        path = _normalize_diff_path(raw)
        if not path:
            continue
        if project_subdir and path != project_subdir and not path.startswith(project_subdir + "/"):
            continue
        if any(path == exclude or path.startswith(exclude + "/") for exclude in excludes):
            continue
        values.add(path)
    return sorted(values)


def _normalize_diff_path(value: str | Path) -> str:
    raw = str(value).strip()
    if raw in {"", "."}:
        return ""
    path = Path(raw).as_posix()
    while path.startswith("./"):
        path = path[2:]
    return "" if path == "." else path.strip("/")


def _git_lines(repo: str | Path, *args: str, split_null: bool = False) -> list[str]:
    output = _git_stdout(repo, *args)
    if split_null:
        return [field for field in output.split("\0") if field]
    return [line.strip() for line in output.splitlines() if line.strip()]


def _git_stdout(repo: str | Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        message = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
