# Phase Session Live Stage Marker Streaming Plan

Status: execution-ready
Date: 2026-05-02 (revised post-readiness-review)

## Coordination With Runtime Foundations Plan

This plan runs concurrently with
`docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` (Phases
1, 4, 4.5, 9). Both plans touch the same writer surfaces (`stage_sessions`,
`phase_beads`, `run_state.append_run_event`, `command.json`). Read this
section before implementing.

**Sequencing**: This plan ships first. It must NOT introduce patterns that
contradict the runtime plan's state-ownership seam (Phase 1).

**Writer rules this plan must follow** (from runtime plan § Phase 1):

- New modules added here (`stage_controller.py`, `claude_stream.py`) are
  CONSUMERS, not writers. They must call into existing writer modules
  (`stage_sessions.record_stage_*`, `phase_beads`, `commit_stage_artifacts`,
  `run_state.append_run_event`) and never write JSON state files directly.
- The runtime plan's Phase 1 fence test will land after this plan and
  will reject any direct write from `stage_controller.py` or
  `claude_stream.py`. Avoiding direct writes from day one means zero
  rework when the fence ships.
- `command.json` is launcher-visible workspace metadata, not a control-plane
  state file — adding new fields to it (`stage_controller.*` counters)
  does NOT count as a fresh writer for fence purposes.

**Trace integration** (runtime plan § Phase 4): the
`command.json.stage_controller` counters this plan introduces
(`duplicate_marker_count`, `amended_count`, `pending_marker_count`,
`rejected_marker_count`, `rejected_unknown_stage`, `rejected_invalid_path`,
`rejected_invalid_result`, `parse_error`, `legacy_json_retry`,
`ignored_frame_types`) will be projected into `AttemptTrace` by Phase 4.
Field names here are the contract — renaming requires a coordinated update
to the runtime plan's AttemptTrace shape.

**Regression boundary** (runtime plan § Concerns And Regression Boundary):
the new tests this plan adds (`test_stage_controller.py`,
`test_claude_stream.py`) and existing tests it must not regress
(`test_phase_pump.py`, `test_phase_recovery.py` for `parse_claude_print_json`,
`test_session_capabilities.py`) are now enumerated in the runtime plan's
regression boundary table. Keep them green.

**Phase 9 SQLite preview**: this plan's "ONLY the main thread calls into
stage_sessions, phase_beads, commit_stage_artifacts, append_run_event,
ClaudeStreamParser, or StageMarkerProcessor" concurrency invariant matches
SQLite's single-writer-per-process model. The runtime plan's Phase 9
migration order lists `stage_sessions` at rank 2.5 (alongside
`phase_sessions`) on the strength of this invariant — do not weaken it.

## Goal

Make controller-owned stage marker handling truly live during `claude-print`
phase execution.

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

## Verified Facts (cite, do not re-verify in code)

These were confirmed during plan review on 2026-05-02. The writer may rely on
them without re-verification; if any contradicts observed behavior at
implementation time, stop and flag.

