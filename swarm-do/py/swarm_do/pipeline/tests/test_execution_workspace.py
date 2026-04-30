from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.execution_workspace import (
    ExecutionWorkspaceError,
    create_execution_workspace,
    repo_id_for_path,
)


class ExecutionWorkspaceTests(unittest.TestCase):
    def test_repo_outside_sensitive_root_uses_real_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            data = root / "data"
            repo.mkdir()
            data.mkdir()

            workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / ".claude"])

            self.assertEqual(workspace.mode, "real")
            self.assertEqual(workspace.launcher_cwd, repo.resolve(strict=False))
            self.assertFalse(workspace.launcher_repo_root.is_symlink())

    def test_repo_inside_sensitive_root_uses_stable_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            data = root / "data"
            repo.mkdir(parents=True)
            data.mkdir()

            workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])

            expected = data / "launcher-workspaces" / repo_id_for_path(repo) / "repo"
            self.assertEqual(workspace.mode, "safe-symlink")
            self.assertEqual(workspace.launcher_repo_root, expected)
            self.assertTrue(workspace.launcher_repo_root.is_symlink())
            self.assertEqual(workspace.launcher_repo_root.resolve(strict=False), repo.resolve(strict=False))

    def test_existing_correct_symlink_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            data = root / "data"
            repo.mkdir(parents=True)
            symlink = data / "launcher-workspaces" / repo_id_for_path(repo) / "repo"
            symlink.parent.mkdir(parents=True)
            symlink.symlink_to(repo, target_is_directory=True)

            workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])

            self.assertEqual(workspace.launcher_repo_root, symlink)
            self.assertEqual(workspace.mode, "safe-symlink")

    def test_existing_wrong_symlink_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            other = root / "other"
            data = root / "data"
            repo.mkdir(parents=True)
            other.mkdir()
            symlink = data / "launcher-workspaces" / repo_id_for_path(repo) / "repo"
            symlink.parent.mkdir(parents=True)
            symlink.symlink_to(other, target_is_directory=True)

            with self.assertRaises(ExecutionWorkspaceError):
                create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])

    def test_concurrent_symlink_creation_is_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            data = root / "data"
            repo.mkdir(parents=True)
            data.mkdir()
            original_symlink_to = Path.symlink_to

            def racing_symlink_to(self: Path, target: Path, target_is_directory: bool = False) -> None:
                original_symlink_to(self, target, target_is_directory=target_is_directory)
                raise FileExistsError(str(self))

            with mock.patch("pathlib.Path.symlink_to", racing_symlink_to):
                workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])

            self.assertEqual(workspace.mode, "safe-symlink")
            self.assertEqual(workspace.launcher_repo_root.resolve(strict=False), repo.resolve(strict=False))

    def test_launcher_workspace_under_sensitive_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sensitive = root / "home" / ".claude"
            repo = sensitive / "plugins" / "swarm-do"
            data = sensitive / "state"
            repo.mkdir(parents=True)
            data.mkdir()

            with self.assertRaises(ExecutionWorkspaceError):
                create_execution_workspace(repo, data_dir=data, sensitive_roots=[sensitive])

    def test_prompt_rewrite_and_assertion_for_option_b(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            data = root / "data"
            repo.mkdir(parents=True)
            data.mkdir()
            workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])
            text = f"Edit {repo}/py/swarm_do/pipeline/phase_pump.py"

            rewritten, count = workspace.rewrite_prompt(text)

            self.assertEqual(count, 1)
            self.assertIn(str(workspace.launcher_repo_root), rewritten)
            self.assertNotIn(str(repo), rewritten)
            workspace.assert_prompt_safe(rewritten)
            with self.assertRaises(ExecutionWorkspaceError):
                workspace.assert_prompt_safe(text)

    def test_safe_cwd_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"SWARM_CLAUDE_SAFE_CWD": "0"}):
            root = Path(td)
            repo = root / "home" / ".claude" / "plugins" / "swarm-do"
            data = root / "data"
            repo.mkdir(parents=True)
            data.mkdir()

            workspace = create_execution_workspace(repo, data_dir=data, sensitive_roots=[root / "home" / ".claude"])

            self.assertEqual(workspace.mode, "disabled")
            self.assertFalse(workspace.safe_cwd_enabled)
            self.assertEqual(workspace.launcher_cwd, repo.resolve(strict=False))


if __name__ == "__main__":
    unittest.main()
