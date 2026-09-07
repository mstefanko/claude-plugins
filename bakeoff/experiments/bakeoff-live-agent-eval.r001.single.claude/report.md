# Bakeoff Report: runmode-review-1273dce-single-claude

## Glossary

- `F-NNN`: report finding.

## Outcome

Mode: `gather`
Run mode: `single_provider`
Decision: `single_provider_result`
Facet: `code-review`
Facet Focus: Find actionable defects in the single-provider and experiment-metadata change: correctness, artifact-contract drift, stale pairwise wording, missing tests, and manifest/summary/report/ls output.
Result: single-provider result
Single provider: `claude`
Next: `bakeoff show bakeoff-live-agent-eval.r001.single.claude`

## Decision Audit

- Judge ran: `false`
- Judge completed: `false`

## Provider Status

| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |
|----------|--------|------|--------|--------|-------|-------|
| `claude` | `ok` | 496.881s | 14.3 KB | 0 B | codebase -> codebase (enforced) | stderr: `providers/claude/stderr.txt` |

## Findings

- **F-001** `reportGlossary` gates the nonwinner line on `decision["run_mode"]` but the `Render` function already has `wo *workorder.WorkOrder` with a `.RunMode` field in scope. The test at `report_test.go:TestRenderSingleProviderGlossaryOmitsPairwiseTerms` injects `run_mode` artificially into the decision map. The reference decision.json shape documented in the plans lists `canonical_winner`, `single_provider`, `decision_kind`, `selection_basis`, and judge flags, but not `run_mode`. If production `decision.json` omits `run_mode`, the check `jsonutil.StringValue(decision["run_mode"]) != workorder.RunModeSingleProvider` is always true (empty string != "single_provider") and the nonwinner glossary line appears in every single-provider report, leaving the stale pairwise wording in place. (source `claude`, severity `medium`, model confidence `medium`)
  Evidence: internal/report/report.go:1120, internal/report/report_test.go:TestRenderSingleProviderGlossaryOmitsPairwiseTerms, docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md — reference decision.json shape omits run_mode, internal/report/report.go:51 — Render has wo *workorder.WorkOrder in scope but passes only decision to reportGlossary
- **F-002** `verify.go:ExperimentMap` uses `stringPtrValue` for the string pointer fields `TaskID`, `ConditionID`, and `RunKind`, which returns `""` (empty string) when the pointer is nil. The slot fields `SlotID` and `SlotAttempt` are handled separately and are explicitly `nil` when absent. This creates an inconsistency: `verify --json` output produces `"task_id": ""` instead of `"task_id": null` for manifests where those fields are absent, while `"slot_id": null` is correct. Consumers distinguishing absent-vs-empty will misread absent string experiment fields. (source `claude`, severity `low`, model confidence `high`)
  Evidence: internal/verify/verify.go:220-224 — stringPtrValue used for TaskID, ConditionID, RunKind, internal/verify/verify.go:225-232 — slot fields handled with explicit nil, internal/verify/verify.go:241-249 — stringPtrValue returns "" for nil pointer
- **F-003** `slashDelimitedProse` was changed from `if len(parts) != 2 { return false }` (only 2-segment paths classified as prose) to `if len(parts) < 2 { return false }` (2+ segment paths classified as prose). Now any path with 2 or more all-lowercase no-dots segments whose first component is not in the known-prefix list is silently classified as prose, suppressing the path-existence warning. Real 3+ segment paths outside the `internal/cmd/pkg/src/app/apps/lib/libs/docs/test/tests/scripts` prefix set (e.g. `"services/auth/handler"`, `"api/v2/router"`) would be silently skipped and never checked for existence. (source `claude`, severity `medium`, model confidence `high`)
  Evidence: internal/repocontext/repocontext.go:307 — changed len(parts) != 2 to len(parts) < 2, internal/repocontext/repocontext.go:310-313 — only parts[0] is checked against known prefixes, internal/repocontext/repocontext_test.go:TestValidateProsePathsSkipsSlashDelimitedProse — updated to test 4-segment path meta/manifest/ls/summary
- **F-004** `researchRunDirIsIncomplete` at the end of the function returns `false` (not incomplete/reclaimable) if `os.ReadDir(runDir)` fails. This silently converts an OS-level error (permission denied, I/O error) into a "directory is not reclaimable" signal, causing the caller to fall through to the `already exists; use --force to replace` validation error. The caller at that point has no indication that the real cause was an OS error. (source `claude`, severity `medium`, model confidence `high`)
  Evidence: internal/commands/researchcmd/run.go:232-234 — os.ReadDir error returns false, not an error, internal/commands/researchcmd/run.go:68-70 — false return causes "already exists" validation error branch
