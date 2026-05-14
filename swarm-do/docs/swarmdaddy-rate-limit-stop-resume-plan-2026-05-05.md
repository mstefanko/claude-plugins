# SwarmDaddy Rate-Limit Stop/Resume Plan

Status: ready for implementation
Date: 2026-05-05
Run-of-record: `01KQSDTRN4HFRRXAVARE8X0QNZ` phase 4
Companion plans:
- `docs/fanout-foundations-fix-plan-2026-05-04.md`
- `docs/phase-session-dispatcher-fanout-plan-2026-05-03.md`
- `docs/failure-taxonomy.md`

> **Session continuity.** This plan assumes a fresh implementer has not seen the
> live failure. The important part is not "retry harder"; it is "classify the
> 429 before normal stage finalization corrupts the failure kind, preserve
> everything durable, and resume only unfinished units with fresh agents."

---

## 1. Problem Statement

In the fanout run `01KQSDTRN4HFRRXAVARE8X0QNZ`, phase 4 hit an API 429 after
burning roughly `$5.55` in the dispatcher session. Claude emitted quota signals
in the stream, including `rate_limit_event` frames and a final result carrying
`api_error_status: 429`, but SwarmDaddy normalized the phase as a child-result
contract failure:

```text
failure_kind: NORMALIZATION_ERROR
failure_operator_message: A dispatched sub-agent result could not be normalized
```

That is the wrong operator story. The real root cause was a provider rate limit,
not malformed child work. The practical impact:

- live sub-agent processes do not reliably resume after the outer dispatcher
  returns;
- dirty unit worktrees, stage result files, command metadata, and adoption
  journals do survive;
- valid already-written artifacts can be adopted;
- unresolved in-flight unit work must be redispatched with fresh agents;
- the controller currently risks turning an "empty 429" into
  `NORMALIZATION_ERROR`, which can waste usable work and hide the reset time.

Target behavior:

1. Detect hard provider rate limits as first-class runtime signals.
2. Stop launching new work when a hard 429 is known.
3. Preserve completed/adoptable work.
4. Leave unresolved in-flight work pending/retryable, not malformed.
5. Park the phase until the provider reset time, or optionally redispatch the
   unfinished units through a compatible fallback model/provider.

---

## 2. Current Local Behavior

### 2.1 Claude stream parser drops quota frames

`py/swarm_do/pipeline/claude_stream.py` currently recognizes only:

- assistant text;
- final result frames;
- malformed frames;
- ignored frame counters.

Every other frame type is counted as ignored. In the failed run, that means
`rate_limit_event` appeared only as an ignored frame type, not as structured
rate-limit evidence.

Relevant surface:

- `py/swarm_do/pipeline/claude_stream.py`
- `py/swarm_do/pipeline/tests/test_claude_stream.py`

### 2.2 The taxonomy already has the right failure kind

`RETRYABLE_RATE_LIMIT` already exists in `failure_taxonomy.py` and
`docs/failure-taxonomy.md`. The missing piece is not the taxonomy; it is getting
the launcher and stage controller to prefer hard 429 evidence over later
normalization failures.

Relevant surface:

- `py/swarm_do/pipeline/failure_taxonomy.py`
- `docs/failure-taxonomy.md`

### 2.3 Stage finalization can convert the phase to normalization failure

`StageMarkerProcessor.finish()` calls `_fail_unresolved_pending_markers()`
before computing the terminal summary. That behavior is correct for ordinary
marker/result contract failures, but wrong after a hard provider abort: in-flight
units did not necessarily fail their contract; the provider stopped the parent
dispatcher before the controller could receive or normalize all child outputs.

Relevant surface:

- `py/swarm_do/pipeline/stage_controller.py`
- `py/swarm_do/pipeline/tests/test_stage_controller.py`
- `py/swarm_do/pipeline/tests/test_dispatcher_fanout.py`

### 2.4 Recovery already knows how to wait and retry

`phase_recovery.py` already handles `STATUS_RETRY_WAITING`, `next_retry_at`, and
`retry_after_seconds`. `stage_controller.py` already has
`resume_stage_adoption_journals()` and `retry_failed_units()`.

Those are the right foundations. The plan should wire rate-limit detection into
them rather than build a parallel resume system.

Relevant surface:

- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/stage_controller.py`

---

## 3. External Research Summary

No researched project exposes a reliable "Claude quota remaining" preflight.
The useful patterns are: classify 429 explicitly, persist retry health, preserve
artifacts, and retry at a clean boundary.

### 3.1 MCO

MCO has the strongest runtime posture:

- explicit error taxonomy including retryable rate limits;
- retries for `rate limit` / `429` matches;
- exponential backoff;
- raw stdout/stderr/run artifacts;
- session retries with partial output preserved.

Useful sources:

- [MCO README: health, usage tracking, session retry](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/README.md#L117-L134)
- [MCO README: retry/resilience and artifacts](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/README.md#L530-L552)
- [MCO error classifier](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/runtime/errors.py#L17-L26)
- [MCO orchestrator retry set](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/runtime/orchestrator.py#L11-L15)
- [MCO retry loop](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/runtime/orchestrator.py#L90-L108)
- [MCO session retry loop](https://github.com/mco-org/mco/blob/85045cab8676cc0ee33a36aa02420e6e67761fb8/runtime/session/daemon.py#L159-L236)

Limit for our case: MCO mostly classifies stderr/text. Our failure was visible
in Claude stream JSON frames, so SwarmDaddy needs stream-native detection first
and text matching only as fallback.

### 3.2 Metaswarm

Metaswarm does not appear to have Claude subscription quota introspection, but
it has good orchestration practices:

- per-dispatch external-tool health checks;
- durable BEADS context recovery;
- work-unit retry loops;
- `rate_limited` treated as transient;
- adapters that capture raw output and emit structured envelopes;
- escalation to another tool/model when a tool is unavailable.

Useful sources:

- [Metaswarm README: workflow and context recovery](https://github.com/dsifry/metaswarm/blob/c86fd6c422a8ddb3d5a0524d2acb784359c25b05/README.md#L7-L21)
- [Metaswarm work-unit loop](https://github.com/dsifry/metaswarm/blob/c86fd6c422a8ddb3d5a0524d2acb784359c25b05/skills/start/SKILL.md#L141-L163)
- [Metaswarm external-tool health checks](https://github.com/dsifry/metaswarm/blob/c86fd6c422a8ddb3d5a0524d2acb784359c25b05/skills/external-tools/SKILL.md#L105-L118)
- [Metaswarm rate-limited handling](https://github.com/dsifry/metaswarm/blob/c86fd6c422a8ddb3d5a0524d2acb784359c25b05/skills/external-tools/SKILL.md#L306-L329)
- [Metaswarm adapter classifier](https://github.com/dsifry/metaswarm/blob/c86fd6c422a8ddb3d5a0524d2acb784359c25b05/skills/external-tools/adapters/_common.sh#L129-L179)

Limit for our case: the rate-limit handling is mostly adapter text matching,
not parent Claude stream handling.

### 3.3 Superpowers

Superpowers does not appear to guard rate limits directly. Its relevant lesson
is execution shape:

- fresh subagent per task;
- explicit terminal statuses;
- isolated worktrees;
- blocked/failure handling by changing context, model, or task size.

Useful sources:

- [Superpowers README: subagent workflow](https://github.com/obra/superpowers/blob/f2cbfbefebbfef77321e4c9abc9e949826bea9d7/README.md#L154-L170)
- [Superpowers subagent statuses](https://github.com/obra/superpowers/blob/f2cbfbefebbfef77321e4c9abc9e949826bea9d7/skills/subagent-driven-development/SKILL.md#L8-L14)
- [Superpowers blocked handling](https://github.com/obra/superpowers/blob/f2cbfbefebbfef77321e4c9abc9e949826bea9d7/skills/subagent-driven-development/SKILL.md#L104-L120)
- [Superpowers worktree guidance](https://github.com/obra/superpowers/blob/f2cbfbefebbfef77321e4c9abc9e949826bea9d7/skills/using-git-worktrees/SKILL.md#L8-L13)

This supports SwarmDaddy's correct resume model: do not expect live children to
come back; redispatch fresh agents over durable worktrees and artifacts.

### 3.4 Everything Claude Code

Everything Claude Code has useful adjacent patterns:

- provider-level `RateLimitError`;
- Claude/OpenAI provider adapters mapping `429`/rate-limit text;
- MCP health state with `nextRetryAt`;
- pre-tool blocking while unhealthy;
- save/resume/checkpoint commands;
- model fallback examples for quota-bound batch work.

Useful sources:

- [ECC LLM error classes](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/src/llm/core/interface.py#L33-L52)
- [ECC Claude provider 429 mapping](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/src/llm/providers/claude.py#L88-L96)
- [ECC MCP health error detection](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/scripts/hooks/mcp-health-check.js#L27-L37)
- [ECC MCP nextRetryAt state](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/scripts/hooks/mcp-health-check.js#L211-L227)
- [ECC MCP pre-tool block](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/scripts/hooks/mcp-health-check.js#L486-L499)
- [ECC model fallback guidance](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/docs/zh-CN/skills/data-scraper-agent/SKILL.md#L48-L57)
- [ECC fallback-on-429 example](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/docs/zh-CN/skills/data-scraper-agent/SKILL.md#L224-L260)
- [ECC save-session](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/commands/save-session.md#L101-L105)
- [ECC resume-session](https://github.com/affaan-m/everything-claude-code/blob/841beea45cb25ba51f29fa45b7e272938d19b80a/commands/resume-session.md#L50-L90)

Limit for our case: provider adapters mostly use exception/text matching. We
need that as a fallback, but the primary signal is still Claude stream JSON.

---

## 4. Decision

Adopt a rate-limit-aware stop/resume path inside the existing phase-session
controller.

Do not add a second scheduler. Do not try to live-resume subagents. Do not treat
the final empty 429 as a result-normalization problem.

The controller should use this precedence order when a phase attempt ends:

1. Hard provider rate-limit evidence from stream JSON or final result.
2. Explicit child failure kind from valid child result.
3. Artifact/contract validation failure.
4. Launcher fallback/text classification.
5. Unknown/normalization failure.

This makes `RETRYABLE_RATE_LIMIT` win over later invalid/missing stage-result
noise caused by the provider abort.

---

## 5. Data Contract

Add a small structured rate-limit signal. Exact field names can move during
implementation, but this is the intended shape.

```json
{
  "schema_version": 1,
  "provider": "claude",
  "model": "unknown-or-model-id",
  "scope": "run|phase|launcher",
  "status": "none|warning|rejected",
  "hard_limit": true,
  "warning_only": false,
  "signal_source": "rate_limit_event|final_result|stderr|stdout|cached_state",
  "api_error_status": 429,
  "message": "You've hit your limit",
  "utilization": 0.93,
  "reset_at": "2026-05-05T17:50:00-04:00",
  "retry_after_seconds": 1200,
  "first_seen_at": "2026-05-05T17:29:59Z",
  "last_seen_at": "2026-05-05T17:30:10Z"
}
```

Persist the signal in three places:

- phase launch `command.json` under `rate_limit`;
- phase result/handoff when an attempt parks or fails due to rate limit;
- run/provider-level cache, for example
  `<run-dir>/rate_limits.v1.json`, so preflight can block the next attempt
  before another expensive launcher starts.

`retry_after_seconds` should be derived from an absolute `reset_at` when
available. Existing retry policy clamps requested delays to 1800 seconds; for
provider reset windows, prefer storing absolute `next_retry_at` and avoid losing
longer real reset windows to the generic cap.

---

## 6. Implementation Plan

### Phase 0: Lock in fixtures and current failure

Goal: make the "empty 429 becomes normalization error" failure reproducible in
tests before changing behavior.

Work:

1. Add Claude stream fixtures under the existing stream test fixture location:
   - allowed warning only;
   - hard rejected `rate_limit_event`;
   - final result frame with `api_error_status: 429` and empty/minimal result;
   - text-only fallback containing `429` or `rate limit`.
2. Add a failing regression test that simulates:
   - two stages adopted;
   - three stages pending/in-flight;
   - final Claude result is a hard 429;
   - current behavior would produce `NORMALIZATION_ERROR`.
3. Record the expected future behavior in the test name and assertion comments.

Files:

- `py/swarm_do/pipeline/tests/test_claude_stream.py`
- `py/swarm_do/pipeline/tests/test_phase_pump_streaming.py`
- `py/swarm_do/pipeline/tests/test_dispatcher_fanout.py`

Acceptance:

- The new tests fail on current main for the reason this plan describes.

### Phase 1: Parse and classify rate-limit signals

Goal: make the launcher see hard quota evidence before stage finalization.

Work:

1. Extend `ClaudeStreamParser` to collect structured rate-limit metadata:
   - count of `rate_limit_event` frames;
   - last/most severe status: `allowed_warning`, `rejected`, or unknown;
   - reset timestamp from fields such as `resetsAt`;
   - utilization when present;
   - raw final result `api_error_status` and `is_error` fields.
2. Keep unknown frames tolerant. Do not break stream parsing if Anthropic changes
   the event payload shape.
3. Add `py/swarm_do/pipeline/rate_limits.py` with a classifier:

```python
def classify_rate_limit(
    *,
    stream_metadata: Mapping[str, Any],
    final_result_frame: Mapping[str, Any] | None,
    returncode: int | None,
    stdout_tail: str,
    stderr_tail: str,
    now: datetime | None = None,
) -> RateLimitSignal:
    ...
