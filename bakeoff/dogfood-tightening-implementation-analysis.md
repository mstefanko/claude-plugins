# Bakeoff Dogfood Tightening: Implementation Analysis

This is the implementation-oriented follow-up to
`dogfood-tightening-synthesis.md`. It deduplicates the five dogfood reports by
underlying issue, records what was verified in runs/code, and recommends what to
fix now, what to fix soon, and what to defer.

Source reports:

- `runs/dogfood-manifest-telemetry-lenses.bakeoff-tightening-report.md`
- `runs/2026-05-24-4f7d/dogfood-tightening.md`
- `dogfood-artifacts-telemetry-split.ux-and-cli-hardening.md`
- `dogfood-ls-manifest-perf-tightening.md`
- `dogfood-metric-lint.tightening-report.md`

## Executive Call

Fix first:

1. Escalation auto-triage must ingest escalation-provider findings.
2. `manifest.highest_severity` must ignore non-actionable triage classes.
3. Metric work orders must fail validation when a repo-local verifier has no
   `protected_paths`.
4. The `/bakeoff:run` appendix reference must be shipped where the skill points.
5. Manual draft guidance must include provider `model`, `facet.focus` shape, and
   real triage taxonomy.

Easy wins:

- Copy `references/run-appendix.md` into the skill-local `references/` path or
  adjust packaging so the path exists.
- Add `providers[].model`, `facet.focus` limits, and `draft-build` flags to
  `skills/bakeoff-run/SKILL.md`.
- Include actual length in `facet.focus` length errors.
- Fix skill wording for triage taxonomy, `structured_union` verdicts, approval
  tokens, preview defaults, and run-command description.
- Add one build tail line for unresolved/tie exit state.
- Add one quiet-worker note when output is buffered or long-silent.

Defer or investigate:

- Full Codex stderr pre-cap filtering is valuable but touches shared runner
  capture behavior.
- Gemini untagged JSON fallback may hide malformed answers unless constrained
  tightly.
- Schema normalization for `caveats`, escalation `judge_passes`, and structured
  truncation telemetry should be a schema PR, not a drive-by hardening change.
- `capture.json`/`final.json` overlap, `judge.status:null`, and escalation
  back-pointer issues were either not reproduced as CLI defects or are mainly
  documentation/reader fixes.

## 1. Escalation Triage Drops Witness/Dispute Material

Status: verified. Recommendation: fix now. Risk: medium, but scoped and high
value.

Seen in run:

- `runs/2026-05-25-d6c4/providers/gemini/final.json` contains
  `missed_material[0].source_finding_id == "new-01"`.
- `runs/2026-05-25-d6c4/report.md` renders that entry under `Missed Material`.
- `runs/2026-05-25-d6c4/triage/final.json` has `items: []`.
- `runs/2026-05-25-d6c4/triage/source_finding_filter.json` says
  `included: 0`, so the run reads as clean even though the escalation provider
  found material.

Relevant code:

- `internal/commands/escalatecmd/escalate.go` auto-runs triage for code-review
  escalation.
- `internal/commands/triagecmd/triage.go` builds triage payloads from report
  source findings.
- `internal/triage/state.go` indexes markdown source findings matching the
  original `F-NNN`-style report shape; it does not treat escalation
  `missed_material[]` or `material_errors[]` as triage inputs.

Implementation:

- Add an escalation-specific intake path before triage prompt construction.
- Prefer reading structured escalation decision/final JSON over reparsing
  markdown.
- Convert `assessment.missed_material[]` and `assessment.material_errors[]` into
  triage source findings with `source: "escalation_provider"`.
- Preserve provider IDs when present, e.g. `new-01`; synthesize stable IDs only
  when absent, e.g. `ESC-MISSED-001`.
- Update `source_finding_filter.json` to report separate intake streams:
  source-run findings vs escalation-provider findings.

Tests:

- Add a fixture escalation decision/report with one `missed_material` entry.
- Assert the triage prompt payload includes that entry.
- Assert `triage/final.json` has `items > 0` and the stdout/json summary reports
  a non-zero triage count.

Do not:

- Mutate the source run's original findings.
- Pretend escalation provider findings are original lens findings; keep the
  provenance distinct.

## 2. `highestSeverity` Ignores Triage Classification

Status: verified. Recommendation: fix now. Risk: low.

Seen in reports:

- Multiple dogfood reports identify the same wire-contract bug: a high-severity
  false positive can still drive `manifest.highest_severity`.

