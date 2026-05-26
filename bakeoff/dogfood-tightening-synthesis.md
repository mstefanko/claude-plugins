# Bakeoff Dogfood Tightening Synthesis

Date: 2026-05-25

This synthesis deduplicates and verifies the CLI/plugin issues reported in:

- `runs/dogfood-manifest-telemetry-lenses.bakeoff-tightening-report.md`
- `runs/2026-05-24-4f7d/dogfood-tightening.md`
- `dogfood-artifacts-telemetry-split.ux-and-cli-hardening.md`
- `dogfood-ls-manifest-perf-tightening.md`
- `dogfood-metric-lint.tightening-report.md`

The path in the prompt that included `bakeoff/dogfood-artifacts-telemetry-split...`
was interpreted relative to the repository parent; in this checkout the file is
`dogfood-artifacts-telemetry-split.ux-and-cli-hardening.md`.

## Executive Recommendation

Fix these before the next release:

1. Escalation auto-triage must ingest witness/dispute provider findings, not
   only report bullets shaped like source-run findings.
2. `manifest.highest_severity` must ignore non-actionable triage classifications.
3. Metric verifier guardrails need at least one hard validation error: a
   repo-relative metric verifier with empty `build.protected_paths` should not
   validate.
4. The `/bakeoff:run` skill's appendix reference is currently broken relative
   to the skill directory. Move or copy `references/run-appendix.md` under the
   skill, or update the references and packaging.
5. Repair the skill/schema drift that caused visible draft-validation retries:
   required `providers[].model`, `facet.focus` shape/cap, triage taxonomy, and
   build/draft flag references.

Fix soon, preferably in the same tightening pass:

- Codex stderr capture/classification, especially prompt echo and diagnostic
  cap saturation.
- Judge-family advisory duplication and inconsistent wording.
- Machine JSON schema expectations for `--json --quiet` and multi-lens summaries.
- Build tie/unresolved output wording and recovery guidance.
- Gemini format-retry handling and status surfacing.
- Prose path-warning false positives.

Do not blindly implement every suggested tweak. Several items are transcript
polish, reader bugs, or policy decisions rather than CLI defects. Those are
called out below.

## Verified Fix-Now Items

### 1. Escalation triage drops witness/dispute material

Status: confirmed. Priority: P0 for code-review escalation.

Evidence:

- `runs/2026-05-25-d6c4/providers/gemini/final.json` contains
  `missed_material[0].source_finding_id == "new-01"`.
- `runs/2026-05-25-d6c4/report.md` renders that missed material under
  `### Missed Material`.
- `runs/2026-05-25-d6c4/triage/final.json` has `items: []` and
  `source_finding_filter.included: 0`.
- `internal/commands/triagecmd/triage.go` builds `source_findings` from
  `triage.BuildFindingIndex(reportText)` and `triage.SelectTriageSourceFindings`.
- `internal/triage/state.go` only indexes `- **F-123** ...` bullets first, then
  legacy actionable sections. Witness `missed_material[]` and dispute structures
  are not first-class intake.

Recommendation:

- Add an escalation-aware triage intake stream for `missed_material[]`,
  `material_errors[]`, and focused dispute results.
- Tag entries with a clear source, such as `source: "escalation_provider"`.
- Keep the existing source-run finding filter, but record both intake streams in
  `triage/source_finding_filter.json` and `triage/final.json`.

Regression cautions:

- Do not mutate the source run's triage. Escalation triage should remain scoped
  to the escalation run.
- The specific Gemini `new-01` fallback-provider claim is refuted in
  `runs/dogfood-manifest-telemetry-lenses.actionable-findings-report.md`; the bug
  is the triage intake path, not that claim's truth.

Acceptance:

- A witness/dispute run with any `missed_material[]` or `material_errors[]`
  produces `triage/final.json.items.length > 0` unless the triage provider
  explicitly classifies every item as false/non-actionable.

### 2. `highestSeverity` ignores triage classification

Status: confirmed. Priority: P0 for manifest telemetry correctness.

Evidence:

- `internal/manifest/manifest.go` computes `summary["highest_severity"] =
  highestSeverity(items)`.
- `highestSeverity` currently iterates every triage item and records only the
  `severity`, regardless of `classification`.
- `internal/triage/state.go` defines the authoritative classifications:
  `real_issue`, `false_positive`, `plan_doc_drift`, `product_decision`,
  `needs_repro`, `already_fixed`, `evidence_gap`.

