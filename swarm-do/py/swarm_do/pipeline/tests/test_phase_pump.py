from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_session_path, phase_status, start_phase
from swarm_do.pipeline.run_state import active_run_path, load_active_run, write_active_run
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhasePumpTests(unittest.TestCase):
    def test_fake_test_completes_three_phase_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["completed_phases"]), 3)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["status"], "complete")

    def test_failed_fake_phase_stops_with_resume_point(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, fake_statuses=["failed"], data_dir=data)

            self.assertEqual(result["status"], "failed")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "failed")
            self.assertEqual(status["phases"][1]["status"], "pending")

    def test_manual_launcher_returns_prompt_and_followup_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="manual", max_phases=1, data_dir=data)

            self.assertEqual(result["status"], "manual_waiting")
            self.assertTrue(Path(result["manual"]["prompt_path"]).is_file())
            self.assertIn("phases complete", result["manual"]["follow_up_command"])

    def test_claude_print_reports_ineligible_without_claiming_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            report = {
                "launchers": [
                    {
                        "name": "claude-print",
                        "eligible": False,
                        "hard_blockers": ["claude_print_fixtures_missing"],
                    }
                ]
            }

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=report):
                result = pump_phases(run_id, launcher="claude-print", max_phases=1, data_dir=data)

            self.assertEqual(result["status"], "ineligible")
            self.assertEqual(phase_status(run_id, data_dir=data, repo_root=repo)["phases"][0]["status"], "pending")

    def test_claude_print_injected_runner_completes_two_phases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            runner = _claude_runner(data, run_id, ["complete", "complete"])

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=None,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["completed_phases"]), 2)
            self.assertEqual(phase_status(run_id, data_dir=data, repo_root=repo)["status"], "complete")

    def test_claude_print_failed_phase_stops_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            runner = _claude_runner(data, run_id, ["failed"])

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=None,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "failed_nonretryable")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "failed")
            self.assertEqual(status["phases"][1]["status"], "pending")

    def test_claude_print_nonzero_without_valid_result_does_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)

            def runner(argv):
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="failed before artifacts")

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "max_phases")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["status"], "pending")
            self.assertEqual(state["phases"][0]["last_failure_kind"], "launcher_nonzero_no_artifacts")
            self.assertTrue(state["phases"][0]["attempt_history"])
            self.assertNotEqual(phase_status(run_id, data_dir=data, repo_root=repo)["status"], "complete")

    def test_claude_print_nonzero_complete_artifacts_are_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            runner = _claude_runner(data, run_id, ["complete"], returncodes=[1])

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["status"], "complete")
            history = status["phases"][0]["attempt_history"]
            self.assertEqual(history[0]["failure_kind"], "launcher_nonzero_with_artifacts")
            self.assertTrue(history[0]["adopted"])

    def test_claude_print_replayed_fixture_records_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            fixture = REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print" / "success.json"
            runner = _claude_runner(data, run_id, ["complete"], stdout_template=fixture.read_text(encoding="utf-8"))

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "complete")

    def test_parent_death_with_complete_artifacts_is_adopted_on_next_pump(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            attempt = int(started["phase"]["attempt"])
            result_path = data / "runs" / run_id / "phase_results" / "1" / f"attempt-{attempt}.result.json"
            handoff_path = data / "runs" / run_id / "phase_handoffs" / "1" / f"attempt-{attempt}.handoff.json"
            _write_claude_artifacts(data, run_id, "1", attempt, result_path, handoff_path, status="complete")

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(phase_status(run_id, data_dir=data, repo_root=repo)["status"], "complete")

    def test_parent_death_with_blocked_artifacts_is_adopted_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            attempt = int(started["phase"]["attempt"])
            result_path = data / "runs" / run_id / "phase_results" / "1" / f"attempt-{attempt}.result.json"
            handoff_path = data / "runs" / run_id / "phase_handoffs" / "1" / f"attempt-{attempt}.handoff.json"
            _write_claude_artifacts(data, run_id, "1", attempt, result_path, handoff_path, status="blocked")

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)

            self.assertEqual(result["status"], "blocked")
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "blocked")
            self.assertEqual(status["phases"][1]["status"], "pending")

    def test_real_claude_launcher_starts_new_session_and_records_child_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text("{}", encoding="utf-8")
            popen_kwargs = {}

            class FakeProc:
                pid = 12345
                returncode = 0

                def communicate(self, timeout=None):
                    return "{}", ""

            def fake_popen(*args, **kwargs):
                popen_kwargs.update(kwargs)
                return FakeProc()

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", side_effect=fake_popen), mock.patch(
                "swarm_do.pipeline.phase_pump.os.getpgid",
                return_value=12345,
            ):
                phase_pump._run_real_claude(
                    ["claude"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata={},
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                )

            self.assertTrue(popen_kwargs["start_new_session"])
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["child_pid"], 12345)
            self.assertEqual(state["phases"][0]["process_group_id"], 12345)

    def test_phase_checkpoint_does_not_reuse_unrelated_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            write_active_run(
                active_run_path(data),
                {
                    "run_id": "01BRZ3NDEKTSV4RRFFQ69G5FAV",
                    "bd_epic_id": "bd-stale",
                    "phase_id": "stale",
                    "work_units": [{"id": "stale-unit", "status": "pending"}],
                    "status": "prepared",
                },
            )

            result = pump_phases(run_id, launcher="fake-test", max_phases=1, data_dir=data)

            self.assertEqual(result["status"], "max_phases")
            active = load_active_run(active_run_path(data))
            self.assertIsNotNone(active)
            self.assertEqual(active["run_id"], run_id)
            self.assertIsNone(active["bd_epic_id"])
            self.assertEqual(active["work_units"], [])


