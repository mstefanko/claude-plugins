# ADR 0002 — Telemetry Sources of Truth

Status: Accepted
Date: 2026-04-23
Supersedes: none
Related: ADR 0001, phases 9a–9g, phase 10 refactor plan

## Context

`swarm-do/bin/swarm-telemetry` grew into a 1,500-line bash script that
hand-rolls a draft-07 validator, owns ledger filenames, duplicates required
field lists, and embeds per-subcommand Python snippets via heredocs. The same
ledger metadata is restated in role specs under `roles/*/shared.md` and
across several bash helpers. Drift between these copies caused phase 9
regressions (findings v2 rollout, adjudications sampler).

We need a small set of authoritative owners so future phases can generate
everything else from them.

## Decision

Three — and only three — sources of truth for telemetry metadata and
behavior:

1. **Python telemetry package** (`swarm-do/py/swarm_do/telemetry/`).
   Owns validator semantics, atomic write path, ID generation, and the
   CLI dispatcher. Phase 1 ships the skeleton; phases 2+ migrate
   subcommands into it incrementally.
2. **Role specs** (`swarm-do/roles/*/spec.yaml`). Own the per-role
   prompt bundles, telemetry field emission rules, and risk tags.
3. **Ledger registry** (`swarm_do.telemetry.registry.LEDGERS`). Owns
   ledger names, JSONL filenames, canonical schema paths, and the
   v2→v1 fallback order. Every other module resolves schemas and
   filenames through this dict.

The top-level `agents/` tree and `roles/*/shared.md` files become
**generated artifacts** in phase 5, produced from the three sources above.
They stop being hand-edited.

## Consequences

Positive:

- Validator semantics live in one file and gain test coverage.
- Adding a ledger is one registry entry + one schema file; no bash edits required.
- Drift between role specs, shared.md, and agent prompts is eliminated by
  generation.

Negative / follow-on work:

- Phase 2 must migrate `validate` and `dump` to Python without changing
  user-visible output; phase 3 replaces the bash validator entirely.
- Phase 5 generation pipeline is a new CI build step.
- Legacy bash remains at `bin/swarm-telemetry.legacy` until all subcommands
  are ported and phase 3 reaches message parity.
