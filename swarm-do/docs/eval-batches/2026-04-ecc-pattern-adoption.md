# Prepare Gate Batch 2026-04 — ECC Pattern Adoption

## Scope

- Batch id: `2026-04-ecc-pattern-adoption`
- Date range: 2026-04-28 — TBD
- Operator: mike.stefanko@enovis.com
- Repo(s): `mstefanko-plugins` (swarm-do)
- Purpose: First controlled dogfood of the prepare-gate flow against the ECC
  Pattern Adoption plan. Establishes baseline telemetry for the
  `prep6.semantic.*` variant family before broader rollout.

## Arms

| Arm | Variant label | Description | Config or preset |
|---|---|---|---|
| A | `prep6.semantic.a` | Default prepare-gate path with semantic decompose | active preset (TBD) |
| B | `prep6.semantic.b` | Comparison arm — fill in once a contrasting config is chosen | TBD |

> Single-arm batches are valid for baseline collection but do not produce
> promotion evidence. Add Arm B before requesting `PROMOTE`.

## Phases

| Phase id | Beads issue | Repo | Base SHA | Kind | Complexity | Risk tags | Worktree A | Worktree B | Included | Exclusion reason |
|---|---|---|---|---|---|---|---|---|---|---|
| ecc-phase-0-baseline | TBD | mstefanko-plugins | `313c986` | feature | moderate | low | TBD | TBD | yes | — |
| ecc-phase-1-selftest | TBD | mstefanko-plugins | `313c986` | feature | moderate | low | TBD | TBD | no | deferred until phase 0 lands |
| ecc-phase-2-hook-profiles | TBD | mstefanko-plugins | `313c986` | feature | moderate | moderate | TBD | TBD | no | depends on phase 1 |
| ecc-phase-3-security-audit | TBD | mstefanko-plugins | `313c986` | feature | moderate | moderate | TBD | TBD | no | later batch |
| ecc-phase-4-activity-telemetry | TBD | mstefanko-plugins | `313c986` | feature | moderate | moderate | TBD | TBD | no | later batch |
| ecc-phase-5-unit-snapshots | TBD | mstefanko-plugins | `313c986` | feature | moderate | low | TBD | TBD | no | later batch |
| ecc-phase-6-codex-surface | TBD | mstefanko-plugins | `313c986` | feature | low | low | TBD | TBD | no | later batch |

> Initial dogfood scope: Phase 0 only. Expand after the first prepared run
> closes cleanly.

## Manual Safety Notes

| Phase id | Arm | Operator interventions | Plan-review minutes | Missed docs fix | Spec/review mismatch notes |
|---|---|---:|---:|---|---|
| ecc-phase-0-baseline | A |  |  | no |  |

## Report Commands

```bash
# Run after the prepared dispatch closes.
swarm-do/bin/swarm-telemetry experiment-report --batch 2026-04-ecc-pattern-adoption
swarm-do/bin/swarm-telemetry dogfood-check     --batch 2026-04-ecc-pattern-adoption \
  --format markdown --output swarm-do/docs/eval-batches/2026-04-ecc-pattern-adoption.report.md
```

## Decision

- Decision: HOLD
- Reason: Single-arm baseline; promotion evidence requires Arm B and at least
  one closed phase per arm.
- Unknown safety metrics: Arm B variant, comparative tool-call p95, repeated-
  read deltas, prepare-event coverage.