Recommendation:

- Compute highest severity from actionable classifications only. I recommend
  `real_issue` and `needs_repro` as the first policy, because those are the
  classes the multi-lens synthesis already treats as actionable.
- Document the policy in code and docs.

Acceptance:

- A triage result with `false_positive/high` and `real_issue/medium` reports
  `highest_severity: "medium"`.

### 3. Metric verifier validation is too soft

Status: confirmed. Priority: P0 if metric verifiers are release-supported;
otherwise P1 but still high leverage.

Evidence:

- `internal/commands/validatecmd/validate.go` only warns when a repo-relative
  metric verifier command is paired with empty `build.protected_paths`.
- The same file only warns when `noise_floor_percent` is set and
  `metric.min_runs <= 1`.
- `internal/workorder/workorder.go` requires positive `min_delta_percent`, but
  accepts `min_runs` unset or `1`.
- The dogfood metric-lint run correctly stopped before draft because
  `internal/manifest` has no `Benchmark*` functions, no fixture/testdata
  directory under that package, and no Makefile target.

Recommendation:

- Make empty `build.protected_paths` a validation error when a metric verifier
  uses a repo-relative command such as `./scripts/bench-json` or
  `scripts/bench-json`.
- Keep the `min_runs >= 2` rule as warning unless there is a product decision
  that metric verifiers always represent repeated measurements. Some commands
  may emit an aggregate metric from their own repeated harness.
- Add draft/validate stat checks for declared protected paths and repo-relative
  verifier `argv[0]`, but avoid rejecting normal PATH commands such as `go`.

Acceptance:

- A metric verifier with `argv[0] == "./scripts/bench-json"` and empty
  `build.protected_paths` fails `bakeoff validate`.
- A missing protected path reports the missing path before providers launch.

### 4. Skill appendix reference is broken

Status: confirmed. Priority: P0 for the plugin skill.

Evidence:

- `skills/bakeoff-run/SKILL.md` references `references/run-appendix.md`.
- Relative to the skill directory, `skills/bakeoff-run/references/run-appendix.md`
  does not exist.
- The file exists at repository root: `references/run-appendix.md`.
- Current skill-loading conventions resolve relative paths from the skill
  directory first, so the source layout matches the cached-skill missing-file
  report.

Recommendation:

- Move or copy `references/run-appendix.md` to
  `skills/bakeoff-run/references/run-appendix.md`, or update every reference to
  the actual packaged path and verify the plugin cache includes it.
- Add a packaging test that opens every skill-relative reference named in
  `SKILL.md`.

Acceptance:

- A fresh plugin install/cache contains the appendix at the path the skill names.

### 5. Manual draft schema guidance is stale

Status: confirmed. Priority: P1, but it caused visible retries.

Evidence:

- `skills/bakeoff-run/SKILL.md` tells manual drafts to use
  `providers[].backend` and `providers[].id`, but omits required
  `providers[].model`.
- `internal/workorder/workorder.go` requires provider `id`, `backend`, and
  `model` when scope is required.
- `internal/workorder/workorder.go` validates `facet.focus` as a string,
  non-empty, no backticks, no angle brackets, no `</facet>`, and at most 500
  characters. The skill does not list those constraints.
- `examples/review.work-order.json` has the code-review facet shape, but
  `examples/gather.work-order.json` does not.
- `internal/workorder/workorder.go` reports `facet.focus must be at most 500
  characters` without the actual length.

Recommendation:

- Update the skill drafting bullets to include `providers[].model`.
- Add `facet.focus` constraints and a short code-review facet reference.
- Change the validation error to include the actual length, for example
  `facet.focus must be at most 500 characters (got 519)`.
- Keep pre-preview validation as best-effort unless the CLI gets a true
  non-mutating stdin validator. Do not require writing a temp work order before
  approval just to validate.

Acceptance:

- A generated gather/code-review draft validates on the first post-approval
  pass for provider fields and facet shape.

### 6. Triage taxonomy in the skill is wrong

Status: confirmed. Priority: P1.

Evidence:

- `skills/bakeoff-run/SKILL.md` asks summaries to count
  `real_issue`, `needs_repro`, evidence gaps, false positives, deferred,
  documented, and ignored items.
