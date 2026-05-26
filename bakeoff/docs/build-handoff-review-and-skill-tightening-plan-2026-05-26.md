# Build-mode handoff review + run-skill tightening plan — 2026-05-26

## Run info

- **Run id:** `2026-05-26-afa3`
- **Mode:** `gather` + `facet.id: "code-review"`
- **Work order:** `build-handoff-semantics-review.work-order.json`
- **Run dir:** `runs/2026-05-26-afa3/`
- **Providers:** `claude/sonnet` (high, codebase) · `codex/gpt-5.5` (high, codebase)
- **Judge:** `claude/opus` (xhigh)
- **Budgets:** 900s wall · 60 KB out · 30s heartbeat
- **Triage:** auto (code-review default); `claude/opus` xhigh
- **Exit:** `0`
- **Decision kind:** `structured_union`; `canonical_winner: null` (expected for code-review research)
- **Provider statuses:** claude ok 168.8s / 11.0 KB · codex ok 147.8s / 12.0 KB
- **Judge status:** ok 121.5s
- **Triage outcome:** 26 source findings → 20 `false_positive` (`ignore`), 6 `evidence_gap` (5 `defer`, 1 `reproduce`), 0 `real_issue`, 0 `needs_repro`, **0 `fix_now`**

### Question reviewed

Three build-mode handoff invariants:

1. Selected patch paths (`providers/<winner>/build/diff.patch`) must appear only when `decision.json.canonical_winner` is non-null.
2. Build runs with exit `3` (unresolved disagreement) or exit `4` (decision-incomplete / judge failed) must not imply a patch is safe.
3. Build output (Go code and skill text) must never recommend `bakeoff rerun --judge-only` — judge-only rerun is research-only.

### Verdict on the invariants

Triage confirmed all three hold across the audited surfaces:

- `internal/commands/buildcmd/{decision.go,summary.go,report.go,run.go,run_test.go}`
- `internal/decision/decision.go`, `internal/summary/summary.go`, `internal/report/report.go`
- `internal/commands/reruncmd/rerun.go`
- `internal/manifest/manifest.go` (selected-patch path derivation)
- `skills/bakeoff-run/SKILL.md`, `skills/bakeoff/SKILL.md`

Zero confirmed violations. Six evidence-gap items remain in `runs/2026-05-26-afa3/triage/triage.md` — none are flagged as real regressions; review them only if a substantive doubt arises.

---

## What we investigated post-run

The run itself was clean. A separate question came up about **drafting friction**: validation failed once before the run launched, with `facet.include must be an array of strings`. We investigated whether the skill text and the validator agree on the shape, and whether other warnings during validation pointed to additional tightening opportunities.

### Probes

- `skills/bakeoff-run/SKILL.md` lines 237-240 and 425-428 — the only two spots that mention `facet.include` / `facet.exclude`.
- `examples/review.work-order.json` — the canonical code-review facet example.
- `internal/workorder/workorder.go:114-115, 481, 1417` — Go struct definition + validation call site + error message.
- `internal/commands/validatecmd/validate.go:174-206` — origin of the `does not exist under <context-root>` warning that fired on the `background` field.

---

## Issues identified

### Issue 1 (real) — skill prose understates `facet.include` / `facet.exclude` shape

**Skill text** (`skills/bakeoff-run/SKILL.md:237-240`):

> "For code-review facets, use `facet.kind: "generic"` and write `facet.focus` as one string of 500 characters or fewer with no backticks, angle brackets, or `</facet>`; write `facet.include` / `facet.exclude` as descriptive criteria, not path globs."

**Validator contract** (`internal/workorder/workorder.go`):

```go
// lines 114-115
Include []string `json:"include"`
Exclude []string `json:"exclude,omitempty"`

// line 481
include, err := validateFacetStringList(obj["include"], "facet.include", 1, 8)

// line 1417 (error path)
return nil, Validationf("%s must be an array of strings", label)
```

**Why this misled the drafter:** the prose sits on the same line as the `focus` shape rule ("one string of 500 characters or fewer") and only says what `include`/`exclude` should *not* be ("not path globs"). It never says it must be an array, and never states the 1-8 cardinality. The example file shows the array shape, but top-down readers don't reach the example before drafting, so the prose is the contract that bites.

