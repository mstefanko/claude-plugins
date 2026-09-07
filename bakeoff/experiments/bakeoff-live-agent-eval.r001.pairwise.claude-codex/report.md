# Bakeoff Report: runmode-review-1273dce

## Glossary

- `F-NNN`: report finding; `R-NNN`: judge rationale.
- Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved.

## Outcome

Mode: `gather`
Run mode: `pairwise`
Decision: `structured_union`
Facet: `code-review`
Facet Focus: Find actionable defects in the 386accc..HEAD diff: correctness, artifact-contract drift, stale pairwise/winner wording for single_provider, missing tests, and single_provider experiment metadata.
Result: `structured_union`
Next: `bakeoff show bakeoff-live-agent-eval.r001.pairwise.claude-codex`

## Selector Confidence

- Selector label: `union/dedupe`
- Evidence: gather merged and deduped provider findings without selecting a winner.
- Decision effect: no canonical winner; report claims are grouped by source overlap.

## Decision Audit

- Judge ran: `true`
- Judge completed: `true`
- pass1: A=`claude`, B=`codex`

## Provider Status

| Provider | Status | Wall | Stdout | Stderr | Scope | Notes |
|----------|--------|------|--------|--------|-------|-------|
| `claude` | `ok` | 467.132s | 16.4 KB | 0 B | codebase -> codebase (enforced) | stderr: `providers/claude/stderr.txt` |
| `codex` | `ok` | 407.441s | 7.7 KB | 58.6 KB (trunc, +518.9 KB) | codebase -> codebase (enforced) | stderr kind: diagnostic; stderr: `providers/codex/stderr.txt` |

## Findings

Provider-set headings name the worker set that surfaced each claim. `single-source` means one worker surfaced it; `multi-source` means both workers surfaced materially similar claims.

Corroboration describes worker overlap within the shared `code-review` facet; it is not proof of correctness.