def _eligible_claude_report() -> dict:
    return {"launchers": [{"name": "claude-print", "eligible": True, "hard_blockers": []}]}


def _claude_runner(
    data: Path,
    run_id: str,
    statuses: list[str],
    stdout_template: str | None = None,
    returncodes: list[int] | None = None,
):
    calls = {"count": 0}

    def runner(argv):
        status = statuses[min(calls["count"], len(statuses) - 1)]
        calls["count"] += 1
        prompt = argv[-1]
        result_path = Path(re.search(r"result JSON exactly to: (.+)", prompt).group(1))
        handoff_path = Path(re.search(r"handoff JSON exactly to: (.+)", prompt).group(1))
        phase_id = result_path.parent.name
        attempt = int(result_path.stem.split("-")[1].split(".")[0])
        _write_claude_artifacts(data, run_id, phase_id, attempt, result_path, handoff_path, status=status)
        if stdout_template is None:
            stdout = json.dumps(
                {
                    "type": "result",
                    "result": json.dumps(
                        {
                            "status": status,
                            "result_path": str(result_path),
                            "handoff_path": str(handoff_path),
                            "session_name": f"swarmdaddy-{run_id}-{phase_id}",
                        }
                    ),
                }
            )
        else:
            stdout = stdout_template.replace("<RUN_DIR>", str(data / "runs" / run_id))
        if returncodes is None:
            returncode = 0 if status == "complete" else 1
        else:
            returncode = returncodes[min(calls["count"] - 1, len(returncodes) - 1)]
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return runner


def _write_claude_artifacts(
    data: Path,
    run_id: str,
    phase_id: str,
    attempt: int,
    result_path: Path,
    handoff_path: Path,
    *,
    status: str,
) -> None:
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
    phase = next(item for item in state["phases"] if item["phase_id"] == phase_id)
    prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    phase_sha = next(item["content_sha"] for item in prepared["phase_map"] if item["phase_id"] == phase_id)
    now = "2026-04-29T00:00:00Z"
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": f"claude fixture {status}",
        "decisions": [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": ["blocked"] if status == "blocked" else [],
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
        "launcher": "claude-print",
        "session_name": phase["session_name"],
        "prepared_plan_sha": state["prepared_plan_sha"],
        "phase_content_sha": phase_sha,
        "started_at": phase["started_at"],
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": f"claude fixture {status}",
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": "blocked" if status == "blocked" else None,
        "needs_input": ["input needed"] if status == "needs_input" else [],
        "validation": [],
        "artifacts": [],
        "error": {"message": "failed"} if status == "failed" else None,
    }
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
