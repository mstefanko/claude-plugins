from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.orchestrator_stream import parse_stage_marker_line, parse_stage_markers
from swarm_do.pipeline.phase_pump import _process_stage_markers
from swarm_do.pipeline.stage_invocation import plan_stage_invocations, render_orchestrator_brief
from swarm_do.pipeline.stage_sessions import (
    claim_stage,
    init_stage_sessions,
    load_stage_sessions,
    record_stage_adopted,
)


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class StageQualityTests(unittest.TestCase):
    def test_marker_parser_accepts_bounded_complete_and_failed_lines(self) -> None:
        complete = parse_stage_marker_line('STAGE_COMPLETE {"stage_id":"writer","result_path":"/tmp/result.json"}')
        failed = parse_stage_marker_line('STAGE_FAILED {"stage_id":"review","failure_kind":"spec_mismatch","notes":"nope"}')

        self.assertIsNotNone(complete)
        self.assertEqual(complete.stage_id, "writer")
        self.assertEqual(complete.kind, "complete")
        self.assertIsNotNone(failed)
        self.assertEqual(failed.kind, "failed")
        self.assertEqual(failed.failure_kind, "spec_mismatch")
        self.assertEqual(parse_stage_markers("noise\nSTAGE_COMPLETE {}\n"), [])

    def test_stage_invocation_planner_expands_default_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": "1"},
                data_dir=Path(td),
            )

        self.assertEqual([stage.stage_id for stage in invocations[:4]], ["research", "analysis", "clarify", "writer"])
        self.assertIn(["analysis", "clarify"], snapshot["topological_layers"])
        prompt = render_orchestrator_brief(base_prompt="# Base\n", stage_invocations=invocations[:1], run_id=RUN_ID, phase_id="1")
        self.assertIn('Task(subagent_type="general-purpose"', prompt)
        self.assertIn("STAGE_COMPLETE", prompt)

    def test_stage_session_lifecycle_round_trips_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": "1"},
                data_dir=data,
            )
            init_stage_sessions(RUN_ID, "1", invocations[:1], snapshot, data_dir=data)
            claim_stage(RUN_ID, "1", "research", data_dir=data)
            record_stage_adopted(
                RUN_ID,
                "1",
                "research",
                commit_sha="a" * 40,
                result_path=data / "result.json",
                transcript_path=data / "stdout.txt",
                data_dir=data,
            )
            state = load_stage_sessions(RUN_ID, "1", data_dir=data)

        self.assertEqual(state["stages"][0]["status"], "adopted")
        self.assertEqual(state["stages"][0]["commit_sha"], "a" * 40)

    def test_stage_terminal_record_can_fill_missing_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": "1"},
                data_dir=data,
            )
            init_stage_sessions(RUN_ID, "1", invocations[:1], snapshot, data_dir=data)
            record_stage_adopted(
                RUN_ID,
                "1",
                "research",
                commit_sha=None,
                result_path=data / "early-result.json",
                transcript_path=None,
                data_dir=data,
            )
            recorded = record_stage_adopted(
                RUN_ID,
                "1",
                "research",
                commit_sha="b" * 40,
                result_path=data / "early-result.json",
                transcript_path=data / "stdout.txt",
                data_dir=data,
            )

        self.assertTrue(recorded["recorded"])
        self.assertEqual(recorded["reason"], "already_terminal_updated")
        self.assertEqual(recorded["stage"]["commit_sha"], "b" * 40)

    def test_controller_ignores_unknown_stage_marker_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": "1"},
                data_dir=data,
            )
            init_stage_sessions(RUN_ID, "1", invocations[:1], snapshot, data_dir=data)
            marker = parse_stage_marker_line('STAGE_COMPLETE {"stage_id":"missing","result_path":"/tmp/result.json"}')
            self.assertIsNotNone(marker)

            processed = _process_stage_markers(
                RUN_ID,
                "1",
                markers=[marker],
                stage_invocations=invocations[:1],
                prepared={},
                workspace_metadata={},
                launch_dir=data,
                data_dir=data,
            )

        self.assertFalse(processed["completed"])
        self.assertEqual(processed["markers"][0]["controller_status"], "unknown_stage_marker")


if __name__ == "__main__":
    unittest.main()
