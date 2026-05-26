# Dogfood findings — bakeoff CLI hardening + /bakeoff:run UX

Source: dogfood pass over the `dogfood-artifacts-telemetry-split` runs on 2026-05-25.

## Run context

| Run id | Mode | Providers | Judge | Outcome |
| --- | --- | --- | --- | --- |
| `dogfood-artifacts-telemetry-split.part-1` | research / analyze | claude/sonnet, codex/gpt-5.5 | claude/opus xhigh | `pick_winner`; canonical_winner=codex; spine_tiebreak=`atomic_count`; `kept_from_nonwinner=4` |
| `dogfood-artifacts-telemetry-split.part-2` | research / analyze | claude/sonnet, codex/gpt-5.5 | claude/opus xhigh | `pick_winner`; canonical_winner=claude; spine_tiebreak=`swap_agreement`; `kept_from_nonwinner=7` |
| `2026-05-25-6b7a` | escalate / independent (source=part-1) | + gemini/pro | claude/opus synthesis | `escalation_supports_source`; canonical_winner=codex |
| `2026-05-25-5e29` | escalate / dispute (source=part-2) | + gemini/pro | none (advisory) | `escalation_advisory_supported`; canonical_winner=null (expected for dispute) |

Doctor at draft time: `selected_default_pair=[claude, codex]`, `runnable_default_pair_available=true`, `judge_family_advisory.relation=same_as_some`, `ready_non_contestant_judges=[gemini, copilot]`.

All four runs exited 0; no triage was emitted (analyze mode does not auto-triage). Both escalation provider calls were `ok_after_format_retry` on gemini.

---

## CLI / plugin hardening targets

### P0

#### 1. Codex stderr disk bloat — 1.26 MB retained per run
- **Evidence:** `runs/dogfood-artifacts-telemetry-split.part-2/manifest.json` lines 165-169 → `stderr_observed_bytes=1264349`, `stderr_bytes=60000`, `stderr_truncated=true`, `stderr_kind=diagnostic`. Part-1 codex stderr was 218 KB observed for the same shape. Judge never reads stderr.
- **Fix shape:** when `stderr_kind=diagnostic` and the in-memory cap fires, write the on-disk `providers/codex/stderr.txt` as gzipped (`.txt.gz`) or as head-30KB + middle-elided + tail-30KB. Likely lives in the codex provider adapter where the stderr capture is finalized.
- **Why it matters:** every codex run today writes ~1 MB of unused diagnostic logs. Multiplies across reruns and escalations.

#### 2. Downstream-reader contract gap on escalation back-pointers
- **Evidence:** `runs/2026-05-25-6b7a/manifest.json:198-203` already contains `escalation.source_run_id`, `escalation.source_providers`, `escalation.source_type`, and `decision.json.synthesis.headline`. The "source_run=None / summary=None" observation in the post-run digest was a *reader* bug (looked at non-existent top-level `source_run` and `summary` keys).
- **Fix shape:** not a CLI fix. Document the escalation manifest schema in `docs/cli-reference.md` (or wherever the manifest schema lives) so downstream consumers know to read `manifest.json.escalation.source_run_id` and `decision.json.synthesis.headline`. Optionally add a thin `bakeoff inspect --escalation-summary <run-id>` view to centralize the projection.

### P1

#### 3. Gemini format-retry tax (100% rate on escalation)
- **Evidence:** both `runs/2026-05-25-6b7a/decision.json:104-167` and `runs/2026-05-25-5e29/decision.json:181-242` show `format_retry.attempted=true`, `reason: stdout is missing a <final_json>...</final_json> block`. ~17 seconds + 1 extra provider invocation per run. Two-for-two so far.
- **Fix shape:** either (a) relax the gemini parser to accept a bare top-level JSON object as fallback when the sentinel tags are absent (it already returns valid JSON), or (b) add a gemini-specific prompt suffix that explicitly requires closing with `</final_json>`. Option (a) is safer.
- **Files likely involved:** the gemini provider adapter (where stdout is parsed into `final_json`), and the prompt builder.

