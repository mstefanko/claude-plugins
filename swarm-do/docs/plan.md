# Swarm-do — canonical plan

**Canonical location:** `mstefanko-plugins/swarm-do/docs/plan.md` (this file).
**Merged on:** 2026-04-23 from two former plans:
- `~/.claude/plans/codex-swarm-integration.md` (policy, rollout, measurement intent)
- `~/cartledger/PLAN-swarm-plugin.md` (packaging, plugin layout, implementation phases)

Both former files are now stubs pointing here. This file is the single source of truth.

---

## Structure

- **Part 1 — Architecture & Policy** — what the swarm is and how it routes work (§1.1–§1.11)
- **Part 2 — Rollout strategy** — Phase 0 → Phase 1 → Phase 2 → B1 dispatcher (§2.1–§2.7)
- **Part 3 — Packaging history (archived)** — stub only; full content lives at `docs/history/packaging.md`. Not part of the runnable scope.
- **Part 4 — Implementation phases — mostly shipped** — Phases 9/10/11 with sub-phases 9a–11g (telemetry, presets, TUI). This is what `/swarm-do:do` runs; remaining work is follow-up hardening and TUI completeness.
- **Part 5 — Replaceability + non-goals** — layer-swap discipline, rollout state file schema, non-goals
- **Appendix** — ADRs, schemas, backups (under `docs/adr/` once Phase 9g / 10f ship)

---

## Swarm-do execution scope (orchestrator directive)

When `/swarm-do:do docs/plan.md` runs against this file, follow these rules:

**Runnable phases** — exactly the 21 Part 4 sub-phases below, in this order. Everything outside Part 4 is context, not a runnable unit.

- `### Phase 9a` → `### Phase 9b` → `### Phase 9c` (strict sequence; each depends on the previous)
- `### Phase 9d`, `### Phase 9e`, `### Phase 9f` (parallelizable after 9c; swarm-do runs them sequentially)
- `### Phase 9g` (retention ADR — must land before any shared operator install)
- `### Phase 10a` → `### Phase 10b` → `### Phase 10c` (strict sequence)
- `### Phase 10d`, `### Phase 10e`, `### Phase 10g` (parallelizable after 10c)
- `### Phase 10f` (invariant ADR — must land before any shared operator install)
- `### Phase 11a` (scaffold) → `### Phase 11b`/`11c`/`11d`/`11e` (parallelizable) → `### Phase 11f`/`11g` (status bar + docs)

**Skip entirely** — the orchestrator must NOT create beads issues for:

- Any `Phase N` reference inside Parts 1 / 2 / 5. Those are rollout stages or strategy discussion, not runnable phase headings (they live under `## Section X — Phase N:` headings, never `### Phase`).
- Anything in `docs/history/packaging.md`. That file is audit reference for shipped work — do not open it to look for work.

**Complexity/kind tags** — every runnable sub-phase carries `(complexity: …, kind: …)` in its heading. Trust the tag; do not auto-assign. Model/effort per role is chosen by the swarm-do SKILL.md complexity→model table; the plan does not override it.

**Execution note** — a single invocation of `/swarm-do:do docs/plan.md` will iterate all 21 runnable sub-phases above in order. For a narrower run, extract one sub-phase into its own plan file (e.g. `docs/phase-9a.md`) and point swarm-do at it.

---

<!-- ==================== PART 1 + PART 2 (from integration plan) ==================== -->

# Part 1 — Architecture & Policy

**Goal:** Add Codex / GPT-5.4 to the existing Claude + beads swarm to support (a) cross-model review, (b) competitive implementation on risky phases, (c) rate-limit fallback. Validate the lowest-commitment version first before investing in dispatcher infrastructure. The top-level operator entrypoint is the `/swarm-do:do` command (packaging shipped; see Part 3 history).

(Part 2 — Rollout strategy — starts at §2.0. Part 3/4/5 — packaging, implementation phases, command surface — follows Part 2.)

---

## Build-order roadmap (canonical sequencer)

This section is the source of truth for execution order. Packaging phases (Phases 0–11) are defined in **Part 3 and Part 4** below; rollout strategy and measurement (§1.x, §2.x) are defined in **Part 1 and Part 2**. They do **not** block each other arbitrarily — the dependency chain below is narrower than it looks.

```
Week 1 (parallel-safe):
  ├─ Matrix refresh (30 min) ──────────────────┐
  ├─ Phase 1.5 spike (30 min, scratch plugin) ─┤
  └─ Phase 0 pre-flight (§2.0, ~2h) + experiment (1-2 evenings) ┤
                                                ▼
Week 1-2:
  Packaging migration — Part 3 Phases 0-7 (2-3 days sequential, now EXECUTED)
      ├─ Depends on: matrix refresh, Phase 1.5 spike
      └─ Ships: /swarm-do plugin + bin/swarm CLI + JSONL run log + config contract
                                                ▼
Week 2-3 (Phase 0 decision recorded as DOGFOOD):
  Integration Phase 1 — opt-in codex-review dogfood lane in /swarm-do
      └─ Depends on: packaging cutover + Phase 0 decision recorded
                                                ▼
Weeks 3-5 — V1 operator experience (§1.8 / §1.9 / §1.10):
  §1.7 role promotions — one role at a time, gated on per-role A/B measurement
  §1.8 operator console — CLI + TUI both V1 (TUI promoted 2026-04-23):
      ├─ Phase 9a/9b (ledger emission) — ships with packaging migration
      ├─ Phase 9c (CLI report, read-only) — once ≥50 runs accumulated
      └─ Phase 11 (TUI) — Textual-based, ships once preset/pipeline system lands
  §1.9 continuous-measurement:
      ├─ Phase 9d (outcome-join) — once Phase 1 stable for 2+ weeks
      ├─ Phase 9e (SQLite indexer) — deferred until JSONL perf warrants
      ├─ Phase 9f (adjudication sampler) — first monthly run after Phase 1 stable
      └─ Phase 9g (retention ADR) — blocks shared-operator install
  §1.10 presets + pipeline registry (~1.5-2 weeks — biggest §1.x chunk):
      ├─ Phase 10a (schemas + validation gates) — BLOCKING before any user pipeline loads
      ├─ Phase 10b (pipeline engine refactor) — orchestrator becomes data-driven
      ├─ Phase 10c (preset loader + bin/swarm subcommands)
      ├─ Phase 10d (stock presets: balanced / claude-only / codex-only / ultra-plan / competitive / lightweight / hybrid-review)
      ├─ Phase 10e (telemetry integration — preset_name / pipeline_name / pipeline_hash in runs.jsonl)
      └─ Phase 10f (invariant-enforcement ADR)
                                                ▼
Only if Phase 1 stays clean 2+ weeks:
  Phase 2 (Pattern 5 manual trial) → Phase 3 (B1 dispatcher) as warranted
```

**Sequencing within the V1 operator experience:** §1.9 telemetry ledgers MUST ship before §1.10 preset/pipeline rollout — otherwise pipeline A/B comparisons are not measurable and pipeline choice stays vibes. §1.10 validation gates (Phase 10a) MUST ship before any user pipeline can be loaded (supply-chain safety). TUI (Phase 11) depends on both CLI surface (§1.8 Phase 9c) and preset/pipeline system (§1.10) — it's a view over both.

**What does NOT block packaging:** Phase 0 experiment (uses direct `codex exec`, not the plugin), §1.7 role measurements (need plugin first), Phase 1 auto-wiring.

**What DOES block packaging:** matrix refresh (required before default config commits), Phase 1.5 spike (path rewrites depend on its outcome).

**What blocks Integration Phase 1:** Packaging Phase 7 verified AND Phase 0 decision recorded. Both must be true.

**Key constraint:** no new orchestration logic (Phase 1 wiring, §1.7 role promotions) lands in `claude-mem:do`. Every new piece targets the `/swarm-do` plugin. This is the whole point of the packaging migration — breaking this invariant recreates the fork-drift bug.

