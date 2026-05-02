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

def test_parent_death_with_complete_artifacts_is_adopted_on_next_pump() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        started = start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        attempt = int(started['phase']['attempt'])
        result_path = data / 'runs' / run_id / 'phase_results' / '1' / f'attempt-{attempt}.result.json'
        handoff_path = data / 'runs' / run_id / 'phase_handoffs' / '1' / f'attempt-{attempt}.handoff.json'
        _write_claude_artifacts(data, run_id, '1', attempt, result_path, handoff_path, status='complete')
        result = pump_phases(run_id, launcher='fake-test', max_phases=None, data_dir=data)
        assert result['status'] == 'complete'
        assert phase_status(run_id, data_dir=data, repo_root=repo)['status'] == 'complete'

def test_parent_death_with_blocked_artifacts_is_adopted_and_stops() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        started = start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        attempt = int(started['phase']['attempt'])
        result_path = data / 'runs' / run_id / 'phase_results' / '1' / f'attempt-{attempt}.result.json'
        handoff_path = data / 'runs' / run_id / 'phase_handoffs' / '1' / f'attempt-{attempt}.handoff.json'
        _write_claude_artifacts(data, run_id, '1', attempt, result_path, handoff_path, status='blocked')
        result = pump_phases(run_id, launcher='fake-test', max_phases=None, data_dir=data)
        assert result['status'] == 'blocked'
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        assert status['phases'][0]['status'] == 'blocked'
        assert status['phases'][1]['status'] == 'pending'

def test_recovery_still_parses_streaming_stdout_txt() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        frame = {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': 'ok', 'usage': {}}
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=json.dumps(frame) + '\n')), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            proc = phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        parsed = parse_claude_print_json((launch_dir / 'stdout.txt').read_text(encoding='utf-8'))
        legacy_parsed = parse_claude_print_json(json.dumps(frame, sort_keys=True) + '\n')
    assert parsed['session_id'] == 's1'
    assert parsed == legacy_parsed
    assert parse_claude_print_json(proc.stdout) == legacy_parsed

def test_legacy_json_fallback_on_unsupported_flag() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        calls = []

        def fake_popen(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                return _StreamProc(stderr="invalid choice: 'stream-json'\n", returncode=2)
            return _LegacyProc(stdout='{}', stderr='', returncode=0)
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', side_effect=fake_popen), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            proc = phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        command = json.loads(command_path.read_text(encoding='utf-8'))
    assert proc.stdout == '{}'
    assert '--output-format' in calls[1]
    assert calls[1][calls[1].index('--output-format') + 1] == 'json'
    assert command['stream_metadata']['fallback'] == 'legacy_json_retry'