- The authoritative classification values are in `internal/triage/state.go`.
- `document`, `defer`, and `ignore` are `recommended_action` values, not
  classifications.

Recommendation:

- Rewrite the skill to distinguish:
  - `classification`: `real_issue`, `false_positive`, `plan_doc_drift`,
    `product_decision`, `needs_repro`, `already_fixed`, `evidence_gap`.
  - `recommended_action`: `fix_now`, `document`, `defer`, `ignore`,
    `reproduce`.

Acceptance:

- Multi-lens summaries report classification counts using only real
  classification names.

## Verified Fix-Soon Items

### 7. Codex stderr capture still saturates caps

Status: confirmed, with a partial source fix already present.

Evidence:

- `runs/2026-05-24-4f7d/providers/codex-gpt-5_5/status.json`:
  `stderr_kind: "diagnostic"`, `stderr_bytes: 60000`,
  `stderr_observed_bytes: 175408`, `stderr_truncated: true`.
- `runs/dogfood-artifacts-telemetry-split.part-2/providers/codex/status.json`:
  `stderr_observed_bytes: 1264349`.
- The stderr artifact begins with Codex banner/config and then echoes the full
  prompt.
- `internal/artifact/artifact.go` now filters Codex transport echo only when
  `stderr_kind == "transport_noise"`. The affected dogfood artifacts are
  classified as `diagnostic`, so the current filter does not help them.
- Manifest provider summaries omit `stderr_kind`, so downstream users see a
  cap without knowing whether it is prompt echo, transport noise, or a real
  warning.

Recommendation:

- Classify/suppress known Codex banner and prompt/final-json echo before the
  stderr cap is applied, including truncated diagnostic-shaped streams.
- Include `stderr_kind`, `stderr_filtered`, and `stderr_filter_note` in
  manifest provider summaries and `--json` summaries.
- Emit a warning only when the remaining stderr contains non-benign diagnostic
  content.

Acceptance:

- Clean Codex runs no longer write 60 KB prompt-echo stderr artifacts.
- If stderr is capped, machine output identifies the provider, stream,
  observed bytes, retained bytes, and kind.

### 8. `--json --quiet` schema and skill expectations diverge

Status: confirmed. Priority: P1 for machine consumers and parallel summaries.

Evidence:

- `runs/.parallel/dogfood-manifest-telemetry-lenses/correctness/stdout` has
  top-level keys such as `artifacts`, `triage`, `run_dir`, and `decision_kind`.
- It does not have top-level `result_class`, `report_path`, `triage_state`, or
  `out_dir`.
- `internal/summary/summary.go` defines nested `ResearchSummary.Artifacts` and
  `ResearchSummary.Triage`.
- `internal/manifest/manifest.go` and `bakeoff ls --json` rows do hoist
  `report_path` and `triage_state`, but run summaries do not.

Recommendation:

- Prefer documenting and teaching the skill to read the current nested schema.
- If compatibility aliases are added, bump or clearly version the JSON schema:
  `report_path = artifacts.report`, `triage_state = triage.state`,
  `out_dir`, and a derived `result_class`.

Acceptance:

- The multi-lens summarizer succeeds by reading either the documented nested
  fields or explicitly added compatibility aliases.

### 9. Judge-family advisory is duplicated and not coherently audited

Status: confirmed, but split into copy and artifact concerns.

Evidence:

- `internal/commands/doctorcmd/doctor.go` and
  `internal/commands/validatecmd/validate.go` format different advisory text.
- The skill renders a third compact preview variant.
- `runs/2026-05-24-4f7d/manifest.json` records
  `telemetry.judge.family_relation: "same_as_some"`, but there is no explicit
  `judge_family_advisory` artifact or `advisories[]` record.

Recommendation:

- Extract shared advisory formatting for doctor/validate/preview.
- Suppress or shorten validate-time advisory output when the preview already
  showed the same advisory.
- Keep the advisory informational. Do not auto-switch judges.
- Be careful about artifact persistence: readiness of alternative judges comes
  from `doctor` and can become stale. It is safer to persist the derived
  relation already available at run time, plus docs explaining it, than to
  persist stale readiness as fact.

Acceptance:

- One workflow surfaces the family advisory once prominently, then only
  back-references it.

### 10. Gemini format retry is common and too quiet

Status: confirmed.

Evidence:

- Both `runs/2026-05-25-6b7a/providers/gemini/status.json` and
  `runs/2026-05-25-5e29/providers/gemini/status.json` show
  `status: "ok_after_format_retry"` with reason
  `stdout is missing a <final_json>...</final_json> block`.
- The initial Gemini stdout in at least one run is fenced JSON, not tagged
  final JSON.
- `internal/runner/runner.go` `ExtractFinalJSON` accepts only
  `<final_json>...</final_json>` blocks.
- The human report does not call out the retry; structured artifacts do.

Recommendation:

- Either strengthen Gemini prompts or accept a single fenced/bare top-level JSON
  object as a provider-specific fallback. The fallback should be conservative:
  only accept when there is exactly one object and it passes the same schema
  validator.
- Surface `ok_after_format_retry` as a short note in human report/summary and
  as a `warnings[]` entry in machine JSON.

Acceptance:

- Gemini fenced JSON that is otherwise schema-valid does not require a second
  provider invocation.

### 11. Prose path warnings need less noise

Status: confirmed.

Evidence:

- `internal/repocontext/repocontext.go` extracts any token with a slash.
- `plausibleMissingPath` returns true before `slashDelimitedProse` when
  suggestions exist.
- This allows prose like `manifest/decision outputs` to warn if a basename
  suggestion is available.
- `bakeoff/...` paths also warn when the context root is already the `bakeoff`
  directory.

Recommendation:

- First refine false positives: prefer only backticked/markdown path spans, a
  known root, extension, leading `./`, absolute path, or `:LINE`.
- For context-root basename prefixes, do not silently rewrite all paths. Emit a
  clearer warning such as `paths are resolved relative to <root>; did you mean
  README.md?` and optionally provide a single stripped suggestion.

Regression cautions:

- Auto-stripping a leading segment can hide genuine nested-directory mistakes in
  monorepos. Treat it as a suggestion, not transparent resolution, unless tests
  cover nested-root cases.

### 12. Build tie/unresolved output needs one stable vocabulary

Status: confirmed. Priority: P1 for build-mode usability.

Evidence:

- `runs/dogfood-ls-manifest-perf/decision.json` has
  `decision_kind: "tie"`, `canonical_winner: null`,
  `stalled_at: "selection"`.
- `judge_passes.pass1.canonical_winner` is null and
  `judge_passes.pass2.canonical_winner` is `codex`.
- `internal/commands/buildcmd/run.go` human tail prints `result`,
  `selected patch`, and `next`, but not exit code or `stalled_at`.
- `internal/commands/escalatecmd/escalate.go` explicitly rejects build source
  runs: `build source runs cannot be escalated`.
- The skill says do not offer build escalation, which matches CLI behavior.

Recommendation:

- Keep build escalation forbidden for now. Do not introduce advisory build
  escalation as a quick fix.
- Add a human tail line such as `status: unresolved at selection (exit 3)`.
- When swapped judge passes disagree, print a compact line before the result:
  `swapped judge disagreed (pass1=tie, pass2=codex) -> unresolved`.
- In `/bakeoff:run` summaries, lead with `Decision: unresolved`, then put
  `Decision kind: tie` on a detail line.
- Document allowed build tie recovery: inspect artifacts, draft an analyze run
  comparing patches, or draft a new build with a stronger gate.

Acceptance:

- Users can understand exit `3` and the stalled stage without opening
  `decision.json`.

### 13. Escalation/decision schema should be more explicit

Status: confirmed. Priority: P2 schema hardening.

Evidence:

- Dispute runs use `decision_kind: "escalation_advisory_supported"` and
  `canonical_winner: null`, but have no explicit `advisory: true`.
- Escalation independent/dispute decisions omit `judge_passes` and `order_maps`
  keys that analyze/compare decisions have.
- `decision.caveats` contains both human sentences
  (`spine chosen by atomic_count after swap disagreement`) and enum-like tokens
  (`synthesis_judge_not_position_swapped`).
- Manifest telemetry currently reports only
  `output_truncation_count`, not structured truncation records.

Recommendation:

- Add explicit advisory/binding fields for advisory escalation modes.
- For independent escalation with a synthesis judge, emit a single-pass
  `judge_passes`/`order_maps` shape; for no-judge advisory modes, emit null or
  document absence.
- Normalize `caveats` as machine tokens plus separate human messages, or
  document that it is a display field.
- Add structured output truncations:
  `{provider, stream, observed_bytes, kept_bytes, kind}`.

