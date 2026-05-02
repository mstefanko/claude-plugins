from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.execution_workspace import is_sensitive_path
from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.phase_autopilot_policy import ResolvedPolicyUpdate
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_session_path, phase_status, start_phase
from swarm_do.pipeline.run_state import active_run_path, load_active_run, write_active_run
from swarm_do.pipeline.session_capabilities import parse_claude_print_json
from swarm_do.pipeline.stage_invocation import plan_stage_invocations
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions
from swarm_do.pipeline.tests.phase_pump_test_helpers import (
    _DelayedLineStream,
    _GatedStream,
    _LegacyProc,
    _StreamProc,
    _claude_runner,
    _eligible_claude_report,
    _write_claude_artifacts,
    _write_stage_result,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run

pytestmark = pytest.mark.unit

def test_claude_print_reports_ineligible_without_claiming_phase() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        report = {'launchers': [{'name': 'claude-print', 'eligible': False, 'hard_blockers': ['claude_print_fixtures_missing']}]}
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=report):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, data_dir=data)
        assert result['status'] == 'ineligible'
        assert phase_status(run_id, data_dir=data, repo_root=repo)['phases'][0]['status'] == 'pending'

def test_claude_print_injected_runner_completes_two_phases() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
        runner = _claude_runner(data, run_id, ['complete', 'complete'])
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=None, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'complete'
        assert len(result['completed_phases']) == 2
        assert phase_status(run_id, data_dir=data, repo_root=repo)['status'] == 'complete'

def test_claude_print_forwards_legacy_max_budget() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        base_runner = _claude_runner(data, run_id, ['complete'])
        seen: dict[str, list[str]] = {}

        def runner(argv, prompt_text):
            seen['argv'] = list(argv)
            return base_runner(argv, prompt_text)
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=runner, max_budget_usd=3.5, data_dir=data)
        assert result['status'] == 'complete'
        assert '--max-budget-usd' in seen['argv']
        assert seen['argv'][seen['argv'].index('--max-budget-usd') + 1] == '3.5'

def test_claude_print_uses_policy_attempt_budget_when_cli_budget_absent() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo, policy_update=ResolvedPolicyUpdate(forced_overrides={'max_phase_attempt_budget_usd': 1.25}, default_overrides={}))
        base_runner = _claude_runner(data, run_id, ['complete'])
        seen: dict[str, list[str]] = {}

        def runner(argv, prompt_text):
            seen['argv'] = list(argv)
            return base_runner(argv, prompt_text)
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, claude_runner=runner, data_dir=data)
        assert result['status'] == 'complete'
        assert '--max-budget-usd' in seen['argv']
        assert seen['argv'][seen['argv'].index('--max-budget-usd') + 1] == '1.25'

def test_claude_print_failed_phase_stops_downstream() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
        runner = _claude_runner(data, run_id, ['failed'])
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=None, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'failed_nonretryable'
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['phases'][0]['status'] == 'failed'
        assert status['phases'][1]['status'] == 'pending'

def test_claude_print_nonzero_without_valid_result_does_not_complete() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)

        def runner(argv, prompt_text):
            return subprocess.CompletedProcess(argv, 1, stdout='', stderr='failed before artifacts')
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'retry_waiting'
        state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding='utf-8'))
        assert state['phases'][0]['status'] == 'retry_waiting'
        assert state['phases'][0]['attempt_history'][0]['retry_after_seconds'] == 60
        assert state['phases'][0]['last_failure_kind'] == 'launcher_nonzero_no_artifacts'
        assert Path(state['phases'][0]['attempt_history'][0]['evidence_path']).is_file()
        assert state['phases'][0]['attempt_history']
        assert phase_status(run_id, data_dir=data, repo_root=repo)['status'] != 'complete'

def test_claude_cli_missing_records_launch_dir_and_manifest() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()), mock.patch('swarm_do.pipeline.phase_pump.shutil.which', return_value=None):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, data_dir=data)
        assert result['status'] == 'blocked'
        state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding='utf-8'))
        history = state['phases'][0]['attempt_history'][0]
        assert history['failure_kind'] == 'claude_cli_missing'
        assert Path(history['launch_dir']).is_dir()
        assert Path(history['evidence_path']).is_file()