Relevant code:

- `internal/manifest/manifest.go` computes `highest_severity` from all triage
  items.
- `internal/triage/state.go` defines classifications:
  `real_issue`, `false_positive`, `plan_doc_drift`, `product_decision`,
  `needs_repro`, `already_fixed`, `evidence_gap`.

Implementation:

- Change `highestSeverity(items)` to skip non-actionable classifications.
- Recommended actionable set: `real_issue` and `needs_repro`.
- Exclude `false_positive`, `already_fixed`, `plan_doc_drift`,
  `product_decision`, and `evidence_gap` from highest severity. `evidence_gap`
  can be important, but it is not a fix-now defect severity and should not make
  a run look worse than its actionable contents.

Tests:

- High false positive plus medium real issue returns medium.
- High needs-repro plus medium real issue returns high.
- Only false positives returns no highest severity.
- Existing empty/no-triage behavior remains unchanged.

## 3. Metric Verifier Validation Is Too Soft

Status: verified. Recommendation: fix the protected-path case now; defer stricter
stat/noise-floor policy. Risk: low to medium.

Seen in run:

- `dogfood-metric-lint` correctly stopped before drafting because no stable
  benchmark harness, fixture path, or Makefile target existed.
- The repo contains no `Benchmark*` functions under `internal/manifest` and no
  Makefile benchmark target.
- The CLI currently only warns if a metric verifier uses a repo-local command
  and `build.protected_paths` is empty.

Relevant code:

- `internal/commands/validatecmd/validate.go` emits metric hardening diagnostics
  as warnings.
- `internal/workorder/workorder.go` validates metric schema but accepts
  `min_runs` defaulting to 1 and accepts empty protected paths.

Implementation:

- Promote exactly this case to a validation error:
  repo-relative metric verifier command plus empty `build.protected_paths`.
- Keep `min_runs <= 1` and missing `noise_floor_percent` as warnings for now;
  older work orders may intentionally run deterministic checks once.
- Add optional stat warnings for protected paths that do not exist, but avoid
  hard-failing PATH commands like `go`.

Tests:

- Empty `protected_paths` with `./bench.sh` fails validation.
- Non-empty existing protected path passes.
- PATH command such as `go test ...` is not treated as missing repo-local
  verifier.
- Existing warning tests are adjusted deliberately, not incidentally.

## 4. Skill Appendix Reference Is Broken

Status: verified. Recommendation: fix now. Risk: very low.

Seen in code:

- `skills/bakeoff-run/SKILL.md` references `references/run-appendix.md`.
- The file exists at repo root as `references/run-appendix.md`.
- The skill-relative path `skills/bakeoff-run/references/run-appendix.md` is
  absent.

Implementation:

- Ship `run-appendix.md` at the path the skill names:
  `skills/bakeoff-run/references/run-appendix.md`.
- If packaging has a manifest/list of included skill files, add this file there
  too.

Tests:

- A lightweight packaging or install smoke should assert every skill-local
  `references/...` path exists.

## 5. Manual Draft Schema Guidance Is Stale

Status: verified. Recommendation: fix now. Risk: low.

Seen in run:

- `runs/2026-05-24-4f7d` drafting hit visible repair loops for:
  missing `providers[].model`, invalid `facet.focus` type, and overlong
  `facet.focus`.

Relevant code/docs:

- `internal/workorder/workorder.go` requires provider `id`, `backend`, and
  `model`.
- `internal/workorder/workorder.go` requires `facet.focus` to be a string,
  length-capped, and free of backticks/angle-bracket sentinels.
- `skills/bakeoff-run/SKILL.md` only names two provider fields and does not name
  the facet shape.
- `examples/review.work-order.json` has a facet; `examples/gather.work-order.json`
  does not.

Implementation:

- Update the skill to name `providers[].model`.
- Add the `facet.focus` constraints and point to the review example.
- Either add a facet block to `examples/gather.work-order.json` or add a
  dedicated gather-code-review example.
- Change the length error to:
  `facet.focus must be at most 500 characters (got N)`.

Tests:

- Unit test for the improved length error.
- Example validation test for the gather/code-review example if one is added.

Pre-preview validation:

- Do not make this mandatory until the tool has a clean non-mutating
  draft-validation path. Today the safer fix is better schema guidance and error
  text.

## 6. Triage Taxonomy In The Skill Is Wrong

