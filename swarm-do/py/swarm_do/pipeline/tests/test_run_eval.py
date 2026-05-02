from __future__ import annotations

import unittest
import argparse
import io
from contextlib import redirect_stderr

from swarm_do.pipeline.cli import cmd_eval
from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.run_eval import EvalMismatch, first_mismatch, run_fixtures
from swarm_do.pipeline.run_trace import build_trace_from_run_dir


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "run-traces"


class RunEvalTests(unittest.TestCase):
    def test_all_committed_fixtures_pass(self) -> None:
        result = run_fixtures(FIXTURES)

        self.assertEqual(result.status, "passed")
        self.assertIsNone(result.first_mismatch)
        self.assertEqual(
            [item.fixture for item in result.results],
            [
                "clean-single-phase",
                "malformed-result",
                "needs-input",
                "provider-review-partial-success",
                "retryable-failure-then-success",
                "streaming-legacy-fallback",
                "streaming-malformed-raw",
                "streaming-stage-adoption",
                "worktree-drift",
            ],
        )

    def test_first_mismatch_names_kind_expected_actual_and_path(self) -> None:
        fixture = FIXTURES / "clean-single-phase"
        trace = build_trace_from_run_dir(
            fixture / "run",
            data_dir=fixture,
            events_path=fixture / "events.jsonl",
            active_path=fixture / "active-run.json",
            worktree_manifest_path=fixture / "worktrees" / "01J00000000000000000000000" / "manifest.json",
        )
        mismatch = first_mismatch(
            trace,
            {
                "schema_version": 1,
                "required_artifacts": ["missing.json"],
                "expected_phase_transitions": [],
                "expected_attempts": [],
                "expected_warnings": [],
                "forbidden_warnings": [],
                "unrecognized_artifacts_allowed": False,
            },
        )

        self.assertIsInstance(mismatch, EvalMismatch)
        self.assertEqual(mismatch.kind, "missing_required_artifact")
        self.assertEqual(mismatch.expected, "missing.json")
        self.assertEqual(mismatch.path, "missing.json")

    def test_stage_adoption_precedes_phase_exit_expectation(self) -> None:
        fixture = FIXTURES / "streaming-stage-adoption"
        trace = build_trace_from_run_dir(
            fixture / "run",
            data_dir=fixture,
            events_path=fixture / "events.jsonl",
            active_path=fixture / "active-run.json",
            worktree_manifest_path=fixture / "worktrees" / "01J00000000000000000000006" / "manifest.json",
        )

        mismatch = first_mismatch(
            trace,
            {
                "schema_version": 1,
                "required_artifacts": [],
                "expected_phase_transitions": [],
                "expected_attempts": [],
                "expected_adoption_precedes_exit": [{"phase_id": "p1", "stage_id": "missing"}],
                "expected_warnings": [],
                "forbidden_warnings": [],
                "unrecognized_artifacts_allowed": True,
            },
        )

        self.assertIsInstance(mismatch, EvalMismatch)
        self.assertEqual(mismatch.kind, "stage_adoption_missing")

    def test_include_trace_requires_json(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = cmd_eval(
                argparse.Namespace(
                    eval_command="run",
                    fixture_dir=str(FIXTURES / "clean-single-phase"),
                    json=False,
                    include_trace=True,
                )
            )

        self.assertEqual(code, 2)
        self.assertIn("--include-trace requires --json", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
