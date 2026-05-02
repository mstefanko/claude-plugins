from __future__ import annotations

import json
import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stderr

from swarm_do.pipeline.cli import cmd_trace
from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.run_trace import build_trace_from_run_dir, trace_to_json


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "run-traces"


class RunTraceTests(unittest.TestCase):
    def test_clean_fixture_builds_versioned_trace_without_raw_prompt(self) -> None:
        fixture = FIXTURES / "clean-single-phase"
        trace = build_trace_from_run_dir(
            fixture / "run",
            data_dir=fixture,
            events_path=fixture / "events.jsonl",
            active_path=fixture / "active-run.json",
            worktree_manifest_path=fixture / "worktrees" / "01J00000000000000000000000" / "manifest.json",
        )

        self.assertEqual(trace.schema_version, 1)
        self.assertEqual(trace.run_id, "01J00000000000000000000000")
        self.assertEqual([phase.status_transitions for phase in trace.phases], [["pending", "running", "complete"]])
        self.assertEqual(len(trace.attempts), 1)
        self.assertEqual(trace.attempts[0].tokens, {"input": 10, "output": 5})
        self.assertEqual(trace.attempts[0].cost_usd, 0.01)
        self.assertIn("prepared_plan.v1.json", {artifact.path for artifact in trace.artifacts})
        self.assertEqual([], trace.unrecognized_artifacts)
        self.assertNotIn("SECRET_TOKEN_DO_NOT_INLINE", trace_to_json(trace))

    def test_provider_review_and_worktree_families_are_projected(self) -> None:
        provider = FIXTURES / "provider-review-partial-success"
        provider_trace = build_trace_from_run_dir(
            provider / "run",
            data_dir=provider,
            events_path=provider / "events.jsonl",
            active_path=provider / "active-run.json",
            worktree_manifest_path=provider / "worktrees" / "01J00000000000000000000003" / "manifest.json",
        )
        self.assertEqual(len(provider_trace.provider_reviews), 1)
        self.assertEqual(provider_trace.provider_reviews[0].status, "partial_success")
        self.assertEqual(provider_trace.provider_reviews[0].selected_providers, ["codex"])

        drift = FIXTURES / "worktree-drift"
        drift_trace = build_trace_from_run_dir(
            drift / "run",
            data_dir=drift,
            events_path=drift / "events.jsonl",
            active_path=drift / "active-run.json",
            worktree_manifest_path=drift / "worktrees" / "01J00000000000000000000004" / "manifest.json",
        )
        self.assertEqual(len(drift_trace.worktree_observations), 1)
        self.assertEqual(drift_trace.worktree_observations[0].drift_kind, "base_drift_safe")

    def test_malformed_result_is_warning_not_content_inline(self) -> None:
        fixture = FIXTURES / "malformed-result"
        trace = build_trace_from_run_dir(
            fixture / "run",
            data_dir=fixture,
            events_path=fixture / "events.jsonl",
            active_path=fixture / "active-run.json",
            worktree_manifest_path=fixture / "worktrees" / "01J00000000000000000000005" / "manifest.json",
        )

        self.assertIn("malformed_result", [warning.kind for warning in trace.warnings])
        payload = json.loads(trace_to_json(trace))
        self.assertEqual(payload["attempts"][0]["failure_kind"], "result_json_invalid")

    def test_streaming_stage_controller_metadata_passes_through(self) -> None:
        fixture = FIXTURES / "streaming-stage-adoption"
        trace = build_trace_from_run_dir(
            fixture / "run",
            data_dir=fixture,
            events_path=fixture / "events.jsonl",
            active_path=fixture / "active-run.json",
            worktree_manifest_path=fixture / "worktrees" / "01J00000000000000000000006" / "manifest.json",
        )

        controller = trace.attempts[0].stage_controller
        self.assertIsNotNone(controller)
        self.assertTrue(controller["completed"])
        self.assertEqual(controller["pending_marker_count"], 0)
        self.assertEqual(controller["duplicate_marker_count"], 1)
        self.assertEqual(controller["ignored_frame_types"], {})

    def test_trace_cli_returns_three_for_missing_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cmd_trace(
                    argparse.Namespace(
                        trace_command="build",
                        run_id="01J00000000000000000009999",
                        data_dir=td,
                        out=None,
                        json=True,
                    )
                )

        self.assertEqual(code, 3)
        self.assertIn("run directory not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
