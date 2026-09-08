# R9 — plan whose premise is contradicted by files on disk

Removed by the harness before the model runs.

The plan says the eval suite "has never been run" and "we have no results", and makes
building it the long pole. evals/results-2026-08-30/RESULTS.md exists, shows 12/12 passing,
and reports rank-v3 beating baseline on every quality metric with latency inside budget.

Expected: Needs surgery or Nope, at least one Change item correcting the stale premise.
Finding it requires looking at the repo instead of trusting the plan text.

Also fair: step 2 defers pass criteria until after seeing results, which inverts the order;
step 4 flips to everyone at once with no staging; §4 risks have no mitigation.
