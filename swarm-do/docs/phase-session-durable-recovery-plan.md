# Phase Session Durable Recovery Plan

Status: implementation-ready proposal
Date: 2026-04-29

## Goal

Move phase-session autopilot from happy-path foreground execution to durable,
unattended recovery after parent or child failure.

The reliability floor is reconcilable resume, not retry. Retrying is useful, but
the system must first be able to restart after parent death, inspect persisted
state and artifacts, adopt valid work, preserve evidence from abandoned
attempts, and only then decide whether another child should launch.

The shared operator vocabulary for these decisions lives in
[`docs/failure-taxonomy.md`](failure-taxonomy.md).

North star:

- Never duplicate an active phase.
- Never discard partial evidence.
- Never retry a human-gated state.
- Never make the operator manually adopt valid artifacts.

## Current State

The current implementation has the right primitives but not yet the right
behavior for non-happy paths.

Existing durable primitives:

- `phase_sessions.v1.json` persists phase status, lease metadata, attempts,
  result paths, handoff paths, and terminal states.
- `phase_sessions.py` validates prepared artifacts, sidecars, result artifacts,
  handoff artifacts, lease ownership, path containment, and state transitions.
- `phase_pump.py` starts fresh phase sessions and writes launch artifacts under
  `data/runs/<run_id>/phase_launches/<phase_id>/attempt-<n>/`.
- `resume.py` reports phase-session state from the Beads epic id.
- `context_bundle.py` renders dependency-scoped completed handoffs into the next
  phase prompt.

Current behavioral gaps:

- `phase_pump.py` stops when `reap_expired_phases()` returns a stale lease.
- `phase_pump.py` stops on launcher errors instead of reconciling expected
  result and handoff paths first.
- `phase_pump.py` currently treats nonzero `claude-print` plus complete artifacts
  as `launcher_error`, even though the artifacts may be adoptable completion.
- `resume.py` reports phase-session state but does not repair or reconcile it.
- `claim_next_phase(..., reclaim_stale=True)` resets a stale phase to pending
  without preserving attempt evidence, launch evidence, retry decision, or
  recovery context.
- The next prompt only includes completed dependency handoffs; it does not
  include dead-attempt launch evidence, dirty diff context, stderr tails, or
  changed-file summaries.

## Recommendation

Add a first-class reconciliation and recovery layer. The pump and prepared-run
auto mode should call this layer before every claim and after every launcher
return.

The order of operations must be:

1. Validate prepared state and sidecar hashes.
2. Reconcile current phase-session state.
3. Scan expected current-attempt result and handoff paths.
4. Adopt valid artifacts for the current attempt.
5. Inspect launch dirs and classify abandoned attempts.
6. Preserve attempt history and recovery evidence.
7. Retry only when policy allows it.
8. Claim the next phase only after reconciliation is complete.

Do not build a daemon as part of this plan. This should make the existing
foreground pump and `bin/swarm do --prepared <run-id> --phase-sessions auto`
safe to re-run after parent death. A daemon can remain a later wrapper around
the same recovery primitives.

## Recovery Buckets

### Adoptable Completion

Use this when the parent or outer launcher reporting failed, but the expected
result and handoff files exist and validate for the current attempt.

Examples:

- Parent process died after the child wrote artifacts.
- `claude-print` returned malformed outer JSON, but expected artifacts are
  present.
- `claude-print` returned nonzero, but expected artifacts validate.
- Outer JSON is missing `stdout`, missing artifact object, or points to unusable
  paths, but the contract paths validate.

Behavior:

- Record/adopt the artifacts instead of retrying.
- Preserve the launcher anomaly in attempt history.
- Continue to the next phase only if the adopted phase status is `complete`.
- Stop for adopted `blocked`, `needs_input`, or nonretryable `failed`.

### Retryable Failure

Use this only after reconciliation proves no valid current-attempt artifacts
exist.

Auto-retry these by default:

- Parent died, lease expired, no valid result or handoff exists.
- Child process died, was killed, or exited nonzero without valid structured
  artifacts.
- Timeout with no valid artifacts.
- Rate limit or provider transport failure, ideally respecting retry-after or
  backoff.
- Invalid outer Claude JSON, missing artifact object, or missing stdout, after
  scanning expected result and handoff paths.
