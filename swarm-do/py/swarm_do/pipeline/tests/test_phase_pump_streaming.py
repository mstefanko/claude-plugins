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

def test_real_claude_launcher_starts_new_session_and_records_child_metadata() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text('{}', encoding='utf-8')
        popen_kwargs = {}

        class FakeProc:
            pid = 12345
            returncode = 0
            stdin = None
            stdout = io.StringIO('{}\n')
            stderr = io.StringIO('')

            def wait(self, timeout=None):
                return self.returncode

        def fake_popen(*args, **kwargs):
            popen_kwargs.update(kwargs)
            return FakeProc()
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', side_effect=fake_popen), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            phase_pump._run_real_claude(['claude'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata={}, prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        assert popen_kwargs['start_new_session']
        state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding='utf-8'))
        assert state['phases'][0]['child_pid'] == 12345
        assert state['phases'][0]['process_group_id'] == 12345

def test_real_claude_launcher_receives_cwd() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text('{}', encoding='utf-8')
        popen_kwargs = {}

        class FakeProc:
            pid = 12345
            returncode = 0
            stdin = None
            stdout = io.StringIO('{}\n')
            stderr = io.StringIO('')

            def wait(self, timeout=None):
                return self.returncode

        def fake_popen(*args, **kwargs):
            popen_kwargs.update(kwargs)
            return FakeProc()
        cwd = data / 'launcher-workspaces' / 'repo'
        cwd.mkdir(parents=True)
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', side_effect=fake_popen), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            phase_pump._run_real_claude(['claude'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata={}, prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', cwd=cwd)
        assert popen_kwargs['cwd'] == str(cwd)
        assert popen_kwargs['env']['PWD'] == str(cwd)
        assert '.claude' not in popen_kwargs['env'].get('OLDPWD', '')

def test_real_claude_launcher_writes_stdin_once_and_refreshes_lease() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text('{}', encoding='utf-8')

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
                self.stdout = _DelayedLineStream('{}\n', delay_seconds=1.2)
                self.stderr = io.StringIO('')

            def wait(self, timeout=None):
                self.returncode = 0
                return 0
        proc = FakeProc()
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=proc), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345), mock.patch('swarm_do.pipeline.phase_pump.load_phase_sessions', return_value={'lease_policy': {'refresh_interval_seconds': 1, 'running_ttl_seconds': 5}}):
            phase_pump._run_real_claude(['claude'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata={}, prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', prompt_text='hello')
        assert proc.stdin_handle.writes == ['hello']
        assert proc.stdin_handle.closed
        assert proc.stdin is None
        events = (data / 'telemetry' / 'run_events.jsonl').read_text(encoding='utf-8')
        assert 'phase_session_refreshed' in events

def test_streaming_live_adoption_before_exit() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        invocations, snapshot = plan_stage_invocations({'name': 'default', 'pipeline': 'default'}, {'run_id': run_id, 'phase_id': '1', 'phase_attempt': 1}, data_dir=data)
        invocation = invocations[0]
        init_stage_sessions(run_id, '1', [invocation], snapshot, data_dir=data)
        _write_stage_result(data, run_id, '1', 1, invocation.expected_result_path, invocation.stage_id)
        marker_text = 'STAGE_COMPLETE ' + json.dumps({'stage_id': invocation.stage_id, 'result_path': str(invocation.expected_result_path)})
        finish = threading.Event()
        proc = _StreamProc(stdout=_GatedStream([json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker_text + '\n'}]}}) + '\n', finish, json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': '{}'}) + '\n']))
        result_holder: dict[str, subprocess.CompletedProcess[str] | BaseException] = {}

        def run_launcher() -> None:
            try:
                result_holder['result'] = phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', phase_attempt=1, stage_invocations=[invocation], prepared={}, workspace_metadata={'phase_attempt': 1})
            except BaseException as exc:
                result_holder['result'] = exc
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=proc), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            thread = threading.Thread(target=run_launcher)
            thread.start()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                state = load_stage_sessions(run_id, '1', data_dir=data)
                if state['stages'][0]['status'] == 'adopted':
                    break
                time.sleep(0.05)
            state = load_stage_sessions(run_id, '1', data_dir=data)
            assert state['stages'][0]['status'] == 'adopted'
            assert proc.poll() is None
            finish.set()
            thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert isinstance(result_holder['result'], subprocess.CompletedProcess)

def test_streaming_lease_refresh_called_on_cadence() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        frame = json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': 'ok'}) + '\n'
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=_DelayedLineStream(frame, 1.2))), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345), mock.patch('swarm_do.pipeline.phase_pump.load_phase_sessions', return_value={'lease_policy': {'refresh_interval_seconds': 1, 'running_ttl_seconds': 5}}), mock.patch('swarm_do.pipeline.phase_pump.refresh_phase') as refresh:
            phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
    refresh.assert_called()

def test_streaming_timeout_writes_partial_stream_jsonl() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        kill_event = threading.Event()
        proc = _StreamProc(stdout=_GatedStream([json.dumps({'type': 'system', 'subtype': 'init'}) + '\n', kill_event]), kill_event=kill_event)
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=proc), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345), mock.patch('swarm_do.pipeline.phase_pump.load_phase_sessions', return_value={'lease_policy': {'refresh_interval_seconds': 1, 'running_ttl_seconds': 3}}):
            with pytest.raises(subprocess.TimeoutExpired):
                phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        assert (launch_dir / 'stdout.stream.jsonl').stat().st_size > 0

