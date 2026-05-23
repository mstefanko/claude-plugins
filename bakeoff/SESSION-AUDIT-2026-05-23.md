# Bakeoff Session Audit — 2026-05-23

Self-contained handoff for a new session. Everything below was observed in a
real Bakeoff run pair on 2026-05-23. No fixes have been applied yet.

## TL;DR

Two Bakeoff runs ran cleanly (exit 0, consensus). No wasted provider calls,
no retries, no orphaned worktrees. But the audit surfaced **two real
user-visible bugs**, **two structural observability issues**, **one validator
false positive**, **one repo-hygiene drift**, and **several UX template
issues** in how the assistant presented choices to the user.

Priority order for fixes is at the bottom of this file.

---

## Session Context

### What the user asked

> compare gate-first short-circuiting, safe verifier parallelism, and stronger
> cleanup/lock recovery behavior.

### What ran

**Run 1 — compare:** `runs/2026-05-23-e57e/`
- Work order: `bakeoff-orchestration-compare.work-order.json` (repo root)
- Type: `compare`
- Providers: `claude/sonnet` (mixed, high), `codex/gpt-5.5` (mixed, high)
- Judge: `claude/opus` (xhigh)
- Budget: 900s wall / 60 KB output / 60s heartbeat
- Result: exit 0, `consensus` (both providers converged on ship order 1 → 3 → 2)
- Provider wall times: claude 249.7s, codex 172.0s
- Judge passes: 61.9s + 58.5s

**Run 2 — escalate (dispute mode):** `runs/2026-05-23-95b9/`
- Source run: `2026-05-23-e57e`
- Added provider: `gemini/pro`
- Mode: `dispute`
- Result: exit 0, `escalation_advisory_supported`, `supports_source`, confidence `high`
- Provider wall time: gemini 92.9s
- 10 dispute points resolved, 0 unresolved, no new winner

### Substantive outcome (not part of the audit but useful background)

Both providers + escalation gemini agree on the implementation order:

1. **Gate-first verifier short-circuit** — small (~15-30 lines) change in
   `internal/buildverify/buildverify.go` around lines 114, 164-168, 562.
   Reordering is safe because the judge's `CompareMetrics` is ID-keyed
   (`buildverify.go:304-366`) and `VerifierSpec` has no dependency/ordering
   contract (`internal/workorder/workorder.go:141-150, 792-854`).
2. **Stronger cleanup / lock recovery** — incremental hardening on top of
   existing lock heartbeat + stale-pid detection at
   `internal/buildworkspace/buildworkspace.go:803, 826, 938` (tests at 276,
   295, 329). Worktrees are run-ID scoped (`buildworkspace.go:354`), so
   startup reconciliation is safe.
3. **Safe verifier parallelism** — *not* per-provider (already exists at
   `internal/commands/buildcmd/providers.go:28-34, 184, 202`). Must be
   per-verifier-within-candidate or cross-candidate, bounded.
   `providerCWD` is shared across verifiers (`providers.go:185`), so
   unconstrained parallelism risks filesystem collisions.

**Open implementation question gemini raised (D-006, material):** when
gate-first short-circuiting skips metrics, those entries disappear from
`result.Results`, changing artifact shape. Add an explicit skipped-metric
placeholder to preserve diagnostic richness before shipping Option 1.

---

## Issues Found

### A. Real bugs (user-visible)

#### A1. Go map literal leaking into dispute-mode escalation reports

**Severity:** High — affects every dispute-mode escalation.

**Evidence:** `runs/2026-05-23-95b9/report.md:37-52`. Each of the 10 resolved
dispute points renders as raw Go `fmt.Sprintf("%v", map)`:

```
- map[evidence:[] id:D-001 resolution:Not material. While a small signal-handling subset of Option 3 ...]
- map[evidence:[internal/commands/buildcmd/providers.go:28-34] id:D-002 resolution:Partially material ...]
```

**Root cause hypothesis:** A `map[string]any` (or similar) is being passed
into a template/printer that falls back to `%v` formatting instead of
rendering fields with labels.

