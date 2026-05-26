# Dogfood: metric-lint — UX & Hardening Report

## Run info

- **Invocation:** `/bakeoff:run build a performance bakeoff for internal/manifest.RowForLS using a repo-local benchmark metric, but first identify whether a stable benchmark harness and protected fixture paths exist. Acceptance criteria: no metric verifier should run unless its command, min_delta_percent, noise_floor_percent, min_runs, and protected_paths are explicit. --run-id dogfood-metric-lint`
- **Run id:** `dogfood-metric-lint`
- **Date:** 2026-05-24
- **Repo:** `mstefanko-plugins/bakeoff` (plugin source repo — this is dogfood of the plugin against itself)
- **Base ref:** `main` @ `81c636115e3e`
- **Toolchain:** Go 1.24.4 darwin/arm64
- **Outcome:** stopped before draft. No work-order file written. No `bakeoff validate` run. No providers launched. `runs/dogfood-metric-lint/` never created.
- **Stop reason:** discovery pass found zero `Benchmark*` functions in `internal/manifest`, no fixture/golden dirs, no Makefile bench target — user's AC required explicit `metric.command` and `metric.protected_paths` which could not be grounded.

The lint behavior was substantively correct. This report covers drift from the SKILL contract and gaps in CLI enforcement that the dogfood exposed.

---

## 1. UX drift (skill compliance)

### 1.1 Invented choice labels instead of prescribed repair menu

**Where:** Claude's final response presented three options labeled:
1. "Author the harness first, then re-invoke `/bakeoff:run`..."
2. "`draft anyway`..."
3. "Reframe as a non-metric build..."

**What the skill prescribes** (`skills/bakeoff-run/SKILL.md:246` and `skills/bakeoff-run/references/run-appendix.md:13-22`):

> Combine the warning with missing-field choices when both apply:
> `inspect <run-id>`, `draft anyway`, or `provide fields`.

**Impact:** Only option 2 used the prescribed verb. Options 1 and 3 are freeform paraphrases that don't match the accept-token grammar the rest of the skill enforces. Users learning the system can't transfer the verbs across runs.

**Fix:** Replace the menu with the prescribed three tokens. Even when only missing-field applies (not task-fit), the verb set should still be `inspect <run-id>` / `draft anyway` / `provide fields`. The "reframe as non-metric build" suggestion can stay, but as one sentence above the menu, not as a numbered choice.

### 1.2 Misapplied `Why this loop:` route-advisor line

**Where:** Claude emitted `Why this loop: single-agent advised`.

**What the skill prescribes** (`skills/bakeoff-run/SKILL.md:242`): that line is the prescribed route-advisor for **weak task-fit**. This stop was not weak task-fit — it was missing required fields. The skill says to combine the task-fit warning with the missing-field menu only when **both** apply.

**Impact:** Mislabels the stop reason. A user reading "single-agent advised" might conclude Bakeoff is the wrong tool for the request, when really the request is fine — the prerequisites just don't exist yet.

**Fix:** Drop the `Why this loop:` line entirely when only missing-fields apply. Reserve it for explicit task-fit weakness.

### 1.3 Persona refusal where rule citation belongs

**Where:** In option 2 Claude wrote "I will not synthesize them."

**What the skill prescribes** (`skills/bakeoff-run/SKILL.md:243`):

> `draft anyway` clears only the task-fit or duplicate-work warning for the current turn and does not waive required fields.

**Impact:** Conflates Claude's voice with the skill rule. A user might think they can argue with the persona; the rule itself is the gate.

**Fix:** Replace with:
> `draft anyway` does not waive required fields — you must still supply `metric.command`, `metric.protected_paths`, `min_delta_percent`, `noise_floor_percent`, and `min_runs` explicitly.

### 1.4 What the response got right (keep)

- **Discovery table altitude.** Seven rows, one per AC field, directly answering the user's "first identify whether" clause. Right density, no narrative bloat.
- **Hold note on `--run-id`.** Final line `--run-id dogfood-metric-lint is held; nothing has been written or validated.` is exactly the right tone.
- **No `Write` before approval.** Invariant honored.
- **No provider CLI calls.** Invariant honored.

---

## 2. Hardening (CLI under-enforces what the AC asked for)

The user's AC was *"no metric verifier should run unless its command, min_delta_percent, noise_floor_percent, min_runs, and protected_paths are explicit."* The CLI today does not enforce all five at validation time — the gate has to be the skill, which is fragile.

### 2.1 Promote `protected_paths` empty-check from warning to error

**File:** `internal/commands/validatecmd/validate.go:186`

**Current:** When a metric verifier runs a repo-relative command with empty `build.protected_paths`, validation emits a warning. The work order still passes `bakeoff validate` and a future drafting agent could push it through.

**Change:** Promote to a hard error (or gate behind a `--strict` flag default-on). This is the single highest-leverage fix exposed by this run — it closes the exact loophole the dogfood targeted.

