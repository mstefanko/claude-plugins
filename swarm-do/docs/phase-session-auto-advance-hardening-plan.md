# Phase Session Auto-Advance Hardening Plan

Status: implementation-ready proposal, spend fuse first
Date: 2026-04-29

## Goal

Make `--phase-sessions auto` safe enough to run without burning large amounts
of model spend before an operator can see what is happening.

The current auto-advancing pipeline can technically move from phase to phase,
but the retry and observability posture is not production-safe yet. A single
misconfigured phase can spend dollars per attempt, retry immediately, and leave
the operator with only coarse status until the attempt has already failed.

Target operator experience:

- See every active run, phase, attempt, retry, error, and cost from the TUI.
- Know whether a phase is waiting, running, retrying, exhausted, blocked, or
  complete without reading raw JSON.
- Stop automatic retries before the next expensive attempt when failures look
  deterministic.
- Retry at most once automatically by default, and hard-stop or human-gate when
  the same phase hits the same failure kind twice.
- Preserve all recovery evidence and artifacts without silently re-running work.
- Keep phase-session semantics aligned with prepared work-unit decomposition.
- Open a full phase-session run graph from the dashboard instead of hunting
  through raw state files.

## Trigger Run

Investigation target:

`01KQD670S0SGHNE54D0TA7174K`

Important evidence from the run:

- Final successful phase 0 attempt took about 162 seconds, cost about `$0.92`,
  used 16 turns, and produced valid result and handoff artifacts.
- The final success reported valid artifacts, three docs/examples fixture files,
  and five completed work-unit-like IDs invented by the child session.
- Archived failed Claude attempts with stdout accounted for about `$15.56` in
  failed model spend before the successful phase 0 attempt.
- Early archived attempts also show sub-second launcher failures with
  `I/O operation on closed file.` and no captured stdout/stderr cost payload.
- Repeated failure kinds were mostly `outer_json_invalid_no_artifacts` and
  `partial_artifacts_invalid`.
- Current state and run events recorded lifecycle information, but cost and
  token data lived only inside per-attempt `stdout.txt` payloads.

The total picture is worse than a normal flaky retry. Some failures were
launcher plumbing, some were permission/tooling mismatches, and some were the
model misunderstanding the strict artifact contract. Those classes need
different retry behavior.

## Current State

Useful primitives already exist:

- `phase_sessions.v1.json` stores phase status, attempt count, lease metadata,
  launch paths, result paths, handoff paths, attempt history, and retry fields.
- `data/telemetry/run_events.jsonl` records prepare, pump, phase start,
  refresh, abandon, retry-exhausted, adoption, completion, and checkpoint
  events during the run.
- `phase_launches/<phase_id>/attempt-<n>/stdout.txt` stores Claude JSON output,
  including cost, tokens, duration, turn count, and permission denials after
  the child exits.
- `phase_recovery/<phase_id>/attempt-<n>.*` stores stdout/stderr tails,
  diff summaries, and recovery context.
- `bin/swarm phases status <run-id> --json` exposes the current durable
  phase-session state.
- The TUI already has a small phase-session status command that finds the
  latest phase-session run from `run_events.jsonl`.
- The real Claude print launcher is in
  `py/swarm_do/pipeline/phase_pump.py`; `_run_real_claude()` currently calls
  `proc.communicate(input=pending_input, timeout=wait_for)` in a refresh loop.
- `schemas/telemetry/run_events.schema.json` is closed over `event_type`.
  It already includes both `phase_session_blocked` and
  `phase_attempt_retry_exhausted`, so human-gate work does not need a new
  run-event enum.

Current gaps:

- Immediate retry is the default when a result does not supply
  `retry_after_seconds`.
- `short_retry_backoff_seconds` is `0`.
- Deterministic model-contract failures retry the same as transport or launcher
  failures.
- Failure names conflate malformed outer Claude JSON with missing artifact
  pointers and missing contract files.
- Per-attempt cost and token data are not rolled into phase status.
- The TUI shows only coarse phase-session status, not per-attempt evidence, and
  the `2` Runs navigation currently returns to the dashboard instead of opening
  a true run cockpit.
- Phase sessions launch one child per phase, while prepare decomposition can
  create multiple work units per phase.
- Per-attempt `writer-settings.json` files duplicate identical settings.
- Cancel/stop leaves phase-created working tree artifacts on disk without a
  cleanup decision path.
- Recovery currently emits `phase_attempt_retry_exhausted` through
  `mark_retry_exhausted()` when attempts are spent or a hard-stop failure is
  detected. Policy human gates are therefore a behavior change: they must mark
  the phase `blocked` and emit `phase_session_blocked`, not merely reuse a
  pre-existing recovery transition.