def test_claude_print_nonzero_complete_artifacts_are_adopted() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        runner = _claude_runner(data, run_id, ['complete'], returncodes=[1])
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'complete'
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['status'] == 'complete'
        history = status['phases'][0]['attempt_history']
        assert history[0]['failure_kind'] == 'launcher_nonzero_with_artifacts'
        assert history[0]['adopted']
        assert Path(history[0]['evidence_path']).is_file()

def test_claude_print_replayed_fixture_records_artifacts() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        fixture = REPO_ROOT / 'py' / 'swarm_do' / 'pipeline' / 'tests' / 'fixtures' / 'claude_print' / 'success.json'
        runner = _claude_runner(data, run_id, ['complete'], stdout_template=fixture.read_text(encoding='utf-8'))
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'complete'
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['phases'][0]['status'] == 'complete'
        command = json.loads((data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1' / 'command.json').read_text(encoding='utf-8'))
        assert command['settings_path'] == str(data / 'runs' / run_id / 'coordinator-settings.json')
        assert command['writer_settings_path'] == str(data / 'runs' / run_id / 'writer-settings.json')
        assert (data / 'runs' / run_id / 'coordinator-settings.json').is_file()
        assert (data / 'runs' / run_id / 'writer-settings.json').is_file()
        expected_mode = 'safe-symlink' if is_sensitive_path(repo) else 'real'
        assert command['execution_workspace_mode'] == expected_mode
        if expected_mode == 'real':
            assert command['launcher_cwd'] == str(repo.resolve(strict=False))
        else:
            assert command['real_repo_root'] == str(repo.resolve(strict=False))
            assert command['launcher_cwd'] == command['launcher_repo_root']
        assert Path(status['phases'][0]['evidence_path']).is_file()

def test_claude_print_rewrites_sensitive_repo_paths_and_records_safe_cwd() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fake_home = root / 'home'
        repo = fake_home / '.claude' / 'plugins' / 'swarm-do'
        repo, data, run_id = make_prepared_run(root, phase_count=1, repo_path=repo, commit_plan=True, ignore_run_artifacts=True)
        base_runner = _claude_runner(data, run_id, ['complete'])
        seen: dict[str, str] = {}

        def runner(argv, prompt_text):
            seen['prompt'] = prompt_text
            return base_runner(argv, prompt_text)
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()), mock.patch('swarm_do.pipeline.execution_workspace.Path.home', return_value=fake_home):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=runner, data_dir=data)
        assert result['status'] == 'complete'
        command = json.loads((data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1' / 'command.json').read_text(encoding='utf-8'))
        assert command['execution_workspace_mode'] == 'safe-worktree'
        assert command['real_repo_root'] == str(repo.resolve(strict=False))
        assert command['source_project_root'] == str(repo.resolve(strict=False))
        assert command['project_subdir'] == ''
        assert command['launcher_cwd'].startswith(str((data / 'worktrees' / run_id / 'repo').resolve(strict=False)))
        assert command['launcher_cwd'] == command['safe_project_root']
        assert Path(command['run_worktree_manifest_path']).is_file()
        assert command['prompt_rewrite_count'] >= 0
        prompt = seen['prompt']
        assert str(repo) not in prompt
        assert str(repo.resolve(strict=False)) not in prompt
        assert command['launcher_repo_root'] in prompt

def test_claude_print_safe_cwd_can_be_disabled() -> None:
    with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {'SWARM_CLAUDE_SAFE_CWD': '0'}):
        root = Path(td)
        fake_home = root / 'home'
        repo = fake_home / '.claude' / 'plugins' / 'swarm-do'
        repo, data, run_id = make_prepared_run(root, phase_count=1, repo_path=repo)
        with mock.patch('swarm_do.pipeline.phase_pump.doctor_report', return_value=_eligible_claude_report()), mock.patch('swarm_do.pipeline.execution_workspace.Path.home', return_value=fake_home):
            result = pump_phases(run_id, launcher='claude-print', max_phases=1, init_if_missing=True, claude_runner=_claude_runner(data, run_id, ['complete']), data_dir=data)
        assert result['status'] == 'complete'
        command = json.loads((data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1' / 'command.json').read_text(encoding='utf-8'))
        assert command['execution_workspace_mode'] == 'disabled'
        assert not command['safe_cwd_enabled']
        assert command['launcher_cwd'] == str(repo.resolve(strict=False))
