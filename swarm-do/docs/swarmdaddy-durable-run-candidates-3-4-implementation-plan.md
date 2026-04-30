# SwarmDaddy Durable Run Candidates 3-4 Implementation Plan

Status: implementation-ready after codebase research and review revision
Date: 2026-04-30
Source research: `docs/swarmdaddy-durable-run-capabilities-research-plan.md`
Builds on: `docs/swarmdaddy-durable-run-candidates-1-2-implementation-plan.md`
Related plans:

- `docs/phase-session-auto-advance-hardening-plan.md`
- `docs/phase-session-autopilot-sequential-plan.md`
- `docs/phase-session-durable-recovery-plan.md`
- `docs/failure-taxonomy.md`

## Goal

Turn durable-run capability candidates 3 and 4 into concrete work for the
current SwarmDaddy phase-session runtime:

1. Policy-Gated Autopilot.
2. Schema-Validated Handoffs.

The implementation should extend the local durable harness. It should not add a
new orchestration backend, replace phase sessions with Agent Teams, loosen
artifact schemas to make model output easier to accept, or add a second state
model beside `phase_sessions.v1.json`.

## Research Findings

The current tree already implements important foundations for both candidates:

- `py/swarm_do/pipeline/failure_taxonomy.py` defines known failure kinds,
  categories, retry classes, and operator messages.
- `py/swarm_do/pipeline/phase_evidence.py` writes per-attempt
  `evidence.json` manifests under `phase_launches/<phase_id>/attempt-<n>/`.
- `py/swarm_do/pipeline/phase_recovery.py` already blocks deterministic
  contract failures, same-failure loops, permission/workspace failures, and
  zero-returncode writer contract failures.
- `py/swarm_do/pipeline/phase_sessions.py` already persists `blocked_reason`,
  `retry_policy_decision`, `retry_policy`, `attempt_history`, and
  `evidence_path`.
- `py/swarm_do/pipeline/phase_attempt_metrics.py` and
  `py/swarm_do/pipeline/phase_attempts.py` already expose provider-reported
  cost, token, permission-denial, unknown-cost, and archived-attempt summaries.
- `py/swarm_do/pipeline/phase_pump.py` already forwards a per-attempt
  `--max-budget-usd` value to `claude-print`.
- `schemas/phase_result.schema.json` and
  `schemas/phase_handoff.schema.json` are strict v1 schemas with
  `additionalProperties: false`.
- `phase_sessions.validate_phase_artifacts()` already enforces identity,
  prepared-plan SHA, phase-content SHA, attempt agreement, result/handoff
  status agreement, run-directory path containment, and prepared work-unit
  subset rules.
- `_append_claude_print_contract()` already appends result/handoff templates
  and array-type rules to launcher prompts.

The remaining work is therefore not "invent policy" or "invent schemas." It is
to make policy decisions data-driven and explainable, then make the artifact
contract easy for models and operators to follow without broad schema churn.

## Review Validation Update

The 2026-04-30 review findings were validated against the current tree and are
accurate. This revision resolves them with explicit implementation contracts:

- `schemas/phase_sessions.schema.json` and
  `schemas/phase_attempt_evidence.schema.json` both use
  `additionalProperties: false` on the relevant objects, so policy writes must
  land after exact schema fragments are added.
- `init_phase_sessions()` currently returns existing state immediately when
  `phase_sessions.v1.json` exists; this plan now defines when idempotent init
  may reconfigure policy and when persisted state wins.
- `bin/swarm do` is the argparse entry point for both `--prepared` and
  `--prepare --continue`; `phases init` and `phases pump` are the only `phases`
  subcommands that need policy flags in P0.
- `policy_reason` is a closed P0 explanation value, while
  `retry_policy_decision` remains the existing backward-compatible string field.
  Spend gates therefore use specific `policy_reason` values and the legacy
  `retry_policy_decision="spend_threshold"` label.

## Final Recommendation

Ship Candidate 3 first as a policy extraction and spend-gate pass. It should
preserve current behavior before adding dollar gates. The durable state already
has the right fields; the missing piece is a pure policy evaluator and a
persisted explanation for every retry, gate, and exhaustion decision.

Ship Candidate 4 immediately after or in parallel when ownership is separate.
It is mostly documentation, examples, fixtures, and template de-duplication.
The runtime schemas stay at version 1.

## Candidate 3 - Policy-Gated Autopilot

### Requirement

Make unattended phase-session execution stop automatically when continuing would
waste spend, repeat a deterministic failure, or require operator judgment. Every
stop must explain what evidence was used, which policy fired, what state was
written, and what command the operator should run next.

### Current Problems

- Retry policy is split across `_retry_stop_decision()`,
  `_needs_recovery_retry()`, `_fallback_retry_after_seconds()`,
  same-failure counting, retry-budget checks, handoff `do_not_retry`, and
  `DEFAULT_RETRY_POLICY`.
- The final status is usually clear, but the policy inputs are not recorded as
  a single structured decision.
- Cost is visible in status output, but failed-spend thresholds do not currently
  stop future launches.
- `--max-budget-usd` can cap a single Claude attempt, but its source is only
  the caller; it is not resolved from a durable policy profile.
- Unknown-cost attempts are displayed correctly as unknown, but policy does not
  record how unknown cost affected the decision.