- `phase_sessions.v1.json` is also closed-schema. Adding durable
  `blocked_reason`, `retry_policy_decision`, observed cost fields, or attempt
  metric fields requires a `schemas/phase_sessions.schema.json` extension and
  state-normalization defaults.

## Spend Telemetry Reality Check

There are three different kinds of spend data in this repository, and they
must not be treated as equally authoritative.

1. Provider-reported Claude print metrics.

   `phase_launches/<phase_id>/attempt-<n>/stdout.txt` can contain a real
   Claude CLI JSON result with `total_cost_usd`, `usage`, `modelUsage`,
   `duration_ms`, `duration_api_ms`, `num_turns`, and `permission_denials`.
   The trigger run's visible spend numbers come from these payloads: the
   current successful attempt reports `total_cost_usd=0.9203579999999998`, and
   archived stdout payloads for the same run sum to about `$15.56`.

   This is provider-reported telemetry, not a local billing ledger. It is good
   enough for operator visibility and post-attempt guardrails when present, but
   it should be labeled `provider_reported` and never presented as a billing
   source of truth.

2. Swarm-run telemetry rows.

   `bin/swarm-run` intentionally writes `estimated_cost_usd: null`; the
   telemetry schema documents cost and token fields as nullable because they
   are not always observable. `py/swarm_do/telemetry/run_observations.py`
   extracts token usage only when backend output includes structured usage
   objects, and tool-call count only when structured tool-call events are
   present.

3. Static estimates.

   Pipeline budget previews use simple heuristics, currently
   `18_000` tokens and `$0.18` per estimated agent. Context bundles estimate
   prompt tokens as roughly `prompt_bytes / 4`. These are planning estimates,
   useful for dry-run warnings and capacity intuition, not spend accounting.

Guardrail implication:

- Phase 0 should not invent dollars from wall time, tool calls, or byte counts.
- Unknown cost contributes to `unknown_cost_attempt_count`, not `$0.00`.
- Dollar thresholds may gate only on observed provider-reported cost. Attempt
  count, same-failure count, backoff, deterministic failure classification, and
  provider-enforced per-attempt budget caps are the reliable Phase 0 controls.

## Root Causes

### Retry Policy Is Spend-Blind

`phase_recovery._retry_or_exhaust()` defaults missing retry delay to zero and
immediately marks the phase pending again. With `max_session_attempts = 3`, a
single foreground pump can launch three expensive attempts back to back.

This is acceptable for fast local process failures. It is not acceptable for
LLM-bound failures that last 60 to 500 seconds and cost `$0.50` to `$2.50`.
The dangerous case is not only three attempts; it is two identical expensive
failures followed by an automatic third launch before the operator can react.

### Failure Classification Is Too Coarse

Current classification:

- `outer_json_invalid_no_artifacts` is used whenever stdout exists but parsing
  the Claude print payload or extracting artifacts fails.
- `partial_artifacts_invalid` is used when result or handoff files exist but do
  not validate.
- `launcher_nonzero_no_artifacts` shares the retry path with model-contract
  failures.

Those failures do not have the same retry value. A transient nonzero launcher is
plausibly retryable. A valid Claude success that omitted the artifact object, or
schema-invalid artifacts that use the wrong contract shape, is likely to repeat
until the prompt or launcher contract changes.

### Launcher Plumbing Has A Known Fragile Spot

The earliest archived attempts failed in under a second with
`I/O operation on closed file.`. This points at the real-Claude launcher loop
in `py/swarm_do/pipeline/phase_pump.py` that repeatedly calls
`proc.communicate(input=pending_input, timeout=...)` to refresh leases. After
the first timed-out communicate call, stdin handling is fragile.

The launcher needs a safer subprocess pattern for long-running Claude children.

### Permission Surface Is Ambiguous

Several failed attempts include Claude permission denials around file creation.
The final success still logged a denial for a compound command:

`mkdir -p .../phase_results/0 .../phase_handoffs/0 && date -u ...`

The writer allowlist includes `Bash(mkdir:*)`, but compound commands and
multi-command shell forms do not behave like simple `mkdir` calls under
`dontAsk`.

### Work Units Are Not The Execution Unit

Prepare decomposed phase 0 into `unit-0-1`, `unit-0-2`, and `unit-0-3`, but
phase sessions launched one full-phase Claude child. The context renderer
unions work-unit boundaries when no `unit_id` is selected, so the child sees the
whole phase. The successful child reported completed work unit IDs like
`fixture:selftest.ok.json`, not the prepared `unit-0-*` IDs.

This makes decomposition look authoritative while the launcher ignores it.

## Decisions

1. Keep auto-advance, but make retry conservative by default.

   Auto-advance is valuable once the failure classes are separated. The right
   fix is not to delete retries; it is to prevent deterministic failures from
   burning repeated LLM attempts.

