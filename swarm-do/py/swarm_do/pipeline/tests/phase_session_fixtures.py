from __future__ import annotations

import os
import subprocess
from pathlib import Path

from swarm_do.pipeline.prepare import accept_prepared, prepare_plan_run


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def make_prepared_run(
    tmp: Path,
    *,
    run_id: str = RUN_ID,
    phase_count: int = 3,
    repo_path: Path | None = None,
) -> tuple[Path, Path, str]:
    repo = repo_path or tmp / "repo"
    data = tmp / "data"
    repo.parent.mkdir(parents=True, exist_ok=True)
    repo.mkdir()
    data.mkdir()
    _git_init(repo)
    plan = repo / "plan.md"
    plan.write_text(_plan_text(phase_count), encoding="utf-8")
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
