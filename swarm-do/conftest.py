"""swarm-do pytest configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

_REPO_ROOT = Path(__file__).resolve().parent
_PY_ROOT = _REPO_ROOT / "py"
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))


@pytest.fixture
def swarm_data_dir(tmp_path: Path) -> Path:
    """A throwaway CLAUDE_PLUGIN_DATA root for tests that need one."""
    data = tmp_path / "swarm-data"
    data.mkdir()
    return data


@pytest.fixture
def swarm_repo_root(tmp_path: Path) -> Path:
    """A throwaway repo root with a seed commit."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
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
    return repo


@pytest.fixture
def fake_path_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Empty directory prepended to PATH so tests can install fake commands."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    yield bin_dir