2. Retry once by default, then require a human decision for repeated failures.

   The spend fuse should allow at most one automatic retry for a failed phase in
   the default Claude phase-session path. If the same phase sees the same
   `failure_kind` twice, automatic execution must stop even if the configured
   absolute attempt ceiling is higher.

3. Treat model-contract failures as human-gated unless explicitly recoverable.

   `outer_json_*_no_artifacts` and `partial_artifacts_invalid` should stop or
   back off aggressively after one attempt. They are usually prompt/contract
   problems, not transient process problems.

4. Use `blocked` with enumerated policy reasons for human gates.

   Do not add a separate `human_gated` status in the first hardening pass. Reuse
   the existing `blocked` status with a producer-side `BlockedReason` literal
   and detailed retry-policy fields. This avoids run-event enum churn while
   still making policy stops first-class. It does require extending the
   phase-session state schema if those fields are stored durably.

   Parent-produced blocked reasons should be a closed set, initially:
   `retry_policy_human_gate`, `deterministic_contract_failure`,
   `permission_contract_failure`, `operator_cancelled`, and
   `child_reported_blocked`. The child result's free-form `blocked_reason`
   remains human text and should be copied to `last_error`; the TUI must not
   parse that string to infer policy.

5. Keep `retry_exhausted` distinct from `blocked`.

   `retry_exhausted` means the configured retry budget was spent for a failure
   that policy still considered retryable. `blocked` means automation refused
   the next launch because continuing is unsafe, deterministic, operator
   cancelled, or requires human judgment. If multiple terminal states somehow
   coexist in one run, user-facing summaries should prefer active/running,
   retry-waiting, `blocked`/`needs_input`, then `retry_exhausted`, then
   `failed`.

6. Make cost visible before adding more automation.

   A run cockpit and CLI cost rollup are required safety features, not polish.

7. Choose one work-unit execution model for v1.

   In v1, a phase-session child executes a phase, not individual prepared work
   units. Decomposition artifacts may remain available for operator review and
   prompt context, but they must be marked informational in phase-session mode.
   The context renderer must stop silently unioning work-unit boundaries as if
   that were the actual execution model.

8. Make the TUI run cockpit the primary operator path.

   The dashboard should show a compact Phase Sessions section above the in-flight
   issue queue. Pressing `2` or selecting a run should open a full-page run
   cockpit with a phase graph, active/retry/blocked status, cost, attempts, and
   artifact evidence.

9. Prefer durable files over a daemon.

   The existing phase state, events, launch dirs, and stdout payloads are enough
   for TUI visibility and recovery. A daemon can come later if needed.

## Implementation Plan

### Phase 0: Add A Spend Fuse Before More Dogfood

Goal: prevent the known expensive retry loop before deeper observability and UI
work lands.

This is a small, conservative patch that should land before another unattended
multi-phase `--phase-sessions auto` dogfood run.

Changes:

- Set the default Claude phase-session path to one automatic retry at most:
  two attempts total unless an operator or preset explicitly raises the ceiling.
- Stop automatic execution when the same `(phase_id, failure_kind)` occurs
  twice, regardless of the absolute attempt ceiling.
- Do not automatically retry deterministic contract failures:
  `outer_artifacts_missing`, zero-returncode `outer_json_invalid_no_artifacts`,
  schema identity mismatches, path escapes, SHA mismatches, and permission
  contract failures.
- Replace zero-delay retry defaults with a nonzero backoff. The first fallback
  backoff should be at least 60 seconds.
- Count unknown-cost attempts against attempt and same-failure limits. Unknown
  cost must never be interpreted as free.
- When the fuse stops automation, mark the phase `blocked` with
  an enumerated `blocked_reason`, record `retry_policy_decision`, record the
  last failure kind, and surface the recommended inspection command.
- Add a durable parent-side blocked transition, likely
  `mark_phase_blocked()`, instead of overloading `mark_retry_exhausted()`.
  It must set `status=blocked`, emit `phase_session_blocked`, and put policy
  details in run-event `details`.
- Extend `schemas/phase_sessions.schema.json` and state normalization for any
  new durable policy fields, at minimum `blocked_reason`,
  `retry_policy_decision`, and `blocked_at`.
- Do not enforce `max_failed_run_cost_usd` in Phase 0 unless this phase also
  adds minimal provider-reported cost extraction from Claude stdout. The
  preferred Phase 0 scope is count/same-failure/backoff/deterministic-stop
  gating plus optional per-attempt `--max-budget-usd`; the dollar threshold
  lands after the Phase 1 reader.
- If a per-attempt budget is configured, pass it through the existing
  `--max-budget-usd` Claude launcher argument. This is the only guard that can
  cap a single runaway attempt while it is still running. If the provider
  rejects or ignores the flag, record the uncertainty and fall back to the
  count-based fuse.

