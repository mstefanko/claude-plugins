# Phase 3 - Policy Consolidation

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 3

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
is a regression.

## Scope

Owned files:

```text
py/swarm_do/pipeline/policies.py
py/swarm_do/pipeline/phase_autopilot_policy.py
py/swarm_do/pipeline/tests/test_policies.py
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py
```

Likely consumers:

```text
py/swarm_do/pipeline/provider_review.py
py/swarm_do/pipeline/budget_estimator.py
py/swarm_do/tui/
```

## Non-Goals

- No `CachePolicy`.
- No event envelope.
- No domain-contract sweep.
- No change to persisted phase-session policy fields unless a schema fragment
  and compatibility test are included.

## Implementation Steps

1. Add `policies.py` as the canonical place for policy summaries and shared
   typed policy records.
2. Re-export or wrap these existing phase-autopilot surfaces:
   - `AutopilotPolicyConfig`;
   - `AutopilotPolicyInput`;
   - `AutopilotPolicyDecision`;
   - `ResolvedPolicyUpdate`;
   - `evaluate_autopilot_policy`;
   - `fallback_retry_after_seconds`;
   - `validate_policy_overrides`.
3. Add a resolved-policy display helper that TUI/status/doctor code can use
   without parsing raw policy dictionaries repeatedly.
4. Add narrow policy records only where there is a concrete caller:
   - timeout policy for provider/launcher timeouts;
   - budget policy for budget previews and spend gates;
   - provider selection policy for provider review quorum/parallelism.
5. Migrate one consumer at a time to read via `policies.py`. Keep behavior
   identical before adding any new policy knobs.
6. Add deterministic error messages for invalid policy input.

## Compatibility Requirements

- Existing phase-session retry decisions must be byte-for-byte compatible where
  tests assert JSON output.
- `phase_autopilot_policy.py` imports must continue to work.
- Policy defaults must remain defined once. If a default is duplicated, the PR
  is not done.

## Acceptance Criteria

- Existing autopilot policy tests pass unchanged or with only import-location
  updates that preserve behavior.
- `policies.py` is the single surface for resolved policy summaries.
- Invalid policy input produces operator-readable errors.
- Provider review and budget policy callers do not create ad-hoc retry/timeout
  dictionaries outside the policy surface.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_policies.py
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_budget_estimator.py
```

## Handoff Notes

Call out any policy-like dictionary that remains outside `policies.py`. If it
has only one caller and no reuse pressure, leave it alone and explain why.