Status: verified. Recommendation: fix now. Risk: very low.

Seen in run:

- The post-run skill wording mixed classifications with recommended actions.

Relevant code:

- `internal/triage/state.go` and triage prompt fixtures distinguish
  `classification` from `recommended_action`.

Implementation:

- Update `skills/bakeoff-run/SKILL.md` to list the real classifications:
  `real_issue`, `false_positive`, `already_fixed`, `needs_repro`,
  `evidence_gap`, `plan_doc_drift`, `product_decision`.
- Separately list actions:
  `fix_now`, `document`, `defer`, `ignore`, `reproduce`.

Tests:

- Documentation-only is acceptable, but a small grep-style doc test could guard
  against the old invented terms returning.

## 7. Codex Stderr Capture Saturates Caps

Status: verified. Recommendation: split into a low-risk artifact/summary change
now and a runner filter later. Risk: medium for the full fix.

Seen in runs:

- `runs/2026-05-24-4f7d/providers/codex-gpt-5_5/status.json`:
  `stderr_kind: "diagnostic"`, `stderr_bytes: 60000`,
  `stderr_observed_bytes: 175408`, `stderr_truncated: true`.
- `runs/dogfood-artifacts-telemetry-split.part-2/providers/codex/status.json`:
  `stderr_observed_bytes: 1264349`.
- The retained stderr begins with the Codex banner/config and prompt echo, not a
  provider failure.

Relevant code:

- `internal/runner/runner.go` applies one generic stderr cap.
- `internal/artifact/artifact.go` filters only streams classified as
  `transport_noise`, not diagnostic prompt echo.
- Manifest summaries do not make benign stderr cap saturation obvious enough.

Implementation options:

- Low-risk now: include `stderr_kind`, `stderr_truncated`, and observed/retained
  byte counts in provider summaries where humans inspect the run. Optionally
  write a compressed or head/tail-elided artifact for diagnostic stderr.
- Medium-risk later: add a Codex-specific pre-cap stderr filter in the provider
  adapter or runner options. It should remove deterministic prompt echo/banner
  blocks while preserving real error lines.

Tests:

- Classifier test for Codex prompt echo.
- Runner/provider test ensuring observed raw bytes are still recorded while
  retained diagnostic bytes are filtered or elided.

Do not:

- Treat all diagnostic stderr as noise. Some diagnostic streams contain the only
  actionable failure evidence.

## 8. `--json --quiet` Schema Expectations Diverge From Skill Consumers

Status: verified. Recommendation: document/fix skill consumers now; defer CLI
aliases unless needed. Risk: low for docs, medium for schema expansion.

Seen in runs:

- Parallel child stdout contains nested keys:
  `artifacts.report` and `triage.state`.
- Skill-side summarization expected top-level `report_path`, `triage_state`,
  `out_dir`, and `result_class`.
- For code-review runs, `decision_kind: structured_union` and
  `canonical_winner: null` are expected, not failure.

Relevant code:

- `internal/summary/summary.go` builds nested `artifacts` and `triage`.
- `internal/manifest/manifest.go` hoists some fields for `ls`, but that does not
  imply the same JSON shape for run summaries.

Implementation:

- Immediate: update the skill/appendix summarizer to read nested fields.
- Optional additive CLI change: add top-level aliases for `report_path`,
  `triage_state`, and `out_dir` across run summaries. If doing this, document
  the compatibility promise and avoid bumping meaning under the same schema
  silently.

Tests:

- JSON summary golden for gather/code-review.
- Skill fixture or appendix example using the actual nested keys.

## 9. Judge-Family Advisory Is Duplicated And Weakly Audited

Status: verified. Recommendation: fix copy duplication soon; add artifact audit
in schema PR. Risk: low for copy, medium for schema.

Seen in runs:

- The same judge-family advisory appeared from doctor/preview and then validate.
- `runs/2026-05-24-4f7d/manifest.json` records judge family relation telemetry
  but not a first-class `advisories[]` trail.

Relevant code:

- `internal/commands/doctorcmd/doctor.go` formats a doctor advisory.
- `internal/commands/validatecmd/validate.go` formats a separate validate
  warning.

Implementation:

- Use one shared formatter or shared structured advisory type for doctor,
  validate, and preview rendering.
- In the skill, show it once in preview and shorten later occurrences to a
  back-reference.
- In a schema PR, persist advisories as `meta.advisories[]` or
  `manifest.telemetry.advisories[]` with relation, judge family, provider
  family, and available alternates.

