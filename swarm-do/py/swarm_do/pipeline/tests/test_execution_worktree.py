from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.execution_worktree import (
    RunExecutionWorktreeError,
    adopt_run_worktree,
    cleanup_run_worktree,
    execution_branch_name,
    materialize_run_execution_worktree,
    resolve_run_execution_worktree,
)
from swarm_do.pipeline.prepare import accept_prepared, prepare_plan_run


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class ExecutionWorktreeTests(unittest.TestCase):
    def test_monorepo_subdir_mapping_and_artifact_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)

            resolved = resolve_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            self.assertEqual(resolved.source_git_root, git_root.resolve(strict=False))
            self.assertEqual(resolved.project_subdir, "swarm-do")
            self.assertEqual(resolved.safe_git_root, (data / "worktrees" / RUN_ID / "repo").resolve(strict=False))
            self.assertEqual(resolved.safe_project_root, (data / "worktrees" / RUN_ID / "repo" / "swarm-do").resolve(strict=False))

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertEqual(worktree.branch, execution_branch_name(RUN_ID))
            self.assertTrue((worktree.safe_project_root / "data" / "runs" / RUN_ID / "prepared.md").is_file())
            copied_prepared = json.loads(
                (worktree.safe_project_root / "data" / "runs" / RUN_ID / "prepared_plan.v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(copied_prepared["repo_root"], str(worktree.safe_project_root))
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_git_root"], str(git_root.resolve(strict=False)))
            self.assertEqual(manifest["safe_project_root"], str(worktree.safe_project_root))
            self.assertGreaterEqual(len(manifest["copied_artifacts"]), 3)

    def test_dirty_source_project_blocks_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "docs").mkdir()
            (project / "docs" / "dirty.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaises(RunExecutionWorktreeError) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn("dirty.md", str(raised.exception))

    def test_adopt_run_dry_run_apply_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("new\n", encoding="utf-8")

            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)
            self.assertFalse(dry_run["applied"])
            self.assertEqual(dry_run["changed_files"], ["docs/new.md"])
            self.assertEqual(
                dry_run["copyback_operations"][0]["destination_path"],
                str((project / "docs" / "new.md").resolve(strict=False)),
            )
            self.assertFalse((project / "docs" / "new.md").exists())

            applied = adopt_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(applied["applied"])
            self.assertEqual((project / "docs" / "new.md").read_text(encoding="utf-8"), "new\n")

            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data)
            self.assertTrue(cleanup["eligible"])
            cleanup_applied = cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(cleanup_applied["applied"])
            self.assertFalse(worktree.safe_git_root.exists())


def _prepared_monorepo(root: Path) -> tuple[Path, Path, Path, dict]:
    git_root = root / "home" / ".claude" / "plugins" / "mstefanko-plugins"
    project = git_root / "swarm-do"
    data = root / "data"
    project.mkdir(parents=True)
    data.mkdir()
    _git(git_root, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text("data/runs/\n", encoding="utf-8")
    (project / "plan.md").write_text(
        (
            "### Phase 1: Tiny\n\n"
            "Do a tiny thing.\n\n"
            "### Files to create / modify\n"
            "- docs/new.md\n\n"
            "### Acceptance Criteria\n"
            "- Tiny thing is done.\n\n"
            "### Validation Commands\n"
            "- python3 -m unittest py.swarm_do.pipeline.tests.test_execution_worktree\n"
        ),
        encoding="utf-8",
    )
    _git(git_root, "add", "swarm-do/.gitignore", "swarm-do/plan.md")
    _git(git_root, "commit", "-q", "-m", "seed")
    result = prepare_plan_run(
        "plan.md",
        run_id=RUN_ID,
        repo_root=project,
        data_dir=data,
        decompose_workers=1,
    )
    if result.status != "ready_for_acceptance":
        raise AssertionError(result.to_dict())
    accept_prepared(RUN_ID, repo_root=project, data_dir=data)
    prepared = json.loads((data / "runs" / RUN_ID / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    return git_root, project, data, prepared


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.test",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ).stdout.strip()


if __name__ == "__main__":
    unittest.main()
