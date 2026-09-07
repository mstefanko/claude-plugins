# Bakeoff Report: bakeoff-live-agent-eval.r001.multilens.operator-docs

## Glossary

- `F-NNN`: report finding; `R-NNN`: judge rationale.
- Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved.

## Outcome

Mode: `gather`
Run mode: `pairwise`
Decision: `structured_union`
Facet: `code-review`
Facet Focus: Find actionable defects in operator-facing docs changed in the diff: inaccuracies, omissions, or drift from the code behavior in the same change.
Result: `structured_union`
Next: `bakeoff show bakeoff-live-agent-eval.r001.multilens.operator-docs`

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
| `claude` | `ok` | 423.742s | 16.5 KB | 0 B | codebase -> codebase (enforced) | stderr: `providers/claude/stderr.txt` |
| `codex` | `ok` | 251.802s | 9.6 KB | 58.6 KB (trunc, +538.3 KB) | codebase -> codebase (enforced) | stderr kind: diagnostic; stderr: `providers/codex/stderr.txt` |

## Findings

Provider-set headings name the worker set that surfaced each claim. `single-source` means one worker surfaced it; `multi-source` means both workers surfaced materially similar claims.

Corroboration describes worker overlap within the shared `code-review` facet; it is not proof of correctness.

### claude
- **F-001** docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md contains two sections both labelled '## P2' ('Stale pairwise wording leaks into single-provider reports' and '`verify` does not assert single-provider semantics'). The duplicate heading breaks the plan's priority/sequencing structure; an operator executing by P-level cannot order or distinguish the two items. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (two consecutive '## P2' headings in diff)
- **F-002** plans/single-provider-hardening-plan.md P3 instructs the operator to 'Locate where the Glossary string and the F/R/D legend are emitted in summary.go' and lists summary.go as the file to grep for nonwinner/additions-from-loser/R-NNN/Glossary, but the glossary is defined and emitted in internal/report/report.go:reportGlossary, not summary.go. Following the instruction as written finds nothing and blocks the operator. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: plans/single-provider-hardening-plan.md (P3: 'Locate ... in summary.go'), internal/report/report.go diff (reportGlossary is in report.go; the nonwinner line is gated here)
- **F-003** docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md P2(wording) cites 'report.go:54 — Render unconditionally appends reportGlossary()' as evidence, but after the diff that call reads `lines = append(lines, reportGlossary(decision, false)...)` — a conditional call. The cited behavior no longer exists, so an operator verifying the evidence would hit a false negative. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (P2 stale-wording evidence: 'report.go:54 — Render unconditionally appends reportGlossary()'), internal/report/report.go diff (line ~54: reportGlossary(decision, false) — now conditional)
- **F-004** docs/work-orders.md adds the instruction 'unless you run `bakeoff triage` explicitly' for plan-review findings, but no `bakeoff triage` subcommand section appears in the docs/cli-reference.md diff and no triage command is introduced in any changed source file. If no such top-level CLI subcommand exists, the guidance directs operators to a nonexistent recovery path. (severity `medium`, model confidence `medium`, corroboration `single-source`, sources `claude`)
  Evidence: docs/work-orders.md (new plan-review text: '... unless you run `bakeoff triage` explicitly.'), docs/cli-reference.md diff (no `bakeoff triage` section added or referenced)

