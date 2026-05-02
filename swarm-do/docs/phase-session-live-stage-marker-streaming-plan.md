# Phase Session Live Stage Marker Streaming Plan

Status: implementation-ready proposal
Date: 2026-05-02

## Goal

Make controller-owned stage marker handling truly live during
`claude-print` phase execution.

The current implementation is durable but post-hoc: the foreground Claude
process prints `STAGE_COMPLETE` / `STAGE_FAILED` markers, the parent captures
stdout, and `phase_pump.py` processes those markers only after the Claude
process exits. That is acceptable as a first restoration step because stage
adoption is now controller-owned, validated, and recoverable. It is not the
end-state because a long phase still behaves like an opaque black box until the
outer process exits.

The target behavior:

- Adopt and event completed stages while the foreground Claude process is still
  running.
- Preserve exactly-once controller side effects across duplicate markers,
  process crashes, retries, and recovery.
- Keep existing `stdout.txt` / recovery / spend parsing compatible.
- Avoid extra Claude turns, a daemon requirement, or token-level stream
  parsing.
- Keep the existing captured-stdout marker scan as a fallback path.

## Current State

Relevant implementation facts:

- `py/swarm_do/pipeline/stage_invocation.py` renders the foreground
  orchestrator brief. It tells Claude to dispatch stages with `Task` and print
  exactly one marker after each stage writes its result JSON.
- `py/swarm_do/pipeline/orchestrator_stream.py` parses bounded marker lines:
  `STAGE_COMPLETE { ... }` and `STAGE_FAILED { ... }`.
- `py/swarm_do/pipeline/stage_sessions.py` owns the durable stage ledger in
  `stage_sessions.v1.json`.
- `py/swarm_do/pipeline/phase_pump.py` owns phase launching, lease refresh,
  stage marker processing, stage artifact commits, Beads lifecycle updates,
  and synthetic controller result creation.
- `_run_real_claude()` currently launches `claude -p --output-format json`,
  waits for the process to exit, writes `stdout.txt` / `stderr.txt`, and then
  calls `_process_stage_markers(parse_stage_markers(stdout))`.
- `schemas/telemetry/run_events.schema.json` already includes `stage_adopted`,
  so first-pass live adoption does not need a run-event enum change.
- The Claude Code CLI supports `--output-format stream-json`, and local
  `claude --help` reports it as a realtime print-mode output format.

## Decision

Move the real `claude-print` launcher to `--output-format stream-json` and
process complete assistant message text as it arrives. Do not process partial
token deltas in the first pass.

Keep two stdout artifacts per attempt:

- `stdout.stream.jsonl`: append-only raw stream frames, written while the child
  process runs.
- `stdout.txt`: the final Claude result object serialized as JSON after the
  process exits, preserving the existing recovery and spend telemetry path.

The implementation should preserve the current post-exit marker scan for:

- injected test runners that still return `subprocess.CompletedProcess`;
- old Claude versions or configurations without reliable `stream-json`;
- malformed stream output where the final result can still be parsed after
  process exit.

## Non-Goals

- No daemon or background service.
- No token-level or partial-message marker parsing in the first pass.
- No early child termination when all expected markers are seen.
- No extra Claude calls or live preflight spending.
- No primary reliance on `bin/swarm stages signal-*`; keep that as an escape
  hatch for unreliable marker delivery.
- No phase parallelism changes.

## Implementation Phases

### Phase 1 - Extract Idempotent Stage Marker Processing

Objective: make marker adoption safe before making it live.

Add `py/swarm_do/pipeline/stage_controller.py` with a small processor that owns
stage marker state transitions:

```python
class StageMarkerProcessor:
    def process_text(self, text: str) -> list[MarkerDecision]: ...
    def process_marker(self, marker: StageMarker) -> MarkerDecision: ...
    def finish(self) -> dict[str, Any]: ...
```

Inputs:

- `run_id`
- `phase_id`
- phase attempt
- `stage_invocations`
- prepared artifact
- workspace metadata
- launch directory
- data dir

Processor rules:

1. Accept only marker `stage_id` values present in the rendered
   `StageInvocation` list.
2. For `STAGE_COMPLETE`, require `result_path` to match the invocation's
   `expected_result_path`. If a looser rule is needed for compatibility, the
   result path must at least stay inside
   `data/runs/<run-id>/phases/<phase-id>/stage_results/`.
3. Validate the stage result JSON before adoption:
   - root is an object;
   - `run_id` matches;
   - `phase_id` matches;
   - `phase_attempt` matches;
   - `stage_id` matches;
   - status is `complete`.
4. If the marker arrives before the result file exists, store it in a pending
   list and retry during `finish()`.
5. If a stage is already terminal in `stage_sessions.v1.json`, treat duplicate
   markers as no-ops.