def test_concurrency_invariant_no_ledger_writes_from_reader_thread() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        invocations, snapshot = plan_stage_invocations({'name': 'default', 'pipeline': 'default'}, {'run_id': run_id, 'phase_id': '1', 'phase_attempt': 1}, data_dir=data)
        invocation = invocations[0]
        init_stage_sessions(run_id, '1', [invocation], snapshot, data_dir=data)
        _write_stage_result(data, run_id, '1', 1, invocation.expected_result_path, invocation.stage_id)
        marker_text = 'STAGE_COMPLETE ' + json.dumps({'stage_id': invocation.stage_id, 'result_path': str(invocation.expected_result_path)})
        stdout = '\n'.join([json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker_text + '\n'}]}}), json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': '{}'})]) + '\n'
        from swarm_do.pipeline import stage_controller
        original = stage_controller.record_stage_adopted

        def checked_record(*args, **kwargs):
            assert threading.current_thread().name not in {'claude-stdout-reader', 'claude-stderr-reader'}
            return original(*args, **kwargs)
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=stdout)), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345), mock.patch('swarm_do.pipeline.stage_controller.record_stage_adopted', side_effect=checked_record):
            phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', phase_attempt=1, stage_invocations=[invocation], prepared={}, workspace_metadata={'phase_attempt': 1})

def test_streaming_live_stage_marker_is_adopted() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        invocations, snapshot = plan_stage_invocations({'name': 'default', 'pipeline': 'default'}, {'run_id': run_id, 'phase_id': '1', 'phase_attempt': 1}, data_dir=data)
        invocation = invocations[0]
        init_stage_sessions(run_id, '1', [invocation], snapshot, data_dir=data)
        _write_stage_result(data, run_id, '1', 1, invocation.expected_result_path, invocation.stage_id)
        marker_text = 'STAGE_COMPLETE ' + json.dumps({'stage_id': invocation.stage_id, 'result_path': str(invocation.expected_result_path)})
        stdout = '\n'.join([json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker_text + '\n'}]}}), json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': '{}'})]) + '\n'
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=stdout)), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            proc = phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', phase_attempt=1, stage_invocations=[invocation], prepared={}, workspace_metadata={'phase_attempt': 1})
        state = load_stage_sessions(run_id, '1', data_dir=data)
    assert proc.returncode == 0
    assert state['stages'][0]['status'] == 'adopted'
    assert proc.stage_controller['completed']

def test_systemic_parse_error_still_processes_deferred_stage_markers() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        invocations, snapshot = plan_stage_invocations({'name': 'default', 'pipeline': 'default'}, {'run_id': run_id, 'phase_id': '1', 'phase_attempt': 1}, data_dir=data)
        invocation = invocations[0]
        init_stage_sessions(run_id, '1', [invocation], snapshot, data_dir=data)
        _write_stage_result(data, run_id, '1', 1, invocation.expected_result_path, invocation.stage_id)
        marker_text = 'STAGE_COMPLETE ' + json.dumps({'stage_id': invocation.stage_id, 'result_path': str(invocation.expected_result_path)})
        malformed = ['{not-json\n' for _ in range(51)]
        marker_frame = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker_text + '\n'}]}}) + '\n'
        result_frame = json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': '{}'}) + '\n'
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=''.join([*malformed, marker_frame, result_frame]))), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json', phase_attempt=1, stage_invocations=[invocation], prepared={}, workspace_metadata={'phase_attempt': 1})
        state = load_stage_sessions(run_id, '1', data_dir=data)
        command = json.loads(command_path.read_text(encoding='utf-8'))
    assert state['stages'][0]['status'] == 'adopted'
    assert command['stream_metadata']['systemic_parse_error']

def test_no_result_frame_writes_raw_stdout_to_stdout_txt() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        raw = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'hello'}]}}) + '\n'
        with mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=raw)), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        command = json.loads(command_path.read_text(encoding='utf-8'))
        assert (launch_dir / 'stdout.txt').read_text(encoding='utf-8') == raw
        assert command['stream_metadata']['fallback'] == 'raw'
        assert not command['stream_final_result_seen']

def test_stream_jsonl_size_cap_truncation() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner='owner-1')
        start_phase(run_id, '1', launcher='claude-print', lease_owner='owner-1', data_dir=data)
        launch_dir = data / 'runs' / run_id / 'phase_launches' / '1' / 'attempt-1'
        launch_dir.mkdir(parents=True)
        command_path = launch_dir / 'command.json'
        command_path.write_text(json.dumps(phase_pump._stream_command_metadata()), encoding='utf-8')
        stdout = json.dumps({'type': 'system', 'payload': 'x' * 40}) + '\n'
        with mock.patch('swarm_do.pipeline.phase_pump._STDOUT_STREAM_CAP_BYTES', 10), mock.patch('swarm_do.pipeline.phase_pump.subprocess.Popen', return_value=_StreamProc(stdout=stdout)), mock.patch('swarm_do.pipeline.phase_pump.os.getpgid', return_value=12345):
            phase_pump._run_real_claude(['claude', '-p', '--verbose', '--output-format', 'stream-json'], run_id=run_id, phase_id='1', lease_owner='owner-1', data_dir=data, launch_dir=launch_dir, command_path=command_path, metadata=phase_pump._stream_command_metadata(), prompt_sha='a' * 64, result_path=data / 'result.json', handoff_path=data / 'handoff.json')
        command = json.loads(command_path.read_text(encoding='utf-8'))
        assert (launch_dir / 'stdout.stream.jsonl.1').is_file()
        assert '_truncated' in (launch_dir / 'stdout.stream.jsonl.1').read_text(encoding='utf-8')
        assert command['stream_metadata']['truncated_at_bytes'] is not None
