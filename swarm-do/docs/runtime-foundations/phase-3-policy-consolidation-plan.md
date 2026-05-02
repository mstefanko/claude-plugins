# Phase 3 - Policy Consolidation

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 3
Last reviewed: 2026-05-02 (evidence-backed against current `pipeline/` source)

## Objective

Centralize retry, timeout, budget, and provider-selection policy display and
validation without forking the existing `phase_autopilot_policy.py` behavior.

## Senior Implementation Decision

Use a facade-first migration. `phase_autopilot_policy.py` already owns the
durable phase retry behavior and has focused tests. Moving or renaming it in
the first PR creates import churn without improving runtime safety.

The first implementation should add `policies.py` as the shared import/display
surface and delegate phase retry decisions to `phase_autopilot_policy.py`.
Only introduce a generic `RetryPolicy` if it is wired to the existing
`AutopilotPolicyConfig` path in the same change. A second retry implementation
is a regression (parent doc Phase 3 explicitly forbids "a NEW parallel
`RetryPolicy` class that does not subsume `AutopilotPolicyConfig`").

## Scope

Owned files:

```text
py/swarm_do/pipeline/policies.py                         # NEW
py/swarm_do/pipeline/phase_autopilot_policy.py           # source of truth, untouched logic
py/swarm_do/pipeline/tests/test_policies.py              # NEW
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py # regression bar (7 tests)
```

Likely consumers (verified against current source):

```text
py/swarm_do/pipeline/phase_sessions.py        # imports ResolvedPolicyUpdate, profile_defaults,
                                              # retry_policy_config, validate_policy_overrides
                                              # (L25-30); owns DEFAULT_RETRY_POLICY duplication
                                              # at L74-90 and DEFAULT_LEASE_POLICY at L69-73
py/swarm_do/pipeline/phase_recovery.py        # the only evaluate_autopilot_policy callsite
                                              # (imports L13-17; calls at L357/L368)
py/swarm_do/pipeline/phase_pump.py            # duck-typed ResolvedPolicyUpdate access via
                                              # getattr(..., "forced_overrides", None) at
                                              # L326-327; reads
                                              # retry_policy["max_phase_attempt_budget_usd"]
                                              # at L124
py/swarm_do/pipeline/cli.py                   # imports ResolvedPolicyUpdate, expand_profile (L41)
py/swarm_do/pipeline/provider_review.py       # owns ReviewProviderPolicy dataclass (L111-130)
                                              # plus DEFAULT_MAX_PARALLEL=4 / DEFAULT_MIN_SUCCESS=1
py/swarm_do/pipeline/budget.py                # writer-tool/output-byte budgets — DIFFERENT
                                              # domain from cost-USD caps. Do not merge.
py/swarm_do/tui/app.py                        # _policy_summary (L744-758) reads only
                                              # review_providers/decompose/mem_prime today;
                                              # Preset editor "Budget & Policy" tab refresh_policy
                                              # at L3597-3615
```

Test files that already exist:

```text
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py   # 7 tests — regression bar
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_budget_estimator.py         # named *_estimator but covers budget.py
py/swarm_do/pipeline/tests/test_phase_sessions.py
py/swarm_do/pipeline/tests/test_phase_pump.py
```

Note: `budget_estimator.py` does **not** exist as a module — the canonical module is `budget.py`. Only the test file is named `test_budget_estimator.py` for historical reasons.

## Non-Goals

- No `CachePolicy`.
- No event envelope.
- No domain-contract sweep.
- No change to persisted phase-session policy fields unless a schema fragment
  and compatibility test are included.

## Out of Scope (explicit deferrals)

These items were considered and **explicitly deferred** so they don't get dropped between phases:

- **`DEFAULT_LEASE_POLICY` consolidation** (`phase_sessions.py:69-73`, duplicated in `phase_pump.py:1190-1191` and `phase_pump.py:1435-1436` via `or 14400` / `or 300` fallbacks). Lease ≠ retry. Defer to a follow-up.
- **`budget.py`** (writer-tool calls and output-byte caps — `DEFAULT_MAX_WRITER_TOOL_CALLS=60`, `DEFAULT_MAX_WRITER_OUTPUT_BYTES=60_000`, `DEFAULT_MAX_HANDOFFS=1` at L11-13). Different domain from `AutopilotPolicyConfig.max_failed_*_cost_usd` spend caps. Do not merge.
- **`TimeoutPolicy`** as a generic surface — no single caller exists today (timeouts live in `phase_autopilot_policy.py`, `provider_review.py` `DEFAULT_CLAUDE_R3_TIMEOUT_SECONDS`/`DEFAULT_CODEX_R2_TIMEOUT_SECONDS`, `catalog.py:739,760` `timeout_seconds: 1800`, `unit_sessions.py:51`, and `timeout_exec.py`). Deferred until one consolidating caller exists.
- **`FailureTolerancePolicy`, `WorktreeRecoveryPolicy`** (named in parent doc Phase 3 § Policy Objects). Deferred to a later phase. This plan covers `RetryPolicy` (via re-export of `AutopilotPolicyConfig`), `BudgetPolicy` (display-only), and `ProviderSelectionPolicy` (re-export of `ReviewProviderPolicy`) — three of the six.
- **Schema-fragment changes** to `schemas/phase_sessions.schema.json` (`$id` ends `#v1`, `schema_version: [1]`) or `schemas/phase_attempt_evidence.schema.json` (lines 239-249 reference the same `retry_policy` keys). State filename `phase_sessions.v1.json` (`phase_sessions.py:18`) is durable.
- **Renaming any value** in `POLICY_ACTIONS` / `POLICY_REASONS` / `POLICY_PROFILES` (`phase_autopilot_policy.py:9-32`). These strings are persisted into attempt evidence rows (`phase_attempts.py:129-132, 187-192, 299-307, 421-423` write `retry_decision`, `policy_action`, `policy_reason`, `policy_inputs`, `failure_retry_class`).

## Implementation Steps

1. **Add `policies.py`** as the canonical place for policy summaries and shared
   typed policy records.

2. **Re-export the full `phase_autopilot_policy.py` public surface** via explicit
   imports + `__all__`. Use direct re-export — **no wrapper classes, no
   `from x import *`**. Identity must be preserved because
   `phase_pump.py:326-327`, `phase_sessions.py:1450-1452`, and the
   `getattr(policy_update, 'forced_overrides', None)` pattern depend on the
   dataclass being passed through unchanged.

   All 12 public symbols (matches `__all__` at `phase_autopilot_policy.py:457-471`):

   - `AutopilotPolicyConfig` (frozen dataclass, 11 fields, L62-74)
   - `AutopilotPolicyInput` (19 fields, L77-98)
   - `AutopilotPolicyDecision` (8 fields, L101-110)
   - `ResolvedPolicyUpdate` (`forced_overrides`, `default_overrides`, L113-116)
   - `evaluate_autopilot_policy` (L158)
   - `fallback_retry_after_seconds` (L340)
   - `validate_policy_overrides` (L348)
   - `retry_policy_config` (L131) — used by `phase_sessions.py`, `phase_recovery.py`
   - `profile_defaults` (L119) — used by `phase_sessions.py`
   - `expand_profile` (L125) — used by `pipeline/cli.py:41`
   - `POLICY_PROFILES`, `POLICY_ACTIONS`, `POLICY_REASONS` — persisted enum strings (renaming forbidden)

   The plan's earlier 7-symbol list was a regression — `cli.py` would break.

3. **Collapse the `DEFAULT_RETRY_POLICY` duplication** at
   `phase_sessions.py:74-90`. This is the **load-bearing work of this phase.**

   Today, `DEFAULT_RETRY_POLICY` (16 keys including `max_session_attempts=2`,
   `max_recovery_attempts=1`, `recovery_timeout_threshold_seconds=600`,
   `short_retry_backoff_seconds=60`, `max_retry_after_seconds=1800`,
   `max_consecutive_same_failure_kind=2`, `autopilot_profile="standard"`, and
   the cost-USD caps) duplicates the `_positive_int(... default=...)` calls in
   `phase_autopilot_policy.retry_policy_config` (L137-151). The values are
   currently in sync; that is luck, not enforcement.

   Define defaults **once** in `phase_autopilot_policy.py` (e.g., expose a
   `DEFAULT_RETRY_POLICY_DICT` constant or a `default_retry_policy()`
   constructor) and re-export through `policies.py`. `phase_sessions.py`
   imports the constant. **Numeric values must match byte-for-byte** — the
   materialized dict is persisted into `data/runs/*/phase_sessions.v1.json` and
   reading old state files must continue to round-trip.

4. **Add a resolved-policy display helper** (`ResolvedPolicySummary`, frozen
   dataclass) for TUI/CLI/status code. Concrete shape:

   ```python
   @dataclass(frozen=True)
   class ResolvedPolicySummary:
       autopilot_profile: str
       retry: dict[str, Any]               # numeric retry/timeout fields from AutopilotPolicyConfig
       budget: dict[str, Any]              # cost-USD caps (max_failed_*_cost_usd, max_phase_attempt_budget_usd)
       review_providers: dict[str, Any] | None  # ReviewProviderPolicy.as_dict() or None
   ```

   First consumer: replace ad-hoc parsing in `tui/app.py:_policy_summary`
   (L744-758). **Do not change the rendered string format until tests pin it.**

   Rationale for dataclass over `TypedDict`: TUI already does dot/`getattr`
   access and the Phase 1 state-ownership pattern uses frozen dataclasses.
   `TypedDict` would force consumers to fork between `Mapping[str, Any]` and
   typed shapes.

5. **Add narrow policy records ONLY where a concrete caller exists today.**
   The original Step 4 was speculative; this is the verified-caller version:

   - **Provider selection**: keep `ReviewProviderPolicy` in
     `provider_review.py:111-130` (already a frozen dataclass with `as_dict()`).
     Re-export it from `policies.py`. **Do not introduce a parallel name.**
   - **Cost-USD budget summary** (display-only): expose existing fields from
     `AutopilotPolicyConfig` via `ResolvedPolicySummary.budget`. Do not touch
     `budget.py` — it covers writer-tool budgets, a separate domain
     (see Out of Scope).
   - **Timeout**: NO new policy record this phase. There is no single caller;
     timeouts live in 5+ modules. Deferred.

6. **Migrate consumers in this order** (smallest blast radius first), keeping
   behavior identical at each step before the next one starts:

   a. `phase_recovery.py` — 3 imports, single `evaluate_autopilot_policy`
      callsite at L368.
   b. `phase_sessions.py` — 4 imports + `DEFAULT_RETRY_POLICY` consolidation
      lands here.
   c. `phase_pump.py` — duck-typed `ResolvedPolicyUpdate` access; safest with
      direct re-export.
   d. `pipeline/cli.py` — operator-facing.
   e. Tests update last (`test_phase_autopilot_policy.py`,
      `test_phase_sessions.py`, `test_phase_pump.py`, plus new
      `test_policies.py`).

7. **Refine `validate_policy_overrides` error messages** to include the offending
   key name. Today they raise bare
   `ValueError("expected integer policy value, got {value!r}")` from
   `phase_autopilot_policy.py:441` and
   `ValueError("expected numeric policy threshold, got {value!r}")` at L451-452,
   wrapped to `PhaseSessionError(str(exc))` at `phase_sessions.py:1474-1477`.

   Refine to `f"policy[{key}] expected integer, got {value!r}"` (and analogous
   for floats). Verified against the 7 tests in
   `test_phase_autopilot_policy.py`: none assert exact string content, so this
   refinement is regression-safe.

## Compatibility Requirements

- Existing phase-session retry decisions must be byte-for-byte compatible where
  tests assert JSON output.
- `phase_autopilot_policy.py` imports must continue to work.
- Policy defaults must remain defined once. If a default is duplicated, the PR
  is not done.
- **`ResolvedPolicyUpdate` dataclass identity must survive re-export.** Code at
  `phase_pump.py:326-327` and `phase_sessions.py:1450-1452` uses
  `getattr(policy_update, "forced_overrides", None)` and accepts the type
  positionally. Wrappers and `TypedDict` substitution are forbidden.
- **`DEFAULT_RETRY_POLICY` numeric values** at `phase_sessions.py:74-90` must
  match `phase_autopilot_policy.retry_policy_config` defaults (L137-151)
  byte-for-byte once consolidated. They are in sync today; collapsing them must
  not drift.
- **`STATE_FILENAME = "phase_sessions.v1.json"`** (`phase_sessions.py:18`) is
  durable. Field reads/writes must be byte-identical for any
  `data/runs/*/phase_sessions.v1.json`. Validate via round-trip test in
  `test_phase_sessions.py`.
- Schema lockdowns: `swarm-do/schemas/phase_sessions.schema.json` (`#v1`) and
  `swarm-do/schemas/phase_attempt_evidence.schema.json`. No property changes.
- `POLICY_ACTIONS` (7 values), `POLICY_REASONS` (12 values), and
  `POLICY_PROFILES` (`"standard"`, `"dogfood"`, `"strict"`) are persisted enum
  strings — see `phase_attempts.py:131,306` writes. Do not rename, do not add
  or remove members in this phase.

## Concerns / Guardrails

**These are the loaded landmines. Mark them prominently and verify each before merge.**

> **C-1. Wrapper classes break duck-typed access.** `getattr(policy_update, "forced_overrides", None)` is used in three places (`phase_sessions.py:1451-1452`, `phase_pump.py:326-327`, plus `phase_recovery.py` flow). Any wrapper around `ResolvedPolicyUpdate` is a regression. **Re-export the dataclass directly. No wrappers, no `TypedDict` substitution.**

> **C-2. `DEFAULT_RETRY_POLICY` duplication is the most dangerous existing duplication.** `phase_sessions.py:74-90` silently shadows `phase_autopilot_policy.retry_policy_config` defaults. Drift between them would cause retry-resume behavior to diverge from new-run behavior. **Collapsing this duplication is the load-bearing work of this phase. The PR is not done without it.**

> **C-3. Cost-USD caps and writer-tool budgets are different domains.** `AutopilotPolicyConfig.max_failed_*_cost_usd` are spend gates evaluated in `evaluate_autopilot_policy`. `budget.DEFAULT_MAX_WRITER_TOOL_CALLS` is a per-attempt tool-call lint. **Do not introduce a `BudgetPolicy` that blends them.** A merged surface invites bugs in `evaluate_writer_budget` (`budget.py:88`).

> **C-4. `TimeoutPolicy` has no concrete consumer today.** Timeout values are scattered across `phase_autopilot_policy.py`, `provider_review.py`, `catalog.py`, `unit_sessions.py`, and `timeout_exec.py`. **Defer this surface; do not speculate.** Premature consolidation will fork yet another timeout source.

> **C-5. `POLICY_ACTIONS` / `POLICY_REASONS` strings are persisted into attempt evidence** (`phase_attempts.py:131,306`). Do not rename, do not add or remove members without an explicit migration plan in a future phase.

> **C-6. `isinstance` / type-positional acceptance is implicit.** `phase_pump.py:114` calls `_policy_update_has_values(policy_update)`. `phase_sessions.py:155` accepts `ResolvedPolicyUpdate | None`. Re-exporting the same class (not subclassing) is the only safe pattern.

> **C-7. Parent doc Phase 3 lists six policy objects; this plan covers three.** `FailureTolerancePolicy`, `WorktreeRecoveryPolicy`, and `TimeoutPolicy` are explicitly deferred (see Out of Scope). They must not get dropped between phases — track them as follow-up beads issues.

## Acceptance Criteria

- All 7 tests in `tests/test_phase_autopilot_policy.py` pass unchanged
  (regression bar — see Tests section for the test names).
- `DEFAULT_RETRY_POLICY` is no longer defined at `phase_sessions.py:74-90`;
  the dict is sourced from `policies.py` (or `phase_autopilot_policy.py`)
  with identical key set and identical numeric values.
- `policies.py` re-exports all 12 public symbols listed in Step 2 with
  `__all__` declared explicitly.
- `tui/app.py:_policy_summary` (or one initial consumer) reads
  `ResolvedPolicySummary` instead of raw `Mapping[str, Any]` — chosen as the
  smoke test for the new helper.
- `validate_policy_overrides` error messages include the offending key name
  (e.g., `policy[max_session_attempts] expected integer, got 'two'`).
- No new `TimeoutPolicy` or generic `BudgetPolicy` class is introduced.
- `provider_review.ReviewProviderPolicy` is re-exported from `policies.py`,
  not re-implemented.
- `data/runs/*/phase_sessions.v1.json` round-trip test exercises the
  consolidated defaults path and passes byte-identically.

## Tests

Required targeted tests (existence verified):

```text
py/swarm_do/pipeline/tests/test_policies.py            # NEW
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py
py/swarm_do/pipeline/tests/test_phase_sessions.py
py/swarm_do/pipeline/tests/test_phase_pump.py
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_budget_estimator.py
```

Regression bar — these 7 tests in `test_phase_autopilot_policy.py` must pass
unchanged:

- `test_human_gate_launcher_failure_uses_literal_decision`
- `test_deterministic_artifact_error_blocks`
- `test_same_failure_limit_blocks_before_retry_budget`
- `test_failed_spend_thresholds_use_known_provider_cost_only`
- `test_child_controlled_unknown_failure_can_retry`
- `test_retry_after_is_clamped`
- `test_dogfood_profile_defaults`

New `test_policies.py` cases:

- Re-export round-trip: every symbol in `policies.__all__` is the same object
  as the one in `phase_autopilot_policy` (`policies.X is phase_autopilot_policy.X`).
- `isinstance` parity: `ResolvedPolicyUpdate` constructed via `policies` is
  accepted by `phase_sessions._configure_retry_policy_in_state` and
  `phase_pump`'s duck-typed access.
- `ResolvedPolicySummary`: JSON-roundtrip of `dataclasses.asdict(summary)`
  against a known `AutopilotPolicyConfig` + `ReviewProviderPolicy` fixture.
- `validate_policy_overrides` deterministic-error messages: each invalid type
  produces a key-named error string.
- `DEFAULT_RETRY_POLICY` dict equality: assert `policies.default_retry_policy()`
  (or equivalent) returns a dict equal to the historical literal at
  `phase_sessions.py:74-90` (vendor the literal as a fixture for this assertion
  so future drift fails loudly).

Test invocation reminder (from project memory):
`cd swarm-do && PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_policies`

## Handoff Notes

Call out any policy-like dictionary that remains outside `policies.py`. If it
has only one caller and no reuse pressure, leave it alone and explain why.

Specifically expected residue (acceptable):

- `DEFAULT_LEASE_POLICY` at `phase_sessions.py:69-73` — not retry; deferred per
  Out of Scope.
- `budget.DEFAULT_MAX_WRITER_TOOL_CALLS` family — separate domain.
- Per-provider timeout constants in `provider_review.py`, `catalog.py`,
  `unit_sessions.py` — no consolidating caller yet.

If the writer finds an additional policy-shaped dict not listed above, surface
it in handoff notes with file:line and let a follow-up phase decide.

## Evidence Index (cited file:line references)

For traceability — the writer should not need to re-discover these:

- `phase_autopilot_policy.py`: docstring L1; `POLICY_PROFILES` L9;
  `POLICY_ACTIONS` L10-17; `POLICY_REASONS` L18-32;
  `DEFAULT_BACKOFF_SCHEDULE_SECONDS` L34; `_PROFILE_DEFAULTS` L36-48;
  `AutopilotPolicyConfig` L62-74; `AutopilotPolicyInput` L77-98;
  `AutopilotPolicyDecision` L101-110; `ResolvedPolicyUpdate` L113-116;
  `profile_defaults` L119; `expand_profile` L125; `retry_policy_config` L131
  (defaults at L137-151); `evaluate_autopilot_policy` L158;
  `fallback_retry_after_seconds` L340; `validate_policy_overrides` L348;
  `_positive_int` L441; `_optional_nonnegative_float` L451; `__all__` L457-471.
- `phase_sessions.py`: `SCHEMA_VERSION = 1` L17; `STATE_FILENAME` L18; imports
  L25-30; `DEFAULT_LEASE_POLICY` L69-73; `DEFAULT_RETRY_POLICY` L74-90;
  `_retry_policy_with_update` L1473-1477; `_configure_retry_policy_in_state`
  L1450-1452.
- `phase_recovery.py`: imports L13-17; `evaluate_autopilot_policy` callsite
  L368.
- `phase_pump.py`: imports L29; `retry_policy["max_phase_attempt_budget_usd"]`
  read L124; duck-typed `forced_overrides` access L326-327; lease defaults at
  L1190-1191, L1435-1436.
- `cli.py`: `from .phase_autopilot_policy import ResolvedPolicyUpdate, expand_profile`
  L41.
- `provider_review.py`: `SELECTIONS` L45; `DEFAULT_MAX_PARALLEL` L46;
  `DEFAULT_MIN_SUCCESS` L47; `ReviewProviderPolicy` L111-130; `_merge_policy`
  L438-453.
- `budget.py`: `DEFAULT_MAX_WRITER_TOOL_CALLS=60` L11;
  `DEFAULT_MAX_WRITER_OUTPUT_BYTES=60_000` L12; `DEFAULT_MAX_HANDOFFS=1` L13;
  `BudgetEstimate` L17; `WriterBudgetResult` L31; `evaluate_writer_budget` L88.
- `phase_attempts.py`: `policy_action`, `policy_reason`, `policy_inputs`,
  `failure_retry_class`, `retry_decision` writes at L129-132, L187-192,
  L299-307, L421-423.
- `tui/app.py`: `_policy_summary` L744-758; phase_table `policy` column
  L1718-1730; attempt-row policy display L1994-2001; Preset editor
  "Budget & Policy" tab and `refresh_policy` L3344, L3393-3396, L3597-3615,
  L3693-3712.
- Schemas: `swarm-do/schemas/phase_sessions.schema.json` (`$id` ends `#v1`,
  `schema_version` enum `[1]`; `lease_policy` L31-46; `retry_policy` L47+);
  `swarm-do/schemas/phase_attempt_evidence.schema.json` L239-249.
- Parent doc: `swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md`
  L671-720 (Phase 3 § Policy Objects); explicit forbid of parallel
  `RetryPolicy` at L685-695.
