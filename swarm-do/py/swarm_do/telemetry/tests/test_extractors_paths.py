"""normalize_path smoke + parity tests vs bin/_lib/normalize-path.sh.

Parity strategy: run the Python port and the bash helper against the same
synthetic inputs, assert identical output. Covers:

  - WORKTREE_ROOT strip
  - relative-path passthrough
  - empty WORKTREE_ROOT passthrough
  - path outside any known prefix (fail-open: strip leading slash)
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from swarm_do.telemetry.extractors.paths import normalize_path
from swarm_do.telemetry.registry import PLUGIN_ROOT


BASH_NORMALIZE = PLUGIN_ROOT / "swarm-do" / "bin" / "_lib" / "normalize-path.sh"


def _run_bash(raw: str, worktree_root: str | None) -> str:
    env = os.environ.copy()
    if worktree_root is not None:
        env["WORKTREE_ROOT"] = worktree_root
    else:
        env.pop("WORKTREE_ROOT", None)
    result = subprocess.run(
        ["bash", str(BASH_NORMALIZE), raw],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result.stdout.rstrip("\n")


class NormalizePathTests(unittest.TestCase):
    def test_worktree_root_strip(self) -> None:
        raw = "/tmp/test-wt/repo/internal/api/foo.go"
        wt = "/tmp/test-wt/repo"
        self.assertEqual(normalize_path(raw, wt), "internal/api/foo.go")

    def test_worktree_root_with_trailing_slash(self) -> None:
        raw = "/tmp/test-wt/repo/a/b.go"
        self.assertEqual(normalize_path(raw, "/tmp/test-wt/repo/"), "a/b.go")

    def test_relative_path_passthrough(self) -> None:
        self.assertEqual(normalize_path("pkg/util/helper.go", ""), "pkg/util/helper.go")

    def test_empty_raw_returns_empty(self) -> None:
        self.assertEqual(normalize_path("", None), "")

    def test_outside_any_prefix_strips_leading_slash(self) -> None:
        # Choose a path outside any plausible repo or WORKTREE_ROOT; expect the
        # resolved absolute path with the leading slash removed.
        raw = "/nonexistent-root-for-swarm-do/phase4/extractors/x.py"
        got = normalize_path(raw, "")
        self.assertFalse(got.startswith("/"))
        self.assertIn("nonexistent-root-for-swarm-do", got)

    # --- Bash parity ---

    @unittest.skipUnless(BASH_NORMALIZE.is_file(), "bash helper missing")
    def test_parity_worktree_strip(self) -> None:
        raw = "/tmp/test-wt/repo/internal/api/foo.go"
        wt = "/tmp/test-wt/repo"
        self.assertEqual(normalize_path(raw, wt), _run_bash(raw, wt))

    @unittest.skipUnless(BASH_NORMALIZE.is_file(), "bash helper missing")
    def test_parity_relative(self) -> None:
        raw = "pkg/util/helper.go"
        # bash helper inherits WORKTREE_ROOT; pass empty to match.
        got_py = normalize_path(raw, "")
        got_sh = _run_bash(raw, "")
        # Both should passthrough "pkg/util/helper.go" (bash realpath resolves
        # relative to CWD but strips REPO_ROOT if found; Python does the same).
        self.assertEqual(got_py, got_sh)


if __name__ == "__main__":
    unittest.main()