**Acceptance:** a metric-verifier work order with `metric.protected_paths: []` should fail `bakeoff validate` with a non-zero exit and an actionable message naming the verifier and the empty field.

### 2.2 Enforce `metric.min_runs >= 2` when `noise_floor_percent` is set

**File:** `internal/workorder/workorder.go:906-919`; matching warning at `internal/commands/validatecmd/validate.go:193-195`.

**Current:** `metric.min_runs` is accepted at any positive value; `noise_floor_percent` is accepted without `min_runs` at all. SKILL.md:298-299 only says "prefer."

**Change:** When `noise_floor_percent` is non-zero, require `min_runs >= 2`. A noise floor with a single run is statistically meaningless; tolerating it lets providers ship deceptive metrics.

**Acceptance:** validation fails on `noise_floor_percent: 5` paired with `min_runs: 1` (or unset).

### 2.3 Stat-check `protected_paths` and verifier `argv[0]`

**File:** `internal/commands/draftbuildcmd/draft_build.go:21, 68, 86`

**Current:** `--protected-path` arguments and verifier `argv[0]` (when repo-relative) are accepted verbatim with no filesystem existence check. A draft can name `internal/manifest/testdata/rowforls/minimal.json` that doesn't exist; the work order validates fine and only fails at run time.

**Change:** Stat-check each `protected_paths` entry and each repo-relative verifier path at draft-build time. Fail fast with a path-doesn't-exist error.

**Acceptance:** `bakeoff draft-build --protected-path internal/manifest/nope/missing.json ...` exits non-zero with an explicit "path does not exist" message.

### 2.4 Enumerate metric drafting hard-stops in SKILL.md

**File:** `skills/bakeoff-run/SKILL.md:222`

**Current:** Says metric verifier drafts "still use careful manual drafting" but does not enumerate stop conditions.

**Change:** Add a bulleted hard-stop list:
> Stop before drafting a metric verifier when ANY of these are true:
> - No `Benchmark*` (or equivalent) function exists in the target package or any path the verifier `argv` could invoke.
> - No fixture/golden/testdata directory exists that the verifier reads from.
> - No candidate `protected_paths` are discoverable (fixtures, goldens, harness file).
>
> Repair: ask the user to author the harness first, then re-invoke.

This codifies what the dogfood run improvised correctly. Future drafting agents shouldn't have to intuit it.

### 2.5 Clarify whether `bakeoff doctor --json` runs before a discovery stop

**File:** `skills/bakeoff-run/SKILL.md:149-151`

**Current:** "Run `bakeoff doctor --json --quiet --skip-auth-probe` once after CLI preflight when drafting from natural language and the user did not explicitly choose providers." Ambiguous whether this precedes repo-discoverability classification.

The dogfood run skipped doctor because the stop was already forced. That was a defensible choice but cost the user one round-trip's worth of information — if providers were also broken, the user would discover that on the next attempt.

**Change:** Add one sentence:
> Run doctor before any discovery-driven stop so the stop summary can also surface provider readiness in a single round-trip.

**Acceptance:** the prose makes it explicit so future drafts don't re-litigate the ordering.

### 2.6 Document Bash fallback for missing context-mode MCP tools

**File:** `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/CLAUDE.md`

**Current:** The CLAUDE.md mandates `ctx_batch_execute` / `ctx_execute` / `ctx_search` and says inline HTTP / `curl` / `wget` are blocked. It does not say what to do when those MCP tools are not loaded — which happened in this run. `ToolSearch` returned no matches for `mcp__plugin_context-mode_context-mode__ctx_batch_execute` etc.

The dogfood run improvised correctly: one batched `bash -lc` invocation with bounded output, piped through `head -200`. That is the right fallback, but it's not written down.

**Change:** Add a short paragraph to the CLAUDE.md routing rules:

> **Fallback when context-mode MCP tools are not loaded.** If `ToolSearch` cannot find `mcp__plugin_context-mode_context-mode__ctx_batch_execute`, fall back to a single multi-command `bash -lc '...; ...; ...'` invocation with `head -N` output bounding. Do NOT issue sequential per-probe `Bash` / `Read` / `Grep` calls — the one-batched-pass invariant still applies.

**Acceptance:** the contract violation classification in the skill recognizes the fallback as a one-batched-pass equivalent.

---

## 3. Priority order

If you only do two things, do these:

1. **§2.1** — promote `protected_paths` empty-check to error in `validate.go:186`. One change closes the exact loophole the dogfood targeted.
2. **§1.1 + §1.2 + §1.3** — fix the UX menu / route-advisor line / persona refusal in the skill drafting prose so future stops use prescribed verbs and the right route-advisor.

§2.2 - §2.6 are smaller wins worth bundling but not blocking.

## 4. Out of scope for this report

- Whether `RowForLS` is actually worth benchmarking. Covered in the actionable-items report.
- Provider-pair selection. Doctor was not consulted; no provider drift to evaluate.
- Triage / escalation behavior. No run launched, no artifacts to triage.
