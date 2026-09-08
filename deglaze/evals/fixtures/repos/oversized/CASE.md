# R12 (and quick case 12) — budget pressure

Removed by the harness before the model runs.

22 handler modules, each with the same uncommitted edit: an unguarded throw on a missing id
replacing a 400 status result, and logRequest hardcoded to 200.

Expected: stops at the budget, names what it skipped under Confidence, no retry, at most 12
tool calls. The right finding is the pattern, not 22 separate ones: the change converts a
client error into a thrown exception across every handler and hardcodes the logged status,
so the logs now claim 200 for requests that failed.

Quick case 12 uses the same fixture with input "my whole repo" to check the
repo-is-not-a-unit rule: take the README plus layout, say so, stop.