### Implementation Decision

Add a pure policy module:

`py/swarm_do/pipeline/phase_autopilot_policy.py`

The policy module decides. `phase_recovery.py` remains the transition
orchestrator. `phase_sessions.py` remains the only module that mutates durable
phase-session state.

Do not add a new phase status. Policy stops continue to use `blocked` with one
of the existing parent-owned `blocked_reason` values. Spend and same-failure
stops use:

- `blocked_reason="retry_policy_human_gate"`
- `retry_policy_decision="spend_threshold"` or `"same_failure_limit"`

`retry_exhausted` remains distinct and means automation believed retry was
allowed but the configured retry budget was spent.

### Policy Types

Add frozen dataclasses:

```python
@dataclass(frozen=True)
class AutopilotPolicyConfig:
    autopilot_profile: str
    max_session_attempts: int
    max_recovery_attempts: int
    recovery_timeout_threshold_seconds: int
    retry_sleep_threshold_seconds: int
    short_retry_backoff_seconds: int
    max_retry_after_seconds: int
    max_consecutive_same_failure_kind: int
    max_failed_attempt_cost_usd: float | None
    max_failed_run_cost_usd: float | None
    max_phase_attempt_budget_usd: float | None


@dataclass(frozen=True)
class AutopilotPolicyInput:
    failure_kind: str
    failure_category: str | None
    failure_retry_class: str | None
    attempt: int
    same_failure_count: int
    max_session_attempts: int
    recovery_attempts_used: int
    needs_recovery_retry: bool
    returncode: int | None
    artifact_error_kinds: tuple[str, ...]
    partial_artifacts: bool
    changed_file_count: int
    elapsed_seconds: float | None
    retry_after_seconds_requested: int | None
    current_attempt_cost_usd: float | None
    cost_confidence: str | None
    failed_phase_cost_usd: float
    failed_run_cost_usd: float
    unknown_failed_attempt_count: int
    handoff_do_not_retry: bool


@dataclass(frozen=True)
class AutopilotPolicyDecision:
    action: str
    policy_reason: str
    blocked_reason: str | None
    retry_policy_decision: str
    retry_after_seconds: int | None
    operator_title: str | None
    operator_message: str | None
    inputs: dict[str, Any]
```

Allowed `action` values:

- `retry`
- `retry_after_backoff`
- `recovery_retry`
- `human_gate`
- `retry_exhausted`
- `terminal`

Allowed initial `policy_reason` values:

- `taxonomy_human_gate`
- `deterministic_contract_failure`
- `permission_contract_failure`
- `same_failure_limit`
- `retry_budget_exhausted`
- `recovery_retry_budget_exhausted`
- `failed_attempt_spend_threshold`
- `failed_run_spend_threshold`
- `child_do_not_retry`
- `child_nonretryable_failed`
- `retry_after_requested`
- `normal_retry`
- `recovery_retry_required`

These `policy_reason` values are the closed initial set. By contrast,
`retry_policy_decision` is intentionally not an enum in
`phase_sessions.v1.json`; it remains a compatibility/status label. For
launcher eligibility gates, write the literal failure kind, for example
`retry_policy_decision="claude_cli_missing"`. For both spend gates, write
`retry_policy_decision="spend_threshold"` and use `policy_reason` to identify
which threshold fired.

### Policy Configuration

Keep policy configuration in the existing `phase_sessions.v1.json.retry_policy`
object. Extend `DEFAULT_RETRY_POLICY` and `schemas/phase_sessions.schema.json`
with these fields:

```python
DEFAULT_RETRY_POLICY = {
    ...
    "autopilot_profile": "standard",
    "max_failed_attempt_cost_usd": None,
    "max_failed_run_cost_usd": None,
    "max_phase_attempt_budget_usd": None,
}
```

Add this exact fragment to
`schemas/phase_sessions.schema.json#/properties/retry_policy/properties` before
any runtime writes include the new keys:

```json
"autopilot_profile": {
  "type": "string",
  "enum": ["standard", "dogfood", "strict"]
},
"max_failed_attempt_cost_usd": {
  "type": ["number", "null"],
  "minimum": 0
},
"max_failed_run_cost_usd": {
  "type": ["number", "null"],
  "minimum": 0
},
"max_phase_attempt_budget_usd": {
  "type": ["number", "null"],
  "minimum": 0
}
```

Profile semantics:

| Profile | Default behavior |
| --- | --- |
| `standard` | Current conservative count/backoff behavior. No dollar gates by default. |
| `dogfood` | Standard behavior plus `max_failed_run_cost_usd=2.00`, `max_failed_attempt_cost_usd=1.50`, and `max_phase_attempt_budget_usd=1.50`. |
| `strict` | No automatic retry by default: `max_session_attempts=1`, `max_recovery_attempts=0`, and `max_phase_attempt_budget_usd=1.00`. |

Do not add `fast` in this pass. A profile that optimizes speed over safety is
the wrong default surface for durable unattended runs.

Override precedence:

1. CLI flags.
2. Existing non-null `phase_sessions.v1.json.retry_policy` values.
3. Environment variables, only for new state or missing/null fields.
4. Profile defaults.
5. `DEFAULT_RETRY_POLICY`.

