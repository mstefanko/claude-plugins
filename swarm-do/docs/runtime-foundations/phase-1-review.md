# Phase 1 — State Ownership Boundary: Pre-Flight Review

Date: 2026-05-02
Reviewer: agent-analysis (pre-flight gut check, not implementation)
Plan under review: `swarm-do/docs/runtime-foundations/phase-1-state-ownership-boundary-plan.md`

---

## 1. Verdict

**Ready with revisions.** The plan's core premise holds: the Protocol seam in `prepared_artifact_writer.py` exists exactly as claimed (`RunStateTxn` at line 35, `RunStateStore` at line 43, `JsonRunStateStore` at line 79), the named owner modules exist with versioned schemas, and the consumer modules (`stage_controller.py`, `claude_stream.py`) already exist on disk. However, three issues block straight execution: **(a) one named regression test does not exist** (`test_prepared_artifact_writer.py` — see EVIDENCE GAP G-1), **(b) the write-fence test scope is under-specified** while a precedent AST-based fence already exists in `test_prepared_artifact_fence.py` that the plan does not reference, and **(c) the plan's "consumer modules must not become direct writers" claim is partially false today** — `stage_controller.py` already imports `append_run_event` from `run_state` (line 16), which is correct (it goes through the owner), but `phase_pump.py` writes directly to `prepared_plan.v1.json`-shaped paths at lines 2072-2123 in addition to going through owners. The "one family at a time" sweep is unsequenced. Address the items in §5 before kickoff; the boundary refactor itself is sound.

---

## 2. Evidence Verification Table