Acceptance:

- A consumer can tell advisory status, judge-pass availability, and truncation
  details without parsing decision-kind strings or human report text.

### 14. Runtime visibility for quiet/buffered workers

Status: confirmed enough to fix as polish.

Evidence:

- `internal/runner/runner.go` records quiet ticks but does not add explanatory
  copy after long quiet windows.
- Dogfood build output had long quiet windows for Claude SDK-style buffered
  output.
- Backgrounded `/bakeoff:run` workflows can lose live CLI heartbeats.

Recommendation:

- After several consecutive quiet ticks, emit one informational line per
  worker: buffered providers can be silent until completion; Ctrl-C aborts.
- In the skill, say long-budget commands may be backgrounded by the host and
  lose live heartbeats. If the assistant backgrounds a run, emit a mid-run
  lifecycle tick from captured status/log files when possible.

Acceptance:

- A 10-minute silent provider is framed as buffered/slow rather than stuck.

## Skill And Copy Bundle

These are mostly small text/template fixes. They should be batched so the
skill's behavior stays internally consistent.

Confirmed:

- Acceptance tokens differ across previews. Standardize one set for
  single-work-order and escalation previews.
- Separate approval tokens from non-approval tokens in preview footers:
  `Approve: yes | approve | run it`; `Other: show, cancel`.
- Explicitly list cheap advisory accept tokens; avoid "single yes" if
  `run it` also works elsewhere.
- Add `edit` and `swap judge to <backend>` when a preview invites those actions.
- When a supplied `--run-id` is known, preview `Run id: <id>`, not
  `Run id (on launch)`.
- Surface lens label normalization, for example `docs/tests` to `docs-tests`.
- Use the appendix multi-lens headings exactly, or loosen the appendix. Today
  `runs/dogfood-manifest-telemetry-lenses.multi-lens-summary.md` diverges from
  the appendix and omits `## Next Commands`.
- Multi-lens summaries should not use single-verdict `Decision:` framing.
- Keep the "one artifact-aware continuation recommendation" rule in split and
  escalation summaries.
- Confirm mode switches in escalation previews, for example
  `Switched to dispute mode. New preview below.`
- Do not editorialize inline with verbatim validation warnings; put assistant
  gloss on a separate line.
- `commands/run.md` should mention the approval gate in its description.
- `README.md` should list approval and non-approval reply tokens.
- Examples use JSON comments. This is acceptable if the CLI intentionally
  supports JSONC, but add a note so users do not paste them into strict JSON
  tools and get surprised.
- `CLAUDE.md` and the skill should document what to do when context-mode MCP
  tools are unavailable. The current `CLAUDE.md` mandates `ctx_batch_execute`
  but does not name an allowed one-shot Bash fallback.

Not recommended as written:

- Making pre-preview validation mandatory without a non-mutating validator.
  The no-write-before-approval invariant matters. Add a stdin/temp validation
  facility first, or keep validation post-approval and repair the schema
  guidance that caused retries.
- Running `bakeoff doctor` before a forced discovery stop. If repo facts already
  prove a metric draft cannot be grounded, doctor adds latency and unrelated
  noise. The skill can say this is optional, not mandatory.

## Lower-Priority CLI Polish

### Draft-build flags and gate shorthand

Status: confirmed.

- `draft-build` has `--scope`, not `--edit-scope`.
- There is no hidden alias or custom flag suggestion.
- `--gate` requires `<id>=<command>`.

Recommendation:

- Add hidden `--edit-scope` and `--edit-boundary` aliases to `--scope`, or at
  least a friendly flag-error suggestion.
- Do not auto-name bare `--gate "go test ./..."` by default. A better low-risk
  fix is an error that says `try --gate "tests=go test ./..."`.
- Document canonical `draft-build` flags in the skill.

### Gitlink/submodule warning

Status: confirmed, but not a defect at reported priority.

Evidence:

- `internal/commands/buildcmd/helpers.go` emits a source warning when the
  checkout contains gitlinks/submodules, even if no provider changes one.

Recommendation:

- Keep an upfront warning/note because it explains a build constraint before
  patches are judged.
- Consider labeling it `note` rather than `warning` when there was no actual
  rejected gitlink change.

### Parallel fanout liveness

Status: confirmed in generated helper/appendix, but not a product blocker.

Evidence:

