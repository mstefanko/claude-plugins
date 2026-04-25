# Cleanup Inventory

Created during the 2026-04 cleanup pass. `docs/plan.md` remains the canonical
implementation plan; this file records repository hygiene decisions only.

## Keep

- Runtime code: `bin/`, `commands/`, `hooks/`, `py/swarm_do/`, and
  `skills/swarm-do/`.
- Stock presets and pipelines: `presets/` and `pipelines/`.
- Schemas and validation fixtures: `schemas/`, `tests/fixtures/`, and
  `py/swarm_do/**/tests/fixtures/`.
- ADRs and provenance: `docs/adr/`, `docs/history/`, and `docs/provenance/`.
- Generated role outputs and their sources: `agents/`, `roles/`, and
  `role-specs/`.
- Phase 0 harness files while they remain documented as a standalone experiment
  surface: `bin/codex-review-phase`, `phase0/`, and
  `agent-codex-review-phase0` specs/outputs.

## Archive

- Useful historical migration notes and provenance under `docs/history/` and
  `docs/provenance/`.
- Concise summaries of one-off spike outputs after the raw data is no longer
  needed in the source tree.

## Delete

- Ephemeral phase extract files that have been merged into `docs/plan.md` and
  are no longer active runnable plans.
- Raw one-off spike output directories after their findings are summarized.
- Prompt shards that only reproduce a completed one-off spike and are not
  reusable operator templates.

## Ignore

- Local runtime state: active preset, telemetry ledgers, active run/checkpoint
  artifacts, and in-flight lockfiles.
- Local TUI virtual environments.
- Python bytecode/caches and common local logs/temp files.
- Scratch `codex-review-*.json` review captures.
