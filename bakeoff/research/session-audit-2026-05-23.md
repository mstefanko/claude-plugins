# Bakeoff session audit — 2026-05-23

A `/bakeoff:run` session reviewing whether three Bakeoff subsystems
(capability cache invalidation, transient-failure handling, required-scope
semantics) are "strong enough" surfaced six tighten-able issues across the
Bakeoff CLI, the `/bakeoff:run` skill, and the assistant's framing. This
document captures the runs, the failures, and the fix candidates so the next
session can start from the file.

## Original session goal

User invoked:

```
/bakeoff:run research/review whether capability cache invalidation,
  transient-failure handling, and required-scope semantics are strong enough.
```

Classified as `gather` + `facet.id: code-review`, single normal review (not
multi-lens — user did not ask for separate lenses).

Work order written to:
`./bakeoff-robustness-review.work-order.json` (repo root of the bakeoff plugin).

## Run inventory

| Run id | Type | Status | Provider time | Outcome |
|---|---|---|---|---|
| `2026-05-23-fddc` | initial bake | providers ok, judge ok, **triage failed** | claude 300s + codex 192s + judge 163s | 31 raw findings, exit 1 due to triage |
| `2026-05-23-276a` | witness escalation (gemini) | ok | gemini 23s + triage ~120s | 0 items, 0 fix-now |
| `2026-05-23-b6f3` | dispute escalation (gemini) | `ok_after_format_retry` | gemini 243s + triage ~120s | 0 items, 0 fix-now |
| `2026-05-23-fddc` retry (triage --force) | triage-only | **ok** | claude/opus 180s | **31 items, 11 fix-now** |

Total provider-seconds ≈ 25-26 min for an answer that would have taken
~14 min (initial bake + one triage retry). Net waste: ~10-12 min on Gemini
escalations that could not address the failed-triage problem.

Artifact paths (preserve exact paths; do not assume `runs/<id>` if a custom
`--out` was used — none was here, so `runs/` is correct):

- `runs/2026-05-23-fddc/report.md` — original 31-finding report
- `runs/2026-05-23-fddc/triage/triage.md` — verified verdicts (after retry)
- `runs/2026-05-23-fddc/triage/final.json` — structured triage with
  classifications, confidences, supporting evidence
- `runs/2026-05-23-fddc/triage/source_finding_filter.json`
- `runs/2026-05-23-276a/report.md` — witness escalation
- `runs/2026-05-23-b6f3/report.md` — dispute escalation

Inspect quickly with:

```
bakeoff show 2026-05-23-fddc --triage
bakeoff show 2026-05-23-276a
bakeoff show 2026-05-23-b6f3
```

## Did the final answer have value?

Yes. Sampled triage item F-001 from `runs/2026-05-23-fddc/triage/final.json`:

```
classification:       real_issue
confidence:           high
recommended_action:   fix_now
source_finding:       Transient probe failures are permanently cached:
                      probeScopeCapabilities returns Available:false with
                      ProbeError on any error; getOrProbe stores
                      unconditionally with no eviction.
supporting_evidence:  internal/provider/provider.go:277-285,
                      internal/provider/provider.go:256-275
```

11 such fix-now items exist across the three target subsystems. The two
Gemini escalations returned `escalation_advisory_supported` and **did not
contradict** the original report — mild cross-provider corroboration that
the report's overall verdicts are defensible.

The robustness question is answered. The fixes below are about the *runway*
(CLI, skill, assistant) that produced the answer, not the findings themselves.

## What went wrong (in event order)

### 1. Drafting validation miss

First `bakeoff validate` rejected the work order:
`error: providers[0].id is required`. Three schema-drift issues in the
generated draft:

1. `providers[]` were missing the `id` field (which serves as the run-time
   handle in `[claude]`/`[codex]` log lines).
2. `budgets` used `wall_seconds` and `output_bytes` — the canonical field
   names from `examples/review.work-order.json` are `wall_clock_seconds`,
   `max_output_bytes`, `heartbeat_seconds`, `output_cap_grace_seconds`,
   `max_output_overrun_bytes`.
3. `facet.include` and `facet.exclude` initially held file path globs;
   examples treat them as descriptive criteria. (Also missing
   `facet.kind: "generic"`.)

Cost: one extra Write + one re-Validate. Cheap, but a wasted round-trip the
skill should prevent. Skill text already says "copy field names from
`examples/*.work-order.json`" — but the assistant's mental skeleton drifted.

### 2. Triage failure looked like a CLI bug, not a provider hiccup

Heartbeat trace of the failed first triage:

```
[triage] running t=60s/900s out=0.0KB err=0.0KB last=60s
[triage] quiet   t=120s/900s out=0.0KB err=0.0KB last=120s
triage failed: exit_error
```

Zero stdout and zero stderr for 120 seconds, then the process terminates and
is classified as generic `exit_error`. Compare to `ClassifyFailure` cases in
`internal/runner/classify.go`: this pattern is the classic "wedged provider"
shape — should arguably be `timeout` or a new `wedged_no_output` class. The
session's own subject (transient-failure classification) caught its own
session in the act.

