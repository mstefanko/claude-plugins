# MCO Spike 1.12 Summary

This note replaces the raw tracked prompt and result artifacts that were used
for a one-off manual `bin/swarm-stage-mco` review of the 1.12
orchestration-friction plan.

The spike was useful for plan shaping, but the raw JSON/stdout/stderr files are
not runtime inputs and should not live under `data/`, which is reserved for
ignored local operator state.

## Result Inventory

| Slice | Findings | Severity mix | Main signal |
|-------|----------|--------------|-------------|
| Whole-plan coherence | 13 | 5 high, 8 medium | Avoid duplicate state stores, split oversized phases, and define token/watchdog observation mechanisms before implementation. |
| Context resilience | 14 | 1 critical, 8 high, 4 medium, 1 low | Do not depend on unproven PreCompact behavior, freeze the run identity model, and define BEADS/checkpoint authority before resume work. |
| Preflight permissions | 10 | 8 high, 2 medium | Align branch and plan-shape preflights with the documented plugin workflow, and specify permission install rollback/confirmation. |
| DAG retry commit | 11 | 2 critical, 5 high, 4 medium | Separate stage DAG execution from work-unit DAG execution, define integration-branch conflict handling, and specify retry persistence. |
| Knowledge adversarial validation | 10 | 5 high, 5 medium | Avoid turning `knowledge.jsonl` into a second behavioral source of truth; register schemas and retry semantics before adding writes. |

## Preserved Decisions

- Treat provider stages as evidence-only. They can summarize findings for
  downstream reviewers, but they must not approve, reject, merge, or mutate
  repo state.
- Keep the run/checkpoint model single-authority: BEADS remains the task graph,
  while checkpoint files are resumability mirrors with explicit drift handling.
- Keep `data/` out of source control for local state and generated run output.
  Historical spike results belong in concise docs summaries like this one.
- Keep one-off prompt shards out of the repository unless they become reusable
  operator templates.
