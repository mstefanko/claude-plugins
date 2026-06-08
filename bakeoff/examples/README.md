# Bakeoff Examples

The example work orders are JSONC: they include comments so humans can learn the
shape quickly. `bakeoff validate` accepts JSONC, but strict JSON tools do not;
remove comments before pasting these files into a strict JSON-only editor or
API.

`plan-review.work-order.json` is a normal `gather` run with a data-only
`plan-review` facet. Use it for actionable defects in an implementation,
rollout, migration, or verification plan before code is written.

`single-provider.work-order.json` is an intentional Claude-only baseline. It
uses `run_mode: "single_provider"`, has exactly one provider, skips the judge,
and may carry `experiment.run_kind: "single_agent_baseline"` for external
analysis. A same-provider duplicate run is different: keep `run_mode:
"pairwise"` and use two unique provider ids such as `claude-a` and `claude-b`.

`repetition-loop.sh` is an instructional external harness example. It generates
ordinary work orders with optional `experiment` labels, validates each one,
runs with explicit deterministic run ids when `RUN_PROVIDERS=1`, skips runs
whose `manifest.json` already exists, verifies completed runs with
`bakeoff runs verify --json`, and models retries as new attempt run ids rather
than `--force`. It is an example script, not a stable Bakeoff scheduler API.
