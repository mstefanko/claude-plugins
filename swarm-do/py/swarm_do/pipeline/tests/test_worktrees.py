from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.worktrees import (
    WorktreeMergeConflict,
    ensure_integration_branch,
    merge_conflict_event,
    merge_unit_branch,
    unit_branch_name,
    unit_worktree_path,
)


class WorktreeTests(unittest.TestCase):
    def test_branch_and_worktree_names_are_predictable(self) -> None:
        self.assertEqual(unit_branch_name("run/1", "unit a"), "swarm/run-1/unit-a")
        self.assertEqual(
            unit_worktree_path("/repo", "run/1", "unit a"),
            Path("/repo/.swarm-do/worktrees/run-1/unit-a"),
        )

    def test_merge_conflict_propagates_without_reset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git(repo, "init")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "Test User")
            (repo / "shared.txt").write_text("base\n", encoding="utf-8")
            git(repo, "add", "shared.txt")
            git(repo, "commit", "-m", "base")

            integration = ensure_integration_branch(repo, "01ARZ3NDEKTSV4RRFFQ69G5FAV")
            git(repo, "checkout", "-b", "swarm/01ARZ3NDEKTSV4RRFFQ69G5FAV/unit-a")
            (repo / "shared.txt").write_text("unit\n", encoding="utf-8")
            git(repo, "commit", "-am", "unit change")
            git(repo, "checkout", integration)
            (repo / "shared.txt").write_text("integration\n", encoding="utf-8")
            git(repo, "commit", "-am", "integration change")

            with self.assertRaises(WorktreeMergeConflict) as raised:
                merge_unit_branch(repo, integration, "swarm/01ARZ3NDEKTSV4RRFFQ69G5FAV/unit-a")

            self.assertEqual(raised.exception.conflicted_files, ["shared.txt"])
            self.assertEqual(git_out(repo, "diff", "--name-only", "--diff-filter=U"), "shared.txt")

    def test_merge_conflict_event_payload(self) -> None:
        event = merge_conflict_event(
            run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            bd_epic_id="bd-1",
            phase_id="phase-1",
            work_unit_id="unit-a",
            integration_branch="swarm/01/integration",
            unit_branch="swarm/01/unit-a",
            conflicted_files=["shared.txt"],
        )

        self.assertEqual(event["event_type"], "worktree_merge_conflict")
        self.assertEqual(event["details"]["conflicted_files"], ["shared.txt"])


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    unittest.main()
