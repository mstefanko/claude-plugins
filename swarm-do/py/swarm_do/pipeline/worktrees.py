"""Git worktree and integration-branch helpers for work-unit execution."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MergeResult:
    integration_branch: str
    unit_branch: str
    head_sha: str


class WorktreeMergeConflict(RuntimeError):
    """Raised when merging a unit branch leaves the integration branch conflicted."""

    def __init__(self, integration_branch: str, unit_branch: str, conflicted_files: list[str], output: str) -> None:
        self.integration_branch = integration_branch
        self.unit_branch = unit_branch
        self.conflicted_files = conflicted_files
        self.output = output
        files = ", ".join(conflicted_files) if conflicted_files else "unknown files"
        super().__init__(f"merge conflict merging {unit_branch} into {integration_branch}: {files}")


def integration_branch_name(run_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/integration"


def unit_branch_name(run_id: str, unit_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/{_safe_ref_segment(unit_id)}"


def unit_worktree_path(repo: str | Path, run_id: str, unit_id: str) -> Path:
    return Path(repo) / ".swarm-do" / "worktrees" / _safe_ref_segment(run_id) / _safe_ref_segment(unit_id)


def ensure_integration_branch(repo: str | Path, run_id: str, *, base_ref: str = "HEAD") -> str:
    branch = integration_branch_name(run_id)
    if not _branch_exists(repo, branch):
        _git(repo, "branch", branch, base_ref)
    return branch


def add_unit_worktree(repo: str | Path, run_id: str, unit_id: str, *, base_ref: str = "HEAD") -> tuple[Path, str]:
    branch = unit_branch_name(run_id, unit_id)
    path = unit_worktree_path(repo, run_id, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _branch_exists(repo, branch):
        _git(repo, "worktree", "add", str(path), branch)
    else:
        _git(repo, "worktree", "add", "-b", branch, str(path), base_ref)
    return path, branch


def remove_unit_worktree(repo: str | Path, run_id: str, unit_id: str, *, force: bool = False) -> None:
    path = unit_worktree_path(repo, run_id, unit_id)
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    _git(repo, *args)


def merge_unit_branch(repo: str | Path, integration_branch: str, unit_branch: str) -> MergeResult:
    _git(repo, "checkout", integration_branch)
    result = _run_git(
        repo,
        "merge",
        "--no-ff",
        unit_branch,
        "-m",
        f"Merge work unit {unit_branch}",
        check=False,
    )
    conflicted = _conflicted_files(repo)
    if result.returncode != 0 or conflicted:
        raise WorktreeMergeConflict(integration_branch, unit_branch, conflicted, _combined_output(result))
    return MergeResult(integration_branch, unit_branch, _git_stdout(repo, "rev-parse", "HEAD"))


def merge_conflict_event(
    *,
    run_id: str,
    bd_epic_id: str | None,
    phase_id: str | None,
    work_unit_id: str,
    integration_branch: str,
    unit_branch: str,
    conflicted_files: list[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "event_type": "worktree_merge_conflict",
        "bd_epic_id": bd_epic_id,
        "phase_id": phase_id,
        "work_unit_id": work_unit_id,
        "child_bead_ids": None,
        "reason": "merge-conflict",
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": {
            "integration_branch": integration_branch,
            "unit_branch": unit_branch,
            "conflicted_files": conflicted_files,
        },
        "schema_ok": True,
    }


def _safe_ref_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not safe or safe in {".", ".."}:
        raise ValueError(f"invalid git ref segment: {value!r}")
    return safe


def _branch_exists(repo: str | Path, branch: str) -> bool:
    return _run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _conflicted_files(repo: str | Path) -> list[str]:
    output = _git_stdout(repo, "diff", "--name-only", "--diff-filter=U")
    return [line for line in output.splitlines() if line]


def _git(repo: str | Path, *args: str) -> None:
    _run_git(repo, *args, check=True)


def _git_stdout(repo: str | Path, *args: str) -> str:
    return _run_git(repo, *args, check=True).stdout.strip()


def _run_git(repo: str | Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise RuntimeError(_combined_output(result) or f"git {' '.join(args)} failed")
    return result


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
