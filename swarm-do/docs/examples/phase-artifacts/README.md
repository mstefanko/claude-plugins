# Phase Artifact Examples

These JSON pairs are synthetic `schema_version=1` phase-session result and
handoff artifacts. They are intentionally strict and keep `completed_work_units`
empty so they can validate without a prepared work-unit sidecar.

- `complete.*`: successful phase.
- `failed-retryable.*`: child-reported retryable failure with `retry_after_seconds`.
- `blocked.*`: child-reported block for operator review.
- `needs-input.*`: child asks the operator for missing information.