- Result or handoff validation failed because artifacts are missing or partially
  written.

Behavior:

- Append attempt history with failure kind and evidence.
- Reset phase to pending only through an explicit retry transition.
- Increment attempt only when `start_phase()` launches the next child.
- Render recovery context into the next prompt.

### Human-Gated Stop

Do not auto-retry:

- `blocked`.
- `needs_input`.
- Handoff `do_not_retry`.
- Structured `failed` unless the result contract explicitly says
  `retryable: true`.

Behavior:

- Record/adopt artifacts if valid.
- Mark the phase as the structured terminal state.
- Surface the reason in phase status, resume output, run events, and Beads notes.

### Hard Contract Stop

Do not auto-retry:

- Prepared artifact drift.
- Sidecar hash mismatch.
- Path escape.
- Result/handoff run_id, phase_id, or attempt mismatch.
- Structurally contradictory artifacts.
- Launcher ineligible.
- Claude CLI missing.
- Permission contract failure.

Behavior:

- Stop the pump.
- Preserve evidence.
- Mark the failure as nonretryable.
- Require operator intervention.

## Timeout Policy

A timeout is not automatically transient.

Short or no-progress timeouts can be retried cheaply. Long timeouts or dirty
partial work should get one recovery-aware attempt, not an identical retry.

Recommended policy:

- For short/no-progress failure with no artifacts and no dirty diff, retry within
  the normal session retry budget.
- For long timeout or dirty partial work, schedule at most one recovery attempt.
- The recovery attempt prompt must say that the previous attempt timed out and
  include launch dir, stderr tail, stdout tail, changed files, and diff summary.
- If the recovery attempt also fails, mark `retry_exhausted` unless the result
  explicitly and safely requests another retry within budget.

Default budgets:

- `max_session_attempts`: 3
- `max_recovery_attempts`: 1 for long/dirty timeout recovery
- `recovery_timeout_threshold_seconds`: 600
- `retry_sleep_threshold_seconds`: 60
- `max_retry_after_seconds`: 1800
- Honor `retry_after_seconds` when present, but clamp provider-supplied values
  to `max_retry_after_seconds`.

Retry timing:

- If `next_retry_at` is 60 seconds or less away, the foreground pump may sleep
  in-process and continue.
- If `next_retry_at` is more than 60 seconds away, return `retry_waiting`.

Recovery-attempt classification:

- If elapsed time is greater than 600 seconds, consume the recovery-attempt
  budget and render a recovery prompt.
- If the worktree diff is dirty relative to the phase-session baseline, consume
  the recovery-attempt budget and render a recovery prompt.
- If partial artifacts exist, consume the recovery-attempt budget and render a
  recovery prompt.
- Otherwise, treat the failure as a cheap retry against
  `max_session_attempts=3`.

## State Schema Changes

Extend `schemas/phase_sessions.schema.json` without bumping schema version if
the fields are optional and old state files still validate. Because the schema
uses `additionalProperties: false`, every new field must be explicitly declared.

Add root fields:

- `retry_policy`
  - `max_session_attempts`
  - `max_recovery_attempts`
  - `recovery_timeout_threshold_seconds`
  - `retry_sleep_threshold_seconds`
  - `short_retry_backoff_seconds`
  - `max_retry_after_seconds`
  - `worktree_baseline_path`

Add per-phase fields:

- `max_session_attempts`
- `next_retry_at`
- `last_failure_kind`
- `last_launcher_error`
- `retry_exhausted_at`
- `attempt_history`

Suggested `attempt_history` item shape:

```json
{
  "attempt": 1,
  "session_name": "swarmdaddy-<run_id>-<phase_id>-attempt-1",
  "launcher": "claude-print",
  "lease_owner": "host:pid:uuid",
  "lease_host": "host",
  "lease_pid": 12345,
  "child_pid": 23456,
  "process_group_id": 23456,
  "started_at": "2026-04-29T00:00:00Z",
  "completed_at": "2026-04-29T00:05:00Z",
  "elapsed_seconds": 300.0,
  "launch_dir": "data/runs/<run_id>/phase_launches/1/attempt-1",
  "result_path": "data/runs/<run_id>/phase_results/1/attempt-1.result.json",
  "handoff_path": "data/runs/<run_id>/phase_handoffs/1/attempt-1.handoff.json",
  "returncode": 1,
  "failure_kind": "launcher_nonzero_no_artifacts",
  "retry_decision": "retry",
  "retry_after_seconds": null,
  "adopted": false,
  "stdout_tail_path": "data/runs/<run_id>/phase_recovery/1/attempt-1.stdout.tail.txt",
  "stderr_tail_path": "data/runs/<run_id>/phase_recovery/1/attempt-1.stderr.tail.txt",
  "changed_files": [],
  "diff_summary_path": "data/runs/<run_id>/phase_recovery/1/attempt-1.diff-summary.md"
}
```

