# Single-Provider Run Mode — Artifact-Contract Hardening Plan

**Date:** 2026-06-08
**Status:** investigation + fix plan (no code written yet)
**Scope:** `single_provider` run mode (recently added to bakeoff core)
**Repo root:** `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff`

This plan captures findings from a live Codex-only single-provider analyze run.
The core feature works; the items below are edge gaps a follow-up agent should
verify and then fix. **Verify each claim against source before changing code** —
the file:line anchors were accurate as of this date but may drift.

---

## Source run (evidence base)

Use this run to reproduce/inspect the artifacts the claims reference.

| Field | Value |
|---|---|
| Run id | `live-v2-single-provider-artifacts` |
| Run dir | `runs/live-v2-single-provider-artifacts/` |
| Work order | `live-v2-single-provider-artifacts.work-order.json` (repo root) |
| Type / run mode | `analyze` / `single_provider` |
| Provider | `codex` / `gpt-5.5`, scope `codebase`, effort `high` |
| Exit | `0` (clean) |
| Command | `bakeoff research ./live-v2-single-provider-artifacts.work-order.json --run-id live-v2-single-provider-artifacts` |
| Inspect | `bakeoff show live-v2-single-provider-artifacts` |
| Experiment | id=`bakeoff-live-runmode-v2`, task_id=`single-provider-artifact-contract`, condition_id=`codex-single-analyze`, run_kind=`single_agent_baseline`, repetition_index=1 |

**Artifacts present in run dir:** `decision.json`, `manifest.json`, `meta.json`,
`report.md`, `work-order.json`, `providers/codex/{final.json,last-message.txt,prompt.txt,status.json,stderr.txt,stdout.txt}`.
**Notably absent:** `summary.json` (see P1).

The full analyze report (with `R-NNN` rationale anchors) is at
`runs/live-v2-single-provider-artifacts/report.md`.

### Confirmed-correct baseline (do NOT "fix" these)

`decision.json` for this run is correct and is the reference shape:
`canonical_winner: null`, `single_provider: "codex"`,
`decision_kind: "single_provider_result"`, `selection_basis: "none"`,
`judge_ran/attempted/completed: false`. Code that is already correct:

- `internal/decision/decision.go` — `SingleProviderResult` / `SingleProviderFailed` emit the right fields.
- `internal/commands/researchcmd/run.go:174-182` — intentional `single_provider_result` vs degraded `single_provider_only` are kept distinct.
- `internal/workorder/workorder.go:471-493,589-599` — enforces exactly one provider and allows judge to share backend/model when `run_mode == single_provider`.
- `internal/report/report.go:288-296` — Outcome section renders "Result: single-provider result / failed" with no Winner wording.

---

## P1 — `summary.json` is named in the contract but never written

**Claim:** Docs list `summary.json` as a single-provider contract surface, but no
`summary.json` artifact is written for any run.

**Evidence:**
- Contract claims: `docs/work-orders.md:132`; implementation plan
  `docs/single-provider-run-mode-option-4-implementation-plan-2026-06-08.md:68,584`
  ("`manifest.json`, `summary.json`, `ls --json`, `show`, and `runs verify` must …").
- Code: `internal/commands/researchcmd/run.go:418-420` calls
  `summary.BuildResearch(...)` then `summary.Print(f.Streams().Out, value)` —
  stdout only, and only on the `--json` path. No `WriteFileAtomic` for a summary file.
- Live proof: `runs/live-v2-single-provider-artifacts/` contains no `summary.json`.

**Investigate:** Confirm there is no `summary.json` writer anywhere
(`grep -rn 'summary.json' internal/`), and confirm whether `summary.Print` is
gated behind `--json`. Determine whether downstream (`show`, `ls --json`,
`verify`) actually depend on a `summary.json` file or read `decision.json`/manifest.

**Fix decision (product call — do not assume):**
- Option A: write `summary.json` into the run dir from `summary.BuildResearch`, OR
- Option B: correct the docs to state the summary is stdout-only under `--json`
  and remove `summary.json` from the contract surfaces.

This is the only ship-blocker that needs a human decision before coding.

---

## P2 — Stale pairwise wording leaks into single-provider reports

**Claim:** Every report, including single-provider, prints the pairwise glossary
line about non-selected providers.