**Fix:** Render each dispute point as labeled fields:

```markdown
- **D-002** — Partially material; supports source.
  *Resolution:* Code confirms per-provider concurrency is already implemented...
  *Evidence:* `internal/commands/buildcmd/providers.go:28-34`
```

**Where to look:** escalation report writer (likely under
`internal/report/` or wherever dispute-mode report assembly happens; search
for `map[` or `%v` rendering and `D-00` / `resolution` / `dispute`).

---

#### A2. `runs/latest` symlink is stale

**Severity:** Medium — silently misleads any tool or user assuming `latest`
points at the most recent run.

**Evidence:** After running run id `2026-05-23-e57e` (finished ~13:53Z) and
then `2026-05-23-95b9` (finished ~16:05Z), `runs/latest` still pointed at an
older run `2026-05-23-0aee`. Neither `compare` nor `escalate` updated the
symlink.

**Fix:** Either (a) update `runs/latest` on every successful run completion
across all subcommands (research, build, compare, escalate), or (b) document
clearly that `latest` is operator-managed and stop using it implicitly. The
skill already warns that `latest` is nondeterministic for parallel multi-lens
— extend that explicit handling.

**Where to look:** wherever the run directory is finalized post-success.
Likely `internal/runner/` or `internal/commands/*/run.go`. Audit each
subcommand independently — the bug pattern is "some subcommands update
latest, some don't."

---

### B. Structural observability issues

#### B1. Codex stderr is overwhelmingly noisy and masks real errors

**Severity:** Medium — wastes ~350KB per codex run and buries the only real
error line.

**Evidence:** `runs/2026-05-23-e57e/providers/codex/stderr.txt` is truncated
at exactly 60049 bytes from an observed 350578 bytes. The content is the
codex CLI echoing the **prompt + full transcript + final JSON** to stderr.
The same 60049-byte truncation appears in every recent codex run (`0aee`,
`1792`, `bb94`, `db11`, `e57e`, `fddc`).

The only actual error line buried inside is:

```
ERROR codex_core::session: failed to record rollout items: thread 019e5517-... not found
```

at 13:50:38 — a benign-looking rollout-recorder warning, but masked by ~349KB
of transcript noise.

**Fix:** Filter codex stderr before persistence. Keep only lines matching
`^\d{4}-\d{2}-\d{2}T.*\b(ERROR|WARN|FATAL)\b` plus initial/final process
metadata. Expected size reduction: 350KB → ~1KB. Surfaces real errors that
are currently invisible.

**Side-investigation:** Confirm whether the rollout-recorder ERROR has any
user-visible consequence (missing rollout artifact? recovered elsewhere?).
Search for `record rollout items` and `failed to record` in the codex
integration code.

**Where to look:** `internal/provider/` codex backend stderr capture, or
wherever provider stderr is written to disk.

---

#### B2. `quiet_tick_count` metric is mathematically odd

**Severity:** Low — observability-only, but the metric is either buggy or
misnamed.

**Evidence:** `runs/2026-05-23-e57e/decision.json:67-72`:

```
"quiet_tick_count": 3,
"quiet_threshold_seconds": 120,
```

Claude wall time was 249.7s. Three disjoint 120s quiet windows cannot fit in
249s. Either the counter is sliding-window (then the field name overstates
what it measures) or the increment logic is buggy.

Also: claude consistently hits the threshold; codex never does
(`quiet_tick_count: 0`). The threshold may be calibrated to codex's chattier
transcript output, not claude-sonnet's bursty cadence.

**Fix options:**
- Rename to `quiet_window_observations` (or similar) if it's a sliding count.
- Fix the increment to count disjoint windows.
- Apply per-backend defaults (claude needs a higher threshold; codex is fine).

**Where to look:** `internal/runner/` or wherever tick observation
accumulates. Search for `quiet_tick_count`, `quiet_threshold_seconds`.

---

### C. Validator false positive

#### C1. `bakeoff validate` flags prose tokens as path references