- `.bakeoff-parallel-launch.sh` and the appendix skeleton write pid files but do
  not implement lockfiles, stale pid cleanup, or resume checks.

Recommendation:

- Do not build a full supervisor unless parallel fanout is becoming a supported
  CLI command.
- For now, add minimal cleanup guidance to the appendix: remove pid files on
  clean exit and mark stale/missing child JSON as partial.

## Items To Document, Not Fix In CLI

### Escalation back-pointer "missing source_run" was a reader bug

Status: confirmed as not a CLI defect.

Evidence:

- `runs/2026-05-25-6b7a/manifest.json` has `source_run_id`,
  `source_type`, `escalation_mode`, `added_provider`, `source_providers`, and
  nested `escalation`.
- The source report's missing `source_run=None / summary=None` observation came
  from reading non-existent top-level `source_run` and `summary` keys.

Recommendation:

- Document the escalation manifest projection in `docs/cli-reference.md`.
- Optionally add an inspect view, but do not change the run artifacts solely for
  this reader bug.

### `judge.status: null` is not current

Status: not reproduced in current source/artifacts.

Evidence:

- Current manifests inspected have `judge` with `backend`, `model`, and
  `effort`; no `status` key is emitted.
- `internal/manifest/manifest.go` `judgeSummary` only copies backend/model/effort.
- `telemetry.judge.ran` and `telemetry.judge.completed` carry state.

Recommendation:

- Do not add `judge.status` just because older artifact readers expected it.
  If a status is needed, design it as part of a schema bump.

### `capture.json` vs `final.json` overlap was not reproduced

Status: refuted for current `dogfood-ls-manifest-perf` artifacts.

Evidence:

- `providers/<id>/final.json` contains provider-authored final build JSON.
- `providers/<id>/build/capture.json` contains patch capture metadata such as
  `patch_digest`, `changed_files_path`, and `gitlink_change_rejected`.
- The keys do not overlap in the way reported.

Recommendation:

- No merge needed. A docs note explaining provider `final.json` vs build
  `capture.json` is enough if users are confused.

### Gemini witness `new-01` fallback-provider claim was refuted

Status: refuted, but keep the triage intake fix.

Evidence:

- `runs/dogfood-manifest-telemetry-lenses.actionable-findings-report.md`
  verifies that `fallback` is derived from `workOrder.providers`, so the removed
  fallback-only loop was redundant.

Recommendation:

- Do not implement a telemetry fallback-provider fix for `new-01`.
- Do implement escalation triage intake so future true witness findings are not
  hidden.

## Source Item Mapping

