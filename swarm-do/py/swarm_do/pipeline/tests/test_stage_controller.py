from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.orchestrator_stream import StageMarker, parse_stage_marker_line
from swarm_do.pipeline.stage_controller import StageMarkerProcessor
from swarm_do.pipeline.stage_invocation import StageInvocation, plan_stage_invocations
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions, record_stage_adopted


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PHASE_ID = "1"


class StageMarkerProcessorTests(unittest.TestCase):
    def test_complete_marker_adopts_one_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            _write_stage_result(invocation.expected_result_path, invocation)
            marker = _complete_marker(invocation)

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "adopted")
        self.assertTrue(summary["completed"])
        self.assertEqual(state["stages"][0]["status"], "adopted")

    def test_duplicate_complete_marker_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            _write_stage_result(invocation.expected_result_path, invocation)
            marker = _complete_marker(invocation)

            from swarm_do.pipeline import stage_controller

            with mock.patch(
                "swarm_do.pipeline.stage_controller.record_stage_adopted",
                wraps=stage_controller.record_stage_adopted,
            ) as adopted:
                first = processor.process_marker(marker)
                second = processor.process_marker(marker)
                summary = processor.finish()

        self.assertEqual(first.outcome, "adopted")
        self.assertEqual(second.outcome, "duplicate")
        self.assertEqual(adopted.call_count, 1)
        self.assertEqual(summary["duplicate_marker_count"], 1)

    def test_failed_marker_records_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            marker = StageMarker(kind="failed", stage_id=invocation.stage_id, failure_kind="blocked", notes="nope")

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "failed_recorded")
        self.assertFalse(summary["completed"])
        self.assertEqual(state["stages"][0]["status"], "failed")
        self.assertEqual(state["stages"][0]["failure_kind"], "blocked")

    def test_marker_with_wrong_result_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            marker = StageMarker(kind="complete", stage_id=invocation.stage_id, result_path=str(data / "escape.json"))

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "rejected_invalid_path")
        self.assertEqual(summary["rejected_invalid_path"], 1)
        self.assertEqual(state["stages"][0]["status"], "failed")

    def test_marker_before_result_file_adopted_at_finish(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            marker = _complete_marker(invocation)

            decision = processor.process_marker(marker)
            _write_stage_result(invocation.expected_result_path, invocation)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "pending")
        self.assertTrue(summary["completed"])
        self.assertEqual(summary["pending_marker_count"], 0)
        self.assertEqual(state["stages"][0]["status"], "adopted")

    def test_unknown_stage_marker_recorded_without_crash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, _invocation, processor = _processor(Path(td))
            marker = StageMarker(kind="complete", stage_id="missing", result_path=str(data / "missing.json"))

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "rejected_unknown_stage")
        self.assertEqual(summary["markers"][0]["controller_status"], "unknown_stage_marker")
        self.assertEqual(state["stages"][0]["status"], "pending")

    def test_amended_duplicate_fills_missing_commit_sha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            record_stage_adopted(
                RUN_ID,
                PHASE_ID,
                invocation.stage_id,
                commit_sha=None,
                result_path=invocation.expected_result_path,
                transcript_path=None,
                data_dir=data,
            )
            payload = {
                "stage_id": invocation.stage_id,
                "result_path": str(invocation.expected_result_path),
                "commit_sha": "b" * 40,
            }
            marker = parse_stage_marker_line("STAGE_COMPLETE " + json.dumps(payload, sort_keys=True))
            self.assertIsNotNone(marker)

            with mock.patch.object(StageMarkerProcessor, "_append_stage_event") as append_event:
                decision = processor.process_marker(marker)
                summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "amended")
        self.assertEqual(summary["amended_count"], 1)
        self.assertEqual(state["stages"][0]["commit_sha"], "b" * 40)
        append_event.assert_not_called()


def _processor(tmp: Path) -> tuple[Path, StageInvocation, StageMarkerProcessor]:
    data = tmp / "data"
    data.mkdir()
    invocations, snapshot = plan_stage_invocations(
        {"name": "default", "pipeline": "default"},
        {"run_id": RUN_ID, "phase_id": PHASE_ID, "phase_attempt": 1},
        data_dir=data,
    )
    invocation = invocations[0]
    init_stage_sessions(RUN_ID, PHASE_ID, [invocation], snapshot, data_dir=data)
    processor = StageMarkerProcessor(
        run_id=RUN_ID,
        phase_id=PHASE_ID,
        phase_attempt=1,
        stage_invocations=[invocation],
        prepared={},
        workspace_metadata={},
        launch_dir=tmp / "launch",
        data_dir=data,
    )
    return data, invocation, processor


def _complete_marker(invocation: StageInvocation) -> StageMarker:
    marker = parse_stage_marker_line(
        "STAGE_COMPLETE "
        + json.dumps({"stage_id": invocation.stage_id, "result_path": str(invocation.expected_result_path)}, sort_keys=True)
    )
    if marker is None:
        raise AssertionError("marker did not parse")
    return marker


def _write_stage_result(path: Path, invocation: StageInvocation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "phase_id": PHASE_ID,
                "phase_attempt": 1,
                "stage_id": invocation.stage_id,
                "status": "complete",
                "summary": "done",
                "artifacts": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
