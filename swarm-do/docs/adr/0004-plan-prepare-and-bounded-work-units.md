# ADR 0004: Plan-Prepare And Bounded Work Units

## Status

Accepted for inspect-mode dogfood.

## Context

Large phases can stress a writer session before handoff logic has a chance to
help. The prepare layer sizes work before writer launch by inspecting a plan
phase, producing a `work_units.v2` artifact, and linting file scope,
dependencies, blocked files, and writer budget estimates.

## Decision

- Stock presets default to `decompose.mode = "off"`.
- Dogfood may flip a preset to `inspect` to gather baseline telemetry.
- `enforce` is gated on observed directional improvement across hard phases.
- `files` remains a v2 legacy alias for one minor version; `allowed_files` is
  the canonical field.
- Budget estimates use conservative hard-coded coefficients until unit-level
  telemetry has at least 30 hard-phase rows.

## Promotion Scorecard

Promotion to `enforce` requires directional improvement, not statistical
significance. Single-operator dogfood volume is too small for strong claims.

Track by `phase_complexity x phase_kind`:

- writer tool-call median per unit decreases on at least 5 hard-phase runs,
- writer output bytes median per unit decreases on at least 5 hard-phase runs,
- handoff count and `NEEDS_CONTEXT` count are strictly lower at the median,
- spec-mismatch retry rate and review churn are not worse,
- integration merge conflicts stay below 2 manual interventions per week,
- wall clock stays within 25% of baseline,
- operator interventions per run are strictly lower.

## Re-Evaluation

Revisit this ADR after two weeks of dogfood or after adding cron/CI dogfood
traffic. Recalibrate `pipeline.budget.estimate_unit_budget` once enough v2
rows exist.
