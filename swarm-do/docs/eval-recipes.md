# Eval Recipes

Date: 2026-04-27

This is the recipe-first outcome dashboard for preset promotion. The source of
truth is still the append-only ledgers under
`${CLAUDE_PLUGIN_DATA}/telemetry/`; the TUI should mirror these commands before
it grows richer charts.

## Baseline Gate

Before promoting a preset above `balanced`, capture at least 10 representative
tasks with `balanced` and the candidate preset. Compare by
`(pipeline_name, phase_kind, phase_complexity)`.

Promotion gate:

- Beat `balanced` on accepted findings, rework rate, or
  wall-time-per-accepted-fix.
- Keep cost delta at or below +25 percent.
- Tie means stay on `balanced`.

## Reproducible Reports

Run a top-line stratified report:

```bash
bin/swarm-telemetry report --since 30d --bucket phase_kind
bin/swarm-telemetry report --since 30d --bucket complexity
bin/swarm-telemetry report --since 30d --bucket risk_tag
```

Compare pipelines by phase kind and complexity:

```bash
bin/swarm-telemetry query '
select
  coalesce(pipeline_name, "(none)") as pipeline,
  coalesce(phase_kind, "(none)") as phase_kind,
  coalesce(phase_complexity, "(none)") as complexity,
  count(*) as runs,
  round(avg(cast(wall_clock_seconds as real)), 1) as mean_wall_s,
  round(avg(cast(estimated_cost_usd as real)), 4) as mean_cost_usd
from runs
group by pipeline, phase_kind, complexity
order by pipeline, phase_kind, complexity;
'
```

Measure accepted findings by producing role:

```bash
bin/swarm-telemetry query '
select
  f.role,
  count(*) as accepted_findings
from findings f
join finding_outcomes o on o.finding_id = f.finding_id
where o.maintainer_action in ("fixed_in_same_pr", "followup_issue", "followup_pr", "hotfix_within_14d")
group by f.role
order by accepted_findings desc, f.role;
'
```

Estimate a non-actioned rate from maintained finding outcomes. This is not a
true false-positive rate; use blinded `adjudications.jsonl` for that once the
outcome linkage is active.

```bash
bin/swarm-telemetry query '
select
  f.role,
  count(*) as adjudicated_findings,
  sum(case when o.maintainer_action in ("ignored") then 1 else 0 end) as ignored_findings,
  round(
    1.0 * sum(case when o.maintainer_action in ("ignored") then 1 else 0 end)
    / nullif(count(*), 0),
    3
  ) as ignored_rate
from findings f
join finding_outcomes o on o.finding_id = f.finding_id
group by f.role
order by ignored_rate desc, f.role;
'
```

Track rework through retries and handoffs:

```bash
bin/swarm-telemetry query '
select
  coalesce(pipeline_name, "(none)") as pipeline,
  count(*) as runs,
  sum(case when writer_status = "HANDOFF_REQUESTED" then 1 else 0 end) as handoffs,
  sum(case when exit_code != "0" then 1 else 0 end) as nonzero_exits
from runs
group by pipeline
order by pipeline;
'
```

Compute wall-time-per-accepted-fix:

```bash
bin/swarm-telemetry query '
with accepted as (
  select f.run_id, count(*) as accepted_count
  from findings f
  join finding_outcomes o on o.finding_id = f.finding_id
  where o.maintainer_action in ("fixed_in_same_pr", "followup_issue", "followup_pr", "hotfix_within_14d")
  group by f.run_id
)
select
  coalesce(r.pipeline_name, "(none)") as pipeline,
  sum(cast(r.wall_clock_seconds as real)) as wall_s,
  sum(accepted.accepted_count) as accepted_findings,
  round(sum(cast(r.wall_clock_seconds as real)) / nullif(sum(accepted.accepted_count), 0), 1)
    as wall_s_per_accepted_finding
from runs r
join accepted on accepted.run_id = r.run_id
group by pipeline
order by wall_s_per_accepted_finding asc;
'
```

## Outcome Ledgers

Use `finding_outcomes.jsonl` as the concrete maintained outcome signal today:

```bash
bin/swarm-telemetry join-outcomes --since 30d --dry-run
bin/swarm-telemetry sample-for-adjudication --count 25 --since 30d
```

Treat `outcomes.jsonl` as optional until the phase-outcome writer is active for
the pipeline being evaluated. Judge disagreements should first be emitted as
findings/run notes; write adjudication rows only after the outcome linkage is
available.