Add phase statuses:

- `retry_waiting`
- `retry_exhausted`

These are net-new enum values. Add back-compat load tests that prove old state
files without retry fields still load, then write back with defaults. Add schema
tests that prove the new statuses validate.

## Result And Handoff Contract Changes

Extend `schemas/phase_result.schema.json` with optional fields:

- `retryable`: boolean
- `failure_kind`: string
- `retry_after_seconds`: integer or null

Rules:

- `handoff.do_not_retry` remains a hard stop.
- `blocked` and `needs_input` are never auto-retried.
- `failed` is retried only when `retryable: true` and no hard contract stop
  applies.
- `retry_after_seconds` may delay retry but must not override retry budget or
  human-gated states.

Add new `record_phase_result()` validation checks:

- Confirm `prepared_plan_sha` matches phase-session state.
- Confirm `phase_content_sha` matches the prepared phase metadata.
- Continue enforcing run_id, phase_id, attempt, handoff status, and path
  containment.

These are new checks, not existing checks being tightened. Tests should cover
both mismatch cases explicitly.

## Worktree Baseline

Add `py/swarm_do/pipeline/worktree_baseline.py`.

Behavior:

- Snapshot porcelain state before phase 1 launches.
- Store the snapshot under the run directory and reference it from
  `retry_policy.worktree_baseline_path`.
- Warn but do not reject if the operator starts with a dirty worktree.
- Compute later `changed_files` and dirty-diff summaries against the baseline,
  not against an assumed clean working tree.
- Include untracked baseline files so preexisting local dirt is not
  misattributed to a failed phase attempt.

Rationale:

- Recovery prompts should show what the dead attempt changed, not everything
  that happened to be dirty before phase execution began.
- Dirty starting state should be visible to the operator but should not block
  adoption, retry, or recovery by default.

## New Recovery Module

Add `py/swarm_do/pipeline/phase_recovery.py`.

Responsibilities:

- Load and validate prepared state.
- Reconcile active, stale, failed, retry-waiting, and retry-exhausted phases.
- Scan expected result/handoff paths for the phase's current attempt.
- Validate artifacts without requiring the phase to currently be `running`.
- Inspect launch dirs and command metadata.
- Inspect worktree baseline state and classify dirty or partial attempts.
- Classify failure kind.
- Build attempt-history records.
- Write recovery-context markdown.
- Return a structured reconciliation decision.

Suggested public API:

```python
def reconcile_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    launcher: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    ...
```

Suggested decision shape:

```json
{
  "status": "ready",
  "actions": [
    {
      "phase_id": "1",
      "attempt": 1,
      "action": "adopted_completion",
      "failure_kind": "outer_json_invalid",
      "retry_decision": "adopted",
      "result_path": "...",
      "handoff_path": "..."
    }
  ],
  "active_phase": null,
  "next_phase": {"phase_id": "2"},
  "blocked_reason": null
}
```

Possible `status` values:

- `ready`
- `complete`
- `active`
- `retry_waiting`
- `retry_exhausted`
- `blocked`
- `needs_input`
- `failed_nonretryable`
- `drift`

Retry timing decisions:

- `reconcile_phase_sessions()` should apply the 1800 second
  `retry_after_seconds` clamp.
- It should return `retry_waiting` when `next_retry_at` is more than 60 seconds
  away.
- The pump may sleep only when `next_retry_at` is 60 seconds or less away.

## Phase Session Transition Changes

Add explicit transitions in `phase_sessions.py`.

### `adopt_phase_result()`

Records valid artifacts for the current attempt even if phase status is
`running` or `stale`.

Constraints:

- Current phase attempt must equal artifact attempt.
- Artifact paths must be expected paths or safely within the run directory.
- Result and handoff must validate.
- Prepared and phase content hashes must match.
- Status must be one of the supported structured states.