### 3. `triage --force` deleted the failure forensics

`bakeoff triage 2026-05-23-fddc --force` per `--help` "replaces an existing
triage directory". After the retry succeeded, the original `triage/status.json`
and `stderr.txt` (such as they were) are gone. We cannot now confirm whether
the first failure was a true wedge, a misclassified timeout, or something
else. `--force` should preserve the prior failed run as
`triage.failed-<timestamp>/` before clobbering.

### 4. Wrong-mode escalation recommended first

User asked at Turn 6: "Can we bring in gemini to only do the triage pass."
Assistant offered **witness** as "the closest fit" at Turn 7.

Per the skill's own rules:

- `witness` — broad sanity check of the report, decision, judge passes, **or
  triage**.
- `dispute` — focus only on contested points: "ties, conflicts, unknowns,
  judge caveats, kept-from-nonwinner material, **or triage gaps**".

A failed triage IS a triage gap — textbook `dispute`. The skill rules
support dispute as the first recommendation in this exact situation; the
assistant routed to witness on the strength of "audit-shaped" framing.

Compounding miss: even `dispute` would not have addressed the failed-triage
problem. Escalation triage operates on the *escalation provider's new
findings*, not on the source-run's 31 unverified findings. The right answer
was always `bakeoff triage --force`. The skill should disclose this
escalation/triage scope split when recommending escalation as a response to
a triage failure, and should down-rank escalation entirely for that scenario.

### 5. Turn-5 diagnostic content was thin

When the initial run came back with the triage failure, the assistant's
report card had:

- `triage: failed (exit_error)` — no stderr excerpt
- One recommended next step: `bakeoff triage --force` with a brief note
  ("stderr/status would show why it errored")

What it lacked:

- A `cat runs/<id>/triage/status.json` excerpt or a `tail -20 stderr.txt`
- A clear "this is most likely transient — retrying is cheap and usually
  works" framing
- A note that triage failure does **not** invalidate the report; the 31
  findings are there, just unverified

User then asked about Gemini at Turn 6 — partly because the report card
didn't make `--force` feel like the obvious cheap-first path.

### 6. Approval vocabulary drift

- Turn 2 preview accepted: `yes`, `approve`, `run it`
- Turn 9 (witness preview) asked for: `approve witness` (or `yes`, `run it`)
- Turn 13 (dispute preview) asked for: `approve dispute`

Three different keywords for the same gesture. The skill enumerates strict
approval phrases for multi-file split/multi-lens; for single escalations the
rule is ambiguous. Tightening: `yes` should always work; mode-specific
tokens are optional aliases shown in the preview, not required.

### 7. Repetition in Turns 11 and 14

The same "31 findings still unverified per-finding" caveat appears twice,
followed by the same three-bullet "next steps" list (read source report,
`triage --force`, run dispute). By Turn 14 the user has heard `--force` as
option 2/3 twice without it being elevated as the obvious answer.

### 8. Stub sentence in Turn 11

Literal text from Turn 11: "Both Gemini escalations would..." — the
sentence trails off and gets restarted mid-paragraph. A final-pass linter on
assistant output would catch this. Credibility hit when it slips through.

### 9. Mental-model leak in escalation dry-run previews

The Turn 9 witness preview shows: mode, provider, cost, triage state. It
does **not** disclose what the mode actually verifies and does not verify.
User did not learn until Turn 11 (after running) that witness is "a sanity
check on conclusions, not item-by-item verification." That information
belongs in the dry-run preview, not the post-run summary.

## Fix candidates

Each candidate is a one-shot, scoped change suitable for a beads issue.

### CLI: bakeoff

