# Phase 4 - Run Trace, Replay, And Eval

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 4

## Objective

Create a read-only trace and fixture-backed eval harness over durable run
artifacts. The harness should verify control-plane behavior without live
Claude/Codex calls.

## Why This Is The Behavioral Test Net

SwarmDaddy is a local development harness. Its highest leverage reliability
move is not a richer graph runtime; it is being able to replay and assert what
the control plane did from the artifacts it already wrote. This phase should
make later refactors safer, especially the read-only projector and any future
state backend change.

## Dependencies

Can start while Phase 1 is in progress:

- P0 reads existing JSON artifacts directly through current helper functions.
- Once Phase 1 lands, move reads behind `state_store.py` or owner readers where
  that reduces duplication.
- Do not wait for Phase 4.5. The projector should consume this harness, not
  block it.

Coordinate with the live stage marker streaming plan. `AttemptTrace` must carry
`command.json.stage_controller` counters as opaque optional metadata when they
exist.

## Scope

Owned files:

```text
py/swarm_do/pipeline/run_trace.py
py/swarm_do/pipeline/run_eval.py
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
tests/fixtures/run-traces/
docs/eval-recipes.md
```

CLI surfaces:

```text
swarm trace build <run-id> --json
swarm eval run <fixture-dir>
```

## Non-Goals

- No deterministic replay of model reasoning.
- No live Claude/Codex calls in unit tests.
- No new source of truth for state.
- No SQLite dependency in P0.
- No event envelope or hook lifecycle.

## Trace Shape

`RunTrace` is a derived view:

```text
schema_version
run_id
source_paths
phases[]
attempts[]
provider_runs[]
worktree_events[]
run_events[]
artifacts[]
summary
```

`AttemptTrace` should include:

- phase id and attempt number;
- launcher and command metadata path;
- prompt, stdout, stderr, result, handoff, evidence paths;
- failure kind and retry decision;
- token/cost metrics when known;
- changed files summary when known;
- optional `stage_controller` metadata from `command.json`.

Keep trace JSON versioned from the first PR.

## Implementation Steps

1. Add dataclasses or small typed records for `RunTrace` and `AttemptTrace` in
   `run_trace.py`. They are internal trace contracts, not persisted source
   state.
2. Add readers for prepared plan, phase sessions, per-attempt evidence,
   provider review outputs, run events, and worktree manifest observations.
   Missing optional artifacts should become trace warnings, not hard crashes,
   unless the eval case marks them required.
3. Add `swarm trace build <run-id> --json`.
4. Add `run_eval.py` with a fixture format that includes expected transitions,
   required artifacts, and expected recovery recommendations.
5. Add golden fixture families:
   - clean single phase;
   - needs input;
   - retryable failure then success;
   - provider-review partial success;
   - worktree drift;
   - malformed result artifact;
   - streaming run with early stage adoption metadata when the streaming plan
     has landed.
6. Add `swarm eval run <fixture-dir>` with failure output that names the first
   unexpected transition or missing artifact.
7. Update `docs/eval-recipes.md` with how to add fixtures and how to dogfood
   against a real run directory.

## Eval Assertions

P0 assertions should cover:

- phase/session status transition order;
- attempt count and retry decisions;
- required evidence files;
- malformed artifact classification;
- provider review quorum/partial-success handling;
- worktree drift detection;
- presence and shape of run events;
- streaming `stage_controller` metadata when present.

## Acceptance Criteria

- Trace generation is read-only.
- A fixture can validate orchestration behavior without live model calls.
- Failed eval output is actionable and names the first mismatch.
- Trace JSON is versioned.
- The harness can run before and after Phase 4.5 and compare behavior.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
```

Also run the Phase 1 regression tests if trace readers touch state helper
paths.

## Handoff Notes

List every artifact family the trace does not yet cover. Those gaps become
schema inputs for Phase 4.5 instead of being silently worked around in SQL.
