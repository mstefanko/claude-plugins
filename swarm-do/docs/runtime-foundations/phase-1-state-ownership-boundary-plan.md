# Phase 1 - State Ownership Boundary

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 1

## Objective

Finish the state ownership seam that is already partially present in
`prepared_artifact_writer.py`. Promote the existing Protocols to a shared
module, add thin owner wrappers for other state families, and add a write fence
so new direct state writes are caught in review.

## Why This Lands First

This is not a storage migration. It is a boundary-setting refactor. The repo
already has direct writers for phase sessions, stage sessions, prepared
artifacts, run events, worktree manifests, evidence, and shared decisions. If
Phase 4 trace/eval and Phase 4.5 projection read those shapes before ownership
is explicit, they will fossilize today's spread of write paths.

The existing code supports this direction:

- `prepared_artifact_writer.py` already defines `RunStateTxn`,
  `RunStateStore`, and `JsonRunStateStore`.
- `phase_autopilot_policy.py`, `phase_evidence.py`, and `phase_decisions.py`
  already own their own typed/schema-versioned surfaces.
- `run_state.py` already centralizes run event appends.

## Scope

Owned files:

```text
py/swarm_do/pipeline/state_store.py
py/swarm_do/pipeline/prepared_artifact_writer.py
py/swarm_do/pipeline/phase_session_store.py
py/swarm_do/pipeline/worktree_state_store.py
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_state_store_write_fence.py
```

Existing owner modules remain owners in this phase:

```text
py/swarm_do/pipeline/phase_sessions.py
py/swarm_do/pipeline/stage_sessions.py
py/swarm_do/pipeline/phase_decisions.py
py/swarm_do/pipeline/phase_evidence.py
py/swarm_do/pipeline/phase_beads.py
py/swarm_do/pipeline/run_state.py
py/swarm_do/pipeline/execution_worktree.py
```

Consumer modules must not become direct writers:

```text
py/swarm_do/pipeline/phase_pump.py
py/swarm_do/pipeline/stage_controller.py
py/swarm_do/pipeline/claude_stream.py
```

## Non-Goals

- No canonical SQLite backend.
- No persisted JSON shape changes.
- No broad rewrite of `phase_sessions.py` internals.
- No event envelope, hooks, reducers, or operator decisions.
- No attempt to make git worktree operations transactional.

## Implementation Steps

1. Add `state_store.py` and move or re-declare the shared Protocols:
   `RunStateTxn`, `RunStateStore`, `PreparedArtifactStore`,
   `PhaseSessionStore`, `WorktreeStateStore`, and `RunEventSink`.
2. Keep compatibility re-exports from `prepared_artifact_writer.py` if any
   caller imports the existing Protocol names from there.
3. Add `phase_session_store.py` as a thin wrapper over existing
   `phase_sessions.py` functions. It should delegate, not duplicate schema or
   validation logic.
4. Add `worktree_state_store.py` as a thin wrapper over existing worktree
   manifest helpers. Reads that affect mutation must reconcile against git.
5. Move orchestration-level direct writes behind the wrappers one family at a
   time. Prefer small call-site changes over module moves.
6. Add a write-fence test that scans for direct writes to core state filenames
   outside the owner modules. The whitelist must be explicit and reviewed.
7. Verify that the streaming plan's new `stage_controller.py` and
   `claude_stream.py`, if already present, are consumers only.

## Write Fence Shape

The fence should fail on new direct writes to:

```text
phase_sessions.v1.json
stage_sessions.v1.json
shared_decisions.v1.json
operator_decisions.v1.json
prepared_plan.v1.json
run_events.jsonl
active_run.json
manifest.json
evidence.json
```

The test can be textual, but keep it narrow enough to avoid false positives in
fixtures and docs. If a whitelist exception is added, the PR must explain why
that module owns the state family.

## Acceptance Criteria

- Existing persisted file paths and JSON shapes are unchanged.
- Existing imports of prepared artifact writer store Protocols still work or
  are migrated in the same PR.
- New store APIs are small enough that a JSON or SQLite implementation could
  sit behind them later.
- Consumer modules do not open/write core state files directly.
- Phase 4 trace/eval can read through the seam or through existing read helpers
  without learning extra writer details.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_state_store_write_fence.py
py/swarm_do/pipeline/tests/test_prepared_artifact_writer.py
```

Regression boundary:

```text
py/swarm_do/pipeline/tests/test_phase_sessions.py
py/swarm_do/pipeline/tests/test_phase_pump.py
py/swarm_do/pipeline/tests/test_phase_recovery.py
py/swarm_do/pipeline/tests/test_phase_crash_resume.py
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_post_writer_report.py
py/swarm_do/pipeline/tests/test_execution_worktree.py
```

## Handoff Notes

Call out every direct writer that remains and why. If the fence has to skip a
file family, record that as a follow-up blocker for Phase 4.5.