**Evidence:**
- `internal/report/report.go:54` — `Render` unconditionally appends `reportGlossary()`.
- `reportGlossary()` (~`report.go:1113-1118`) always emits:
  "Kept-from-nonwinner / additions-from-loser sections are material from the
  non-selected provider that the report preserved."
- Live proof: `runs/live-v2-single-provider-artifacts/report.md:6` contains this
  line despite there being no non-selected provider.

**Investigate:** Confirm `Render` has `decision`/`run_mode` in scope at line 54.
Check whether any single-provider report path legitimately needs the line.

**Fix:** Gate the kept-from-nonwinner glossary bullet on
`run_mode != "single_provider"` (or on `decision_kind`). Keep the `F-/R-/D-NNN`
bullet. Low-risk, cosmetic-but-contractual.

---

## P2 — `verify` does not assert single-provider semantics

**Claim:** `runs verify` never checks the single-provider invariants, so a
regression in `decision.json` would pass silently.

**Evidence:**
- `internal/verify/verify.go` — `dynamicRequiredArtifacts` returns `nil` for
  non-build types and otherwise keys off `selected_patch_provider` →
  `canonical_winner` (`verify.go:296`). `Run` only validates `schema_version`,
  `run_id`, artifact fingerprints, and triage.
- No assertion that, when `run_mode == "single_provider"`: `canonical_winner` is
  null, `single_provider` is set, `judge_ran == false`, and `decision_kind` is
  `single_provider_result`/`single_provider_failed`.

**Investigate:** Confirm `verify.Run` reads `decision.json` (it reads
`manifest.json` schema + fingerprints; check whether decision is loaded).
Decide whether semantic checks belong in `verify` or a dedicated validator.

**Fix:** When `run_mode == "single_provider"`, add semantic assertions to verify
(null winner, single_provider present, judge not run, decision_kind in the
single-provider set). Defense-in-depth against future regressions.

---

## P3 — Test gaps

**Claim / evidence:**
- `internal/summary/summary_test.go` has **no** assertions for `single_provider`
  or `run_mode` projection (current tests cover `stalled_at`, experiment,
  judge-only recommendations). This is the same summary code drifting in P1.
- `internal/verify/verify_test.go` mentions `single_provider` 3× but cannot test
  a contract that `verify` does not enforce — pairs with the P2 verify fix.
- Already well-covered (no action): `internal/decision/decision_test.go` (15),
  `internal/commands/researchcmd/run_test.go` (10),
  `internal/manifest/manifest_test.go` (9), `internal/workorder/workorder_test.go` (8).

**Fix:** Add summary projection tests for single-provider `run_mode`; add a
verify semantic-contract test alongside the P2 verify change.

---

## P3 — `bakeoff ls` human table cannot identify the provider

**Claim:** The `ls` table shows the decision kind but not which provider ran a
single-provider job.

**Evidence:**
- `internal/commands/lscmd/ls.go:204-216` — columns are
  `finished | run id | type | facet | decision | triage | summary`. The
  `decision` cell shows `single_provider_result` (distinguishable, good), but
  there is no `run_mode`/`single_provider` column.

**Investigate:** Confirm `ls --json` still surfaces `single_provider`/`run_mode`
from the manifest row (the doc at `docs/work-orders.md:132` claims it does). If
`--json` carries it, this is cosmetic only.

**Fix (optional):** Either surface the provider in the human table for
single-provider rows, or accept the `--json`-only behavior and leave a comment.

---

## Operational notes (not bugs)

- Codex emitted ~896 KB stderr, correctly truncated to 60 KB
  (`decision.json` → `stderr_truncated: true`, `stderr_kind: "diagnostic"`,
  `+816 KB` accounted in `stderr_observed_bytes`). The byte-cap accounting held
  under a noisy provider — good signal.
- Scope resolved `codebase → codebase (partial)` via `codex:sandbox=read-only` +
  `codex:disable=web_search`. Expected for Codex on a research/analyze run.

---

## Suggested sequencing

1. **P1 decision** (human): write `summary.json` vs. fix docs. Blocks summary tests.
2. **P2 verify** + **P2 glossary** (independent, low-risk).
3. **P3 tests** (after P1 decision and P2 verify land).
4. **P3 ls** (optional, after confirming `ls --json`).

P2 glossary and P2 verify can be done immediately and in parallel; they don't
depend on the P1 product decision.
