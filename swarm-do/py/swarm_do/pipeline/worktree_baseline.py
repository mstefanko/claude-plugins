"""Worktree baseline snapshots for phase-session recovery evidence."""

from __future__ import annotations

import json
import shutil
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
    snapshot_dir = path.parent / "worktree-baseline-files"
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
        "file_snapshots": _snapshot_dirty_files(root, snapshot_dir, _status_paths(status_lines)),
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
    snapshots = baseline.get("file_snapshots") if isinstance(baseline.get("file_snapshots"), dict) else {}
    try:
        current_lines = _git_lines(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    except Exception as exc:
        return {"changed_files": [], "warning": f"git status failed: {exc}", "diff_summary": ""}
    current_entries = set(current_lines)
    changed_entries = sorted(current_entries.symmetric_difference(baseline_entries))
    changed_paths = _dedupe(_status_paths(changed_entries) + _changed_snapshot_paths(root, snapshots))
    diff_summary = _diff_summary(root, changed_paths, snapshots=snapshots)
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


def _snapshot_dirty_files(repo_root: Path, snapshot_dir: Path, paths: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for rel in paths:
        source = (repo_root / rel).resolve(strict=False)
        entry: dict[str, Any] = {"exists": source.is_file(), "sha256": None, "snapshot_path": None}
        if source.is_file():
            target = snapshot_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            entry["sha256"] = _sha256_file(source)
            entry["snapshot_path"] = str(target)
        snapshots[rel] = entry
    return snapshots


def _changed_snapshot_paths(repo_root: Path, snapshots: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for rel, raw_entry in snapshots.items():
        if not isinstance(raw_entry, dict):
            continue
        current = repo_root / rel
        baseline_exists = bool(raw_entry.get("exists"))
        current_exists = current.is_file()
        if baseline_exists != current_exists:
            changed.append(rel)
            continue
        if baseline_exists and current_exists and raw_entry.get("sha256") != _sha256_file(current):
            changed.append(rel)
    return changed


def _diff_summary(repo_root: Path, changed_paths: list[str], *, snapshots: dict[str, Any]) -> str:
    chunks: list[str] = []
    if changed_paths:
        chunks.append("Baseline-relative changed files:\n" + "\n".join(f"- {path}" for path in changed_paths))
    clean_baseline_paths = [path for path in changed_paths if path not in snapshots]
    for args in (["diff", "--name-status", "--", *clean_baseline_paths], ["diff", "--shortstat", "--", *clean_baseline_paths]):
        if not clean_baseline_paths:
            continue
        try:
            output = "\n".join(_git_lines(repo_root, args))
        except Exception as exc:
            output = f"{' '.join(args)} failed: {exc}"
        if output:
            chunks.append(output)
    snapshot_diffs = _snapshot_diffs(repo_root, changed_paths, snapshots)
    if snapshot_diffs:
        chunks.append(snapshot_diffs)
    text = "\n\n".join(chunks).strip()
    if len(text.encode("utf-8")) <= MAX_DIFF_BYTES:
        return text
    return text.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore").rstrip() + "\n[diff summary truncated]"


def _snapshot_diffs(repo_root: Path, changed_paths: list[str], snapshots: dict[str, Any]) -> str:
    chunks: list[str] = []
    for rel in changed_paths:
        raw_entry = snapshots.get(rel)
        if not isinstance(raw_entry, dict):
            continue
        snapshot_path = raw_entry.get("snapshot_path")
        current = repo_root / rel
        if not snapshot_path:
            chunks.append(f"{rel}: absent at baseline, present={current.exists()}")
            continue
        if not current.is_file():
            chunks.append(f"{rel}: deleted since baseline")
            continue
        proc = subprocess.run(
            ["diff", "-u", str(snapshot_path), str(current)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode in {0, 1} and proc.stdout:
            chunks.append(f"Baseline diff for {rel}:\n{proc.stdout.rstrip()}")
        elif proc.stderr:
            chunks.append(f"Baseline diff for {rel} failed: {proc.stderr.strip()}")
    return "\n\n".join(chunks)


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["changed_files_since_baseline", "snapshot_worktree_baseline"]
