from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.phase_sessions import (
    BLOCKED_OPERATOR_CANCELLED,
    PhaseSessionError,
    archive_phase_session_evidence,
    cancel_phase_session_run,
    claim_next_phase,
    cleanup_phase_generated_artifacts,
    configure_retry_policy,
    init_phase_sessions,
    load_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    phase_status,
    reap_expired_phases,
    record_phase_result,
    reset_phase_session,
    start_phase,
)
from swarm_do.pipeline.phase_autopilot_policy import ResolvedPolicyUpdate
from swarm_do.pipeline.phase_doctor import run_phase_doctor
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseSessionTests(unittest.TestCase):
    def test_status_reports_not_initialized_for_accepted_prepared_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["status"], "not_initialized")
            self.assertIn("phases init", status["recommended_command"])

    def test_init_copies_exact_phase_ids_and_sequential_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            result = init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            phases = result["state"]["phases"]
            self.assertEqual([phase["phase_id"] for phase in phases], ["1", "2", "3"])
            self.assertEqual(phases[0]["depends_on_phase_ids"], [])
            self.assertEqual(phases[1]["depends_on_phase_ids"], ["1"])
            self.assertEqual(phases[2]["depends_on_phase_ids"], ["2"])

    def test_init_uses_explicit_prepared_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
            prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
            prepared["phase_map"][2]["depends_on_phase_ids"] = ["1"]
            prepared["phase_map"][2]["dependency_reason"] = "manual test dependency"
            prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            self.assertEqual(result["state"]["phases"][2]["depends_on_phase_ids"], ["1"])

    def test_claim_start_complete_then_claims_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            self.assertTrue(claim["claimed"])
            self.assertEqual(claim["phase"]["phase_id"], "1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)
            self.assertEqual(recorded["phase"]["status"], "complete")
            self.assertTrue(Path(recorded["phase"]["evidence_path"]).is_file())

            claim2 = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-2")
            self.assertTrue(claim2["claimed"])
            self.assertEqual(claim2["phase"]["phase_id"], "2")

    def test_completion_requires_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            phase_handoff_path(run_id, "1", int(started["phase"]["attempt"]), data_dir=data).unlink()
            with self.assertRaises(PhaseSessionError):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_result_handoff_path_must_stay_inside_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            original_handoff = phase_handoff_path(run_id, "1", int(started["phase"]["attempt"]), data_dir=data)
            outside_handoff = Path(td) / "outside.handoff.json"
            outside_handoff.write_text(original_handoff.read_text(encoding="utf-8"), encoding="utf-8")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["handoff_path"] = str(outside_handoff)
            result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(PhaseSessionError, "escapes run directory"):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_reap_marks_expired_lease_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["phases"][0]["lease_expires_at"] = "2026-01-01T00:00:00Z"
            path.write_text(json.dumps(state), encoding="utf-8")

            result = reap_expired_phases(run_id, data_dir=data)
            self.assertEqual(result["reaped"][0]["status"], "stale")
            self.assertEqual(load_phase_sessions(run_id, data_dir=data)["phases"][0]["status"], "stale")

    def test_failed_phase_status_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="failed")
            record_phase_result(run_id, "1", json_file=result_path, expected_status="failed", data_dir=data)

            status = phase_status(run_id, data_dir=data, repo_root=repo)

            self.assertEqual(status["status"], "failed")
            self.assertIn("phases status", status["recommended_command"])

    def test_partial_success_is_terminal_but_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="partial_success")

            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="partial_success", data_dir=data)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            claim = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-2")

        self.assertEqual(recorded["phase"]["status"], "partial_success")
        self.assertEqual(status["status"], "partial_success")
        self.assertFalse(claim["claimed"])
        self.assertEqual(claim["reason"], "no_claimable_phase")

    def test_hard_reset_clears_dispatch_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="failed")
            record_phase_result(run_id, "1", json_file=result_path, expected_status="failed", data_dir=data)

            reset = reset_phase_session(run_id, "1", hard=True, data_dir=data)

            phase = reset["phase"]
            self.assertEqual(phase["status"], "pending")
            self.assertEqual(phase["attempt"], 0)
            self.assertIsNone(phase["result_path"])
            self.assertIsNone(phase["handoff_path"])
            self.assertIsNone(phase["last_failure_kind"])
            self.assertEqual(phase["attempt_history"], [])
            loaded = load_phase_sessions(run_id, data_dir=data)
            self.assertEqual(loaded["phases"][0]["status"], "pending")

    def test_doctor_isolates_probe_errors(self) -> None:
        def broken_probe(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict]:
            raise RuntimeError("boom")

        def healthy_probe(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict]:
            return [{"id": "healthy", "severity": "warning", "detail": "still ran"}]

        with tempfile.TemporaryDirectory() as td:
            report = run_phase_doctor(
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                data_dir=Path(td),
                probes=[broken_probe, healthy_probe],
            )

            ids = [item["id"] for item in report["findings"]]
            self.assertIn("probe_error", ids)
            self.assertIn("healthy", ids)

    def test_load_validates_hand_edited_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["phases"][0]["phase_id"] = "../bad"
            path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(PhaseSessionError):
                load_phase_sessions(run_id, data_dir=data)

    def test_old_state_without_retry_fields_loads_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            state.pop("retry_policy")
            for key in (
                "attempt_history",
                "next_retry_at",
                "last_failure_kind",
                "child_pid",
                "process_group_id",
            ):
                state["phases"][0].pop(key, None)
            path.write_text(json.dumps(state), encoding="utf-8")

            loaded = load_phase_sessions(run_id, data_dir=data)

            self.assertEqual(loaded["retry_policy"]["max_session_attempts"], 2)
            self.assertEqual(loaded["retry_policy"]["short_retry_backoff_seconds"], 60)
            self.assertEqual(loaded["retry_policy"]["autopilot_profile"], "standard")
            self.assertIsNone(loaded["retry_policy"]["max_failed_attempt_cost_usd"])
            self.assertEqual(loaded["phases"][0]["attempt_history"], [])

    def test_configure_retry_policy_persists_validated_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            configured = configure_retry_policy(
                run_id,
                ResolvedPolicyUpdate(
                    forced_overrides={"autopilot_profile": "dogfood", "max_failed_run_cost_usd": 3.25},
                    default_overrides={"max_failed_attempt_cost_usd": 1.0},
                ),
                data_dir=data,
            )

            policy = configured["state"]["retry_policy"]
            self.assertEqual(policy["autopilot_profile"], "dogfood")
            self.assertEqual(policy["max_failed_run_cost_usd"], 3.25)
            self.assertEqual(policy["max_failed_attempt_cost_usd"], 1.0)
            self.assertEqual(policy["max_phase_attempt_budget_usd"], 1.5)

    def test_configure_retry_policy_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            with self.assertRaises(PhaseSessionError):
                configure_retry_policy(
                    run_id,
                    ResolvedPolicyUpdate(
                        forced_overrides={"autopilot_profile": "turbo"},
                        default_overrides={},
                    ),
                    data_dir=data,
                )
            with self.assertRaises(PhaseSessionError):
                configure_retry_policy(
                    run_id,
                    ResolvedPolicyUpdate(
                        forced_overrides={"max_failed_attempt_cost_usd": -0.01},
                        default_overrides={},
                    ),
                    data_dir=data,
                )

    def test_init_refuses_to_resnapshot_when_phase_artifacts_exist_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            phase_session_path(run_id, data_dir=data).unlink()
            orphan = data / "runs" / run_id / "phase_results" / "1"
            orphan.mkdir(parents=True, exist_ok=True)
            (orphan / "attempt-1.result.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(PhaseSessionError, "phase execution artifacts already exist"):
                init_phase_sessions(run_id, data_dir=data, repo_root=repo)

    def test_record_result_rejects_prepared_plan_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["prepared_plan_sha"] = "b" * 64
            result_path.write_text(json.dumps(result), encoding="utf-8")

            with self.assertRaisesRegex(PhaseSessionError, "prepared_plan_sha"):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_record_result_rejects_phase_content_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["phase_content_sha"] = "c" * 64
            result_path.write_text(json.dumps(result), encoding="utf-8")

            with self.assertRaisesRegex(PhaseSessionError, "phase_content_sha"):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_phase_session_result_completed_work_units_must_be_prepared_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["completed_work_units"] = ["fixture:selftest.ok.json"]
            result_path.write_text(json.dumps(result), encoding="utf-8")

            with self.assertRaisesRegex(PhaseSessionError, "completed_work_units"):
                record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

    def test_cancel_marks_active_phase_operator_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            (repo / "docs" / "phase-1.md").parent.mkdir(exist_ok=True)
            (repo / "docs" / "phase-1.md").write_text("partial work\n", encoding="utf-8")

            payload = cancel_phase_session_run(run_id, data_dir=data, repo_root=repo, kill_child=False)

            self.assertTrue(payload["cancelled"])
            self.assertEqual(payload["phase_id"], "1")
            state = load_phase_sessions(run_id, data_dir=data)
            phase = state["phases"][0]
            self.assertEqual(phase["status"], "blocked")
            self.assertEqual(phase["blocked_reason"], BLOCKED_OPERATOR_CANCELLED)
            self.assertEqual(phase["retry_policy_decision"], BLOCKED_OPERATOR_CANCELLED)
            self.assertEqual(phase["attempt_history"][0]["retry_decision"], BLOCKED_OPERATOR_CANCELLED)
            self.assertEqual(payload["cleanup"]["untracked_artifacts_by_phase"], {"1": ["docs/phase-1.md"]})
            events = [json.loads(line) for line in (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8").splitlines()]
            blocked = [row for row in events if row["event_type"] == "phase_session_blocked"][-1]
            self.assertEqual(blocked["reason"], BLOCKED_OPERATOR_CANCELLED)

    def test_cancel_records_child_kill_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["phases"][0]["child_pid"] = 123
            state["phases"][0]["process_group_id"] = 456
            path.write_text(json.dumps(state), encoding="utf-8")

            with mock.patch("swarm_do.pipeline.phase_sessions._pid_alive", return_value=True), mock.patch(
                "swarm_do.pipeline.phase_sessions.os.killpg"
            ) as killpg:
                payload = cancel_phase_session_run(run_id, data_dir=data, repo_root=repo)

            killpg.assert_called_once()
            self.assertTrue(payload["child_process"]["kill_attempted"])
            self.assertEqual(payload["child_process"]["kill_target"], "pgid:456")

    def test_cleanup_refuses_generated_artifact_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            with self.assertRaisesRegex(PhaseSessionError, "outside generated artifact allowlist"):
                cleanup_phase_generated_artifacts(run_id, data_dir=data, phase_id="../escape", apply=True)

    def test_archive_copies_attempt_evidence_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

            archived = archive_phase_session_evidence(run_id, data_dir=data, label="test")

            manifest = Path(archived["archive_dir"]) / "phase_launches" / "1" / "attempt-1" / "evidence.json"
            self.assertTrue(manifest.is_file())


def _write_result(data: Path, run_id: str, phase: dict, *, status: str) -> Path:
    phase_id = phase["phase_id"]
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data)
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
    prepared_sha = state["prepared_plan_sha"]
    phase_sha = "0" * 64
    prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    for item in prepared["phase_map"]:
        if item["phase_id"] == phase_id:
            phase_sha = item["content_sha"]
            break
    now = "2026-04-29T00:00:00Z"
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": "done",
        "decisions": [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [],
        "do_not_retry": [],
        "validation_summary": [],
        "artifacts": [],
        "next_phase_context": [],
    }
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "launcher": "manual",
        "session_name": phase["session_name"],
        "prepared_plan_sha": prepared_sha,
        "phase_content_sha": phase_sha,
        "started_at": phase["started_at"],
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": "done",
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": None,
    }
    handoff_path.parent.mkdir(parents=True)
    result_path.parent.mkdir(parents=True)
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path


if __name__ == "__main__":
    unittest.main()