### claude+codex
- **F-005** docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md still names `summary.json` as a single-provider contract surface and frames the summary.json question as the sole ship-blocking decision (Options A/B unresolved), but the same diff's docs/work-orders.md already replaces it with 'command JSON summaries' (Option B) and the research path only prints the JSON summary to stdout under --json. An operator picking up the P1 item would think it is unresolved when the docs already chose. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (P1: 'This is the only ship-blocker that needs a human decision before coding.'), docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:54, docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:76, docs/work-orders.md diff (removes `summary.json`, adds 'command JSON summaries'), docs/work-orders.md:131, internal/commands/researchcmd/run.go:452
- **F-006** The artifact-contract hardening plan's P2 'stale pairwise wording' section is presented as an open investigation/fix, but report.go:reportGlossary now accepts decision+escalation and gates the kept-from-nonwinner/additions-from-loser line out when run_mode == single_provider. The plan describes already-shipped behavior. (severity `low`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (P2 stale-wording section, 'Fix: Gate the kept-from-nonwinner glossary bullet'), docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:82, docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:96, internal/report/report.go diff (reportGlossary signature change; `if jsonutil.StringValue(decision["run_mode"]) != workorder.RunModeSingleProvider` gate), internal/report/report.go:54, internal/report/report.go:1115, internal/report/report.go:1126
- **F-007** The artifact-contract hardening plan's second P2 section says `verify` does not assert single-provider semantics, but verify.go now implements validateSingleProviderDecision() reading decision.json and asserting null canonical_winner, single_provider set, judge flags false, and decision_kind in the single-provider set. The plan describes work already done. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md (second P2: 'Fix: When run_mode == single_provider, add semantic assertions to verify'), docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:104, docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:112, internal/verify/verify.go diff (validateSingleProviderDecision ~lines 350-378), internal/verify/verify.go:100, internal/verify/verify.go:353, internal/verify/verify.go:359, internal/verify/verify.go:362, internal/verify/verify.go:368
- **F-008** docs/single-provider-telemetry-hardening-plan-2026-06-08.md Finding 1 presents telemetry.judge.selection_basis: null as an open medium bug (DoD: re-run yields non-null), but decision.go now sets out["selection_basis"] = tiebreak and manifest.go adds a firstNonEmpty(selection_basis, spine_tiebreak) fallback for the telemetry field. Already done. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/single-provider-telemetry-hardening-plan-2026-06-08.md (Finding 1, severity medium, 'Required change: Populate telemetry.judge.selection_basis'), docs/single-provider-telemetry-hardening-plan-2026-06-08.md:58, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:74, internal/decision/decision.go:229, internal/decision/decision.go diff (line ~230: out["selection_basis"] = tiebreak), internal/manifest/manifest.go diff (telemetrySummary firstNonEmpty fallback), internal/manifest/manifest.go:479
- **F-009** docs/single-provider-telemetry-hardening-plan-2026-06-08.md Finding 4 presents enforcement_level: 'partial' with null reason as an open bug, but scope.go now sets enforcementLevel = 'enforced' when len(mechanisms) > 0 && len(fallbackReasons) == 0 — the exact case the plan says is mislabeled. Already corrected. (severity `low`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/single-provider-telemetry-hardening-plan-2026-06-08.md (Finding 4, 'Required change: relabel ... best_effort fully applied'), docs/single-provider-telemetry-hardening-plan-2026-06-08.md:157, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:172, internal/scope/scope.go diff (`if requestedScope == "mixed" || (len(mechanisms) > 0 && len(fallbackReasons) == 0)` yields 'enforced'), internal/scope/scope.go:109, internal/scope/scope.go:110, internal/scope/scope.go:111
- **F-010** docs/plan-review-facet-hardening-2026-06-08.md Item 4 presents the diagnostic-stderr truncation alarm as an open fix to confirm, but manifest.go now adds diagnosticStderrOnly() and gates output_truncation_count with `&& !diagnosticStderrOnly(obj)` so successful diagnostic stderr no longer increments the alarm. Already resolved. (severity `low`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: docs/plan-review-facet-hardening-2026-06-08.md (Item 4: 'Do not increment the truncation/overrun alarm for stderr already classified diagnostic'), docs/plan-review-facet-hardening-2026-06-08.md:166, docs/plan-review-facet-hardening-2026-06-08.md:193, internal/manifest/manifest.go diff (diagnosticStderrOnly; outputTruncationCount gated), internal/manifest/manifest.go:661, internal/manifest/manifest.go:673, internal/manifest/manifest.go:680, docs/cli-reference.md:561
- **F-011** plans/single-provider-hardening-plan.md P1 presents the orphan run-dir problem (only work-order.json, no decision/manifest forces --force) as open with three options, but researchcmd/run.go now adds researchRunDirIsIncomplete() and reclaims an incomplete dir without --force. The plan's cited evidence lines describe pre-fix behavior that no longer matches the source. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: plans/single-provider-hardening-plan.md (P1, 'Options to harden (pick one)'), plans/single-provider-hardening-plan.md:31, plans/single-provider-hardening-plan.md:43, plans/single-provider-hardening-plan.md:55, internal/commands/researchcmd/run.go diff (researchRunDirIsIncomplete; conditional reclaim ~line 63), internal/commands/researchcmd/run.go:61, internal/commands/researchcmd/run.go:63, internal/commands/researchcmd/run.go:229, internal/commands/researchcmd/run.go:239
- **F-012** plans/experiment-metadata-hardening.md Finding #1 (verify lacks experiment identity) and the Status line 'no code written yet' are stale: verify.go now exposes a nested experiment object (Result.Experiment / ExperimentMap) built from manifest experiment fields, and cli-reference.md documents the experiment object. The plan presents implemented work as an open gap. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: plans/experiment-metadata-hardening.md (Status: 'no code written yet'; Definition of done, finding #1), plans/experiment-metadata-hardening.md:67, plans/experiment-metadata-hardening.md:75, plans/experiment-metadata-hardening.md:131, internal/verify/verify.go diff (Result.Experiment field and ExperimentMap method), internal/verify/verify.go:28, internal/verify/verify.go:176, internal/verify/verify.go:207, docs/cli-reference.md:481
- **F-013** plans/experiment-metadata-hardening.md Finding #2 says manifest experiment data is sourced from meta.json (not work-order.json) and asks for a fallback, but manifest.go now adds addExperimentManifestFields with a fallback to the archived work order when meta has no experiment object. The plan presents implemented work as open. (severity `medium`, model confidence `high`, corroboration `multi-source`, sources `claude+codex`)
  Evidence: plans/experiment-metadata-hardening.md (Definition of done, finding #2), plans/experiment-metadata-hardening.md:81, plans/experiment-metadata-hardening.md:91, internal/manifest/manifest.go diff (addExperimentManifestFields fallback to workOrder), internal/manifest/manifest.go:385, internal/manifest/manifest.go:386, internal/manifest/manifest.go:388

### codex
- **F-014** Both docs/plan-review-facet-hardening-2026-06-08.md and docs/single-provider-telemetry-hardening-plan-2026-06-08.md still present slash-delimited prose 'path' warnings as open validator defects, but repocontext path classification now explicitly treats multi-part lowercase slash-delimited tokens without dots and without common path roots as prose. The plans describe already-resolved behavior. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: docs/plan-review-facet-hardening-2026-06-08.md:45, docs/plan-review-facet-hardening-2026-06-08.md:81, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:88, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:111, internal/repocontext/repocontext.go:302, internal/repocontext/repocontext.go:310, internal/repocontext/repocontext.go:315
- **F-015** docs/single-provider-telemetry-hardening-plan-2026-06-08.md says the provider status table lacks a stderr truncation indicator, but report rendering now passes the stderr truncation flag into byteCell, which appends '(trunc, +...)' when observed bytes exceed captured bytes. The plan describes a missing feature that already exists. (severity `low`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: docs/single-provider-telemetry-hardening-plan-2026-06-08.md:123, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:136, internal/report/report.go:553, internal/report/report.go:554, internal/report/report.go:608, internal/report/report.go:615
- **F-016** docs/cli-reference.md says the single-provider build JSON summary leaves both `winner` and `canonical_winner` null, but buildcmd/summary.go only emits a `winner` key (populated from decision["canonical_winner"]) and does not emit a `canonical_winner` key for summary consumers. The documented field set is inaccurate. (severity `low`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: docs/cli-reference.md:298, docs/cli-reference.md:300, internal/commands/buildcmd/summary.go:35, internal/commands/buildcmd/summary.go:47
- **F-017** docs/plan-review-facet-hardening-2026-06-08.md asks operators to decide whether plan-review should auto-triage or be documented as untriaged-by-design, but docs/work-orders.md already states plan-review runs do not start automatic code-review triage and should be treated as raw unless explicitly triaged. The open decision in the plan is already resolved in the shipped docs. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: docs/plan-review-facet-hardening-2026-06-08.md:103, docs/plan-review-facet-hardening-2026-06-08.md:113, docs/plan-review-facet-hardening-2026-06-08.md:118, docs/work-orders.md:269, docs/work-orders.md:270, internal/triage/state.go:239, internal/triage/state.go:240

## Conflicts

- **F-018** A and B directly disagree on whether the changed cli-reference.md documents the manifest-vs-telemetry schema-version distinction: A says the documentation gap remains absent; B says cli-reference.md now documents telemetry schema version 2.
  Evidence: docs/single-provider-telemetry-hardening-plan-2026-06-08.md ('Not a bug' section), docs/single-provider-telemetry-hardening-plan-2026-06-08.md:183, docs/single-provider-telemetry-hardening-plan-2026-06-08.md:187, docs/cli-reference.md diff (A: no schema versioning note added; B cites cli-reference.md:535, cli-reference.md:536 as documenting telemetry schema version 2), docs/work-orders.md diff (A: no schema versioning note added), internal/manifest/manifest.go:457

## Unknowns

- **F-019** Whether `bakeoff triage` exists as a first-class CLI subcommand in the pre-diff cli-reference.md baseline (not visible in the diff); if it exists, the `bakeoff triage` broken-reference claim is moot.
- **F-020** Whether `examples/repetition-loop.sh` exists at that path; both work-orders.md and cli-reference.md reference it but the file is not in the diff.
- **F-021** Whether docs/single-provider-run-mode-option-4-implementation-plan-2026-06-08.md (referenced as 'F-008' in the telemetry hardening plan 'Not a bug' section) exists and is up-to-date with shipped behavior; file not in diff.
- **F-022** [A recommended next check] verify.go:ExperimentMap() returns empty-string (via stringPtrValue), not JSON null, for nil TaskID/ConditionID/RunKind; cli-reference.md:479-482 documents the experiment fields but not the empty-string-vs-null distinction for required fields — operators relying on null-checks could be surprised.
- **F-023** [A recommended next check] plans/experiment-metadata-hardening.md Finding 3 (rerun not attempt-aware) says 'decide and act', but work-orders.md was updated to document the verbatim-replay behavior; the plan's Definition of done does not mark this item closed, so an operator may duplicate the documentation fix.

## Out-of-Facet Claims

These claims are observability-only and are excluded from triage source selection.

- researchcmd/run.go post-diff has two EnsureChildPath calls (one added ~line 98 inside the replaceRunDir block, one at the original location); whether the pre-existing call is now dead code or a redundant double-check needs review. (sources `A`, reason `Source-code correctness concern that worker A explicitly flagged as belonging to a separate code-review lens, not a docs defect; out of the operator-docs facet.`)
  Evidence: internal/commands/researchcmd/run.go diff (~line 98 EnsureChildPath inside replaceRunDir block; original-location call)
