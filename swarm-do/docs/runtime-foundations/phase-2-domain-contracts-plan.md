# Phase 2 - Typed Domain Contracts

Date: 2026-05-02
Status: **BLOCKED on Phase 1 + Phase 4.5** — see §Prerequisites. Promote to "active implementation plan" only when prerequisites verified.
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 2 (lines 568–637)

## Prerequisites (verify before any code is written)

- **Phase 1 state ownership boundary**: must be merged. Verify by checking that
  `prepared_artifact_writer.py` no longer writes outside the `RunStateStore` /
  `JsonRunStateStore` seam (Phase 1 review §1 verdict). Phase 1 plan header is
  currently `Status: active implementation plan` — confirm completion before
  starting Phase 2.
- **Phase 4.5 read-only projector**: at least the first read shape must be
  landed and used by `phase_status`, `phase_doctor`, or `phase_recovery`.
  Verify by listing the projector tables those consumers query. Phase 4.5
  plan header is currently `Status: active implementation plan after
  Phases 1, 4, and 3` — confirm completion before starting Phase 2.
- If either prerequisite is open, this plan is BLOCKED. Do not start.

## Objective

Replace repeated runtime `Mapping[str, Any]` shape checks in status, doctor,
recovery, provider review, and projector consumers with small typed domain
records.

## Senior Implementation Decision

Do this after the first projector increment, not before. The code should know
which records are actually queried by trace/status/doctor before freezing
internal contracts. Otherwise `domain.py` becomes a parallel schema universe
beside JSON Schema, SCHEMA_VERSION manifests, and existing dataclasses.

Use stdlib dataclasses first. Do not add a validation framework.

## Prior Art (re-pin at implementation time)

Per parent plan lines 165–176: every upstream file referenced MUST be re-pinned
to a specific commit hash before agent execution. Pattern sources:

- `smolagents@<sha> src/smolagents/memory.py` — `Step`, `ActionStep`,
  `TaskStep` (frozen records, lossless serialization).
- `adk-python@<sha> src/google/adk/events/event.py` — `Event` /
  `EventActions` pattern for unknown-key handling at the ingestion boundary.
- `langgraph@<sha> libs/langgraph/langgraph/types.py` — `Send`, `Command`
  minimal typed control-plane records.

Pin the SHAs and quote the exact field-handling lines in the PR description.
Do not begin implementation against `<sha>` placeholders.

## Scope

Owned files:

```text
py/swarm_do/pipeline/domain.py
py/swarm_do/pipeline/tests/test_domain_contracts.py
```

Initial records:

```text
PhaseRecord
PhaseAttemptRecord
DoctorFinding
ProviderRunRecord
ProviderFindingRecord
```

Only add these later if a real caller needs them:

```text
RunRef
RunRecord
StageRecord
WorkUnitRecord
ArtifactExport
```

## Non-Goals

- No replacement for JSON Schema validators.
- No replacement for `phase_evidence.MANIFEST_SCHEMA_VERSION`.
- No replacement for `phase_autopilot_policy` dataclasses.
- No persisted artifact shape change.
- No broad conversion of every dict in the pipeline.
- **No migration of existing local records.** `provider_review.py`
  `ReviewProviderPolicy`, `ReviewProviderProbe`, and `ReviewProviderProbeCheck`
  stay caller-private. `ProviderRunRecord` / `ProviderFindingRecord` in
  `domain.py` cover the cross-module runtime view (status / doctor / recovery
  / projector consumers). If overlap appears, prefer extending the local
  record over duplicating into `domain.py`.

## Boundary Rule (enforced by lint test)

`domain.py` is forbidden from:

- importing or re-defining any `*SCHEMA_VERSION` constant
  (`phase_evidence.MANIFEST_SCHEMA_VERSION`, `run_state.SCHEMA_VERSION`,
  `phase_decisions.SCHEMA_VERSION`, `context_bundle.SCHEMA_VERSION`,
  `mco_stage.SCHEMA_VERSION`, `provider_review.SCHEMA_VERSION`,
  `provider_review.FULL_FINDINGS_SCHEMA_VERSION`,
  `selftest.SCHEMA_VERSION`);
- reading from or writing to any path under `swarm-do/schemas/`;
- being imported by `phase_evidence.py`, `prepared_artifact_writer.py`,
  `mco_stage.py`, or `run_state.py`.

Add `test_domain_contracts.py::test_domain_does_not_couple_to_persistence` as
an AST-grep fence (precedent: `test_prepared_artifact_fence.py`).

Records in `domain.py` are NOT versioned. They are in-process types and
evolve with the code. If a record needs to be persisted, it does not belong
in `domain.py` — promote to a JSON Schema + `SCHEMA_VERSION` constant in the
owning module.

## Implementation Steps