### `abandon_attempt_and_retry()`

Classifies an abandoned attempt and moves the phase back to pending while
preserving evidence.

Constraints:

- Only active/stale/retryable failed phases are eligible.
- Do not increment attempt here.
- Clear lease fields only after attempt history has been appended.
- Preserve `last_failure_kind`, `last_launcher_error`, and `next_retry_at`.
- Emit run event with retry decision.

### `mark_retry_exhausted()`

Marks a phase exhausted when retry budget is spent.

Constraints:

- Preserve the last attempt evidence.
- Do not erase result/handoff paths if any partial files exist.
- Surface a recommended command that points to status/recovery evidence, not a
  blind retry.

### `record_launch_metadata()`

Record launch dir, command path, parent PID, child PID, process group id, prompt
sha, and expected artifact paths as soon as the child starts.

Rationale:

- Active lease liveness currently only proves the parent pump PID. To safely
  avoid duplicate launches, same-host liveness checks should know the child PID
  or process group.

Launcher implementation requirement:

- `_run_real_claude()` must launch the child with `start_new_session=True`.
- Persist `proc.pid` as `child_pid`.
- Persist `os.getpgid(proc.pid)` as `process_group_id` when available.
- If process-group lookup fails, record the error in launch metadata and treat
  liveness as unknown.

Liveness rule:

- Same-host active lease recovery requires child-PID liveness evidence.
- Use `os.kill(pid, 0)` for PID checks so the implementation works on macOS
  without `/proc`.
- Cross-validate the process group id when available.
- Treat unknown, permission-denied, missing metadata, malformed metadata, and
  other liveness-check errors as alive.
- Only recover an unexpired same-host active lease when liveness proves the child
  is gone.

## Pump Integration

Update `phase_pump.py`.

Before the loop claims anything:

1. Initialize if requested.
2. Run `reconcile_phase_sessions()`.
3. If reconciliation adopted a complete phase, continue the loop.
4. If reconciliation returns active, blocked, needs_input, retry_waiting,
   retry_exhausted, failed_nonretryable, or drift, stop with that status.
5. Only claim when reconciliation returns ready.

After a `claude-print` launch returns:

1. Scan expected result/handoff files first.
2. If they validate, adopt/record them regardless of outer JSON or return code.
3. Parse outer JSON second and use it as supporting evidence.
4. If no valid artifacts exist, classify the launcher result and decide retry.
5. If retryable, abandon attempt and continue the loop when retry timing allows.
6. If not retryable, stop with preserved evidence.

Important behavior change:

- Nonzero launcher return with valid complete artifacts becomes adoptable
  completion, not launcher error.

Child process metadata:

- Step 2 must update `_run_real_claude()` to use `start_new_session=True`.
- Step 2 must persist child PID and process group id in launch metadata before
  waiting on the process.
- Recovery must use that metadata for conservative active-lease liveness checks.

## Resume Integration

Keep `bin/swarm resume <bd-id>` read-only. Do not add `--reconcile`.

Changes:

- Teach `resume.py` to report `retry_waiting`, `retry_exhausted`,
  `failed_nonretryable`, and recovery evidence paths.
- Update `commands/resume.md` so `ready` with phase-session state points the
  operator to `bin/swarm do --prepared <run-id> --phase-sessions auto`.
- Do not let resume mutate `phase_sessions.v1.json`.

Recommended rule:

- Mutation belongs in `phases pump`, `phases recover`, or
  `do --prepared --phase-sessions auto`, never the default `resume` manifest
  command.

## Recovery Context Rendering

Update `context_bundle.py` and `schemas/phase_context.schema.json`.

Add a recovery section to the next prompt when the current phase is a retry.

Artifacts:

- `data/runs/<run_id>/phase_recovery/<phase_id>/attempt-<n>.recovery.md`
- `data/runs/<run_id>/phase_recovery/<phase_id>/attempt-<n>.stdout.tail.txt`
- `data/runs/<run_id>/phase_recovery/<phase_id>/attempt-<n>.stderr.tail.txt`
- `data/runs/<run_id>/phase_recovery/<phase_id>/attempt-<n>.diff-summary.md`

Prompt content:

