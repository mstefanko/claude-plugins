# Bakeoff Report: runmode-review-1273dce-single-codex

## Glossary

- `F-NNN`: report finding.

## Outcome

Mode: `gather`
Run mode: `single_provider`
Decision: `single_provider_result`
Facet: `code-review`
Facet Focus: Review the 386accc..HEAD diff as a single-provider Codex baseline: flag correctness bugs, artifact-contract drift, stale pairwise wording, missing test coverage, and single_provider experiment metadata handling, with file and line evidence.
Result: single-provider result
Single provider: `codex`
Next: `bakeoff show bakeoff-live-agent-eval.r001.single.codex`

## Decision Audit

- Judge ran: `false`
- Judge completed: `false`

## Provider Status

| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |
|----------|--------|------|--------|--------|-------|-------|
| `codex` | `ok` | 335.701s | 6.8 KB | 58.6 KB (trunc, +541.2 KB) | codebase -> codebase (enforced) | stderr kind: diagnostic; stderr: `providers/codex/stderr.txt` |

## Findings

- **F-001** `runs verify` still does not validate the manifest-side single-provider contract: `manifest.json` is documented and written with `run_mode`, `single_provider`, `canonical_winner`, and judge flags, but verify only parses `run_mode`, experiment fields, and fingerprints from the manifest and then validates only `decision.json`. A corrupted single-provider manifest with the wrong or missing `single_provider` can therefore pass if the decision is correct. (source `codex`, severity `medium`, model confidence `medium`)
  Evidence: docs/cli-reference.md:571, internal/manifest/manifest.go:104, internal/manifest/manifest.go:105, internal/manifest/manifest.go:111, internal/manifest/manifest.go:113, internal/verify/verify.go:193, internal/verify/verify.go:353
- **F-002** `validateSingleProviderDecision` does not enforce that `canonical_winner` is actually JSON null; it only rejects values whose string form is non-empty. Because `jsonutil.StringValue(nil)` and `jsonutil.StringValue("")` both produce an empty string, `canonical_winner: ""` would pass verification even though the single-provider decision writers set this field to null and the test only covers a non-empty winner. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/verify/verify.go:362, internal/jsonutil/jsonutil.go:10, internal/jsonutil/jsonutil.go:14, internal/decision/decision.go:97, internal/decision/decision.go:109, internal/verify/verify_test.go:260
- **F-003** The new output-truncation telemetry can undercount real retained-output loss: `outputTruncationCount` ignores truncated stderr whenever `stderr_kind == "diagnostic"` and the provider succeeded, but `StderrKind` assigns `diagnostic` to any non-empty successful stderr that is not recognized Codex transport noise. A successful provider that emits a large warning/error stream on stderr can be truncated without increasing `telemetry.artifacts.output_truncation_count`. (source `codex`, severity `medium`, model confidence `medium`)
  Evidence: internal/manifest/manifest.go:673, internal/manifest/manifest.go:680, internal/manifest/manifest.go:681, internal/artifact/artifact.go:132, internal/artifact/artifact.go:137, internal/artifact/artifact.go:140, internal/artifact/artifact.go:143
- **F-004** The new incomplete-run reclaim path can delete an existing scaffold without `--force` based only on an allowlist of filenames, not on whether the archived `work-order.json` matches the incoming work order. Reusing a run id that points at an earlier incomplete scaffold containing `work-order.json` and review-context artifacts will set `replaceRunDir` and then `RemoveAll` that directory. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/commands/researchcmd/run.go:61, internal/commands/researchcmd/run.go:63, internal/commands/researchcmd/run.go:100, internal/commands/researchcmd/run.go:104, internal/commands/researchcmd/run.go:229, internal/commands/researchcmd/run.go:239, internal/commands/researchcmd/run.go:245
- **F-005** Human `bakeoff ls` output still cannot identify which provider ran a single-provider job. The manifest-backed row contains `run_mode` and `single_provider`, but the standard table and `--history` table print only run id/type/facet/decision/triage/finished or summary columns. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/manifest/manifest.go:170, internal/manifest/manifest.go:171, internal/commands/lscmd/ls.go:162, internal/commands/lscmd/ls.go:168, internal/commands/lscmd/ls.go:205, internal/commands/lscmd/ls.go:214
- **F-006** `runs verify --json` now projects experiment metadata from `manifest.json`, but it does not validate that the required experiment identity fields are present or compatible with the run mode. If a manifest has `experiment_id` but drops `task_id`, `condition_id`, `run_kind`, or `repetition_index`, `ExperimentMap` can still emit an `experiment` object with empty strings or nulls while `Run` only checks manifest schema version, run id, and fingerprints. (source `codex`, severity `low`, model confidence `medium`)
  Evidence: docs/work-orders.md:217, docs/work-orders.md:223, internal/verify/verify.go:85, internal/verify/verify.go:89, internal/verify/verify.go:207, internal/verify/verify.go:211, internal/verify/verify.go:232, internal/verify/verify_test.go:228

## Unknowns

- None reported.
