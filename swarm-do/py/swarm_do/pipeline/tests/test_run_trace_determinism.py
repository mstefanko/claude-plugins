from __future__ import annotations

import unittest

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.run_trace import build_trace_from_run_dir, trace_to_json


FIXTURE = REPO_ROOT / "tests" / "fixtures" / "run-traces" / "retryable-failure-then-success"


class RunTraceDeterminismTests(unittest.TestCase):
    def test_same_fixture_builds_byte_identical_json(self) -> None:
        kwargs = {
            "data_dir": FIXTURE,
            "events_path": FIXTURE / "events.jsonl",
            "active_path": FIXTURE / "active-run.json",
            "worktree_manifest_path": FIXTURE / "worktrees" / "01J00000000000000000000002" / "manifest.json",
        }
        first = trace_to_json(build_trace_from_run_dir(FIXTURE / "run", **kwargs))
        second = trace_to_json(build_trace_from_run_dir(FIXTURE / "run", **kwargs))

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
