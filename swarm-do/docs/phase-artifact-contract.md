# Phase Artifact Contract

Phase-session launchers complete an attempt by writing two strict JSON files:

- Result: `runs/<run_id>/phase_results/<phase_id>/attempt-<n>.result.json`
- Handoff: `runs/<run_id>/phase_handoffs/<phase_id>/attempt-<n>.handoff.json`

Both files use `schema_version=1` and validate against
`schemas/phase_result.schema.json` and `schemas/phase_handoff.schema.json`.
Unknown fields are rejected.

## Required Identity

The result and handoff must match durable phase-session state:

- `run_id`
- `phase_id`
- `phase_attempt`
- result `prepared_plan_sha`
- result `phase_content_sha`
- result `handoff_path`
- handoff `status`

`handoff_path` must resolve inside `data/runs/<run_id>/`. Absolute paths and
relative paths are accepted only when they stay inside that run directory.

## Status Values

- `complete`: the phase finished successfully.
- `failed`: the child could not complete the phase. Set `retryable=true` only
  when a fresh attempt is reasonable.
- `blocked`: the child cannot proceed without operator action.
- `needs_input`: the child needs a decision or missing information.

For retryable failures, `retry_after_seconds` may request a backoff. The parent
policy clamps the value to the durable retry policy. Handoff `do_not_retry`
turns an otherwise retryable child failure into a parent human gate.

## Work Units

In phase-session mode, `completed_work_units` in both files must stay empty
unless the value is one of the prepared unit IDs for the current phase. Put
semantic accomplishments in `summary`, `validation`, `artifacts`, or
`next_phase_context`.

## Common Failures

- `status_mismatch`: result status differs from the expected command status.
- `result_identity_mismatch`: result `run_id` or `phase_id` differs.
- `prepared_plan_sha_mismatch`: result prepared-plan SHA differs from state.
- `phase_content_sha_mismatch`: result phase-content SHA differs from prepared metadata.
- `handoff_identity_mismatch`: handoff `run_id` or `phase_id` differs.
- `attempt_mismatch`: handoff attempt differs from result attempt.
- `handoff_status_mismatch`: handoff status differs from result status.
- `completed_work_units_not_prepared`: a completed work-unit id was not prepared for this phase.
- `path_escape`: result or handoff path escapes the run directory.

Invalid artifacts are recorded in attempt evidence. Deterministic contract
failures are blocked for operator review instead of retried blindly. Evidence
manifests live under
`runs/<run_id>/phase_launches/<phase_id>/attempt-<n>/evidence.json` and record
artifact validity plus the failure kind used by recovery policy.

Valid examples are in `docs/examples/phase-artifacts/`.