**Severity:** Low — advisory only, doesn't block runs, but creates user
friction every time a `foo/bar` token appears in `background` or `goal` prose.

**Evidence:** `bakeoff validate ./bakeoff-orchestration-compare.work-order.json`
emitted:

```
warning: background references "build/research" which does not exist under <context-root>
```

The literal source phrase was *"Bakeoff is a Go CLI that runs competitive
build/research work orders..."* (work order line 6) — a noun phrase, not a
path.

**Fix:** Tighten the path-detection content-scan to only match tokens in
fenced code blocks, backticks, or explicit path fields (`scope.paths`,
`build.protected_paths`, etc.). Free prose in `background`/`goal` should be
exempt.

**Where to look:** `internal/workorder/` validation or wherever `validate`
walks the work order looking for path-like strings.

---

### D. Repo hygiene

#### D1. 18 work-order files at repo root

**Severity:** Cosmetic — works, but pollutes `ls`.

**Evidence:** `ls bakeoff/*.work-order.json` returns 18 files at repo root.
No `work-orders/` directory exists.

**Fix:** Move existing work orders to `work-orders/`. Update any examples or
docs that imply repo-root as the convention. Optionally add a `.gitignore`
entry for repo-root `*.work-order.json` to discourage future drift.

---

#### D2. `ledger.jsonl` not produced

**Severity:** Unknown — needs code confirmation.

**Evidence:** Neither run dir contains `ledger.jsonl`. Manifests reference
only `decision`, `meta`, `report`, `work_order` artifacts. If `ledger.jsonl`
is expected by `/bakeoff:inspect` or any other tooling, this is a silent
missing-artifact bug. If it's an aspirational name that was never wired up,
it's noise in the skill copy.

**Where to look:** `internal/ledger/` and any caller. Confirm whether ledger
write happens, and whether consumers (`bakeoff inspect`, `bakeoff show`,
`bakeoff history`) require it.

---

### E. UX issues in assistant output templates

These are issues with the **`/bakeoff:run` skill / `bakeoff-run` skill**
prompt and routing templates, not Bakeoff CLI bugs. Fix them in
`skills/bakeoff-run/SKILL.md` and `references/run-appendix.md`.

#### E1. AskUserQuestion framing leaked context when offering escalation

**Severity:** Medium UX — user could approve a wrong-shape option.

**What happened:** User said *"Can we bring gemini in to do the analyze."*
The skill correctly routed to "this could be escalation," then asked:

> Question: How should Gemini fit into the analyze?
> - A. Gemini + Claude (drop Codex)
> - B. Gemini + Codex (drop Claude)
> - C. Escalate the compare instead — Run gemini as a third opinion over
>   the just-completed compare run 2026-05-23-e57e (independent / witness /
>   dispute mode) rather than a new analyze work order.

**Problems:**
- The framing question *"How should Gemini fit into the analyze?"* is false
  for Option C (escalation is not an analyze).
- Option C's load-bearing phrase *"rather than a new analyze work order"* is
  buried at the end.
- Option C introduces three undefined terms (independent/witness/dispute) at
  decision time.
- Labels mix grammatical forms — A/B are noun phrases ("Gemini + Claude"),
  C is a verb phrase ("Escalate the compare instead").

**Fix — replacement framing (ready to lift):**

> **Two ways to bring Gemini in.** You asked about analyze, but the compare
> just finished — so a third-opinion escalation is also on the table. Pick
> the shape:
>
> - **A. New analyze: Claude + Gemini** — fresh work order, drops Codex.
> - **B. New analyze: Codex + Gemini** — fresh work order, drops Claude.
> - **C. Escalate the compare with Gemini** — no new work order. Adds Gemini
>   as a third opinion over `2026-05-23-e57e`. Advisory only — does not
>   change the existing winner.

**Where to fix:** Provider-pair clarification rules in
`skills/bakeoff-run/SKILL.md`. Add an explicit template branch for the
"user-says-add-Gemini + just-finished-research-run" case so the framing
question acknowledges the redirect instead of pretending all three options
are the same shape.

---

