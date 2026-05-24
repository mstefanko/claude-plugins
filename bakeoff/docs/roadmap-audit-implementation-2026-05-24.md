# Bakeoff Roadmap — Implementation/Risk Audit (2026-05-24)

Auditor: agent-deep-analysis. Scope: implementation effort and risk only. The
value/evidence axis is being audited by a parallel agent and is out of scope
here.

Inputs verified against actual code (file:line citations throughout):

- `internal/workorder/workorder.go` (1767 lines, validators incl.
  `ValidateEscalationWitnessResult` at line 1172)
- `internal/provider/provider.go` (419 lines, `BackendSpec` at line 27 — **no
  family field**)
- `internal/decision/decision.go` (761 lines) + `internal/decision/escalation.go`
  (175 lines)
- `internal/report/report.go` (1167 lines, `renderOutcome` at line 261)
- `internal/commands/buildcmd/report.go` (373 lines, `Selection basis` at line 33)
- `internal/commands/escalatecmd/escalate.go` (1401 lines — large file, mode
  dispatch at lines 247-251, build rejection at line 727-728)
- `internal/commands/reruncmd/rerun.go` (112 lines, `--judge-only` build
  rejection at line 78-80)
- `internal/commands/validatecmd/validate.go` (197 lines)
- `internal/artifact/artifact.go` (649 lines, `WriteMeta` at line 517) +
  `internal/manifest/manifest.go` (800 lines)
- `internal/triage/state.go` (452 lines)
- `skills/bakeoff-run/SKILL.md` (545 lines)
- `README.md` (329 lines), `docs/cli-reference.md` (477 lines),
  `commands/run.md` (15 lines)

---

## Summary Table

| Item | Assessment rating (cmplx / risk) | Auditor rating | Verdict | One-line reason |
|---|---|---|---|---|
| Fix Routing Copy | XS-S / Low | XS-S / Low | Agree | Doc-only across 4 files. |
| Route Advisor Preview | S / Low | S / Low | Agree | Stays in skill/run.md natural-language layer. |
| Selector Confidence Section | S-M / Med | **M / Med** | Partial disagree | report.go is 1167 lines + buildcmd/report.go 373 lines + fixture churn; closer to M than S. |
| Stop-Here Recommendations | S / Low-Med | S / Low-Med | Agree | Skill copy only. |
| Post-Run Recommendations | S-M / Med | M / Med | Agree | Reasonable. |
| Judge-Only Degraded Copy | S / Low-Med | S / Low-Med | Agree | Three small surfaces. |
| Provider-Authored Tests Reminder | XS-S / Low | XS-S / Low | Agree | Single buildcmd/report.go insert. |
| Triage Freshness First Copy | S-M / Low-Med | S / Low-Med | Disagree | Skill-copy first cut is S (XS even); only goes to M if enforced in code. |
| Source-Run Bundle For Escalation | S / Low | S / Low | Agree | Docs + maybe small bundle nudge. |
| Tighten Witness Audit/Falsification | M / Med | **M-L / Med-High** | Partial disagree | Per-item object schema across `material_errors`/`missed_material`/`triage_concerns` plus report rendering plus prompt fixture changes is heavier than M; underrated. |
| Build Metric Verifier Guidance/Linting | S-M / Med | **S / Med** | Disagree (cheaper) | validate.go is 197 lines; lints are additive `warnings = append(...)` lines. Closer to S. |
| Third-Party Judge Advisory | M / Med | **M-L / Med** | Disagree (more expensive) | Requires `Family` on `BackendSpec` (touches catalog, doctor, validate, draft, preview, advisory message) + provider_test.go updates. The metadata work bleeds into 3-4 other items. |
| Local Telemetry Fields | M-L / Med | M-L / Med | Agree | Spans artifact, manifest, summary, multiple cmds; schema discipline mandatory. |
| Accepted-Finding Feedback | M / Med | M / Med | Agree | New command + new artifact + triage integration. |
| `judge_policy` / Draft-Time Judge Knob | M-L / Med | M-L / Med | Agree | Needs family metadata first; correctly deferred. |
| Judge-Family Rotation Recipe | S as recipe / M-L as CLI | S / M-L | Agree | Docs-only path is fine. |
| Witness Self-Consistency n=3 | L / High | L / High | Agree | Many new artifact + aggregation surfaces. |
| Judge Panels Or Juries | XL / High | XL / High | Agree | Selector + schema redesign. |
| Build Escalation | L / High | L / High | Agree | escalate.go is already 1401 lines and explicitly rejects build at 727-728; opening it is invasive. |
| Batch Schema / Persistent Multi-Run | XL / High | XL / High | Agree | Cuts across runner/ledger/manifest/status. |
| Hidden Patch Synthesis | L / High (if built) | L / High | Agree | Reject. |
| Default Debate Loops | XL / High (if built) | XL / High | Agree | Reject. |
| Three Worker Providers Normal | XL / High (if built) | **L / High** | Partial disagree | Schema break is real but smaller than XL — `validateProviders` is one function (workorder.go:401-432); selector + report fanout is the wider blast. Still correct to reject; just calling out the rating. |
| Auto-Apply / Merge / PR | M-L / High (if built) | M-L / High | Agree | Reject. |
| New `adversarial` Mode | S-M / Med (if built) | S-M / Med | Agree | Reject — duplicate of witness. |
| Per-Finding Agent Fanout | L-XL / High (if built) | L-XL / High | Agree | Defer/reject. |
| Large `report.md` Parser | M / High (if built) | M / High | Agree | Avoid. |
| Verbal Confidence Gates | M / High (if built) | M / High | Agree | Reject. |
| Persona Lenses As Cross-Family Substitute | S-M / Med | S-M / Med | Agree | Avoid framing. |