#### 4. Validate substring path-sniff false positive
- **Evidence:** part-1 emitted `warning: background references "manifest/decision" which does not exist under <context-root>; did you mean one of: internal/decision/?` — the prose phrase was `"manifest/decision outputs"`. The token has a `/`, so the path-sniff fired, but no extension/leading-dot/known-dir prefix.
- **Fix shape:** in `internal/commands/validatecmd/validate.go:168` (and the token extractor that calls it), require one of: file extension, leading `./` / `~` / `/`, leading `internal/` / `docs/` / `examples/` / known-top-level dir, or a `:LINE` suffix, before classifying a token as a path reference. Alternatively, only scan tokens inside backtick-delimited spans.
- **Why it matters:** noisy validate warnings train users to ignore validate output.

#### 5. Judge family advisory emitted twice (validate + preview)
- **Evidence:** `internal/commands/validatecmd/validate.go:256` emits the advisory at validate time; the run-preview path re-renders it from doctor output. Both this dogfood's runs printed the same copy twice.
- **Fix shape:** either (a) the preview suppresses validate advisories the doctor preview already showed (pass a "seen" set), or (b) validate emits structured advisories and the preview renders only ones the user hasn't acknowledged in this session.

#### 6. Dispute advisory status encoded only in string prefix
- **Evidence:** `runs/2026-05-25-5e29/manifest.json:70-72` has `canonical_winner: null` and `decision_kind: "escalation_advisory_supported"` — but no top-level `advisory_only: true` or `binding: false`. Consumers must know that `escalation_advisory_*` decision_kinds are advisory by convention.
- **Fix shape:** add `"advisory": true` to both `manifest.json` and `decision.json` whenever `escalation_mode=="dispute"` or `decision_kind` starts with `escalation_advisory_`. Surface in `internal/decision/decision.go` and `internal/manifest/manifest.go`.

### P2

#### 7. `caveats` field shape inconsistency across decision.json
- **Evidence:**
  - part-1 `decision.json`: `"caveats": ["spine chosen by atomic_count after swap disagreement"]` (human sentence)
  - `2026-05-25-6b7a/decision.json`: `"caveats": ["synthesis_judge_not_position_swapped"]` (snake_case enum-like token)
  - `2026-05-25-5e29/decision.json`: `"caveats": []`
- **Fix shape:** pick one. Recommended: machine-readable `caveats: ["snake_case_token", ...]` plus a sibling `caveat_messages: { "snake_case_token": "human sentence", ... }`. Update emitters in `internal/decision/`.

#### 8. Escalation runs missing `judge_passes` / `order_maps`
- **Evidence:** `runs/2026-05-25-6b7a/decision.json` and `runs/2026-05-25-5e29/decision.json` lack the `judge_passes` / `order_maps` keys that analyze runs have (part-1 lines 264-293). For judge-bias measurement (literally the question part-2 asked), escalations are currently not bias-auditable.
- **Fix shape:** when escalation runs a synthesis judge (independent mode), emit the same `judge_passes` / `order_maps` shape. For advisory/dispute modes where there is no synthesis judge, emit them as `null` so the schema stays uniform across run types.

#### 9. `output_truncation_count` is too coarse
- **Evidence:** all four manifests show `telemetry.artifacts.output_truncation_count: 1`. Doesn't say which provider, which stream (stdout vs stderr), or by how much.
- **Fix shape:** replace with structured `output_truncations: [{ provider, stream, observed_bytes, kept_bytes }]` in `internal/manifest/manifest.go`.

---

## /bakeoff:run skill UX issues

### Blockers (spec-violation)