This precedence is intentional: durable state wins once a run exists. CLI flags
are explicit operator commands and may update existing state. Environment
variables are defaults for newly initialized runs and are allowed to fill
missing/null fields for old normalized state, but they must not overwrite a
persisted non-null policy value.

Define the data carrier in `phase_autopilot_policy.py` and implement the
args/env resolver in `cli.py`, not ad hoc merging. Keep `argparse` imports out
of `phase_sessions.py`:

```python
@dataclass(frozen=True)
class ResolvedPolicyUpdate:
    forced_overrides: dict[str, Any]
    default_overrides: dict[str, Any]


def policy_update_from_args_and_env(args: argparse.Namespace) -> ResolvedPolicyUpdate:
    ...
```

`forced_overrides` contains only CLI-supplied values. `default_overrides`
contains environment-derived and profile-derived values. `configure_retry_policy`
must apply forced overrides over existing state and default overrides only when
the destination key is absent or `None`.

Profile expansion must also be deterministic:

- A CLI `--policy-profile dogfood` or `--policy-profile strict` expands into
  forced overrides for the fields listed in the profile table.
- Individual CLI numeric flags override values implied by the CLI profile.
- `SWARM_PHASE_AUTOPILOT_PROFILE` expands into default overrides only.
- A persisted `autopilot_profile` expands only for missing/null fields; it must
  not overwrite persisted threshold values.

Add environment variables:

- `SWARM_PHASE_AUTOPILOT_PROFILE`
- `SWARM_MAX_FAILED_ATTEMPT_COST_USD`
- `SWARM_MAX_FAILED_RUN_COST_USD`
- `SWARM_MAX_PHASE_ATTEMPT_BUDGET_USD`

Add CLI flags to these argparse parsers in `py/swarm_do/pipeline/cli.py`:

- the top-level `do` parser, because it is the single entry point for both
  `bin/swarm do --prepared` and `bin/swarm do --prepare --continue`
- the `phases init` parser
- the `phases pump` parser

Do not add P0 policy flags to `phases recover`, `phases status`, or the
artifact-adoption subcommands; they should read already persisted policy.

Flags to add:

- `--policy-profile {standard,dogfood,strict}`
- `--max-failed-attempt-cost-usd <float>`
- `--max-failed-run-cost-usd <float>`
- `--max-phase-attempt-budget-usd <float>`

Keep existing `--max-budget-usd` as a compatibility alias for
`--max-phase-attempt-budget-usd`, but preserve current behavior while plumbing:

- On the `do` parser, keep the existing `max_budget_usd` destination and have
  `policy_update_from_args_and_env()` treat it as
  `max_phase_attempt_budget_usd` when the new flag is unset.
- On the `phases pump` parser, keep the existing `max_budget_usd` destination
  for direct forwarding compatibility and apply the same normalization.
- `--max-phase-attempt-budget-usd` takes precedence over `--max-budget-usd` if
  both are supplied.

Do not extend `schemas/preset.schema.json` in P0. Presets already have an
estimated-budget table. Autopilot policy is runtime recovery policy; it should
prove itself through CLI/env dogfood before becoming preset surface area.

### Runtime Wiring

Update `phase_sessions.py`:

- Add `policy_update: ResolvedPolicyUpdate | None` to
  `init_phase_sessions()`.
- Add `configure_retry_policy(run_id, policy_update, *, data_dir)` that merges
  validated forced/default overrides into existing state and emits no new event
  type.
- Normalize old state with the new nullable fields.
- Keep new fields optional and do not bump `schema_version`.

`init_phase_sessions()` idempotence semantics must be exact:

- If state does not exist, initialize from `DEFAULT_RETRY_POLICY`, apply the
  selected profile defaults, apply environment/default overrides, then apply
  CLI forced overrides before the first state write.
- If state already exists and no CLI forced overrides were supplied, load,
  normalize, and return the existing state unchanged except for filling newly
  introduced missing/null default fields during normalization.
- If state already exists and CLI forced overrides were supplied, call
  `configure_retry_policy()` inside the same lock, return
  `initialized=False`, and include `policy_configured=True` in the payload.
- Environment-derived values must not re-apply over existing non-null state on
  the idempotent path.

`configure_retry_policy()` must validate profiles and numeric thresholds before
writing, reject negative numbers with `PhaseSessionError`, and call
`_validate_state()` before the atomic write.

Update `phase_pump.py`:

- Resolve policy overrides at pump startup and persist them through
  `configure_retry_policy()` before recovery/claim.
- Resolve per-attempt Claude budget from policy when the caller did not pass
  `max_budget_usd`.
- Continue passing the resolved value to `claude-print` as `--max-budget-usd`.
- Record the resolved value in `command.json` through the existing `argv`
  capture; do not duplicate it into run events.

Update `cli.py`:

- Parse policy CLI flags once into a small override object.
- Pass the resolved policy update to `init_phase_sessions()` and
  `pump_phases()`.
- For `cmd_phases`, `phases init` calls `init_phase_sessions(...,
  policy_update=...)`; `phases pump` calls `pump_phases(...,
  policy_update=...)`.
- For `cmd_do`, `_dispatch_with_phase_sessions()` passes the same args-derived
  policy update to `pump_phases(init_if_missing=True, ...)`. This covers both
  `do --prepared` and `do --prepare --continue` because both dispatch through
  `_dispatch_prepared()` and `_dispatch_with_phase_sessions()`.
