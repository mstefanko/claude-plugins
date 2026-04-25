# Phase 0 Experiment Surface

`phase0/` is retained as a standalone Codex cross-model review experiment
surface. It is not wired into `/swarm-do:do`, stock presets, or the default
pipeline.

Keep these files together:

- `bin/codex-review-phase`
- `phase0/result-schema.json`
- `phase0/rubric-template.md`
- `role-specs/agent-codex-review-phase0.md`
- `agents/agent-codex-review-phase0.md`

The active dogfood path is plugin telemetry plus opt-in presets such as
`hybrid-review`. Use this harness only for a future isolated cohort where raw
Phase 0 adjudication is deliberately being rerun.

If the harness is retired later, remove it in one cohesive change that updates
the README, role specs, generated agents, docs, and path helpers together.