- **CLI-1 — Classify zero-byte termination as wedge/timeout, not
  `exit_error`.** In `internal/runner/classify.go`, when a provider process
  exits non-zero with `stdout_bytes == 0 && stderr_bytes == 0 && wall_seconds
  > <heartbeat * N>`, return a dedicated class (`wedged_no_output` or fold
  into `timeout` if the runner's deadline expired). Surface that class in
  the heartbeat tail so the CLI prints "triage timed out: no provider
  output" instead of generic `exit_error`. Cross-reference: this is exactly
  the kind of transient-classification gap the F-001 finding flags.

- **CLI-2 — `triage --force` archives prior triage dir.** Before replacing
  `<run>/triage/`, move it to `<run>/triage.failed-<RFC3339>/`. Add a
  user-visible "archived prior triage to ..." line. Keeps forensics for
  debugging future failures without preventing retries.

- **CLI-3 — `bakeoff show` triage-failed run cards include stderr tail.**
  When `triage/status.json` shows non-`ok` status, embed the last ~20 lines
  of `stderr.txt` (or "no stderr captured" if empty) in the report card.

### Skill: bakeoff-run drafting

- **SKILL-1 — Canonical work-order field names.** Reinforce in the skill
  body (not just "copy from examples"): `providers[].id` is required;
  `budgets` keys are `wall_clock_seconds`, `max_output_bytes`,
  `heartbeat_seconds`, `output_cap_grace_seconds`,
  `max_output_overrun_bytes`; `facet.include`/`facet.exclude` are
  descriptive criteria, not paths; include `facet.kind: "generic"` for
  code-review. Treat these as explicit drafting checklist items so the
  assistant doesn't drift from the example shape.

### Skill: bakeoff-run escalation router

- **SKILL-2 — Route "triage gap / failed triage / re-run triage" to
  `bakeoff triage --force` first, not escalation.** When the source run has
  a failed or missing triage, the first recommendation should always be
  `bakeoff triage <id> --force`. Escalation is a fallback when the retry
  also fails or when the user wants a different provider's *opinion on the
  report*, not when they want per-finding verification of source findings.

- **SKILL-3 — When escalation IS appropriate, map user intent to mode more
  precisely.** Phrases mentioning triage, verification, or "is this
  finding real" → `dispute`. Phrases mentioning "is the conclusion sound /
  sanity check the report" → `witness`. Phrases mentioning "fresh
  independent answer / second opinion / third take" → `independent`.
  Always state in the dry-run preview, in one line, what the mode does
  **and does not** verify, before approval. Specifically call out that
  escalation triage operates on the escalation provider's new findings,
  not the source run's findings.

### Skill: bakeoff-run output framing

- **SKILL-4 — Triage-failure report card template.** Standard layout when
  triage fails on an otherwise-successful run:
  1. Run table (with `triage: failed (<class>)`)
  2. stderr tail (or "no stderr captured")
  3. Caveat line: "Report is durable; only triage failed. 31 findings are
     present but unverified."
  4. Primary recommendation: `bakeoff triage <id> --force` with
     one-sentence why ("retry — first failure is most often transient").
  5. Secondary options under a `<details>` or "Other options" sub-bullet,
     not a sibling-weight bullet list.

- **SKILL-5 — Approval vocabulary.** Single rule: `yes`, `approve`, and
  `run it` are accepted for every preview, single or multi. Mode-specific
  aliases (`approve witness`) are optional and shown only as "or" alongside
  the base set. Do not require mode-specific tokens.

- **SKILL-6 — De-duplicate session-level caveats.** State "findings are
  unverified per-finding until triage runs" **once** per session and refer
  back to it. Repeating it on every escalation summary trains the user to
  scroll past it.

- **SKILL-7 — Final-pass assistant output check.** Lightweight self-review
  before emitting: no half-finished sentences, no internal phrase markers,
  no contradictions between header and body. Catches stubs like "Both
  Gemini escalations would…".

## Beads issue stubs

Recommended priorities (0=critical, 4=backlog) and types in parens. Convert
in a new session with `bd create`:

| Pri | Type | Title |
|---|---|---|
| 2 | bug | CLI-1 — Classify zero-output triage termination as timeout/wedge, not exit_error |
| 2 | bug | CLI-2 — `triage --force` should archive prior triage dir as triage.failed-<ts>/ |
| 3 | feature | CLI-3 — `bakeoff show` includes stderr tail when triage failed |
| 2 | task | SKILL-1 — Document required work-order field names in bakeoff-run skill |
| 2 | task | SKILL-2 — Escalation router: recommend `triage --force` first on triage gaps |
| 2 | task | SKILL-3 — Escalation mode mapping + dry-run preview discloses scope limits |
| 2 | task | SKILL-4 — Standard triage-failure report card template |
| 3 | task | SKILL-5 — Normalize approval vocabulary (`yes` always accepted) |
| 3 | task | SKILL-6 — De-duplicate session-level caveats |
| 3 | task | SKILL-7 — Final-pass output check (catch stubs, contradictions) |

## Verification commands for the next session

```bash
# Confirm the runs still exist
ls runs/2026-05-23-fddc runs/2026-05-23-276a runs/2026-05-23-b6f3

# Spot-check the F-001 evidence cited by triage
sed -n '256,285p' internal/provider/provider.go

# Read the verified triage verdicts
bakeoff show 2026-05-23-fddc --triage

# Confirm escalation reports really did contain zero new disputes
bakeoff show 2026-05-23-276a
bakeoff show 2026-05-23-b6f3

# Inspect the triage classifier code that needs CLI-1
sed -n '1,160p' internal/runner/classify.go
```

## Open questions worth probing in the next session

1. Is the `exit_error` classification of zero-byte termination a true bug in
   `ClassifyFailure`, or is it the runner that picks the class before
   `ClassifyFailure` ever sees it? (Look at call sites of
   `StatusTimeout` / `StatusOutputCap` and what sets `status` for triage
   children.)
2. Does the escalation-triage scope (escalation-provider findings only)
   match user intent in any realistic case, or is it always a UX
   mismatch? If always, the skill should never offer escalation triage as
   an answer to "is finding X real".
3. Should `bakeoff triage` accept `--provider`/`--judge-override`? The
   user asked exactly this. Today the only way to swap is to edit the
   work order and re-bake. A targeted override would have ended the
   session's confusion in one command.