| # | Plan Claim | Status | Evidence |
|---|---|---|---|
| C-1 | `prepared_artifact_writer.py` defines `RunStateTxn` | **VERIFIED** | `prepared_artifact_writer.py:35` `class RunStateTxn(Protocol):` with `__enter__`/`__exit__` |
| C-2 | `prepared_artifact_writer.py` defines `RunStateStore` | **VERIFIED** | `prepared_artifact_writer.py:43` `class RunStateStore(Protocol):` with `load()` and `begin()` |
| C-3 | `prepared_artifact_writer.py` defines `JsonRunStateStore` | **VERIFIED** | `prepared_artifact_writer.py:79` `class JsonRunStateStore:` (note: no explicit `RunStateStore` base — duck-typed against the Protocol) |
| C-4 | Names re-exported from module | **VERIFIED** | `prepared_artifact_writer.py:507-511` lists `JsonRunStateStore`, `RunStateStore`, `RunStateTxn` in `__all__` |
| C-5 | `phase_autopilot_policy.py` owns its own typed/schema-versioned surface | **PARTIALLY VERIFIED** | File exists; grep returned only function/class signatures, no `SCHEMA_VERSION` constant surfaced. **Verify locally** before treating "schema-versioned" as load-bearing. |
| C-6 | `phase_evidence.py` owns its own schema-versioned surface | **VERIFIED** | `phase_evidence.py:16` `MANIFEST_SCHEMA_VERSION = 1`, `phase_evidence.py:17` `MANIFEST_FILENAME = "evidence.json"`, public `write_attempt_evidence_manifest` at line 174 |
| C-7 | `phase_decisions.py` owns its own schema-versioned surface | **VERIFIED** | `phase_decisions.py:13` `SCHEMA_VERSION = 1`, public `add_shared_decision`, `load_shared_decisions`, `_validate_shared_decisions` |
| C-8 | `run_state.py` centralizes run event appends | **VERIFIED** | `run_state.py:63` references `telemetry / "run_events.jsonl"`; module exports `append_run_event`, `validate_run_event`, `active_run_path`, `write_active_run`, `load_active_run` (used by `phase_pump`, `stage_controller`, `prepared_artifact_writer`). |
| C-9 | `phase_sessions.py` exists as a state owner | **VERIFIED** | File exists; `phase_session_path` at line 117, `init_phase_sessions` at line 145, internal `_touch_and_write` at line 1621 (file is ~1700 lines — non-trivial to wrap; see CONCERN-1) |
| C-10 | `stage_sessions.py` exists as a state owner | **VERIFIED** | `stage_session_path` at line 43, `init_stage_sessions` at line 79, `claim_stage` at line 130, `_touch_and_write` at line 395 |
| C-11 | `phase_beads.py` exists as a state owner | **VERIFIED** | File exists; module-level functions like `close_stage_child`, `mark_stage_blocked` imported by `stage_controller.py:13` |
| C-12 | `execution_worktree.py` exists as worktree owner | **VERIFIED** | `manifest_path = control_run_root / "manifest.json"` at line 206; `_write_manifest` invocation at line 279, line 432; `materialize_run_execution_worktree` at line 233 |
| C-13 | `phase_pump.py` exists | **VERIFIED** | 86 KB, 2000+ lines — by far the largest file in the dir |
| C-14 | `stage_controller.py` exists ("if already present") | **VERIFIED** | 469 lines; imports owner modules (`phase_sessions`, `phase_beads`, `run_state`, `stage_sessions`, `execution_worktree`, `post_writer`) — already a good consumer pattern |
| C-15 | `claude_stream.py` exists ("if already present") | **VERIFIED** | 86 lines; pure dataclass/typing module — only imports `json`, `dataclasses`, `typing`. **Already a clean consumer** (in fact, doesn't even touch state). |
| C-16 | `phase_sessions.v1.json` is a real persisted filename | **VERIFIED** | Referenced in `resume.py:254`, test fixtures, archives |
| C-17 | `stage_sessions.v1.json` is a real persisted filename | **VERIFIED** | Referenced in `writer_phase_selftest.py:74`, test fixtures |
| C-18 | `prepared_plan.v1.json` is a real persisted filename | **VERIFIED** | Referenced in `resume.py:239`, `context_bundle.py:104`, `phase_pump.py:2072,2092`, etc. |
| C-19 | `run_events.jsonl` is a real persisted filename | **VERIFIED** | `run_state.py:63`, `resume.py:188` |
| C-20 | `evidence.json` is a real persisted filename | **VERIFIED** | `phase_evidence.py:17` `MANIFEST_FILENAME = "evidence.json"` |
| C-21 | `manifest.json` is a real persisted filename | **VERIFIED** | `execution_worktree.py:206,442` (worktree manifests) |
| C-22 | `shared_decisions.v1.json` is a real persisted filename | **PARTIALLY VERIFIED** | `phase_decisions.shared_decisions_path` exists at line 17 but the literal filename string was not surfaced in the grep. **EVIDENCE GAP G-2** — confirm the on-disk filename exactly matches `shared_decisions.v1.json` (could be `.json` without `.v1.`). |
| C-23 | `operator_decisions.v1.json` is a real persisted filename | **EVIDENCE GAP G-3** | Grep for `operator_decisions` returned **no hits anywhere in the codebase**. Either this file family does not exist yet (premature in the fence list) or it is named differently. |
| C-24 | `active_run.json` is a real persisted filename | **VERIFIED** | `run_state.py:22` `active_run_path`, `run_state.py:30` `write_active_run`, callers throughout `phase_pump.py:2106,2123` |
| C-25 | Existing test `test_prepared_artifact_writer.py` exists | **EVIDENCE GAP G-1** | **Does not exist**. The closest existing test is `test_prepare_artifact.py` (note: no `d`) and the AST-fence at `test_prepared_artifact_fence.py`. The plan must either rename or note that a new file is being added. |
| C-26 | Other regression test files exist (`test_phase_sessions`, `test_phase_pump`, `test_phase_recovery`, `test_phase_crash_resume`, `test_provider_review`, `test_post_writer_report`, `test_execution_worktree`) | **VERIFIED** | All seven exist on disk |
| C-27 | "Consumer modules must not become direct writers" — `stage_controller.py` is currently a consumer | **VERIFIED (today)** | Imports go through owners (`stage_sessions`, `phase_beads`, `run_state.append_run_event`); writes via `commit_stage_artifacts` (worktree owner). No direct `*.v1.json` writes in this module. |
| C-28 | `claude_stream.py` is a consumer | **VERIFIED (trivially)** | Only imports `json`, `dataclasses`, `typing` — does not write state. |
| C-29 | `phase_pump.py` is a consumer | **MIXED** | Goes through owners for state (`init_phase_sessions:113`, `record_phase_result:293`, `init_stage_sessions:485`, `append_run_event:2150,2178`, `write_active_run:2123`) — good. **But it also constructs `prepared_plan.v1.json` paths directly at lines 2072, 2074, 2092, 2094** (read-only resolution). The plan's blanket statement needs a "writers vs. readers" qualifier. See OPEN QUESTION OQ-3. |
| C-30 | "Existing imports of prepared artifact writer Protocol names" — exist? | **VERIFIED — none external** | `RunStateTxn`/`RunStateStore`/`JsonRunStateStore` are referenced only within `prepared_artifact_writer.py` itself (definition + `__all__`). No external module imports these names. The "compatibility re-exports" question (step 2) collapses to: re-exports are unused; safe to leave them or remove them. |
| C-31 | A precedent AST-based fence test exists | **VERIFIED — plan does not mention it** | `tests/test_prepared_artifact_fence.py` already implements an AST visitor (`_GitBaseWriteVisitor`) that excludes `tests/` and the writer module itself, recording violations. This is the model the new write-fence test should follow. **The plan should reference it.** |

---

## 3. Open Questions

**OQ-1. Initial whitelist for the write-fence.** The plan says the whitelist must be "explicit and reviewed" but never names it. **Proposed answer**, based on evidence:

```
phase_sessions.v1.json     -> phase_sessions.py
stage_sessions.v1.json     -> stage_sessions.py
shared_decisions.v1.json   -> phase_decisions.py
operator_decisions.v1.json -> [DOES NOT EXIST YET — drop from initial fence]
prepared_plan.v1.json      -> prepared_artifact_writer.py + prepare.py
                              (prepare.py has the original artifact-write site;
                              prepared_artifact_writer.py owns coordinated mutation)
run_events.jsonl           -> run_state.py
active_run.json            -> run_state.py
manifest.json              -> execution_worktree.py
                              (CONCERN: 'manifest.json' is generic — see CONCERN-2)
evidence.json              -> phase_evidence.py
```

**OQ-2. What does `worktree_state_store.py` "reconcile against git" actually mean?** No precedent in `execution_worktree.py` for transactional reads-that-affect-mutation. The existing `_classify_existing_manifest` at line 251 is a pure manifest comparison; the actual git reconciliation lives in `materialize_run_execution_worktree` at line 233. **Proposed answer**: the wrapper should not introduce new invariants; it should expose the existing `materialize_run_execution_worktree` / `adopt_run_worktree` / `integrate_run_worktree` functions through a Protocol surface and *not* try to reorder their internal git checks. Mark this in the plan as "captures existing behavior" rather than a new invariant.

**OQ-3. Is `phase_pump.py` allowed to *read* `prepared_plan.v1.json` paths directly?** Today it does (`phase_pump.py:2072,2092`). **Proposed answer**: yes — the boundary is for *writes*, not reads. The plan should state explicitly: "Direct path *reads* in consumer modules are out of scope; the fence only catches writes (`write_text`, `write_bytes`, `json.dump`, `open(..., 'w')`, and assignment to `Path / 'X.v1.json'` followed by a write call)."

**OQ-4. Migration order for "one family at a time."** The plan does not order families. **Proposed sequence** (lowest blast radius first):
  1. `prepared_artifact` — the seam already exists; add `state_store.py`, re-point `prepared_artifact_writer` to import Protocols from there with re-exports.
  2. `run_state` — already centralized; add `RunEventSink` Protocol, no call-site changes.
  3. `phase_evidence` and `phase_decisions` — small surfaces, already schema-versioned, low risk.
  4. `worktree_state_store.py` — wrap `execution_worktree.py`, capture-existing-behavior only.
  5. `phase_session_store.py` — biggest wrap target (`phase_sessions.py` is ~1700 lines), do last.
  6. `stage_sessions` — fold into `phase_session_store` or split; defer to a follow-up if scope creeps.

**OQ-5. Acceptance criterion: "Existing imports of prepared artifact writer store Protocols still work or are migrated in the same PR" — which?** **Proposed answer**: this is a non-issue. Evidence (C-30) shows no external callers import the Protocol names. Pick "migrated in the same PR" since the migration is empty. Remove the "still work or" clause from the criterion to eliminate ambiguity.

**OQ-6. Does `test_prepared_artifact_writer.py` exist or get created here?** Per EVIDENCE GAP G-1, it does not exist. The plan lists it under "Required targeted tests". **Proposed answer**: this is a *new* test file the writer creates. Rename or annotate accordingly so the writer agent doesn't search in vain.

**OQ-7. Does `operator_decisions.v1.json` belong in the initial fence?** Per EVIDENCE GAP G-3, the file family does not exist anywhere in the codebase today. **Proposed answer**: drop it from the initial fence; add a TODO referencing Phase 4 operator-decisions work.

---

## 4. Concerns and Guardrails

**CONCERN-1: `phase_session_store.py` as a "thin wrapper" over `phase_sessions.py`.** `phase_sessions.py` is ~1700 lines with internal locking (`PhaseSessionLockTimeout`), policy-update plumbing (`policy_update: ResolvedPolicyUpdate | None`), retry-policy normalization, and an in-process state machine. A literal "thin wrapper" can only forward a small public surface. The plan's "thin wrapper that delegates" needs a definition: **forward only the public top-level functions** (`init_phase_sessions`, `record_phase_result`, `phase_session_path`, the lock context manager) and **leave the policy/retry/state-machine internals alone**. Otherwise an implementer will be tempted to refactor mid-PR and bust scope.

**CONCERN-2: `manifest.json` is too generic for a textual fence.** The fence string `manifest.json` will hit:
- `execution_worktree.py:206` (worktree manifest — owner-internal, OK)
- `provider_evidence.py:139` `provider-review.manifest.json` (different family)
- `capture_claude_print_fixture.py:78` `*.manifest.json` (different family)
- Any future `.manifest.json` sibling.

A textual contains-check will both miss legitimate writes (because `provider-review.manifest.json` matches `manifest.json` substring) and produce false positives. **GUARDRAIL**: the fence must be path-component-scoped (e.g., `Path / "manifest.json"` only when the parent is `worktrees/<run-id>/`), not a substring match. The existing `test_prepared_artifact_fence.py` AST visitor pattern is the correct precedent — use it.

**CONCERN-3: Textual fence vs. AST fence.** The plan says "the test can be textual, but keep it narrow enough to avoid false positives in fixtures and docs." A textual fence on `phase_sessions.v1.json` will trip on:
- Test fixtures that legitimately `read_text()` the file.
- Doc strings / log messages that mention the filename.
- The owner's own constants (need allowlist).

**GUARDRAIL**: Use the AST approach from `tests/test_prepared_artifact_fence.py` — visit `Call` nodes for `write_text`/`write_bytes`/`json.dump`/`open(..., "w"|"a")` and check whether the path expression resolves through one of the known filename literals. Skip `tests/` and the owner module(s). Substring fences in fixtures and docs are then ignored automatically because they aren't write calls.

**CONCERN-4: Step 5 ("Move orchestration-level direct writes behind the wrappers one family at a time") is unbounded.** Given the all-writers grep returned ~50+ write call sites across `phase_pump.py`, `prepare.py`, `decompose.py`, `mco_stage.py`, `plan.py`, `context_bundle.py`, etc., a writer agent without a sequenced list will either (a) do nothing meaningful or (b) churn through unrelated files. **GUARDRAIL**: pin Step 5 to OQ-4's sequence and add a "stop after step N" rule that any sweep beyond a named family is out of scope for this PR.

**CONCERN-5: Compatibility re-export decision.** Plan step 2 says re-exports are conditional on callers. Per C-30, no external callers exist. **GUARDRAIL**: the plan should resolve this conditional now ("no external callers; re-exports may be removed when Protocols move to `state_store.py`") instead of deferring to runtime discovery.

**CONCERN-6: Acceptance criterion is not testable as written.** "New store APIs are small enough that a JSON or SQLite implementation could sit behind them later" — there is no signal a writer can check. **GUARDRAIL**: convert to a concrete count, e.g., "each store Protocol exposes ≤ 6 methods; methods take only run_id, phase_id, payload, and Path-resolved inputs; no methods leak `dict[str, Any]` schema-version internals."

**CONCERN-7: No rollback story.** If the new fence test catches a legitimate write in CI on day one, what's the recovery? **GUARDRAIL**: add a "fence allowlist" file (e.g., `tests/state_store_fence_allowlist.txt`) with one-line justification per entry; the test loads this and treats listed paths as exempt. PR review adds entries with explanation rather than skipping the test.

**CONCERN-8: Coupling risk.** Putting `RunStateStore`/`PhaseSessionStore`/`WorktreeStateStore` in one `state_store.py` creates a single import target that every owner depends on. If `state_store.py` ever needs to import from any owner (for shared types), a circular import is likely. **GUARDRAIL**: state_store.py must define Protocols only and import nothing from owner modules. Shared types (`PhaseSessionLockTimeout`, etc.) stay where they are; the Protocol uses structural typing, not nominal.

---

## 5. Gaps to Close Before Implementation

Each item below is a concrete edit to the plan file.

1. **Resolve EVIDENCE GAP G-1**: rename "Tests > Required targeted tests > `test_prepared_artifact_writer.py`" to either reference the existing `test_prepare_artifact.py` (used for prepare flow) or explicitly mark it `(new file)`.

2. **Resolve EVIDENCE GAP G-2**: confirm `shared_decisions.v1.json` literal filename in `phase_decisions.py`. If the literal differs (e.g., `shared_decisions.json`), update the fence list.

3. **Resolve EVIDENCE GAP G-3**: drop `operator_decisions.v1.json` from the fence list. The file family does not exist; add a TODO in handoff notes.

4. **Add OQ-1 whitelist** to the plan as the explicit initial fence whitelist with file-owner mapping.

5. **Replace "the test can be textual" with "use the AST visitor pattern from `tests/test_prepared_artifact_fence.py`"** (CONCERN-3, CONCERN-2).

6. **Sequence Step 5** with the OQ-4 family ordering and a "stop after named family" rule (CONCERN-4).

7. **Resolve OQ-5 ambiguity** in acceptance criteria: replace "still work or are migrated" with "migrated in the same PR; no external callers exist today (verified 2026-05-02 — see Phase 1 review §C-30)."

8. **Define what "thin wrapper" means** (CONCERN-1): forward only the named public functions of `phase_sessions.py` (`init_phase_sessions`, `record_phase_result`, `phase_session_path`, `phase_session_lock_path`, `phase_handoff_path`, `phase_result_path` — pulled from `phase_sessions_module` grep). State explicitly: do not wrap private helpers or refactor internals.

9. **Add a definition-of-done block** mapping each acceptance criterion to a verifiable signal (CONCERN-6). Example:
   - "Persisted file paths unchanged" -> `find data/runs -type f -name "*.json"` before/after produces identical sets.
   - "JSON shapes unchanged" -> `git diff` of any persisted fixture file is empty.
   - "Consumer modules don't open core state directly" -> the new fence test is green.
   - "New store APIs are small" -> `grep -c "^    def " state_store.py` per Protocol class ≤ 6.

10. **Add an allowlist file** (CONCERN-7) so legitimate fence escapes are documented, not skipped.

11. **Reference the existing precedent**: add a "Prior art" subsection citing `tests/test_prepared_artifact_fence.py` so the writer doesn't reinvent the AST visitor.

12. **Clarify reads vs. writes** (OQ-3): explicitly scope the fence to writes only.

13. **Add coupling rule for `state_store.py`** (CONCERN-8): "imports nothing from owner modules; Protocols only."

---

## 6. Suggested Plan Edits

Apply these as direct text changes to `phase-1-state-ownership-boundary-plan.md`.

### Insert new section after "Why This Lands First":

```markdown
## Prior Art

The repo already contains a working AST-based fence: `tests/test_prepared_artifact_fence.py`
uses an `ast.NodeVisitor` to ensure only `prepared_artifact_writer.py` writes the
`git_base_sha` field. The new state-store fence should follow the same pattern (visit
write-call expressions; exempt the owner module and `tests/`) rather than a textual scan.
```

### Replace "Implementation Steps" item 2 with:

```markdown
2. The Protocol names (`RunStateTxn`, `RunStateStore`, `JsonRunStateStore`) are
   currently defined in `prepared_artifact_writer.py` and re-exported via `__all__`.
   Verified 2026-05-02: no external module imports these names. The move to
   `state_store.py` is therefore a clean rename — leave `prepared_artifact_writer.py`'s
   `__all__` re-exports as a courtesy (no callers, but cheap to keep).
```

### Replace "Implementation Steps" item 3 with:

```markdown
3. Add `phase_session_store.py` as a thin wrapper that forwards only these public
   functions of `phase_sessions.py`: `init_phase_sessions`, `record_phase_result`,
   `phase_session_path`, `phase_session_lock_path`, `phase_handoff_path`,
   `phase_result_path`, plus the public lock context manager. Do not wrap private
   helpers (`_touch_and_write`, `_normalize_state`, etc.) and do not refactor the
   policy-update / retry-policy / state-machine internals — those stay inside
   `phase_sessions.py`.
```

### Replace "Implementation Steps" item 4 with:

```markdown
4. Add `worktree_state_store.py` as a thin wrapper over the public surface of
   `execution_worktree.py`: `materialize_run_execution_worktree`, `commit_stage_artifacts`,
   `adopt_run_worktree`, `integrate_run_worktree`, plus the resolution helpers. The
   "reads that affect mutation must reconcile against git" rule captures the *existing*
   behavior of `materialize_run_execution_worktree` (which calls `_classify_existing_manifest`
   at line 251 before writing). It is not a new invariant.
```

### Replace "Implementation Steps" item 5 with:

```markdown
5. Migrate one family at a time, in this order. Stop after the named family if scope
   pressure rises:
   1. `prepared_artifact` (Protocols already exist — pure rename to `state_store.py`).
   2. `run_state` (already centralized — add `RunEventSink` Protocol, no call-site changes).
   3. `phase_evidence` and `phase_decisions` (small surfaces, schema-versioned, low risk).
   4. `worktree_state_store` (wrap existing, capture-existing-behavior only).
   5. `phase_session_store` (largest wrap target — do last).
   Out of scope for this PR: `stage_sessions` wrapper, `mco_stage`/`prepare`/`decompose`
   write-site sweeps. File these as Phase 1.5 follow-ups.
```

### Replace "Write Fence Shape" section with:

```markdown
## Write Fence Shape

Use an AST visitor (modeled on `tests/test_prepared_artifact_fence.py`) that walks every
`*.py` file under `swarm_do/pipeline/` outside `tests/` and the owner modules listed
below. Flag any `Call` node where the receiver path resolves to one of the protected
filename literals AND the call name is in `{write_text, write_bytes, write, dump}` or
the call is `open(..., "w"|"a"|"wb"|"ab")` followed by a write.

Initial fence whitelist (filename → owner module):

| Filename                  | Owner module                  |
|---------------------------|-------------------------------|
| `phase_sessions.v1.json`  | `phase_sessions.py`           |
| `stage_sessions.v1.json`  | `stage_sessions.py`           |
| `shared_decisions.v1.json`| `phase_decisions.py`          |
| `prepared_plan.v1.json`   | `prepared_artifact_writer.py`, `prepare.py` |
| `run_events.jsonl`        | `run_state.py`                |
| `active_run.json`         | `run_state.py`                |
| `evidence.json`           | `phase_evidence.py`           |
| `manifest.json` (worktree)| `execution_worktree.py` (path-component-scoped: parent dir matches `worktrees/<run-id>/`) |

Note: `operator_decisions.v1.json` is intentionally excluded from the initial fence —
the file family does not exist in the codebase as of 2026-05-02. Add it when the
operator-decisions surface lands (likely Phase 2 or 4).

If a whitelist exception is added, the PR must (a) explain why that module owns the
state family and (b) record the exemption in `tests/state_store_fence_allowlist.txt`
with a one-line justification. CI fences off new entries; review approves them.

The fence is for **writes only**. Direct path-resolution reads (e.g.,
`phase_pump.py:2072` resolves a `prepared_plan.v1.json` path for read access) are out
of scope.
```

### Replace `state_store.py` description (top of "Owned files") implicitly via new section:

```markdown
### `state_store.py` Coupling Rule

`state_store.py` defines Protocols only. It MUST NOT import from any owner module
(`phase_sessions`, `stage_sessions`, `phase_evidence`, `phase_decisions`,
`execution_worktree`, `run_state`, `prepared_artifact_writer`). Owner modules may
import Protocols from `state_store.py`; the dependency is one-way. Shared exception
types stay in their owner modules; Protocol typing is structural, not nominal.
```

### Update "Acceptance Criteria":

```markdown
## Acceptance Criteria

- Existing persisted file paths and JSON shapes are unchanged (signal: `find data/runs
  -type f` and any test fixture diff are empty).
- Protocol names move from `prepared_artifact_writer.py` to `state_store.py` in the
  same PR; `__all__` re-exports remain in the writer module as a no-op courtesy.
  (Verified 2026-05-02: no external callers import these names — see review §C-30.)
- New store Protocols expose ≤ 6 methods each; arguments are restricted to `run_id`,
  `phase_id`, payload `Mapping[str, Any]`, and `Path`-resolved inputs.
- Consumer modules (`phase_pump.py`, `stage_controller.py`, `claude_stream.py`) do not
  *write* core state files directly. Reads are unaffected.
- The new write-fence test passes; the fence allowlist file lists every documented
  exemption with justification.
- Phase 4 trace/eval can read through the seam or through existing read helpers
  without learning extra writer details.
```

### Update "Tests":

```markdown
## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_state_store.py                  (new)
py/swarm_do/pipeline/tests/test_state_store_write_fence.py      (new)
py/swarm_do/pipeline/tests/test_prepare_artifact.py             (existing — Protocol-name imports may need touch)
py/swarm_do/pipeline/tests/test_prepared_artifact_fence.py      (existing — AST precedent for the new fence)
```
```

### Add to "Handoff Notes":

```markdown
## Handoff Notes

Call out every direct writer that remains and why. If the fence has to skip a file
family, record that in `tests/state_store_fence_allowlist.txt` with justification, and
file a follow-up blocker for Phase 4.5.

Known follow-ups deferred from this phase:

- `operator_decisions.v1.json` family does not yet exist. Add to fence when the
  operator-decisions surface lands.
- `stage_sessions` wrapper (`stage_session_store.py`) is intentionally not in this PR.
- Direct-write call sites in `mco_stage.py`, `prepare.py`, `decompose.py`,
  `context_bundle.py`, `plan.py`, `phase_pump.py` (launch artifacts) are out of scope.
  These write *sidecar* files (stdout/stderr/command.json/launcher_prompt), not core
  state — confirm they're truly sidecars and don't belong in the fence.
```

---

## Status: COMPLETE
