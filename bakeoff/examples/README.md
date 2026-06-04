# Bakeoff Examples

The example work orders are JSONC: they include comments so humans can learn the
shape quickly. `bakeoff validate` accepts JSONC, but strict JSON tools do not;
remove comments before pasting these files into a strict JSON-only editor or
API.

`plan-review.work-order.json` is a normal `gather` run with a data-only
`plan-review` facet. Use it for actionable defects in an implementation,
rollout, migration, or verification plan before code is written.