```

4. Classifier rules:
   - hard limit if any stream event has rejected status;
   - hard limit if final result has `api_error_status == 429`;
   - hard limit if final result/text says 429/rate limit and return code is
     non-zero;
   - warning only for allowed-warning/high-utilization events;
   - parse reset time into `reset_at` and derive `retry_after_seconds`;
   - never classify a mere warning as a failed phase by itself.
5. Store the classifier output into `metadata["rate_limit"]` and
   `metadata["stream_metadata"]["rate_limit"]`.

Files:

- `py/swarm_do/pipeline/claude_stream.py`
- `py/swarm_do/pipeline/rate_limits.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/tests/test_claude_stream.py`
- `py/swarm_do/pipeline/tests/test_phase_pump_streaming.py`

Acceptance:

- Stream fixtures expose structured rate-limit metadata.
- The final empty 429 fixture classifies as `hard_limit=True`.
- Warning-only fixtures do not fail the phase.

### Phase 2: Stop safely on hard 429

Goal: prevent normal stage finalization from turning a provider abort into
`NORMALIZATION_ERROR`.

Work:

1. Add an abort-aware finalization path to `StageMarkerProcessor`:

```python
summary = processor.finish(abort_reason="rate_limit", rate_limit=signal)
```

or, if a smaller change is cleaner:

```python
summary = processor.snapshot_for_abort(abort_reason="rate_limit", rate_limit=signal)
```

2. The abort path must:
   - run `_retry_pending()` so already-written result files can still adopt;
   - not call `_fail_unresolved_pending_markers()` for the rate-limit abort;
   - leave unresolved stages pending/retryable;
   - mark affected unit stages with `failure_kind=RETRYABLE_RATE_LIMIT` only
     when a retry marker is needed for redispatch;
   - use `record_stage_retry_requested(..., fresh_reviewer=True)` or the local
     equivalent for retry-target unit stages;
   - preserve adopted work units;
   - compute retry target work units from pending/in-flight or retryable failed
     stages;
   - include `terminal_state=RETRYABLE_RATE_LIMIT` or equivalent metadata.
3. In `_run_real_claude`, after stream drain and before `processor.finish()`,
   classify the final stream. If `hard_limit=True`, call the abort-aware path.
4. Write a phase result/handoff with:
   - `status: failed` or `retry_waiting` as the surrounding recovery contract
     requires;
   - `failure_kind: RETRYABLE_RATE_LIMIT`;
   - `retryable: true`;
   - `retry_after_seconds` and/or `next_retry_at`;
   - `preserved_work_units`;
   - `retry_target_work_units`;
   - path pointers for dirty unit worktrees and partial result files.
5. In `phase_recovery._failure_kind_for_unit()` and
   `_launcher_failure_kind()`, prefer `metadata.rate_limit.hard_limit` and
   result `failure_kind=RETRYABLE_RATE_LIMIT` over
   `rejected_invalid_result -> NORMALIZATION_ERROR`.

Files:

- `py/swarm_do/pipeline/stage_controller.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_artifact_contract.py` if result/handoff schema
  needs new fields
- `py/swarm_do/pipeline/tests/test_stage_controller.py`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`
- `py/swarm_do/pipeline/tests/test_dispatcher_fanout.py`

