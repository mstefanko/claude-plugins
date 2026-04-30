# SwarmDaddy Durable Run Candidates 3-4 Implementation Plan

Status: implementation-ready after codebase research
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
    max_attempts: int
    recovery_attempts_used: int
    needs_recovery_retry: bool
    returncode: int | None
    artifact_error_kinds: tuple[str, ...]
    partial_artifacts: bool
    changed_file_count: int
    elapsed_seconds: float | None
    retry_after_seconds_requested: int | None
    current_attempt_cost_usd: float | None
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

### Policy Configuration

Keep policy configuration in the existing `phase_sessions.v1.json.retry_policy`
object. Extend `DEFAULT_RETRY_POLICY` and `schemas/phase_sessions.schema.json`
with optional nullable fields:

- `autopilot_profile`: enum string, default `"standard"`.
- `max_failed_attempt_cost_usd`: number or null.
- `max_failed_run_cost_usd`: number or null.
- `max_phase_attempt_budget_usd`: number or null.

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
2. Environment variables.
3. Existing `phase_sessions.v1.json.retry_policy`.
4. Profile defaults.
5. `DEFAULT_RETRY_POLICY`.

Add environment variables:

- `SWARM_PHASE_AUTOPILOT_PROFILE`
- `SWARM_MAX_FAILED_ATTEMPT_COST_USD`
- `SWARM_MAX_FAILED_RUN_COST_USD`
- `SWARM_MAX_PHASE_ATTEMPT_BUDGET_USD`

Add CLI flags to `bin/swarm phases init`, `bin/swarm phases pump`,
`bin/swarm do --prepared`, and `bin/swarm do --prepare --continue`:

- `--policy-profile {standard,dogfood,strict}`
- `--max-failed-attempt-cost-usd <float>`
- `--max-failed-run-cost-usd <float>`
- `--max-phase-attempt-budget-usd <float>`

Keep existing `--max-budget-usd` as a compatibility alias for
`--max-phase-attempt-budget-usd`.

Do not extend `schemas/preset.schema.json` in P0. Presets already have an
estimated-budget table. Autopilot policy is runtime recovery policy; it should
prove itself through CLI/env dogfood before becoming preset surface area.

### Runtime Wiring

Update `phase_sessions.py`:

- Add `retry_policy_overrides` to `init_phase_sessions()`.
- Add `configure_retry_policy(run_id, overrides, *, data_dir)` that merges
  validated overrides into existing state and emits no new event type.
- Normalize old state with the new nullable fields.
- Keep new fields optional and do not bump `schema_version`.

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
- Pass overrides to `init_phase_sessions()` and `pump_phases()`.
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

- Use provider-reported cost only: `total_cost_usd` or normalized
  `modelUsage.*.costUSD` from `phase_attempt_metrics.stdout_metrics()`.
- Treat `cost_confidence="conflict"` as unknown for gating.
- Unknown cost contributes to `unknown_failed_attempt_count`, never to a
  fabricated dollar value.
- Unknown cost still counts against attempt limits and same-failure limits.
- Failed-run cost excludes adopted successful attempts and includes only
  attempts that `_is_failed_attempt()` would count today.

### Policy Persistence

Add optional fields to `attempt_history[]` in
`schemas/phase_sessions.schema.json`:

- `policy_action`
- `policy_reason`
- `policy_inputs`

Add the same optional fields to the `failure` object in
`schemas/phase_attempt_evidence.schema.json`.

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
| `claude_cli_missing` or `launcher_ineligible` | `human_gate`, `blocked_reason=retry_policy_human_gate`, `retry_policy_decision=<failure_kind>` |
| `launcher_workspace_error` or `launcher_prompt_sensitive_path` | `human_gate`, `retry_policy_decision=deterministic_contract_failure` |
| `permission_contract_failure` | `human_gate`, `blocked_reason=permission_contract_failure`, `retry_policy_decision=permission_contract_failure` |
| `outer_json_invalid_no_artifacts` with return code 0 | `human_gate`, `retry_policy_decision=deterministic_contract_failure` |
| `outer_artifacts_missing` with return code 0 | `human_gate`, `retry_policy_decision=deterministic_contract_failure` |
| `writer_tool_denied_no_artifacts` with return code 0 | `human_gate`, `retry_policy_decision=deterministic_contract_failure` |
| `writer_silent_with_turns` with return code 0 | `human_gate`, `retry_policy_decision=deterministic_contract_failure` |
| Artifact error in `path_escape`, identity mismatch, SHA mismatch, attempt mismatch, handoff status mismatch, or unprepared completed work unit | `human_gate`, `blocked_reason=deterministic_contract_failure`, `retry_policy_decision=deterministic_contract_failure` |
| Same failure kind count reaches `max_consecutive_same_failure_kind` | `human_gate`, `retry_policy_decision=same_failure_limit` |
| Known current failed-attempt cost exceeds `max_failed_attempt_cost_usd` | `human_gate`, `retry_policy_decision=spend_threshold` |
| Known failed-run cost exceeds `max_failed_run_cost_usd` | `human_gate`, `retry_policy_decision=spend_threshold` |
| Attempt budget exhausted for retryable failure | `retry_exhausted` |
| Dirty, partial, or long attempt and recovery budget remains | `recovery_retry` |
| Retryable failure with child `retry_after_seconds` | `retry_after_backoff`, clamped to `max_retry_after_seconds` |
| Retryable transport/lifecycle/launcher failure | `retry_after_backoff` using the fallback schedule |

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
- CLI override values win over environment/profile defaults.
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
- Use valid 64-character lowercase hex strings for prepared and phase shas.
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

### P0.1 - Extract Autopilot Policy

Files:

- `py/swarm_do/pipeline/phase_autopilot_policy.py`
- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`

Work:

1. Add dataclasses, profile defaults, override resolution, and evaluator.
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
- `schemas/phase_sessions.schema.json`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`

Work:

1. Add nullable runtime policy fields.
2. Add `configure_retry_policy()`.
3. Add CLI/env override resolution.
4. Resolve and forward per-attempt Claude budget from policy.

Acceptance:

- Old state loads.
- Dogfood profile applies thresholds.
- CLI values override environment/profile values.
- Existing `--max-budget-usd` still works.

### P0.3 - Failed-Spend Gates

Files:

- `py/swarm_do/pipeline/phase_autopilot_policy.py`
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
- Initial policy profiles: `standard`, `dogfood`, and `strict`.
- No `fast` profile in this pass.
- Override precedence: CLI, environment, existing state, profile, defaults.
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