| Fact | Source |
|------|--------|
| `claude --output-format stream-json` is supported. | `claude --help` lists `text`, `json`, `stream-json` under `--output-format`. |
| Stream emits NDJSON frames. Observed `type` values: `system`, `user`, `assistant`, `result`. `hook_response` may appear as a `system` subtype. | Live invocation 2026-05-02. |
| Assistant text frame shape: `{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}`. Other content block types (`tool_use`, `thinking`) coexist; only `text` blocks contain stage markers. | Live invocation 2026-05-02. |
| Final frame shape: `{"type":"result","subtype":"success"\|"error","is_error":bool,"session_id":"...","result":"...",...}`. Substantively the same shape that `--output-format json` writes today. | Live invocation 2026-05-02. |
| `_run_real_claude` (`phase_pump.py:1200`) uses `proc.wait(timeout=wait_for)` followed by `proc.communicate()` (lines 1276, 1282, 1284). `communicate()` blocks until EOF on both pipes; nothing reads stdout while the child runs. | Source read. |
| `_process_stage_markers` (`phase_pump.py:577`) performs in order: `record_stage_failed` + `_mark_stage_bead_blocked` (failure path), `claim_stage`, `_load_valid_stage_result`, `commit_stage_artifacts` (with `RunExecutionWorktreeError` → `record_stage_failed("adoptable_artifacts_uncommittable")`), `record_stage_adopted`, `_close_stage_bead`, `_append_stage_event(event_type="stage_adopted")`. Return shape: `{completed, markers, commits, commit_sha, worktree_diff, changed_files}`. | Source read, lines 577–655. |
| `stage_sessions.v1.json` is guarded by `fcntl.flock(LOCK_EX\|LOCK_NB)` at process granularity. POSIX flock semantics across threads of one process are undefined. | `stage_sessions.py:67`. |
| `phase_recovery._failure_kind_for_attempt` calls `parse_claude_print_json(stdout)` on the launcher result's `stdout` field. Whatever string the streaming runner returns as `CompletedProcess.stdout` MUST remain a single JSON object that `parse_claude_print_json` accepts. | `phase_recovery.py:1084`. |
| `_claude_print_capability` (`session_capabilities.py:136`) currently probes only `claude --version`. No `--help` parse exists. | Source read. |
| `command.json` has no JSON Schema (none in `swarm-do/schemas/`). It is free-form; new fields require no schema update. | Schemas dir listed. |
| `schemas/telemetry/run_events.schema.json` already includes `stage_adopted`. | Source read. |
| The new files `stage_controller.py`, `claude_stream.py`, `test_stage_controller.py`, `test_claude_stream.py` do not exist. Fixture dir pattern (`tests/fixtures/<topic>/`) is consistent with sibling dirs (`fixtures/claude_print/`, `fixtures/claude_transcripts/`). | Filesystem checked. |

## Decision

Move the real `claude-print` launcher to `--output-format stream-json` and
process complete assistant message text as it arrives. Do not process partial
token deltas in the first pass.

Keep two stdout artifacts per attempt:

- `stdout.stream.jsonl`: append-only raw stream frames, written while the child
  process runs. Bounded to 64 MiB with one rollover (see Phase 3).
- `stdout.txt`: the final Claude `{"type":"result"}` frame's body serialized as
  a single JSON object after the process exits, preserving the existing
  recovery and spend telemetry path.

The implementation MUST preserve the current post-exit marker scan for:

- injected test runners that still return `subprocess.CompletedProcess`;
- old Claude versions or configurations without reliable `stream-json`;
- malformed stream output where the final result can still be parsed after
  process exit.

## Resolved Decisions (replaces "Open Questions")

These were open at first draft. They are now ratified. Treat as MUST.

1. **`stage_adopted` event firing.** First terminal adoption only. Duplicate
   markers that arrive after a stage is already adopted MUST NOT emit a second
   `stage_adopted` event. Duplicate accounting goes into
   `command.json.stage_controller.duplicate_marker_count`. If a duplicate fills
   a missing field (e.g., `commit_sha`) on an already-adopted stage, update the
   ledger silently and record `stage_controller.amended_count++`; do not append
   a second run-event.

   *Rationale:* run-events are a state-transition log. Re-emitting on
   re-arrival creates double-counting in any consumer that totals adoption
   counts.

2. **JSON Schema for stage result.** Out of scope. Validation stays as explicit
   identity/status checks in `StageMarkerProcessor._validate_stage_result`. A
   formal schema can be added once the result shape stabilizes across writer
   roles.

3. **Early child termination when all stages adopted.** MUST NOT happen. The
   foreground Claude process is allowed to run to natural exit so the final
   `{"type":"result"}` frame and cost telemetry are captured. Killing early
   forfeits cost accounting and risks orphaning the controller-written phase
   result file.

4. **Live tool-result inspection.** Out of scope. Only `assistant.message
   .content[type=text]` blocks and the final `{"type":"result"}` frame are
   parsed in this plan. `tool_use`, `thinking`, and `system` subtypes are
   ignored (counted only as `ignored_frame_types`).

## Non-Goals

- No daemon or background service.
- No token-level or partial-message marker parsing in the first pass.
- No early child termination when all expected markers are seen.
- No extra Claude calls or live preflight spending.
- No primary reliance on `bin/swarm stages signal-*`; keep that as an escape
  hatch for unreliable marker delivery.
- No phase parallelism changes.
- No `--include-partial-messages` or `--include-hook-events` use.
- No JSON Schema for stage results in this plan.
- No foreground orchestrator change to skip already-adopted stages on rerun
  (keep that as a follow-up; this plan only makes adoption durable and
  idempotent).

