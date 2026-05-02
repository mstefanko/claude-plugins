# Phase 1 - State Ownership Boundary

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 1
Pre-flight review: `docs/runtime-foundations/phase-1-review.md` (2026-05-02)

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

The existing code supports this direction (verified 2026-05-02):

- `prepared_artifact_writer.py:35,43,79` already defines `RunStateTxn`,
  `RunStateStore`, and `JsonRunStateStore`; re-exported via `__all__` at
  line 507-511. **No external module imports these names today**, so the
  Protocol move is a clean rename.
- `phase_evidence.py:16-17` (`MANIFEST_SCHEMA_VERSION = 1`, `MANIFEST_FILENAME
  = "evidence.json"`) and `phase_decisions.py:13-14` (`SCHEMA_VERSION = 1`,
  `SHARED_DECISIONS_FILENAME = "shared_decisions.v1.json"`) already own
  schema-versioned surfaces. `phase_autopilot_policy.py` owns its policy
  surface but is not directly touched by this phase.
- `run_state.py` already centralizes run event appends (`append_run_event`,
  `write_active_run`, `load_active_run`) and the `run_events.jsonl` /
  `active_run.json` paths.

## Prior Art

The repo already contains a working AST-based fence: `tests/test_prepared_artifact_fence.py`
uses an `ast.NodeVisitor` (`_GitBaseWriteVisitor`) to ensure only
`prepared_artifact_writer.py` writes the `git_base_sha` field, exempting
`tests/` and the writer module itself. The new state-store fence MUST follow
the same pattern (visit write-call expressions; exempt the owner modules and
`tests/`) rather than a textual scan. See "Write Fence Shape" below.

## Scope

Owned files:

```text
py/swarm_do/pipeline/state_store.py
py/swarm_do/pipeline/prepared_artifact_writer.py
py/swarm_do/pipeline/phase_session_store.py
py/swarm_do/pipeline/worktree_state_store.py
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_state_store_write_fence.py
py/swarm_do/pipeline/tests/state_store_fence_allowlist.txt
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

Consumer modules must not become direct **writers** (reads of resolved paths
remain allowed; see "Write Fence Shape"):

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
- **No `stage_sessions` wrapper (`stage_session_store.py`)** — deferred to
  Phase 1.5 follow-up to keep blast radius bounded.
- **No write-site sweep of `mco_stage.py`, `prepare.py`, `decompose.py`,
  `context_bundle.py`, `plan.py`, or sidecar artifact writes in
  `phase_pump.py`** — deferred. Those write sidecar files
  (stdout/stderr/command.json/launcher_prompt), not core state.

## `state_store.py` Coupling Rule

**GUARDRAIL:** `state_store.py` defines Protocols only. It MUST NOT import from
any owner module (`phase_sessions`, `stage_sessions`, `phase_evidence`,
`phase_decisions`, `execution_worktree`, `run_state`,
`prepared_artifact_writer`). Owner modules may import Protocols from
`state_store.py`; the dependency is one-way. Shared exception types
(e.g. `PhaseSessionLockTimeout`) stay in their owner modules; Protocol typing
is structural, not nominal. A circular import here will cascade across the
pipeline.

## Implementation Steps

1. Add `state_store.py` and move the shared Protocols into it: `RunStateTxn`,
   `RunStateStore`, `PreparedArtifactStore`, `PhaseSessionStore`,
   `WorktreeStateStore`, and `RunEventSink`. Each Protocol exposes ≤ 6 methods.

2. The Protocol names (`RunStateTxn`, `RunStateStore`, `JsonRunStateStore`) are
   currently defined in `prepared_artifact_writer.py` and re-exported via
   `__all__` (lines 507-511). Verified 2026-05-02: no external module imports
   these names. The move to `state_store.py` is therefore a clean rename —
   leave `prepared_artifact_writer.py`'s `__all__` re-exports as a courtesy
   (no callers, but cheap to keep).

3. Add `phase_session_store.py` as a **thin wrapper** that forwards only the
   following public functions of `phase_sessions.py`: `init_phase_sessions`,
   `record_phase_result`, `phase_session_path`, `phase_session_lock_path`,
   `phase_handoff_path`, `phase_result_path`, plus the public lock context
   manager. **Do not** wrap private helpers (`_touch_and_write`,
   `_normalize_state`, etc.) and **do not** refactor the policy-update /
   retry-policy / state-machine internals — those stay inside
   `phase_sessions.py`. (See CONCERN: `phase_sessions.py` is ~1700 lines; a
   literal "thin wrapper" only forwards a small public surface.)

4. Add `worktree_state_store.py` as a thin wrapper over the public surface of
   `execution_worktree.py`: `materialize_run_execution_worktree`,
   `commit_stage_artifacts`, `adopt_run_worktree`, `integrate_run_worktree`,
   plus the resolution helpers. The "reads that affect mutation must reconcile
   against git" rule **captures the existing behavior** of
   `materialize_run_execution_worktree` (which calls
   `_classify_existing_manifest` at line 251 before writing). It is **not** a
   new invariant.

5. Migrate one family at a time, in this order. **Stop after the named family
   if scope pressure rises** — this is a hard rule, not a guideline:
   1. `prepared_artifact` — Protocols already exist; pure rename to `state_store.py`.
   2. `run_state` — already centralized; add `RunEventSink` Protocol, no call-site changes.
   3. `phase_evidence` and `phase_decisions` — small surfaces, schema-versioned, low risk.
   4. `worktree_state_store` — wrap existing, capture-existing-behavior only.
   5. `phase_session_store` — largest wrap target, do last.

   **Out of scope** for this PR (file as Phase 1.5 follow-ups): `stage_sessions`
   wrapper, write-site sweeps of `mco_stage.py` / `prepare.py` / `decompose.py`
   / `context_bundle.py` / `plan.py`, and sidecar artifact writes from
   `phase_pump.py`.

6. Add a write-fence test that uses an AST visitor (modeled on
   `tests/test_prepared_artifact_fence.py`) to scan for direct writes to core
   state filenames outside the owner modules. The whitelist must be explicit
   and reviewed (see "Write Fence Shape").

7. Verify that `stage_controller.py` and `claude_stream.py` (both already on
   disk as of 2026-05-02) remain consumers only. **Note:**
   `stage_controller.py:13-16` already imports owner-side helpers
   (`phase_beads`, `run_state.append_run_event`); `claude_stream.py` is a pure
   dataclass module that touches no state. No code changes expected here —
   this is a regression check.

## Write Fence Shape

**GUARDRAIL: Use AST, not text.** A textual contains-check on filenames like
`manifest.json` will both miss legitimate writes (because
`provider-review.manifest.json` matches the substring) and produce false
positives in fixtures and docstrings. Follow the precedent at
`tests/test_prepared_artifact_fence.py`.

The fence walks every `*.py` file under `py/swarm_do/pipeline/` outside
`tests/` and the owner modules listed in the table below. It flags any `Call`
node where:

- The receiver is a `Path` expression resolving to one of the protected
  filename literals, AND
- The call name is in `{write_text, write_bytes, write, dump}` OR the call is
  `open(..., "w" | "a" | "wb" | "ab")` followed by a write.

Initial fence whitelist (filename → owner module):

| Filename                   | Owner module                                                |
|----------------------------|-------------------------------------------------------------|
| `phase_sessions.v1.json`   | `phase_sessions.py`                                         |
| `stage_sessions.v1.json`   | `stage_sessions.py`                                         |
| `shared_decisions.v1.json` | `phase_decisions.py`                                        |
| `prepared_plan.v1.json`    | `prepared_artifact_writer.py`, `prepare.py`                 |
| `run_events.jsonl`         | `run_state.py`                                              |
| `active_run.json`          | `run_state.py`                                              |
| `evidence.json`            | `phase_evidence.py`                                         |
| `manifest.json`            | `execution_worktree.py` (path-component-scoped: parent dir matches `worktrees/<run-id>/`) |

**Update:** `operator_decisions.v1.json` was intentionally excluded from the
initial fence because the file family did not exist yet; Phase 7 adds it with
`operator_decisions.py` as the owner module.

The fence is for **writes only**. Direct path-resolution **reads** (e.g.
`phase_pump.py:2072,2092` resolves a `prepared_plan.v1.json` path for read
access) are out of scope. The boundary protects mutation, not lookup.

If a whitelist exception is added, the PR must (a) explain why that module
owns the state family and (b) record the exemption in
`tests/state_store_fence_allowlist.txt` with a one-line justification. CI
fences off new entries; review approves them. **No `pytest.skip` escapes** —
either the entry is in the allowlist or the test fails.

## Acceptance Criteria

Each criterion below has a concrete verifiable signal so a writer agent can
check off completion:

- **Persisted file paths and JSON shapes are unchanged.**
  Signal: `find data/runs -type f` before/after produces identical sets; any
  test fixture diff is empty.

- **Protocol names move from `prepared_artifact_writer.py` to
  `state_store.py` in the same PR.**
  Signal: `__all__` re-exports remain in the writer module as a no-op
  courtesy. (Verified 2026-05-02: no external callers import these names —
  see review §C-30.)

- **New store Protocols expose ≤ 6 methods each.**
  Signal: `grep -c "^    def " state_store.py` per Protocol class ≤ 6;
  arguments are restricted to `run_id`, `phase_id`, payload `Mapping[str,
  Any]`, and `Path`-resolved inputs. No methods leak `dict[str, Any]`
  schema-version internals.

- **Consumer modules (`phase_pump.py`, `stage_controller.py`,
  `claude_stream.py`) do not write core state files directly.**
  Signal: the new write-fence test is green.

- **Fence allowlist is documented, not skipped.**
  Signal: `tests/state_store_fence_allowlist.txt` lists every documented
  exemption with justification; no `pytest.skip` escapes in the fence test.

- **Phase 4 trace/eval can read through the seam or through existing read
  helpers without learning extra writer details.**
  Signal: review-time check; no new read APIs introduced in this PR.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_state_store.py                 (new)
py/swarm_do/pipeline/tests/test_state_store_write_fence.py     (new)
py/swarm_do/pipeline/tests/test_prepare_artifact.py            (existing — Protocol-name imports may need touch)
py/swarm_do/pipeline/tests/test_prepared_artifact_fence.py     (existing — AST precedent for the new fence)
```

Regression boundary (verified all seven exist on disk):

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
file family, record that in `tests/state_store_fence_allowlist.txt` with
justification, and file a follow-up blocker for Phase 4.5.

Known follow-ups deferred from this phase:

- **`operator_decisions.v1.json` family** is added by Phase 7 with
  `operator_decisions.py` as the owner module.
- **`stage_sessions` wrapper** (`stage_session_store.py`) is intentionally
  not in this PR; defer to Phase 1.5.
- **Direct-write call sites** in `mco_stage.py`, `prepare.py`, `decompose.py`,
  `context_bundle.py`, `plan.py`, and launch-artifact writes in `phase_pump.py`
  are out of scope for this PR. These write *sidecar* files (stdout/stderr/
  command.json/launcher_prompt), not core state — confirm during the next pass
  that they are truly sidecars and don't belong in the fence.
