from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.failure_taxonomy import failure_kind_details
from swarm_do.pipeline.orchestrator_stream import StageMarker, parse_stage_marker_line
from swarm_do.pipeline.stage_adoption_journal import adoption_journal_path, checkpoint_adoption_journal, start_adoption_journal
from swarm_do.pipeline.stage_controller import StageMarkerProcessor, resume_stage_adoption_journals, retry_failed_units
from swarm_do.pipeline.stage_invocation import StageInvocation, plan_stage_invocations
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions, record_stage_adopted, stage_session_path


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

    def test_retryable_failed_marker_requests_fresh_reviewer_and_caps_at_three(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            marker = StageMarker(kind="failed", stage_id=invocation.stage_id, failure_kind="RETRYABLE_TIMEOUT", notes="timeout")

            first = processor.process_marker(marker)
            second = processor.process_marker(marker)
            third = processor.process_marker(marker)
            fourth = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)
            events = (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8")

        self.assertEqual(first.outcome, "retry_requested")
        self.assertEqual(second.outcome, "retry_requested")
        self.assertEqual(third.outcome, "retry_requested")
        self.assertEqual(fourth.outcome, "blocked_recorded")
        self.assertEqual(fourth.reason, "retry_cycle_cap_exceeded")
        self.assertEqual(state["stages"][0]["status"], "blocked")
        self.assertEqual(state["stages"][0]["retry_cycle_count"], 4)
        self.assertTrue(state["stages"][0]["fresh_reviewer_required"] is False)
        self.assertEqual(summary["retry_requested_count"], 4)
        self.assertEqual(summary["terminal_state"], "failed")
        self.assertIn("stage_human_gate", events)

    def test_marker_missing_result_becomes_stage_result_missing_at_finish(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            marker = _complete_marker(invocation)

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "pending")
        self.assertEqual(summary["stage_result_missing_count"], 1)
        self.assertEqual(summary["terminal_state"], "failed")
        self.assertEqual(state["stages"][0]["status"], "failed")
        self.assertEqual(state["stages"][0]["failure_kind"], "stage_result_missing")

    def test_mixed_adopted_and_blocked_stages_report_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data = tmp / "data"
            data.mkdir()
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": PHASE_ID, "phase_attempt": 1},
                data_dir=data,
            )
            first = invocations[0]
            second = dataclasses.replace(
                first,
                stage_id="second-stage",
                expected_result_path=first.expected_result_path.with_name("second-stage.result.json"),
            )
            init_stage_sessions(RUN_ID, PHASE_ID, [first, second], snapshot, data_dir=data)
            processor = StageMarkerProcessor(
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=1,
                stage_invocations=[first, second],
                prepared={},
                workspace_metadata={},
                launch_dir=tmp / "launch",
                data_dir=data,
            )
            _write_stage_result(first.expected_result_path, first)

            adopted = processor.process_marker(_complete_marker(first))
            blocked = processor.process_marker(
                StageMarker(
                    kind="failed",
                    stage_id=second.stage_id,
                    failure_kind="NON_RETRYABLE_INVALID_INPUT",
                    notes="bad input",
                )
            )
            summary = processor.finish()

        self.assertEqual(adopted.outcome, "adopted")
        self.assertEqual(blocked.outcome, "blocked_recorded")
        self.assertEqual(summary["terminal_state"], "PARTIAL_SUCCESS")
        self.assertEqual(summary["phase_result_status"], "partial_success")
        self.assertEqual(summary["failed_stage_ids"], ["second-stage"])

    def test_three_parallel_markers_adopt_once_each(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data = tmp / "data"
            data.mkdir()
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": RUN_ID, "phase_id": PHASE_ID, "phase_attempt": 1},
                data_dir=data,
            )
            base = invocations[0]
            stages = [
                dataclasses.replace(
                    base,
                    stage_id=f"writer-{idx}",
                    expected_result_path=base.expected_result_path.with_name(f"writer-{idx}.result.json"),
                )
                for idx in range(1, 4)
            ]
            init_stage_sessions(RUN_ID, PHASE_ID, stages, snapshot, data_dir=data)
            processor = StageMarkerProcessor(
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=1,
                stage_invocations=stages,
                prepared={},
                workspace_metadata={},
                launch_dir=tmp / "launch",
                data_dir=data,
            )
            for stage in stages:
                _write_stage_result(stage.expected_result_path, stage)

            decisions = [processor.process_marker(_complete_marker(stage)) for stage in stages]
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual([decision.outcome for decision in decisions], ["adopted", "adopted", "adopted"])
        self.assertTrue(summary["completed"])
        self.assertEqual([stage["status"] for stage in state["stages"]], ["adopted", "adopted", "adopted"])

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

    def test_in_root_wrong_result_path_is_human_gate_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            wrong_path = invocation.expected_result_path.with_name("other.result.json")
            _write_stage_result(wrong_path, invocation)
            marker = StageMarker(kind="complete", stage_id=invocation.stage_id, result_path=str(wrong_path))

            decision = processor.process_marker(marker)
            summary = processor.finish()
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "rejected_metadata_tampered")
        self.assertEqual(summary["rejected_metadata_tampered"], 1)
        self.assertEqual(state["stages"][0]["status"], "blocked")
        self.assertEqual(state["stages"][0]["failure_kind"], "stage_metadata_tampered")
        self.assertEqual(failure_kind_details("stage_metadata_tampered")["failure_retry_class"], "human_gate")

    def test_result_metadata_claims_cannot_change_unit_worktree_or_bead(self) -> None:
        for key, value in (
            ("work_unit_id", "unit-spoof"),
            ("worktree_path", "/tmp/spoofed-worktree"),
            ("bead_id", "bd-spoof"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                data, invocation, processor = _processor(Path(td))
                _write_stage_result(invocation.expected_result_path, invocation, extra={key: value})
                marker = _complete_marker(invocation)

                decision = processor.process_marker(marker)
                state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

            self.assertEqual(decision.outcome, "rejected_metadata_tampered")
            self.assertEqual(state["stages"][0]["failure_kind"], "stage_metadata_tampered")

    def test_result_human_gate_failure_kind_is_metadata_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            _write_stage_result(
                invocation.expected_result_path,
                invocation,
                extra={"status": "failed", "failure_kind": "NON_RETRYABLE_INVALID_INPUT"},
            )
            marker = _complete_marker(invocation)

            decision = processor.process_marker(marker)
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(decision.outcome, "rejected_metadata_tampered")
        self.assertEqual(state["stages"][0]["failure_kind"], "stage_metadata_tampered")

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

    def test_adoption_journal_resume_repairs_missing_event_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, invocation, _unused_processor = _processor(tmp)
            marker = _complete_marker(invocation)
            start_adoption_journal(
                data_dir=data,
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=1,
                marker=marker,
                invocation=invocation,
            )
            record_stage_adopted(
                RUN_ID,
                PHASE_ID,
                invocation.stage_id,
                commit_sha="a" * 40,
                result_path=invocation.expected_result_path,
                transcript_path=None,
                data_dir=data,
            )
            checkpoint_adoption_journal(
                data_dir=data,
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=1,
                stage_id=invocation.stage_id,
                checkpoint="stage_recorded",
                payload={"commit_sha": "a" * 40},
            )

            first = resume_stage_adoption_journals(
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=None,
                prepared={},
                workspace_metadata={},
                launch_dir=tmp / "launch",
                data_dir=data,
            )
            second = resume_stage_adoption_journals(
                run_id=RUN_ID,
                phase_id=PHASE_ID,
                phase_attempt=1,
                prepared={},
                workspace_metadata={},
                launch_dir=tmp / "launch",
                data_dir=data,
            )
            events = [
                json.loads(line)
                for line in (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            journal = json.loads(
                adoption_journal_path(
                    data,
                    RUN_ID,
                    PHASE_ID,
                    1,
                    invocation.stage_id,
                    result_path=str(invocation.expected_result_path),
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(first["resumed_adoption_journals"][0]["outcome"], "duplicate")
        self.assertEqual(second["resumed_adoption_journals"], [])
        self.assertEqual(sum(1 for event in events if event["event_type"] == "stage_adopted"), 1)
        self.assertTrue(journal["completed"])

    def test_corrupt_adoption_journal_requires_repair_instead_of_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, invocation, _unused_processor = _processor(tmp)
            journal_path = adoption_journal_path(
                data,
                RUN_ID,
                PHASE_ID,
                1,
                invocation.stage_id,
                result_path=str(invocation.expected_result_path),
            )
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            journal_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(ValueError):
                resume_stage_adoption_journals(
                    run_id=RUN_ID,
                    phase_id=PHASE_ID,
                    phase_attempt=None,
                    prepared={},
                    workspace_metadata={},
                    launch_dir=tmp / "launch",
                    data_dir=data,
                )

    def test_retry_failed_units_caps_failed_stage_at_three_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, _processor_unused = _processor(Path(td))
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)
            state["stages"][0].update(
                {
                    "status": "failed",
                    "failure_kind": "RETRYABLE_TIMEOUT",
                    "retry_cycle_count": 3,
                    "attempt": 3,
                }
            )
            _write_stage_state(data, state)

            summary = retry_failed_units(run_id=RUN_ID, phase_id=PHASE_ID, data_dir=data)
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)

        self.assertEqual(summary["blocked_stage_ids"], [invocation.stage_id])
        self.assertEqual(summary["retry_stage_ids"], [])
        self.assertEqual(state["stages"][0]["status"], "blocked")
        self.assertEqual(state["stages"][0]["failure_kind"], "retry_cycle_cap_exceeded")

    def test_retry_failed_units_treats_zero_retry_cycle_as_zero_not_attempt_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, _processor_unused = _processor(Path(td))
            state = load_stage_sessions(RUN_ID, PHASE_ID, data_dir=data)
            state["stages"][0].update(
                {
                    "status": "pending",
                    "failure_kind": "RETRYABLE_TIMEOUT",
                    "fresh_reviewer_required": True,
                    "retry_cycle_count": 0,
                    "attempt": 99,
                }
            )
            _write_stage_state(data, state)

            summary = retry_failed_units(run_id=RUN_ID, phase_id=PHASE_ID, data_dir=data)

        self.assertEqual(summary["blocked_stage_ids"], [])
        self.assertEqual(summary["retry_stage_ids"], [invocation.stage_id])

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

    def test_processor_rejects_non_owner_thread_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _data, _invocation, processor = _processor(Path(td))
            failures: list[BaseException] = []

            def call_from_reader_thread() -> None:
                try:
                    processor.process_text("")
                except BaseException as exc:
                    failures.append(exc)

            thread = threading.Thread(target=call_from_reader_thread, name="claude-stdout-reader")
            thread.start()
            thread.join(timeout=5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], RuntimeError)


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


def _write_stage_result(path: Path, invocation: StageInvocation, *, extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "phase_id": PHASE_ID,
        "phase_attempt": 1,
        "stage_id": invocation.stage_id,
        "result_path": str(path),
        "work_unit_id": invocation.work_unit_id,
        "worktree_path": str(invocation.worktree_path) if invocation.worktree_path else None,
        "bead_id": invocation.bead_id,
        "allowed_files": list(invocation.allowed_files),
        "status": "complete",
        "summary": "done",
        "artifacts": [],
    }
    if extra:
        payload.update(extra)
    path.write_text(
        json.dumps(payload, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_stage_state(data: Path, state: dict) -> None:
    stage_session_path(RUN_ID, PHASE_ID, data_dir=data).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