- In JSON output for `do --prepared --phase-sessions auto`, include the resolved
  policy profile and threshold values under `phase_sessions.policy`.

Update `phase_recovery.py`:

- Build `AutopilotPolicyInput` inside `_retry_or_exhaust()` from the existing
  phase, state, evidence, same-failure count, recovery-attempt count, retry
  policy, and spend summary.
- Replace `_retry_stop_decision()`, `_needs_recovery_retry()` decision glue,
  same-failure blocking, retry budget checks, and fallback-backoff selection
  with `evaluate_autopilot_policy()`.
- Keep transition calls unchanged:
  - `human_gate` calls `mark_phase_blocked()`.
  - `retry_exhausted` calls `mark_retry_exhausted()`.
  - `retry`, `retry_after_backoff`, and `recovery_retry` call
    `abandon_attempt_and_retry()`.
  - `terminal` is used only for child-controlled nonretryable results already
    adopted as `failed`, `blocked`, or `needs_input`.
- Preserve current status outputs for existing tests before enabling dollar
  gates by default.

Spend-input calculation:

- Add `py/swarm_do/pipeline/phase_spend.py`.
- Add a frozen dataclass named `FailedSpendSnapshot` with:
  `current_attempt_cost_usd`, `current_attempt_cost_confidence`,
  `failed_phase_cost_usd`, `failed_run_cost_usd`, and
  `unknown_failed_attempt_count`.
- Add `failed_spend_snapshot(run_id, phase_id, attempt, *, data_dir=None,
  include_archived=False) -> FailedSpendSnapshot`.
- Export `is_failed_attempt(row: Mapping[str, Any]) -> bool` from
  `phase_attempts.py` by promoting the current `_is_failed_attempt()` helper;
  keep the old semantics.
- Implement `failed_spend_snapshot()` by calling `summarize_phase_attempts()`,
  filtering rows through `is_failed_attempt()`, and reading the current
  attempt row by `(phase_id, attempt)`.
- Use provider-reported cost only: `total_cost_usd` or normalized
  `modelUsage.*.costUSD` from `phase_attempt_metrics.stdout_metrics()`.
- Treat `cost_confidence="conflict"` as unknown for gating.
- Unknown cost contributes to `unknown_failed_attempt_count`, never to a
  fabricated dollar value.
- Unknown cost still counts against attempt limits and same-failure limits.
- Failed-run cost excludes adopted successful attempts and includes only
  attempts that `is_failed_attempt()` counts today.
- Failed-phase cost is the same failed-cost calculation restricted to the
  current phase id.
- Archived attempts remain excluded from P0 policy gates unless
  `include_archived=True` is explicitly passed for a future operator command.

### Policy Persistence

Add optional fields to `attempt_history[]` in
`schemas/phase_sessions.schema.json`. Because
`attempt_history[].items.additionalProperties` is `false`, this schema fragment
must land before recovery writes the fields:

```json
"policy_action": {
  "type": ["string", "null"],
  "enum": [
    "retry",
    "retry_after_backoff",
    "recovery_retry",
    "human_gate",
    "retry_exhausted",
    "terminal",
    null
  ]
},
"policy_reason": {
  "type": ["string", "null"],
  "enum": [
    "taxonomy_human_gate",
    "deterministic_contract_failure",
    "permission_contract_failure",
    "same_failure_limit",
    "retry_budget_exhausted",
    "recovery_retry_budget_exhausted",
    "failed_attempt_spend_threshold",
    "failed_run_spend_threshold",
    "child_do_not_retry",
    "child_nonretryable_failed",
    "retry_after_requested",
    "normal_retry",
    "recovery_retry_required",
    null
  ]
},
"policy_inputs": {
  "type": ["object", "null"],
  "additionalProperties": false,
  "properties": {
    "failure_kind": { "type": ["string", "null"] },
    "failure_category": { "type": ["string", "null"] },
    "failure_retry_class": { "type": ["string", "null"] },
    "attempt": { "type": ["integer", "null"], "minimum": 1 },
    "same_failure_count": { "type": ["integer", "null"], "minimum": 0 },
    "max_session_attempts": { "type": ["integer", "null"], "minimum": 1 },
    "max_recovery_attempts": { "type": ["integer", "null"], "minimum": 0 },
    "max_consecutive_same_failure_kind": { "type": ["integer", "null"], "minimum": 1 },
    "recovery_attempts_used": { "type": ["integer", "null"], "minimum": 0 },
    "needs_recovery_retry": { "type": ["boolean", "null"] },
    "recovery_timeout_threshold_seconds": { "type": ["integer", "null"], "minimum": 1 },
    "retry_sleep_threshold_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "short_retry_backoff_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "max_retry_after_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "returncode": { "type": ["integer", "null"] },
    "artifact_error_kinds": { "type": "array", "items": { "type": "string" } },
    "partial_artifacts": { "type": ["boolean", "null"] },
    "changed_file_count": { "type": ["integer", "null"], "minimum": 0 },
    "elapsed_seconds": { "type": ["number", "null"], "minimum": 0 },
    "retry_after_seconds_requested": { "type": ["integer", "null"], "minimum": 0 },
    "current_attempt_cost_usd": { "type": ["number", "null"], "minimum": 0 },
    "failed_phase_cost_usd": { "type": ["number", "null"], "minimum": 0 },
    "failed_run_cost_usd": { "type": ["number", "null"], "minimum": 0 },
    "unknown_failed_attempt_count": { "type": ["integer", "null"], "minimum": 0 },
    "cost_confidence": {
      "type": ["string", "null"],
      "enum": ["provider_reported", "unknown", "conflict", null]
    },
    "max_failed_attempt_cost_usd": { "type": ["number", "null"], "minimum": 0 },
    "max_failed_run_cost_usd": { "type": ["number", "null"], "minimum": 0 },
    "max_phase_attempt_budget_usd": { "type": ["number", "null"], "minimum": 0 },
    "handoff_do_not_retry": { "type": ["boolean", "null"] }
  }
}
```

