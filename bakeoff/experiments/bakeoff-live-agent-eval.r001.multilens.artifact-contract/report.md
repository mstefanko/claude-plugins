# Bakeoff Report: bakeoff-live-agent-eval.r001.multilens.artifact-contract

## Glossary

- `F-NNN`: report finding; `R-NNN`: judge rationale.
- Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved.

## Outcome

Mode: `gather`
Run mode: `pairwise`
Decision: `structured_union`
Facet: `code-review`
Facet Focus: Find actionable defects in the run artifact contract introduced or exposed by the diff: manifest, decision, report, verify, scope, and workorder shape and field consistency.
Result: `structured_union`
Next: `bakeoff show bakeoff-live-agent-eval.r001.multilens.artifact-contract`

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
| `claude` | `ok` | 527.578s | 12.9 KB | 0 B | codebase -> codebase (enforced) | stderr: `providers/claude/stderr.txt` |
| `codex` | `ok` | 267.537s | 6.5 KB | 58.6 KB (trunc, +321.0 KB) | codebase -> codebase (enforced) | stderr kind: diagnostic; stderr: `providers/codex/stderr.txt` |

## Findings

Provider-set headings name the worker set that surfaced each claim. `single-source` means one worker surfaced it; `multi-source` means both workers surfaced materially similar claims.

Corroboration describes worker overlap within the shared `code-review` facet; it is not proof of correctness.