Acceptance:

- A hard 429 after partial adoption yields `RETRYABLE_RATE_LIMIT`, not
  `NORMALIZATION_ERROR`.
- Adopted units remain adopted.
- Pending/in-flight units become retry targets.
- The operator can see reset time and preserved work.

### Phase 3: Add durable provider/run preflight

Goal: avoid starting another expensive launcher while the provider is known to
be unavailable.

Work:

1. Add run-level rate-limit state:

```text
<run-dir>/rate_limits.v1.json
```

2. Store one record per provider/model/scope with:
   - provider;
   - model;
   - last 429 time;
   - reset time;
   - next retry time;
   - signal source;
   - last warning utilization;
   - phase/attempt/run pointers.
3. Add a preflight before phase launch:
   - if now is before `next_retry_at`, do not start Claude;
   - return/record `STATUS_RETRY_WAITING`;
   - surface the wait in resume/status output.
4. Add a soft-warning behavior:
   - warning-only events should not abort current work;
   - if utilization is high enough, avoid starting the next wave/phase unless
     explicitly forced;
   - record advisory warnings in command metadata and run events.
5. Integrate with existing `phase_recovery` retry waiting logic rather than
   adding a separate sleep loop.

Files:

- `py/swarm_do/pipeline/rate_limits.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- CLI/status rendering surface that reports retry waiting
- tests under `py/swarm_do/pipeline/tests/`

Acceptance:

- A second `swarm do --prepared` invocation before reset does not launch Claude.
- Status/resume reports the absolute reset time.
- After reset, the phase is released and only retry targets redispatch.

### Phase 4: Redispatch unfinished units only

Goal: make resume preserve landed work and spend only on what remains.

Work:

1. Use existing `resume_stage_adoption_journals()` before redispatch to finish
   any interrupted adoption work.
2. Use existing `retry_failed_units()` or extend it to include rate-limit
   pending stages when `fresh_reviewer_required` is set by the abort path.
3. Ensure dispatcher prompt generation receives:
   - `preserved_work_units`;
   - `retry_target_work_units`;
   - recovery context from previous attempt;
   - paths to existing unit worktrees.
4. Ensure retry dispatch does not recreate unit worktrees from scratch when a
   dirty/partial worktree already exists for the same unit.
5. Make the operator output explicit:

```text
Rate limited until 2026-05-05 17:50 America/New_York.
Preserved: unit-4-1, unit-4-2.
Will retry with fresh agents: unit-4-3, unit-4-4, unit-4-5.
Partial worktrees preserved under: <path>
```

Files:

- `py/swarm_do/pipeline/stage_controller.py`
- `py/swarm_do/pipeline/stage_invocation.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/context_bundle.py` if retry context rendering lives there
- resume/status CLI tests

Acceptance:

- Resume after reset does not redispatch adopted units.
- Retry targets get fresh agents.
- Dirty worktrees and prior artifacts are visible to the retry prompt.

### Phase 5: Optional model/provider fallback

Goal: support the long-term "try another model" idea without risking
mid-subagent corruption.

Default policy for v1: `none`.

Add an explicit fallback policy later:

```toml
[rate_limits]
fallback_policy = "none" # none | same_provider_model | cross_provider
same_provider_models = ["claude-sonnet-4-5", "claude-haiku-4-5"]
cross_provider_models = ["codex", "gemini"]
```

Rules:

1. Fallback only at a phase or unit boundary.
2. Never switch model/provider inside an already-running child.
3. Reuse the same preserved/retry-target contract.
4. Only allow cross-provider fallback when the target runner can satisfy the
   same tool, worktree, and result-artifact contract.
5. Record fallback choice in phase result and run trace.

Files:

- policy/config surfaces;
- launcher/provider abstraction;
- `stage_invocation.py` prompt annotations;
- run trace/status output;
- tests for fallback disabled/enabled.

Acceptance:

- With fallback disabled, a hard 429 parks until reset.
- With fallback enabled and compatible, only unfinished units are redispatched
  through the fallback lane.
- Completed/adopted work is never thrown away.

### Phase 6: Prevent obvious rate-limit burn

Goal: reduce how often the stop path is needed.

Work:

1. Treat high-utilization warnings as a reason to avoid starting additional
   fanout waves in the same run.
2. Cap parallelism when warning utilization crosses a threshold, for example
   90 percent.
3. Add per-phase spend/turn guardrails where SwarmDaddy can observe them.
4. Avoid prompt blowups already tracked by the fanout foundation plan:
   unsubstituted caps, repeated writer role briefs, and unbounded fanout prompts.
5. Keep cost/token fields nullable unless provider telemetry is authoritative.

Acceptance:

- Soft warning events are visible in metadata.
- The dispatcher does less new work after a high-utilization warning.
- Hard 429 behavior remains deterministic if prevention fails.

---

## 7. Test Plan

Unit tests:

- parser captures `rate_limit_event`;
- parser captures final result `api_error_status=429`;
- classifier handles empty 429;
- text fallback handles `429`/`rate limit`;
- warning-only events do not fail a phase;
- hard 429 beats `NORMALIZATION_ERROR`;
- provider reset windows produce absolute `next_retry_at`;
- generic retry-after clamp does not erase provider reset time.

Controller tests:

- `finish(abort_reason="rate_limit")` adopts already-valid results;
- unresolved pending markers are not failed as missing/invalid under rate-limit
  abort;
- pending/in-flight unit stages become retry targets;
- adopted units stay adopted.

Integration/fake-run tests:

- dispatch five unit stages;
- two write valid result files and markers;
- three remain pending;
- inject hard 429 final result;
- assert preserved units are exactly the two adopted units;
- assert retry targets are exactly the three unfinished units;
- assert phase is `retry_waiting`;
- assert failure kind is `RETRYABLE_RATE_LIMIT`;
- assert no `NORMALIZATION_ERROR` appears as root cause;
- resume after reset redispatches only retry targets.

Fallback tests:

- fallback disabled -> wait until reset;
- fallback enabled but incompatible -> wait/human gate with clear reason;
- fallback enabled and compatible -> redispatch retry targets only.

---

## 8. Operator UX

The operator-facing message should answer four questions:

1. What happened?
2. When can work continue?
3. What work was preserved?
4. What will be retried?

Preferred wording:

```text
Phase 4 stopped because Claude returned API 429.
Reset: 2026-05-05 17:50 America/New_York.
Preserved adopted units: unit-4-1, unit-4-2.
Fresh agents will retry: unit-4-3, unit-4-4, unit-4-5.
Partial worktrees and result artifacts were preserved under <run-dir>.
```

Avoid saying "normalization error" unless the root cause is actually a contract
normalization failure unrelated to provider rate limits.

---

## 9. Rejected Alternatives

### A. Text-scrape stderr only

MCO, Metaswarm, and ECC all use text matching somewhere, and it is useful as a
fallback. It is not sufficient here because the observed Claude failure had
structured stream evidence that the current parser ignored.

### B. Retry the whole phase from scratch

This wastes adopted work and repeats token-heavy setup. SwarmDaddy already has
durable worktrees, stage sessions, and adoption journals, so retry should be at
the unfinished-unit level.

### C. Live-resume child subagents

Do not build correctness around this. Treat live child sessions as gone after
the parent dispatcher aborts. Durable artifacts are the contract.

### D. Immediate cross-model fallback by default

Fallback is promising, but it can change tool availability, model behavior, and
result formatting. Make it explicit and boundary-scoped after the stop/resume
path is correct.

---

## 10. Open Questions

1. What exact fields does Claude Code guarantee on `rate_limit_event`? Current
   implementation should be tolerant and evidence-based, not schema-fragile.
2. Should `rate_limits.v1.json` be run-local only, or also provider-global under
   the SwarmDaddy data dir so a different run does not immediately hit the same
   known reset window?
3. Should warning utilization throttle within a single dispatcher prompt, or is
   v1 limited to suppressing the next phase/wave?
4. Which fallback models/providers satisfy the full fanout contract, including
   `Agent`, worktree discipline, file writes, result artifacts, and permission
   posture?

---

## 11. Done Definition

The work is complete when:

- the run-of-record failure class is represented by a fixture;
- hard 429s classify as `RETRYABLE_RATE_LIMIT`;
- hard 429s do not become `NORMALIZATION_ERROR`;
- reset time is persisted and shown to the operator;
- running before reset parks without launching another expensive Claude
  dispatcher;
- resume after reset adopts any recoverable artifacts and redispatches only
  unfinished units with fresh agents;
- fallback is either explicitly disabled or boundary-scoped and tested.
