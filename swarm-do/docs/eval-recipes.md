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

## Prepare Gate Phase 6 Scorecard

Phase 6 keeps `--prepare --continue` blocked until the two-step prepare gate
has dogfood evidence. The source rows are `telemetry/run_events.jsonl` for
prepare lifecycle events plus the existing run, finding, outcome, adjudication,
and observation ledgers for downstream churn.

Promotion gate for `--prepare --continue`:

- At least 10 representative dogfood runs have both prepared and non-prepared
  comparison notes.
- Operator interventions per run decrease or stay flat.
- Manual plan-review time decreases or stays flat.
- `NEEDS_CONTEXT`, spec-mismatch retries, and review failures do not increase.
- Final review churn and decomposition rejections do not increase.
- Wall-clock stays within the operator's accepted budget for the phase class.
- Code-only changes can skip docs only when analysis, writer, or deterministic
  diff classification records `doc_impact: false`.

Hold criteria:

- Fewer than 10 dogfood runs exist.
- Any non-regressive safety metric is unknown.
- `prepare_stale_rejected` events appear without an operator-visible reason.
- Docs or spec-review gating lacks a deterministic post-writer summary.

Rollback criteria after opt-in use:

- `NEEDS_CONTEXT`, spec mismatches, review failures, or stale dispatch rejects
  increase in two consecutive dogfood batches.
- A prepared dispatch bypasses artifact status, stale, sidecar hash, or
  trust-boundary validation.
- A doc-stage skip misses a required documentation update.

Prepare lifecycle sanity check:

```bash
python3 - <<'PY'
import collections, json, os, pathlib

data = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_DATA", "data"))
events = data / "telemetry" / "run_events.jsonl"
counts = collections.Counter()
if events.exists():
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event_type", "").startswith("prepare_"):
            counts[row["event_type"]] += 1
for event_type, count in sorted(counts.items()):
    print(f"{event_type}\t{count}")
PY
```

Required event coverage for each dogfood batch:

- `prepare_started`
- `prepare_lint_findings`
- `prepare_review_findings`
- `prepare_safe_fixes_accepted`
- `prepare_safe_fixes_proposed_unaccepted`
- `prepare_ready_for_acceptance` or `prepare_blocking_findings`
- `prepare_accepted` for runs that proceed
- `prepare_stale_rejected` when stale acceptance or dispatch is refused
- `prepare_dispatch_started` before execution from an accepted artifact

Controlled-experiment status as of 2026-04-28: **HOLD**. Phase 7 remains
blocked until the following comparisons are recorded with real dogfood data:

| Experiment | Required comparison | Current decision |
|---|---|---|
| Current decomposition vs semantic decomposition | 10 phases; compare mean and p95 unit tool calls, wall-clock, tokens, cache hit ratio, repeated source reads, handoffs, `NEEDS_CONTEXT`, spec mismatches, review failures | Hold; no Phase 6 dogfood batch recorded yet |
| Prompt-only tightening vs decompose-only tightening | Same phase set; isolate prompt policy changes from work-unit splitting changes | Hold; no controlled batch recorded yet |
| Test-first vs implement-then-test for parser/CLI tasks | Parser and CLI phases only; compare first-test position, retries, review findings, and wall-clock | Hold; no controlled batch recorded yet |
| Notes-only analysis vs source-allowed analysis on hard phases | Hard phases only; compare repeated source reads, gaps returned as `NEEDS_RESEARCH`, `NEEDS_CONTEXT`, and review failures | Hold; no controlled batch recorded yet |
| Downstream gating | Prepared work-unit runs; compare doc-stage skip rate, spec-review source reads, and missed documentation fixes | Hold; do not enable by default |

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
