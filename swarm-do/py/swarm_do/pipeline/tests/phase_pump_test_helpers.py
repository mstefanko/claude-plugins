from __future__ import annotations

import io
import json
import re
import subprocess
import threading
import time
from pathlib import Path

from swarm_do.pipeline.phase_sessions import phase_session_path

def _eligible_claude_report() -> dict:
    return {'launchers': [{'name': 'claude-print', 'eligible': True, 'hard_blockers': []}]}

class _DelayedLineStream:

    def __init__(self, line: str, delay_seconds: float) -> None:
        self._line = line
        self._delay_seconds = delay_seconds
        self._sent = False

    def readline(self) -> str:
        if self._sent:
            return ''
        time.sleep(self._delay_seconds)
        self._sent = True
        return self._line

class _GatedStream:

    def __init__(self, items) -> None:
        self._items = list(items)
        self._index = 0

    def readline(self) -> str:
        while self._index < len(self._items):
            item = self._items[self._index]
            self._index += 1
            if isinstance(item, threading.Event):
                item.wait()
                continue
            return item
        return ''

class _StreamProc:
    pid = 12345
    stdin = None

    def __init__(self, *, stdout='', stderr='', returncode: int=0, kill_event: threading.Event | None=None) -> None:
        self.stdout = io.StringIO(stdout) if isinstance(stdout, str) else stdout
        self.stderr = io.StringIO(stderr) if isinstance(stderr, str) else stderr
        self.returncode = None
        self._final_returncode = returncode
        self._kill_event = kill_event
        self.killed = False

    def wait(self, timeout=None):
        self.returncode = self._final_returncode
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        if self._kill_event is not None:
            self._kill_event.set()

class _LegacyProc:
    pid = 12346
    stdin = None

    def __init__(self, *, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = None
        self._final_returncode = returncode

    def wait(self, timeout=None):
        self.returncode = self._final_returncode
        return self.returncode

def _write_stage_result(data: Path, run_id: str, phase_id: str, attempt: int, result_path: Path, stage_id: str) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({'schema_version': 1, 'run_id': run_id, 'phase_id': phase_id, 'phase_attempt': attempt, 'stage_id': stage_id, 'status': 'complete', 'summary': 'stage complete', 'artifacts': []}, sort_keys=True) + '\n', encoding='utf-8')

def _claude_runner(data: Path, run_id: str, statuses: list[str], stdout_template: str | None=None, returncodes: list[int] | None=None):
    calls = {'count': 0}

    def runner(argv, prompt_text):
        status = statuses[min(calls['count'], len(statuses) - 1)]
        calls['count'] += 1
        prompt = prompt_text
        result_path = Path(re.search('result JSON exactly to: (.+)', prompt).group(1))
        handoff_path = Path(re.search('handoff JSON exactly to: (.+)', prompt).group(1))
        phase_id = result_path.parent.name
        attempt = int(result_path.stem.split('-')[1].split('.')[0])
        _write_claude_artifacts(data, run_id, phase_id, attempt, result_path, handoff_path, status=status)
        if stdout_template is None:
            stdout = json.dumps({'type': 'result', 'result': json.dumps({'status': status, 'result_path': str(result_path), 'handoff_path': str(handoff_path), 'session_name': f'swarmdaddy-{run_id}-{phase_id}'})})
        else:
            stdout = stdout_template.replace('<RUN_DIR>', str(data / 'runs' / run_id))
        if returncodes is None:
            returncode = 0 if status == 'complete' else 1
        else:
            returncode = returncodes[min(calls['count'] - 1, len(returncodes) - 1)]
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr='')
    return runner

def _write_claude_artifacts(data: Path, run_id: str, phase_id: str, attempt: int, result_path: Path, handoff_path: Path, *, status: str) -> None:
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding='utf-8'))
    phase = next((item for item in state['phases'] if item['phase_id'] == phase_id))
    prepared = json.loads((data / 'runs' / run_id / 'prepared_plan.v1.json').read_text(encoding='utf-8'))
    phase_sha = next((item['content_sha'] for item in prepared['phase_map'] if item['phase_id'] == phase_id))
    now = '2026-04-29T00:00:00Z'
    handoff = {'schema_version': 1, 'run_id': run_id, 'phase_id': phase_id, 'phase_attempt': attempt, 'status': status, 'written_at': now, 'summary': f'claude fixture {status}', 'decisions': [], 'changed_files': [], 'completed_work_units': [], 'open_items': [], 'blockers': ['blocked'] if status == 'blocked' else [], 'do_not_retry': [], 'validation_summary': [], 'artifacts': [], 'next_phase_context': []}
    result = {'schema_version': 1, 'run_id': run_id, 'phase_id': phase_id, 'phase_attempt': attempt, 'status': status, 'launcher': 'claude-print', 'session_name': phase['session_name'], 'prepared_plan_sha': state['prepared_plan_sha'], 'phase_content_sha': phase_sha, 'started_at': phase['started_at'], 'completed_at': now, 'handoff_path': str(handoff_path), 'summary': f'claude fixture {status}', 'completed_work_units': [], 'failed_work_units': [], 'blocked_reason': 'blocked' if status == 'blocked' else None, 'needs_input': ['input needed'] if status == 'needs_input' else [], 'validation': [], 'artifacts': [], 'error': {'message': 'failed'} if status == 'failed' else None}
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
