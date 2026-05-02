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

def test_fake_test_completes_three_phase_fixture() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        result = pump_phases(run_id, launcher='fake-test', max_phases=None, data_dir=data)
        assert result['status'] == 'complete'
        assert len(result['completed_phases']) == 3
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['status'] == 'complete'
        evidence = Path(status['phases'][0]['evidence_path'])
        assert evidence.is_file()

def test_failed_fake_phase_stops_with_resume_point() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        result = pump_phases(run_id, launcher='fake-test', max_phases=None, fake_statuses=['failed'], data_dir=data)
        assert result['status'] == 'failed'
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['phases'][0]['status'] == 'failed'
        assert status['phases'][1]['status'] == 'pending'

def test_manual_launcher_returns_prompt_and_followup_command() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        result = pump_phases(run_id, launcher='manual', max_phases=1, data_dir=data)
        assert result['status'] == 'manual_waiting'
        assert Path(result['manual']['prompt_path']).is_file()
        assert 'phases complete' in result['manual']['follow_up_command']
        command = json.loads((data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1' / 'command.json').read_text(encoding='utf-8'))
        assert command['launcher'] == 'manual'
        assert command['prompt_delivery'] == 'manual'

def test_pump_stops_on_blocking_doctor_preflight() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        doctor = {'run_id': run_id, 'status': 'findings', 'finding_count': 1, 'findings': [{'id': 'prepared_dispatch_sidecars', 'severity': 'error', 'recommended_command': f'bin/swarm prepare refresh-base {run_id}'}], 'recommended_command': f'bin/swarm prepare refresh-base {run_id}'}
        with mock.patch('swarm_do.pipeline.phase_pump.run_phase_doctor', return_value=doctor):
            result = pump_phases(run_id, launcher='fake-test', max_phases=1, data_dir=data)
        assert result['status'] == 'preflight_failed'
        assert result['doctor'] == doctor
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['phases'][0]['status'] == 'pending'

def test_retry_sleep_threshold_comes_from_recovery_policy() -> None:
    recovery = {'status': 'retry_waiting', 'actions': [{'action': 'retry_waiting', 'retry_sleep_seconds': 90, 'retry_sleep_threshold_seconds': 120}]}
    with tempfile.TemporaryDirectory() as td, mock.patch('swarm_do.pipeline.phase_pump._sleep_interruptibly') as sleep:
        result = phase_pump._handle_recovery_decision(recovery, completed=[], data_dir=Path(td), run_id='01ARZ3NDEKTSV4RRFFQ69G5FAV', stop_on_checkpoint=False)
    assert result == {'continue': True}
    sleep.assert_called_once_with(90)

def test_phase_checkpoint_does_not_reuse_unrelated_active_run() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        write_active_run(active_run_path(data), {'run_id': '01BRZ3NDEKTSV4RRFFQ69G5FAV', 'bd_epic_id': 'bd-stale', 'phase_id': 'stale', 'work_units': [{'id': 'stale-unit', 'status': 'pending'}], 'status': 'prepared'})
        result = pump_phases(run_id, launcher='fake-test', max_phases=1, data_dir=data)
        assert result['status'] == 'max_phases'
        active = load_active_run(active_run_path(data))
        assert active is not None
        assert active['run_id'] == run_id
        assert active['bd_epic_id'] is None
        assert active['work_units'] == []


def test_doctor_report_always_contains_claude_print_launcher() -> None:
    from swarm_do.pipeline.session_capabilities import doctor_report

    report = doctor_report()
    names = [launcher.get("name") for launcher in report.get("launchers", [])]
    assert "claude-print" in names, f"doctor_report launchers missing claude-print: {names}"
    claude = next(launcher for launcher in report["launchers"] if launcher["name"] == "claude-print")
    assert "eligible" in claude