- Previous attempt number and session name.
- Failure kind and retry decision.
- Launch dir.
- Return code and elapsed time.
- Stdout and stderr tails.
- Changed files.
- Concise diff summary.
- Instruction to inspect existing work and continue or return blocked; do not
  restart blindly.

Diff evidence:

- Use `worktree_baseline.py` to compare current state against the stored
  pre-phase baseline.
- Use `git diff --name-status`, `git diff --shortstat`, and capped `git diff`
  snippets from that baseline.
- Include untracked files that were not present in the baseline.
- Cap output size to protect prompt budget.
- If the repository is unavailable or git commands fail, include the failure as
  recovery evidence rather than blocking reconciliation.

## Beads And Telemetry Logging

Telemetry remains the source of truth. Beads notes are for operator visibility
and cross-session human context.

Add or reuse run events for:

- `phase_session_reconciled`
- `phase_attempt_abandoned`
- `phase_attempt_retry_scheduled`
- `phase_attempt_retry_exhausted`
- `phase_attempt_adopted`

If avoiding new event types, fold these into `phase_pump_stopped`,
`phase_session_failed`, and `retry_started` with strong `details.reason` and
`details.failure_kind` values. Prefer new event types if the telemetry schema
can be updated in the same phase because recovery needs to be queryable.

Beads epic notes should be updated for significant state changes:

- Phase-session run started.
- Adopted completion after parent/launcher failure.
- Retry scheduled, with phase id, attempt, failure kind, and next retry time.
- Retry exhausted, with recovery evidence path.
- Human-gated stop: blocked or needs_input.
- Hard contract stop: drift, path escape, sidecar mismatch, launcher ineligible,
  permission failure.
- Run complete.

Do not write Beads notes for:

- Every lease refresh.
- Every status read.
- Repeated identical retry-waiting checks.

Child issue notes:

- Only update a child Beads issue when there is an unambiguous `beads_id` for the
  affected work unit or phase.
- For phase-level failures without a child issue, write to the epic only.
- Never let Beads logging be required for recovery correctness; if `bd update`
  fails, preserve a local run event and keep the phase-session transition.

Add `py/swarm_do/pipeline/phase_beads.py`.

Rationale:

- `bd_epic_id` already flows through prepared artifacts, run events, and resume
  lookup, so the helper has enough identity to write useful epic notes.

Helper behavior:

- Best-effort only; Beads write failures must not block recovery transitions.
- Kind allowlist enforces the no-noise rule.
- Per-run dedupe cache suppresses repeated `retry_waiting` notes.
- Notes go to the epic by default.
- Child issue notes require an unambiguous phase/work-unit `beads_id`.
- The helper should produce concise, operator-facing note blocks with paths to
  local recovery evidence.

Suggested allowlist:

- `phase_session_started`
- `phase_attempt_adopted`
- `phase_attempt_retry_scheduled`
- `phase_attempt_retry_exhausted`
- `phase_human_gated`
- `phase_hard_stop`
- `phase_session_complete`

## CLI And UX Changes

Update `phase_status()` and CLI formatting to show:

- Recovery status.
- Last failure kind.
- Retry budget used/remaining.
- Next retry time.
- Last launch dir.
- Recovery context path.
- Recommended command.

Update `_phase_session_status_label()` for:

- `retry_waiting`
- `retry_exhausted`
- `failed_nonretryable`
- `adopted_completion` if surfaced as a transient pump result.

Add a recover command:

```bash
bin/swarm phases recover <run-id> --json [--dry-run]
```

This command runs reconciliation without launching a new child. `--dry-run`
reports the actions recovery would take without mutating phase-session state.
The pump must call the same recovery helper internally and must not depend on the
operator running this command manually.

## Test Plan

Add tests in `test_phase_sessions.py`, `test_phase_pump.py`, `test_resume.py`,
and `test_context_bundle.py`. Add a new `test_phase_recovery.py` if the recovery
module is large enough.

Required cases:

- Parent death with valid complete artifacts: next pump adopts artifacts and
  advances.
- Parent death with valid blocked artifacts: next pump adopts and stops blocked.
- Parent death without artifacts: expired lease becomes retryable.
- Expired lease retry preserves attempt history.
- Valid active lease does not duplicate a phase.
- Valid active lease with same-host dead child recovers only when child PID or
  process group proves death.