Net: 23 of 29 items agree; 6 partial-disagreements. The corrections are not
dramatic — the doc is broadly well-calibrated — but two ratings are off in
ways that matter for sequencing (Selector Confidence underrated, Witness
tightening underrated; Metric lint overrated; Third-Party Judge Advisory
underrated because of hidden Family-metadata work).

---

## Detailed Notes (Disagreements Only)

### Selector Confidence Section — S-M is borderline; call it M

The assessment says S-M, derived from `decision.json`. That's correct in the
narrow sense but understates the surrounding work:

- `internal/report/report.go` is 1167 lines and has 7+ render functions that
  the new section must coexist with (`renderOutcome` at 261, `decisionAudit` at
  ~336, `renderJudgeFailureStatus`, plus dispute/witness branches at 100, 192).
- `internal/commands/buildcmd/report.go` (373 lines) renders `Selection basis`
  at line 33 and judge rationale at line 227 — extending into a "confidence
  explanation" means rewiring the renderer's ordering decisions.
- `internal/report/report_test.go` is 398 lines of fixture-driven tests; adding
  the taxonomy from the assessment (8 labels) requires fixture updates for
  every label, not just adding one fixture.
- The taxonomy itself crosses build and research reports. Two renderers must
  agree on labels.

Effort: M (still low risk). Worth flagging because the assessment's
"Authoritative Next Implementation Plan" pairs this with three other items in
"slice 2" and the fixture cost dominates that slice.

### Tighten Witness Audit/Falsification — M is too low; M-L

The assessment says M with the caveat "Validation **may need** stricter per-
item JSON objects." Looking at the current validator (`workorder.go:1172`):

- Current validation: `material_errors`, `missed_material`, `triage_concerns`,
  `out_of_scope`, `recommended_next_checks`, `rationale` are all just
  `[]any` (any element type passes).
- Tightening means: per-item object schema for at least three of these arrays
  (text, location, evidence pointer, severity, etc.), each with its own
  required-fields list. That's effectively four new validators inside
  `workorder.go`.
- Prompt builder (`internal/prompt/...` — referenced via
  `prompt.BuildEscalationWitnessPrompt` in escalate.go:257) must also change to
  ask for the new shape. Schema-prompt drift is a recurring source of
  validation failures.
- Report rendering (`report.go` already renders witness at lines 100, 192-ish)
  must render structured per-item witness output without making the report
  noisier.
- `escalate_test.go` is 513 lines and has prompt-fixture coverage. Tightening
  changes those fixtures across at least 3 scenarios.

This is closer to M-L. Important because the assessment lists this as "ship
soon" after slice 1.

### Build Metric Verifier Guidance/Linting — S, not S-M

`internal/commands/validatecmd/validate.go` is 197 lines, with `min_runs`
already wired at line 185. Adding three more warnings (`noise_floor_percent`
absent, `min_delta_percent` absent, `min_runs` too low for noisy metrics) is
three additive `warnings = append(...)` calls. Test surface is
`validate_test.go` (228 lines) — add 3-4 table-driven cases.

