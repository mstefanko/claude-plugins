# Phase 2 - Typed Domain Contracts

Date: 2026-05-02
Status: active implementation plan after projector read shapes stabilize
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 2

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

## Implementation Steps

1. Add `domain.py` with small frozen dataclasses where practical.
2. Each record gets:
   - `from_mapping()`;
   - `to_dict()`;
   - `validate()` when construction alone is not enough;
   - stable status constants or enums only where existing persisted statuses
     are already known.
3. Start with `PhaseRecord`, `PhaseAttemptRecord`, and `DoctorFinding`.
4. Convert `phase_status`, `phase_doctor`, and recovery summaries internally
   while keeping external JSON output unchanged.
5. Add provider records after phase/status records are stable.
6. Add work-unit records only if they reduce repeated control-plane checks and
   do not duplicate schema lint behavior.

## Boundary Rule

`domain.py` owns runtime control-plane records inside the process. It does not
own launcher-visible artifact contracts. If a payload is already governed by a
schema file or a versioned manifest, domain records may wrap summaries of it,
but they do not become the validator of record.

## Acceptance Criteria

- Core status/recovery paths stop repeating the same shape checks.
- Unknown keys are rejected where the runtime boundary requires strictness.
- Missing required fields produce useful errors.
- All existing persisted statuses remain accepted.
- CLI JSON output remains backward compatible.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_domain_contracts.py
py/swarm_do/pipeline/tests/test_phase_status.py
py/swarm_do/pipeline/tests/test_phase_doctor.py
py/swarm_do/pipeline/tests/test_provider_review.py
```

## Handoff Notes

Include before/after examples of repeated mapping access that disappeared. If
the PR mostly adds types without deleting shape checks, the phase is not yet
paying rent.
