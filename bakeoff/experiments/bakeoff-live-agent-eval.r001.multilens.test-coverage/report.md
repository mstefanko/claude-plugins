# Bakeoff Report: bakeoff-live-agent-eval.r001.multilens.test-coverage

## Glossary

- `F-NNN`: report finding.
- Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved.

## Outcome

Mode: `gather`
Run mode: `pairwise`
Decision: `single_provider_only`
Facet: `code-review`
Facet Focus: Find actionable test-coverage gaps for behavior changed in the diff: untested branches, missing edge cases, and weak assertions in the changed *_test.go files.
Winner: `codex`
Next: `bakeoff show bakeoff-live-agent-eval.r001.multilens.test-coverage`

## Selector Confidence

- Selector label: `unresolved`
- Evidence: only `codex` completed successfully; no two-provider selector ran.
- Decision effect: partial result only; treat the surfaced provider output as incomplete competitive evidence.

## Decision Audit

- Judge ran: `false`
- Canonical winner: `codex`

## Provider Status

| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |
|----------|--------|------|--------|--------|-------|-------|
| `claude` | `schema_error` | 206.485s | 18.4 KB | 0 B | codebase -> codebase (enforced) | stderr kind: errors; failure kind: schema_error; stderr: `providers/claude/stderr.txt` |
| `codex` | `ok` | 263.281s | 8.8 KB | 58.6 KB (trunc, +357.0 KB) | codebase -> codebase (enforced) | stderr kind: diagnostic; stderr: `providers/codex/stderr.txt` |

## Findings

- **F-001** The manifest fallback test does not meaningfully assert all experiment fields on the new work-order fallback path: the fixture includes task_id, condition_id, and run_kind, and production writes those fields, but the assertion only checks experiment_id, repetition_index, slot_id, and slot_attempt. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/manifest/manifest.go:385, internal/manifest/manifest.go:396, internal/manifest/manifest.go:399, internal/manifest/manifest.go:402, internal/manifest/manifest_test.go:257, internal/manifest/manifest_test.go:276
- **F-002** The verify JSON experiment projection test leaves condition_id, run_kind, and repetition_index unasserted even though the new Result.Experiment contract projects them; a regression dropping those fields from runs verify --json would still pass this test. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/verify/verify.go:211, internal/verify/verify.go:214, internal/verify/verify.go:215, internal/verify/verify.go:220, internal/verify/verify_test.go:236, internal/verify/verify_test.go:250
- **F-003** The new single-provider decision verifier has branches for missing/unreadable decision.json, invalid decision_kind, missing single_provider, judge_attempted, and judge_completed, but the changed test asserts only canonical_winner and judge_ran failures. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/verify/verify.go:353, internal/verify/verify.go:359, internal/verify/verify.go:365, internal/verify/verify.go:368, internal/verify/verify_test.go:255, internal/verify/verify_test.go:279
- **F-004** The single-provider verify trigger is an OR over manifest.run_mode and decision.run_mode, but the changed test sets run_mode in both places, so it does not cover either source independently. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/verify/verify.go:100, internal/verify/verify.go:101, internal/verify/verify.go:102, internal/verify/verify_test.go:257, internal/verify/verify_test.go:267
- **F-005** The diagnostic-stderr truncation test only covers a successful provider, leaving the ProviderSucceeded guard untested for failed providers; a regression that ignores failed diagnostic stderr truncation would undercount a real failed-run output alarm. (source `codex`, severity `medium`, model confidence `high`)
  Evidence: internal/manifest/manifest.go:673, internal/manifest/manifest.go:680, internal/manifest/manifest.go:681, internal/manifest/manifest_test.go:945, internal/manifest/manifest_test.go:953, internal/manifest/manifest_test.go:957
- **F-006** The incomplete-run reclaim tests do not exercise the allowed review-context scaffold branch: production treats source-work-order.json, review-context.md, and review-context.json as reclaimable, but the success test creates only work-order.json. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/commands/researchcmd/run.go:239, internal/commands/researchcmd/run.go:241, internal/commands/researchcmd/run.go:242, internal/commands/researchcmd/run.go:243, internal/commands/researchcmd/run_test.go:153, internal/commands/researchcmd/run_test.go:157
- **F-007** The incomplete-run reclaim tests do not assert that directories containing decision.json or manifest.json are preserved without --force; a regression in this branch could delete a completed run when retrying a run id. (source `codex`, severity `high`, model confidence `high`)
  Evidence: internal/commands/researchcmd/run.go:61, internal/commands/researchcmd/run.go:63, internal/commands/researchcmd/run.go:230, internal/commands/researchcmd/run.go:231, internal/commands/researchcmd/run.go:232, internal/commands/researchcmd/run_test.go:171, internal/commands/researchcmd/run_test.go:197, internal/commands/researchcmd/run_test.go:207
- **F-008** The scope enforcement test added for the new enforced-with-mechanisms/no-fallback behavior covers Codex codebase only; Claude codebase with disallowed_tools takes the same production branch but its existing test does not assert enforcement_level or fallback_reason. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/scope/scope.go:71, internal/scope/scope.go:74, internal/scope/scope.go:109, internal/scope/scope.go:110, internal/scope/scope_test.go:52, internal/scope/scope_test.go:186, internal/scope/scope_test.go:194, internal/scope/scope_test.go:200
- **F-009** The ResolveAnalyze selection_basis test covers only the swap_agreement tiebreak, leaving the new selection_basis assignment untested for the atomic_count and position_a tiebreak paths. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/decision/decision.go:198, internal/decision/decision.go:204, internal/decision/decision.go:207, internal/decision/decision.go:229, internal/decision/decision.go:230, internal/decision/decision_test.go:96, internal/decision/decision_test.go:108
- **F-010** The research command JSON summary experiment test supplies condition_id, run_kind, and repetition_index but does not assert them, so BuildResearch could stop projecting those experiment metadata fields while this test still passes. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/summary/summary.go:269, internal/workorder/workorder.go:397, internal/workorder/workorder.go:399, internal/workorder/workorder.go:400, internal/workorder/workorder.go:401, internal/summary/summary_test.go:90, internal/summary/summary_test.go:96
- **F-011** The build command JSON summary experiment test supplies condition_id, run_kind, and repetition_index but does not assert them, so buildSummary could regress to a partial experiment object while the changed test still passes. (source `codex`, severity `low`, model confidence `high`)
  Evidence: internal/commands/buildcmd/summary.go:57, internal/workorder/workorder.go:397, internal/workorder/workorder.go:399, internal/workorder/workorder.go:400, internal/workorder/workorder.go:401, internal/commands/buildcmd/summary_test.go:23, internal/commands/buildcmd/summary_test.go:31

## Unknowns

- None reported.

## Caveats

- single_provider_only: claude schema_error; rendering codex findings without dedupe