Do not:

- Make validate suppress advisories based on implicit session state in the CLI;
  validate should remain independently truthful.

## 10. Gemini Format Retry Is Common And Too Quiet

Status: verified. Recommendation: surface successful retry now; parser fallback
needs constrained implementation. Risk: low for warning, medium for fallback.

Seen in runs:

- `runs/2026-05-25-6b7a/providers/gemini/status.json` and
  `runs/2026-05-25-5e29/providers/gemini/status.json` show
  `ok_after_format_retry`.
- Initial stdout was valid-looking fenced JSON but missing `<final_json>` tags.

Relevant code:

- `internal/runner/runner.go` extracts only tagged final JSON, then launches a
  format retry.

Implementation:

- Low-risk now: add a report/json warning when a provider needed a format retry
  and succeeded.
- Later: allow exactly one fallback shape, such as a single fenced `json` object
  with no competing objects, ideally behind a provider capability flag.

Tests:

- Extraction test for one fenced JSON object.
- Negative tests for prose with multiple JSON blocks and malformed objects.

Do not:

- Accept arbitrary first JSON-looking text from a provider response. That risks
  masking instruction-following failures.

## 11. Prose Path Warnings Are Noisy

Status: verified. Recommendation: fix with focused tests. Risk: low to medium.

Seen in runs:

- A prose phrase like `manifest/decision outputs` was warned as a missing path.
- References like `bakeoff/README.md` warned because the context root was already
  the `bakeoff` repo directory.

Relevant code:

- `internal/repocontext/repocontext.go` tokenizes slash-containing strings and
  suggests nearby paths before some prose filtering kicks in.

Implementation:

- Treat slash-delimited two-word prose as prose before accepting fuzzy
  suggestions, unless the token has a strong path signal:
  extension, leading `./`, leading `/`, leading known repo root, line suffix, or
  backtick/code context.
- For a leading segment equal to the context-root basename, emit a clarifying
  note: paths resolve relative to this root; the leading repo segment can be
  removed.

Tests:

- `manifest/decision outputs` with `internal/decision/` present does not warn.
- `bakeoff/README.md` under a `bakeoff` root gets the specific root-prefix note.
- Real missing paths with extensions still warn.

## 12. Build Tie/Unresolved Output Hides Exit State

Status: verified. Recommendation: fix soon. Risk: low.

Seen in run:

- `runs/dogfood-ls-manifest-perf/decision.json` has
  `decision_kind: "tie"`, `canonical_winner: null`, and
  `stalled_at: "selection"`.
- CLI tail showed `result: tie, winner=none, basis=none` but not exit code 3 or
  stalled substate.
- Swapped judge pass disagreement was visible in JSON but not the final tail.

Relevant code:

- `internal/commands/buildcmd/run.go` prints generic swapped-judge and tail
  lines.
- Build escalation is intentionally forbidden, so the tail must not steer users
  toward escalation.

Implementation:

- Add a tail line:
  `status: stalled at selection (exit 3)` when a build decision exits
  unresolved.
- Add a concise swapped-pass rationale line when pass1/pass2 disagree:
  `swapped pass disagreed (pass1=tie, pass2=codex) -> tie`.
- Update skill summary vocabulary so `tie` maps to the allowed lead label
  `unresolved`, with decision-kind details on the next line.

Tests:

- Build command output golden for a tie/stalled decision.
- Existing success output remains unchanged.

## 13. Escalation/Decision Schema Should Be More Explicit

Status: partially verified. Recommendation: only add additive advisory flags soon;
defer broad schema normalization. Risk: medium.

Seen in runs:

- Dispute/advisory decisions encode advisory-ness in strings such as
  `escalation_advisory_supported`.
- `canonical_winner: null` is not enough for consumers to know the result is
  intentionally non-binding.
- `caveats` alternates between human text and token-like strings across run
  types.
- Escalation independent runs do not expose the same `judge_passes`/`order_maps`
  shape as analyze/build position-swap decisions.

Relevant code:

- `internal/decision/escalation.go` builds escalation decision objects.
- `internal/manifest/manifest.go` projects decision data into manifest telemetry.

Implementation:

- Safe additive change: add `advisory: true` and `binding: false` to advisory
  witness/dispute decisions and manifest summaries.
- Defer `caveats` normalization to a schema PR:
  `caveats: ["snake_case_token"]` plus `caveat_messages`.