6. Only commit stage artifacts when `record_stage_adopted()` records a new
   terminal transition or fills missing terminal fields.
7. Only append `stage_adopted`, close Beads children, and update related
   controller side effects when adoption actually changed durable state.
8. For `STAGE_FAILED`, record the durable failed state and mark the stage Bead
   blocked, again idempotently.
9. Keep the aggregate return shape compatible with the existing
   `_process_stage_markers()` result:
   - `completed`
   - `markers`
   - `commits`
   - `commit_sha`
   - `worktree_diff`
   - `changed_files`

Refactor `phase_pump._process_stage_markers()` into a thin compatibility
wrapper around `StageMarkerProcessor`. Existing fake launcher and post-exit
tests should still pass through this wrapper.

Acceptance:

- Duplicate markers do not double-commit, double-close Beads, or double-append
  `stage_adopted`.
- Unknown stage markers still fail the controller summary without crashing.
- A marker seen before its result file exists can be adopted at `finish()`.

### Phase 2 - Add Claude Stream Parser

Objective: isolate Claude `stream-json` shape handling from launcher logic.

Add `py/swarm_do/pipeline/claude_stream.py`.

Responsibilities:

1. Parse one newline-delimited JSON frame at a time.
2. Extract assistant text from tolerant message shapes, especially:

   ```json
   {
     "type": "assistant",
     "message": {
       "content": [
         {"type": "text", "text": "..."}
       ]
     }
   }
   ```

3. Capture the final `{"type":"result", ...}` frame.
4. Track malformed frame count and the first parse error.
5. Ignore partial-message frames in the first pass unless they use the same
   complete text-block shape as normal assistant messages.
6. Return no marker decisions directly; it should only expose text chunks and
   final result frames to the caller.

Avoid binding the parser to every known Claude frame variant. It should be
liberal about unknown frames and strict only about JSON validity and text
extraction.

Acceptance:

- Fixture frames with assistant text produce marker lines.
- Non-text tool-use frames are ignored.
- Malformed lines increment parse-error count and do not abort the stream by
  default.
- Final result frame is preserved exactly enough to write `stdout.txt`.

### Phase 3 - Implement Streaming Real Claude Runner

Objective: replace the real subprocess IO path without disturbing the injected
test runner path.

Refactor `_run_real_claude()` in `phase_pump.py`.

Behavior:

1. Launch Claude with:

   ```text
   --output-format stream-json
   ```

   instead of `--output-format json` for the real subprocess path.

2. Continue to write the prompt once through stdin, close stdin, and refresh
   the phase lease on the existing interval.
3. Read stdout and stderr concurrently. Prefer two small reader threads feeding
   a queue over complex nonblocking text IO.
4. For each stdout line:
   - append it immediately to `stdout.stream.jsonl`;
   - pass complete JSON lines to `claude_stream.py`;
   - pass extracted assistant text to `StageMarkerProcessor.process_text()`.
5. For each stderr line:
   - append it immediately to `stderr.txt` or `stderr.stream.txt`;
   - preserve final `stderr.txt` compatibility.
6. On child exit:
   - call `StageMarkerProcessor.finish()`;
   - write the final result frame to `stdout.txt`;
   - if no final result frame was seen, write the captured raw stdout fallback
     to `stdout.txt` and mark stream metadata as incomplete;
   - store stream metadata and stage controller summary in `command.json`;
   - return `subprocess.CompletedProcess` with `stdout` equal to the final
     `stdout.txt` contents so downstream recovery remains unchanged.

Recommended internal helper:

```python
def _run_real_claude_streaming(..., marker_processor: StageMarkerProcessor) -> subprocess.CompletedProcess[str]:
    ...
```

Then keep `_run_real_claude()` as the public helper used by tests and
`_run_claude_print_phase()`, or rename carefully and update tests.

Fallback behavior:

- If a stream parser error looks systemic, keep appending raw frames and finish
  the process.
- If the final result frame is missing but raw stdout contains one valid JSON
  object, preserve the old parse path.
- If stream-json launch itself fails due to an unsupported flag, retry once
  with `--output-format json` and post-exit marker processing.

Acceptance:

- Live stage adoption updates `stage_sessions.v1.json` before the child exits.
- Lease refresh behavior remains intact.
- Timeout still kills the process and captures partial stdout/stderr.
- Existing `reconcile_phase_sessions()` behavior continues to receive a normal
  launcher result with `stdout`, `stderr`, `returncode`, and `launch_dir`.

### Phase 4 - Capability And Metadata

Objective: make the new behavior observable and diagnosable.

Update `py/swarm_do/pipeline/session_capabilities.py`:

- Add `stream_json_supported` to `claude-print` details.
- Derive it from `claude --help` in non-live mode if possible.
- Do not make stream-json absence a hard blocker while the fallback path
  exists.

Update `command.json` metadata:

