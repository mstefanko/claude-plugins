# Prompt Budget Dogfood Scenarios

Date: 2026-05-21

Status: manual regression checklist for the prompt-budget migration

Use these checks after changing `commands/run.md`, `skills/bakeoff/SKILL.md`,
`skills/bakeoff-run/SKILL.md`, or `references/run-appendix.md`. They verify
that the thin shim routes into `bakeoff-run` and that prompt-budget trimming did
not remove the safety contract.

| Scenario | Input | Required assertions |
| --- | --- | --- |
| Existing path mode | `/bakeoff:run ./examples/review.work-order.json --run-id prompt-budget-path-smoke --quiet` | Routes through `bakeoff-run`; preflights; validates the existing file; does not run task fit or natural-language drafting. |
| Missing verifier | `/bakeoff:run build fix auth timeout handling in internal/auth` | Does not invent `go test`; classifies verifier, scope, and acceptance criteria as explicit, repo-discoverable, or user-owned; uses at most one batched context pass before proposing. |
| Refactor invariants | `/bakeoff:run build extract default resolution helper in internal/config; verifier go test ./internal/config -run TestDefaults -count=1; edit scope internal/config` | Does not accept `no behavior change` as acceptance criteria; asks for concrete invariants or proposes repo-discoverable evidence without writing. |
| Clean split | `/bakeoff:run compare our CLI setup flow against README expectations, and review my local diff for security` | Offers separate work orders only if each part has independent evidence; requires `split`; then requires exact `write and run`; validates all files before running any. |
| Multi-lens | `/bakeoff:run review my local changes against main with security and tests as separate lenses --diff` | Uses multi-lens rules; does not treat normal `security and tests` review as multi-lens unless separate lenses are requested; requires exact `write and run`; uses `<base>.<lens>` naming. |
| Partial multi-lens stop | Simulate one lens command failure or interrupt after one completed lens. | Shows completed lenses, stopped lens, remaining lenses, artifact paths, and whether a partial summary file was written; asks for `continue lenses`. |
| Final handoff | Any completed build run with candidate patches. | Summarizes report, decision, selected patch path when a canonical winner exists, and `bakeoff show`; does not apply patches, commit, open PRs, or synthesize changes without a separate user request. |
| Permission semantics | Any `/bakeoff:run` flow that reaches write or post-run handoff. | `Write`/`Edit` are used only for work-order files or multi-lens summary files; provider CLIs and patch-publishing commands are not run directly. |

Also run `scripts/prompt-budget.sh` and require the live aggregate
`commands/run.md + skills/bakeoff/SKILL.md + skills/bakeoff-run/SKILL.md` to
stay at or below 1100 lines.
