"""Tests for role-specs / repo root resolution.

The dogfood case: when a cached plugin snapshot is invoked from inside a real
mstefanko-plugins repo, `_find_role_specs_dir` must resolve to the live repo's
role-specs (CWD walk) rather than the snapshot's own copy (`__file__` walk).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from swarm_do.roles import cli as roles_cli


class FindRoleSpecsDirTests(unittest.TestCase):
    def _make_repo(self, base: Path) -> Path:
        repo = base / "fake-repo"
        (repo / "swarm-do" / "role-specs").mkdir(parents=True)
        return repo

    def test_cwd_walk_resolves_when_run_from_inside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_repo(Path(td))
            inner = repo / "some" / "subdir"
            inner.mkdir(parents=True)
            with patch.object(Path, "cwd", return_value=inner):
                resolved = roles_cli._find_role_specs_dir()
            self.assertEqual(resolved, (repo / "swarm-do" / "role-specs").resolve())

    def test_cwd_walk_resolves_when_cwd_is_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_repo(Path(td))
            with patch.object(Path, "cwd", return_value=repo):
                resolved = roles_cli._find_role_specs_dir()
            self.assertEqual(resolved, (repo / "swarm-do" / "role-specs").resolve())

    def test_file_walk_fallback_when_cwd_unrelated(self) -> None:
        # Point CWD somewhere with no role-specs anywhere up the tree, then
        # confirm the live repo's __file__ walk-up still finds role-specs.
        with tempfile.TemporaryDirectory() as td:
            unrelated = Path(td) / "unrelated"
            unrelated.mkdir()
            with patch.object(Path, "cwd", return_value=unrelated):
                resolved = roles_cli._find_role_specs_dir()
            self.assertTrue(resolved.is_dir())
            self.assertEqual(resolved.name, "role-specs")

    def test_repo_root_is_role_specs_grandparent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._make_repo(Path(td))
            with patch.object(Path, "cwd", return_value=repo):
                resolved = roles_cli._find_repo_root()
            self.assertEqual(resolved, repo.resolve())


if __name__ == "__main__":
    unittest.main()
