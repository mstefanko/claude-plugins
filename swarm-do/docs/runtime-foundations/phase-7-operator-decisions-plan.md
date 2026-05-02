# Phase 7 - Operator Decisions

Date: 2026-05-02
Status: active implementation plan after Phases 1 and 2
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 7

## Objective

Represent mutating human recovery choices as auditable operator decision
artifacts. Normal happy-path pumping should not depend on these records.

## Senior Implementation Decision

Scope this to recovery commands only. The useful pattern from LangGraph is the
contract shape: pause with a value, resume with an explicit command. SwarmDaddy
does not need `interrupt()` inside its runner.

Also keep the name explicit. `phase_decisions.py` already means shared
controller-promoted decisions between phases. This phase is about human
operator recovery choices.

## Scope

Owned files:

```text
py/swarm_do/pipeline/operator_decisions.py
py/swarm_do/pipeline/tests/test_operator_decisions.py
```

Artifact:

```text
operator_decisions.v1.json
```

CLI surfaces:

```text
swarm decisions record <run-id> ... --json
swarm decisions apply <run-id> <decision-id> --json
```

## Dependencies

- Phase 1 state store wrappers, so decision writes route through the same owner
  boundary.
- Phase 2 domain records for status/recovery summaries.
- Phase 4 eval fixtures for at least one recovery flow, so decision application
  is testable without live model calls.

Does not depend on the deferred event envelope.

## Non-Goals

- No generic workflow interrupt system.
- No public plugin API.
- No happy-path requirement that every normal phase transition has an operator
  decision.
- No rename or merger of `phase_decisions.py`.

## Decision Types

P0 decision types:

```text
resume_with_input
retry_phase
reset_phase
rebuild_worktree
archive_attempt
cancel_run
abort_phase
accept_provider_partial
```

Defer `skip_best_effort_stage` unless the live stage marker work has a concrete
recovery command that needs it.

## Implementation Steps

1. Add `OperatorDecision` and `OperatorDecisionStore` in
   `operator_decisions.py`.
2. Store records in `operator_decisions.v1.json` beside phase-session state.
3. Include stable `decision_id`, `run_id`, `kind`, `created_at`, `operator`,
   `payload`, `status`, and `applied_at`.
4. Make `decision_id` idempotent. Re-recording or reapplying the same decision
   is either a no-op or a controlled error with JSON output.
5. Add record/apply CLI commands.
6. Integrate mutating recovery commands one at a time. Start with the command
   that has the clearest existing test coverage.
7. Add a docstring sentence to `phase_decisions.py` that distinguishes shared
   phase decisions from operator decisions.
8. Let `phases status --events` or equivalent status output show recent
   operator decisions after the artifact exists.

## Acceptance Criteria

- Every integrated recovery mutation can point to the operator decision that
  caused it.
- Reapplying a decision is deterministic.
- Existing recovery commands remain usable.
- Help text and errors say "operator decision" to avoid confusion with shared
  phase decisions.
- No happy-path pump flow requires an operator decision record.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_operator_decisions.py
py/swarm_do/pipeline/tests/test_phase_recovery.py
py/swarm_do/pipeline/tests/test_phase_cli.py
py/swarm_do/pipeline/tests/test_run_eval.py
```

## Handoff Notes

List which recovery commands are decision-backed and which are not yet
integrated. Do not imply full recovery coverage until each mutating command is
actually wired.