- Defer escalation `judge_passes`/`order_maps` unless product explicitly wants
  bias-audit parity for independent escalation. Independent escalation is not the
  same as a position-swapped judge pass, so copying the shape casually may
  confuse consumers.

Tests:

- Golden decisions for witness/dispute include `advisory`/`binding`.
- Schema docs spell out which escalation modes can be binding.

## 14. Runtime Visibility For Quiet/Buffered Workers

Status: verified. Recommendation: fix soon. Risk: low.

Seen in runs:

- Long Claude SDK spans produced repeated quiet ticks or, under the desktop
  harness, no visible heartbeats for many minutes.
- Users interpreted `out=0.0KB err=0.0KB last=600s` as a possible deadlock.

Relevant code:

- `internal/commands/shared.go` owns tick formatting.
- `internal/runner/runner.go` detects quiet phases and IO stats.

Implementation:

- Add a once-per-provider note after a long quiet threshold:
  `long quiet; provider output may be buffered until completion`.
- For known buffered transports, append a shorter first-quiet note:
  `(buffered, output expected at completion)`.
- In the skill, say long-budget runs may be backgrounded by the host and live
  heartbeats may not be visible.

Tests:

- Tick-printer test confirming the note appears once and normal ticks remain
  compact.

## 15. Draft-Build Flag Discoverability And Gate Shorthand

Status: verified. Recommendation: fix as low-risk polish. Risk: low.

Seen in run:

- Drafting tried `--edit-scope`; CLI only accepts `--scope`.
- Bare `--gate "go test ./..."` errors without a concrete suggestion.
- Skill does not list canonical `draft-build` flags.

Relevant code:

- `internal/commands/draftbuildcmd/draft_build.go` declares flags and parses
  `--gate <id>=<command>`.

Implementation:

- Add skill docs naming canonical flags:
  `--id`, `--goal`, `--acceptance`, `--scope`, `--gate`,
  `--protected-path`, `--base-ref`, `--provider`.
- Either add hidden aliases `--edit-scope`/`--edit-boundary`, or leave flags
  unchanged and improve the error copy. The lowest-risk change is docs plus a
  concrete gate error:
  `--gate[0] must use <id>=<command>, for example tests=go test ./...`.
- Auto-naming bare gates is convenient but changes semantics; defer unless users
  keep hitting it.

Tests:

- Gate parse error includes the example.
- If aliases are added, hidden flag tests cover them.

## 16. Skill And Copy Bundle

Status: verified. Recommendation: batch as one skill/docs commit. Risk: very low.

Items:

- `commands/run.md` description should name the preview/approval gate.
- `README.md` should list approval tokens.
- Preview footer should separate approval tokens from non-approval commands:
  approval: `yes`, `approve`, `run it`; commands: `show`, `edit`, `cancel`,
  and `swap judge to <backend>` when applicable.
- Preview defaults should be marked as defaults where useful:
  triage on, effort levels, `scope_policy.enforcement`, inferred base ref, and
  background conversion.
- Multi-lens summaries should use canonical headings from the appendix, or the
  appendix should explicitly say headings are advisory. Prefer canonical
  headings.
- Lens label normalization should be disclosed in preview.
- `structured_union` should render as `merged` or `combined`, not `consensus`.
- Escalation previews should not repeat redundant `Why this loop` lines.
- Split/post-run summaries should provide at most one artifact-aware
  continuation recommendation.
- Validation warnings should be printed verbatim before assistant gloss.

Implementation:

- Update `skills/bakeoff-run/SKILL.md`, `references/run-appendix.md`,
  `commands/run.md`, and `README.md`.
- No CLI tests required unless docs tests exist.

## 17. Gitlink/Submodule Warning

Status: verified in report, not yet high value. Recommendation: defer or demote
later. Risk: low.

Seen in run:

- Build warned that source checkout contains gitlink/submodule entries even
  though no provider attempted a gitlink modification.

Relevant code:

- `internal/commands/buildcmd/helpers.go` emits the warning.

Implementation:

- Demote to info, or gate warning display on an actual rejected gitlink patch.

Decision:

- This is mild noise. It is less important than tie-state output and metric
  validation.

## 18. Parallel Fanout Liveness

Status: sharp edge, not current CLI defect. Recommendation: defer. Risk: medium
if implemented hastily.

Seen in reports:

- `.bakeoff-parallel-launch.sh` has pid files but no lock/reap/resume protocol.