- `output_format: "stream-json"`
- `stream_stdout_path`
- `stream_stderr_path`
- `stream_parse_error_count`
- `stream_first_parse_error`
- `stream_final_result_seen`
- `stage_controller.live: true`
- `stage_controller.pending_marker_count`
- `stage_controller.duplicate_marker_count`

Keep `stdout.txt`, `stderr.txt`, and existing result fields stable.

Acceptance:

- `bin/swarm sessions doctor --json` reports stream-json support information.
- Attempt `command.json` is enough to explain whether live markers were used,
  fell back, or partially failed.

### Phase 5 - Tests And Fixtures

Objective: cover both live behavior and fallback compatibility.

Add or update tests:

1. `py/swarm_do/pipeline/tests/test_stage_controller.py`
   - complete marker adopts one stage;
   - duplicate complete marker is idempotent;
   - failed marker records failed state;
   - marker with wrong result path is rejected;
   - marker before result file exists is adopted at finish;
   - unknown marker is recorded in summary without crashing.

2. `py/swarm_do/pipeline/tests/test_claude_stream.py`
   - assistant text extraction;
   - final result extraction;
   - malformed line accounting;
   - unknown frame tolerance.

3. `py/swarm_do/pipeline/tests/test_phase_pump.py`
   - fake `Popen` streaming stdout emits a marker, keeps running, and the
     stage ledger changes before process exit;
   - final `stdout.txt` remains parseable by `stdout_metrics()`;
   - timeout captures partial `stdout.stream.jsonl`;
   - unsupported stream-json falls back to legacy JSON path.

4. Regression tests for existing paths:
   - injected `claude_runner` still completes phases;
   - fake-test launcher still uses the compatibility wrapper;
   - post-exit marker scanning still works.

Add fixtures under:

```text
py/swarm_do/pipeline/tests/fixtures/claude_stream/
  success_with_stage_markers.jsonl
  malformed_then_success.jsonl
  result_only_no_markers.jsonl
```

Acceptance:

- Existing phase-session tests pass.
- New tests prove live adoption happens before final process completion.
- Recovery and spend metric tests continue to parse `stdout.txt`.

## Failure Modes And Handling

### Duplicate Markers

Treat as expected. The stage ledger is the source of truth. Duplicate markers
must not repeat controller side effects.

### Marker Arrives Before Result File

Keep the marker pending. Retry when more stream text arrives and at `finish()`.
If the result file never appears, mark the controller summary incomplete and let
phase recovery classify the attempt from artifacts and launcher output.

### Stage Result Is Invalid

Do not commit or adopt. Record marker payload with
`controller_status: invalid_stage_result`. The phase should not synthesize a
complete controller phase result.

### Stream Parser Sees Malformed Lines

Count and preserve them. Unknown or malformed stream frames should not by
themselves kill the child process. The final artifact contract remains the hard
gate.

### Final Result Frame Missing

Do not mark the phase complete from markers alone unless the controller has
already written a valid phase result and handoff. Preserve raw stream evidence
and let recovery classify the attempt.

### Parent Crashes Mid-Phase

Already-adopted stages stay durable in `stage_sessions.v1.json`. On rerun,
the processor must observe terminal stages and avoid repeating their side
effects. A later implementation can teach the foreground orchestrator to skip
already-adopted stages in the prompt; this plan only makes adoption durable and
idempotent.

## Open Questions

- Should `stage_adopted` be appended only for first terminal adoption, or also
  when a duplicate marker fills missing terminal fields such as `commit_sha`?
  Recommendation: first adoption only; use `command.json` for duplicate/fill
  diagnostics.
- Should stage result schema validation become a formal JSON Schema?
  Recommendation: defer. Start with explicit identity/status checks and add a
  schema once result shapes stabilize.
- Should the pump stop early if all expected stages are adopted?
  Recommendation: defer. Early termination risks losing the final Claude result
  object and cost telemetry.
- Should streaming transcript diagnostics inspect tool results live?
  Recommendation: later. This plan should only parse assistant text markers and
  the final result frame.

## Recommended Work Order

1. Extract and test `StageMarkerProcessor` using the existing post-exit path.
2. Add the stream parser and fixtures.
3. Add streaming subprocess IO behind a feature flag or internal fallback.
4. Switch real `claude-print` to stream-json by default with legacy fallback.
5. Add doctor metadata and command metadata.
6. Dogfood on one short phase-session run, then one multi-stage phase with a
   deliberately slow later stage to prove early adoption is visible.

## Done Definition

A `claude-print` phase can adopt stage 1 while Claude is still running stage 2.
If the parent process crashes after stage 1 adoption, rerunning the pump does
not duplicate stage 1 commit, Beads closure, or `stage_adopted` event. Existing
phase recovery still sees a normal final `stdout.txt` and continues to classify
attempts using the current artifact contract.
