"""Worktree baseline snapshots for phase-session recovery evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT, resolve_data_dir
from .run_state import _atomic_json_write, utc_now


MAX_DIFF_BYTES = 12_000


def snapshot_worktree_baseline(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    root = (repo_root or REPO_ROOT).resolve(strict=False)
    path = base / "runs" / run_id / "phase_recovery" / "worktree-baseline.json"
    warning = None
    status_lines: list[str] = []
    try:
        status_lines = _git_lines(root, ["status", "--porcelain=v1", "--untracked-files=all"])
        _git_lines(root, ["rev-parse", "--is-inside-work-tree"])
    except Exception as exc:
        warning = str(exc)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": utc_now(),
        "repo_root": str(root),
        "status_porcelain": status_lines,
        "tracked_paths": _status_paths(status_lines),
        "warning": warning,
    }
    _atomic_json_write(path, payload)
    return {"path": str(path), "warning": warning, "dirty": bool(status_lines)}


def changed_files_since_baseline(
    baseline_path: str | Path | None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if not baseline_path:
        return {"changed_files": [], "warning": "worktree baseline unavailable", "diff_summary": ""}
    path = Path(str(baseline_path))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"changed_files": [], "warning": f"worktree baseline unreadable: {exc}", "diff_summary": ""}
    root = (repo_root or Path(str(baseline.get("repo_root") or REPO_ROOT))).resolve(strict=False)
    baseline_entries = {str(item) for item in baseline.get("status_porcelain") or [] if isinstance(item, str)}
    try:
        current_lines = _git_lines(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    except Exception as exc:
        return {"changed_files": [], "warning": f"git status failed: {exc}", "diff_summary": ""}
    changed_entries = [line for line in current_lines if line not in baseline_entries]
    changed_paths = _status_paths(changed_entries)
    diff_summary = _diff_summary(root, changed_paths)
    return {
        "changed_files": changed_paths,
        "warning": None,
        "diff_summary": diff_summary,
        "current_status_porcelain": current_lines,
    }


def _git_lines(repo_root: Path, args: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git command failed").strip())
    return [line for line in proc.stdout.splitlines() if line]


def _status_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in lines:
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path not in paths:
            paths.append(path)
    return paths


def _diff_summary(repo_root: Path, changed_paths: list[str]) -> str:
    chunks: list[str] = []
    for args in (["diff", "--name-status"], ["diff", "--shortstat"]):
        try:
            output = "\n".join(_git_lines(repo_root, args))
        except Exception as exc:
            output = f"{' '.join(args)} failed: {exc}"
        if output:
            chunks.append(output)
    if changed_paths:
        chunks.append("Changed files since baseline:\n" + "\n".join(f"- {path}" for path in changed_paths))
    text = "\n\n".join(chunks).strip()
    if len(text.encode("utf-8")) <= MAX_DIFF_BYTES:
        return text
    return text.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore").rstrip() + "\n[diff summary truncated]"


__all__ = ["changed_files_since_baseline", "snapshot_worktree_baseline"]
