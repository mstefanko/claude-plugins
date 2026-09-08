# R1 — complete implementation plan

Removed by the harness before the model runs.

Expected: Annoyingly solid (Worth a cheap test acceptable), at most one Change item.
The plan has concrete named artifacts, a rollback for both the pre-flag and post-flag
states, the invalid-index failure mode, and four numeric pass criteria sourced from existing
metrics. Keep should name shipping behind a flag with a concurrent index build.

Traps: §2's claim about the schema is TRUE (db/schema.sql has no composite index), so a
"stale premise" finding is a false positive. The 12-18 minute estimate is extrapolated and
labeled as such, so calling it unproven is at most a Risk.

Every mechanism the plan names must exist here, or the case stops testing what it claims to.
On 2026-09-08 this fixture had no flag system, and the model correctly returned "Needs
surgery" with two well-evidenced findings: the plan hung a staged rollout and a no-deploy
rollback on a `config/flags.yaml` that did not exist. That was a fixture bug, not a false
positive. `config/flags.yaml` and `src/config/flags.ts` now provide the watched-file loader,
per-tenant allow list, and percentage bucketing that §4 step 2 and §5 assume. If you edit
this plan, check that the repo still backs every claim it makes.