### claude
- **F-001** verify.ExperimentMap uses stringPtrValue for required string fields (task_id, condition_id, run_kind), which returns "" for a nil pointer, so a manifest with null/absent task_id/condition_id/run_kind emits "task_id": "" in verify JSON instead of null. This is a representation inconsistency with workorder.ExperimentMap and manifest.addExperimentManifestFields, which use nilIfEmpty to emit explicit null; a consumer comparing verify JSON against the manifest sees mismatched representations of the same absent field. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/verify/verify.go:226-233 — ExperimentMap sets id/task_id/condition_id/run_kind via stringPtrValue(m.TaskID) etc., bakeoff/internal/verify/verify.go:247-253 — stringPtrValue returns "" for nil pointer, bakeoff/internal/workorder/workorder.go:399 — ExperimentMap emits fields via direct assignment; compare nilIfEmpty usage in manifest
- **F-002** scope.go changes enforcementLevel from "partial" to "enforced" when len(mechanisms) > 0 && len(fallbackReasons) == 0, covering codex codebase scope (sandbox=read-only + disable=web_search) and any scope where all requested mechanisms applied without fallback. Existing meta.json/manifest consumers that branch on enforcement_level == "partial" to detect scope limitations would now observe "enforced" and behave differently; backward compatibility with prior artifacts that recorded "partial" under the same conditions is not verified. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/scope/scope.go:110 — if requestedScope == "mixed" || (len(mechanisms) > 0 && len(fallbackReasons) == 0) { enforcementLevel = "enforced" }, bakeoff/docs/single-provider-telemetry-hardening-plan-2026-06-08.md:149-155 — live run shows partial + null reason for fully-applied codex controls (old value), bakeoff/internal/scope/scope_test.go:52 — asserts enforcement_level == "enforced" for codex codebase controls
- **F-003** slashDelimitedProse in repocontext.go now allows 3+ part slash tokens through to the switch (old: len(parts) != 2 returned false; new: len(parts) < 2 returns false). The switch tests only parts[0] against a fixed list of directory roots, so any 3+ part lowercase path whose first component is not in that list (e.g. examples/mylib/foo) is classified as prose and silently excluded from path-existence validation, suppressing the warning a genuinely missing reference would otherwise produce. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/repocontext/repocontext.go:307 — old: if len(parts) != 2 { return false }; new: if len(parts) < 2 { return false }, bakeoff/internal/repocontext/repocontext.go:316-322 — switch parts[0] covers only listed directory prefixes; any other root returns true (prose)
- **F-004** validateSingleProviderDecision in verify.go checks decision_kind, canonical_winner, single_provider, and the three judge_* booleans, but does not assert the selection_basis invariant (which for a valid single-provider run must be "none"). A corrupted/edited decision.json with selection_basis set to an unexpected value (e.g. "swap_agreement") passes semantic validation silently — a gap in the regression guard the verify change introduces. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/verify/verify.go:350-379 — validateSingleProviderDecision checks kind, canonical_winner, single_provider, judge_ran/attempted/completed; no selection_basis assertion, bakeoff/docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:31 — live reference shape: selection_basis: "none"
- **F-005** ResolveAnalyze in decision.go writes both out["selection_basis"] = tiebreak and out["spine_tiebreak"] = tiebreak. manifest.go reads firstNonEmpty(decision["selection_basis"], decision["spine_tiebreak"]), so spine_tiebreak is dead for telemetry on new runs. Every new analyze decision.json carries two fields with identical values but different names; external consumers reading decision.json directly face an ambiguous canonical field, and older runs carry only spine_tiebreak, so the two fields mean different things depending on run age. (severity `low`, model confidence `high`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/decision/decision.go:228-231 — out["spine_tiebreak"] = tiebreak immediately followed by out["selection_basis"] = tiebreak, bakeoff/internal/manifest/manifest.go:476 — firstNonEmpty(decision["selection_basis"], decision["spine_tiebreak"]) — selection_basis always wins on new runs
- **F-006** addExperimentManifestFields falls back to workOrder["experiment"] when meta["experiment"] is absent/empty. workOrder is JSON-unmarshaled into map[string]any, so numeric values (including repetition_index) arrive as float64, whereas the meta path likely writes a Go int. If the fallback passes float64 through without integer coercion, the manifest field type diverges between primary and fallback paths, with downstream impact on verify.go's strict RepetitionIndex *int unmarshal target. (severity `medium`, model confidence `low`, corroboration `single-source`, sources `claude`)
  Evidence: bakeoff/internal/manifest/manifest.go:384-395 — addExperimentManifestFields reads experiment from workOrder when meta absent; workOrder is map[string]any from JSON unmarshal, bakeoff/internal/verify/verify.go:206 — manifestDocument.RepetitionIndex *int json:"repetition_index" — strict int unmarshal target

### codex
- **F-007** A pairwise compare run can write a stable pick_winner decision with canonical_winner but no selection_basis: ResolveCompare sets decision_kind and canonical_winner then returns, while manifest telemetry projects only decision.selection_basis or spine_tiebreak, so manifest.telemetry.judge.selection_basis remains null for this winner path. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/decision/decision.go:165, internal/decision/decision.go:168, internal/decision/decision.go:169, internal/decision/decision.go:171, internal/manifest/manifest.go:479
- **F-008** research --json summaries do not expose selection_basis even though analyze decisions now write that field and build summaries already include it; a machine consumer gets the selection reason from build summaries but not research summaries — a field-consistency gap across the run JSON output surface. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/decision/decision.go:229, internal/decision/decision.go:230, internal/summary/summary.go:47, internal/summary/summary.go:67, internal/summary/summary.go:263, internal/summary/summary.go:269, internal/commands/buildcmd/summary.go:45, internal/commands/buildcmd/summary.go:47
- **F-009** The manifest experiment fallback uses work-order.json only when meta.experiment is absent or empty, so a partial meta.experiment shadows the complete archived work order; required experiment labels accepted by work-order validation can still be omitted from manifest.json. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/manifest/manifest.go:385, internal/manifest/manifest.go:388, internal/manifest/manifest.go:393, internal/manifest/manifest.go:407, internal/workorder/workorder.go:770, internal/workorder/workorder.go:799
- **F-010** runs verify --json can return an incomplete experiment object without failing verification: it validates manifest schema and run id, then ExperimentMap fills missing required fields with empty strings or null rather than recording problems, so verification fails open on an incomplete experiment block. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/verify/verify.go:85, internal/verify/verify.go:91, internal/verify/verify.go:176, internal/verify/verify.go:207, internal/verify/verify.go:221
- **F-011** output_truncation_count undercounts truncated stderr because it suppresses every successful provider status whose stderr_kind is diagnostic, while StderrKind classifies any non-empty stderr from a successful provider as diagnostic unless it is the special transport-noise case. (severity `medium`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/manifest/manifest.go:670, internal/manifest/manifest.go:674, internal/manifest/manifest.go:680, internal/manifest/manifest.go:681, internal/artifact/artifact.go:137, internal/artifact/artifact.go:143
- **F-012** Reports still print the kept-from-nonwinner/additions-from-loser glossary for pairwise no-winner decisions such as structured_union and consensus, because the glossary gates only on run_mode != single_provider rather than on whether the decision actually has a non-selected provider. (severity `low`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/report/report.go:1126, internal/report/report.go:1127, internal/decision/decision.go:122, internal/decision/decision.go:127, internal/decision/decision.go:157, internal/decision/decision.go:161
- **F-013** Single-provider verification does not validate the decision.json run_mode field: validateSingleProviderDecision checks only decision kind, winner, provider, and judge flags, so a missing or mistyped decision run_mode can pass even when the manifest says single_provider. (Distinct from the selection_basis gap in M-04 — same validator, different unchecked field.) (severity `low`, model confidence `high`, corroboration `single-source`, sources `codex`)
  Evidence: internal/decision/decision.go:43, internal/decision/decision.go:52, internal/verify/verify.go:353, internal/verify/verify.go:373

## Conflicts

- **F-014** Disagreement on whether single-provider decision.json actually persists run_mode: A claims it may be absent (which would make the glossary gate a no-op); B asserts the decision writer records run_mode. B's citation is the general writer while A's open question targets the SingleProviderResult path specifically, so the citations do not resolve it.
  Evidence: bakeoff/internal/report/report.go:1132 — if jsonutil.StringValue(decision["run_mode"]) != workorder.RunModeSingleProvider, bakeoff/docs/single-provider-artifact-contract-hardening-plan-2026-06-08.md:31 — live decision.json field inventory omits run_mode, bakeoff/internal/report/report_test.go:157 — test injects "run_mode": RunModeSingleProvider into the decision map, internal/decision/decision.go:43, internal/decision/decision.go:52

## Unknowns

- **F-015** Does SingleProviderResult (decision.go, body not in diff) write run_mode into single-provider decision.json? If absent, the report.go:1132 glossary gate must instead key on decision_kind or decision["single_provider"]. This is the crux of the A-R-001 / B-R-007 conflict.
- **F-016** Does researchcmd/run.go augment the decision map with run_mode from the work order before report.Render? If it does, the single-provider glossary fix is operative; if not, it is inoperative.
- **F-017** Does addExperimentManifestFields apply integer coercion to repetition_index before writing it to the manifest output map (float64 from the work-order JSON path vs int from the meta path)? Function body beyond the signature is not visible.
- **F-018** Does artifact.ProviderSucceeded accept only status=="ok" or also other passing statuses? This governs which successful providers diagnosticStderrOnly suppresses and bears on the output_truncation_count undercount (M-11).