#### A. Continuation recommendation listed two options
- **Evidence:** SKILL.md §Execution And Summary says "at most one artifact-aware continuation recommendation is allowed." The post-split summary offered both `--mode dispute --dry-run` for part-2 *and* `--mode independent --dry-run` for either run as parallel siblings.
- **Tweak:** pick the higher-signal mode (independent, when a family advisory is active) as the single recommendation; demote alternatives to a single trailing "Other options" line matching the triage-failed ordering already in the spec.
- **Where:** SKILL.md needs an explicit clause covering the post-split summary template (the constraint exists for single-run summaries; the split summary template inherited the constraint implicitly but didn't enforce it in practice).

#### B. Inconsistent accept tokens across escalation previews
- **Evidence:** the independent preview said `Reply \`run it\` to launch`; the dispute preview said `Reply \`yes\` to launch`. Users comparing the two see asymmetric accept-tokens for what is functionally the same step.
- **Tweak:** standardize on `Reply \`run it\` to launch` in all escalation dry-run previews. The cheap-advisory "single yes" carve-out in SKILL.md §Drafting Invariants should be reconciled — either accept `yes` *or* `run it` in both, or drop the carve-out entirely.

### Polish

#### C. `Why this loop:` line is redundant in escalation previews
- **Evidence:** the mode name is already in the title (`Mode: independent (fresh third answer)`); `Why this loop: fresh third answer` restates the parenthetical.
- **Tweak:** drop the route-advisor line from escalation previews. Keep it only on task-fit warnings (`Why this loop: single-agent advised`) and build drafts (`Why this loop: build-verifier path`), where it actually disambiguates.

#### D. Post-split verdict prefix diverged from spec
- **Evidence:** spec says `Decision: <X wins | consensus | unresolved> - <one-line position>`. The summary emitted `Decision: part-1 — codex wins — research replay & artifact-copy extraction analysis`. The run-id appears before the verdict noun.
- **Tweak:** render as `Decision: codex wins part-1 — research replay & artifact-copy extraction analysis`. Update the post-split summary template (likely in SKILL.md or in run-appendix.md).

#### E. Family-advisory copy repeats verbatim three times
- **Evidence:** the same "judge claude shares family metadata with provider claude; ready non-contestants: gemini, copilot" wording appeared in the preview, in the validation warning passthrough, and in the post-run caveats — all unchanged, all in one workflow.
- **Tweak:** after the first preview disclosure, downgrade subsequent surfacings to a back-reference: `Judge family advisory (see preview) still applies.`

#### F. Mode-switch (`dispute` after `independent` preview) worked silently
- **Evidence:** user typed `dispute` after seeing the independent-mode preview; the skill re-previewed without any acknowledgment of the switch.
- **Tweak:** add one-line confirmation: `Switched to dispute mode. New preview below.`

#### G. Parallel cost note buried under choice labels
- **Evidence:** the split preview's "Parallel cost note: ... `latest` will point to one child run" is accurate but only relevant if the user picks `parallel`. Users who pick `sequential` don't need it.
- **Tweak:** show the parallel cost note only after the user types `parallel`, or visually nest it under the `parallel` bullet.

#### H. "Per split rules, I'm not synthesizing..." reads defensive
- **Evidence:** the trailing sentence in the post-split summary explains the absence of a cross-run synthesis. Internal rule leaking into user-facing copy.
- **Tweak:** replace with affirmative offer: `Want a cross-run synthesis pass? Reply \`synthesize\`.` Or drop entirely — the user did not ask, and the rule is internal.

#### I. Validation warning gloss editorialized on assistant prose
- **Evidence:** the validate-warning passthrough included the editorializing gloss `(part-1; my prose used the phrase loosely — not a path)` inline with the warning text.
- **Tweak:** SKILL.md §Clean Splits already says "print each warning verbatim on its own line before adding any assistant gloss." Apply the same rule to non-split execution warning passthroughs. Glosses are fine but must be on a separate line after the verbatim warning.

#### J. Dispute summary re-explained the alternative mode after the user chose
- **Evidence:** the dispute completion summary's "Caveats" section ended with "...the equivalent here would be `--mode independent`. Independent CAN change the winner; dispute cannot." — second-guessing a just-made user choice.
- **Tweak:** drop that trailer; the user already saw the trade-off in the preview.

### What worked well (keep)

- Split proposal: numbered parts + eligibility rationale + three-choice reply (`split` / keep-combined / `cancel`).
- Sequential/parallel token consistency matched `references/run-appendix.md` exactly.
- Family advisory was surfaced *without* auto-switching — the load-bearing UX rule.
- Sequential exit-code handling continued correctly after part-1's clean exit.
- Independent escalation summary named "family bias did not drive the outcome" in plain English — the right interpretation of `escalation_supports_source`.
- Dispute preview correctly identified the 7 `kept_from_nonwinner` items as the natural dispute surface.

---

## Suggested next steps

1. **Single PR**: items 4, 5, A, B, C, D, E, F, I — all small SKILL.md / validate.go edits, no schema changes.
2. **Schema PR**: items 6, 7, 8, 9 — additive `advisory` flag, normalized `caveats`, escalation `judge_passes`/`order_maps`, structured `output_truncations`. Bump or version-gate manifest schema if needed.
3. **Separate PR per provider**: item 3 (gemini fallback parser) and item 1 (codex stderr compression).
4. **Doc**: item 2 — escalation back-pointer schema in `docs/cli-reference.md`.