| Source item | Synthesis disposition |
| --- | --- |
| manifest-lenses P0-1 witness triage drops findings | Fix-now item 1 |
| manifest-lenses P0-2 JSON quiet missing top-level fields | Fix-soon item 8 |
| manifest-lenses P0-3 `highestSeverity` classification | Fix-now item 2 |
| manifest-lenses P1-1 Codex stderr cap | Fix-soon item 7 |
| manifest-lenses P1-2 duplicate judge-family advisory | Fix-soon item 9 |
| manifest-lenses P1-3 `bakeoff/` path-prefix warning | Fix-soon item 11 |
| manifest-lenses P1-4 multi-lens headings | Skill/copy bundle |
| manifest-lenses P1-5 lens-name normalization | Skill/copy bundle |
| manifest-lenses P2-1 `ok_after_format_retry` silent | Fix-soon item 10 |
| manifest-lenses P2-2 fanout liveness | Lower-priority parallel polish |
| manifest-lenses P2-3 `judge.status: null` | Do not fix; not current |
| manifest-lenses P2-4 multi-lens `Decision:` framing | Skill/copy bundle |
| manifest-lenses P2-5 git probe invariant conflict | Skill/copy bundle; clarify fallback/probes |
| manifest-lenses P2-6 cheap advisory accept tokens | Skill/copy bundle |
| 2026-05-24 1.1 advisory audit trail | Fix-soon item 9, with caution |
| 2026-05-24 1.2 Codex prompt echo | Fix-soon item 7 |
| 2026-05-24 2.1 provider model omitted | Fix-now item 5 |
| 2026-05-24 2.2 facet focus shape/cap | Fix-now item 5 |
| 2026-05-24 2.3 gather code-review example | Fix-now item 5 |
| 2026-05-24 2.4 length error lacks got-N | Fix-now item 5 |
| 2026-05-24 2.5 pre-preview validation | Do not require until non-mutating validator exists |
| 2026-05-24 3.1 triage taxonomy | Fix-now item 6 |
| 2026-05-24 3.2 structured_union consensus wording | Skill/copy bundle |
| 2026-05-24 3.3 ad-hoc `Why this loop` | Skill/copy bundle |
| 2026-05-24 4.1 background silence | Fix-soon item 14 |
| 2026-05-24 4.2 edit/swap judge tokens | Skill/copy bundle |
| 2026-05-24 4.3 hidden defaults | Skill/copy bundle, low priority |
| 2026-05-24 4.4 advisory printed twice | Fix-soon item 9 |
| 2026-05-24 4.5 command description | Skill/copy bundle |
| 2026-05-24 4.6 README approval tokens | Skill/copy bundle |
| 2026-05-24 examples JSON comments | Skill/copy bundle |
| 2026-05-24 heartbeat telemetry candidate | Fix-soon item 13 or 14 |
| artifacts split P0-1 Codex stderr disk bloat | Fix-soon item 7 |
| artifacts split P0-2 escalation back-pointers | Document; reader bug |
| artifacts split P1-3 Gemini format retry | Fix-soon item 10 |
| artifacts split P1-4 path-sniff false positive | Fix-soon item 11 |
| artifacts split P1-5 advisory emitted twice | Fix-soon item 9 |
| artifacts split P1-6 advisory status encoded in kind | Fix-soon item 13 |
| artifacts split P2-7 caveats shape | Fix-soon item 13 |
| artifacts split P2-8 escalation judge passes/order maps | Fix-soon item 13 |
| artifacts split P2-9 truncation count too coarse | Fix-soon item 13 |
| artifacts split skill A-J | Skill/copy bundle, except schema items above |
| ls manifest item 1 draft-build flag discoverability | Lower-priority CLI polish |
| ls manifest item 2 Codex banner noise | Fix-soon item 7 |
| ls manifest item 3 run-id preview wording | Skill/copy bundle |
| ls manifest item 4 advisory wording | Fix-soon item 9 |
| ls manifest items 5-7 build tie/swap output | Fix-soon item 12 |
| ls manifest item 8 gate shorthand | Lower-priority CLI polish |
| ls manifest items 9-11 summary/token/recommendation | Skill/copy bundle |
| ls manifest items 12/14 long quiet/buffered heartbeat | Fix-soon item 14 |
| ls manifest item 13 gitlink warning | Lower-priority CLI polish |
| ls manifest item 15 capture/final overlap | Do not fix; not reproduced |
| ls manifest item 16 missing run appendix | Fix-now item 4 |
| ls manifest item 17 draft-build flags in skill | Lower-priority CLI polish / skill bundle |
| metric-lint UX 1.1-1.3 repair menu wording | Skill/copy bundle |
| metric-lint 2.1 protected paths warning | Fix-now item 3 |
| metric-lint 2.2 min_runs/noise floor | Fix-now item 3 with policy caution |
| metric-lint 2.3 stat checks | Fix-now item 3 |
| metric-lint 2.4 metric hard-stops | Fix-now item 5 / skill bundle |
| metric-lint 2.5 doctor before discovery stop | Do not make mandatory |
| metric-lint 2.6 context-mode fallback | Skill/copy bundle |

## Suggested Commit Shape

1. CLI correctness/schema PR:
   - escalation triage intake;
   - `highestSeverity` filtering;
   - metric protected-path validation error;
   - optional structured truncation/advisory schema additions.
2. Provider/runtime PR:
   - Codex stderr filtering/classification;
   - Gemini JSON fallback or prompt fix;
   - long-quiet heartbeat copy.
3. Skill/docs PR:
   - appendix packaging;
   - schema bullets, triage taxonomy, preview tokens, verdict vocabulary;
   - run/README descriptions and examples note.
4. Build UX PR:
   - unresolved/tie tail status;
   - swapped-pass disagreement line;
   - build tie recovery guidance.

Run tests after each PR slice. The most targeted test packages are:

- `go test ./internal/manifest ./internal/commands/triagecmd ./internal/commands/escalatecmd`
- `go test ./internal/commands/validatecmd ./internal/workorder`
- `go test ./internal/artifact ./internal/runner`
- `go test ./internal/commands/buildcmd ./internal/commands/draftbuildcmd`