## Implementation Phases

### Phase 1 — Extract Idempotent Stage Marker Processing

Objective: make marker adoption safe before making it live.

Add `swarm-do/py/swarm_do/pipeline/stage_controller.py`.

#### Required types and signatures (writers MUST match these)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from .orchestrator_stream import StageMarker, parse_stage_markers
from .stage_invocation import StageInvocation


@dataclass
class MarkerDecision:
    marker: StageMarker
    outcome: Literal[
        "adopted",
        "duplicate",
        "amended",
        "pending",
        "rejected_unknown_stage",
        "rejected_invalid_path",
        "rejected_invalid_result",
        "failed_recorded",
    ]
    commit_sha: str | None = None
    reason: str | None = None


class StageMarkerProcessor:
    def __init__(
        self,
        *,
        run_id: str,
        phase_id: str,
        phase_attempt: int,
        stage_invocations: list[StageInvocation],
        prepared: Mapping[str, Any],
        workspace_metadata: Mapping[str, Any],
        launch_dir: Path,
        data_dir: Path,
    ) -> None: ...

    def process_text(self, text: str) -> list[MarkerDecision]:
        """Run parse_stage_markers(text) and route each marker through
        process_marker(). Concatenate text across calls to handle markers
        split mid-token only when the parser already supports that — do not
        re-implement marker boundary handling here."""

    def process_marker(self, marker: StageMarker) -> MarkerDecision: ...

    def finish(self) -> dict[str, Any]:
        """Retry pending markers (whose result file did not yet exist when
        first seen). Return aggregate dict matching the legacy
        _process_stage_markers shape exactly:
            completed: bool
            markers: list[dict]
            commits: list[str]
            commit_sha: str | None
            worktree_diff: Mapping | None
            changed_files: list[str]
        Plus controller counters for command.json:
            pending_marker_count, duplicate_marker_count,
            rejected_marker_count, amended_count.
        """
```

#### Processor rules (MUST)

1. Accept only marker `stage_id` values present in the rendered
   `StageInvocation` list. Unknown stage → `MarkerDecision(outcome=
   "rejected_unknown_stage")`; payload's `controller_status` set to
   `unknown_stage_marker`. Do not crash.
2. For `STAGE_COMPLETE`, require `result_path` to match the invocation's
   `expected_result_path`. If the path differs but stays inside
   `data/runs/<run-id>/phases/<phase-id>/stage_results/`, accept it; otherwise
   reject as `rejected_invalid_path`.
3. Validate stage result JSON before adoption:
   - root is an object,
   - `run_id`, `phase_id`, `phase_attempt`, `stage_id` match,
   - `status == "complete"`.

   Failure → `record_stage_failed(... "stage_result_invalid", ...)`,
   `MarkerDecision(outcome="rejected_invalid_result")`.
4. Marker arrives before its result file exists → store in pending list,
   return `MarkerDecision(outcome="pending")`. Retry pending markers on every
   subsequent `process_text` call AND once more during `finish()`. If still
   pending at `finish()`, mark controller summary incomplete; do not synthesize.
5. **Idempotency.** Before mutating the ledger, call
   `load_stage_sessions(run_id, phase_id, data_dir=data_dir)`. If the stage is
   already in a terminal state (`adopted` or `failed`):
   - same outcome → `MarkerDecision(outcome="duplicate")`, no side effects;
   - terminal but the ledger row is missing `commit_sha` and the duplicate
     marker carries one → call `record_stage_adopted` again to fill the field
     (the underlying writer is idempotent on the field set), increment
     `amended_count`, return `MarkerDecision(outcome="amended")`. Do NOT
     re-emit `stage_adopted` event, do NOT re-close the Bead, do NOT
     re-commit.
6. The full adoption side-effect chain (in order) for a fresh terminal
   transition MUST mirror the existing `_process_stage_markers`:
   - For failure marker: `record_stage_failed` → `_mark_stage_bead_blocked`.
   - For completion marker: `claim_stage` → `_load_valid_stage_result` →
     `commit_stage_artifacts` (catch `RunExecutionWorktreeError` →
     `record_stage_failed("adoptable_artifacts_uncommittable")`) →
     `record_stage_adopted(transcript_path=launch_dir / "stdout.txt")` →
     `_close_stage_bead` → `_append_stage_event(event_type="stage_adopted",
     commit_sha=...)`.
   - The `transcript_path` stays as `launch_dir / "stdout.txt"` (a forward
     reference; not read at adoption time).
7. **Threading.** Every method is documented as MUST be called from the
   thread that owns the subprocess wait loop. The processor MUST NOT be
   called from a reader thread. Add a runtime assertion in `process_marker`
   and `finish()`:
   ```python
   assert threading.current_thread() is threading.main_thread() or \
       getattr(self, "_owner_thread", threading.current_thread()) is \
       threading.current_thread(), "StageMarkerProcessor is not thread-safe"
   ```
   The constructor MUST capture `self._owner_thread = threading.current_thread()`.

#### Refactor of `_process_stage_markers`

Replace `phase_pump._process_stage_markers` (currently `phase_pump.py:577`)
with a thin wrapper:

```python
def _process_stage_markers(
    run_id, phase_id, *, markers, stage_invocations, prepared,
    workspace_metadata, launch_dir, data_dir,
) -> dict[str, Any]:
    processor = StageMarkerProcessor(
        run_id=run_id, phase_id=phase_id, phase_attempt=...,
        stage_invocations=stage_invocations, prepared=prepared,
        workspace_metadata=workspace_metadata, launch_dir=launch_dir,
        data_dir=data_dir,
    )
    for marker in markers:
        processor.process_marker(marker)
    return processor.finish()