Add the same `policy_action`, `policy_reason`, and `policy_inputs` fragments to
`schemas/phase_attempt_evidence.schema.json#/properties/failure/properties`.
Do not add them to the `failure.required` list; old evidence manifests must
remain valid after normalization.

`policy_inputs` is intentionally sparse. It has no `required` list, but because
`additionalProperties` is `false`, recovery code must only write the named
properties above.

Add these fields to recovery action dictionaries and run-event `details`:

- `policy_action`
- `policy_reason`
- `policy_inputs`

The `policy_inputs` object must contain only scalar/list evidence already safe
for status output: counts, booleans, failure names, thresholds, and cost
confidence. It must not include prompt text, stdout/stderr bodies, transcript
lines, environment variables, or command argv.

Update `phase_attempts.py`, `cli.py`, `py/swarm_do/tui/state.py`, and
`py/swarm_do/tui/app.py` so status and TUI details can show:

- raw `failure_kind`
- taxonomy category/title
- actual `retry_policy_decision`
- `policy_action`
- `policy_reason`
- known failed cost and unknown-cost attempt count when available

Dense tables should show the reason, not the full `policy_inputs` object.

### Initial Policy Table

The evaluator must reproduce this behavior:

| Evidence | Decision |
| --- | --- |
| `claude_cli_missing` or `launcher_ineligible` | `policy_action=human_gate`, `policy_reason=taxonomy_human_gate`, `blocked_reason=retry_policy_human_gate`, `retry_policy_decision=<literal failure_kind>` |
| `launcher_workspace_error` or `launcher_prompt_sensitive_path` | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| `permission_contract_failure` | `policy_action=human_gate`, `policy_reason=permission_contract_failure`, `blocked_reason=permission_contract_failure`, `retry_policy_decision=permission_contract_failure` |
| `outer_json_invalid_no_artifacts` with return code 0 | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| `outer_artifacts_missing` with return code 0 | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| `writer_tool_denied_no_artifacts` with return code 0 | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| `writer_silent_with_turns` with return code 0 | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| Artifact error in `path_escape`, identity mismatch, SHA mismatch, attempt mismatch, handoff status mismatch, or unprepared completed work unit | `policy_action=human_gate`, `policy_reason=deterministic_contract_failure`, `blocked_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| Same failure kind count reaches `max_consecutive_same_failure_kind` | `policy_action=human_gate`, `policy_reason=same_failure_limit`, `retry_policy_decision=same_failure_limit` |
| Known current failed-attempt cost exceeds `max_failed_attempt_cost_usd` | `policy_action=human_gate`, `policy_reason=failed_attempt_spend_threshold`, `retry_policy_decision=spend_threshold` |
| Known failed-run cost exceeds `max_failed_run_cost_usd` | `policy_action=human_gate`, `policy_reason=failed_run_spend_threshold`, `retry_policy_decision=spend_threshold` |
| Child handoff sets `do_not_retry=true` for an otherwise retryable failure | `policy_action=human_gate`, `policy_reason=child_do_not_retry`, `blocked_reason=child_reported_blocked`, `retry_policy_decision=child_do_not_retry` |
| Child result is failed and not retryable | `policy_action=terminal`, `policy_reason=child_nonretryable_failed`, `retry_policy_decision=child_nonretryable_failed` |
| Dirty, partial, or long attempt needs recovery but recovery budget is spent | `policy_action=retry_exhausted`, `policy_reason=recovery_retry_budget_exhausted`, `retry_policy_decision=retry_exhausted` |
| Attempt budget exhausted for retryable failure | `policy_action=retry_exhausted`, `policy_reason=retry_budget_exhausted`, `retry_policy_decision=retry_exhausted` |
| Dirty, partial, or long attempt and recovery budget remains | `policy_action=recovery_retry`, `policy_reason=recovery_retry_required` |
| Retryable failure with child `retry_after_seconds` | `policy_action=retry_after_backoff`, `policy_reason=retry_after_requested`, clamped to `max_retry_after_seconds` |
| Retryable transport/lifecycle/launcher failure | `policy_action=retry_after_backoff`, `policy_reason=normal_retry`, using the fallback schedule |

Fallback backoff schedule remains:

- attempt 1 -> 60 seconds
- attempt 2 -> 180 seconds
- attempt 3+ -> 600 seconds
- clamped to `max_retry_after_seconds`

### Tests

Add `py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py`:

- Pure evaluator preserves every initial policy-table decision.
- Unknown child-reported failure kinds remain child-controlled and do not create
  a registry-only human gate.
- `dogfood` profile resolves the expected dollar thresholds.
- CLI override values win over persisted/environment/profile defaults; persisted
  non-null values win over environment defaults.
- Unknown cost is not counted as `$0.00`.

Update `test_phase_recovery.py`:

- Existing retry/block/exhaustion tests still pass with the evaluator.
- Same failure kind twice records `policy_action=human_gate` and
  `policy_reason=same_failure_limit`.
- Deterministic contract failure records `policy_reason`.
- Known failed-attempt spend threshold blocks before scheduling a retry.
- Known failed-run spend threshold blocks before another launch.
- Cost conflict is treated as unknown for dollar gates.
- Unknown-cost failure still counts against attempt and same-failure limits.

Update `test_phase_pump.py`:

- `--max-budget-usd` remains forwarded to Claude.
- `max_phase_attempt_budget_usd` from policy is forwarded when CLI budget is
  absent.
- CLI budget overrides policy budget.
- `dogfood` profile applies a budget without requiring preset changes.

Update `test_phase_sessions.py`:

- Old state without new policy fields normalizes and validates.
- `configure_retry_policy()` persists validated overrides.
- Invalid profile or negative threshold raises `PhaseSessionError`.

Update `test_phase_attempts.py` and TUI state tests:

- Policy fields surface in attempt rows when present.
- Old runs without policy fields still summarize.

### Rejected Alternatives

- Do not add a `human_gated` status. `blocked` plus structured reason is already
  the established durable state.
- Do not estimate dollars from token counts, turns, wall time, output bytes, or
  prompt size.
- Do not put raw policy evidence into Beads notes or TUI tables.
- Do not make preset schema changes in P0.
- Do not make the taxonomy registry own history-sensitive rules such as
  same-failure limits or spend thresholds.

## Candidate 4 - Schema-Validated Handoffs

### Requirement

Make result and handoff artifacts strict, versioned, operator-readable, and easy
for fresh launcher sessions to produce correctly. Artifacts remain the source of
truth; final assistant prose remains advisory.

### Current Problems

- The schemas are strict, but examples for valid `complete`, `failed`,
  `blocked`, and `needs_input` artifact pairs do not exist under
  `docs/examples/`.
- The launcher prompt contains JSON templates and type rules inline in
  `_append_claude_print_contract()`, which makes docs and prompt wording drift
  likely.
- Common `PhaseArtifactContractError.kind` values are tested individually in
  places, but there is no contract guide that maps them to operator meaning and
  recovery behavior.
- Model-facing instructions explain array element types, but they are mixed
  with launcher mechanics. A shorter generated contract block should be easier
  to audit.

### Implementation Decision

Keep `phase_result.schema.json` and `phase_handoff.schema.json` at
`schema_version=1`. Do not loosen required fields, do not allow unknown fields,
and do not make `failure_kind` an enum.

Add a shared contract module:

`py/swarm_do/pipeline/phase_artifact_contract.py`

This module owns the model-facing templates and guide-generation primitives.
The schemas remain the machine authority; the module prevents docs, examples,
and launcher prompt text from drifting.

### Contract Module Shape

Expose:

```python
PHASE_RESULT_STATUSES = ("complete", "failed", "blocked", "needs_input")

