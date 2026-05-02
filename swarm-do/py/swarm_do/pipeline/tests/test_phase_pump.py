from __future__ import annotations

import json
import io
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.execution_workspace import is_sensitive_path
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_autopilot_policy import ResolvedPolicyUpdate
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_session_path, phase_status, start_phase
from swarm_do.pipeline.run_state import active_run_path, load_active_run, write_active_run
from swarm_do.pipeline.session_capabilities import parse_claude_print_json
from swarm_do.pipeline.stage_invocation import plan_stage_invocations
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions
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
            evidence = Path(status["phases"][0]["evidence_path"])
            self.assertTrue(evidence.is_file())

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
            command = json.loads((data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(command["launcher"], "manual")
            self.assertEqual(command["prompt_delivery"], "manual")

    def test_pump_stops_on_blocking_doctor_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            doctor = {
                "run_id": run_id,
                "status": "findings",
                "finding_count": 1,
                "findings": [
                    {
                        "id": "prepared_dispatch_sidecars",
                        "severity": "error",
                        "recommended_command": f"bin/swarm prepare refresh-base {run_id}",
                    }
                ],
                "recommended_command": f"bin/swarm prepare refresh-base {run_id}",
            }

            with mock.patch("swarm_do.pipeline.phase_pump.run_phase_doctor", return_value=doctor):
                result = pump_phases(run_id, launcher="fake-test", max_phases=1, data_dir=data)

            self.assertEqual(result["status"], "preflight_failed")
            self.assertEqual(result["doctor"], doctor)
            status = phase_status(run_id, data_dir=data, repo_root=repo)
            self.assertEqual(status["phases"][0]["status"], "pending")

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

    def test_claude_print_forwards_legacy_max_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            base_runner = _claude_runner(data, run_id, ["complete"])
            seen: dict[str, list[str]] = {}

            def runner(argv, prompt_text):
                seen["argv"] = list(argv)
                return base_runner(argv, prompt_text)

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=runner,
                    max_budget_usd=3.5,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            self.assertIn("--max-budget-usd", seen["argv"])
            self.assertEqual(seen["argv"][seen["argv"].index("--max-budget-usd") + 1], "3.5")

    def test_claude_print_uses_policy_attempt_budget_when_cli_budget_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(
                run_id,
                data_dir=data,
                repo_root=repo,
                policy_update=ResolvedPolicyUpdate(
                    forced_overrides={"max_phase_attempt_budget_usd": 1.25},
                    default_overrides={},
                ),
            )
            base_runner = _claude_runner(data, run_id, ["complete"])
            seen: dict[str, list[str]] = {}

            def runner(argv, prompt_text):
                seen["argv"] = list(argv)
                return base_runner(argv, prompt_text)

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            self.assertIn("--max-budget-usd", seen["argv"])
            self.assertEqual(seen["argv"][seen["argv"].index("--max-budget-usd") + 1], "1.25")

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

            def runner(argv, prompt_text):
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

            self.assertEqual(result["status"], "retry_waiting")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(state["phases"][0]["status"], "retry_waiting")
            self.assertEqual(state["phases"][0]["attempt_history"][0]["retry_after_seconds"], 60)
            self.assertEqual(state["phases"][0]["last_failure_kind"], "launcher_nonzero_no_artifacts")
            self.assertTrue(Path(state["phases"][0]["attempt_history"][0]["evidence_path"]).is_file())
            self.assertTrue(state["phases"][0]["attempt_history"])
            self.assertNotEqual(phase_status(run_id, data_dir=data, repo_root=repo)["status"], "complete")

    def test_claude_cli_missing_records_launch_dir_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()), mock.patch(
                "swarm_do.pipeline.phase_pump.shutil.which",
                return_value=None,
            ):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "blocked")
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            history = state["phases"][0]["attempt_history"][0]
            self.assertEqual(history["failure_kind"], "claude_cli_missing")
            self.assertTrue(Path(history["launch_dir"]).is_dir())
            self.assertTrue(Path(history["evidence_path"]).is_file())

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
            self.assertTrue(Path(history[0]["evidence_path"]).is_file())

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
            command = json.loads((data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(command["settings_path"], str(data / "runs" / run_id / "coordinator-settings.json"))
            self.assertEqual(command["writer_settings_path"], str(data / "runs" / run_id / "writer-settings.json"))
            self.assertTrue((data / "runs" / run_id / "coordinator-settings.json").is_file())
            self.assertTrue((data / "runs" / run_id / "writer-settings.json").is_file())
            expected_mode = "safe-symlink" if is_sensitive_path(repo) else "real"
            self.assertEqual(command["execution_workspace_mode"], expected_mode)
            if expected_mode == "real":
                self.assertEqual(command["launcher_cwd"], str(repo.resolve(strict=False)))
            else:
                self.assertEqual(command["real_repo_root"], str(repo.resolve(strict=False)))
                self.assertEqual(command["launcher_cwd"], command["launcher_repo_root"])
            self.assertTrue(Path(status["phases"][0]["evidence_path"]).is_file())

    def test_claude_print_rewrites_sensitive_repo_paths_and_records_safe_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_home = root / "home"
            repo = fake_home / ".claude" / "plugins" / "swarm-do"
            repo, data, run_id = make_prepared_run(
                root,
                phase_count=1,
                repo_path=repo,
                commit_plan=True,
                ignore_run_artifacts=True,
            )
            base_runner = _claude_runner(data, run_id, ["complete"])
            seen: dict[str, str] = {}

            def runner(argv, prompt_text):
                seen["prompt"] = prompt_text
                return base_runner(argv, prompt_text)

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()), mock.patch(
                "swarm_do.pipeline.execution_workspace.Path.home",
                return_value=fake_home,
            ):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=runner,
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            command = json.loads((data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(command["execution_workspace_mode"], "safe-worktree")
            self.assertEqual(command["real_repo_root"], str(repo.resolve(strict=False)))
            self.assertEqual(command["source_project_root"], str(repo.resolve(strict=False)))
            self.assertEqual(command["project_subdir"], "")
            self.assertTrue(command["launcher_cwd"].startswith(str((data / "worktrees" / run_id / "repo").resolve(strict=False))))
            self.assertEqual(command["launcher_cwd"], command["safe_project_root"])
            self.assertTrue(Path(command["run_worktree_manifest_path"]).is_file())
            self.assertGreaterEqual(command["prompt_rewrite_count"], 0)
            prompt = seen["prompt"]
            self.assertNotIn(str(repo), prompt)
            self.assertNotIn(str(repo.resolve(strict=False)), prompt)
            self.assertIn(command["launcher_repo_root"], prompt)

    def test_claude_print_safe_cwd_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"SWARM_CLAUDE_SAFE_CWD": "0"}):
            root = Path(td)
            fake_home = root / "home"
            repo = fake_home / ".claude" / "plugins" / "swarm-do"
            repo, data, run_id = make_prepared_run(root, phase_count=1, repo_path=repo)

            with mock.patch("swarm_do.pipeline.phase_pump.doctor_report", return_value=_eligible_claude_report()), mock.patch(
                "swarm_do.pipeline.execution_workspace.Path.home",
                return_value=fake_home,
            ):
                result = pump_phases(
                    run_id,
                    launcher="claude-print",
                    max_phases=1,
                    init_if_missing=True,
                    claude_runner=_claude_runner(data, run_id, ["complete"]),
                    data_dir=data,
                )

            self.assertEqual(result["status"], "complete")
            command = json.loads((data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(command["execution_workspace_mode"], "disabled")
            self.assertFalse(command["safe_cwd_enabled"])
            self.assertEqual(command["launcher_cwd"], str(repo.resolve(strict=False)))

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
                stdin = None

                def communicate(self, input=None, timeout=None):
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

    def test_real_claude_launcher_receives_cwd(self) -> None:
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
                stdin = None

                def communicate(self, input=None, timeout=None):
                    return "{}", ""

            def fake_popen(*args, **kwargs):
                popen_kwargs.update(kwargs)
                return FakeProc()

            cwd = data / "launcher-workspaces" / "repo"
            cwd.mkdir(parents=True)
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
                    cwd=cwd,
                )

            self.assertEqual(popen_kwargs["cwd"], str(cwd))
            self.assertEqual(popen_kwargs["env"]["PWD"], str(cwd))
            self.assertNotIn(".claude", popen_kwargs["env"].get("OLDPWD", ""))

    def test_real_claude_launcher_writes_stdin_once_and_refreshes_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text("{}", encoding="utf-8")

            class FakeStdin:
                def __init__(self) -> None:
                    self.writes = []
                    self.closed = False

                def write(self, value):
                    self.writes.append(value)

                def flush(self):
                    pass

                def close(self):
                    self.closed = True

            class FakeProc:
                pid = 12345

                def __init__(self) -> None:
                    self.returncode = None
                    self.stdin_handle = FakeStdin()
                    self.stdin = self.stdin_handle
                    self.wait_calls = 0

                def wait(self, timeout=None):
                    self.wait_calls += 1
                    if self.wait_calls == 1:
                        raise subprocess.TimeoutExpired(["claude"], timeout)
                    self.returncode = 0
                    return 0

                def communicate(self):
                    if self.stdin is not None:
                        raise AssertionError("stdin should be detached before communicate")
                    return "{}", ""

            proc = FakeProc()

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", return_value=proc), mock.patch(
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
                    prompt_text="hello",
                )

            self.assertEqual(proc.stdin_handle.writes, ["hello"])
            self.assertTrue(proc.stdin_handle.closed)
            self.assertIsNone(proc.stdin)
            events = (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("phase_session_refreshed", events)

    def test_streaming_live_stage_marker_is_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding="utf-8")
            invocations, snapshot = plan_stage_invocations(
                {"name": "default", "pipeline": "default"},
                {"run_id": run_id, "phase_id": "1", "phase_attempt": 1},
                data_dir=data,
            )
            invocation = invocations[0]
            init_stage_sessions(run_id, "1", [invocation], snapshot, data_dir=data)
            _write_stage_result(data, run_id, "1", 1, invocation.expected_result_path, invocation.stage_id)
            marker_text = "STAGE_COMPLETE " + json.dumps({"stage_id": invocation.stage_id, "result_path": str(invocation.expected_result_path)})
            stdout = "\n".join(
                [
                    json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": marker_text + "\n"}]}}),
                    json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "s1", "result": "{}"}),
                ]
            ) + "\n"

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", return_value=_StreamProc(stdout=stdout)), mock.patch(
                "swarm_do.pipeline.phase_pump.os.getpgid",
                return_value=12345,
            ):
                proc = phase_pump._run_real_claude(
                    ["claude", "-p", "--verbose", "--output-format", "stream-json"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata=phase_pump._stream_command_metadata(),
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                    phase_attempt=1,
                    stage_invocations=[invocation],
                    prepared={},
                    workspace_metadata={"phase_attempt": 1},
                )
            state = load_stage_sessions(run_id, "1", data_dir=data)

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(state["stages"][0]["status"], "adopted")
        self.assertTrue(proc.stage_controller["completed"])

    def test_recovery_still_parses_streaming_stdout_txt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding="utf-8")
            frame = {"type": "result", "subtype": "success", "is_error": False, "session_id": "s1", "result": "ok", "usage": {}}

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", return_value=_StreamProc(stdout=json.dumps(frame) + "\n")), mock.patch(
                "swarm_do.pipeline.phase_pump.os.getpgid",
                return_value=12345,
            ):
                proc = phase_pump._run_real_claude(
                    ["claude", "-p", "--verbose", "--output-format", "stream-json"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata=phase_pump._stream_command_metadata(),
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                )

            parsed = parse_claude_print_json((launch_dir / "stdout.txt").read_text(encoding="utf-8"))

        self.assertEqual(parsed["session_id"], "s1")
        self.assertEqual(parse_claude_print_json(proc.stdout)["result"], "ok")

    def test_no_result_frame_writes_raw_stdout_to_stdout_txt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding="utf-8")
            raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}) + "\n"

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", return_value=_StreamProc(stdout=raw)), mock.patch(
                "swarm_do.pipeline.phase_pump.os.getpgid",
                return_value=12345,
            ):
                phase_pump._run_real_claude(
                    ["claude", "-p", "--verbose", "--output-format", "stream-json"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata=phase_pump._stream_command_metadata(),
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                )
            command = json.loads(command_path.read_text(encoding="utf-8"))

            self.assertEqual((launch_dir / "stdout.txt").read_text(encoding="utf-8"), raw)
            self.assertEqual(command["stream_metadata"]["fallback"], "raw")
            self.assertFalse(command["stream_final_result_seen"])

    def test_legacy_json_fallback_on_unsupported_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding="utf-8")
            calls = []

            def fake_popen(argv, **kwargs):
                calls.append(list(argv))
                if len(calls) == 1:
                    return _StreamProc(stderr="invalid choice: 'stream-json'\n", returncode=2)
                return _LegacyProc(stdout="{}", stderr="", returncode=0)

            with mock.patch("swarm_do.pipeline.phase_pump.subprocess.Popen", side_effect=fake_popen), mock.patch(
                "swarm_do.pipeline.phase_pump.os.getpgid",
                return_value=12345,
            ):
                proc = phase_pump._run_real_claude(
                    ["claude", "-p", "--verbose", "--output-format", "stream-json"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata=phase_pump._stream_command_metadata(),
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                )
            command = json.loads(command_path.read_text(encoding="utf-8"))

        self.assertEqual(proc.stdout, "{}")
        self.assertIn("--output-format", calls[1])
        self.assertEqual(calls[1][calls[1].index("--output-format") + 1], "json")
        self.assertEqual(command["stream_metadata"]["fallback"], "legacy_json_retry")

    def test_stream_jsonl_size_cap_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch_dir.mkdir(parents=True)
            command_path = launch_dir / "command.json"
            command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding="utf-8")
            stdout = json.dumps({"type": "system", "payload": "x" * 40}) + "\n"

            with mock.patch("swarm_do.pipeline.phase_pump._STDOUT_STREAM_CAP_BYTES", 10), mock.patch(
                "swarm_do.pipeline.phase_pump.subprocess.Popen",
                return_value=_StreamProc(stdout=stdout),
            ), mock.patch("swarm_do.pipeline.phase_pump.os.getpgid", return_value=12345):
                phase_pump._run_real_claude(
                    ["claude", "-p", "--verbose", "--output-format", "stream-json"],
                    run_id=run_id,
                    phase_id="1",
                    lease_owner="owner-1",
                    data_dir=data,
                    launch_dir=launch_dir,
                    command_path=command_path,
                    metadata=phase_pump._stream_command_metadata(),
                    prompt_sha="a" * 64,
                    result_path=data / "result.json",
                    handoff_path=data / "handoff.json",
                )
            command = json.loads(command_path.read_text(encoding="utf-8"))

            self.assertTrue((launch_dir / "stdout.stream.jsonl.1").is_file())
            self.assertIn("_truncated", (launch_dir / "stdout.stream.jsonl.1").read_text(encoding="utf-8"))
            self.assertIsNotNone(command["stream_metadata"]["truncated_at_bytes"])

    def test_retry_sleep_threshold_comes_from_recovery_policy(self) -> None:
        recovery = {
            "status": "retry_waiting",
            "actions": [
                {
                    "action": "retry_waiting",
                    "retry_sleep_seconds": 90,
                    "retry_sleep_threshold_seconds": 120,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td, mock.patch("swarm_do.pipeline.phase_pump._sleep_interruptibly") as sleep:
            result = phase_pump._handle_recovery_decision(
                recovery,
                completed=[],
                data_dir=Path(td),
                run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                stop_on_checkpoint=False,
            )

        self.assertEqual(result, {"continue": True})
        sleep.assert_called_once_with(90)

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


class _StreamProc:
    pid = 12345
    stdin = None

    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = None
        self._final_returncode = returncode
        self.killed = False

    def wait(self, timeout=None):
        self.returncode = self._final_returncode
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class _LegacyProc:
    pid = 12346
    stdin = None

    def __init__(self, *, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def communicate(self):
        return self.stdout_text, self.stderr_text


def _write_stage_result(data: Path, run_id: str, phase_id: str, attempt: int, result_path: Path, stage_id: str) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "phase_id": phase_id,
                "phase_attempt": attempt,
                "stage_id": stage_id,
                "status": "complete",
                "summary": "stage complete",
                "artifacts": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _claude_runner(
    data: Path,
    run_id: str,
    statuses: list[str],
    stdout_template: str | None = None,
    returncodes: list[int] | None = None,
):
    calls = {"count": 0}

    def runner(argv, prompt_text):
        status = statuses[min(calls["count"], len(statuses) - 1)]
        calls["count"] += 1
        prompt = prompt_text
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