Tests:

- A repeated `outer_json_invalid_no_artifacts` failure does not launch attempt 3.
- Same failure kind twice produces `blocked` with
  `blocked_reason=retry_policy_human_gate` and
  `retry_policy_decision=same_failure_limit`.
- Unknown cost still counts against retry limits.
- Unknown cost does not add `$0.00` to any failed-spend rollup.
- The first retry is delayed instead of immediately claimable.
- Hard-stop contract failures never schedule a retry.
- Policy stops emit `phase_session_blocked`, not
  `phase_attempt_retry_exhausted`.
- Plain retry-budget exhaustion still produces `retry_exhausted`.

### Phase 1: Normalize Attempt Evidence

Goal: create one canonical reader that joins phase-session state, run events,
launch dirs, recovery files, and Claude stdout metrics.

Add a pure helper module, likely under `py/swarm_do/pipeline/`, that can return
a `run_attempts` summary for a run id:

- run id
- phase id and title
- attempt number
- status
- failure kind
- retry decision
- started/completed timestamps
- elapsed seconds
- launcher return code
- session name
- child pid and process group id
- launch dir
- result and handoff paths
- recovery context paths
- total cost USD
- cost confidence/source, such as `provider_reported`, `unknown`, or
  `archived_provider_reported`
- input/cache-create/cache-read/output tokens
- permission denial count
- stdout/stderr tail paths

Inputs:

- `data/runs/<run_id>/phase_sessions.v1.json`
- `data/telemetry/run_events.jsonl`
- `data/runs/<run_id>/phase_launches/**/stdout.txt`
- `data/runs/<run_id>/phase_recovery/**`
- archived directories when explicitly requested

Rules:

- If `stdout.txt` is absent, show metrics as unknown, not zero.
- If `stdout.txt` is not valid Claude result JSON, preserve parse error.
- Extract dollar cost only from provider-reported fields such as
  `total_cost_usd` or `modelUsage.*.costUSD`. Do not synthesize dollars from
  wall time, turns, prompt bytes, or token heuristics.
- Do not require archived attempts for normal status, but support a diagnostic
  flag to include `.archived-*`.
- Default summaries may report that archived cost exists, but detailed archived
  attempts should be included only when explicitly requested.
- Never fail the entire summary because one attempt payload is unreadable.

Tests:

- Valid Claude stdout produces cost/token rollup.
- Missing stdout keeps attempt visible with unknown metrics.
- Invalid stdout records parse error.
- Archived attempts can be included only when requested.
- If `total_cost_usd` and `modelUsage.*.costUSD` disagree, preserve both and
  mark the attempt as `cost_confidence=conflict` instead of choosing silently.

### Phase 2: Add Cost And Attempt Views To CLI

Goal: make `bin/swarm phases status` useful without opening raw files.

Add CLI options:

- `bin/swarm phases status <run-id> --cost`
- `bin/swarm phases status <run-id> --attempts`
- `bin/swarm phases status <run-id> --events`
- `bin/swarm phases status <run-id> --include-archived`

JSON output should include:

- `cost.total_usd`
- `cost.failed_usd`
- `cost.unknown_attempt_count`
- `cost.archived_provider_reported_usd` when archived attempts exist
- `cost.by_phase`
- `tokens.by_phase`
- `attempts.by_phase`
- `last_failure`
- `last_error`
- `permission_denial_count`
- `recommended_action`

Text output should stay compact:

```text
run 01... status=running cost=$16.48 failed=$15.56
phase 0 complete attempts=1 cost=$0.92
phase 1 running attempts=1 elapsed=...
recent failures:
- phase 0 attempt 3 outer_json_invalid_no_artifacts cost=$0.51 retry_exhausted
```

Tests:

- Text output includes cost when requested.
- JSON output remains backward-compatible when `--cost` is omitted.
- Missing stdout does not report `$0.00` as if the attempt was free.
- Archived attempts are summarized without detailed attempt rows unless
  `--include-archived` is present.

### Phase 3: Classify Retry Decisions By Failure Kind

Goal: replace immediate retry with policy-driven retry decisions.

Add a retry policy table whose entries include:

- failure kind
- maximum automatic retries
- same-failure limit
- backoff profile
- spend guard participation
- terminal action
- recommended operator action

Initial policy:

| Failure kind | Auto retry | Terminal action |
| --- | --- | --- |
| `launcher_nonzero_no_artifacts` | one retry with normal backoff | `blocked` if same failure kind repeats |
| `lease_expired_no_artifacts` | one retry after process liveness check | `blocked` if same failure kind repeats |
| `claude_print_timeout` | one retry unless artifacts are adoptable | `blocked` after repeat timeout |
| `outer_json_missing_no_artifacts` | one retry with backoff | `blocked` after repeat |
| `outer_json_invalid_no_artifacts` with return code 0 | no automatic retry | `blocked` with `retry_policy_human_gate` |
| `outer_json_invalid_no_artifacts` with nonzero return code | one retry with backoff | `blocked` after repeat |
| `outer_artifacts_missing` with return code 0 | no automatic retry | `blocked` with `retry_policy_human_gate` |
| `partial_artifacts_invalid` | one recovery retry only when changed files or partial artifacts suggest salvage | `blocked` otherwise |
| schema identity failures | no retry | `blocked` with hard-stop reason |
| path escape and SHA mismatch failures | no retry | `blocked` with hard-stop reason |
| permission contract failures | no retry | `blocked` with operator-facing permission guidance |

Same-failure rule:

- If the same phase records the same `failure_kind` twice, automatic execution
  must stop before another launch.
- This rule applies even if cost is unknown and even if
  `max_session_attempts` is higher than two.

Add default backoff:

- failure after attempt 1, before attempt 2: 60 seconds
- failure after attempt 2, before attempt 3: 180 seconds
- failure after attempt 3, before attempt 4: 600 seconds
- maximum: existing `max_retry_after_seconds`

Under the default Phase 0 ceiling of two total attempts, only the 60-second
fallback is normally reachable. The later entries are for explicit higher
ceilings.

Add spend guardrails:

- `max_failed_attempt_cost_usd` per phase, evaluated after an attempt exits
- `max_failed_run_cost_usd`
- `max_consecutive_same_failure_kind`
- `max_phase_attempt_budget_usd`, forwarded to Claude as `--max-budget-usd`
  before the attempt starts when configured

Recommended dogfood default:

- `max_failed_run_cost_usd = 2.00`
- `max_phase_attempt_budget_usd = 1.50` for unattended Claude dogfood, unless
  the operator explicitly opts into a larger phase
- preset or environment override allowed for explicit high-risk runs
- threshold violations block the next launch before it is claimed

Cost guard semantics:

- Known failed cost uses provider-reported values only.
- Unknown cost contributes to `unknown_cost_attempt_count`, not to a fabricated
  dollar value.
- Unknown cost still counts against attempt and failure-kind limits.
- If any failed attempt has unknown cost, the status and TUI should show that
  dollar threshold enforcement is incomplete for that run.

Tests:

- Deterministic model-contract failure is not immediately retried.
- Transport-like failure schedules backoff.
- Same failure kind twice becomes `blocked` with a structured policy reason.
- Spend threshold prevents another launch.
- Existing `retry_after_seconds` remains honored and clamped.
- Dogfood failed-spend threshold defaults to `$2.00` unless explicitly
  configured otherwise.
- Unknown-cost attempts are visible in the spend summary and do not pass or
  fail the dollar threshold as `$0.00`.

### Phase 4: Make Human-Gated Stops First-Class

Goal: stop using retry exhaustion as the only way to interrupt automation.

Use the existing `blocked` phase status for policy stops.

Do not add a new `human_gated` phase status in this hardening pass. The schema
is already closed over phase statuses, and `blocked` is the right user-facing
meaning: automation cannot safely continue without operator input. The
run-event schema is also closed, but already has the required
`phase_session_blocked` event. The phase-session state schema must still be
extended for any new durable policy fields.

The state must include:

- failure kind
- last error
- attempt count
- launch dir
- cost spent so far
- recommended command
- reason auto-retry was refused
- enumerated `blocked_reason`
- `retry_policy_decision`, such as `same_failure_limit`, `spend_threshold`, or
  `deterministic_contract_failure`

Run events should reuse the existing closed-schema event:

- Emit `phase_session_blocked`.
- Set `reason` to the same enumerated blocked reason.
- Put detailed policy fields in `details`.

Precedence with existing `retry_exhausted`:

- Use `blocked` when policy refuses another launch before the configured
  retry budget would otherwise be spent, or when a deterministic/hard-stop
  condition means retrying is unsafe.
- Use `retry_exhausted` only when a retryable failure consumed the configured
  attempt budget.
- `phase_status()`, resume, Beads notes, and the TUI must share the same
  precedence: running/leased, retry waiting, blocked/needs input,
  retry exhausted, failed, ready/waiting.

Recovery notes and Beads notes may use human-readable labels such as
`phase_human_gated`, but durable run events should avoid a new enum unless a
later migration proves it is needed.

Tests:

- Human-gated phase appears in status and resume output.
- TUI latest phase-session reader does not treat it as drift.
- Run-event schema validates.
- `phase_session_blocked` with `reason=retry_policy_human_gate` appears in the
  attempt summary and TUI event strip.