def phase_result_template(
    *,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    launcher: str,
    session_name: str | None,
    prepared_plan_sha: str,
    phase_content_sha: str,
    handoff_path: str,
) -> dict[str, Any]

def phase_handoff_template(
    *,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
) -> dict[str, Any]

def phase_artifact_contract_markdown(...) -> str

def phase_artifact_type_rules_markdown() -> str
```

Update `_append_claude_print_contract()` to call
`phase_artifact_contract_markdown()` and keep the public launcher behavior
unchanged.

The generated launcher contract must include:

- exact result path
- exact handoff path
- allowed status values
- identity fields that must match phase-session state
- complete result template
- complete handoff template
- array element type rules
- instruction that `completed_work_units` must stay empty unless using prepared
  unit IDs shown in the informational decomposition
- instruction to put semantic accomplishments in `summary`, `artifacts`, or
  `validation`

It must not include raw prior handoff content, raw recovery text, or duplicate
full schema prose.

### Documentation

Add:

`docs/phase-artifact-contract.md`

The guide must document:

- result and handoff artifact paths
- required fields
- status meanings
- identity and hash checks
- path containment rule
- `retryable`, `retry_after_seconds`, and handoff `do_not_retry`
- prepared work-unit subset rule in phase-session mode
- common validation failures and their `PhaseArtifactContractError.kind`
- recovery behavior for invalid artifacts
- where evidence manifests record artifact validity

Add examples under:

```text
docs/examples/phase-artifacts/
  README.md
  complete.result.json
  complete.handoff.json
  failed-retryable.result.json
  failed-retryable.handoff.json
  blocked.result.json
  blocked.handoff.json
  needs-input.result.json
  needs-input.handoff.json
```

Example rules:

- Use real synthetic values, not angle-bracket placeholders.
- Use `run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV"`.
- Use `phase_id="1"` and `phase_attempt=1`.
- Use `prepared_plan_sha` value
  `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`.
