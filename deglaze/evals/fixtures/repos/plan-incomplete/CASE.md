# R2 — incomplete implementation plan

Removed by the harness before the model runs.

Expected: Needs surgery or Nope, 2-5 Change items. Must include the missing rollback and
the non-criterion validation ("Test it. If the search feels fast, we are done.").
Other fair findings: steps are not concrete artifacts ("Add the index", "Clean up anything
left over"), §5 mentions batching a backfill that no step defines, §7 invites scope creep
that serves no stated goal, and CREATE INDEX without CONCURRENTLY on a live table is never
addressed.

Same code and schema as plan-complete, so premise claims are still true.