### claude
- **F-001** reportGlossary gates the pairwise 'Kept-from-nonwinner' gloss on decision["run_mode"], but the single_provider decision.json shape does not appear to include run_mode (Render already receives reliable wo.RunMode, which reportGlossary ignores). The test TestRenderSingleProviderGlossaryOmitsPairwiseTerms artificially injects run_mode into the decision map, so it passes regardless of what decision.json actually contains — a misleading test. If SingleProviderResult omits run_mode from the decision map, the glossary fix silently fails and single-provider reports still print the pairwise-only gloss. NOTE: production reachability is unverified (whether SingleProviderResult writes run_mode is an open unknown), so demoted from high. (severity `medium`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/report/report.go:1123 (gates on jsonutil.StringValue(decision["run_mode"])), bakeoff/internal/report/report_test.go:152-170 (test injects run_mode into decision map), bakeoff/docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (baseline decision.json keys without run_mode), bakeoff/plans/single-provider-hardening-plan.md (decision.json shape lists canonical_winner, selection_basis:none, judge_ran/attempted/completed, single_provider — no run_mode)
- **F-002** When opts.Force=true and the run dir exists, EnsureChildPath(opts.Out, runDir) is called twice — once in the force branch and again in the if replaceRunDir block — a redundant double call that will misfire if EnsureChildPath later gains side effects or non-idempotent behavior. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/commands/researchcmd/run.go (force branch EnsureChildPath ~line 68; if replaceRunDir block EnsureChildPath ~line 101)
- **F-003** nilIfEmpty(firstNonEmpty(decision["selection_basis"], decision["spine_tiebreak"])) in telemetrySummary can surface a spine_tiebreak value as selection_basis for decision types where selection_basis is intentionally absent but spine_tiebreak is set, conflating two fields with distinct semantics (single_provider is fine since selection_basis is "none"; the risk is compare/tiebreak paths). (severity `medium`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/manifest/manifest.go:479 (nilIfEmpty(firstNonEmpty(...selection_basis, ...spine_tiebreak)))
- **F-004** TestRunResearchReclaimsIncompleteRunDirWithoutForce verifies only that manifest.json exists after recovery — not that decision.json has the correct single_provider shape, that provider artifacts are present, or that the report renders correctly. An implementation that reclaims an incomplete dir and produces a malformed manifest would still pass. (severity `medium`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/commands/researchcmd/run_test.go:117-168 (test body ends with fsutil.FileExists(manifest.json) check only)
- **F-005** docs/work-orders.md replaces 'summary.json' with 'command JSON summaries' without explicitly stating that summary.json is not written as a file artifact. The contract-hardening plan flagged this as a human product decision (write summary.json vs. document it as not-written); the implemented wording remains ambiguous, so a harness author cannot tell summary.json is absent. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/docs/work-orders.md:129-131 (diff: 'summary.json' -> 'command JSON summaries'), bakeoff/docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md P1 section (ship-blocker human decision)
- **F-006** ExperimentMap in verify.go uses stringPtrValue for required string-pointer fields (m.TaskID, m.ConditionID, m.RunKind), returning "" for nil pointers. A manifest with experiment_id set but task_id/condition_id/run_kind unexpectedly nil yields {"task_id":"", ...} rather than nil, making the experiment map misleadingly populated for malformed manifests. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/verify/verify.go:219-222 (ExperimentMap uses stringPtrValue for required pointer fields)
- **F-007** TestBuildResearchProjectsSingleProviderFields injects "run_mode": RunModeSingleProvider into the decision map passed to BuildResearch. If BuildResearch reads run_mode from the decision map (mirroring the report glossary issue) and real decision.json lacks run_mode, got.RunMode would be empty in production while the test still expects RunModeSingleProvider — a potentially misleading test. (severity `low`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/summary/summary_test.go:67-81 (test injects run_mode into decision map passed to BuildResearch)
- **F-008** researchRunDirIsIncomplete's allowed set omits meta.json (allows only work-order.json, source-work-order.json, review-context.md, review-context.json). A run that writes meta.json before crashing (but before decision.json/manifest.json) is treated as having an unknown file and is NOT auto-reclaimable without --force, limiting the feature to the earliest orphan scaffold and surprising users whose runs failed mid-flight. (severity `low`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/commands/researchcmd/run.go:233-247 (allowed set excludes meta.json)

### claude+codex
- **F-009** addExperimentManifestFields falls back to workOrder["experiment"] only when meta["experiment"] is absent or len==0. A non-empty but partial meta.experiment block (e.g. stale or partial crash write) makes the fallback condition false, so the authoritative archived work-order.json is never consulted and otherwise-validated experiment fields (e.g. repetition_index, slot_id, slot_attempt) are dropped from the manifest. (severity `medium`, model confidence `medium`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: bakeoff/internal/manifest/manifest.go:382-397 (fallback gated on !ok || len(experiment)==0), bakeoff/internal/manifest/manifest.go:385-388, bakeoff/internal/manifest/manifest.go:393, bakeoff/internal/manifest/manifest.go:405, bakeoff/internal/manifest/manifest.go:408, bakeoff/internal/workorder/workorder.go:770
- **F-010** The selection_basis fix is asymmetric: out["selection_basis"]=tiebreak was added only to ResolveAnalyze, while ResolveCompare sets the winner but never sets selection_basis or spine_tiebreak. Since manifest telemetry only projects those two fields into telemetry.judge.selection_basis, compare-mode pick-winner runs still emit a null telemetry selection basis. (B frames it as the compare null bug; A frames it as incomplete coverage of the original telemetry-hardening finding across ResolveCompare/gather paths.) (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: bakeoff/internal/decision/decision.go:230 (out["selection_basis"]=tiebreak added only to ResolveAnalyze), bakeoff/internal/decision/decision.go:163, bakeoff/internal/decision/decision.go:168, bakeoff/internal/decision/decision.go:169, bakeoff/internal/decision/decision.go:170, bakeoff/internal/manifest/manifest.go:479, bakeoff/docs/cli-reference.md:554, bakeoff/docs/single-provider-telemetry-hardening-plan-2026-06-08.md Finding 1 (selection_basis null in manifest.telemetry.judge)

### codex
- **F-011** A valid single-provider build whose baseline gate fails before providers launch is reported invalid by `runs verify`: the build path emits decision_kind baseline_failed / baseline_expectation_failed while preserving run_mode: single_provider, but verify accepts only single_provider_result and single_provider_failed for single-provider runs. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: bakeoff/internal/commands/buildcmd/run.go:161, bakeoff/internal/commands/buildcmd/run.go:164, bakeoff/internal/commands/buildcmd/decision.go:343, bakeoff/internal/verify/verify.go:101, bakeoff/internal/verify/verify.go:359
- **F-012** `runs verify` does not enforce the successful single-provider build handoff contract: if a single_provider_result build decision loses selected_patch_provider, the dynamic required-patch-artifact check returns no selected-patch requirements and the single-provider semantic check only requires a non-empty single_provider, so the missing handoff field is not caught. (severity `medium`, model confidence `medium`, corroboration `single-source`, sources `codex`)
  Evidence: bakeoff/internal/decision/decision.go:325, bakeoff/internal/decision/decision.go:328, bakeoff/internal/decision/decision.go:329, bakeoff/internal/verify/verify.go:340, bakeoff/internal/verify/verify.go:344, bakeoff/internal/verify/verify.go:345, bakeoff/internal/verify/verify.go:365
- **F-013** The new truncation-alarm suppression can hide real stderr loss: successful provider stderr is classified as diagnostic even when it contains a trailing ERROR, and output_truncation_count now ignores truncated diagnostic stderr for successful providers. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: bakeoff/internal/artifact/artifact.go:137, bakeoff/internal/artifact/artifact.go:143, bakeoff/internal/artifact/artifact_test.go:87, bakeoff/internal/artifact/artifact_test.go:92, bakeoff/internal/manifest/manifest.go:673, bakeoff/internal/manifest/manifest.go:680
- **F-014** Run-id collision safety regressed for incomplete research directories: an existing run dir containing only the allowlisted scaffold files is removed without checking that its archived work-order.json matches the work order being launched, so reusing a run id can silently overwrite a different incomplete run. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: bakeoff/internal/commands/researchcmd/run.go:61, bakeoff/internal/commands/researchcmd/run.go:63, bakeoff/internal/commands/researchcmd/run.go:100, bakeoff/internal/commands/researchcmd/run.go:104, bakeoff/internal/commands/researchcmd/run.go:229, bakeoff/internal/commands/researchcmd/run.go:239, bakeoff/internal/commands/researchcmd/run_test.go:136, bakeoff/internal/commands/researchcmd/run_test.go:157

## Conflicts

- No conflicts found.

## Unknowns

- **F-015** Whether SingleProviderResult / BuildResearch in internal/decision/decision.go and internal/summary/summary.go write run_mode into the decision-map output (vs. reading wo.RunMode); determines whether the report-glossary (merged claim 1) and summary projection (claim 'summary_test run_mode') findings are production bugs or only test-quality gaps. (A; B silent)
- **F-016** Full content of the if len(mechanisms)==0 block in internal/scope/scope.go — the diff shows only two changed lines, leaving the interaction with the new 'enforced' assignment for requestedScope=='mixed' && len(mechanisms)==0 unresolvable from the diff alone. (A; B silent)
- **F-017** Whether examples/repetition-loop.sh and examples/single-provider.work-order.json (cited in work orders but absent from the diff) are consistent with the updated summary.json wording in docs/work-orders.md. (A; B silent)