**Second load-bearing invariant — underlying layer replaceability.** Two layers the orchestration sits on are explicitly kept swappable (see packaging plan "Replaceability" section):
- **Memory (today: `claude-mem`)** — no role file or runner may import claude-mem-specific commands. Memory is consumed through the skill surface only. Keeps Anthropic-native-memory / context-mode / custom-plugin swaps cheap.
- **Task store (today: `beads`)** — coupling is accepted. No wrapper is pre-built (rejected as premature abstraction — see packaging plan's "Replaceability" section for full reasoning). Free discipline only: preflight DRY via one sourced shell function; grep-consistent `bd` invocations to make an eventual find/replace mechanical; small command-surface to minimize swap scope. Load-bearing features any candidate must preserve if a swap becomes real: atomic claim, append-only notes, dependency edges, assignee-on-create. A wrapper gets built *when* a real alternative is under evaluation, not before — so it can be tailored to both implementations correctly.

These invariants are not refactors to execute now; they are rules to enforce going forward.

**Safe to start today:** plugin dogfood rollout: `hybrid-review`, `swarm compete`, and rollout-status state/CLI. The standalone Phase 0 harness is no longer the critical path.

---

## Status (as of 2026-04-24)

- **M1 manual fallback runner — SHIPPED.** The fallback runner is now plugin-owned under `bin/{swarm-run,swarm-claude,swarm-gpt,swarm-gpt-review}` with role bundles under `roles/agent-{writer,review,spec-review,codex-review}/{shared,claude,codex}.md`. Beads preflight hard-stop embedded in the runner.
- **Phase 0 initial experiments — COMPLETE; decision: DOGFOOD IN PLUGIN.** The first harness round produced enough signal to stop isolated experimentation for now. We will learn faster by shipping opt-in Codex lanes inside `/swarm-do` and using normal plugin runs as the measurement surface. The blinded 12-15 phase cohort remains useful if later data is noisy, but it no longer blocks Phase 1.
- **Phase 9a (append-only ledgers) — SHIPPED (2026-04-23, PR #1, merged at `ff14fc8`; follow-ups landed by 2026-04-24).** v1-frozen JSONSchemas under `swarm-do/schemas/telemetry/`; `bin/_lib/hash-bundle.sh` (portable sha256 over `shared.md + <backend>.md`); `bin/swarm-run` EXIT-trap appends one `runs.jsonl` row per invocation, fail-open. Follow-ups now landed: strict Crockford ULIDs via `swarm_do.telemetry.ids`, `diff_size_bytes` wired from the run delta, and nullable `timestamp_end` in the schema.
- **Phase 9b (findings extractor) — SHIPPED (2026-04-23, commit `6b62467`; Claude extractor landed by 2026-04-24).** `bin/extract-phase.sh` appends one `findings.jsonl` row per reviewer finding. It handles `agent-codex-review` JSON output plus Claude-style `agent-review` / `agent-code-review` markdown, and `bin/_lib/normalize-path.sh` strips worktree prefix so main-repo and worktree paths hash identically. `findings.v2.schema.json` carries `stable_finding_hash_v1`, `duplicate_cluster_id` (always null on append), and `short_summary`. `swarm-run` wires the extractor after review roles with a fail-open guard.
- **Phase 1 (Codex review in swarm)** — proceed as opt-in dogfood: ship a `hybrid-review` preset/pipeline with fail-open `agent-codex-review` after spec-review. Do not make it default yet.
- **Phase 2 (Pattern 5 / 6)** — build only the manual Pattern 5 entrypoint now (`swarm compete` + competitive preset). Pattern 6 and auto-triggering remain deferred.
- **Phase 2.5 (manual fallback)** — covered by M1; no further work here until the manual track fatigue signal fires.
- **Phase 3 (B1 dispatcher)** — do not implement live dispatch yet. Build only the shared rollout-status state/CLI that future dispatcher shadow mode will read.
- **Phase 10 (preset + pipeline registry) — SHIPPED on main-compatible local commit `0c8bc0f` (2026-04-24).** Preset/pipeline validation, stock presets, resolver invariants, telemetry context, and rollout-status CLI are usable for dogfood.
- **Phase 11 (TUI) — MVP/PARTIAL on local commit `0c8bc0f` (2026-04-24).** The Textual app exists under `py/swarm_do/tui` with dashboard/settings/preset/pipeline/status surfaces, but it is not the full §1.8/Phase 11 spec yet. Known gaps: burn chart is still simplified from available telemetry, save/undo flow is incomplete compared with 11c, preset rename/delete UX needs more polish, and live visual verification has not been exercised as a release gate.
- **Phase 9e (SQLite indexer) — DEFERRED.** Keep JSONL as the source of truth until real plugin usage shows query/performance pain.

## Dependency note — future Claude-side orchestration

Any future Claude-side orchestration work (Phase 1 review integration, Pattern 5/6 auto-dispatch, and eventually the B1 dispatcher's Claude front-end) **must target the owned `/swarm-do` plugin**, not a patched `claude-mem:do` skill. The packaging migration is documented in Part 3 of this plan. Rationale:

- `claude-mem` is a third-party plugin; editing it forks upstream and blocks `/plugin update`.
- Claude Code loads skills from `~/.claude/plugins/cache/<marketplace>/...`, not the marketplace source — in-place edits silently revert on reinstall.
- Owning the orchestration command is the only durable path to ship Phase 1+ changes.

**When to act:** before Phase 1 lands its auto-trigger wiring. The `/swarm-do` plugin must be the active entrypoint before any new orchestration logic is written, or Phase 1 will repeat the same fork-drift bug this migration exists to fix.

---

## Section 0 — Backup current flow (DO THIS FIRST)

Most agent definitions, skills, and hooks live outside the repo and are not tracked. Snapshot before any changes.

**Action:**
```bash
# Tag the current state with a dated snapshot
mkdir -p ~/.claude-backups
cd ~ && tar czf ~/.claude-backups/claude-$(date +%Y%m%d-%H%M).tar.gz \
  .claude/CLAUDE.md \
  .claude/agents \
  .claude/skills \
  .claude/commands \
  .claude/hooks \
  .claude/settings.json \
  .claude/settings.local.json \
  2>/dev/null

# Snapshot the installed Codex CLI contract before depending on it
TS=$(date +%Y%m%d-%H%M)
mkdir -p ~/.claude-backups/codex-contract-$TS
codex --version > ~/.claude-backups/codex-contract-$TS/version.txt
codex exec --help > ~/.claude-backups/codex-contract-$TS/exec-help.txt
codex exec review --help > ~/.claude-backups/codex-contract-$TS/exec-review-help.txt

# Also init a git repo inside ~/.claude for ongoing version control
cd ~/.claude && git init 2>/dev/null && git add -A && git commit -m "snapshot before codex integration"
```

**Trigger:** Manual, once, before starting Phase 0.

**Rollback plan:** `tar xzf ~/.claude-backups/claude-YYYYMMDD-HHMM.tar.gz -C ~/` or `git reset --hard` inside `~/.claude`.

---

## Section 1 — What to steal from superpowers

Validated by their 160k-star, 4-harness deployment:

1. **Symlinked skills/agents directory** — single canonical source under `~/.agents/` (or equivalent), symlinked into each harness's config dir. Makes B1 dispatcher cheap later.
2. **External prompt files adjacent to skill/agent definitions** — `./implementer-prompt.md`, `./spec-reviewer-prompt.md`. Lets you maintain Claude-tuned and Codex-tuned variants side by side.
3. **Strict two-stage review ordering** — spec compliance first (fast reject), then code quality. Confirm your existing `agent-spec-review` → `agent-review` ordering enforces this.
4. **Fresh-subagent-per-task principle** — already matches your beads swarm. Keep reinforcing.

**Skip:** their `dispatching-parallel-agents` skill (hardcodes Claude Code's `Task()`), their plugin distribution model, their lack of cross-model orchestration.

---

## Section 1.5 — Pre-Phase 0 blockers

Do **not** start Phase 0 until these are done. They affect the control path and the evaluation contract.

**Blocker 1 — Freeze the control review chain**
- There are currently **three incompatible descriptions** of review ordering:
  - `~/.claude/AGENTS.md` topology shows `writer -> spec-review -> code-review`
  - `~/.claude/AGENTS.md` role docs describe `agent-review` as "Stage 1 of 2"
  - role files describe `agent-spec-review -> agent-review -> optional agent-code-review`
  - `~/.claude/agents/agent-review.md` frontmatter `description` (verified 2026-04-22) still says "Runs in parallel with agent-docs after writer closes" — a fourth description that must also be reconciled.
- Pick one canonical default chain and update `AGENTS.md`, the role body files, **and** `agent-review.md`'s YAML frontmatter `description` field to match **before Phase 0**.
- Recommended canonical control chain for the experiment:
  - `agent-spec-review -> agent-review -> optional agent-code-review`
- `AGENTS.md` should mention `agent-spec-review` by filename / role name explicitly, so the control reviewer in Phase 0 is not ambiguous.
- **Phase 0 control scope:** the "existing Claude review path" measured in Phase 0 is the **full default chain** (`agent-spec-review` + `agent-review`). Optional `agent-code-review` is **excluded** unless it was part of that phase's normal execution; this keeps the control honest — Codex is being compared against what actually runs, not against the maximum possible Claude review.

**Blocker 2 — Snapshot the installed Codex CLI contract**
- Treat Codex CLI contract capture as a **Phase 0 preflight**, not a Phase 3 assumption.
- Record:
  - `codex --version`
  - `codex exec --help`
  - `codex exec review --help`
- Phase 0 and Phase 1 should use **direct `codex exec` shell invocation only**.
- Do **not** introduce MCP wrappers in Phase 0 or Phase 1.
- If an MCP wrapper is introduced later, ship the direct `codex exec` fallback in the **same commit**.

---

## Section 1.6 — Model and effort policy

**Canonicity note.** The tables below use lane-level aliases (`opus`, `sonnet`, `gpt-5.4`) for operator mental models. The **canonical source for specific model IDs is §1.7's `backends.toml` config example**. When the two disagree, §1.7 wins — this section is policy; §1.7 is contract.

### Matrix staleness policy

**Trust horizon: 6 weeks from `last_refresh_date`.** Past that, do not commit default-config changes without refreshing first. Treat it like CLAUDE.md hygiene — routine, not event-driven.

**Detection (cheap, automated):** `swarm models check` subcommand hits `GET /v1/models` on both Anthropic and OpenAI, diffs against the matrix IDs stored in `${CLAUDE_PLUGIN_DATA}/last-refresh.json`, prints `new: [...] / removed: [...] / unchanged: [...]`. No LLM call, no HTML parsing, ~2 seconds. Does **not** auto-edit the matrix — only surfaces that a refresh is warranted.

**Refresh (manual, LLM-assisted):** when detection flags a change, run `/swarm-do models refresh`. Reuses `agent-research` to fetch vendor docs, compiles a diff patch against §1.6/§1.7 for human review and commit. Judgment calls (which role moves to a new model, effort level choice) stay with the operator.

**Optional scheduler:** weekly cron invoking `swarm models check`, report to `${CLAUDE_PLUGIN_DATA}/model-refresh-report.md`. Nice-to-have, not required — the 6-week trust horizon plus manual check before any config commit covers 90% of the risk.

### Matrix refresh — verified from vendor docs 2026-04-20

Fetched `docs.anthropic.com/en/docs/about-claude/models/overview` and `developers.openai.com/codex/models` + `platform.openai.com/docs/models`. Lineups confirmed / corrected:

**Claude (Anthropic) — current lineup:**
| Model | API ID | Pricing (in/out per MTok) | Context | Thinking |
|---|---|---|---|---|
| Claude Opus 4.7 | `claude-opus-4-7` | $5 / $25 | 1M | Adaptive |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | $3 / $15 | 1M | Extended + Adaptive |
| Claude Haiku 4.5 | `claude-haiku-4-5` (full: `claude-haiku-4-5-20251001`) | $1 / $5 | 200k | Extended |

Anthropic positions Opus 4.7 as "step-change improvement in agentic coding over 4.6." Opusplan pattern (Opus plans, Sonnet executes) remains their guidance.

**OpenAI / Codex — current lineup (corrected — previous plan references to `gpt-5.1-codex-max`/`-mini` are wrong; those IDs do not appear in current docs):**
| Model | ID | Pricing (in/out per MTok) | Context | Positioning |
|---|---|---|---|---|
| GPT-5.4 | `gpt-5.4` | $2.50 / $15 | 1M | Flagship frontier; "best intelligence at scale for agentic, coding, and professional workflows" |
| GPT-5.4 mini | `gpt-5.4-mini` | $0.75 / $4.50 | 400k | "Strongest mini model yet for coding, computer use, and subagents" |
| GPT-5.4 nano | `gpt-5.4-nano` | (cheaper) | — | Simple high-volume tasks |
| GPT-5.3-codex | `gpt-5.3-codex` | — | — | Coding specialist — capabilities now also power GPT-5.4; still available for code-optimized work |
| GPT-5.3-codex-spark | `gpt-5.3-codex-spark` | — | — | Research preview, **ChatGPT Pro only** — not usable from `codex exec` CLI |

**Reasoning effort enum — 5 levels (corrected, previous plan missed `none`):** `none | low | medium | high | xhigh`. Both GPT-5.4 and GPT-5.4-mini support the full range.

**Key cost observations driving §1.7 routing:**
- gpt-5.4-mini vs Sonnet 4.6: **~4x cheaper input, ~3.3x cheaper output**. Strong justification for bounded / rubric-driven lanes.
- gpt-5.4 vs Opus 4.7: **2x cheaper input, ~1.7x cheaper output**. For complex work, this is the "half-priced frontier" argument.
- Haiku 4.5 at $1/$5 is competitive with gpt-5.4-mini for extremely bounded work and stays in the Claude quota pool — useful when you want to preserve Codex quota.

**What to use where:**
- Primary frontier Claude lane: `claude-opus-4-7` (planning, review, synthesis, analysis)
- Execution Claude lane: `claude-sonnet-4-6` (writer moderate/hard, long-context research)
- Bounded Claude lane (preserve Codex quota): `claude-haiku-4-5` (docs/specs when routing through Claude)
- Primary frontier Codex lane: `gpt-5.4` (competitive writer, Pattern 5, complex Codex work)
- Cheap Codex subagent lane: `gpt-5.4-mini` (docs, spec-review, writer-simple, clarify)
- Coding specialist: `gpt-5.3-codex` (optional — for cases where code-optimization matters more than general reasoning)

Do **not** rely on ambient model / effort defaults for any measured or automated path. The current local defaults are useful for ad hoc work, but they are too implicit for experiments and cross-model orchestration.

Do **not** rely on ambient model / effort defaults for any measured or automated path. The current local defaults are useful for ad hoc work, but they are too implicit for experiments and cross-model orchestration.

**Current-state facts to account for:**
- Current Claude `/do` is the `claude-mem:do` skill and it currently has **no** explicit `model` or `effort` frontmatter, so it inherits the active Claude session settings.
- Current local Claude settings pin the session model to `opus[1m]`.
- Current swarm orchestration uses the `general-purpose` subagent workaround in `AGENTS.md`, so role prompt files are often being **read by** a general-purpose subagent rather than invoked as first-class custom subagents. Until that changes, role-level Claude model / effort frontmatter is a **target policy** unless you also pass explicit per-invocation overrides or launch roles in dedicated Claude sessions.
- Current local Codex config pins:
  - `model = "gpt-5.4"`
  - `model_reasoning_effort = "xhigh"`
- If you do nothing, Codex-backed runners will tend to inherit `xhigh`, which is too expensive to silently apply everywhere.

**Research-backed guidance:**
- Anthropic's current Claude Code docs are explicit:
  - `medium` is the cost-sensitive level when you can trade off some intelligence
  - `high` is the minimum for intelligence-sensitive work
  - `xhigh` is recommended for the best results on coding and agentic tasks
- OpenAI's current model docs confirm that `gpt-5.4` and `gpt-5.4-mini` support `reasoning.effort` values through `xhigh`, but they do **not** provide an equally detailed role-by-role usage guide.
- Therefore, the matrix below uses:
  - Anthropic's explicit effort guidance as the primary behavioral reference
  - OpenAI model support / cost docs to verify what is possible
  - engineering inference to map effort levels onto your swarm roles

**Decision rule for effort levels:**
- `medium`
  - use for bounded, rubric-driven, low-ambiguity tasks where latency and cost matter
  - examples: spec checks, cheap control-path review, structured verification with narrow scope
- `high`
  - default for intelligence-sensitive production work with a clear objective and external correctness signals
  - examples: quality review, normal writer fallback, implementation judge, most Phase 0 review passes
- `xhigh`
  - reserve for low-frequency, high-stakes, hard-to-reverse work where deeper reasoning is worth the extra latency/cost
  - examples: architecture / analysis on risky phases, competitive implementation, synthesis, fragmented-context resume after interruption

**Claude matrix for this plan:**

| Path / role | Model | Effort | Why |
|-------------|-------|--------|-----|
| Current Claude `/do` normal measured run | `opus[1m]` | `high` | Best practical default while current `/do` still orchestrates with inherited general-purpose subagents |
| Current Claude `/do` high-risk / analysis-heavy / Pattern 5-6 run | `opus[1m]` | `xhigh` | Use when the whole orchestration lane is dominated by hard reasoning and reversals are expensive |
| Claude `agent-spec-review` | `sonnet` | `medium` | Fast reject layer, bounded scope, and already locally intended to stay cheap |
| Claude `agent-review` | `opus` | `high` | Primary quality review is intelligence-sensitive and should stay stronger than the spec check |
| Claude optional `agent-code-review` | `opus` | `xhigh` | Deep audit lane; low-frequency and worth extra reasoning when used |
| Claude `agent-writer` | `opus` | `high` | Normal implementation default |
| Claude `agent-analysis` | `opus` | `xhigh` | Ambiguity and design judgment make errors expensive here |
| Claude `agent-docs` | `sonnet` | `medium` | Bounded translation / alignment work, not a hard reasoning lane |
| Claude writer-A in Pattern 5 | `opus` | `xhigh` | Competitive implementation should maximize quality, not optimize for cheapness |
| Claude writer-judge | chosen Claude judge model | `high` | Needs careful comparison, but should stay decisive rather than overthinking |
| Claude code synthesizer | chosen Claude synthesizer model | `xhigh` | Highest-risk merge / synthesis step |
| M1 Claude fallback for `agent-spec-review` | `sonnet` | `medium` | Cheap narrow contract |
| M1 Claude fallback for `agent-review` | `opus` | `high` | Same as primary quality lane |
| M1 Claude fallback for `agent-writer` | `opus` | `high` | Same as primary implementation lane |
| M1 Claude fallback for `agent-analysis` / `risk:high` recovery | `opus` | `xhigh` | Use when ambiguity or interruption recovery makes mistakes expensive |

**Codex matrix for this plan:**

| Path / role | Model | Effort | Why |
|-------------|-------|--------|-----|
| Phase 0 Codex Mode A (scoped review) | `gpt-5.4` | `high` | Review is intelligence-sensitive, but bounded and rubric-driven; `xhigh` is too expensive as the baseline |
| Phase 0 Codex Mode B (repo-aware review) | `gpt-5.4` | `high` | Same rationale as Mode A; compare context depth first, not effort depth |
| Phase 0 escalation rerun on borderline high-risk phases only | `gpt-5.4` | `xhigh` | Use only as a tie-break / sensitivity check on a capped subset, not the default baseline |
| Phase 1 `agent-codex-review` | `gpt-5.4` | `high` | Specialized blocking-issue review needs strong reasoning, but must stay within latency budget |
| Phase 1 cheap reviewer downshift trial | `gpt-5.4-mini` | `medium` first, `high` if needed | Use only after `gpt-5.4 high` proves the lane is valuable and you want to optimize cost |
| Phase 2 writer-B (competitive implementation) | `gpt-5.4` | `xhigh` | Expensive but low-frequency; better to maximize implementation quality on risky phases |
| Phase 2 writer-judge | chosen judge model | `high` | Needs careful comparison, but benefits from being decisive rather than overthinking |
| Phase 2 code synthesizer | chosen synthesizer model | `xhigh` | Synthesis is the highest-risk merge step and should not run on a cheaper effort tier |
| M1 GPT fallback for `agent-spec-review` | `gpt-5.4` | `medium` | Narrow contract, low ambiguity, should stay cheap |
| M1 GPT fallback for `agent-review` | `gpt-5.4` | `high` | Normal quality review is intelligence-sensitive |
| M1 GPT fallback for `agent-writer` | `gpt-5.4` | `high` | Default fallback writer setting |
| M1 GPT fallback for `agent-analysis` / fragmented resume / `risk:high` fallback | `gpt-5.4` | `xhigh` | Use when interruption recovery or ambiguity makes mistakes expensive |
| Phase 3 external dispatcher defaults | explicit per role | explicit per role | No automated path should inherit ambient Codex or Claude effort silently |

**Operator policy for the current Claude `/do` path:**
- For any measured run, record the Claude session model + effort before invoking `/do`.
- If reproducibility matters, set them explicitly first:
  - `/model opus[1m]`
  - `/effort high` for normal `/do` execution runs
  - `/effort xhigh` for hard planning / risky / competition-heavy runs
- Do **not** assume the current Claude session is still using the same effort as a previous session.
- Under the current general-purpose workaround, this session-level setting is the **effective** model / effort for most spawned Claude roles unless you explicitly override per invocation.

**Implementation policy for wrappers / prompts:**
- Every non-interactive Codex invocation should set both model and effort explicitly rather than inheriting from `~/.codex/config.toml`.
- Every Claude role file in `~/.claude/agents/` should get explicit `model` + `effort` frontmatter matching the matrix above, even if current orchestration is still on the general-purpose workaround.
- Current Claude orchestration should move toward one of these enforcement paths:
  - invoke real custom subagents so frontmatter applies
  - pass explicit per-invocation `model` (and, when supported on the invocation path, effort) when spawning
  - split cheap lanes such as `agent-spec-review` into dedicated Claude entrypoints rather than inheriting the parent `/do` session
- Do not claim full Claude-side symmetry is operational until one of those enforcement paths is live.
- Record both in notes for auditability:
  - `Model: <model-id-or-alias>`
  - `Effort: <medium|high|xhigh>`
  - `Setting source: explicit-runner | skill-frontmatter | session-inherited`

---

## Section 1.7 — Primary backend per role (cost-elasticity policy)

**Motivation.** M1 was originally framed as "switch to Codex when Claude rate-limits." The stronger reframe: Claude and Codex are two independent quota pools. Keeping both pools fed extends total runway regardless of whether either is currently limited. For certain roles, Codex can be the **primary** backend, not the fallback — freeing Claude quota for lanes where Claude actually leads.

**Is this valid?** Yes. It's cost-based model routing — a standard pattern. Three facts make it straightforward here:

1. Aider polyglot coding benchmark (current published data): `gpt-5 (high)` 88.0% at ~$0.13/task; `gpt-5 (medium)` 86.7% at ~$0.08/task; `claude-opus-4 (no think)` 70.7% at ~$0.30/task. gpt-5 / codex is strictly cheaper and higher-scoring on pure code-editing benchmarks. (Caveats: older model generations than current Claude 4.6/4.7 and gpt-5.4; Aider tests are small exercism problems, not long-context codebase reasoning.)
2. Your infrastructure is already backend-agnostic at the role level: `roles/<role>/shared.md` + `claude.md`/`codex.md` overlays exist. Adding a `default_backend` field per role is a minor extension — the hard work is prompt portability, which is already done for M1 roles.
3. The swarm has heterogeneous role profiles. Some roles are pure mechanical edits; others are nuanced design judgment. One model is not optimal for all of them.

**What GPT-5 / Codex is reliably good at (candidate primary roles):**
- Pure algorithmic / mechanical code generation (Aider, HumanEval, LiveCodeBench consistently top)
- Structured transformation tasks — documentation generation, schema/type synthesis, format conversion
- Rubric-driven review (deterministic checklist application)
- Bounded refactors with clear in/out contracts
- Math-heavy / numerical code

**What Claude Opus/Sonnet 4.x still leads on (keep Claude-primary):**
- Long-context codebase reasoning (cache + effective 200K+ window)
- Complex agentic tool-use (nested `Agent()`, MCP chains, parallel dispatch)
- Nuanced natural-language judgment over many turns
- Chain-of-verification self-correction under ambiguity
- Root-cause reasoning under incomplete context
- Safety-relevant / architectural judgment

### Recommended per-role primary backend

| Role | Current primary | Proposed primary | Measurement gate before promotion | Rationale |
|---|---|---|---|---|
| agent-docs | claude | **codex** | 5-phase A/B: blind judge rates doc quality. ≥ parity required. | Bounded translation; gpt-5 excels at structured output. Lowest risk. |
| agent-spec-review | claude | **codex** | 10-phase A/B on `SPEC_MISMATCH` detection rate. Parity or better required. | Rubric-driven; deterministic checklist application is Codex's strength. Already intended cheap lane. |
| agent-writer (`complexity: simple`) | claude | **codex** | 10-phase A/B: downstream review pass rate + rework rate. ≥ parity required. | Mechanical edits; gpt-5 tops Aider polyglot. |
| agent-clarify | claude | **prefer-codex** | 5-phase A/B on ambiguity-catch rate. | Bounded surfacing task. |
| agent-codex-review | codex (already) | codex | Already covered by Phase 0. | No change. |
| agent-writer (`complexity: moderate`) | claude | claude | Defer promotion until simple-phase writer data lands. | Mid-ambiguity; risk compounds. |
| agent-writer (`complexity: hard`) | claude | **claude** | Do not promote. | Architectural / novel logic; Claude leads. |
| agent-research | claude | **claude** | Do not promote. | Long-context reading-heavy; Claude's cache advantage. |
| agent-analysis | claude | **claude** | Do not promote. | Design judgment. |
| agent-debug | claude | **claude** | Do not promote. | Root-cause reasoning under ambiguity. |
| agent-review | claude | **claude** | Do not promote. | Primary quality reviewer; already paired with codex-review for the other axis. |
| agent-writer-judge / agent-analysis-judge / agent-code-synthesizer | claude | **claude** | Do not promote. | Highest-stakes; don't optimize cost here. |
| Orchestrator (the `/swarm-do` skill body itself) | claude | **claude** | Not applicable. | Nested Agent() spawning, worktree management, bd dispatching — Claude's home turf. |

### "Codex" is not one bucket; "Claude" is not one bucket

Before the config model, an important clarification the earlier draft elided: **each backend has multiple lanes that must be chosen independently**. Model IDs below are verified against vendor docs (2026-04-20 refresh — see §1.6 table).

**Codex lane (verified: `codex-cli 0.121.0` exposes `-m/--model`; existing `swarm-run:178` already passes it):**
- `gpt-5.4` — frontier: tool/computer-use-heavy workflows, strong reasoning. $2.50/$15 per MTok.
- `gpt-5.4-mini` — cheap coding subagent: structured transforms, bounded edits, high throughput. $0.75/$4.50.
- `gpt-5.4-nano` — simple high-volume tasks; lower capability than -mini.
- `gpt-5.3-codex` — coding specialist (still current; its capabilities now also power gpt-5.4).
- Not `gpt-5.3-codex-spark` — ChatGPT Pro only, not accessible via `codex exec` CLI.

**Claude lane:**
- `claude-opus-4-7` — planning, architecture, deep review, high-ambiguity debugging. $5/$25 per MTok. Adaptive thinking.
- `claude-sonnet-4-6` — execution: writer lanes, long-context reasoning, deep codebase fixes. $3/$15. Extended + adaptive thinking.
- `claude-haiku-4-5` — bounded / near-frontier at $1/$5. Useful for preserving Codex quota when a cheap Claude lane suffices.
- "Opusplan" pattern (Anthropic's own guidance): Opus plans, Sonnet executes.

Collapsing either side into a single `backend = "codex"` or `backend = "claude"` loses the token-saving behavior the operator actually wants. The config surface must expose `{backend, model, effort}` as three independent axes. **Reasoning effort enum is 5 values:** `none | low | medium | high | xhigh` (both vendors now use the same value set for the Codex-side; Claude-side effort maps onto adaptive/extended thinking settings, see §1.6).

### Matrix refresh gate — read before touching the tables

The per-role matrix in §1.6 and the routing recommendations in this section reflect a specific vendor-docs snapshot (dated in §1.6's matrix header). §1.6 is the canonical source for current model IDs; this section's routing recommendations must match it.

**Refresh order when vendor docs change** — change propagates in one direction:

1. **Update §1.6's matrix tables** first (new model IDs, new pricing, new effort/thinking enums). Bump the `last_refresh_date`.
2. **Regenerate `backends.example.toml`** from §1.6's canonical table — the template is the source of `backends.toml`'s initial values.
3. **Update `${CLAUDE_PLUGIN_DATA}/last-refresh.json`** (the snapshot the `swarm models check` subcommand diffs against).
4. **Only then update this section's routing narrative** (§1.7 role promotions) to reconcile with the refreshed matrix. §1.7 is downstream of §1.6 — never the other way around.

**Before any role is promoted to codex-primary, or before the plugin's default `backends.toml` is finalized, run a matrix-refresh pass:**
1. Confirm each listed model ID in §1.6 is still the current canonical name for its lane.
2. Confirm the per-role {backend, model, effort} triplet still reflects vendor guidance for that role type.
3. Record the refresh date in §1.6's matrix header. Stale matrices mis-route work.

Do not treat §1.6 as immutable; treat it as the current canonical matrix, refresh-gated. (Earlier drafts of this plan named retired IDs like `gpt-5.1-codex-max`/`-mini`; the 2026-04-20 refresh in §1.6 corrected to the current lineup — always verify against §1.6, never rely on prose in this section.)

### Configuration model — how this should work

**Configurable, not hardcoded. Default stays Claude-primary until measured. Three axes per (role, complexity): backend, model, effort.**

1. **Plugin config surface** (`${CLAUDE_PLUGIN_DATA}/backends.toml` — verified live env path. All model IDs verified against vendor docs 2026-04-20; see §1.6 refresh table.):
   ```toml
   # Per-role, per-complexity triplet. Omit complexity keys for uniform roles.
   # Effort enum: none | low | medium | high | xhigh

   [roles.agent-docs]
   backend = "codex"
   model   = "gpt-5.4-mini"       # $0.75/$4.50 per MTok; ~4x cheaper than Sonnet for bounded translation
   effort  = "medium"

   [roles.agent-spec-review]
   backend = "codex"
   model   = "gpt-5.4-mini"       # rubric-driven fast reject; cheap lane by design
   effort  = "medium"

   [roles.agent-clarify]
   backend = "codex"
   model   = "gpt-5.4-mini"
   effort  = "medium"

   [roles.agent-writer.simple]
   backend = "codex"
   model   = "gpt-5.4-mini"       # mechanical edits — coding specialist lane
   effort  = "medium"

   [roles.agent-writer.moderate]
   backend = "claude"
   model   = "claude-sonnet-4-6"  # mid-ambiguity execution lane — opusplan "execute" side
   effort  = "high"

   [roles.agent-writer.hard]
   backend = "claude"
   model   = "claude-opus-4-7"    # architectural / novel logic — frontier Claude lane
   effort  = "xhigh"

   [roles.agent-research]
   backend = "claude"
   model   = "claude-sonnet-4-6"  # 1M context + extended thinking; reading-heavy
   effort  = "high"

   [roles.agent-analysis]
   backend = "claude"
   model   = "claude-opus-4-7"    # opusplan "plan" side — design judgment
   effort  = "xhigh"

   [roles.agent-debug]
   backend = "claude"
   model   = "claude-opus-4-7"    # root-cause reasoning under ambiguity
   effort  = "xhigh"

   [roles.agent-review]
   backend = "claude"
   model   = "claude-opus-4-7"    # primary quality review; paired with agent-codex-review
   effort  = "high"

   [roles.agent-codex-review]
   backend = "codex"
   model   = "gpt-5.4"            # specialist cross-model review — frontier needed
   effort  = "high"

   [roles.agent-writer-judge]
   backend = "claude"
   model   = "claude-opus-4-7"
   effort  = "high"

   [roles.agent-code-synthesizer]
   backend = "claude"
   model   = "claude-opus-4-7"    # highest-risk merge step
   effort  = "xhigh"

   [fallback]
   on_failure = "fallback"        # "fallback" | "halt"
   fallback_backend = "claude"
   fallback_model = "claude-sonnet-4-6"
   fallback_effort = "high"
   ```

   This is the **refreshed canonical default template**. Operator may override per-role or globally. Default config file ships empty — operator copies from `backends.example.toml` and enables promotions as measurements land (§1.7 measurement gate).
2. **Runner resolution order** (in `swarm-run`): explicit operator flags (`--backend`, `--model`, `--effort` — each independent and composable) → plugin config lookup by (role, complexity) → role default → hardcoded default (`claude-opus-4-7 / high`). An operator who passes only `--model gpt-5.4-mini` inherits everything else from config.
3. **Quota-aware auto-bias (deferred, B1 territory).** If Claude quota > 80% consumed in current window, flip simple/moderate primaries to codex automatically for remainder of window. Log the bias decision in beads notes. **Not for initial rollout** — ship static config first, add quota awareness only after it's clearly needed.
4. **Operator override per invocation.** `swarm-run --backend claude --model claude-opus-4-7 --effort xhigh --issue bd-42` always wins over config. Config is a default, never a constraint.
5. **Visibility.** Every backend run already appends a `## Backend Run` block with `Model:` and `Effort:` lines. Add `Setting source: plugin-config | operator-override | quota-bias` so you can audit *why* each role ran where it did.

### Measurement gate — do not skip

Before flipping any role from claude-primary to codex-primary:

1. Run 5-10 matched phases (same plan, same complexity) with both backends.
2. Score downstream signals — not just "did it produce output":
   - Downstream review `SPEC_MISMATCH` / `NEEDS_CHANGES` rate
   - Rework commits in the 7 days post-merge
   - For docs: blind operator rating on accuracy + completeness
   - For writers: test pass rate on first submission
3. Require **parity or better** on downstream quality, then promote. Revert if the signal degrades.

Same methodology Phase 0 applies to `agent-codex-review`; same rigor for each promotion.

**Pre-registered templates:** `${CLAUDE_PLUGIN_DATA}/measurements/` holds one pre-registration file per role. `agent-docs.md` is the first, landed 2026-04-20 — fully specified cohort criteria, blinded rating rubric, decision rule, and veto conditions. Fill in the results sections only after the experiment runs. Pre-registering the rubric before data lands is the whole point — otherwise the "parity or better" gate is vibes.

**Recommended promotion order (lowest risk first):** agent-docs → agent-spec-review → agent-clarify → agent-writer.simple. Do not measure higher-risk roles (writer.moderate, research, analysis, debug, review, judges) until at least two lower-risk roles have passed the gate.

**Prerequisites before any §1.7 measurement runs (none today):**
1. `/swarm-do` plugin shipped (packaging Phase 7 verified).
2. `${CLAUDE_PLUGIN_DATA}/runs.jsonl` writer wired into `bin/swarm-run`.
3. `backends.toml` per-role config loading verified.
4. At least 5 real upcoming work phases identified that match the cohort rubric for the role under test.

Without these, the measurement is a spreadsheet exercise, not a structured promotion gate.

### Economics sanity check

Even a naive split helps. If 40% of your swarm's token load (docs + spec-review + simple writers + clarify) runs on Codex, you're reclaiming 40% of Claude quota for the lanes where Claude actually matters. That's the entire point — **split quota, extend session runway, lose nothing on the lanes where Claude leads**.

---

## Section 1.8 — Operator console (CLI + TUI, both in V1)

**Motivation.** Section 1.7's config model has many knobs (per-role × per-complexity × backend). Section 1.10 adds presets + swappable pipelines on top. Editing TOML by hand is fine for first-time setup but too slow for the "reconfigure as the week progresses" use case that the combined §1.7/§1.10 surface creates. Plus there is no current view of in-flight beads issues, consumption burn, or per-role historical performance — all of which the operator needs in the loop.

**Verdict revision (2026-04-23).** TUI is **promoted to V1**, not deferred. The earlier "ship last — convenience overlay" framing was right for §1.8 in isolation but wrong once §1.10 lands ~15 roles × 3 complexities × 2 backends × multiple models × 5 efforts + a preset/pipeline registry on top. Without a TUI, the operator has to either round-trip through Claude for every setting inspection ("what's my current matrix?") or memorize a CLI cheat sheet — both friction points the TUI exists to remove. The operator's own framing — "build and use it in order to improve the interface" — confirms iteration-on-UI is the point.

### Phasing

1. **Data model (ship first).** Append-only JSONL at `${CLAUDE_PLUGIN_DATA}/runs.jsonl` + companion ledgers per §1.9. Lockfiles at `${CLAUDE_PLUGIN_DATA}/in-flight/bd-<id>.lock` created on `bd --claim`, deleted on close.
2. **CLI commands (ship second — delivers 80% of the value on a scripting surface).**
   - `swarm status` — in-flight issues + consumption burn + active preset + pipeline summary.
   - `swarm handoff bd-42 --to codex` — one-liner M1 fallback.
   - `swarm config edit` / `swarm config set roles.agent-writer.simple.backend=codex` — fast reconfiguration.
   - `swarm preset load <name> | save <name> | diff <name> | list` — preset management (per §1.10).
   - `swarm pipeline list | show <name> | lint <path>` — pipeline registry access (per §1.10).
   - `swarm mode <claude-only | codex-only | balanced | custom>` — shortcut for the four canonical preset names.
   - `swarm stats --since 7d --role agent-writer` — measurement gate input for §1.7 promotions.
3. **TUI (ship third — now V1 scope, not deferred).** Textual-based (see framework decision below). Primary value: live in-flight panel, matrix-editor for per-role config, preset browser + diff viewer, pipeline inspector, rollup stats. Not a rewrite — a different view on the same state files.

### TUI framework decision — Textual

Three candidates considered (2026-04-23): **Textual** (Python), **bubbletea** (Go), **ratatui** (Rust). Decision: **Textual**, for three reasons in priority order.

1. **Ecosystem consistency.** `tech-radar` (sibling plugin in the same marketplace) already ships with Textual 0.80+ and `textual-serve`. Adding a second TUI stack (Go or Rust) doubles the plugin's build/maintain surface. Operator already has the Python 3.13 env + dependency install flow working — one less thing to bootstrap.
2. **Form-heavy UI fits Textual's widget model.** Settings matrix editor, preset picker, pipeline inspector are all forms/tables. Textual's `DataTable` widget handles the role × complexity matrix natively; reactive state + tcss styling + Dev Console hot-reload make the settings editor cheap to build. ratatui's immediate-mode rendering is excellent for view-heavy tools (gitui, bottom) but painful for edit-heavy forms because the view rebuilds every frame. bubbletea's Elm MVU is clean but requires more boilerplate per form field than Textual's declarative widgets.
3. **Iteration speed matches stated goal.** Dev Console + tcss hot reload is the fastest "build it while using it" loop of the three. The operator explicitly wants to iterate on the interface while using it — Textual optimizes for exactly that workflow. Python startup latency (~200–300ms) is the frequently-cited downside but irrelevant for an operator console opened once per working session.

**Bonus — `textual-serve` ships the same code as a web dashboard** if a future use case warrants it (remote monitoring, team dashboards). Go/Rust stacks would require a separate web build.

**Rejected alternatives:**
- **bubbletea / Go**: strong fit on its own merits; excellent Charmbracelet ecosystem (lipgloss, bubbles). Rejected because it adds Go as a plugin dependency with no other Go code in the plugin or marketplace — consistency argument wins.
- **ratatui / Rust**: fastest startup, best for live dashboards. Rejected because the settings-editor surface dominates the TUI, and immediate-mode rendering is the wrong paradigm for edit-heavy forms. Strong candidate if this were a read-only observability tool.
- **Rich alone (no Textual)**: non-interactive. Covers status reports but not editing. Used internally by Textual anyway.

### TUI — v1 interface

Four screens. Keyboard-first. Status bar persistent across all screens.

**[d] Dashboard** (landing screen)
- In-flight table: `issue_id | role | backend | model | elapsed | cost_so_far | status`
- Consumption burn chart: tokens/hr per backend over last 24h
- Recent 429s per backend (last event timestamp + count in last hour)
- Active preset banner (top) — `Preset: balanced | Pipeline: default | Mode: balanced`
- Auto-refresh every 2s, tailing telemetry ledgers (append-only = safe to read live)
- Hotkeys: `f` handoff in-flight issue to other backend, `o` open issue in browser, `c` cancel

**[s] Settings — role × complexity matrix editor**
- Rows: all configured roles (from backends.toml + role registry)
- Columns: simple / moderate / hard (grayed for roles without complexity keys)
- Cells: `{backend}/{model}/{effort}` as compact string
- Arrow keys navigate; Enter opens a detail panel for the selected cell with three dropdowns (backend, model, effort) + show/hide derived fields (matrix origin: stock / overridden / inherited)
- Ctrl-S writes to backends.toml atomically (temp file + rename; config_hash updates for telemetry)
- Invariant guard: changing `orchestrator` / `agent-code-synthesizer` to non-Claude backend displays a blocking error and cannot be saved. Structural invariants have no force path; only advisory warnings can be dismissed.

**[p] Presets — preset browser + diff viewer**
- Left pane: list of available presets (stock + user), grouped by origin
- Right pane: preview of selected preset's matrix + pipeline reference
- `l` load preset (confirm prompt), `s` save current config as new preset, `d` diff against stock, `r` rename (user presets only)
- Diff view highlights cells that differ from stock/current

**[i] Pipelines — pipeline inspector**
- Left pane: list of available pipelines (stock + user), with tag for origin
- Right pane: visual stage graph (indented ASCII showing fan-out + merge stages), agents per stage, failure tolerance per stage, invariant status
- `s` select pipeline (updates active-pipeline in current preset), `l` lint pipeline file, `v` validate against role registry
- Read-only v1 — editing happens in an external editor, TUI just lists + validates

**Status bar (persistent):**
`preset=<name> pipeline=<name> runs_today=N cost_today=$X last_429_claude=<time> last_429_codex=<time>`

**Out of v1 (deferred):**
- Pipeline YAML editor inside the TUI (external editor is fine; TUI lints on load)
- Telemetry report generation (CLI `swarm telemetry report` is authoritative; TUI mirrors output)
- Per-repo config (global-only v1)
- Remote / web variant via textual-serve (ships post-v1 only if useful)
- Adjudication workflow inside TUI (external blinded-adjudication pipeline already works; TUI just links)

### Distribution

- TUI ships as a Python module under `swarm-do/tui/` with its own `requirements.txt` — matches `tech-radar/scripts/`.
- Entry point: `bin/swarm-tui` wrapper that sets up the venv + invokes Textual.
- On first run: `bin/swarm-tui` detects missing venv, prompts to create (`python3 -m venv .venv && pip install -r requirements.txt`). Operator can skip; CLI still works.
- Textual Dev Console for development: `TEXTUAL=debug,devtools bin/swarm-tui` pairs with `textual console` in a second terminal for hot reload + logging.

### What to track (per invocation, in the telemetry ledgers)

Telemetry is split across four append-only JSONL ledgers (schema tiers match
the observation shape, not the invocation count — one run can produce many
findings, and findings accrue outcomes over time). See §1.9 for the two-tier
architecture (JSONL truth + SQLite derived index).

**runs.jsonl — one row per invocation:**
- `run_id` (ulid), `timestamp_start`, `timestamp_end`
- `backend` (claude | codex), `model`, `effort`
- `prompt_bundle_hash` — SHA-256 of concatenated role prompt (shared.md + backend.md)
- `config_hash` — SHA-256 of backends.toml at invocation time
- `role`, `phase_kind` (feature|bug|refactor), `phase_complexity` (simple|moderate|hard)
- `risk_tags` (array — `risk:high`, `kind:bug`, etc.)
- `issue_id`, `phase_id`, `plan_path`
- `repo`, `worktree`, `base_sha`, `head_sha`
- `diff_size_bytes`, `changed_file_count`
- `input_tokens`, `cached_input_tokens`, `output_tokens`, `estimated_cost_usd`
- `wall_clock_seconds`
- `tool_call_count`, `budget_breach` (bool), `cap_hit` (bool — reviewer hit the finding cap)
- `schema_ok` (bool), `exit_code`, `last_429_at`
- `writer_status` (DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT) for writer roles
- `review_verdict` (APPROVED | SPEC_MISMATCH | NEEDS_CHANGES) for review roles
- `setting_source` (plugin-config | operator-override | quota-bias)

**findings.jsonl — one row per finding:**
- `finding_id`, `run_id` (joins to runs.jsonl)
- `category` (types | null | boundary | security | performance | design | test)
- `severity` (critical | warning | info)
- `file`, `line_start`, `line_end`, `symbol` (when resolvable; else null)
- `short_summary` (normalized — leading verb stripped, trimmed)
- `stable_finding_hash_v1` — SHA-256 over (file, category, line_start/10, normalized_summary_tokens)
- `duplicate_cluster_id` — assigned by indexer post-hoc via §1.9 duplicate rule
- `was_truncated` (bool — output cap), `was_uncertain` (bool — emitted as info/speculative)

**finding_outcomes.jsonl — append-only, joined ex-post by the manual/periodic enricher:**
- `finding_id`, `observed_at`
- `maintainer_action` (ignored | commented | fixed_in_same_pr | followup_issue | followup_pr | hotfix_within_14d)
- `followup_ref` (bd-id | PR url | commit sha)
- `time_to_action_hours`, `time_to_fix_hours`
- `recurrence_of` (stable_finding_hash_v1 of a prior matching finding — same pattern re-flagged)

**adjudications.jsonl — append-only, populated by monthly blinded adjudication:**
- `finding_id`, `adjudicated_at`, `adjudicator`
- `verdict` (TP | FP | Ambiguous)
- `rubric_version`, `blind_batch_id`, `rationale`

**Ledger invariants:**
- Append-only. Never overwrite. Corrections are new rows referencing the prior `run_id` / `finding_id`.
- `prompt_bundle_hash` and `config_hash` are load-bearing — without them you can't tell whether a trend is model drift, prompt drift, or config drift.
- Failed/aborted runs (schema_ok=false, 429, timeout, budget breach) stay in the dataset. Survivorship bias is the most expensive metric error to unwind later.

### What to show / compute

**Live panel:**
- In-flight: `bd-42 agent-writer (claude/opus/high) — 00:08:12` + `[f]` fallback / `[o]` open / `[c]` cancel.
- Consumption burn (last 24h): tokens/hr per backend, cost/hr.
- Recent 429s per backend — the only honest quota signal. "No 429s in 24h on codex" = plenty of room.
- Active config mode banner.

**History panel (last N runs):**
- One line per run: bd-id / role / backend / model / duration / cost / verdict.

**Stats (on-demand, drives §1.7 promotions):**
- Per-(role, backend, complexity): success rate, mean cost, mean latency, sample count.
- Side-by-side claude vs codex on matched roles — this is the parity-gate view.
- Rework rate: count of bd issues opened in 7-day window after a phase merged that reference the same files.

### Quota tracking — be honest about limits

Neither Anthropic nor OpenAI expose "remaining quota" as a reliable programmatic read. Every quota bar in this console is a **consumption estimate** against known session/daily ceilings, not a quota-remaining read from an API. Label them that way. The only hard quota signal is a 429 — track the last-429 timestamp per backend and show it prominently. "3 × 429 in last hour on claude" means flip to codex-only mode; "no 429 in 24h on either" means run balanced without worry.

### What to configure

**Minimum viable:**
- Global mode: claude-only / codex-only / balanced / custom.
- Per-role primary backend (single column).
- On-failure: fallback | halt.

**Power user:**
- Full per-role × per-complexity matrix.
- Model + effort overrides per role.
- Latency budget per role (for auto-discard in the style of Phase 1's 60s Codex review cap).
- Quota-bias thresholds (deferred; auto-trigger territory).

### Why CLI-first is the right call

- Delivers the highest-pain fix (in-flight bd-id lookup + handoff command) in one command, one evening.
- Forces the data model decision early — TUIs that skip this end up re-shaping their data stores twice.
- CLI is scriptable. The operator can build their own muscle-memory wrappers and aliases before we commit to a UI shape.
- TUI rebuild later is additive. No wasted work.

### Plugin-implications summary

- `bin/swarm` (single binary or bash dispatcher) adds subcommands listed above.
- `bin/swarm-run` writes a `runs.jsonl` line on every invocation + a `findings.jsonl` line per finding + manages lockfiles.
- `bin/swarm-telemetry` (new) exposes `append | rebuild-index | query | report` subcommands (see §1.9).
- Existing `## Backend Run` note block stays the same; ledgers are the machine-readable mirror.
- Part 3 packaging phases include `bin/swarm` + `bin/swarm-telemetry` in the copy-cutover step, and reserve `${CLAUDE_PLUGIN_DATA}/telemetry/` as the ledger dir (see Part 5 "Operator console + telemetry — infra this migration must reserve").

---

## Section 1.9 — Continuous measurement architecture

**Motivation.** §1.8 ships the raw telemetry; §1.7 ships the promotion gate;
Phase 0 shipped the pre-registered experiment. As we add reviewer lanes (Codex
Mode B, Codex Mode C, future lanes) and run them alongside Claude on real
features, we need a way to *keep learning* without running a full pre-registered
cohort for every question. This section defines the always-on measurement loop
that surrounds the discrete experiments.

### Principles — what the watcher is and isn't

1. **Analyst, not judge.** The watcher surfaces patterns, not verdicts. TP/FP
   labels come only from blinded adjudication (monthly).
2. **Proxies, not truth.** Mechanical duplication, hotfix-within-14d, "finding
   became a code comment" — all are *proxy signals* stored as `maintainer_action`
   values. Treating them as TP/FP labels breaks the trust chain the adjudication
   gate depends on.
3. **No auto-tuning.** The watcher never rewrites prompts, config, or routing.
   Its output is a report for the operator. Closing the loop automatically is
   how Goodhart's law eats the system — reviewers learn to minimize the metric,
   not produce value.
4. **Stratify before averaging.** Global means across roles / complexities /
   phase kinds hide the signal. Reports compare within
   `role × complexity × phase_kind × risk_tag` buckets.
5. **Keep the adjudication anchor.** Monthly blinded adjudication on a sample
   (10–20 findings) is the only trustworthy TP/FP source. Everything else is
   auxiliary.

### The three-layer loop

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Always-on telemetry (every swarm run)                  │
│   bin/swarm-run appends runs.jsonl + findings.jsonl             │
│   bin/swarm-telemetry append (programmatic API)                 │
│   Fail-open: telemetry errors never block pipeline              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Nightly outcome-join (enricher, not mutator)           │
│   - Scan recent PR merges                                       │
│   - For each finding: did a hotfix touch the same file+lines    │
│     within 14d? did a follow-up bd issue reference it?          │
│   - Append finding_outcomes.jsonl rows (never overwrite)        │
│   - Recurrence detection: same stable_finding_hash_v1 seen      │
│     twice = pattern, flag for attention                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Monthly blinded adjudication (authoritative)           │
│   - Sample 10-20 recent findings                                │
│   - Run through the same pipeline Phase 0 used                  │
│     (blinded-merged → verdicts → unblinded)                     │
│   - Append adjudications.jsonl; scorecard bead gets updated     │
│   - Refresh per-reviewer TP/FP rates                            │
└─────────────────────────────────────────────────────────────────┘
```

### Storage — two-tier (JSONL truth + SQLite derived index)

**Source of truth: append-only JSONL ledgers** at
`${CLAUDE_PLUGIN_DATA}/telemetry/`:
- `runs.jsonl` — schema per §1.8
- `findings.jsonl` — schema per §1.8
- `finding_outcomes.jsonl` — append-only, per-finding outcome observations
- `adjudications.jsonl` — append-only, blinded-verdict rows

**Derived index: SQLite** at `${CLAUDE_PLUGIN_DATA}/telemetry/index.sqlite`:
- Built by `swarm telemetry rebuild-index` — tails all four JSONL files, populates tables
- FTS5 virtual table over `findings.short_summary` for free-text search
- Views: `v_reviewer_scorecard`, `v_finding_overlap`, `v_outcome_proxy_rates`
- If deleted, fully reproducible from JSONL. Not load-bearing for core swarm.
- Matches the pattern already used by sibling plugins (`tech-radar/`, `enovis-trello/`).

**Why two tiers:**
- JSONL wins on simplicity, append safety, grep-ability, backup, forward-compat.
- SQLite wins on query speed, joins, FTS5 search — essential once the dataset crosses a few thousand rows.
- The indexer is a CLI command, not a hook. If the index breaks, `bin/swarm-run` keeps writing ledgers; `rebuild-index` recovers.

### Duplicate rule (pinned version — v1)

Identical to the Phase 0 rubric §2 rule, pinned here so the indexer can stamp
`duplicate_cluster_id` consistently as it tails `findings.jsonl`:
- Same file (after path normalization — resolve symlinks, strip worktree prefix)
- Same category-class (`types` and `null` merge to `types_or_null`; others stand alone)
- Line references within ±3 lines

**When available, also match on symbol** (function/method name resolved via
language server or ctags): cheaper defense against line drift from unrelated
edits. Symbol match is a tiebreaker, never a requirement — many findings won't
have a resolved symbol.

### Watcher report — what it flags

Manual-first cadence: `swarm telemetry report --since 30d`. Add scheduled runs
only after the signal is proven useful (premature scheduling creates false-alarm
fatigue). Report sections:

1. **Rising duplicate rate without rising unique accepted findings** — suggests
   a reviewer is converging on its peers' catches.
2. **Reviewer silent streaks** — `reviewer X produced 0 findings on N
   consecutive phases in bucket B`. Early warning of prompt rot or scope
   mismatch.
3. **New defect categories surfaced only by one lane** — complementary coverage
   signal.
4. **Cost per maintainer-action** (proxy, not TP) — cheap quality heuristic.
5. **Regressions after prompt/model/config hash changes** — joins on
   `prompt_bundle_hash`, `model`, `config_hash` columns so "it changed on
   2026-05-01" is visible, not inferred.
6. **Workload-mix guardrail**: report is *always* stratified, never a global
   mean. A reviewer's stats are shown per
   `role × complexity × phase_kind × risk_tag` bucket.

### Gotchas and Goodhart safeguards

- **Correlated reviewers are not independent evidence.** If two agents share
  `prompt_bundle_hash` prefixes (same shared.md) their agreement is not
  confirmation. Report flags this by tagging lanes as
  `independence: full | partial | shared-upstream`.
- **Output-cap distortion.** If `cap_hit=true`, the finding count is a
  lower bound. Stats must use "cap-hit-aware means" — don't compute "mean
  findings/phase" over runs with `cap_hit=true` mixed with runs without.
- **Survivorship bias.** Reports include a "runs excluded" counter (schema
  failures, timeouts, 429s, budget breaches) with reasons. Never filter these
  silently.
- **Rare-critical reviewers look bad on means.** Add a `p95_severity` column:
  the 95th-percentile severity of each lane's TP findings, per-bucket. A lane
  with low count but high p95 severity stays.
- **Duplicate ≠ noise.** Report distinguishes convergent-TP (two reviewers
  found the same real bug — *confirmation signal*) from duplicated-FP (same
  incorrect claim — actual noise).
- **Maintainer action ≠ correctness.** Kept as a separate column; never
  collapsed into a TP proxy. The adjudication ledger is the only correctness
  source.

### Retention and privacy — pre-shipment decision required

Raw findings contain file paths, code snippets, and model-generated critique of
in-progress code. At minimum this is sensitive; depending on repo contents it
may be secret. Decide before shipping to operators outside mstefanko's own
workflow:

- **Retention window** per ledger (runs: 90d default? findings: 180d? outcomes:
  1y? adjudications: indefinite?). Beyond the window, summarize into aggregate
  counters; drop row-level detail.
- **PII / secret scrubbing** on append. Run a regex pass before writing
  `short_summary` / `rationale` to strip obvious secrets (API key shapes,
  emails). Not bulletproof — must document that the ledger may still contain
  sensitive substrings and advise operators accordingly.
- **Cross-repo tier.** Repos tagged as sensitive may require the telemetry to
  be emitted with redacted `file` paths (directory hash rather than path).

This is a pre-shipment gate, not a Phase 1 task — but flag it here so it's
visible when the plugin is first packaged.

### Prerequisites before this layer is useful

1. `/swarm-do` plugin shipped with `bin/swarm-run` writing structured runs +
   findings JSONL (Part 3 Phase 2 + Part 4 Phase 9).
2. `backends.toml` per-role config loading verified (§1.7 config contract).
3. At least one reviewer lane producing structured findings reliably on a real
   workload (Phase 1 — codex-review in swarm).
4. Duplicate rule v1 is pinned and SQLite indexer stamps
   `duplicate_cluster_id` deterministically.
5. Retention/privacy decision logged in ADR form (proposed: `${CLAUDE_PLUGIN_ROOT}/docs/adr/0001-telemetry-retention.md`).

### Sequencing

1. **First** — ship `runs.jsonl` emission (§1.8 requires it anyway).
2. **Second** — ship `findings.jsonl` extractor so the reviewer-overlap join
   doesn't require re-parsing raw run dirs.
3. **Third** — ship `bin/swarm-telemetry` as a report generator (read-only).
   Recommendations only; no auto-controller.
4. **Fourth** — nightly outcome-join job (beads + git log integration).
5. **Fifth** — SQLite indexer + FTS5. Deferrable until JSONL scan performance
   justifies it.
6. **Ongoing** — monthly blinded adjudication on sampled findings refreshes
   the reviewer scorecard.

---

## Section 1.10 — Swarm presets + pipeline registry (swappable architectures)

**Motivation.** §1.7 configures **which backend** runs each role. This section
adds **which pipeline shape** runs the roles in the first place — so operators
can swap the whole orchestration topology as easily as they swap a backend. A
single concept called a **swarm preset** bundles both: a routing matrix + a
named pipeline + optional model/effort overrides. Drop in a new preset file,
run `swarm preset load <name>`, and the swarm reshapes.

**Motivating examples:**
- "Ultra Plan" (https://www.mindstudio.ai/blog/claude-code-ultra-plan-multi-agent-architecture) — 3 parallel exploration agents + 1 critique agent, replacing the linear analysis stage.
- "Competitive writer" — 2× writer (Claude + Codex) + judge, for risky phases.
- "Lightweight" — skip spec-review + docs stages, for minor changes.
- "All-codex" — routing matrix flips every delegatable role to Codex (orchestrator + synthesizer stay Claude per invariant).

### Architecture — presets bundle routing + pipeline

A **preset** is a single TOML file that references a pipeline YAML:

```toml
# ${CLAUDE_PLUGIN_ROOT}/presets/ultra-plan.toml  (stock)
# or
# ${CLAUDE_PLUGIN_DATA}/presets/my-experiment.toml  (user)

name = "ultra-plan"
description = "3 parallel exploration agents + 1 critique for planning stages"
pipeline = "ultra-plan"               # references pipelines/ultra-plan.yaml
origin = "stock"                      # stock | user | experiment

[routing]                             # overrides on top of the default backends.toml matrix
"roles.agent-analysis.hard" = { backend = "claude", model = "claude-opus-4-7", effort = "xhigh" }

[budget]                              # ceilings enforced by dry-run and /swarm-do:do run start
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
```

A **pipeline** is a YAML file declaring stages and their dependency DAG. Concurrency is expressed in exactly one way: **stages with the same `depends_on` set run in parallel; a stage runs as soon as all its declared dependencies complete.** No `parallel_with`, no `all-parallel` merge strategy — parallelism is topology, not an adjacent flag.

```yaml
# ${CLAUDE_PLUGIN_ROOT}/pipelines/ultra-plan.yaml
pipeline_version: 1
name: ultra-plan
description: 3 parallel exploration agents + 1 critique

stages:
  - id: research
    agents:
      - role: agent-research

  - id: exploration
    depends_on: [research]
    fan_out:
      count: 3
      variant: prompt_variants                     # same | prompt_variants | models
      variants: [explorer-a, explorer-b, explorer-c]
    merge:
      strategy: synthesize                          # synthesize | vote
      agent: agent-analysis-judge
    failure_tolerance:
      mode: quorum                                  # strict | quorum | best-effort
      min_success: 2                                # required iff mode=quorum

  - id: writer
    depends_on: [exploration]
    agents:
      - role: agent-writer

  - id: spec-review
    depends_on: [writer]
    agents:
      - role: agent-spec-review

  # review and docs declare the same depends_on, so they run in parallel
  - id: review
    depends_on: [spec-review]
    agents:
      - role: agent-review

  - id: docs
    depends_on: [spec-review]
    agents:
      - role: agent-docs
```

### Pipeline DSL schema freeze

Pinning the one canonical encoding so schema lint (validation gate 1) has a concrete target. Any other shape is a schema-lint failure.

**Stage object:**
```
stage = {
  id            : string   # unique within pipeline
  depends_on    : array of stage ids, default []    # empty ⇒ runs at DAG root
  agents        : array of agent-refs, default []   # one-per-stage execution
  fan_out       : fan-out object, optional          # if present, `agents` must be absent
  merge         : merge object, required iff fan_out is present
  failure_tolerance : failure-tolerance object, default {mode:"strict"}
}
```

**Exactly one of `agents` OR `fan_out` per stage.** If you want both parallel agents and fan-out variants, use two stages with the same `depends_on`.

**Fan-out object:**
```
fan_out = {
  count    : integer (1..10)
  variant  : enum("same" | "prompt_variants" | "models")
  variants : array of strings (required iff variant=="prompt_variants"; length must == count)
  routes   : array of route objects or named preset routes (required iff variant=="models"; length must == count)
}
```

For `variant: models`, each route is a full backend route, not just a model ID:

```
route = {
  backend : enum("claude" | "codex")
  model   : string
  effort  : enum("none" | "low" | "medium" | "high" | "xhigh")
}
```

This keeps `compete.yaml` expressible as "Claude writer + Codex writer" without inferring provider from model-name strings.

**Merge object:**
```
merge = {
  strategy : enum("synthesize" | "vote")
  agent    : agent-role-name (required iff strategy=="synthesize"; must be Claude-backed)
}
```
(`all-parallel` is removed. "All outputs pass through without merging" is expressed by omitting `merge` and having downstream stages consume each fan-out branch explicitly — out of v1 scope; fan-out stages always have a merge.)

**Failure-tolerance object (structured, not string):**
```
failure_tolerance = {
  mode        : enum("strict" | "quorum" | "best-effort")
  min_success : integer (required iff mode=="quorum"; must be 1..count for fan-out stages)
}
```
- `strict`: all N must succeed (default).
- `quorum` with `min_success: N`: continue if ≥N succeed; merge sees successful outputs only.
- `best-effort`: continue with whatever succeeded (including zero); merge/downstream must handle empty input.

**Agent-ref object:**
```
agent_ref = {
  role   : agent-role-name
  backend: enum("claude" | "codex"), optional
  model  : string, optional     # overrides active routing for this stage only
  effort : enum, optional
}
```

**Engine schedules stages via DAG:**
1. Compute topological layers from `depends_on`.
2. Each layer executes in parallel — `bd --claim` acquires per-stage issues simultaneously.
3. Fan-out stages spawn `fan_out.count` sibling issues all depending on upstream + all blocking the same merge issue.
4. Merge stage starts when its fan-out predecessor satisfies `failure_tolerance`.
5. Cycle detection (validation gate 4) rejects any pipeline whose DAG has cycles.

**Engine boundary:** deterministic helpers own parsing YAML, validating schema, resolving routes, computing topological layers, estimating budget, and creating/edging beads issues. The Claude `/swarm-do` skill remains the dispatcher for Claude Code `Agent()` calls; shell/Python helpers do not try to invoke Claude subagents directly. External CLI-backed providers (Codex today, MCO or Gemini later) are invoked through provider helpers and write results back to beads for the Claude dispatcher to merge into the pipeline state.

**Resolution order** (in `bin/swarm-run`, extending §1.7):
1. Operator flags: `--backend`, `--model`, `--effort`, `--preset`, `--pipeline`
2. Active preset: `${CLAUDE_PLUGIN_DATA}/current-preset.txt` (single line with preset name)
3. Preset's `[routing]` overrides
4. Base matrix in `backends.toml`
5. Role default
6. Hardcoded default (`claude-opus-4-7 / high`)

**Default on install: no active preset.** `${CLAUDE_PLUGIN_DATA}/current-preset.txt` starts empty. Resolution falls back to `backends.toml` alone, which per §1.7 is Claude-primary everywhere until the operator records per-role measurements. This preserves the measurement gate — `balanced` is available but never auto-activated.

The existing `swarm mode claude-only | codex-only | balanced | custom` is a shortcut for `swarm preset load <name>`. `swarm mode custom` = `swarm preset clear` (no active preset; `backends.toml` alone drives routing). Operators who never touch presets see the same behavior as before §1.10.

### Validation gates — pipelines are code

User-authored pipelines can spawn 20 agents, burn a day's quota in one run, or route the orchestrator to Codex. **"Find one online and drop it in" is supply-chain risk.** Validation is hard, not loose. Structural gates run at preset load; plan-dependent budget gates run at dry-run and `/swarm-do:do` run start because they need the plan's phase count and complexity. There is no `--force` bypass for structural invariants or budget ceilings; overriding budget requires editing the preset file itself, which makes the decision owner-attributable in the YAML rather than a per-invocation flag. Gates, in order:

1. **Schema lint** — JSONSchema at `swarm-do/schemas/pipeline.schema.json` (pipelines) and `preset.schema.json` (presets). Required fields, typed enums per §1.10 "Pipeline DSL schema freeze" below. Fail on unknown top-level keys (no forward-compat silent ignore).
2. **Role existence check** — every referenced `agent-X` resolves to a role file in `swarm-do/agents/`. No phantom roles.
3. **Invariant guard — hard reject, unoverrideable:**
   - Pipeline cannot route `orchestrator` (the `/swarm-do` skill itself runs in Claude; this is structural)
   - Pipeline cannot route `agent-code-synthesizer` to non-Claude backend (highest-risk merge step, pinned by §1.7)
   - Fan-out merge strategy `synthesize` requires `agent` to be Claude-backed
   - Violation = loader refuses to activate the preset, with a clear error. TUI also refuses to save an invariant-violating config (no force-save). The loader never sees invariant-violating state because the save path prevents it.
4. **Cycle detection** — beads dependency graph is a DAG check. Stages with `depends_on` edges form an explicit DAG; any cycle = reject.
5. **Budget ceiling — hard reject at dry-run and run start:** `swarm preset dry-run <name> <plan-path>` and `/swarm-do:do <plan-path>` estimate agent count + token cost + critical-path latency, compare against the preset's declared `[budget]` block, and refuse to start if any ceiling is exceeded. `swarm preset load <name>` cannot enforce this gate because it has no plan path. No `--force-over-budget` flag exists. To exceed a ceiling the operator must edit the preset's `[budget]` block to declare the higher limit explicitly — the preset file itself becomes the authorization record.

**Cost preview is emitted on every `swarm preset dry-run` invocation** regardless of pass/fail, so the operator always sees the numbers. Gate 5 is the budget-enforcement side of that same output.

**Backend resolver:** validation and runtime use the same resolver for `(role, complexity)` and per-stage route overrides: operator flags → active preset routing → `backends.toml` → role default → hardcoded default. The invariant guard asks the resolver whether a role is Claude-backed; it must not match literal model-name strings. Phase 10a ships the minimal resolver needed by validation, and later runtime work wires `bin/swarm-run` to the same contract.

**Distinction — advisory warnings vs. hard rejects.** The five gates above are structural/correctness/supply-chain concerns and are never bypassable. Advisory warnings (e.g., "this preset routes a role to an untested model lane", "pipeline version is 2 steps behind stock") are printed on load but don't block. Only advisory warnings can be suppressed via `--quiet` or "dismissed" in the TUI. Structural invariants have no dismiss path.

### Failure tolerance semantics

Fan-out stages must declare what "partial success" means. Three modes:

- **`strict`** — all N agents must succeed. Any failure halts the pipeline.
- **`N-of-M`** (e.g. `2-of-3`) — pipeline continues if at least N succeed. Merge stage sees only the successful outputs.
- **`best-effort`** — pipeline continues with whatever succeeded, including zero. Merge stage must handle empty input.

Default: `strict`. Operators must opt into looser tolerance per stage.

### Fan-out variant semantics

Pinned enum values (prevents ambiguity):

- **`same`** — same agent, same prompt, different seeds. Lowest-variance exploration.
- **`prompt_variants`** — same role, different prompt overlay files. Requires `variants: [name, name, ...]` listing files in `swarm-do/roles/<role>/variants/`.
- **`models`** — same prompt, different resolved backend routes. Requires `routes: [{backend, model, effort}, ...]` or named preset routes. Bare model IDs are invalid because they cannot distinguish Claude vs Codex execution.

Combining variants (e.g. different prompts AND different models) is out of v1 — declare two stages instead.

### Versioning + evolution

Stock pipelines update over time. Users who forked a stock preset need visibility.

- Every pipeline YAML has `pipeline_version: N`
- Every preset TOML records the stock hash it diverged from: `forked_from_hash = "sha256:..."` (populated automatically when user does `swarm preset save <new> --from stock`)
- `swarm preset diff <name>` shows stock-vs-user delta in routing matrix and pipeline reference
- On stock update: `swarm preset list` flags user presets with `fork-outdated` if the upstream pipeline version changed since fork

### Telemetry integration

Ledger schema (§1.8) gains two fields per `runs.jsonl` row:
- `preset_name` — active preset at run time
- `pipeline_name` + `pipeline_hash`

This unlocks the evaluation loop: "does `ultra-plan` produce fewer post-merge hotfixes than `default`, stratified by phase_kind?" — queryable from `index.sqlite` (§1.9) once enough runs accumulate.

Without this, pipeline choice stays vibes. With it, pipeline choice becomes data-driven.

### Stock presets + pipelines shipped with v1

| Preset name | Pipeline | Purpose |
|---|---|---|
| `balanced` | `default` | §1.7 matrix — Codex for docs/spec/clarify/simple-writer, Claude elsewhere |
| `claude-only` | `default` | Every role routed to Claude (emergency fallback if Codex quota is gone) |
| `codex-only` | `default` | Every delegatable role routed to Codex (orchestrator + synthesizer stay Claude per invariant) |
| `ultra-plan` | `ultra-plan` | 3 explorers + 1 critique for planning stages |
| `competitive` | `compete` | 2× writer (Claude + Codex) + judge — existing Pattern 5 trigger |
| `lightweight` | `lightweight` | Skip spec-review + docs — for minor changes / small PRs |

User presets live alongside in `${CLAUDE_PLUGIN_DATA}/presets/`. Stock presets are read-only from the plugin install dir.

### What's explicitly NOT in v1

- **Mid-flight pipeline modification.** "Change the pipeline for this run only, without a file edit" — tempting, deferred. Workflow is: edit YAML, save under new name, re-run. Keeps state model tractable.
- **Dynamic pipeline composition.** "Use `ultra-plan` analysis but `default` writer" — would require fragment composition. v1 is whole-pipeline only; users who want combinations author a new YAML.
- **Community preset marketplace.** A discovery/install flow for presets shared by others. Exciting, multiplies the supply-chain problem. v1 ships stock + user-local only.
- **Conditional stages.** "If writer flags high-risk, insert competitive writer stage." Doable but adds a runtime-condition evaluator to the pipeline engine. Defer until we see the need.

### Prerequisites before §1.10 lands

1. `/swarm-do` plugin shipped (packaging Phase 7 verified).
2. A shared backend resolver exists for `{backend, model, effort}` per-role (§1.7 config contract); Phase 10 wires validation first, then runtime.
3. Telemetry ledgers writing `runs.jsonl` / `findings.jsonl` (§1.8, packaging Phase 9a/9b) — so pipeline comparison queries work.
4. At least one non-default pipeline authored + validated (ultra-plan is the obvious first target).
5. Invariant-guard unit tests in place before any operator loads a user preset.

### Sequencing within §1.10

1. **Preset + pipeline schemas frozen** (JSONSchema + sample YAML) plus the minimal backend resolver contract validation needs. ~0.5-1 day.
2. **Pipeline engine refactor** — orchestrator skill becomes data-driven dispatch reading pipeline YAML. Fan-out + merge + failure-tolerance runtime. ~2–3 days. Biggest chunk.
3. **Validation gates** — schema lint, role existence, invariant guard, cycle detection, budget preview. ~2–3 days. Not optional.
4. **Preset loader + `bin/swarm` subcommands** (`swarm preset load/save/diff/list`, `swarm pipeline show/lint/list`). ~1 day.
5. **Stock presets + pipelines** (`balanced`, `claude-only`, `codex-only`, `ultra-plan`, `competitive`, `lightweight`). ~1 day.
6. **Telemetry integration** — add `preset_name` + `pipeline_name` + `pipeline_hash` to runs.jsonl. ~0.5 day (piggybacks on §1.9).
7. **Invariant enforcement ADR** — documents which invariants are hard rejects, why. ~0.5 day.
8. **TUI integration** — Presets + Pipelines screens (per §1.8 v1 interface). Folds into TUI packaging phase.

**Total effort: ~1.5–2 weeks** of careful work. Validation gates (step 3) are the most skip-tempting and the most important.

---

## Section 1.11 — Post-Phase-10 patterns to borrow without expanding the maintenance surface

Phase 10 shipped the local preset/pipeline registry. Section 1.11 is the next
planning layer: borrow only patterns that fill measured swarm-do gaps while
preserving the current ownership model. Beads remains the task state. `/swarm-do`
owns pipeline state. Telemetry is the measurement surface. Structural invariants
remain hard rejects.

Validated 2026-04-24 against:
- Local implementation: current pipeline schema and validators allow `agents`
  or `fan_out` stages only; there is no provider-stage contract yet.
- Superpowers: current workflow emphasizes bite-sized plans, exact file/test
  steps, fresh subagents, and two-stage spec-then-quality review
  (https://github.com/obra/superpowers).
- metaswarm: current workflow emphasizes plan/design gates, work-unit
  decomposition, BEADS-backed state recovery, cross-model review, PR shepherding,
  and knowledge extraction (https://github.com/dsifry/metaswarm).
- MCO: current README advertises multi-provider fan-out across Claude, Codex,
  Gemini, OpenCode, and Qwen; `mco doctor`; JSON/SARIF/Markdown output;
  consensus fields; debate/divide modes; timeouts; and extensible provider
  adapters (https://github.com/mco-org/mco).

### Decision

Use MCO as the first post-10 integration candidate, but only as an optional
read-only stage provider. Do not make it a second orchestrator. Do not let it
own beads issues, pipeline state, routing state, memory, merges, or quality gate
decisions.

Superpowers and metaswarm are worth mining, but the winning patterns are
discipline and lifecycle contracts, not their whole workflow engines. The
highest-value steals are:

- From Superpowers: decomposition into exact, bounded work units; spec review
  before quality review; fresh subagent context hygiene; verification-before-
  completion as an explicit task contract.
- From metaswarm: hard-plan review gates, external dependency preflight, work
  unit dependency graphs, recovery/status views over persisted beads state, and
  small post-run knowledge capture.
- From MCO: external provider health checks, parallel provider execution,
  output normalization, consensus/dedupe, debate/divide modes, and
  machine-readable artifacts.

Rejected for now: importing Superpowers wholesale, replacing swarm-do with
metaswarm, full PR shepherd automation, recursive orchestration by default,
letting MCO own beads/pipeline state, community preset marketplaces, global hard
TDD, and mandatory 100% coverage. Each expands the maintenance surface before
measured swarm-do value is proven.

### Adoption filter

Borrow a pattern only if it passes all checks:

1. It addresses a recurring swarm-do workflow gap already visible during
   operator use.
2. It can be expressed as a pipeline stage, role contract, or CLI helper without
   rewriting the orchestrator.
3. It has an obvious telemetry hook so value can be measured.
4. It does not add a second source of truth for task state, routing state,
   pipeline state, memory, or quality gates.
5. It can ship behind a stock opt-in preset or experimental command before it
   changes the default pipeline.

Patterns that fail these checks stay as references, not implementation work.

### MCO validation plan

The open question is not "can swarm-do shell out to MCO?" It can. The question is
whether a third stage kind, `provider`, earns its schema, validation, telemetry,
and operator UX cost.

Run a two-part spike before committing to the provider-stage DSL:

1. **CLI contract spike, outside the pipeline engine.**
   - Confirm `mco doctor --json` reports installed/authenticated providers with
     stable machine-readable status.
   - Confirm `mco review` can run read-only against this repo with an explicit
     prompt file, selected providers, hard timeout, no memory by default, and
     JSON output suitable for downstream parsing.
   - Confirm MCO does not write repo files in review mode unless explicitly
     configured to do so.
   - Capture exit-code behavior for all-provider success, partial provider
     failure, provider auth failure, timeout, malformed output, and no findings.

2. **Adapter contract spike, still not in stock pipelines.**
   - Prototype `bin/swarm-stage-mco` as a private helper that accepts a prompt
     file, repo path, provider list, command mode, timeout, output directory, and
     run metadata.
   - Store raw MCO output under the swarm run directory, never in beads as the
     only copy.
   - Normalize read-only review findings into a draft `findings.v3` shape with
     `provider`, `provider_count`, `detected_by`, `consensus_score`,
     `consensus_level`, `source_artifact_path`, and `provider_error_class`.
   - Verify duplicate hashes remain stable across MCO and native
     `agent-codex-review` findings for the same file/line/summary.

Go/no-go gate for adopting `provider` stages:

- **Go** if MCO produces parseable JSON in at least 95% of read-only review runs,
  fails closed on malformed output, classifies provider failures clearly, keeps
  repo writes disabled in review mode, and surfaces at least one useful
  consensus/dedupe field swarm-do would otherwise have to build.
- **No-go / defer** if MCO output is unstable, health checks are not reliable
  enough for `swarm providers doctor`, review mode writes files unexpectedly, or
  consensus fields cannot be mapped cleanly into telemetry without lossy
  special cases.

### Provider-stage design, if the spike passes

Extend the pipeline DSL with a third mutually exclusive stage kind:

```yaml
- id: cross-model-review
  depends_on: [writer]
  provider:
    type: mco
    command: review
    providers: [codex, gemini]
    mode: debate
    strict_contract: true
    output: findings
    memory: false
    timeout_seconds: 1800
  failure_tolerance:
    mode: quorum
    min_success: 1
```

Validation changes:
- `agents`, `fan_out`, and `provider` are mutually exclusive.
- `provider.type` is an enum; v1 only allows `mco`.
- `provider.command` is `review` or `run`; v1 stock pipelines use `review` only.
- `provider.providers` is a non-empty list with a small max, default max 5.
- `provider.memory` defaults to false and must be explicit to enable.
- Provider stages cannot use `merge.strategy=synthesize`; Claude remains the
  downstream synthesizer through an ordinary Claude-backed stage.
- Budget preview counts provider branches separately from Claude/Codex agents.
- Dry-run prints provider count, selected providers, timeout, estimated
  wall-clock, and artifact destination.

Runtime boundary:
- Swarm-do creates the beads issue and assembles the prompt from upstream notes,
  diffs, relevant tests, and the verification contract.
- `bin/swarm-stage-mco` invokes MCO, writes raw artifacts, normalizes findings,
  and emits one machine-readable stage result.
- The Claude orchestrator decides what to do with the evidence. MCO results are
  inputs, not automatic accept/reject decisions.

### Implementation order

1. **ADR: external provider stage contract.** Document the provider boundary,
   why MCO is an adapter rather than an orchestrator, read-only-first scope, and
   telemetry/versioning implications.
2. **Provider doctor.** Add `swarm providers doctor` with local backend checks
   plus optional `mco doctor --json` passthrough. This is useful even if the
   provider-stage spike later fails.
3. **MCO adapter spike.** Build `bin/swarm-stage-mco` and a Python parser behind
   tests using captured fixture outputs. Keep it unreachable from stock
   pipelines until the go/no-go gate passes.
4. **Telemetry draft.** Add `findings.v3` or a provider-findings schema rather
   than mutating frozen v1/v2 schemas. Include consensus and provenance fields.
5. **Experimental provider DSL.** Add schema/validation/graph rendering support
   for `provider` stages, guarded by tests and an experimental stock pipeline
   such as `mco-review-lab`.
6. **One opt-in pipeline.** Ship a read-only `mco-review-lab` preset that runs
   after `writer` and before Claude `agent-review`. No default activation.
7. **Compare against hybrid-review.** Run at least 20 real dogfood phases with
   both `hybrid-review` and `mco-review-lab`, then compare useful-findings rate,
   false-positive rate, timeout/failure rate, cost, and operator intervention.
8. **Promote or retire.** Promote only if MCO improves useful findings or
   provider resilience enough to justify the new stage kind. Otherwise keep
   `swarm providers doctor` and retire the provider DSL before it hardens.

### Superpowers pattern plan

Implement as role and pipeline contracts, not as a second workflow engine:

1. Add an `agent-analysis` output mode for `bounded_work_units`:
   `id`, `goal`, `file_scope`, `allowed_files`, `blocked_files`,
   `dependencies`, `commands`, `expected_results`, `done_when`,
   `risk_tags`, and `handoff_notes`.
2. Add a `decompose-plan` pipeline stage for hard phases that emits those work
   units read-only. The first version creates a decomposition artifact, not
   parallel implementation branches.
3. Tighten writer/reviewer prompts so each subagent receives only its task
   slice, upstream dependency notes, and verification contract.
4. Keep `agent-spec-review -> agent-review` as an invariant and cite
   Superpowers as supporting prior art.
5. Treat TDD as a configurable pipeline policy. Do not make it global because
   swarm-do also handles docs, config, generated artifacts, and cleanup work.

Validation:
- Measure worker reopen rate, review failure rate, time-to-first-useful-output,
  and number of "task too broad" clarifications before/after decomposition.
- Promote decomposition only if it reduces review churn without increasing
  merge conflicts or operator bookkeeping.

### metaswarm pattern plan

Mine lifecycle gates, not the whole lifecycle:

1. Add a `hard-plan-review` pipeline that runs feasibility, completeness,
   scope/alignment, security, and UX/API perspectives in parallel before writer
   work on hard/high-risk phases.
2. Add an `external-deps-check` stage before execution for API keys, CLIs,
   service credentials, local servers, package managers, and CI assumptions.
3. Represent decomposed work as beads child issues with explicit dependency
   edges only after the read-only decomposition artifact proves useful.
4. Improve `swarm status` / future `swarm recover` around existing beads and run
   artifacts before adding any new state store.
5. Add small structured knowledge capture after successful runs, tied to files,
   risk tags, and decisions. Retrieval must be selective and telemetry-friendly.

Deferred:
- PR shepherding waits until core run telemetry is stable.
- Recursive orchestration requires budget preview, depth limits, and explicit
  operator approval.
- Coverage thresholds are repo/preset config, not a swarm-do universal.

### Promotion scorecard

Each post-10 pattern needs a scorecard before becoming default:

- Useful finding rate or prevented-rework rate improves over the current
  pipeline.
- False positives and operator interventions do not rise materially.
- Timeout/provider failure behavior is observable and recoverable.
- Added schema/CLI/docs surface is small enough to test locally.
- The pattern can be disabled by switching presets, with no migration of beads
  state or telemetry history.

---

# Part 2 — Rollout strategy

Policy in Part 1 defines **what** the swarm routes and **how** it measures. Part 2 defines **when** each capability lands: Phase 0 pre-flight → Phase 0 experiment → Phase 1 (Codex review in the swarm) → Phase 2 (Pattern 5 / 6) → Phase 2.5 (manual fallback) → Phase 3 (B1 dispatcher). Each phase has its own go/no-go gate.

---

## Section 2.0 — Phase 0 pre-flight: harness and rubric cleanup

**Do not start the cohort until this section is green.** The harness exists but — verified against `bin/codex-review-phase` on 2026-04-22 — has six measurement-integrity issues. Fix them in a single cleanup pass before any phase is fed through the experiment. Running the cohort against the current harness would poison the blinded adjudication and force a redo.

### Fixes required in `bin/codex-review-phase`

1. **Remove the Claude-findings leak — CLOSED 2026-04-24.** The `## Claude-side findings (for duplicate_of_claude detection)` section has been removed from `bin/codex-review-phase`. Codex must not see Claude's findings during the run — duplicate detection is the adjudicator's job, computed **after** unblinding, using the §2 match rule (same file, same defect class, line references within ±3 lines). Each Codex finding is emitted with `duplicate_of_claude: unknown` unconditionally at run time.
2. **Resolve Mode A honestly.** Current Mode A lists changed-file *paths* (lines 167-172) but no contents. Pick one of:
   - **Option A1 (recommended):** inline the full contents of each changed file post-diff into the prompt under `## Changed file snapshots` (bounded by a max-bytes cap — truncate with a visible marker if exceeded). Keep the name "scoped review."
   - **Option A2:** leave Mode A as path-list + diff only, and rename it **"diff-only review"** in both the plan and the script's help text so the contract matches reality. The signal interpretation is different.
   Choose before the first cohort run and record the choice in the rubric.
3. **Post-process Codex output into a single schema-conforming object.** `codex exec --json` emits a JSONL event stream; redirecting it to `codex-review-<phase>-mode<X>.json` does not produce the `${CLAUDE_PLUGIN_ROOT}/phase0/result-schema.json` shape the rubric expects. Two acceptable approaches:
   - Switch to `--output-last-message <path>` so Codex writes only the final structured message, then read that file and fill top-level `phase_id`, `mode`, `model`, `effort` in a post-run pass.
   - Keep `--json` for event telemetry but capture events to `events.jsonl` (sidecar), extract the final assistant message via `jq`, validate it against the schema, and write the resulting object to the primary output file.
   Either way, write a **sidecar metadata file** (`meta.json`) alongside the primary output containing `wall_clock_seconds`, approximate `input_tokens` / `output_tokens` / `estimated_cost_usd` (parse from the event stream), `codex_version`, `model`, `effort`, and `mode`. Latency and cost must not live only in stderr.
4. **Mode B sandbox vs. test re-run contradiction.** The prompt currently invites test / linter re-runs (line 187) while the sandbox is `-s read-only`, which will fail any suite that writes caches, temp files, or coverage output. Pick one:
   - **Option B1 (recommended):** switch Mode B to `-s workspace-write -C <repo-root>` (still read-only to the rest of the disk; can write within the worktree). Keeps the "Codex may re-run tests" affordance meaningful.
   - **Option B2:** keep `-s read-only` and delete the "you may re-run tests" sentence from the prompt. Mode B becomes "read-only inspection" only.
   Record the choice; it changes what Mode B is actually measuring.
5. **Anonymize source attribution before adjudication.** Add a minimal blinding step before the adjudicator sees findings:
   - Merge Claude findings + Codex Mode A + Codex Mode B into one list per phase.
   - Strip obvious source-attribution tells: reviewer name, persona-specific phrasing, file paths that leak to only one reviewer, tool-specific output formatting.
   - Assign each finding an opaque ID (`F-001`, `F-002`, …) and shuffle.
   - Adjudicator rates TP / FP / ambiguous on the blinded list.
   - Unblind only after verdicts are locked to the finding IDs.
   The blinding step is small shell + `jq` — do not over-engineer it, but do not skip it either. The whole experiment depends on keeping the scoring boring.
6. **`agent-review.md` frontmatter.** Fix `description` to match the canonical chain in §1.5 Blocker 1 before the cohort runs.

### Artifact layout

Create one directory per phase per cohort date:

```
${CLAUDE_PLUGIN_DATA}/phase0/runs/<YYYY-MM-DD>/<phase-id>/
  inputs/
    diff.patch
    analysis-notes.md
    acceptance-criteria.md
    test-results.txt          # optional
    changed-snapshots/        # only if Option A1 selected
  claude/
    findings.json             # control: full default chain output
  codex-mode-a/
    findings.json
    events.jsonl
    meta.json
  codex-mode-b/
    findings.json
    events.jsonl
    meta.json
  adjudication/
    blinded-merged.json       # opaque IDs, no source attribution
    verdicts.json             # adjudicator-filled TP/FP/ambiguous
    unblinded.json            # verdicts joined with source attribution
  base-sha.txt
  head-sha.txt
```

Base / head SHAs are required so a rerun can reproduce inputs exactly.

### Latency and cost budgets (commit numbers before seeing results)

Replace the vague "acceptable for your `/do` cadence" with concrete targets. These are **pre-registered thresholds**, not post-hoc rationalizations:

- **Mode A** (every-phase candidate): median ≤ 60s, p90 ≤ 120s, cost ≤ $0.15/phase. Fails any of these → Mode A is not eligible for GO-EVERY-DO regardless of signal quality.
- **Mode B** (high-risk candidate): median ≤ 180s, p90 ≤ 300s, cost ≤ $0.50/phase. Allowed to be slower because it only runs on tagged phases.
- **Optional `xhigh` sensitivity rerun:** no budget cap; this is a separate question (does deeper reasoning change the verdict?), not a steady-state lane candidate.

### Cohort source

Use a **mix of historical and future phases**, with the following constraint: the "follow-up rework / hotfix happened later" bucket (at least 3 phases) must come from **historical** phases — you need the rework signal to already exist. The other buckets may come from either source. If you use future queued phases, run normal `/do` first and let it complete fully before running any Codex pass; Codex must not influence the writer during Phase 0.

### Historical phases missing artifacts — selection rule

Older phases often won't have `analysis-notes.md` or `acceptance-criteria.md` archived. The artifact layout's `inputs/` bundle is the experiment's fairness contract — every reviewer gets the same inputs. Fix rule, in priority order:

1. **Prefer phases with a complete inputs bundle** (diff, analysis notes, acceptance criteria, test results). These form the primary cohort.
2. **Where a historical phase is indispensable for the rework bucket** but missing non-diff artifacts, reconstruct from git/beads sources under these constraints:
   - `diff.patch` is always derivable from `git diff <base>..<head>` — never missing.
   - `analysis-notes.md`: reconstruct from the beads analysis issue's notes (`bd show <analysis-id>`). If no analysis issue exists, write a short note like `Reconstructed 2026-04-23: analysis did not pre-date this phase. Diff describes the work.` and include only that — do NOT invent intent that wasn't recorded.
   - `acceptance-criteria.md`: reconstruct from the spec-review issue's notes if one exists. Otherwise, write `Reconstructed 2026-04-23: no acceptance criteria were specified. Diff + tests are the only contract.` — again, do NOT invent.
   - `test-results.txt`: regenerate from `git stash; git checkout <head>; <test-command>` on a fresh worktree. If tests no longer pass on an old SHA (infrastructure drift), omit and note the reason in the phase's root `README.md`.
3. **If reconstruction is impossible for acceptance criteria AND analysis notes together**, exclude the phase from the cohort. Recording "reconstructed, no signal" twice is not the same as the real artifact — the reviewer would receive essentially nothing but the diff, which is a different experiment than "Mode A vs Mode B with full inputs."
4. **Mark reconstructed inputs explicitly.** Every reconstructed file gets a YAML frontmatter block:
   ```yaml
   ---
   reconstructed_on: 2026-04-23
   source: bd-analysis-id-123 | git log | reviewer-memory
   completeness: partial | notes-only | none
   ---
   ```
   Telemetry + adjudication can filter or weight on `completeness`. Reconstructed phases should stay <30% of the cohort; if more phases need reconstruction, the cohort's underlying signal is probably not informative enough to run.
5. **Document excluded phases** in `${CLAUDE_PLUGIN_DATA}/phase0/runs/<date>/excluded.md` with one line per exclusion and the reason. Keeps the experiment honest about selection bias in reporting.

If you cannot assemble a 12-phase cohort under these rules with ≥3 rework-bucket phases, delay Phase 0 until more recent phases accumulate the needed artifacts — do not dilute the experiment.

### Exit criteria for the pre-flight

Before starting the cohort:
- [x] Claude-findings block removed from `codex-review-phase` prompt assembly.
- [ ] Mode A option selected (A1 snapshots vs A2 diff-only rename) and implemented.
- [ ] Codex output post-processed into a single schema-conforming object; sidecar `meta.json` with latency and cost emitted.
- [ ] Mode B sandbox option selected (B1 workspace-write vs B2 inspection-only) and prompt language matches.
- [ ] Blinding pipeline (merge → strip attribution → opaque IDs → shuffle) exists as a small script, tested on a throwaway example.
- [ ] `agent-review.md` frontmatter corrected.
- [ ] Latency / cost budgets committed in writing in the rubric template.
- [ ] Cohort list (12-15 phase IDs) selected, with the historical-rework bucket identified.
- [ ] Artifact directory for the cohort date created.

When every box is checked, start §2.

---

## Section 2 — Phase 0: Validation experiment (1-2 evenings)

Before committing to any long-term architecture, prove cross-model review actually adds value on your codebase.

**What to build:** One manual Codex review harness, invoked directly via Codex CLI first. Do **not** start by depending on `codex-subagents-mcp` for validation — that repo is archived and should be treated as an optional convenience layer, not the foundation of the experiment.

**Phase 0 must answer two questions separately:**
1. Does GPT-5.4 add meaningful reviewer signal on your codebase?
2. What is the **minimum** context / runtime needed for it to add that signal?

That means Phase 0 should compare a cheap scoped review against a richer repo-aware review, not just run one vaguely-defined Codex pass.

**Setup:** Complete §2.0 pre-flight first — the harness and rubric cleanup pass is a precondition, not a bonus. Once that is green, Phase 0 runs against the corrected harness with the following contract:

1. The wrapper (`bin/codex-review-phase`, cleaned per §2.0) runs **two modes** against the same completed phase:
   - **Mode A — Scoped review** (or "Diff-only review" if §2.0 Option A2 was chosen)
     - writer diff
     - analysis notes
     - spec-review acceptance criteria
     - test commands / results
     - full changed-file snapshots (only if §2.0 Option A1 was chosen)
     - **No Claude findings — the prompt never sees the control output.**
   - **Mode B — Repo-aware review**
     - everything from Mode A
     - sandbox per §2.0 Option B1 or B2 (workspace-write + test re-run, or read-only inspection)
2. Invoke Codex directly:
   - `codex exec --json` with an explicit review prompt plus `--output-schema` and the post-processing pipeline described in §2.0 fix #3
   - direct shell invocation only; no MCP wrapper in Phase 0
   - `-m gpt-5.4 -c model_reasoning_effort="high"` passed explicitly on every invocation — never inherit from `~/.codex/config.toml`
3. Every invocation produces: `findings.json` (schema-conforming), `events.jsonl` (sidecar), `meta.json` (latency, token counts, cost, model, effort, mode). Findings schema: `finding_id`, severity (`critical | warning | info`), category (`types|null|boundary|security|performance|design|test`), `file:line`, short rationale, `duplicate_of_claude: unknown` (unconditional — the adjudicator computes duplicates post-unblinding).
4. `~/.claude/agents/agent-codex-review.md` persona stays as-is:
   - "terse, blocking-issues-only reviewer focused on types, null/edge cases, off-by-one, security"
   - Max 5 findings, no nits, no style feedback, no speculative comments without `file:line` support
   - Input contract for Mode A and Mode B matches §2.0.

**Test protocol (manual trigger, not every /do yet):**
- Pick **12-15 representative phases** stratified on purpose:
  - 3 bug phases
  - 3 feature phases
  - 2 refactor phases
  - 2-4 high-risk phases (security boundary, parser/data transformation, tricky business logic, heavy nullability / edge handling)
  - at least 3 phases from a "follow-up rework / hotfix happened later" cohort (**must be historical** — the rework signal has to already exist)
  - overlap is allowed; a single phase may satisfy more than one bucket
- Cohort source: historical phases, future queued phases, or a mix — see §2.0 "Cohort source".
- Run each /do as today first. Do **not** let Codex influence the writer during Phase 0.
- For each completed phase, run:
  - the full default Claude review chain (`agent-spec-review` + `agent-review`) as control — see §1.5 Blocker 1. Optional `agent-code-review` is excluded from the control unless it ran as part of that phase's normal execution.
  - Codex Mode A
  - Codex Mode B
- Rubric is **pre-registered** in `${CLAUDE_PLUGIN_ROOT}/phase0/rubric-template.md` (populated per §2.0 exit criteria) and covers:
  - what counts as a true positive
  - what counts as a false positive
  - what counts as ambiguous
  - what counts as the "same defect" across reviewers
- Use **blinded adjudication** per the pipeline in §2.0 fix #5:
  - merge Claude + Codex Mode A + Codex Mode B into one list per phase
  - strip source-attribution tells, assign opaque `F-NNN` IDs, shuffle
  - rate TP / FP / ambiguous on the blinded list
  - unblind only after verdicts are locked to the opaque IDs
- Duplicate / overlap match rule (applied by adjudicator post-unblind, **never** shown to Codex during the run):
  - same file
  - same defect class
  - line references within ±3 lines
- Record results in a simple comparison table per phase after unblinding (fields sourced from `meta.json` sidecars, not stderr):
  - `phase_id`
  - phase kind
  - model + effort used
  - did Claude find it?
  - did Codex Mode A find it?
  - did Codex Mode B find it?
  - adjudication (`true positive | false positive | duplicate | ambiguous`)
  - marginal latency for A (median and p90 reported at cohort level)
  - marginal latency for B (median and p90 reported at cohort level)
  - approximate cost for A
  - approximate cost for B
- Human adjudication rule:
  - A finding only counts as "unique real issue" if it is both real **and** not already captured by the current Claude review path.
  - Duplicate wording of the same root issue does **not** count as incremental value.
  - If the reviewer cannot confidently label a finding true/false, mark it ambiguous and exclude it from the go/no-go numerator.

**Decision criteria for continuing (original harness plan):**
- **GO-EVERY-DO:** Mode A catches ≥1 non-overlapping real issue in ≥30% of phases, noise rate stays <2 false flags per phase, **and** Mode A meets the §2.0 budgets (median ≤ 60s, p90 ≤ 120s, cost ≤ $0.15/phase). Miss any of those budgets → not eligible for GO-EVERY-DO.
- **GO-TARGETED:** Mode A fails (signal or budget), but Mode B hits the signal threshold with acceptable noise **and** meets the §2.0 Mode B budgets (median ≤ 180s, p90 ≤ 300s, cost ≤ $0.50/phase). Continue to Phase 1 only for tagged high-risk phases first — not every `/do`.
- **NO-GO:** both modes show heavy overlap, noise > signal, or neither mode meets its budget.

**2026-04-24 update:** the initial experiment round ended with a fourth operational decision: **DOGFOOD**. That means the standalone harness has done enough for now, and Phase 1 should move into the actual plugin as an opt-in lane so real `/swarm-do` usage generates better data than more isolated runs. This does **not** mean `GO-EVERY-DO`; it explicitly avoids default-on review until normal plugin telemetry shows the lane is worth promoting.

**Optional effort sensitivity check (keep small):**
- If Phase 0 is borderline on the high-risk subset, rerun at most 3 high-risk phases with `gpt-5.4` at `xhigh`.
- Treat this as a separate data point:
  - did `xhigh` improve unique true positives enough to justify the extra latency / cost?
- Do **not** mix `high` and `xhigh` results into one baseline bucket.

**Deliverable at the end of Phase 0 — one persisted decision record:**

Write the decision to `${CLAUDE_PLUGIN_DATA}/state/rollout-status.json` as a single JSON object (merged into the broader rollout-state schema defined in Part 5):

```json
{
  "phase_0": {
    "decision": "GO-EVERY-DO | GO-TARGETED | NO-GO | DOGFOOD",
    "selected_mode": "A | B | plugin | none",
    "decided_on": "2026-04-24",
    "cohort_run_date": null,
    "notes": "initial experiments complete; learn from opt-in plugin dogfooding before default-on automation"
  }
}
```

Enum semantics (these are the authoritative names used everywhere in this plan):

- **`GO-EVERY-DO`** + `selected_mode: "A"` — Phase 1 wires Codex Mode A (scoped review) into every `/swarm-do:do` after spec-review. Triggered on all phases unless labeled `kind:bug` or `review:skip-codex`.
- **`GO-TARGETED`** + `selected_mode: "B"` — Phase 1 wires Codex Mode B (repo-aware review) into `/swarm-do:do` for phases labeled `risk:high` only. Unlabeled phases do NOT get Codex review. Mode A is NOT concurrently active in this lane — Phase 0 produces one selected mode, not a matrix.
- **`DOGFOOD`** + `selected_mode: "plugin"` — Phase 1 ships as an opt-in plugin preset/pipeline. Operators enable it with `swarm preset load hybrid-review` or an explicit `/swarm-do:do --codex-review on`-style override once that flag is parsed by the orchestrator. Default runs stay on the normal pipeline.
- **`NO-GO`** + `selected_mode: "none"` — Phase 1 does not ship. Codex review stays in the manual fallback track only.

The prior prose outcomes (`scoped-review is good enough` / `repo-aware review is required` / `stop here`) are retired — they mapped 1:1 to the enum above but left the persistence contract ambiguous.

**Phase 1 reads `phase_0.decision` + `phase_0.selected_mode` to decide what to wire.** `DOGFOOD` authorizes opt-in plugin wiring only; it does not authorize default-on Codex review.

**Triggers:** Manual only. Do NOT wire into /do yet.
**Runs on every /do:** No.

## Section 3 — Phase 1: Codex review in swarm (dogfood lane first)

**What to build:**
- Promote `agent-codex-review` into the post-spec-review quality lane as a **specialized** reviewer, not a second generic reviewer.
- Add a stock `hybrid-review` preset/pipeline that keeps the default Claude review/docs lanes and adds a parallel Codex review after spec-review.
- Narrow its scope to failure modes Claude is most likely to miss or underweight: types, null / nil edges, off-by-one / boundary conditions, parser / serializer mismatches, and security boundaries.
- Cap output to blocking or clearly actionable findings only.
- Use beads **labels**, not metadata, for review routing:
  - `kind:bug`
  - `review:skip-codex`
  - `risk:high` — high-risk routing trigger for GO-TARGETED mode

**Who sets `risk:high` (and when):**

1. **`agent-analysis` is the primary writer.** As part of its normal output, analysis emits a `risk_label` field (enum: `low | moderate | high`) alongside the existing `complexity` field. If `risk_label == "high"`, the orchestrator applies `risk:high` to every child issue analysis creates (writer, spec-review, etc.). Analysis judges risk on: ambiguous spec, security boundary, parser/data-transformation, fragile business logic, concurrency/ordering, migration-without-rollback. Full heuristic lives in `agent-analysis.md`.
2. **Operator override always wins.** At `/swarm-do:do <plan> --risk high` time, the operator can force the label regardless of what analysis produces. Symmetric flag `--risk low` overrides analysis when it mis-reads a case as risky.
3. **Fallback when analysis doesn't emit the field.** For legacy plans or analysis outputs that predate the `risk_label` extension, `bin/swarm-run` treats absence as `risk_label=moderate` — which does NOT apply `risk:high`. In GO-TARGETED mode, absent-label = skip Codex review. This is the conservative default: a silent missing label never auto-triggers the extra lane.
4. **Label is queryable post-facto.** `bd list --label risk:high` is the operator's audit trail for which phases got the extra review. Telemetry's `risk_tags` column (§1.8) mirrors this for stratified reporting.

**Triggers:**
- **AUTO on every /do** — only if `rollout-status.json` has `phase_0.decision == "GO-EVERY-DO"`.
- **AUTO on `risk:high`-labeled phases only** — if `phase_0.decision == "GO-TARGETED"`.
- In both cases, run after spec-review passes, parallel to the existing quality review lane, unless phase is labeled `kind:bug` or `review:skip-codex`.
- **Manual override:** `/swarm-do:do <plan> --codex-review <auto|on|off>` (ships with Phase 1 wiring). `auto` honors rollout status; `on` forces Codex review regardless of labels; `off` skips. No `/do-no-codex` sibling command — the flag is cheaper.
- **DOGFOOD opt-in:** `swarm preset load hybrid-review` activates the Codex review lane for the next `/swarm-do:do` run without changing the default preset.

**Runs on every /do:** YES only if scoped review proved cheap enough in Phase 0. Otherwise: NO, tagged high-risk phases only.

**Guardrails:**
- Hard latency budget: if Codex review exceeds 60s, the review is discarded and pipeline proceeds. Prevents rate-limit cascades from blocking work.
- Enforce that budget in the runner, not by policy text alone. Use a portable timeout wrapper (`timeout`, `gtimeout`, or a small helper script) that emits a sentinel result such as `{"status":"discarded","reason":"timeout"}` so audits can distinguish timeout from "no findings".
- Findings go to beads notes only — never block merge. You decide what to act on.
- If two weeks of data show high overlap or low incremental value, demote Codex review to high-risk-only phases or trial `gpt-5.4-mini` as the steady-state reviewer model.
- Keep the steady-state effort at `high` unless measured data show that `medium` preserves enough signal.

---

## Section 4 — Phase 2: Pattern 5 manual trial first; Pattern 6 stays manual longer

**What to build:**
- First run Pattern 5 **manually** on 10-15 selected high-risk phases:
  - writer-A: Claude
  - writer-B: Codex / GPT-5.4
  - existing writer-judge picks the winner on tests first, code quality second
- Instrument every Pattern 5 run:
  - per-writer tokens
  - per-writer wall-clock time
  - judge time
  - winning backend
  - post-merge follow-up rework / hotfix commits attributable to the phase
- Keep Pattern 6 **manual-only** during this calibration window.
- Ship `swarm compete <plan-path>` as the manual Pattern 5 entrypoint. It validates the `competitive` preset/pipeline against the plan and activates that preset unless `--dry-run` is supplied.
- Extend the writer-judge output schema before any Pattern 6 automation:
  - `synthesis_recommended: true|false`
  - `synthesis_reason`
  - `decomposable_units` (function / method boundaries only)
- Only after the manual Pattern 5 trial passes:
  - extend `agent-analysis` output schema with `competition_recommended: true|false` + `competition_reason`
  - train analysis to recommend competition ONLY for: ambiguous spec, novel algorithm, UNVERIFIED items implying design judgment, or high-stakes logic
  - let `/do` auto-dispatch Pattern 5 when analysis flags it
- Pattern 6 should not auto-dispatch until manual synthesis trials show the merged code remains understandable, testable, and clearly owned.

**Triggers:**
- **MANUAL first** — Pattern 5 on selected phases via `/swarm-do:compete <plan-phase>` (added in the swarm-do plugin command family — see packaging plan). Pattern 6 by explicit human choice only.
- **AUTO later** — analysis may decide Pattern 5 per phase only after the manual calibration window passes.
- **Manual override:** `/swarm-do:compete` is the dedicated manual command. Do not overload `/swarm-do:do` with a `--compete` flag — distinct pipeline shape warrants a distinct command.

**Runs on every /do:** NO — only when selected manually or, later, when analysis flags it. Target ≤20% of phases after tuning.

**Calibration gate:** log every auto-trigger for 2 weeks. If analysis recommends competition >30% of the time, the prompt is over-recommending; retune before trusting it.

**Economics gate before any Pattern 5 auto-dispatch:**
- Require evidence that manual Pattern 5 reduced downstream defects / rework by at least **25%** versus the single-writer baseline.
- Require marginal model/tooling cost to stay below the measured rework labor it avoids.
- If either condition fails, keep Pattern 5 manual-only.

**Why gate this behind Phase 1:** Pattern 5/6 is 2× writer cost + judge/synthesizer. Don't pay this until Phase 0's validation work has already built confidence that GPT-5.4 meaningfully differs from Claude on your codebase, and Pattern 5 has proven itself in manual trials.

---

## Section 4.5 — Manual fallback track (recommended before full B1 dispatcher)

Before building an automatic multi-backend dispatcher, add a **manual beads-preserving fallback path**. This is likely the best maintenance / complexity tradeoff unless Claude rate-limit interruptions become frequent enough to justify B1.

**Core idea:** keep beads as the single source of truth, keep your current Claude `/do` flow intact, and add explicit GPT entrypoints that can operate on the **same issue IDs** when needed.

**Important current-state fact:** today's `/do` is the `claude-mem:do` skill, and observed usage is plan-centric (`/do <plan-path>`), not issue-centric. That means the manual GPT path should plug in **below** `/do` at the active-issue level first, instead of trying to overload the current `/do` command with backend routing immediately.

**Why this may be better than Phase 3 right now:**
- No re-architecture of `/do`
- No automatic rate-limit detection logic
- No attempt to perfectly reproduce all Claude startup hooks in a new supervisor
- No need to solve full prompt portability for every role up front
- Easier to audit, teach, and maintain

**Entrypoint recommendation for the manual track:**
- Keep current `/do <plan-path>` exactly as the Claude / claude-mem launcher.
- Use explicit issue-level GPT entrypoints for takeover / resume:
  - `swarm-gpt <issue-id>`
  - optional ergonomic alias if you want slash-command symmetry later: `/resume-gpt <issue-id>` or `/do-gpt <issue-id>`
- Do **not** make `/do --backend=gpt` part of the manual track. Even if slash-command arguments are technically possible, the current `/do` still runs inside Claude / claude-mem, so it does not buy you true fallback when the Claude session is the thing that is failing.
- If you eventually want one shared `/do` surface for both backends, do that only after Phase 3 externalizes dispatch.

**Recommended manual variants:**

### M1 — Manual GPT sidecar commands on the same beads graph

This is the recommended manual model. The beads issue remains the unit of work, and backend choice is an operator decision rather than a graph rewrite.

**Design principle:** make commands **issue-centric**, not prompt-centric. The operator should point at a beads issue ID and let the runner infer the role, dependencies, and prompt bundle.

**Command set (minimum viable):**
- `swarm-run --backend claude --issue <issue-id>`
- `swarm-run --backend gpt --issue <issue-id>`
- convenience aliases:
  - `swarm-claude <issue-id>`
  - `swarm-gpt <issue-id>`
  - optional UI-level alias later: `do-gpt <issue-id>` or `/resume-gpt <issue-id>`
  - `swarm-compete <issue-id>` for manual Pattern 5
  - `swarm-gpt-review <issue-id>` as a convenience wrapper for review-tagged issues

**Do not require `<role>` on the command line by default.** Infer role from the issue assignee or issue metadata:
- `agent-analysis`
- `agent-writer`
- `agent-spec-review`
- `agent-review`
- `agent-codex-review`
- later, optionally: `agent-writer-judge`, `agent-code-synthesizer`

**Initial M1 scope (ship first):**
- `agent-writer`
- `agent-spec-review`
- `agent-review`
- `agent-codex-review`

This covers the most important "Claude hit a limit, but I need to finish the active phase" cases with the least prompt-porting work.

**Runner contract:**
1. Read `bd show <issue-id>`.
2. Infer role from assignee / issue metadata.
3. Set `BD_ACTOR` to the logical role and run `bd update <issue-id> --claim`; if claim fails, abort rather than appending notes optimistically.
4. Read dependency notes that role would normally consume.
5. Load prompt bundle for that role:
   - `shared.md`
   - backend-specific override: `claude.md` or `codex.md`
6. Resolve model + effort from the role matrix instead of inheriting ambient defaults.
7. Invoke the selected backend.
8. Append a backend-run block to beads notes with `bd update <issue-id> --append-notes ...`
9. Close or leave open based on the role's normal completion rules.

**Prompt layout for M1:**
- `.swarm/roles/<role>/shared.md`
- `.swarm/roles/<role>/claude.md`
- `.swarm/roles/<role>/codex.md`

This keeps one logical role and two backend-specific overlays, instead of forking the whole swarm into separate Claude and GPT prompt trees.

**Ownership / concurrency rules:**
- One issue, one active worker at a time.
- `bd update --claim` is the enforcement mechanism behind that rule; do not append backend-run notes unless the claim succeeded.
- M1 does **not** create a sibling issue by default.
- The logical assignee stays the role (`agent-writer`, `agent-review`, etc.), not the backend.
- Backend choice is recorded in notes, not in assignee.
- If Claude started a role and GPT takes over, GPT appends a new run block to the same issue rather than overwriting prior notes.
- The backend that completes the role may close the issue if the role's normal completion criteria are satisfied.
- If there is any doubt about whether a role is mid-flight in another terminal, do not start a second runner on that same issue.

**Beads note format for M1 runs:**

Append a clearly delimited block before the role-specific output:

```markdown
## Backend Run
- Backend: claude | codex
- Model: <model-id-or-alias>
- Effort: <medium | high | xhigh>
- Setting source: explicit-runner | skill-frontmatter | session-inherited
- Mode: normal | fallback | competition
- Role: agent-<role>
- Issue: <issue-id>
- Trigger: operator choice | claude rate-limit | manual competition
- Prompt bundle: .swarm/roles/<role>/{shared,<backend>}
- Started: <timestamp>
- Prior backend run: <none | link/ref>

<role-specific output follows>
```

**Mode semantics:**
- `normal`: intentional backend selection for a role
- `fallback`: operator switched because Claude was interrupted, rate-limited, or unavailable
- `competition`: one side of a manual Pattern 5 run

**Handoff rules:**
- Claude -> GPT fallback:
  - leave existing notes intact
  - append a new `Backend Run` block with `Mode: fallback`
  - reference the interrupted Claude run in `Prior backend run`
- GPT -> Claude return:
  - same pattern; do not summarize by hand outside beads notes
- Multi-stage mixed flow is allowed, but each stage should have one clearly attributable backend run block

**Concrete operator workflow:**
1. Run `/do <plan-path>` in Claude as today. This is currently the `claude-mem:do` skill entrypoint.
2. If Claude rate-limits or stalls on an active phase, capture the issue ID from beads.
3. Run `swarm-gpt <issue-id>`.
4. Let GPT finish that role against the same notes chain.
5. Resume the next stage with whichever backend is most convenient:
   - back to Claude via normal `/do`, or
   - continue manually with `swarm-gpt <next-issue-id>`

**What M1 should NOT do:**
- No automatic 429 detection
- No automatic phase hopping
- No issue graph rewriting
- No backend-specific assignee explosion like `agent-writer-gpt`
- No attempt to maintain a hidden second state store outside beads

**Rollout order for M1:**
1. Build `swarm-run` with backend selection and issue inference.
2. Support `agent-writer` and `agent-review` first.
3. Trial real fallback on 5-10 phases or synthetic "resume this issue with GPT" drills.
4. Only then add `agent-spec-review`, `agent-analysis`, and competition helpers.

**Success criteria for M1 specifically:**
- An operator can switch an in-flight role from Claude to GPT in under 60 seconds.
- The GPT run produces notes that are understandable to a later Claude or human reader.
- No duplicate beads issues are needed in the common fallback case.
- After 2 weeks, the team can say whether manual failover friction is low enough to keep or painful enough to justify B1.

### M2 — Manual mirrored GPT issues only when fallback is needed

If writing into the same issue feels too risky or confusing, create a sibling issue only when switching backends, e.g.:
- `Implement (GPT fallback): <phase>`
- `Review (GPT sidecar): <phase>`

Behavior:
- Sibling issue depends on the same upstream analysis / debug issue
- Notes explicitly reference the original Claude-owned issue
- Use this only for fallback or competition, not as the default graph

This is more explicit, but also noisier in beads and heavier to manage.

### M3 — Explicit end-to-end model lanes

Provide top-level commands for humans:
- `do-claude <phase-id>`
- `do-gpt <phase-id>`
- `do-hybrid-review <phase-id>`
- `do-resume-gpt <issue-id>`

This is still manual orchestration, but it makes the operational model obvious:
- Claude lane for normal work
- GPT lane for explicit fallback or experiments
- Hybrid lane for review / competition cases

**Recommendation:** start with **M1**. It preserves your current beads workflow best, adds the least machinery, and directly answers whether manual fallback is "good enough" before you build B1.

**Decision criteria for keeping the manual track instead of building B1 immediately:**
- GO-MANUAL: manual fallback is used occasionally, operators can recover quickly, and the extra human orchestration is acceptable
- ESCALATE-TO-B1: manual fallback is used often enough that repeated human dispatching becomes annoying, error-prone, or slow

**Important:** this manual track does **not** solve automatic failover. It is a deliberate "80% of the value for 20% of the complexity" option.

---

## Section 5 — Phase 3: B1 dispatcher for rate-limit fallback (last, only if Phases 1-2 paid off)

**What to build:**
- Extract every agent definition into `~/.agents/agents/<name>/` with external prompt files (steal from superpowers).
- Add prompt-portability guardrails:
  - `.swarm/roles/_check-overlays.sh` verifies that backend overlays only adjust tone, examples, and tool syntax — not the role contract, sequencing, or ownership rules
  - run a quarterly frozen-prompt A/B regression on representative tasks to catch prompt drift across overlays
- Keep the architecture decision explicit:
  - **B1 remains the only architecture that solves rate-limit fallback.**
  - **B2 (Claude Code orchestrator + Codex as MCP tool) is still valid for mixed-model phases, but it does not solve the rate-limit problem because the Claude session remains the orchestrator.**
- Implement B1 in two layers:
  - **B1a — thin shell prototype:** `swarm-run <agent> <phase-id>` reads the agent spec and resolves the full `{backend, model, effort}` triplet from §1.7's config (operator flags > plugin config > role default), then invokes the appropriate CLI with prompt + beads context. Do **not** collapse resolution into a binary `SWARM_MODEL=claude|codex` — that loses the per-lane choices (`gpt-5.4-mini` vs `gpt-5.4` vs `gpt-5.3-codex`, Opus vs Sonnet) that deliver the token-saving behavior. Canonical model lineup lives in §1.6.
  - **B1b — recommended production path:** a small Python or TypeScript supervisor built on the Claude Agent SDK for Claude-backed workers plus `codex exec` for Codex-backed workers. This keeps more parity with current Claude behavior than a shell-only driver.
- Replace or wrap the current `claude-mem:do` entrypoint so `/do` becomes a thin front door to the external supervisor instead of a Claude-only in-session orchestrator.
- Add rate-limit detection via hook / SDK signal first, not CLI-text scraping. On Claude API failure or 429, the supervisor logs, flips to `SWARM_MODEL=codex`, and resumes the same phase.
- If an MCP wrapper is added here or later, keep the direct `codex exec` shell path as a first-class fallback in the same commit.
- Roll out in **shadow mode** first for 2 weeks: log would-be dispatch / fallback decisions without taking over live execution.
- Keep a legacy entrypoint (`/do-legacy` or direct `claude-mem:do`) available for at least 30 days after live cutover.
- Store model + effort in the role config itself, not in global defaults, so dispatcher decisions are reproducible.

**Shared `/do` becomes viable only here.** Once dispatch is externalized, you can choose one of these front-end shapes:
- keep `/do <plan>` as the default and add `--backend claude|gpt|hybrid`
- add sibling commands like `/do-claude <plan>` and `/do-gpt <plan>`
- keep terminal-first commands such as `swarm-run` and let `/do` be a thin convenience wrapper

Before Phase 3, separate commands are cleaner than flags because the current `/do` is still Claude / claude-mem-native.

**Triggers:**
- **AUTO** — rate-limit detection flips model.
- **Manual override:** once `/do` is externalized, either `SWARM_MODEL=codex /do <plan>` or `/do --backend=gpt <plan>` becomes reasonable. Before that point, prefer the manual issue-level GPT runner.

**Runs on every /do:** the *driver* runs every /do; the *fallback* only activates on rate-limit.

**Why last:**
- This is a real re-architecture (moves /do out of the Claude Code session into a shell driver).
- Only worth doing if Phase 0-2 prove cross-model value at scale.
- Only worth doing if the manual fallback track proves the operational need is real and frequent enough.
- Prompt portability is the biggest risk — plan to maintain Claude-tuned and Codex-tuned prompt variants per agent.
- Context/bootstrap parity is the second-biggest risk — the fallback path must preserve the hook-, memory-, and session-level behavior your current swarm depends on.

---

## Section 6 — Assumptions to verify before Phase 3

1. Current top-level swarm entrypoint is `claude-mem:do` (`/do`), with `~/.claude/AGENTS.md` and `~/.claude/hooks` providing downstream role contracts and fork behavior. *Treat the plugin skill as part of the architecture and verify exactly what layer you are rewriting before changing anything.*
2. The installed Codex CLI contract captured before Phase 0 still matches what your wrappers expect when you begin Phase 3.
3. Claude headless / Agent SDK can either load the same `.claude` skills / hooks / memory you rely on today, or the supervisor must bootstrap explicit equivalents.
4. Beads state plus startup hook context plus claude-mem context are sufficient to resume a phase outside the interactive Claude session.
5. Claude rate-limit surfaces through a detectable hook / SDK event path (prefer `StopFailure`, SDK rate-limit events, or statusline `rate_limits` data over text scraping).
6. Running the **chosen** Codex review mode at the intended cadence (`every /do` or high-risk-only) is within budget. Price it first, and compare `gpt-5.4` versus `gpt-5.4-mini` before locking the steady-state reviewer model.
7. The manual fallback runner can infer role from the beads issue, consume the same notes chain and prompt bundle, and append backend-run blocks without introducing ambiguity about ownership, closure rules, or assignee semantics.
8. If you want one shared `/do` surface later, define its argument grammar explicitly first: plan-path entry vs. issue-id resume, backend selection, and whether the user intent is "launch a new plan" or "resume an active role."

---

## Summary table

| Phase | Auto/Manual | On every /do? | Depends on |
|-------|------------|---------------|------------|
| 0 — Validation experiment | Manual | No | Backup + review-chain freeze + Codex CLI contract snapshot + §2.0 harness cleanup |
| 1 — Codex review in swarm | Opt-in dogfood first; Auto later only with data | No while `DOGFOOD`; **Yes** only after a later `GO-EVERY-DO`; tagged high-risk only after `GO-TARGETED` | Phase 0 decision recorded |
| 2 — Pattern 5 manual trial, then optional auto-trigger | Manual first, Auto later | No (~20% of phases after tuning) | Phase 1 stable |
| 2.5 — Manual fallback track | Manual | No — only when explicitly invoked | Phase 1 stable |
| 3 — B1 rate-limit dispatcher | Auto (on 429) | Driver: yes. Fallback: on rate-limit only | Phase 2 + manual fallback track both paid off |

---

## Success signal to keep going after each phase

- **Phase 0:** one explicit outcome is chosen and written down: `DOGFOOD`, `GO-EVERY-DO`, `GO-TARGETED`, or `NO-GO`. `DOGFOOD` means the isolated harness pauses and the plugin becomes the measurement surface.
- **Phase 1:** Two weeks of swarm use with Codex review adds <10% pipeline latency and findings are actionable.
- **Phase 2:** Manual Pattern 5 beats single-writer quality on a sample of 10-15 phases, clears the economics gate, and Pattern 6 stays manual until at least 3 clean synthesis wins.
- **Phase 2.5:** an operator can switch an active issue from Claude to GPT quickly, the same issue remains the source of truth, and the appended backend-run notes stay understandable to later humans and Claude sessions.
- **Phase 3:** shadow mode predictions were accurate enough to trust, live rate-limit fallback actually unblocks a session that would otherwise be dead **without losing required startup context, hooks, or memory inputs**, and the legacy entrypoint remains available during the rollback window.

If any signal fails, stop at that phase. The architecture is additive — you can sit on Phase 1 forever if Phase 2 doesn't prove out.

---

# Part 3 — Packaging history (archived)

The packaging migration that produced this plugin (Phases 0–8: plugin scaffold, command/skill/agent cutover, single-sourced beads preflight, claude-mem unfork, `/swarm-do` rename, beads-first enforcement, verification, rollback doc) has **shipped**. Audit trail lives in **[`docs/history/packaging.md`](history/packaging.md)** — kept for reference, not for re-execution.

That file also holds reference material the active plan still cites:
- Command family + modes × command compatibility matrix
- Uniform flags contract (`--backend`, `--model`, `--effort`, `--dry-run`, `--verbose`)
- Plugin config surface (`backends.toml` triplet schema + runner resolution order)
- Operator console + telemetry scaffolding decisions (state dir, lockfile schema, ledger contracts)
- Target directory layout for the plugin
- Senior-developer reflection on packaging direction

If you are running `/swarm-do:do docs/plan.md`, **the orchestrator should not create beads issues for anything in this part.** Part 4 below is the only runnable scope.

**Consuming references from here:** Part 4 sub-phases (9a–11g) and Part 5 (Replaceability + non-goals) link back to specific `docs/history/packaging.md` subsections when they need to cite the pinned config or command surface. Follow the link; do not inline-copy.

---

# Part 4 — Pending implementation phases (active work)

Phases 9–11 below are the active implementation workstreams. They depend on the already-shipped packaging (Part 3, archived) and implement the architecture decisions recorded in Part 1 (§1.8 TUI, §1.9 telemetry, §1.10 presets + pipelines).

**Dependency order**: Phase 9 (telemetry) → Phase 10 (presets + pipelines) → Phase 11 (TUI). Phase 9's ledgers are the data source for both Phase 10 (pipeline comparison queries) and Phase 11 (dashboard). Phase 10's schemas are the content Phase 11 renders.

---

## Phase 9 — Telemetry wiring (meta)

Implements the continuous-measurement architecture from §1.9. Ships in staged order so the dataset accumulates before the analyzer is built — no point writing a reporter with no data to report on.

**Overall ordering:** 9a → 9b → 9c in strict sequence (each depends on the previous). 9d / 9e / 9f can ship in parallel once 9c is stable. 9g must land before any shared operator install.

**Phase-wide verification (runs once after all sub-phases close):**
- Dogfood on one real cartledger phase: `runs.jsonl` and `findings.jsonl` both gain rows; `swarm telemetry report` prints a stratified summary.
- Fault injection: remove write permission on telemetry dir, run `/swarm-do:do`, confirm pipeline completes and stderr shows a telemetry write error (fail-open).
- Round-trip: delete `index.sqlite`, run `rebuild-index`, confirm all queries return the same rows as pre-delete.

### Phase 9a: Append-only ledgers (complexity: moderate, kind: feature) — **SHIPPED 2026-04-23 (PR #1, `ff14fc8`)**

> **What landed:** four v1-frozen schemas under `swarm-do/schemas/telemetry/{runs,findings,outcomes,adjudications}.schema.json`; `bin/_lib/hash-bundle.sh`; `bin/swarm-run` EXIT-trap append to `${CLAUDE_PLUGIN_DATA}/telemetry/runs.jsonl` with 31 required fields (unobservables typed `X | null`), fail-open guard, exit-code preserved. See `swarm-do/schemas/telemetry/README.md` for the contract.
>
> **Follow-up status:** the original 9a deviations are now closed. New rows use strict Crockford ULIDs, `diff_size_bytes` is emitted from the run delta, and `timestamp_end` is nullable in the schema to represent abnormal trap failures.
>
> **Install hook:** none. The `mkdir -p ${CLAUDE_PLUGIN_DATA}/telemetry` is lazy inside the EXIT trap (no `on_install` in `plugin.json`). If `CLAUDE_PLUGIN_DATA` is unset the trap emits a single-line stderr warning and skips the write — fail-open covers it.

**Objective:** Create the JSONL ledger files and wire `bin/swarm-run` to append one `runs.jsonl` row per invocation. This is the data source everything else in Phase 9/10/11 reads from — ship first.

**What to implement:**
- Create `${CLAUDE_PLUGIN_DATA}/telemetry/` on plugin install (idempotent `mkdir -p`).
- Pin JSONSchema for each ledger under `swarm-do/schemas/telemetry/{runs,findings,outcomes,adjudications}.schema.json`. Freeze v1 before first write.
- Wire `bin/swarm-run` to append one `runs.jsonl` row per invocation. Required fields: `run_id`, `timestamp_*`, `backend`, `model`, `effort`, `prompt_bundle_hash`, `config_hash`, `role`, `phase_kind`, `phase_complexity`, `risk_tags`, `issue_id`, `repo`, `base_sha`, `head_sha`, `diff_size_bytes`, `tokens`, `cost`, `wall_clock_seconds`, `tool_call_count`, `cap_hit`, `schema_ok`, `exit_code`.
- Hash helper: `bin/_lib/hash-bundle.sh` — computes `prompt_bundle_hash` by concatenating `shared.md + <backend>.md` and sha256'ing.
- **Fail-open discipline:** wrap the ledger write in an `|| true`-style guard with stderr log. Telemetry errors never block pipeline execution.

**Verify:**
- Run `/swarm-do:do` against a scratch plan; confirm one `runs.jsonl` row per invoked role, all required fields present, JSONSchema-valid.
- Fault injection: `chmod a-w ${CLAUDE_PLUGIN_DATA}/telemetry/runs.jsonl`; re-run — pipeline completes with stderr warning, no pipeline failure.
- Hash reproducibility: invoke `bin/_lib/hash-bundle.sh` twice on the same role — identical output.

**Anti-pattern guards:**
- Do NOT let a failed ledger write propagate a non-zero exit. Fail-open is load-bearing; a reviewer breaking the pipeline because the disk filled is the exact regression this discipline exists to prevent.
- Do NOT embed schema inline in the bash runner. JSONSchema lives under `schemas/telemetry/` and is validated by a separate helper — schema drift between writer and validator is how ledgers silently corrupt.
- Do NOT capture free-form strings. Every field in `runs.jsonl` is enumerated above; adding a field requires a schema bump AND an ADR note, never just a code edit.

### Phase 9b: Findings extractor (complexity: moderate, kind: feature) — **SHIPPED 2026-04-23 (commit `6b62467`)**

**Objective:** Extract one `findings.jsonl` row per reviewer finding, with a stable dedup hash. Depends on 9a ledgers.

**What to implement:**
- Extract findings from each reviewer role's output (existing `findings.json` from `agent-codex-review`; TBD format for Claude reviewers). One row per finding into `findings.jsonl`.
- Compute `stable_finding_hash_v1` at append time per integration §1.9 rule (sha256 of `{file_normalized, category_class, line_start/10, normalized_summary_tokens}`).
- Leave `duplicate_cluster_id` null on append — stamped by indexer post-hoc.
- Normalize file paths: resolve symlinks, strip worktree prefix, then canonical form. Worktree-relative and main-repo-relative paths for the same file must hash identically.

**Verify:**
- Run a review through a worktree and through main-repo on the same file+line; both produce the same `stable_finding_hash_v1`.
- A finding with `file_normalized="/tmp/xyz/foo.go"` and `line_start=47` produces a hash identical to `line_start=49` (both round to 40 via `/10`), but NOT identical to `line_start=52` (rounds to 50).
- Dedup: two reviewers flagging the same file+line cluster produce distinct hashes only if the normalized summaries differ.

**Anti-pattern guards:**
- Do NOT use raw worktree paths in the hash input. Worktrees live at `/tmp/<worktree-sha>/...`; hashing those defeats cross-run dedup.
- Do NOT stamp `duplicate_cluster_id` on append. Append is single-pass; cluster IDs require a second pass (indexer in 9e).
- Do NOT change the hash algorithm without bumping `stable_finding_hash_v1` → `_v2`. Silent algorithm changes corrupt the ledger retroactively.

### Phase 9c: `bin/swarm-telemetry` dispatcher — read-only (complexity: moderate, kind: feature) — **SHIPPED 2026-04-23 (commit `66a75c3`)**

**Objective:** Ship the read-only reporter so operators can query accumulated data. No write subcommands here — indexer + join-outcomes come in 9d/9e.

**What to implement:**
- Subcommands: `query <sql>`, `report [--since Nd] [--role R] [--bucket K]`, `dump <ledger>`, `validate`.
- `report` stratifies by `role × complexity × phase_kind × risk_tag` (never global means). Output format: plain markdown so it's pipeable to `gh pr comment` or saved to beads notes.
- `validate` runs every ledger through its schema; reports rows that fail validation.

**Verify:**
- Dump and report on a dev dataset of ≥50 synthetic runs; hand-check bucket arithmetic.
- `swarm telemetry report --since 30d --role agent-review` excludes rows outside the window and other roles.
- `swarm telemetry validate` flags a hand-corrupted row (truncate mid-JSON) without crashing.

**Anti-pattern guards:**
- Do NOT emit global means. Averaging `agent-docs` time next to `agent-analysis` time is the exact bias this stratification exists to prevent.
- Do NOT add write subcommands in 9c. Writes (rebuild-index, join-outcomes) belong in 9d/9e; keeping 9c read-only preserves the fail-open guarantee.

### Phase 9d: Outcome-join job (complexity: moderate, kind: feature) — **SHIPPED 2026-04-23 (commit `1fc3f5e`)**

**Objective:** Correlate reviewer findings with post-merge maintainer behavior (hotfix within 14d, follow-up issue, etc.) to produce `finding_outcomes.jsonl`.

**What to implement:**
- `swarm telemetry join-outcomes --since 30d` — scans recent merged PRs via `gh api` + local `git log`.
- For each finding with a file+line range, check: did any commit within 14d post-merge touch the same file within ±10 lines? If yes → append `finding_outcomes.jsonl` row with `maintainer_action: hotfix_within_14d`.
- Also detects beads follow-up references (`bd list --references <finding_id>`) and marks `followup_issue` / `followup_pr`.

**Verify:**
- Run against cartledger's own recent merges; spot-check that clear cases (hotfix on a known bug) are flagged correctly.
- Idempotent re-run: invoking twice on the same 30d window produces no duplicate `finding_outcomes.jsonl` rows.

**Anti-pattern guards:**
- Do NOT schedule via cron in 9d. Operator invokes manually first; cron waits until the output proves useful (avoids burning API quota on an unvalidated job).
- Do NOT correlate on file path alone. ±10 line window is load-bearing — broader matching produces false positives; narrower matching misses cases where the hotfix is near the finding.

### Phase 9e: SQLite indexer + FTS5 (complexity: moderate, kind: feature) — deferrable

**Objective:** Populate `index.sqlite` from the four JSONL ledgers so expensive queries (scorecard views, full-text search) are fast. Gate: ship only when JSONL grep+jq queries feel slow (~5k findings).

**What to implement:**
- `swarm telemetry rebuild-index` tails all four JSONL ledgers, populates `index.sqlite`.
- Tables mirror JSONL shape; add view `v_reviewer_scorecard` (joins runs × findings × adjudications, stratified) and FTS5 virtual table over `findings.short_summary`.
- Stamps `duplicate_cluster_id` during rebuild using the §1.9 duplicate rule.

**Verify:**
- Delete `index.sqlite`; run `rebuild-index`; confirm all queries return the same rows as pre-delete. Round-trip test.
- FTS5 query returns results ranked by relevance, not insertion order.
- `duplicate_cluster_id` stamping is idempotent across multiple rebuilds.

**Anti-pattern guards:**
- Do NOT ship 9e before JSONL is the measured bottleneck. Premature indexer = two sources of truth, maintenance cost, no benefit.
- Do NOT let the indexer be a write path for new data. JSONL is the authoritative ledger; the indexer is a cache that can be rebuilt from scratch.

### Phase 9f: Adjudication sampler (complexity: simple, kind: feature)

**Objective:** Pick a stratified random sample of findings that don't yet have an `adjudications.jsonl` row, laid out so the existing `blind-findings` + `unblind-findings` machinery works unchanged.

**What to implement:**
- `swarm telemetry sample-for-adjudication --count 20 --since 30d` — picks a stratified random sample of findings without adjudication rows. Output is a directory laid out like `${CLAUDE_PLUGIN_DATA}/phase0/runs/<date>/`.
- Monthly cadence suggested; operator triggers manually. Results append to `adjudications.jsonl`.
- Keep the same rubric version pinned in `swarm-do/rubrics/` so adjudication outcomes are comparable over time.

**Verify:**
- Run against the dev dataset; confirm output directory is consumable by the existing blinded-adjudication pipeline without modification.
- Rubric version pin is read from `swarm-do/rubrics/` and stamped in each adjudication row.

**Anti-pattern guards:**
- Do NOT sample unstratified. Random sampling skews toward the dominant role; stratification by role/complexity/phase_kind is load-bearing.
- Do NOT bump the rubric version without an ADR note. Rubric bumps break longitudinal comparability.

### Phase 9g: Retention + privacy ADR (complexity: simple, kind: feature)

**Objective:** Document retention windows, PII/secret scrubbing, and cross-repo sensitivity tiers. Blocking for any shared operator install; not blocking own-use dogfooding.

**What to implement:**
- Draft `swarm-do/docs/adr/0001-telemetry-retention.md`. Must decide: retention window per ledger, PII/secret scrubbing on append, cross-repo sensitivity tiers.
- Add a `swarm telemetry purge --older-than Nd` subcommand referenced by the ADR (implementation may defer; the ADR commits to the contract).

**Verify:**
- ADR names a specific retention window per ledger (not "TBD").
- ADR identifies at least three PII/secret classes and whether each is scrubbed on append or at query time.

**Anti-pattern guards:**
- Do NOT ship `purge --older-than` without the ADR pinning retention first. Purging before policy = unrecoverable data loss.
- Do NOT ship to a shared operator before 9g lands. Without retention policy, the first cross-operator install is the ADR-writing moment under pressure.

## Phase 10 — Swarm preset + pipeline registry (meta)

Implements integration plan §1.10 — the "swap pipelines on the fly" architecture. This is the biggest §1.x chunk (~1.5–2 weeks). Validation gates (10a) are load-bearing supply-chain safety — skipping them means a copy-pasted YAML from a blog post can blow through a day's quota or route the orchestrator to Codex. Not optional.

**Overall ordering:** 10a → 10b → 10c in strict sequence (each depends on the previous). 10d / 10e / 10g can ship in parallel once 10c is stable. 10f must land before any shared operator install.

**Phase-wide verification:**
- `swarm preset dry-run ultra-plan <plan-path>` prints a complete stage graph + cost estimate without spawning anything.
- `swarm preset load ultra-plan && /swarm-do:do <plan-path>` runs an ultra-plan pipeline end-to-end; resulting beads graph has 3 parallel exploration issues all blocking a critique issue.
- `swarm preset load claude-only` then attempting to route orchestrator to Codex displays a blocking invariant warning.
- Characterization test: default pipeline produces identical beads graph before and after 10b refactor.
- Fault injection: malformed user pipeline YAML → preset loader refuses to activate, falls back to last-known-good preset, logs the rejection reason.

### Phase 10a: Schemas + validation gates (complexity: hard, kind: feature)

**Objective:** Ship JSONSchema for presets and pipelines, plus `bin/swarm-validate` running 5 gates in order. Blocks everything else in Phase 10 — no user pipeline can load until this lands.

**What to implement:**
- Write JSONSchema files: `swarm-do/schemas/preset.schema.json`, `pipeline.schema.json` — matching the DSL schema freeze in integration §1.10:
  - `variant` enum: `same | prompt_variants | models`
  - `strategy` enum: `synthesize | vote` (no `all-parallel`)
  - `variant: models` uses explicit route objects (`backend`, `model`, `effort`) or named preset routes — not bare model IDs. A model ID alone cannot express Claude vs Codex execution.
  - `failure_tolerance` is a **structured object** with `mode` enum (`strict | quorum | best-effort`) + required `min_success` integer iff `mode=quorum`. Not a patterned string.
  - Concurrency is expressed **only** via `stages[].depends_on` — no `parallel_with` field. Stages with the same `depends_on` run in parallel; `depends_on: []` (or absent) means the stage runs at DAG root.
  - A stage must have exactly one of `agents` or `fan_out` (mutually exclusive); fan-out stages require a `merge` block.
  - Unknown top-level keys = lint failure (no silent forward-compat).
- Ship the minimal backend registry / resolver contract that validation depends on:
  - Reads the active preset routing, base `backends.toml`, role defaults, and hardcoded default.
  - Returns a resolved `{backend, model, effort, setting_source}` for `(role, complexity)` and for any stage route override.
  - Exposes a stable helper/API used by both `bin/swarm-validate` and later `bin/swarm-run` updates. Do not let the invariant guard depend on the current M1 hardcoded role matrix in `bin/swarm-run`.
- `bin/swarm-validate` — loads a preset/pipeline and runs all gates in order:
  1. Schema lint
  2. Role existence check (every `agent-X` resolves to `swarm-do/agents/agent-X.md`)
  3. Invariant guard via the backend resolver (hard reject, no force-override: orchestrator must resolve to a Claude backend, agent-code-synthesizer must resolve to a Claude backend, any stage with `merge.strategy=synthesize` must use a Claude-backed merge agent)
  4. Cycle detection on the `depends_on` DAG
  5. Budget preview — when a plan path is supplied, estimates agent count + token cost + wall-clock, compares against preset's `[budget]` ceilings. Budget is a **hard reject for dry-run and `/swarm-do:do` run start**, not bare `preset load`, because budget depends on the plan's phase count and complexity. Raising ceilings requires editing the preset's `[budget]` block so the authorization is owner-attributable in the file.
- `swarm preset load <name>` — runs plan-independent gates only (schema, role existence, invariants, cycle detection), activates the preset if those pass, and records that budget will be enforced at dry-run/run start.
- `swarm preset dry-run <name> <plan-path>` — invokes all gates including budget + prints the stage graph, agent count, and cost estimate.

**Verify:**
- Unit tests for each gate — at minimum one known-bad fixture per gate, one known-good control.
- Invariant-guard tests MUST include a "try to route orchestrator to codex" case that fails.
- Resolver tests MUST include a preset route override and a base `backends.toml` fallback so the invariant guard is not testing a hardcoded `"claude"` string.
- Schema-lint tests MUST include the `2-of-3` string form for `failure_tolerance` and confirm it fails in favor of the structured object.
- Dry-run always emits the cost preview (pass or fail) so operators see the numbers before starting a run.

**Anti-pattern guards:**
- Do NOT add a `--force-over-budget` or `--skip-invariant` flag. Invariant/budget gates are structural; "force" destroys the supply-chain safety this phase exists to provide.
- Do NOT allow unknown top-level keys as "forward-compat." Silent forward-compat = silent pipeline misconfiguration.
- Do NOT hardcode "claude" as a string in the invariant guard. Resolve via the backends registry so new Claude model IDs don't trigger false rejects.

### Phase 10b: Pipeline engine refactor (complexity: hard, kind: feature)

**Objective:** Refactor the orchestrator SKILL.md from a procedural prompt to a data-driven engine that reads the active pipeline YAML and executes stages. Biggest single chunk (~2–3 days). Depends on 10a.

**What to implement:**
- Runtime responsibilities:
  - **Two-layer engine boundary** — code helpers parse/validate YAML, resolve routing, compute topological layers, create a deterministic execution plan, and create/edge beads issues. The Claude SKILL remains the dispatcher that calls Claude Code `Agent()` for Claude-backed stages. Shell/Python helpers must not pretend they can invoke Claude subagents directly.
  - **DAG scheduling** — compute topological layers from `depends_on`, execute each layer's stages in parallel. Stages sharing `depends_on` run concurrently.
  - Fan-out execution (spawn `fan_out.count` agents in parallel within a fan-out stage; wait per failure_tolerance).
  - Merge (invoke `merge.agent` with successful fan-out outputs as input).
  - Beads dependency-edge creation (fan-out spawns N sibling issues all blocking the same merge issue; stage-level `depends_on` becomes bd edges).
  - Failure tolerance enforcement per structured config — `strict` | `quorum` (with `min_success`) | `best-effort`.
- SKILL.md body shrinks to: "load active pipeline YAML via helper, ask helper for the next executable stage set, dispatch the resolved roles/providers, record results, repeat." The prompt owns orchestration decisions that require Claude Code Agent calls; helpers own deterministic graph/routing math.

**Verify:**
- Characterization test: the existing `/swarm-do:do` default pipeline (from Phase 2) must produce identical beads issue graphs before and after the refactor. Same issue titles, same assignees, same dependency edges.
- The `default.yaml` produced in 10d must express today's analysis+clarify parallelism as two stages both with `depends_on: [research]` (not `parallel_with`).
- Fan-out test: a pipeline with `fan_out.count: 3` spawns 3 sibling issues that all block the merge issue.

**Anti-pattern guards:**
- Do NOT rewrite the prompt skeleton. The SKILL.md body shrinks to load+execute; any prose orchestration that survives the refactor becomes drift vector.
- Do NOT special-case the default pipeline. If the engine works for ultra-plan, it works for default; carve-outs defeat the whole point of data-driven dispatch.
- Do NOT introduce `parallel_with`. Concurrency is `depends_on`-only; two concepts for one thing guarantees divergent interpretation.

### Phase 10c: Preset loader + bin/swarm subcommands (complexity: moderate, kind: feature)

**Objective:** Ship the `bin/swarm preset ...` and `bin/swarm pipeline ...` CLI surface. Depends on 10b engine + 10a validation.

**What to implement:**
- `bin/swarm` gains: `preset load <name>`, `preset save <name> --from <current|preset-name>`, `preset diff <name>`, `preset list`, `preset clear`, `pipeline show <name>`, `pipeline lint <path>`, `pipeline list`.
- Active preset stored at `${CLAUDE_PLUGIN_DATA}/current-preset.txt` (single-line filename, or empty file).
- **Default on install = no active preset.** Resolution falls back to `backends.toml` alone (per §1.7 defaults to Claude-primary everywhere).
- Existing `swarm mode claude-only | codex-only | balanced | custom` becomes a shortcut for `swarm preset load <name>`. `swarm mode custom` = `swarm preset clear`.
- Preset save writes to `${CLAUDE_PLUGIN_DATA}/presets/<name>.toml`. Stock presets are read-only — attempts to save with a stock name are rejected; use `swarm preset save <new-name> --from <stock-name>` to fork.

**Verify:**
- `swarm preset list` distinguishes stock vs user presets.
- `swarm preset save balanced` (stock name) rejects with a fork-instruction message.
- Fresh install: `cat ${CLAUDE_PLUGIN_DATA}/current-preset.txt` is empty; `/swarm-do:do` uses `backends.toml` alone.

**Anti-pattern guards:**
- Do NOT ship with a stock preset pre-activated. Silent codex promotion of `agent-docs`/`agent-spec-review`/`agent-clarify`/`agent-writer.simple` before the §1.7 measurement gate passes = exactly the regression the gate exists to prevent.
- Do NOT allow stock presets to be mutated in place. Fork-before-edit is load-bearing; in-place edits break `swarm preset diff <stock>`.

### Phase 10d: Stock presets + pipelines (complexity: moderate, kind: feature)

**Objective:** Write the 6 stock presets and 4 stock pipelines. Validate each locally with synthetic fixtures; create a post-merge operator verification bead for real cartledger dogfooding.

**What to implement:**
- `default.yaml` — translation of today's `/swarm-do:do` pipeline into the YAML schema. No behavior change.
- `ultra-plan.yaml` — mindstudio.ai-referenced architecture: 3 explorer fan-out + 1 critique merge before writer stage.
- `compete.yaml` — Pattern 5: existing analysis stage, then 2× writer fan-out (Claude + Codex via `variant: models` route objects or named preset routes), then writer-judge merge.
- `lightweight.yaml` — drops spec-review + docs stages.
- 6 stock presets, each referencing exactly one pipeline + a routing override block matching its name's intent.

**Verify:**
- `swarm preset dry-run <each-preset>` prints a valid stage graph.
- Local synthetic dogfood: each preset runs against a repo-local fixture plan; beads graph matches expectations.
- Create one follow-up bead for operator-driven cartledger dogfooding after merge. Do not claim cartledger dogfooding complete from inside this repo.
- Characterization: default preset produces identical beads graph to pre-10b behavior.

**Anti-pattern guards:**
- Do NOT invent fan-out counts. ultra-plan = 3 explorers per the referenced architecture; compete = 2 writers per Pattern 5. Changing these without an ADR is cargo-culting.
- Do NOT ship a preset without local fixture dogfooding. Do NOT claim external cartledger dogfooding until the operator-run follow-up bead is closed.

### Phase 10e: Telemetry integration (complexity: simple, kind: feature)

**Objective:** Wire `preset_name`, `pipeline_name`, `pipeline_hash` into `runs.jsonl` so A/B comparisons by pipeline are possible. Depends on 9a/9b ledgers + 10b engine.

**What to implement:**
- Extend `runs.jsonl` schema (per integration §1.9) with `preset_name`, `pipeline_name`, `pipeline_hash`.
- Extend `schemas/telemetry/runs.schema.json` to match.
- Indexer (Phase 9e) adds indexes on `(preset_name, pipeline_name)` for A/B comparison queries.
- New report section in `swarm telemetry report`: "Pipeline comparison — last 30d" stratified by `pipeline_name × phase_kind × complexity`.

**Verify:**
- Run with default preset → rows tagged `pipeline_name=default`; switch to ultra-plan → rows tagged `pipeline_name=ultra-plan`.
- `pipeline_hash` matches `sha256(pipeline.yaml)` computed out-of-band.
- Report's pipeline-comparison section correctly attributes findings to their originating pipeline.

**Anti-pattern guards:**
- Do NOT emit global pipeline means. Stratification by phase_kind × complexity is load-bearing — ultra-plan on simple phases looks bad; on hard phases it looks good; averaging these is misleading.

### Phase 10f: Invariants + pipeline evolution ADR (complexity: simple, kind: feature)

**Objective:** Document the hard-reject invariants and pipeline versioning policy. Blocking before any operator outside mstefanko installs the plugin.

**What to implement:**
- Write `swarm-do/docs/adr/0002-pipeline-invariants.md` documenting:
  - The hard-reject invariants (orchestrator must be Claude; synthesizer must be Claude)
  - Why they're structural, not policy (skill runs inside the Claude session; synthesizer is the highest-risk merge step)
  - Pipeline versioning policy: when `pipeline_version` bumps, how forked user presets get flagged
  - Budget ceiling semantics

**Verify:**
- ADR names specific invariants, not "TBD." Each invariant has a concrete rationale tied to an architectural fact (not just "because we said so").
- Pipeline versioning policy is specific enough that a forked user preset gets flagged automatically (not manual review).

**Anti-pattern guards:**
- Do NOT couch invariants as "policy" or "recommendation." They are structural hard-rejects with no force-override — the ADR must make this explicit.

### Phase 10g: Fan-out variant asset structure (complexity: simple, kind: feature)

**Objective:** Write the role-variant files that `variant: prompt_variants` pipelines need. At minimum for ultra-plan: 3 explorer variants of `agent-analysis`.

**What to implement:**
- `swarm-do/roles/agent-analysis/variants/{explorer-a,explorer-b,explorer-c}.md` — additive overlays on `shared.md` differing in prompt framing (e.g., "focus on architectural risk" vs "focus on API contract stability" vs "focus on data model implications") without changing contract.
- Pre-flight lint: `swarm pipeline lint` checks every referenced variant file exists.

**Verify:**
- Pipeline lint catches a dangling `variant: prompt_variants` reference.
- Running ultra-plan through the engine (10b) loads all 3 variants and produces 3 distinct explorer issues.

**Anti-pattern guards:**
- Do NOT let variants change the role contract (e.g., output schema). Variants differ in framing, not interface.
- Do NOT create variants without a concrete framing rationale. "Explorer-a / -b / -c with identical prompts" is waste, not fan-out.

## Phase 11 — TUI operator console (meta) — **MVP/PARTIAL 2026-04-24**

Implements integration plan §1.8's V1 TUI. Framework: **Textual** (same stack as `tech-radar`). Ships after Phase 9a/9b (telemetry ledgers — the data source) and Phase 10 (presets/pipelines — the content it manages).

**Current implementation status:** an MVP exists under `py/swarm_do/tui` and launches through `bin/swarm-tui`. Treat it as a usable operator console, not the full Phase 11 spec. The richer planned behavior still needs follow-up work: a real burn chart from token/cost telemetry, complete Ctrl-S/Ctrl-Z save and undo semantics, more deliberate preset rename/delete interactions, and live visual verification with the Textual dev loop.

**Framework rationale (codified here for maintainers):**
- Ecosystem consistency — tech-radar already ships Textual 0.80+; operators already have the Python env. Adding Go/Rust doubles the plugin's build/maintain surface.
- Form-heavy UI — settings matrix + preset picker are mostly tabular/form; Textual's DataTable + reactive widgets handle these natively. ratatui's immediate-mode is wrong paradigm for edit-heavy forms.
- Iteration speed — Dev Console + tcss hot reload matches the stated goal of "build it while using it."
- Textual-serve available as a future web-dashboard path without rewriting.

**Overall ordering:** 11a first (bootstrap). Then 11b/11c/11d/11e can ship in parallel once scaffolding is in place — they share the status bar (11f) and dev-loop docs (11g). 11b depends on Phase 9a/9b (ledgers). 11d/11e depend on Phase 10 (preset/pipeline system).

**Phase 10 contract fixes discovered during review (must land inside Phase 11 before screens rely on them):**
- TUI module path is `py/swarm_do/tui/`; wrapper invokes `python -m swarm_do.tui.app`. Do not create a top-level `tui` package that bypasses the existing Python layout.
- `bin/swarm-run` must create `${CLAUDE_PLUGIN_DATA}/in-flight/bd-<id>.lock` after a successful claim and remove it on EXIT. Dashboard/cancel/handoff features read this lockfile contract.
- `bin/swarm-run` must emit a real `config_hash` in `runs.jsonl` from the active config surface (`backends.toml` plus active preset/pipeline identity where present). The Settings screen cannot claim telemetry hash updates while runtime still writes null.
- Phase 11 owns the missing action surface it calls: handoff/cancel helpers, preset rename/delete, and current-preset pipeline update either ship as shared Python helpers or `bin/swarm` subcommands. The TUI must not shell out to nonexistent commands.
- Token/cost/429 telemetry fields may still be null in Phase 11. Dashboard and status bar render `n/a` for unavailable burn/cost/rate-limit data instead of fabricating zeroes.

**Phase-wide verification:**
- Fresh install: `/plugin install swarm-do@mstefanko-plugins`, then `bin/swarm-tui` — prompts for venv creation, installs, launches.
- Dashboard updates live while a real `/swarm-do:do` runs in a second terminal.
- Settings editor: change `agent-docs` backend, Ctrl-S, verify `backends.toml` updated + `config_hash` is non-null and changes in the next telemetry row.
- Presets: `swarm preset load ultra-plan` via TUI, verify active preset updates everywhere (status bar, dashboard banner, pipeline inspector preview).
- Invariant guard: attempt to set `orchestrator = codex` in settings → blocking error, save disabled until the route is changed back to a Claude-backed backend.
- Fault: delete `runs.jsonl` mid-session — dashboard displays "no telemetry yet" gracefully, does not crash.

**What's NOT in Phase 11 (deferred):**
- Pipeline YAML editor inside the TUI — external editor only for v1.
- Telemetry reports — CLI (`swarm telemetry report`) is authoritative; TUI may link out.
- Per-repo config — global-only v1.
- textual-serve / web variant — ships post-v1 only if useful.
- Adjudication workflow — existing blinded-adjudication pipeline already works; TUI does not duplicate it.

### Phase 11a: Scaffold + venv bootstrap (complexity: moderate, kind: feature)

**Objective:** Ship `bin/swarm-tui` and the venv bootstrap that survives plugin upgrades. Install is opt-in; CLI + SKILL.md still work without the TUI.

**What to implement:**
- `swarm-do/tui/requirements.txt` pinned: `textual>=0.80`, `tomli`, `pydantic`, optionally `textual-serve` (deferred).
- **Venv location: `${CLAUDE_PLUGIN_DATA}/tui/.venv`** — NOT under the plugin install tree. Plugin upgrades replace the install tree (`swarm-do/<sha>/...`), so a venv living there would be wiped on every `/plugin update` and re-require a ~40MB reinstall.
- Versioned via `requirements.lock`; `bin/swarm-tui` re-runs `pip install` only when the lock hash differs from `${CLAUDE_PLUGIN_DATA}/tui/requirements.lock.hash`.
- `bin/swarm-tui` wrapper: resolves venv path → checks venv missing or lock-hash mismatch (prompts operator) → creates venv + installs + stamps lock hash → execs `"$VENV/bin/python" -m swarm_do.tui.app` with `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` forwarded.

**Verify:**
- First invocation: prompts for venv creation; creates under `${CLAUDE_PLUGIN_DATA}/tui/.venv`.
- Second invocation (same lock): no pip re-run; launches immediately.
- After `/plugin update swarm-do`: venv still present under `CLAUDE_PLUGIN_DATA` (not blown away); lock-hash check decides whether to re-install.
- Without running `bin/swarm-tui`: `/swarm-do:do` and `bin/swarm` still work.

**Anti-pattern guards:**
- Do NOT place the venv under `${CLAUDE_PLUGIN_ROOT}`. Plugin upgrades wipe it, forcing repeat 40MB reinstalls.
- Do NOT auto-install on plugin install. TUI is opt-in; silent pip installs on plugin install violates the "CLI still works without TUI" contract.
- Do NOT check venv freshness via timestamp. Lock-hash is deterministic; timestamps break cross-machine reproducibility.

### Phase 11b: Dashboard screen (complexity: moderate, kind: feature)

**Objective:** Landing screen — tails `runs.jsonl`, lists in-flight runs, shows burn chart. Read-only. Depends on 9a/9b ledgers.

**What to implement:**
- Tails `${CLAUDE_PLUGIN_DATA}/telemetry/runs.jsonl` via `watchfiles` or polling every 2s.
- Lists in-flight runs from `${CLAUDE_PLUGIN_DATA}/in-flight/*.lock` (lockfiles created by `bin/swarm-run`).
- Consumption burn chart over last 24h, aggregated from runs.jsonl (tokens/hr per backend; render `n/a` while token fields are null).
- Recent 429 events per backend (timestamp + count in last hour), read from runs.jsonl's `last_429_at` column; render `n/a` when no observable 429 data exists.
- Active preset + pipeline banner (top). Status bar (bottom).
- Hotkeys: `f` handoff selected in-flight issue to other backend (shared Python helper or `bin/swarm handoff`), `o` open issue in browser via `bd show` + URL construction, `c` cancel (signal the lockfile's PID).

**Verify:**
- Mock a `runs.jsonl` with 10 rows + 2 in-flight lockfiles; TUI renders in-flight table + burn chart correctly.
- Live-test: start a real `/swarm-do:do` in another terminal, confirm dashboard updates within 2s.
- Delete `runs.jsonl` mid-session — dashboard shows "no telemetry yet" gracefully, does not crash.

**Anti-pattern guards:**
- Do NOT poll runs.jsonl more frequently than 2s. Faster polling burns CPU without visible benefit; slower polling breaks the live-update promise.
- Do NOT let `c` (cancel) terminate via SIGKILL. Signal the lockfile's PID with SIGTERM; let the runner clean up its lockfile.

### Phase 11c: Settings screen (complexity: hard, kind: feature)

**Objective:** Role × complexity matrix editor with atomic writes and unoverrideable invariant guard. Depends on 11a scaffold.

**What to implement:**
- DataTable with rows = roles, columns = simple / moderate / hard. Grayed cells for roles without complexity keys.
- Cell content: `{backend}/{model}/{effort}` compact string.
- **Edit target is singular and explicit.** Top of screen shows `Editing: <target>` — either `backends.toml (base)`, `<user-preset-name>.toml (routing)`, or a "Stock preset active — press F to fork" banner (editing disabled).
- Arrow keys navigate; Enter opens a detail modal with three dropdowns (backend / model / effort).
- Ctrl-S writes the active target atomically (tempfile + rename). Runtime `config_hash` is computed by `bin/swarm-run`; the Settings screen validates that the hash would change after save.
- Ctrl-Z undo (in-session only).
- **Invariant guard: unoverrideable hard reject.** Attempting to set `orchestrator` or `agent-code-synthesizer` to non-Claude, or a `synthesize`-merge agent to non-Claude, displays a modal with invariant text and refuses the change. Save button stays disabled until the operator picks a conforming backend. **No Ctrl-Shift-S force-save.**

**Verify:**
- Edit `agent-docs` backend; Ctrl-S; `backends.toml` updated atomically (no torn writes under kill -9).
- Ctrl-Z reverts in-session edits pre-save.
- Attempt to set `orchestrator = codex` → modal blocks; save button remains disabled.
- Switching active preset while editor is open is disallowed (cancel edits first).

**Anti-pattern guards:**
- Do NOT add a force-save shortcut. Invariants are structural, not policy; an escape hatch defeats the 10f ADR contract.
- Do NOT introduce a "transient next-run overlay" tier. Precedence is {operator flags > active preset routing > backends.toml > role default > hardcoded}; a fourth tier breaks the precedence model.
- Do NOT write to a stock preset through the TUI. Stock presets are read-only; fork-before-edit is load-bearing.

### Phase 11d: Presets screen (complexity: moderate, kind: feature)

**Objective:** Preset browser + diff viewer. Depends on 10c + 11a.

**What to implement:**
- Split pane: left = preset list grouped by origin (stock / user), right = preview.
- Preview panel shows routing matrix (read-only) + referenced pipeline name.
- Hotkeys: `l` load preset (confirm dialog), `s` save current config as new preset (prompts for name), `d` diff against stock or against current, `r` rename user preset, `x` delete user preset (confirm). Rename/delete ship through shared registry helpers or CLI subcommands in this phase.
- Stock presets are read-only — `r`/`x` attempts display a message.

**Verify:**
- `l` on a stock preset activates it; dashboard banner + status bar update.
- `d` on a user preset shows a routing-matrix diff highlighting differing cells.
- `x` on a stock preset is refused; on a user preset requires confirmation.

**Anti-pattern guards:**
- Do NOT allow `r`/`x` on stock presets. Silent stock mutation breaks `swarm preset diff <stock>` forever.

### Phase 11e: Pipelines screen (complexity: moderate, kind: feature)

**Objective:** Pipeline inspector — read-only v1. Depends on 10c + 11a.

**What to implement:**
- List pane + preview pane.
- Preview renders stage graph as indented ASCII (generator from pipeline YAML — fan-out nodes show fan-out count + merge strategy + failure tolerance).
- Hotkeys: `s` set as active pipeline in current preset (updates user preset TOML; stock preset requires fork first), `l` lint pipeline file (invokes `bin/swarm-validate` or shared validator), `v` full validate including budget/dry-run preview.
- Editing pipelines = external editor. TUI re-reads on focus return.

**Verify:**
- Preview renders ultra-plan correctly — 3 fan-out explorer nodes under a critique merge, then writer, then review.
- `l` on a malformed pipeline highlights the schema violation.
- `v` on a valid pipeline prints the dry-run cost estimate.

**Anti-pattern guards:**
- Do NOT add a pipeline editor in V1. External editor only — building a YAML editor inside Textual is scope creep.
- Do NOT silently re-read pipelines on disk changes. Re-read on focus return only; mid-edit re-reads corrupt the preview's pinned state.

### Phase 11f: Status bar + navigation (complexity: simple, kind: feature)

**Objective:** Persistent bottom bar + top-level navigation hotkeys. Shared across all screens.

**What to implement:**
- Persistent bottom bar: `preset=<name> pipeline=<name> runs_today=N cost_today=$X|n/a last_429_claude=<time|n/a> last_429_codex=<time|n/a>`.
- Top-level hotkeys: `d` dashboard, `s` settings, `p` presets, `i` pipelines, `?` help, `q` quit.
- tcss styling inherits from `tech-radar` theme where feasible.

**Verify:**
- Status bar updates when active preset changes (via 11d).
- Hotkeys work from every screen.
- Theme is visually consistent with tech-radar.

**Anti-pattern guards:**
- Do NOT poll for status-bar data on a separate timer. Derive from the same reactive state the dashboard subscribes to.

### Phase 11g: Dev-loop documentation (complexity: simple, kind: feature)

**Objective:** Document the TUI development loop so future maintainers can iterate fast.

**What to implement:**
- `swarm-do/tui/README.md` documents: venv setup, `textual console` hot-reload flow, how to add a screen, the reactive state model, invariant guards.
- Matches the dev-loop pattern tech-radar operators already know.

**Verify:**
- A fresh operator following the README can launch the TUI, open the Textual dev console, and hot-reload a tcss edit within 5 minutes.
- Invariant-guard section points at 11c's implementation and 10f ADR.

**Anti-pattern guards:**
- Do NOT duplicate the tech-radar dev-loop docs verbatim. Link where patterns match; document only TUI-specific deltas.

---

# Part 5 — Replaceability + non-goals

## Replaceability — keeping underlying layers swappable

Two dependencies are worth explicit architectural attention: the memory layer (today: `claude-mem`) and the task/issue store (today: `beads` via `bd` CLI). Both may be swapped someday. Cheap insurance now prevents a full rewrite later.

### Memory layer — boundary is already clean; keep it that way

**Current state:** the orchestration consumes memory abstractly. No role file, SKILL.md body, or runner script directly invokes `claude-mem` commands or reads its DB schema. Users invoke `mem-search` / `smart-explore` through the skill surface; SessionStart hooks restore context transparently. If claude-mem were uninstalled and replaced with a different memory plugin tomorrow, the swarm would not break.

**Candidates on the radar:**
- Anthropic's native memory features (context compaction, session continuity) — still evolving
- `context-mode` (already installed; uses a different model: indexed sandbox storage with FTS5)
- `superpowers`' memory patterns (if they ever ship one)
- Custom SQLite-backed memory plugin

**Load-bearing rule to preserve this:** no role file, command body, or `bin/swarm-run` script may import claude-mem-specific commands or data shapes. Memory interaction happens through skills (`Skill(claude-mem:mem-search)`) or through hooks we don't author. If this invariant is broken later, document why and reassess the swap cost.

**Action for this plan:** none beyond documenting the invariant. Add a one-liner to the plugin README once packaged.

### Task/issue store (beads) — accept the coupling; don't pre-abstract

**Current state:** every role prompt and every runner invokes `bd` directly. Call sites scattered across SKILL.md + role files + runner scripts.

**Earlier drafts of this plan proposed a `bin/swarm-issue` wrapper.** On reflection, that's a premature abstraction and should not be built now. Reasons:

1. **YAGNI.** No concrete alternative is being evaluated. Building for a hypothetical swap that may never happen is speculation.
2. **An abstraction built without a second implementation solidifies the first implementation's semantics** rather than abstracting them. A wrapper designed from beads alone would leak beads semantics into the verb surface — the new tool's mismatch wouldn't be caught until the real swap.
3. **`bd` is already a stable CLI abstraction.** Wrapping a CLI in a slightly-thinner CLI adds indirection without insulation. Cognitive tax, forever.
4. **The coupling that matters is semantic, not syntactic.** Atomic claim, dependency edges, append-only notes — these are load-bearing. A wrapper cannot conjure atomic claim if a replacement lacks it. False insulation.
5. **Deferred wrapper is better-informed.** Written when a real alternative is being evaluated, the verb surface accommodates both implementations correctly. Written now, it probably doesn't.
6. **This project's own CLAUDE.md:** "Don't design for hypothetical future requirements. Three similar lines is better than a premature abstraction."

**What we do instead — free discipline, zero new code:**

1. **Preflight DRY** — single `bd_preflight_or_die` shell function sourced by every runner. Already planned as packaging Phase 3. This is legitimate DRY, not abstraction.
2. **Grep-consistency** — keep `bd` invocations syntactically uniform (same flag order, same patterns) so a future grep-and-replace is mechanical, not surgical.
3. **Small surface** — don't start using obscure `bd` features we don't need. Staying on a narrow command subset makes any eventual swap cheaper.
4. **Document the semantic coupling** (below) — architectural documentation, not code. Read before evaluating any alternative.

**Load-bearing features any beads alternative must preserve** (the list that actually matters if a swap becomes real):
1. **Atomic claim** (`--claim` returns non-zero if already claimed) — enforces single-worker ownership. Without this, M1 fallback is unsafe.
2. **Append-only notes** — Claude ↔ Codex handoff semantics depend on prior notes staying intact across runs.
3. **Dependency edges** (parent/child, blocks) — expresses the research → analysis → writer chain. Swap target must support or the plan linearizes.
4. **Assignee on create** — routes the right role file at invocation time.

If any candidate lacks all four, the swap cost is dominated by reimplementing them — not by rewriting call sites. A wrapper would not have helped with this.

**Candidates on the radar (for documentation only — no action now):**
- **Linear** — REST API; no native atomic claim (would need label-based lock); rich dependency graph.
- **GitHub Issues** (via `gh`) — universal, free, but no atomic claim, weak dependency edges, rate-limited.
- **Local SQLite** (like enovis-trello / tech-radar use) — total control; full reimplementation; probably the right target if we ever outgrow beads.
- **Plain markdown files** — simplest; no locking, single-worker-only.
- **A beads successor CLI** — lowest migration friction if command surface matches.

**When a wrapper actually makes sense:** when a concrete alternative is under evaluation and we're comparing two real command surfaces. Write the wrapper then — tailored to both implementations, correctly.

**Action for this plan:** none for the beads layer beyond what's already there (preflight DRY in Phase 3). This section exists so future-us remembers why no wrapper was built, and the load-bearing features list exists so future-us knows what to verify in any candidate.

## Rollout state file schema

The file at `${CLAUDE_PLUGIN_DATA}/state/rollout-status.json` is the authoritative record of rollout decisions. Plan prose (Part 2) describes **when** to decide and **what shape** the decision takes; the state file records the value. CLI, TUI, and Phase 1/2/3 gating all read this file.

**Schema (v1, pinned):**

```json
{
  "schema_version": 1,
  "phase_0": {
    "decision": "GO-EVERY-DO | GO-TARGETED | NO-GO | DOGFOOD | pending",
    "selected_mode": "A | B | plugin | none",
    "decided_on": "YYYY-MM-DD | null",
    "cohort_run_date": "YYYY-MM-DD | null",
    "notes": "short rationale; full detail in ${CLAUDE_PLUGIN_DATA}/phase0/runs/<cohort_run_date>/"
  },
  "phase_1": {
    "status": "pending | live | rolled-back",
    "activated_on": "YYYY-MM-DD | null",
    "rolled_back_on": "YYYY-MM-DD | null",
    "rollback_reason": "string | null"
  },
  "pattern_5_trial": {
    "status": "pending | complete | abandoned",
    "completed_on": "YYYY-MM-DD | null",
    "decision": "AUTO-DISPATCH | MANUAL-ONLY | NO-GO | pending",
    "phases_sampled": 0,
    "notes": "short rationale"
  },
  "b1_dispatcher": {
    "status": "pending | shadow | live | rolled-back",
    "shadow_started_on": "YYYY-MM-DD | null",
    "live_cutover_on": "YYYY-MM-DD | null",
    "rolled_back_on": "YYYY-MM-DD | null",
    "notes": "short rationale"
  },
  "role_promotions": {
    "agent-docs":         {"primary": "claude | codex", "promoted_on": "YYYY-MM-DD | null", "measurement_ref": "path or null"},
    "agent-spec-review":  {"primary": "claude | codex", "promoted_on": "YYYY-MM-DD | null", "measurement_ref": "path or null"},
    "agent-clarify":      {"primary": "claude | codex", "promoted_on": "YYYY-MM-DD | null", "measurement_ref": "path or null"},
    "agent-writer.simple":{"primary": "claude | codex", "promoted_on": "YYYY-MM-DD | null", "measurement_ref": "path or null"}
  }
}
```

**Initial state on install:** every `decision` / `status` field is `"pending"`; every `primary` defaults to `"claude"`; every date field is `null`. After the first Phase 0 dogfood decision, `swarm rollout dogfood` records `phase_0.decision = "DOGFOOD"` and `selected_mode = "plugin"` without promoting Codex review to default-on.

**Writers:**
- Phase 0 rollout (Part 2 §2) writes `phase_0`.
- `swarm rollout set <path> <value>` is the generic CLI for updating any field.
- `swarm rollout set phase_1.status live` / etc. — typed helpers for common transitions. Helpers validate enums against the schema.

**Readers:**
- `bin/swarm-run` reads `phase_0.decision` + `phase_0.selected_mode` when deciding whether to invoke Codex review, and reads `role_promotions.*` when resolving routing.
- TUI Dashboard shows a compact rollout-status ribbon at the top.
- CLI `swarm status` prints the file in a human-readable form.
- Any automated rollout logic (e.g., Phase 2's "if analysis flags competition, dispatch Pattern 5") checks `pattern_5_trial.decision == "AUTO-DISPATCH"` before acting.

**Write discipline:**
- Atomic writes only (tempfile + rename). Never partial-update.
- Schema validation on every write (JSONSchema at `swarm-do/schemas/rollout-status.schema.json`).
- Append a one-line audit row to `${CLAUDE_PLUGIN_DATA}/state/rollout-status.log` on every change (`YYYY-MM-DD hh:mm <actor> <field>=<new-value>`). Append-only; plain text; used by `swarm rollout history`.

---

## Non-goals for this refactor

- Do **not** rewrite the orchestration logic itself — it's working. This is a packaging move.
- Do **not** absorb mem-search / smart-explore. They stay in claude-mem.
- Do **not** auto-init beads in repos. Explicit user consent.
- Do **not** publish publicly yet. Local path marketplace only.
- **No data migration needed** — bd data is per-repo, claude-mem memory is untouched. Explicit non-goal.