The risk framing (false-positive lint across languages) is fair — keep it
"Medium" — but the **effort** is S, not S-M. The assessment may have inflated
it because the doc-side work (work-order docs, README, cli-reference, SKILL)
travels with it; even so, that doc work is XS individually.

### Third-Party Judge Advisory — M is too low; M-L

The assessment correctly identifies that `BackendSpec` has no family field.
Grep confirms: `internal/provider/provider.go:27` lists only `Name,
Executable, DefaultModel, Optional, PromptFlavor, SupportsBuild`. Adding
`Family`:

- Touches catalog at line 64 (4 entries to fill).
- Touches `KnownBackends`, `Backend(name)` lookups.
- Provider tests (`provider_test.go`, 286 lines) need family assertions.
- Doctor command (`internal/commands/doctorcmd/doctor.go`) needs to consume
  family for the advisory output.
- Validate (`validatecmd/validate.go`) needs an advisory warning path; this is
  the new warning surface.
- Draft (`internal/workorder/draft.go`, 265 lines) needs to be family-aware if
  the advisory should fire at draft time.
- SKILL.md (545 lines) must explain when the third-backend advisory means
  "switch judge family".

This is M-L, not M. **And it's a prerequisite for `judge_policy` (Measure
First) and for judge-family rotation if productized — the assessment lists
those as independent but they actually all depend on this metadata landing
first.** See cross-cutting concern below.

### Triage Freshness First Copy — closer to S/XS than S-M

The assessment's primary surface is `skills/bakeoff-run/SKILL.md` which already
says "recommend `bakeoff triage <run-id> --force` first." If this is the
docs-only delivery the assessment describes, effort is XS-S. The M ceiling
only applies if the recommendation gets enforced in code (bundle.go / show.go
/ escalation dry-run), which the assessment notes as optional. Splitting the
item into "doc copy now (XS-S)" and "enforce later (M)" would make the
sequencing clearer.

### Three Worker Providers Normal — L, not XL

The schema enforcement is one function: `validateProviders` at
`workorder.go:401-432` (the `len(items) != 2` check at line 403 is the
explicit gate). The XL rating in the assessment is right when you count
selector redesign (`decision.go`, 761 lines, mostly assumes 2-provider input
keys), report fanout, and judge logic — but the **schema lift** itself is M.
This matters only if someone reads "XL" as "schema break impossible." The
reject recommendation is still correct.

---

## Top 3 Corrections The User Should Know

1. **Third-Party Judge Advisory is a gating prerequisite, not an independent
   item.** The assessment puts it in "Ship Soon" with no explicit dependency
   declaration, but it requires adding `Family` to `BackendSpec`
   (`provider.go:27` — currently absent). That family field is *also* needed
   by `judge_policy` (Measure First) and Judge-Family Rotation (Measure
   First). If the user ships those in any order other than "advisory first,"
   they'll either duplicate the metadata work or build two of them against
   ad-hoc family inference. **Recommend sequencing the family-metadata change
   as its own micro-item before any of the three judge-family items.**

2. **Tighten Witness is underrated at M; treat it as M-L and don't bundle it
   into slice 2 with three other items.** Per-item object validators for
   `material_errors`/`missed_material`/`triage_concerns` are effectively four
   new validators inside `workorder.go`, plus prompt-fixture rewrites in
   `escalate_test.go` (513 lines), plus report rendering changes. The
   "Authoritative Next Implementation Plan" lists witness work as the fourth
   slice item; in practice it deserves its own slice.

3. **Build Metric Verifier Linting is cheaper than rated and should move
   earlier in the queue.** `validate.go` is 197 lines and the lints are
   additive append-warning calls. This is S, not S-M, and probably the
   cheapest high-value Ship-Soon item. If the user wants quick wins after
   slice 1, this is the lowest-cost build-side improvement.

---

## Cross-Cutting Concerns

### C1. Provider-family metadata is a hidden hub

Four items depend on `BackendSpec.Family`: Third-Party Judge Advisory,
`judge_policy`, Judge-Family Rotation, and (loosely) Local Telemetry "judge-
family relation" field. The assessment treats them as independent. They are
not. Sequencing recommendation:

```
Family metadata on BackendSpec  →  Telemetry capture of family
                              ↓
                          Advisory  →  judge_policy  →  Rotation
```

### C2. `internal/report/report.go` is a fragile shared module