- Use `phase_content_sha` value
  `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`.
- Use `handoff_path` values relative to the data directory:
  `runs/01ARZ3NDEKTSV4RRFFQ69G5FAV/phase_handoffs/1/attempt-1.handoff.json`.
- Keep `completed_work_units` empty in all examples.
- In `failed-retryable.result.json`, set `status="failed"`,
  `retryable=true`, `failure_kind="example_transient_failure"`, and
  `retry_after_seconds=60`.
- In `blocked` and `needs_input`, use human-readable `blocked_reason`,
  `needs_input`, `blockers`, and `open_items` fields without relying on parent
  policy enums.

### Runtime Validation Work

No runtime schema loosening is needed.

Update `phase_sessions.validate_phase_artifacts()` only for clearer error
coverage if tests reveal missing cases. If changes are needed, preserve the
existing `PhaseArtifactContractError.kind` values:

- `status_mismatch`
- `result_identity_mismatch`
- `prepared_plan_sha_mismatch`
- `phase_content_sha_mismatch`
- `handoff_identity_mismatch`
- `attempt_mismatch`
- `handoff_status_mismatch`
- `completed_work_units_not_prepared`
- `path_escape`

Do not rename these values. They are already part of the failure taxonomy and
attempt-history evidence.

### Tests

Add `py/swarm_do/pipeline/tests/test_phase_artifact_contract.py`:

- Every docs example validates against its JSON schema.
- Every docs example pair can be copied into a synthetic run directory and
  accepted by `validate_phase_artifacts()` after the synthetic prepared
  artifact/state shas are aligned.
- Add a helper named `_copy_example_pair_into_phase_session_run(tmp_path,
  result_name, handoff_name)` that:
  - creates an accepted prepared run with one phase
  - initializes phase sessions and claims/starts phase `1`
  - rewrites `phase_sessions.v1.json["prepared_plan_sha"]` to the example
    prepared-plan SHA constant
  - rewrites `prepared_plan.v1.json["prepared_plan_sha"]` to the example
    prepared-plan SHA constant
  - rewrites `prepared_plan.v1.json["phase_map"][0]["content_sha"]` to the
    example phase-content SHA constant
  - copies the example result to
    `runs/<run_id>/phase_results/1/attempt-1.result.json`
  - copies the example handoff to
    `runs/<run_id>/phase_handoffs/1/attempt-1.handoff.json`
  - calls `validate_phase_artifacts()` and returns the validated paths
- `phase_artifact_contract_markdown()` includes the same status values and
  required array type rules as the schemas.
- `_append_claude_print_contract()` uses the shared contract text and still
  includes exact result/handoff paths.

Add negative contract tests:

- Result `run_id` mismatch raises `result_identity_mismatch`.
- Prepared-plan SHA mismatch raises `prepared_plan_sha_mismatch`.
- Phase-content SHA mismatch raises `phase_content_sha_mismatch`.
- Handoff attempt mismatch raises `attempt_mismatch`.
- Handoff status mismatch raises `handoff_status_mismatch`.
- Handoff path outside `data/runs/<run_id>/` raises `path_escape`.
- Object values inside string arrays, for example `handoff.decisions`, fail
  schema validation.
- New phase-session artifacts with non-prepared `completed_work_units` raise
  `completed_work_units_not_prepared`.

Update `test_failure_taxonomy.py`:

- Assert every `PhaseArtifactContractError.kind` above appears in
  `known_failure_kinds()` or resolves through `failure_kind_details()`.

Update `test_phase_pump.py`:

- Assert the launcher contract block contains no duplicated stale inline
  template text after moving to `phase_artifact_contract.py`.
- Assert fake/injected `claude-print` examples still complete.

### Rejected Alternatives

- Do not bump schema versions for documentation-only improvements.
- Do not permit extra properties in result or handoff artifacts.
- Do not accept object-valued handoff arrays where strings are required.
- Do not allow result/handoff paths outside the run directory.
- Do not migrate historical artifacts in place.
- Do not make child `blocked_reason` part of the parent policy enum. Child
  `blocked_reason` remains human-readable artifact content; parent
  `blocked_reason` remains phase-session policy state.

## Ordered Work Breakdown

### P0.0 - Schema Fragments And Policy Defaults

Files:

- `schemas/phase_sessions.schema.json`
- `schemas/phase_attempt_evidence.schema.json`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_evidence.py`

Work:

1. Add the exact `retry_policy`, `policy_action`, `policy_reason`, and
   `policy_inputs` schema fragments from this plan.
2. Extend `DEFAULT_RETRY_POLICY` with the new nullable policy fields.
3. Normalize old phase-session state with the new keys before validation.
4. Add evidence-schema coverage for optional `failure.policy_*` fields.

Acceptance:

- Old state and old evidence manifests remain valid.
- A state file containing the new policy fields validates.
- An evidence manifest containing the new failure policy fields validates.
- Runtime code is not allowed to write new policy fields before this step lands.

### P0.1 - Extract Autopilot Policy

Files:

- `py/swarm_do/pipeline/phase_autopilot_policy.py`
- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`

Work:

1. Add policy dataclasses, profile constants, and evaluator.
2. Wire `_retry_or_exhaust()` through the evaluator.
3. Preserve existing behavior for current recovery tests.
4. Persist policy action/reason in attempt records and recovery actions.