```

The `phase_attempt` is read from `workspace_metadata` if present, otherwise
from the `StageInvocation` list (all invocations share a phase_attempt). The
writer MUST verify that `_process_stage_markers` callers (`phase_pump.py:1127`
and any post-exit fallback path) supply a way to determine `phase_attempt`;
if not, thread a new keyword argument through.

#### Phase 1 acceptance

- All existing tests under `swarm-do/py/swarm_do/pipeline/tests/` pass without
  modification.
- New `test_stage_controller.py` cases:
  - `test_complete_marker_adopts_one_stage`,
  - `test_duplicate_complete_marker_is_idempotent` — patch
    `record_stage_adopted` as a `MagicMock`; assert call count == 1 across
    two `process_marker` invocations on the same marker,
  - `test_failed_marker_records_failed_state`,
  - `test_marker_with_wrong_result_path_is_rejected`,
  - `test_marker_before_result_file_adopted_at_finish` — write the result
    file between `process_marker` and `finish()`,
  - `test_unknown_stage_marker_recorded_without_crash`,
  - `test_amended_duplicate_fills_missing_commit_sha` — first call without
    `commit_sha`, second with; assert ledger commit_sha set, no second
    `_append_stage_event` call.

### Phase 2 — Add Claude Stream Parser

Objective: isolate Claude `stream-json` shape handling from launcher logic.

Add `swarm-do/py/swarm_do/pipeline/claude_stream.py`.

#### Frame inventory (MUST handle)

| `type` | Action |
|--------|--------|
| `system` | Ignore; increment `ignored_frame_types["system"]`. |
| `user` | Ignore; increment `ignored_frame_types["user"]`. |
| `assistant` | Iterate `message.content[]`; emit one `StreamChunk(kind="assistant_text", text=block["text"])` per block whose `type == "text"`. Other content block types (`tool_use`, `thinking`) → ignore. |
| `result` | Emit `StreamChunk(kind="result", raw_frame=frame)`. Set `metadata.final_result_seen = True`. |
| any other | Ignore; record under `ignored_frame_types[type]`. |
| line is not valid JSON | `StreamChunk(kind="malformed", parse_error=str(exc))`; increment `parse_error_count`; if first error, store under `first_parse_error`. |

#### Required types and signatures

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


@dataclass
class StreamChunk:
    kind: Literal["assistant_text", "result", "ignored", "malformed"]
    text: str = ""
    raw_frame: Mapping[str, Any] | None = None
    parse_error: str | None = None
    frame_type: str | None = None  # for ignored/result kinds


class ClaudeStreamParser:
    def __init__(self) -> None: ...

    def feed_line(self, line: str) -> StreamChunk:
        """Parse one NDJSON line. Empty/whitespace lines return
        StreamChunk(kind="ignored")."""

    def metadata(self) -> dict[str, Any]:
        """Returns:
            frames_seen: int
            parse_error_count: int
            first_parse_error: str | None
            final_result_seen: bool
            ignored_frame_types: dict[str, int]
        """
```