Six Ship-Now items touch `report.go` (1167 lines) or `buildcmd/report.go`
(373 lines): Selector Confidence, Stop-Here, Post-Run Recommendations,
Judge-Only Copy, Provider-Authored Tests Reminder, Triage Freshness (if
code-enforced). Plus Tighten Witness in Ship Soon. The renderer has 7+
render functions already and ordering matters. Recommend a **single report
refactor PR before Slice 2** that introduces a stable section ordering and
helper for advisory blocks; otherwise these six items will collide in
review.

### C3. `escalatecmd/escalate.go` is already 1401 lines

Two roadmap items touch this file (Tighten Witness, Build Escalation if ever
revisited). Witness self-consistency n=3 would land here too. It is already
the largest command file by far. Any non-trivial change should consider
splitting it (e.g., `runWitness`, `runDispute`, `runIndependent`, source-run
plumbing into separate files in the same package) before piling more on.
That refactor is not in the roadmap; flag it as latent debt that any Witness
work will run into.

### C4. Skill/doc surfaces are the cheapest delivery — but they're spread
across four files

`skills/bakeoff-run/SKILL.md` (545), `README.md` (329), `docs/cli-reference.md`
(477), `commands/run.md` (15). Most Ship-Now items want all four updated for
consistency. The assessment correctly flags "contradictory wording" as the
primary risk. Recommend a single doc-pass PR for slice 1 rather than per-item
commits; otherwise consistency will drift between PRs that each touch only
two of the four surfaces.

---

## Risks The Assessment Missed Or Underweighted

- **Prompt-validator drift on Tighten Witness:** when `ValidateEscalationWitnessResult`
  tightens, the prompt builder (`prompt.BuildEscalationWitnessPrompt`) must
  match exactly or every witness run fails validation. The assessment
  mentions "prompt builder and fixtures should define the tighter contract"
  but doesn't flag the failure mode if they desync. Mitigation: pin a
  prompt-validator round-trip test that asserts a sample valid output passes
  the validator.
- **Manifest stability for telemetry:** the assessment says "version additive
  changes." The actual risk is that `manifest.json` is read by
  `internal/manifest/manifest.go:184 readLSManifest` and surfaced in
  `bakeoff ls` / `bakeoff show`. Adding fields requires updating those
  readers and their tests in lockstep. The assessment understates how many
  call sites must be touched to add a single telemetry field.
- **`escalatecmd/escalate.go` file size as a multiplier:** any change to
  witness/dispute/independent within a 1401-line file is high-merge-conflict
  surface, especially given the file's active history. Bundling Tighten
  Witness with other slice-2 items raises rebase pain.

---

## Sources

- `internal/workorder/workorder.go:401-432` — `validateProviders` enforces
  exactly two participants.
- `internal/workorder/workorder.go:1172-1208` — `ValidateEscalationWitnessResult`
  current array-typed shape (no per-item validation).
- `internal/provider/provider.go:27-34, 64-69` — `BackendSpec` definition and
  catalog; no Family field.
- `internal/decision/decision.go:23-115` — confirms `decision_kind`,
  `selection_basis`, `canonical_winner`, `judge_ran`, `judge_completed`,
  `stalled_at`, `judge_passes`, `caveats` fields.
- `internal/report/report.go:56,100,192,261,336` — outcome/decision-audit/
  judge-failure renderers and existing escalation render branches.
- `internal/commands/buildcmd/report.go:33,227,296` — selection_basis rendering
  in build reports.
- `internal/commands/escalatecmd/escalate.go:34-36` — three modes;
  `:247-251` — mode dispatch; `:727-728` — build source rejection.
- `internal/commands/reruncmd/rerun.go:55,76-80` — `--judge-only` flag and
  build rejection.
- `internal/commands/validatecmd/validate.go:185` — existing `min_runs` lint;
  file is 197 lines.
- `internal/artifact/artifact.go:517,584` — `WriteMeta` paths.
- `internal/manifest/manifest.go:46,108,184,318` — manifest build/write and
  escalation-aware fields.
- `internal/triage/state.go:97-168,217-238` — triage state detection (stale/
  failed/missing) and recommendation hooks.
- `skills/bakeoff-run/SKILL.md:169-184` — existing routing copy already maps
  audit/second-opinion/disputes to modes.

## Confidence: HIGH (~85%)

Specific code lines verified directly; the only items I did not deeply
inspect are `internal/prompt/...` (witness prompt builder) and
`internal/commands/doctorcmd/doctor.go` (third-party advisory output). Both
are referenced indirectly — the analysis depends on their existence and
general shape, not on specific line numbers. If the user wants those
verified to HIGH-confidence, request a follow-up spot-check.

## Status: COMPLETE