1. Add `domain.py` with small frozen dataclasses where practical.
2. Each record gets:
   - `from_mapping()` — the validation seam. Raises `ValueError` (or a typed
     subclass) on bad input. Untyped input enters the process through
     `from_mapping` only;
   - `to_dict()` — lossless against `from_mapping` for the fixture corpus
     (see §Tests round-trip property);
   - `validate()` only when a cross-field invariant cannot be expressed in
     `from_mapping` (e.g., "if status==failed then failure_kind required").
     Otherwise omit it. No `__post_init__` validators — construction with
     valid kwargs is trusted inside the process;
   - Use `@dataclasses.dataclass(frozen=True, slots=True)` (matches
     Python 3.11+ baseline; existing dataclasses without `slots` are not
     migrated by this phase);
   - **Status enums REUSE existing constants — do not redefine:**
     - Phase status: `phase_sessions.STATUS_*` (10 values: `pending`,
       `leased`, `running`, `complete`, `failed`, `blocked`, `needs_input`,
       `stale`, `retry_waiting`, `retry_exhausted`) plus the
       `CLAIMABLE_STATUSES` / `ACTIVE_STATUSES` / `TERMINAL_STATUSES` sets
       and the `RESULT_TO_PHASE_STATUS` map (`phase_sessions.py:39-48`).
     - Phase-result status: `phase_artifact_contract.PHASE_RESULT_STATUSES`.
     - Doctor report status: `{"ok", "findings"}` (`phase_doctor.py:46`).
     - Doctor finding severity: `{"error", "warning", "info"}`
       (`phase_doctor.py:178-180`).
     - Worktree status sentinel: `{"ok", "not_found"}`
       (`phase_doctor.py:117`).
     `domain.py` re-exports these; it does not define new ones.
   - **Unknown-key policy** (declare explicitly in module docstring):
     reject unknown keys with a typed error from `from_mapping` for runtime
     control-plane records (status, doctor, recovery). Preserve unknown keys
     in an `extra: Mapping[str, Any]` field for projector-derived records
     (so future projector columns don't break readers).
3. Start with `PhaseRecord`, `PhaseAttemptRecord`, and `DoctorFinding`.
4. Wrap the dict returned by `phase_sessions.phase_status()` (defined at
   `py/swarm_do/pipeline/phase_sessions.py:291` — note: `phase_status` is a
   FUNCTION, not a module) with a `PhaseStatusReport` view, or convert
   callers to `PhaseRecord`-per-phase. The function name stays; only
   consumers change.
5. Convert these consumers, in order, deleting the listed shape checks:
   - `py/swarm_do/pipeline/phase_doctor.py` lines 54–68 (format loop),
     72–86 (`_probe_phase_status`), 89–110 (`_probe_lease`), 178–180
     (`_finding_rank`).
   - `py/swarm_do/pipeline/phase_recovery.py` lines 92–94, 127, 133,
     138–140, 163, 170, 173, 195–196, 220–240, 256–262, 276–282
     (status/result/phase `dict.get` chains; wrap with `PhaseRecord` /
     `PhaseAttemptRecord`).
   - `py/swarm_do/pipeline/phase_attempts.py` lines 50–73 (status/cost
     projection), 89–98 (phase iteration with `isinstance(phase, Mapping)`
     guard), 112–148 (`_row_from_mapping` — the largest single shape-check
     site, ~36 keys).
6. Add `ProviderRunRecord` and `ProviderFindingRecord` only after:
   - `PhaseRecord`, `PhaseAttemptRecord`, `DoctorFinding` have shipped and
     removed their target shape checks per §Definition of Done;
   - one full release cycle (or one swarm dogfood run) has passed without a
     record-shape regression.
7. Add work-unit records only if they reduce repeated control-plane checks
   and do not duplicate schema lint behavior.

## Migration Sequence

Per consumer, in this order:

1. Add `Record.from_mapping()` and `Record.to_dict()`. Round-trip property
   test: `Record.from_mapping(payload).to_dict() == payload` for the
   existing fixture corpus (see §Tests).
2. Inside the consumer function, parse once at the top
   (`record = PhaseRecord.from_mapping(raw)`) and consume the typed object
   inside the body. Keep the dict return shape unchanged.
3. Delete the now-dead `dict.get` / `isinstance(..., Mapping)` chain in the
   same PR. The PR diff must show a net reduction in `.get(` calls in the
   consumer file (see §Definition of Done).
4. Repeat for the next consumer. Do not touch a second consumer until the
   first lands and the test net stays green.

No dual-path / feature-flag layer. Conversion is a refactor, not a rollout.

## Definition of Done (per consumer PR)

- Net reduction of at least 10 `.get(` calls in the touched consumer file
  OR removal of every `isinstance(x, Mapping)` guard whose purpose was only
  to access a now-typed field (whichever is smaller).
- For `phase_doctor.py`: removes the dict-walk in `format_phase_doctor`
  (lines 54–68), removes `_finding_rank` (178–180) dict access.
- For `phase_recovery.py`: removes the `_recovery_projection` /
  `_prefer_persisted_failure_fields` shape walks at the call sites listed
  in Implementation Step 5.
- For `phase_attempts.py`: replaces the 36-key projection in
  `_row_from_mapping` (lines 112–148) with `PhaseAttemptRecord.from_mapping`
  + a single `to_row()` view.
- All listed consumers' `--json` output is byte-identical to the pre-PR
  output for the fixture corpus in §Tests.

## Acceptance Criteria

- Core status/recovery paths stop repeating the same shape checks.
- Unknown keys are rejected where the runtime boundary requires strictness
  (control-plane: status, doctor, recovery) and preserved where the boundary
  must tolerate projector evolution (projector-derived reads).
- Missing required fields produce useful errors that name the field.
- All existing persisted statuses (enumerated in §Implementation Steps
  step 2) remain accepted.
- CLI JSON output remains backward compatible (asserted by byte-equality
  test below).

## Tests

New:

- `py/swarm_do/pipeline/tests/test_domain_contracts.py` — covers, per record:
  1. **Round-trip**: `Record.from_mapping(d).to_dict() == d` for every
     fixture payload found under `py/swarm_do/pipeline/tests/fixtures/` and
     any inline test dict in `test_phase_sessions.py`,
     `test_phase_recovery.py`, `test_phase_attempts*.py`,
     `test_provider_review.py` (golden corpus).
  2. **Unknown-key handling**: explicit assertion of the chosen policy
     (reject for control-plane records; preserve in `extra` for
     projector-derived records).
  3. **Required-field error**: missing required field raises with the
     field name in the message.
  4. **Status enum**: every persisted status string in §Implementation
     Steps step 2 is accepted; an unknown status is rejected with a clear
     error.
  5. **Boundary fence**:
     `test_domain_does_not_couple_to_persistence` AST-grep test that
     enforces §Boundary Rule (no `*SCHEMA_VERSION` import, no `schemas/`
     read, not imported by listed persisters).

Updated (no new files):

- `test_phase_sessions.py`, `test_phase_recovery.py`,
  `test_provider_review.py` — replace any inline shape checks with the
  typed record where the consumer was converted.

Add (currently missing):

- `test_phase_attempts.py` covering the `_row_from_mapping` rewrite.

CLI compatibility:

- Parametric test that runs `bin/swarm phases doctor <fixture_run> --json`
  before and after the rewrite and asserts byte equality.

## Handoff Notes

Include before/after examples of repeated mapping access that disappeared.
The §Definition of Done section above makes this measurable: a green test
suite without shape-check deletion means the phase has not paid rent —
bounce the PR.

## Evidence Pack (callsites the writer must touch)

- `py/swarm_do/pipeline/phase_sessions.py:39-48` — existing `STATUS_*`
  constants (10 values).
- `py/swarm_do/pipeline/phase_sessions.py:291` — `def phase_status(...)`
  function (NOT a module).
- `py/swarm_do/pipeline/phase_doctor.py:46` —
  `"status": "ok" if not ranked else "findings"`.
- `py/swarm_do/pipeline/phase_doctor.py:54-68` — dict-walk shape checks in
  `format_phase_doctor`.
- `py/swarm_do/pipeline/phase_doctor.py:72-86` — `_probe_phase_status`
  consumer.
- `py/swarm_do/pipeline/phase_doctor.py:178-180` — `_finding_rank` severity
  dict.
- `py/swarm_do/pipeline/phase_recovery.py:92-94, 127, 138-140, 195-196,
  220-262, 276-282` — primary shape-check removal sites.
- `py/swarm_do/pipeline/phase_attempts.py:50-73` — status/cost projection.
- `py/swarm_do/pipeline/phase_attempts.py:89-98` — phase iteration with
  `isinstance(phase, Mapping)` guard.
- `py/swarm_do/pipeline/phase_attempts.py:112-148` — `_row_from_mapping`,
  the largest single shape-check site (~36 keys).
- `py/swarm_do/pipeline/phase_evidence.py:16` —
  `MANIFEST_SCHEMA_VERSION = 1`.
- `py/swarm_do/pipeline/run_state.py:15` — `SCHEMA_VERSION = 1`.
- `py/swarm_do/pipeline/provider_review.py:37-38` — `SCHEMA_VERSION` and
  `FULL_FINDINGS_SCHEMA_VERSION`.
- `py/swarm_do/pipeline/provider_review.py` — existing
  `ReviewProviderPolicy` / `ReviewProviderProbe` /
  `ReviewProviderProbeCheck` frozen dataclasses with `as_dict` (precedent;
  do not duplicate into `domain.py`).
- `py/swarm_do/pipeline/phase_autopilot_policy.py:62, 77, 101, 113` —
  existing `AutopilotPolicy*` frozen dataclasses (precedent: no
  `__post_init__`, no `slots`).
- `py/swarm_do/pipeline/phase_artifact_contract.py` —
  `PHASE_RESULT_STATUSES` enumeration.
- `swarm-do/schemas/` — 20+ `*.schema.json` files (the persistence layer
  that `domain.py` must NOT replicate).