The parser MUST be liberal about unknown frames (count under
`ignored_frame_types` and continue). It MUST be strict about JSON validity for
the line itself (count malformed lines and continue).

The parser MUST NOT call into stage processing; it has no knowledge of
`StageMarkerProcessor`.

#### Phase 2 acceptance

- Fixtures under
  `swarm-do/py/swarm_do/pipeline/tests/fixtures/claude_stream/`:
  - `success_with_stage_markers.jsonl` — assistant frames containing
    `STAGE_COMPLETE` text, plus a final result frame.
  - `malformed_then_success.jsonl` — at least one non-JSON line, otherwise
    valid stream.
  - `result_only_no_markers.jsonl` — only a `{"type":"result"}` frame.
  - `unknown_frame_types.jsonl` — mix of `system`, `user`, `tool_use`-only
    assistant frames; no markers, no result.
- Tests in `test_claude_stream.py`:
  - `test_assistant_text_extracted`,
  - `test_final_result_captured`,
  - `test_malformed_line_increments_count_no_raise`,
  - `test_unknown_frame_type_counted_in_metadata`,
  - `test_tool_use_block_in_assistant_message_ignored`,
  - `test_marker_in_assistant_text_round_trips_through_parse_stage_markers` —
    feeds the chunk's `text` into `parse_stage_markers` (from
    `orchestrator_stream`) and asserts a marker is returned.

### Phase 3 — Implement Streaming Real Claude Runner

Objective: replace the real subprocess IO path without disturbing the injected
test runner path.

Refactor `_run_real_claude` (`phase_pump.py:1200`).

#### Argv change

In `_run_claude_print_phase`, find the argv assembly that currently passes
`"--output-format", "json"` (around `phase_pump.py:980`). Change it to
`"--output-format", "stream-json"` for the real path. The injected
`claude_runner` path (test seam) MUST remain unchanged.

#### Threading model (MUST)

```
Main thread
- Owns subprocess.Popen.
- Writes prompt to proc.stdin once and closes it (existing behavior).
- Drains a queue.Queue of (stream, line) tuples with queue.get(timeout=tick).
- On each tuple: appends raw line to the corresponding stream-file fd, feeds
  stdout lines through ClaudeStreamParser, feeds extracted assistant_text
  chunks through StageMarkerProcessor.process_text.
- Calls refresh_phase(...) when monotonic elapsed since last refresh exceeds
  refresh_interval.
- On timeout: proc.kill(); drains queue for up to 5.0 s; joins both reader
  threads with 5.0 s timeout each; raises subprocess.TimeoutExpired carrying
  the partial captured stdout/stderr (joined-string form, see "Stdout return
  contract" below).

stdout reader thread (daemon=True, name="claude-stdout-reader")
- Reads proc.stdout line-by-line until EOF.
- Enqueues ("stdout", line) for each line.
- On EOF enqueues ("stdout", None).
- Exits.

stderr reader thread (daemon=True, name="claude-stderr-reader")
- Same shape; enqueues ("stderr", line) and ("stderr", None) on EOF.

Queue: queue.Queue[tuple[str, str | None]] with no max size.

Concurrency invariant: ONLY the main thread calls into stage_sessions,
phase_beads, commit_stage_artifacts, append_run_event, ClaudeStreamParser,
or StageMarkerProcessor. Reader threads are pure pipe-to-queue I/O.
```

The existing `proc.communicate()` calls (`phase_pump.py:1276`, `1282`, `1284`)
MUST be removed. `communicate()` may not be called once the reader threads
own the pipes.

#### Stream file writes

Open both stream files in the main thread before spawning readers:

- `stdout.stream.jsonl` (line-buffered, append).
- `stderr.stream.txt` (line-buffered, append).

Reader threads send lines to the queue; the main thread writes them to disk.
This keeps the write ordering deterministic and the file handles single-owner.

**Size cap.** Hard cap of 64 MiB on `stdout.stream.jsonl`. When the running
byte count crosses the cap:

1. Append a single sentinel line:
   `{"type":"_truncated","at_bytes":<count>,"ts":"<iso8601>"}\n`