- `phase_session_blocked` and `phase_attempt_retry_exhausted` remain distinct
  in event history and summaries.

### Phase 5: Harden The Claude Launcher

Goal: remove the sub-second launcher failure class and reduce permission
friction.

Launcher changes:

- In `py/swarm_do/pipeline/phase_pump.py`, replace the repeated
  `communicate(input=..., timeout=...)` loop in `_run_real_claude()` with a
  safer pattern that writes stdin once, closes stdin, then polls or uses
  non-blocking readers while refreshing the lease.
- Always persist stdout and stderr on exceptions when available.
- Classify the `I/O operation on closed file.` path as a launcher bug, not a
  model failure.
- Add an integration-style fake process test for timeout, refresh, and stdin
  close behavior.

Permission changes:

- Avoid asking child Claude to create result/handoff directories with shell
  commands when the parent already knows the paths. Parent should create those
  directories before launch.
- Keep final child shell commands simple and single-purpose.
- Do not rely on compound `&&` forms being covered by `Bash(mkdir:*)`.
- Do not add a separate live Claude preflight unless it is explicitly counted
  and capped. Verifying `Write` and `Edit` inside a `dontAsk` session is itself
  a Claude launch; prefer non-spend parent setup first, and if a live preflight
  is later required, run it with a tiny `--max-budget-usd` and record it as an
  attempt-like spend source.

Tests:

- Long-running fake Claude gets prompt once and refreshes leases.
- Timeout captures stdout/stderr.
- Parent creates phase result and handoff directories before child launch.
- Command metadata records launcher bug failures distinctly.

### Phase 6: Resolve Work-Unit Semantics

Goal: make decomposition and execution agree.

Chosen v1 simplification:

- When `--phase-sessions auto` is enabled, prepared work-unit sidecars are
  informational unless the launcher is explicitly running in a future work-unit
  scheduler mode.
- The phase-session execution unit is the phase.
- Render phase-session prompts from phase text and prior handoffs, not from a
  silent union of prepared work-unit file scopes.
- If work-unit sidecars exist, include them under an explicitly labeled
  "informational decomposition" section.
- Keep the existing `completed_work_units` schema field for compatibility, but
  require values to be empty or a subset of prepared unit IDs. Semantic
  accomplishments invented by the child should be represented in `summary`,
  `artifacts`, `validation`, or a future schema field such as
  `completed_work_items`.
- Apply this enforcement prospectively. Existing run artifacts already contain
  non-prepared values such as `fixture:selftest.ok.json`; readers should load
  them as legacy evidence with a contract warning rather than marking the whole
  historical run as drift.
- Prepared artifact validation remains strict for non-phase-session dispatch.

Alternative v2:

- Make phase sessions queue work units.
- Add `phase_id`, `work_unit_id`, and dependency edges to session state.
- Launch one child per ready unit.
- Aggregate unit result and handoff artifacts into a phase handoff.

Recommendation:

Ship the v1 simplification first. It removes the current foot-gun without
building a second scheduler.

Tests:

- A phase-session run does not report prepared work-unit IDs unless it launched
  those units.
- Context bundle does not silently union work-unit boundaries in phase-session
  mode without an explicit mode marker.
- Prepared artifact validation remains strict for non-phase-session dispatch.
- Existing accepted prepared artifacts with work-unit sidecars remain readable.
- Existing phase result artifacts with legacy `completed_work_units` values
  remain readable and are flagged as legacy/nonconforming instead of migrated
  in place.
- Phase-session context can render a phase prompt even when work-unit sidecars
  are absent or marked informational.

### Phase 7: Build The TUI Run Cockpit

Goal: give the operator live visual access to phase-session runs.

Add a real Runs screen and a compact Dashboard entry point backed by the Phase 1
summary helper. The current `2` navigation should stop returning to the
dashboard and should open this run-focused surface.

Dashboard integration:

- Add a "Phase Sessions" section above the existing in-flight issue queue.
- Show active and recent phase-session runs by default.
- Include run id, overall status, active phase, attempt count, failed cost, last
  failure, and updated time.
- Selecting a row or pressing enter opens the full run cockpit.
- Keep the existing issue queue for Beads-backed in-flight workers.
- Show `bd_epic_id` when present, but do not run `bd list` on the 2-second
  refresh path. Use durable run state and run events for polling; call Beads
  only on explicit open or a slower cached refresh.
- Poll durable files every 2 seconds using the current dashboard cadence.

Full-page run cockpit:

- Top band: run id, Beads epic id when present, overall status, active phase,
  total cost, failed cost, unknown-cost attempt count, attempts, and last
  failure.
- Center: phase graph derived from `phase_sessions.v1.json`, not from the active
  preset graph.