- **F-005** When `opts.Force` is true, `ledger.EnsureChildPath(opts.Out, runDir)` is called twice: once in the `else` branch of the `!opts.Force` condition and again inside the `if replaceRunDir` block before `os.RemoveAll`. The second call is redundant. This is harmless but means the security path check incurs double invocation on every `--force` execution. (source `claude`, severity `low`, model confidence `high`)
  Evidence: internal/commands/researchcmd/run.go:64-67 — EnsureChildPath called in force branch, internal/commands/researchcmd/run.go:98-101 — EnsureChildPath called again inside replaceRunDir block
- **F-006** Both `TestRenderSingleProviderGlossaryOmitsPairwiseTerms` and `TestBuildResearchProjectsSingleProviderFields` inject `"run_mode": workorder.RunModeSingleProvider` directly into the decision/input map. There is no test verifying `reportGlossary` behavior when `run_mode` is absent from the decision map but `decision_kind` is `"single_provider_result"`. This is the key production scenario: if decision.json contains `decision_kind: "single_provider_result"` but no `run_mode` key, the glossary gate fails silently and the fix provides no coverage assurance. (source `claude`, severity `medium`, model confidence `high`)
  Evidence: internal/report/report_test.go:TestRenderSingleProviderGlossaryOmitsPairwiseTerms — decision map explicitly includes run_mode, internal/summary/summary_test.go:TestBuildResearchProjectsSingleProviderFields — decision map explicitly includes run_mode, internal/report/report.go:1120 — gate only checks run_mode, not decision_kind
- **F-007** `live-single-provider-plan-review.work-order.json` has id `"live-single-provider-plan-review"` but specifies two providers (`claude/sonnet` + `codex/gpt-5.5`) and no `run_mode` field, meaning it defaults to pairwise. The plan document `single-provider-telemetry-hardening-plan-2026-06-08.md` confirms this run produced `pick_winner → claude` via `swap_agreement`. Artifacts written from this work order (manifest.json, decision.json, report.md) will appear under the misleadingly named run id and may cause confusion when referenced as evidence for single-provider behavior. (source `claude`, severity `low`, model confidence `high`)
  Evidence: bakeoff/live-single-provider-plan-review.work-order.json:3-4 — id is live-single-provider-plan-review, no run_mode field, bakeoff/live-single-provider-plan-review.work-order.json:9-12 — two providers listed, bakeoff/docs/single-provider-telemetry-hardening-plan-2026-06-08.md — Source Run section confirms pick_winner result
- **F-008** `manifest.go:addExperimentManifestFields` falls back to `workOrder["experiment"]` when `meta["experiment"]` is absent or empty (len==0). The new test `TestWriteRunManifestFallsBackToWorkOrderExperiment` covers only the fully-absent-from-meta case. No test covers the scenario where `meta["experiment"]` is non-empty (some fields present) but missing required keys — in that case the fallback is NOT triggered and the partial meta map is used directly, potentially hoisting an incomplete experiment identity into the manifest. (source `claude`, severity `low`, model confidence `high`)
  Evidence: internal/manifest/manifest.go:383-390 — fallback only triggers on !ok || len(experiment)==0, internal/manifest/manifest_test.go:TestWriteRunManifestFallsBackToWorkOrderExperiment — only tests fully-absent meta experiment
- **F-009** `manifest.go:diagnosticStderrOnly` exempts diagnostic stderr from the truncation alarm via `artifact.ProviderSucceeded(status)`. If a provider exits non-zero (status != "ok") but its stderr is classified as `diagnostic`, the truncation IS counted. This is correct behavior for failed runs. However, the test case at `manifest_test.go:TestBuildManifestTelemetryOutputTruncationCount` ("diagnostic stderr truncation is not alarming") uses `decision_kind: "pick_winner"` with `judge_ran: false` — an internally inconsistent fixture — rather than a more representative single-provider or non-judge decision shape. The fixture covers the code path but its decision shape is not a valid production state. (source `claude`, severity `low`, model confidence `high`)
  Evidence: internal/manifest/manifest.go:677-679 — diagnosticStderrOnly checks stderr_kind and ProviderSucceeded, internal/manifest/manifest_test.go:941-962 — test uses decision_kind:pick_winner with judge_ran:false

## Unknowns

- **F-010** Whether production single-provider decision.json written by internal/decision/decision.go:SingleProviderResult includes a top-level run_mode field — the reference plan shape does not list it, but the verify and report tests both inject it. This determines whether R-001 and R-006 are theoretical or actual production failures.
- **F-011** Full source of internal/commands/researchcmd/run.go beyond the diff — specifically whether there is a second run-dir existence check at ~line 248 (referenced in the hardening plan as having no --force escape) that may remain unaddressed by this diff.