2. Close the file. Rename to `stdout.stream.jsonl.1` (overwriting any prior
   `.1`). Re-open `stdout.stream.jsonl` for append.
3. Set `command.json.stream_metadata.truncated_at_bytes = <count>`.

`stderr.stream.txt` is uncapped; it is small in practice.

#### Lease refresh

Replace the current `proc.wait(timeout=wait_for) + proc.communicate()` cadence
with a clock check inside the queue-drain loop. Pseudocode:

```python
last_refresh = time.monotonic()
while not (stdout_closed and stderr_closed):
    elapsed = time.monotonic() - started
    if elapsed > timeout_seconds:
        # timeout cancellation path (above)
        ...
    try:
        stream, line = q.get(timeout=min(refresh_interval,
                                         max(0.1, timeout_seconds - elapsed)))
    except queue.Empty:
        pass
    else:
        # process line ...
    if time.monotonic() - last_refresh >= refresh_interval:
        refresh_phase(run_id, phase_id, lease_owner=lease_owner,
                      data_dir=data_dir)
        last_refresh = time.monotonic()
```

The cadence MUST remain the same as today (every `refresh_interval` seconds).

#### Stdout return contract (CRITICAL)

`phase_recovery._failure_kind_for_attempt` (`phase_recovery.py:1084`) calls
`parse_claude_print_json(stdout)` on the launcher's `stdout` field. The
streaming runner MUST preserve this contract:

- On normal exit with a `{"type":"result"}` frame: serialize the result
  frame's body as JSON and return it via `CompletedProcess(stdout=<that
  string>)`. Write the same string to `stdout.txt`. The result frame's body
  is the same shape `--output-format json` produced previously, so
  `parse_claude_print_json` continues to work without changes.
- On normal exit without a result frame: write the concatenated raw
  stream lines to `stdout.txt` (preserving forensic value), return that same
  string as `CompletedProcess.stdout`. `parse_claude_print_json` will fail to
  parse this; that is acceptable because `phase_recovery` already has a
  failure-classification path for unparseable launcher output. Set
  `command.json.stream_metadata.fallback = "raw"`.
- On timeout: kill, drain, raise `subprocess.TimeoutExpired(output=<string>,
  stderr=<string>)`. The string is the same content rule as above.
- The injected test runner path (when `claude_runner` is supplied via the
  test seam) MUST NOT be re-routed through this code; it returns its
  pre-built `CompletedProcess` directly, exactly as today.

**Verification step (writer MUST run first):** before integrating, run
`claude -p --output-format stream-json` against any prompt and inspect the
final `{"type":"result"}` frame's body. Confirm it contains the same fields
that `parse_claude_print_json` reads (`subtype`, `is_error`, `result`,
`session_id`, `total_cost_usd`, `usage`, etc.). If the shape diverges, write
a tiny adapter inside `_run_real_claude` that projects the result frame to the
legacy shape; do not alter `parse_claude_print_json` itself.

#### Legacy fallback (precise definition)

"Stream-json launch failure" is detected as ALL of:

- child exits with `returncode != 0`,
- elapsed wall time since spawn `< 3.0 s`,
- stderr matches one of these case-insensitive substrings:
  `"unknown option"`, `"invalid choice: 'stream-json'"`,
  `"unrecognized argument"`, `"unrecognized option"`.

On match, the runner retries exactly once with the original argv changed back
to `--output-format json` and routes through the existing post-exit marker
scan. Any other failure shape (timeout, IO error, child exits with success but
no frames, parser error) does NOT trigger fallback.

Set `command.json.stream_metadata.fallback = "legacy_json_retry"` on retry.

#### Phase 3 acceptance (CI-provable)

Each below maps to a test in `test_phase_pump.py`:

- `test_streaming_live_adoption_before_exit` — fake `Popen` (`_FakePopen`)
  emits stdout lines on a timer; `poll()` returns `None` until enough lines
  delivered; assert `load_stage_sessions` shows stage 1 `adopted` while
  `proc.poll() is None`.
- `test_streaming_lease_refresh_called_on_cadence` — mock clock, mock
  `refresh_phase`, drive `_FakePopen` to exceed `refresh_interval` boundary;
  assert refresh called.
- `test_streaming_timeout_writes_partial_stream_jsonl` — `_FakePopen` never
  exits; assert `subprocess.TimeoutExpired` is raised AND
  `stdout.stream.jsonl` size > 0.
- `test_legacy_json_fallback_on_unsupported_flag` — `_FakePopen` exits
  returncode 2 within 0.5 s with stderr `"invalid choice: 'stream-json'"`;
  assert retry argv contains `"--output-format", "json"` and
  `command.json.stream_metadata.fallback == "legacy_json_retry"`.
- `test_recovery_still_parses_stdout_txt` — full streaming path completes
  with a result frame; assert
  `parse_claude_print_json((launch_dir / "stdout.txt").read_text())` returns
  the same dict shape as the legacy json path on identical content, and
  `phase_recovery._failure_kind_for_attempt(...)` returns the same value.
- `test_stream_jsonl_size_cap_truncation` — feed > 64 MiB; assert sentinel
  line present, `stdout.stream.jsonl.1` exists,
  `command.json.stream_metadata.truncated_at_bytes` set.
- `test_concurrency_invariant_no_ledger_writes_from_reader_thread` — patch
  `record_stage_adopted` to assert
  `threading.current_thread() is threading.main_thread()`; run a streaming
  scenario that adopts multiple stages.
- `test_no_result_frame_writes_raw_stdout_to_stdout_txt` — `_FakePopen`
  emits assistant frames but exits before any result frame; assert
  `stdout.txt` contains the concatenated raw lines and
  `command.json.stream_metadata.fallback == "raw"`,
  `stream_final_result_seen == false`.
- `test_existing_test_paths_unchanged` — every preexisting test in
  `test_phase_pump.py` that uses an injected `claude_runner` continues to
  pass with no edits.

### Phase 4 — Capability And Metadata

Objective: make the new behavior observable and diagnosable.

#### `session_capabilities` change

In `_claude_print_capability` (`session_capabilities.py:136`), after the
existing `claude --version` probe (~line 170), add a single
`claude --help` probe with a 5-second timeout. Parse stdout/stderr for the
substring `stream-json`. Set `details["stream_json_supported"] = bool(match)`.
Cache the boolean in a module-level singleton keyed by `claude_path` for the
process lifetime; do not re-probe.

Probe failure (timeout, missing binary) MUST NOT fail the capability check —
emit `details["stream_json_probe_error"] = str(exc)`,
`details["stream_json_supported"] = false`, and continue. The launcher's
runtime fallback (Phase 3) handles unsupported environments.

#### `command.json` additions (canonical field names)

```jsonc
{
  "output_format": "stream-json",
  "stream_stdout_path": "stdout.stream.jsonl",
  "stream_stderr_path": "stderr.stream.txt",
  "stream_metadata": {
    "frames_seen": 0,
    "parse_error_count": 0,
    "first_parse_error": null,
    "final_result_seen": false,
    "ignored_frame_types": {},
    "fallback": null,
    "systemic_parse_error": false,
    "truncated_at_bytes": null
  },
  "stage_controller": {
    "live": true,
    "completed": false,
    "markers": [],
    "commits": [],
    "commit_sha": null,
    "worktree_diff": null,
    "changed_files": [],
    "pending_marker_count": 0,
    "duplicate_marker_count": 0,
    "amended_count": 0,
    "rejected_marker_count": 0
  }
}
```

The existing keys (`completed`, `markers`, `commits`, `commit_sha`,
`worktree_diff`, `changed_files`) inside `stage_controller` MUST keep their
current names and types. The new counter keys are additive.

A "systemic parse error" is defined as `parse_error_count > 50` OR
(`frames_seen > 100` AND `parse_error_count / frames_seen > 0.25`). On match,
the parser keeps draining and writing raw frames to disk but stops feeding
text to `StageMarkerProcessor.process_text`; the post-exit marker scan path
takes over for any remaining markers in the final `stdout.txt`.

#### Phase 4 acceptance

- `bin/swarm sessions doctor --json` (or whatever path
  `session_capabilities` feeds) reports `stream_json_supported` in
  `claude-print` details.
- A multi-stage attempt's `command.json` contains every field listed above.
- `test_session_capabilities.py` adds
  `test_claude_print_stream_json_probe_supported` and
  `test_claude_print_stream_json_probe_unsupported` (both mock the
  subprocess that runs `claude --help`).

### Phase 5 — Tests And Fixtures

The full test list is itemized inline in Phase 1, Phase 2, Phase 3, and
Phase 4 acceptance sections above. This phase is the integration point where
the writer ensures:

1. `cd swarm-do && PYTHONPATH=py python3 -m unittest discover py/swarm_do/pipeline/tests -v`
   passes.
2. `cd swarm-do && PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_session_capabilities -v`
   passes.
3. New fixture dir
   `swarm-do/py/swarm_do/pipeline/tests/fixtures/claude_stream/` exists with
   the four files listed in Phase 2.
4. No existing test was modified to make the new code pass; if a test had to
   change, that change MUST be called out in the writer's review notes with
   a justification.

## Failure Modes And Handling

### Duplicate Markers

Treat as expected. Stage ledger is the source of truth. Duplicate markers
MUST NOT repeat controller side effects. A duplicate that fills a missing
field is "amended" (see Resolved Decision 1).

### Marker Arrives Before Result File

Keep pending. Retry on every subsequent `process_text` call and once at
`finish()`. If still missing, mark controller summary incomplete and let
phase recovery classify the attempt from artifacts and launcher output. Do
NOT synthesize a stage result.

### Stage Result Is Invalid

Do not commit or adopt. Record marker payload with
`controller_status: stage_result_invalid` (matches existing
`_process_stage_markers` behavior at `phase_pump.py:621`). The phase MUST NOT
synthesize a complete controller phase result.

### Stream Parser Sees Malformed Lines

Count and preserve. Unknown or malformed stream frames MUST NOT by themselves
kill the child process. The 25%-or-50-malformed threshold (Phase 4) flips
the parser into raw-only mode but does not abort.

### Final Result Frame Missing

Do not mark the phase complete from markers alone unless the controller has
already written a valid phase result and handoff. Preserve raw stream
evidence in `stdout.txt` (concatenated raw lines) and let recovery classify
the attempt. Set `stream_metadata.fallback = "raw"`.

### Parent Crashes Mid-Phase

Already-adopted stages stay durable in `stage_sessions.v1.json`. On rerun,
`StageMarkerProcessor` MUST observe terminal stages via
`load_stage_sessions` and route duplicates to `outcome="duplicate"` /
`"amended"`. Teaching the foreground orchestrator to skip already-adopted
stages in the prompt is out of scope for this plan.

### Backwards Compatibility With Legacy `command.json`

Pre-existing in-flight runs have `command.json` without `output_format` or
`stream_metadata`. `phase_recovery.reconcile_phase_sessions` and any other
reader MUST treat missing `output_format` as the legacy `json` path. Concretely:

- If `command.get("output_format") != "stream-json"`, use only `stdout.txt`
  via `parse_claude_print_json`; do not look for `stdout.stream.jsonl`.
- If `command.get("output_format") == "stream-json"` but `stream_metadata`
  is absent, treat as a partially-written record: log a warning, fall back
  to legacy parsing of `stdout.txt`, and continue.

No code path is allowed to fail when reading a legacy attempt directory.

## Recommended Work Order

1. Phase 1: extract and test `StageMarkerProcessor` using the existing
   post-exit path (refactor `_process_stage_markers` to a wrapper). Land
   this independently and verify the existing test suite still passes.
2. Phase 2: add `claude_stream.py` + fixtures + parser tests.
3. Phase 3: rewrite `_run_real_claude` for streaming. Remove
   `proc.communicate()` calls. Add the legacy-fallback retry path.
4. Phase 4: add capability probe and `command.json` metadata fields.
5. Phase 5: integration sweep; full unittest run.
6. Dogfood on one short phase-session run, then one multi-stage phase with a
   deliberately slow later stage to prove early adoption is visible (assert
   stage 1 ledger transition happens before phase exit by inspecting
   timestamps).

## Done Definition

A `claude-print` phase can adopt stage 1 while Claude is still running
stage 2. If the parent process crashes after stage 1 adoption, rerunning the
pump does not duplicate stage 1 commit, Beads closure, or `stage_adopted`
event. Existing phase recovery still sees a normal final `stdout.txt` and
continues to classify attempts using the current artifact contract. Legacy
in-flight runs (`output_format` absent from `command.json`) continue to
recover and reconcile without code changes on the reader side.