- Bottom panel: selected phase details, attempt list, retry decision, backoff
  countdown, last error, cost/token rollup, and artifact paths.
- Drawer or focused detail pane: selected attempt stdout/stderr tail, return
  code, permission denials, result path, handoff path, recovery context path, and
  launch command metadata.

Phase graph design:

- Nodes are phases from durable phase-session state.
- Edges come from `depends_on_phase_ids`.
- Layout uses the existing layer-board visual language where possible.
- Statuses include waiting, running, retrying, exhausted, blocked, needs input,
  operator-cancelled, and complete. Operator-cancelled may be rendered as a
  `blocked` phase with `blocked_reason=operator_cancelled` unless a later schema
  migration adds a distinct durable status.
- The UI must read `blocked_reason` and `retry_policy_decision` fields directly.
  It must not infer policy states by parsing free-form `last_error` or child
  `blocked_reason` strings.
- The active phase may pulse or blink, but blinking must never be the only
  status indicator. Use labels/classes/badges as the accessible source of truth.
- If a phase is retrying, show the countdown near the node and in the detail
  panel.

Run list columns:

- run id
- status
- active phase
- completed phases
- attempts
- failed attempts
- failed cost
- total cost
- last failure
- updated at

Selected run detail:

- phase timeline
- per-phase status table
- current attempt metadata
- retry/backoff countdown
- last error
- permission denial count
- cost and token rollup
- links/paths for stdout, stderr, result, handoff, and recovery context

Attempt drawer:

- attempt number
- duration
- return code
- failure kind
- retry decision
- cost
- token breakdown
- permission denials
- stdout tail
- stderr tail
- recovery context path

Event strip:

- recent `run_events` for the selected run
- show lifecycle events as they arrive
- highlight `phase_attempt_abandoned`, `phase_attempt_retry_exhausted`,
  `phase_session_blocked`, `phase_session_needs_input`, policy gates, and cost
  thresholds

Tests:

- Pure state helpers summarize a run with running, retrying, exhausted, and
  complete phases.
- Missing launch stdout does not break the Runs screen.
- Latest phase-session status still works when no runs exist.
- Snapshot-style tests cover compact text rendering for narrow terminals.
- Pressing `2` opens the Runs screen rather than returning to Dashboard.
- Dashboard Phase Sessions rows open the selected run cockpit.
- Phase graph status remains understandable without blink/pulse styling.
- Beads commands are invoked only for explicit open actions, not every refresh.

### Phase 8: Add Cleanup And Cancel Visibility

Goal: make cancel/stop leave a visible and recoverable state.

Add cancel behavior:

- Mark active phase `blocked` with `blocked_reason=operator_cancelled` unless a
  later schema migration deliberately adds a distinct `cancelled` status.
- Preserve launch evidence.
- Record whether child process was alive and whether kill was attempted.
- Write `phase_session_blocked` with `reason=operator_cancelled`.
- Surface untracked files created by completed or partial phase attempts.

Add cleanup guidance:

- List untracked artifacts grouped by phase.
- Offer explicit commands for "keep", "remove generated phase artifacts", and
  "archive run evidence".
- Do not automatically delete docs or source artifacts on cancel.

Tests:

- Cancel records a durable event and status.
- TUI shows cancel state and untracked artifact list.
- Cleanup command refuses to delete files outside the run or generated artifact
  allowlist.
- The run-event schema validates without adding a new cancel enum.

### Phase 9: De-Duplicate Writer Settings

Goal: reduce per-attempt file proliferation without changing behavior.

Move stable writer settings to:

`data/runs/<run_id>/writer-settings.json`

Attempt metadata should record the shared settings path and settings SHA.

Keep compatibility:

- Existing attempts with per-attempt settings remain readable.
- New attempts use the shared settings file.

Tests:

- New launches point at run-level settings.
- Existing launch metadata remains parseable.
- Settings changes between attempts update the shared file SHA.

## Acceptance Criteria

- Before another unattended multi-phase dogfood run, the spend fuse prevents a
  third launch after two matching failure kinds.
- Default auto-retry allows at most one retry for a failed Claude phase session.
- A run with repeated model-contract failures does not immediately launch three
  expensive retries.
- Policy gates produce `blocked`; normal retry budget exhaustion still produces
  `retry_exhausted`.
- Unknown-cost attempts are shown as unknown, never as `$0.00` and never as a
  fabricated dollar estimate.
- `bin/swarm phases status <run-id> --cost --attempts` surfaces failed spend,
  total spend, unknown-cost attempts, last failure kind, and retry decision.
- The dashboard shows active/recent phase-session runs above the issue queue.
- Pressing `2` opens a real Runs screen.
- The full run cockpit shows the phase graph, per-phase status, attempts, retry
  waits, errors, artifact evidence, and cost rollups.