- Valid active lease with missing, unknown, permission-denied, or malformed
  liveness metadata is treated as alive.
- `_run_real_claude()` starts child processes with `start_new_session=True` and
  records `child_pid` plus `process_group_id`.
- Launcher nonzero with valid complete artifacts is adopted.
- Malformed outer JSON with valid expected artifacts is adopted.
- Outer JSON points outside run dir but expected contract artifacts validate:
  adopt expected artifacts and record outer path anomaly.
- Retry-after values are clamped to 1800 seconds.
- `next_retry_at` 60 seconds or less away may sleep in-process; longer delays
  return `retry_waiting`.
- Timeout at 600 seconds or less with no dirty diff and no partial artifacts gets
  a cheap retry.
- Timeout greater than 600 seconds renders recovery context and consumes the
  recovery-attempt budget.
- Dirty diff or partial artifacts render recovery context and consume the
  recovery-attempt budget.
- Worktree baseline captures preexisting dirty state before phase 1 and excludes
  it from later changed-file attribution.
- Structured failed with `retryable` absent or false does not retry.
- Structured failed with `retryable: true` retries within budget.
- `blocked`, `needs_input`, and handoff `do_not_retry` never retry.
- Prepared drift, sidecar mismatch, path escape, run_id/phase_id/attempt
  mismatch, launcher ineligible, CLI missing, and permission contract failures do
  not retry.
- Retry budget exhaustion sets `retry_exhausted` and preserves evidence.
- Back-compat state files without retry fields still load and write back with
  defaults.
- `retry_waiting` and `retry_exhausted` validate as phase-session statuses.
- Resume reports retry-waiting and retry-exhausted states.
- Recovery prompt includes launch dir, stdout/stderr tail paths, changed files,
  and diff summary.
- `bin/swarm phases recover <run-id> --json --dry-run` reports recovery actions
  without mutation.
- `phase_beads.py` writes only allowlisted note kinds and dedupes repeated
  retry-waiting notes.

Validation commands:

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_sessions
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_pump
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_resume
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_context_bundle
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_command_profiles
```

## Implementation Steps

### Step 1 - Contract And Schema

Files:

- `schemas/phase_sessions.schema.json`
- `schemas/phase_result.schema.json`
- `schemas/phase_handoff.schema.json` if handoff retry fields are needed
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`

Work:

- Add optional retry/result fields.
- Add optional phase-session history fields.
- Add default retry policy during init.
- Add `retry_waiting` and `retry_exhausted` to the phase status enum.
- Add `child_pid` and `process_group_id` to the attempt-history schema.
- Add compatibility handling for old state files before write.
- Add new result validation checks for prepared and phase content hashes.

Done when:

- Old phase-session fixtures still load.
- New state writes include retry policy and history fields.
- New retry statuses validate.
- Invalid prepared or phase hash artifacts are rejected.

### Step 2 - Worktree Baseline And Launcher Liveness

Files:

- `py/swarm_do/pipeline/worktree_baseline.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`

Work:

- Snapshot porcelain state before phase 1.
- Store baseline path in retry policy.
- Compute changed files against baseline.
- Launch Claude with `start_new_session=True`.
- Persist `child_pid` and `process_group_id`.
- Add conservative same-host liveness helper using `os.kill(pid, 0)`.

Done when:

- Dirty starting state is warned and captured, not rejected.
- Changed-file summaries do not misattribute baseline dirtiness.
- Active unexpired leases recover only when child death is proven.
- Unknown liveness is treated as alive.

### Step 3 - Recovery State Machine

Files:

- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`

Work:

- Implement artifact scanning and validation.
- Implement attempt classification.
- Implement adopt, abandon, retry, retry-waiting, and retry-exhausted decisions.
- Preserve attempt history.
- Add launch-dir scanning.
- Apply 60 second retry-wait sleep threshold and 1800 second retry-after clamp.
- Apply 600 second recovery timeout threshold.

Done when:

- Reconciliation is idempotent.
- Re-running reconciliation does not duplicate history or relaunch work.
- Adoptable artifacts are recorded without manual intervention.

### Step 4 - Pump Integration

Files:

- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`

Work:

- Call reconciliation before every claim.
- Replace stale stop with recovery decision handling.
- Scan expected artifacts before trusting outer JSON.
- Convert launcher error paths into classified retry or hard-stop outcomes.
- Ensure every return path emits a useful pump stop event.
- Use the child PID/process-group metadata from Step 2 for active-lease recovery.

Done when:

- Fresh re-run after parent death continues without manual adoption.
- Nonzero/malformed outer launcher results do not hide valid artifacts.
- Active lease duplicate protection is preserved.

### Step 5 - Recovery Prompt Context

Files:

- `py/swarm_do/pipeline/context_bundle.py`
- `schemas/phase_context.schema.json`
- `py/swarm_do/pipeline/tests/test_context_bundle.py`

Work:

- Write recovery markdown and tail files.
- Add recovery context paths to source list and context JSON.
- Render recovery context into dispatcher prompts for retry attempts.
- Include baseline-relative dirty diff summaries.
- Cap output size.

Done when:

- Retry prompts are explicitly resume-aware.
- Dirty partial work is visible to the next child.
- Prompt budget enforcement still works.

### Step 6 - Resume And Operator UX

Files:

- `py/swarm_do/pipeline/resume.py`
- `py/swarm_do/pipeline/cli.py`
- `commands/resume.md`
- `README.md`
- `py/swarm_do/pipeline/tests/test_resume.py`

Work:

- Report retry and recovery states.
- Add recommended recovery commands.
- Update status labels.
- Document that `do --prepared --phase-sessions auto` reconciles before launch.
- Add `bin/swarm phases recover <run-id> --json [--dry-run]`.
- Keep `bin/swarm resume <bd-id>` read-only with no `--reconcile`.

Done when:

- Resume output tells the operator what happened and what command is safe.
- Retry-exhausted and human-gated states are clearly distinct.
- Recover command can reconcile without launching a child.

### Step 7 - Beads Visibility

Files:

- `py/swarm_do/pipeline/phase_beads.py`
- `commands/do.md`
- `commands/resume.md`
- telemetry schema/docs if adding event types

Work:

- Append concise Beads epic notes for significant recovery transitions.
- Keep Beads writes best-effort.
- Avoid noisy lease-refresh notes.
- Enforce kind allowlist.
- Add per-run dedupe cache for repeated retry-waiting notes.
- Document which states are logged.

Done when:

- A human opening the epic can see adoption, retry, exhaustion, and blockers.
- Recovery correctness does not depend on Beads being writable.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Duplicate active phase launch | Preserve one-active-phase invariant; require valid lease expiry or same-host child liveness proof before retrying active leases. |
| Retrying corrupt partial work | Render recovery context and use one recovery-aware attempt for long/dirty timeouts. |
| Adopting wrong artifacts | Validate run_id, phase_id, attempt, prepared_plan_sha, phase_content_sha, handoff status, and path containment. |
| Schema migration breaks old runs | Add optional fields and backfill defaults on write. |
| Beads notes become noisy | Log only significant recovery transitions, not refreshes/status reads. |
| Retry hides real blockers | Treat blocked, needs_input, do_not_retry, drift, sidecar mismatch, path escape, and contradiction as hard stops. |
| Recovery module duplicates phase-session logic | Keep state mutation transitions in `phase_sessions.py`; recovery module decides and calls explicit transitions. |
| Dirty starting worktree pollutes recovery context | Capture a baseline before phase 1 and compute later changes against it. |
| Child liveness check is wrong or unavailable | Treat unknown as alive and recover active leases only with positive dead-child proof. |

## Resolved Decisions

- Resume stays read-only. Do not add `--reconcile`.
- Add `bin/swarm phases recover <run-id> --json [--dry-run]`.
- Sleep in-process only when `next_retry_at` is 60 seconds or less away;
  otherwise return `retry_waiting`.
- Clamp provider `retry_after_seconds` at 1800 seconds.
- Use 600 seconds as the timeout boundary for recovery-aware attempts.
- Warn and capture dirty starting worktree state as a baseline; do not reject it.
- Require child-PID/process-group liveness for unexpired same-host active lease
  recovery, and treat unknown as alive.
- Add `phase_beads.py` with an allowlist and retry-waiting dedupe cache.

## Non-Goals

- No daemon.
- No parallel phase scheduling.
- No new global state database.
- No automatic merge behavior.
- No retry of human-gated states.
- No retry around prepared artifact drift or permission contract failure.
