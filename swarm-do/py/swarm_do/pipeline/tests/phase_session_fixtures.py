from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from swarm_do.pipeline.prepare import accept_prepared, prepare_plan_run


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def _purge_run_worktree_leaks(run_id: str) -> None:
    """Remove any pre-existing worktree dir for this run_id at the safe-fallback paths.

    `_safe_run_worktree_root` walks four candidates (data_dir → XDG → /tmp → tempdir).
    Tests routinely fail candidates 1 and 2 (sensitive prefixes) and land on /tmp;
    once a /tmp dir exists from a prior run, the next run trips on
    "run worktree path already exists without a valid manifest". Clear leftovers
    eagerly so every test invocation starts clean.
    """
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    candidates = [
        Path(xdg).expanduser() / "swarmdaddy" / "worktrees" / run_id,
        Path("/tmp") / "swarmdaddy-worktrees" / run_id,
        Path(tempfile.gettempdir()) / "swarmdaddy-worktrees" / run_id,
    ]
    for path in candidates:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def make_prepared_run(
    tmp: Path,
    *,
    run_id: str = RUN_ID,
    phase_count: int = 3,
    repo_path: Path | None = None,
    commit_plan: bool = False,
    ignore_run_artifacts: bool = False,
) -> tuple[Path, Path, str]:
    repo = repo_path or tmp / "repo"
    data = tmp / "data"
    repo.parent.mkdir(parents=True, exist_ok=True)
    repo.mkdir()
    data.mkdir()
    # Pin _default_worktree_data_dir() under tmp so a tmp-data_dir rejection
    # (e.g., tmp resolving inside a sensitive prefix) can't fall back to
    # ~/.local/share/swarmdaddy and leak per-run worktrees across test runs.
    xdg = tmp / "xdg"
    xdg.mkdir(exist_ok=True)
    os.environ["XDG_DATA_HOME"] = str(xdg)
    # Clear any pre-existing fallback worktree dirs for this run_id so we can't
    # trip on "run worktree path already exists without a valid manifest".
    _purge_run_worktree_leaks(run_id)
    _git_init(repo)
    if ignore_run_artifacts:
        (repo / ".gitignore").write_text("data/runs/\n", encoding="utf-8")
        _git_commit(repo, [".gitignore"], "ignore run artifacts")
    plan = repo / "plan.md"
    plan.write_text(_plan_text(phase_count), encoding="utf-8")
    if commit_plan:
        _git_commit(repo, ["plan.md"], "add plan")
    result = prepare_plan_run(
        "plan.md",
        run_id=run_id,
        data_dir=data,
        repo_root=repo,
        decompose_workers=1,
    )
    if result.status != "ready_for_acceptance":
        raise AssertionError(result.to_dict())
    accept_prepared(run_id, data_dir=data, repo_root=repo)
    return repo, data, run_id


def _git_init(repo: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.test",
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True, env=env)


def _git_commit(repo: Path, paths: list[str], message: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.test",
    }
    subprocess.run(["git", "add", *paths], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, env=env)


def _plan_text(phase_count: int) -> str:
    chunks = []
    for idx in range(1, phase_count + 1):
        chunks.append(
            f"""### Phase {idx}: Phase {idx}

Implement phase {idx}.

### Files to create / modify
- docs/phase-{idx}.md

### Acceptance Criteria
- Phase {idx} acceptance is met.

### Validation Commands
- python3 -m unittest py.swarm_do.pipeline.tests.test_phase_sessions
"""
        )
    return "\n".join(chunks)