#### E2. Inconsistent approval verbs across previews

**Severity:** Low UX, real consistency issue.

**Evidence:**
- Compare preview accepted: `yes` / `approve` / `run it` (three synonyms).
- Escalation preview accepted: `yes` / `run dispute` (one synonym + one
  mode-bound verb).
- Approval pattern for picking a non-recommended escalation mode was "tell
  me what to change" — asymmetric with the compare preview's three explicit
  verbs.

**Fix — replacement approval line for mode recommendations:**

> Reply `yes` to run `dispute`, or `run independent` / `run witness` to
> pick a different mode. `show` for full justifications.

**Where to fix:** mode-recommendation template in `bakeoff-run` skill /
appendix.

---

#### E3. Escalate-mode recommendation justifications were thin

**Severity:** Low UX.

**Observation:** The skill recommended `dispute` and listed `independent` /
`witness` with one-line justifications, but the alternatives didn't get
equal-weight rationales — the user had to trust the recommendation rather
than weigh modes side-by-side.

**Fix:** When recommending a mode, list **all three** with equal-shape
one-liners (when-to-use + cost), then put the recommendation on top with
"recommended:" prefix. Example:

> - **recommended: dispute** — focus only on contested sub-claims when
>   artifacts already show conflicts. Cost: 1 provider call.
> - **independent** — fresh third take, ignoring source providers. Cost:
>   1 provider call + 1 judge.
> - **witness** — broad sanity check of decision + judge. Cost: 1 provider
>   call.

---

## Fix Priority Order (recommended)

Rank by user-visible blast radius and effort:

| # | Issue | Severity | Effort | Notes |
|---|-------|----------|--------|-------|
| 1 | A1 — Go map literal leak in dispute reports | High | S | Affects every dispute escalation. Pure formatting fix. |
| 2 | A2 — `runs/latest` symlink staleness | Medium | S | Audit all subcommands; centralize symlink update. |
| 3 | B1 — Codex stderr noise filtering | Medium | M | Drops 350KB → 1KB; surfaces the buried rollout-recorder ERROR. |
| 4 | E1 — AskUserQuestion framing for "add Gemini" case | Medium UX | S | Skill template only; no Go changes. |
| 5 | C1 — Validator path-detection false positive | Low | S | Tighten scan to fenced code / explicit path fields. |
| 6 | B2 — `quiet_tick_count` metric semantics | Low | S | Either rename or fix counter. Decide which after reading the code. |
| 7 | D2 — `ledger.jsonl` missing | Unknown | ? | Confirm whether it's expected before fixing. |
| 8 | E2 + E3 — Approval verbs and mode-recommendation template | Low UX | S | Skill template only. |
| 9 | D1 — Move work orders to `work-orders/` | Cosmetic | S | Optional. |

## Files to Open First

- `internal/report/` (or wherever dispute-mode reports are assembled) for A1.
- `internal/runner/` and `internal/commands/*/run.go` for A2.
- `internal/provider/` (codex backend) for B1.
- `internal/runner/` tick accumulation for B2.
- `internal/workorder/` validation for C1.
- `skills/bakeoff-run/SKILL.md` and `references/run-appendix.md` for E1, E2, E3.

## What is *not* a bug

- Both runs exited 0 with the expected decision kinds.
- All three providers reported `final_json_source: "stdout"` — no
  recovery-from-non-JSON fallback fired anywhere.
- No orphaned worktrees, lock files, or partial cleanup leftovers under
  either run dir.
- Judge passes ran clean: 0 bytes stderr each, exit 0 both passes.
- Gemini escalation was tidy: 92.9s wall, 5668 bytes stdout, 316 bytes
  stderr (ripgrep-fallback + Node deprecation warning only).
- Provider wall-time imbalance (claude 250s vs codex 172s) is normal
  variance for `mixed` scope `high` effort — not a budget or scheduling
  problem.

---

*Generated from a Bakeoff session on 2026-05-23. Run ids referenced:
`2026-05-23-e57e` (compare), `2026-05-23-95b9` (escalate/dispute).*