- Launcher stdin handling no longer produces `I/O operation on closed file.`
  under the fake long-running process test.
- Permission-denied shell setup commands are removed or isolated so successful
  paths do not carry avoidable denials.
- Phase-session mode has documented and enforced work-unit semantics.
- Operator-cancelled runs preserve evidence and show cleanup options.

## Rollout Order

1. Spend fuse: one automatic retry, same-failure hard stop, and nonzero backoff.
2. Attempt evidence reader and CLI cost/attempt view.
3. Full retry policy classification, blocked human gates, and spend thresholds.
4. Launcher stdin and permission hardening.
5. Work-unit semantics simplification and artifact contract prompt cleanup.
6. TUI dashboard Phase Sessions section, real Runs screen, and run cockpit graph.
7. Cancel cleanup visibility.
8. Writer settings de-duplication.

Step 1 must land before any more unattended dogfood of multi-phase
`--phase-sessions auto` runs. Steps 1 through 3 are the spend-containment layer
and should land before extending automation behavior. Step 8 is trailing
optional; it reduces artifact noise but does not block the spend fuse, launcher
hardening, or run cockpit.

## Resolved Review Decisions

- Policy stops use `blocked` with an enumerated `blocked_reason`, not a new
  `human_gated` status.
- `retry_exhausted` remains a distinct terminal state for normal retry-budget
  exhaustion.
- The run-event schema path is `schemas/telemetry/run_events.schema.json`; its
  `event_type` enum already includes `phase_session_blocked` and
  `phase_attempt_retry_exhausted`.
- The real Claude launcher target is `_run_real_claude()` in
  `py/swarm_do/pipeline/phase_pump.py`.
- The dogfood default failed-spend threshold is `$2.00` after the Phase 1
  provider-reported cost reader exists, with explicit preset or environment
  override for high-risk runs. Phase 0 should not fabricate cost to enforce
  this threshold.
- Default cost rollups summarize archived provider-reported cost when archives
  exist, but detailed archived attempt rows require `--include-archived`.
- Phase-session mode keeps decomposition artifacts informational in v1; it does
  not execute prepared work units.
- The parent creates known result/handoff directories before launch. The child
  still writes validated result and handoff files in v1, while parent-written
  artifacts from final inline JSON remain a future simplification.

## Open Questions And Recommendations

- Where should the dogfood failed-spend threshold override live first: preset
  config, environment variable, CLI flag, or all three?

  Recommendation: support CLI and environment first for dogfood speed, then add
  preset schema once Phase 3 hardens policy. CLI should win over environment,
  which wins over preset/default.

- What does unknown cost contribute toward `max_failed_run_cost_usd`?

  Recommendation: no numeric contribution. Track it as unknown and count the
  attempt against attempt/failure-kind limits. Do not estimate dollars from
  time, turns, tool calls, token heuristics, or prompt bytes for gating.

- Should Phase 0 inline minimal cost extraction?

  Recommendation: keep Phase 0 count-first unless the extractor is tiny and
  provider-reported only. The important Phase 0 fuse is same-failure and attempt
  gating; post-attempt dollar gating should wait for the Phase 1 summary reader.

- Does the Phase 3 backoff schedule conflict with Phase 0's default two-attempt
  ceiling?

  Recommendation: no conflict if documented as a schedule for raised ceilings.
  Under default settings only the 60-second retry delay is reachable.

- How should existing nonconforming `completed_work_units` values be handled?

  Recommendation: treat historical values as legacy evidence with warnings.
  Enforce subset-of-prepared-unit-ids only for new phase-session artifacts after
  Phase 6 lands.

- Is Phase 9 required for rollout?

  Recommendation: no. Keep writer-settings de-duplication as trailing optional;
  it should not block spend containment or launcher hardening.

- Should Phase 5 add a live permission preflight?

  Recommendation: avoid a standalone Claude preflight in the first pass. Parent
  directory creation and simpler child commands remove most friction without
  spending. If a later live preflight is needed, cap it with `--max-budget-usd`
  and count it as attempt-like spend.

- How much stdout/stderr should the TUI attempt drawer show inline before it
  switches to path/copy-only behavior?
- Should the run cockpit eventually include a read-only Beads epic/task list
  from cached `bd` output, or should Beads stay explicit-action-only?
- Should a later schema migration add distinct durable statuses for
  `human_gated` and `cancelled`, or is `blocked` plus enumerated reason enough?

## Non-Goals

- No daemon requirement.
- No live token streaming from Claude unless the provider exposes a reliable
  machine-readable stream.
- No automatic deletion of generated source/docs files on cancel.
- No parallel phase execution in this plan.
- No per-work-unit scheduler in the first hardening pass.