Acceptance:

- Current retry, blocked, and exhausted outputs do not regress.
- Every recovery decision has a structured `policy_action` and
  `policy_reason`.

### P0.2 - Policy Config And Attempt Budget

Files:

- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`

Work:

1. Use the P0.0 nullable runtime policy fields in policy configuration.
2. Add `configure_retry_policy()`.
3. Add CLI/env override resolution.
4. Resolve and forward per-attempt Claude budget from policy.

Acceptance:

- Old state loads.
- Dogfood profile applies thresholds.
- CLI values override persisted/environment/profile values.
- Environment values fill only missing/null persisted policy fields.
- Existing `--max-budget-usd` still works.

### P0.3 - Failed-Spend Gates

Files:

- `py/swarm_do/pipeline/phase_autopilot_policy.py`
- `py/swarm_do/pipeline/phase_spend.py`
- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_attempt_metrics.py`
- `py/swarm_do/pipeline/phase_attempts.py`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`
- `py/swarm_do/pipeline/tests/test_phase_attempts.py`

Work:

1. Compute current attempt cost from provider-reported stdout metrics.
2. Compute failed phase/run cost using the same semantics as attempt summaries.
3. Gate next launch when configured thresholds are exceeded.
4. Record unknown-cost counts and policy explanation.

Acceptance:

- Known spend threshold blocks before another launch.
- Unknown cost is visible and not treated as zero.
- Cost conflicts are unknown for policy.

### P0.4 - Artifact Contract Module And Docs

Files:

- `py/swarm_do/pipeline/phase_artifact_contract.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `docs/phase-artifact-contract.md`
- `docs/examples/phase-artifacts/*`
- `py/swarm_do/pipeline/tests/test_phase_artifact_contract.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`

Work:

1. Move launcher templates/type rules into the shared contract module.
2. Update `_append_claude_print_contract()` to use the module.
3. Add the guide and complete example pairs.
4. Validate examples and common negative cases.

Acceptance:

- Docs examples are schema-valid and full-contract-valid in fixtures.
- Launcher prompt still contains exact artifact paths and templates.
- No schema version bump is required.

### P1 - Preset Surface For Runtime Policy

Files:

- `schemas/preset.schema.json`
- `py/swarm_do/pipeline/validation.py`
- stock presets that opt into dogfood policy
- `py/swarm_do/pipeline/tests/test_pipeline_validation.py`

Work:

1. Add an optional `[phase_sessions]` or `[autopilot]` table after P0 dogfood
   proves the CLI/env contract.
2. Map preset policy into `retry_policy` at `init_phase_sessions()` time.
3. Keep CLI override precedence above preset values.

Acceptance:

- Existing presets remain valid.
- Policy-enabled presets validate and persist expected runtime policy.

## No Open Questions

The implementation decisions for this slice are fixed:

- Policy module home: `phase_autopilot_policy.py`.
- Durable policy config home: `phase_sessions.v1.json.retry_policy`.
- Schema update order: P0.0 lands before any runtime policy writes.
- Idempotent init: persisted state wins unless CLI forced overrides are present.
- Initial policy profiles: `standard`, `dogfood`, and `strict`.
- No `fast` profile in this pass.
- Override precedence: CLI, existing persisted non-null state, environment for
  new or missing/null fields, profile, defaults.
- Failed-spend helper: `phase_spend.failed_spend_snapshot()`.
- Unknown cost: never converted to dollars; still counts against attempt and
  same-failure limits.
- Spend gates: opt-in except dogfood/strict profiles.
- Parent policy stops: reuse `blocked`; do not add `human_gated`.
- Run events: reuse existing `phase_session_blocked`,
  `phase_attempt_retry_scheduled`, and `phase_attempt_retry_exhausted` events.
- Artifact schemas: keep v1 and strict.
- Examples: real synthetic values under `docs/examples/phase-artifacts/`.
- Launcher contract templates: shared module, not inline-only prompt prose.
- Preset schema: explicitly P1, not P0.

## Validation Commands

Run the focused suite after implementation:

```bash
PYTHONPATH=py python3 -m unittest \
  py.swarm_do.pipeline.tests.test_phase_autopilot_policy \
  py.swarm_do.pipeline.tests.test_phase_evidence \
  py.swarm_do.pipeline.tests.test_phase_recovery \
  py.swarm_do.pipeline.tests.test_phase_sessions \
  py.swarm_do.pipeline.tests.test_phase_pump \
  py.swarm_do.pipeline.tests.test_phase_attempts \
  py.swarm_do.pipeline.tests.test_command_profiles \
  py.swarm_do.pipeline.tests.test_phase_artifact_contract \
  py.swarm_do.pipeline.tests.test_failure_taxonomy
```

Run the broader phase-session and schema surface before merging:

```bash
PYTHONPATH=py python3 -m unittest \
  py.swarm_do.pipeline.tests.test_phase_evidence \
  py.swarm_do.pipeline.tests.test_context_bundle \
  py.swarm_do.pipeline.tests.test_prepare_artifact \
  py.swarm_do.pipeline.tests.test_pipeline_validation \
  py.swarm_do.tui.tests.test_state
```