**Symptom in this session:** initial draft had `"include": "Build command summary..."` and `"exclude": "Research-only paths..."` as strings. `bakeoff validate` rejected with exit 2 before launch. One round-trip lost to a repair edit.

**Impact level:** drafting friction only. Validator caught it correctly. No risk to run safety.

### Issue 2 (non-issue, documenting for context) — advisory `background` path warning

`bakeoff validate` printed:

```
warning: background references "/build/diff.patch" which does not exist under <context-root>
```

This came from `internal/commands/validatecmd/validate.go:206`, which scans `background` for path-like tokens and warns when the literal token is absent on disk. The work order's `background` legitimately described the literal artifact path `providers/<id>/build/diff.patch`, which tokenized to `/build/diff.patch` — not a real file.

**Action:** none. The skill already covers this at the appropriate level: "Validation warnings are advisory when validation exits successfully." The warning is doing its job (catching typos in path references). Adding skill prose to pre-empt the warning would add words without changing safety.

### Issue 3 (non-issue, documenting for context) — judge family advisory

Doctor and validator both flagged that the `claude/opus` judge shares the Anthropic family with the `claude/sonnet` provider (`judge_family_advisory.relation: "same_as_some"`, ready non-contestant peers: `gemini`, `copilot`). Skill preview correctly surfaced the advisory inline. Run completed cleanly. No action.

---

## Proposed fix

### Edit 1 (only edit) — tighten `facet.include` / `facet.exclude` shape in the skill

**File:** `skills/bakeoff-run/SKILL.md`
**Lines:** 237-240

**Before:**

> For code-review facets, use `facet.kind: "generic"` and write `facet.focus` as one string of 500 characters or fewer with no backticks, angle brackets, or `</facet>`; write `facet.include` / `facet.exclude` as descriptive criteria, not path globs. Use `examples/review.work-order.json` as the code-review facet example.

**After:**

> For code-review facets, use `facet.kind: "generic"` and write `facet.focus` as one string of 500 characters or fewer with no backticks, angle brackets, or `</facet>`; write `facet.include` and `facet.exclude` as JSON arrays of 1-8 short descriptive criteria strings (the validator requires `[]string` with cardinality 1-8; do not collapse to a single string and do not use path globs). Use `examples/review.work-order.json` as the code-review facet example.

**Why this wording:**

- States the JSON shape inline (`JSON arrays of ... strings`) so top-down readers cannot mistake it for a single string.
- Names the exact cardinality the validator enforces (1-8), matching `internal/workorder/workorder.go:481`.
- Preserves the existing "not path globs" guidance — that constraint is still correct.
- Adds no new contract; only makes the existing one explicit.

**Why not more edits:**

- The other reference (`skills/bakeoff-run/SKILL.md:425-428` under multi-lens) names the same fields but makes no shape claim, so no edit is needed there. Multi-lens drafts inherit the corrected rule from the single-work-order section.
- The example file already encodes the right shape and need not change.
- The validator error message is already clear (`"facet.include must be an array of strings"`); the failure mode was a drafting-prompt gap, not a CLI UX gap.

### Acceptance criteria

- The two-line edit at `skills/bakeoff-run/SKILL.md:237-240` lands as shown above.
- A future drafter reading the skill top-down cannot reasonably read `facet.include` as a single string.
- No change in CLI behavior; no test changes required.
- This file (`docs/build-handoff-review-and-skill-tightening-plan-2026-05-26.md`) ships alongside the edit so the rationale survives.

### Out of scope

- Editing the validator error wording.
- Adding new background-path validator behavior.
- Swapping the judge to a non-contestant backend by default.
- Any code change in `internal/commands/buildcmd/*`, `internal/decision/*`, `internal/report/*`, `internal/summary/*`, or `internal/commands/reruncmd/*` — triage confirmed the three handoff invariants already hold there.

---

## Artifacts

- Run dir: `runs/2026-05-26-afa3/`
- Report: `runs/2026-05-26-afa3/report.md`
- Triage: `runs/2026-05-26-afa3/triage/triage.md`
- Decision: `runs/2026-05-26-afa3/decision.json`
- Manifest: `runs/2026-05-26-afa3/manifest.json`
- Work order: `build-handoff-semantics-review.work-order.json`
- Inspect: `bakeoff show 2026-05-26-afa3 --triage`