Implementation:

- If parallel fanout becomes first-class, implement a small supervisor with
  lockfile, `kill -0` checks, pid cleanup, and relaunch refusal for live runs.

Decision:

- Defer. The helper is not yet a stable CLI contract, and there are more direct
  user-facing defects.

## 19. Escalation Back-Pointer Reader Bug

Status: verified as documentation/reader issue, not CLI defect. Recommendation:
document, do not alter schema now. Risk: very low.

Seen in run:

- `runs/2026-05-25-6b7a/manifest.json` already contains
  `escalation.source_run_id`, `source_providers`, and `source_type`.
- The reported `source_run=None` came from a downstream reader looking for
  non-existent top-level keys.

Implementation:

- Document the escalation manifest schema in `docs/cli-reference.md`.
- Optional future CLI projection:
  `bakeoff inspect --escalation-summary <run-id>`.

## 20. `judge.status: null`

Status: not reproduced as current fix target. Recommendation: no code change
without a fresh failing fixture. Risk: low if fixed, but not worth guessing.

Seen in report:

- One report observed top-level `judge.status: null` with nested judge completion.

Decision:

- Do not fix from memory. Reproduce against current manifest writer first. If
  still present, either elide nil `judge.status` or backfill from nested status.

## 21. `capture.json` vs `final.json` Overlap

Status: observed but not proven harmful. Recommendation: document only. Risk:
medium to merge.

Seen in run:

- Provider `capture.json` and `final.json` share some outcome fields.

Decision:

- Keep both until a consumer contract says otherwise. Document which file is
  canonical for raw capture vs provider-declared final JSON.
- Do not merge files casually; artifacts are already consumed by run readers and
  debugging workflows.

## 22. Gemini Witness `new-01` Fallback-Provider Claim

Status: refuted. Recommendation: no fix.

Seen in run:

- The source item existed in Gemini witness output and report markdown; the bug
  was triage intake, not provider generation or fallback-provider attribution.

Decision:

- Fold all action into item 1.

## 23. Pre-Preview Validation Contract

Status: real UX pain, but policy needs care. Recommendation: defer mandatory
validation; improve docs and errors now. Risk: medium.

Seen in run:

- User saw multiple write/validate repair loops after approval.

Implementation path:

- Add a non-mutating validator path for generated drafts, preferably validating
  an in-memory or temp file before showing preview.
- Until that exists, the skill should not promise mandatory invisible validation.

Decision:

- Do not force every preview through current file-writing validation mechanics.
  That risks more churn and hidden edits.

## 24. Metric `min_runs` And Noise-Floor Strictness

Status: plausible but not enough evidence to hard-fail broadly. Recommendation:
defer hard errors; keep warnings. Risk: medium.

Seen in report:

- User requested explicit `min_runs` and `noise_floor_percent` for a metric
  bakeoff.

Decision:

- Hard-fail missing `protected_paths` for repo-local metric verifiers now.
- Keep `min_runs <= 1` and missing noise floor as warnings until the CLI has
  enough examples of deterministic one-shot metrics.

## Suggested Implementation Order

1. Skill/docs batch:
   appendix path, provider model/facet guidance, taxonomy, approval tokens,
   verdict vocabulary, draft-build flags, run-command description, preview
   default wording.
2. Small validation/manifest correctness batch:
   `highestSeverity` classification filter, metric protected-path error,
   `facet.focus` length feedback.
3. Escalation triage batch:
   structured escalation-provider finding intake, source-finding filter
   provenance, tests.
4. Human-output batch:
   build unresolved/tie status line, swapped-pass line, quiet/buffered tick note,
   format-retry warning.
5. Schema/runtime batch:
   advisory audit trail, additive advisory/binding flags, structured truncations,
   Codex stderr pre-cap filtering, constrained Gemini parser fallback.

## Highest Value / Lowest Risk Shortlist

- Copy or package `run-appendix.md` under `skills/bakeoff-run/references/`.
- Add `providers[].model` and `facet.focus` rules to the skill.
- Add actual length to the `facet.focus` validation error.
- Fix triage taxonomy and `structured_union` wording in the skill.
- Add `draft-build` flag reference and better `--gate` error text.
- Change `highestSeverity` to ignore non-actionable classifications.
- Promote repo-local metric verifier with empty `protected_paths` to validation
  error.
- Add build `status: stalled at selection (exit 3)` tail line.
- Add one quiet/buffered note in runner output.
