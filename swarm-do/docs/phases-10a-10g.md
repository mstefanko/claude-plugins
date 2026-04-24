# Extracted phases — swarm-do run scope

**Source:** `docs/plan.md` (canonical). **Phases:** `10a` → `10b` → `10c` → `10d` → `10e` → `10f` → `10g`. Multi-phase extract.

**Runnable scope for this swarm-do invocation:** the seven `### Phase 10{a,b,c,d,e,f,g}:` sections below, in strict sequence. Orchestrator: iterate each phase once in order. Do not start the next phase until the current phase's review is APPROVED, the writer's branch is merged, and all phase issues are closed. Open exactly one consolidated PR at the end — do not stack PRs.

**Dependency structure** (from `docs/plan.md:32-34`):
- `10a → 10b → 10c` is a strict sequence.
- `10d`, `10e`, `10g` are each independent once `10c` lands — the orchestrator still runs them sequentially.
- `10f` (invariant ADR) can land at any point in the sequence but must land before any shared operator install.

**Prerequisites (all shipped):** Phase 9a–9g telemetry ledgers, the four v1 schemas under `swarm-do/schemas/telemetry/`, `bin/_lib/hash-bundle.sh`, and the `runs.jsonl` append path. Phase 10e depends on the Phase 9 ledger surface.

**Known open follow-ups against Phase 9a output — Phase 10a MUST address `mstefanko-plugins-utu`:**
- `mstefanko-plugins-utu` — swap the relaxed `run_id` pattern for strict ULID. Analysis for 10a must decide whether to close this with a ULID generator or keep the relaxed form; leaving it unaddressed in 10a means the follow-up bleeds into Phase 10e's schema extension.
- `mstefanko-plugins-1zv` — wire the already-computed `_diff_bytes` into the jq row. Any 10x writer touching `bin/swarm-run` may opportunistically fix.
- `mstefanko-plugins-rgb` — widen `runs.schema.json` `timestamp_end.type` to `["string","null"]`. 10e is the natural landing spot (schema already being extended) — fold it in there.

**Complexity signal for the orchestrator's model-selection routing:**
- 10a (`hard`), 10b (`hard`): analysis + writer on opus per the complexity→model table.
- 10c (`moderate`), 10d (`moderate`): analysis + writer on sonnet.
- 10e, 10f, 10g (`simple`): analysis sonnet, writer haiku.

**Risk flags for analysis to treat as first-class inputs:**
- **10b refactors the SKILL.md that dispatches this run.** The orchestrator prompt is itself the target of the refactor. Any mid-phase prompt change takes effect on the *next* `/swarm-do:do`, not this one — analysis must be explicit about commit ordering (refactor commits ship here; new dispatch behavior kicks in on the next invocation). Characterization test must run against the pre-refactor skill and the post-refactor skill with the same fixture; both must produce identical beads graphs.
- **10d cannot dogfood directly in cartledger from this repo.** The phase now requires local synthetic fixture dogfooding before merge plus an operator-driven post-merge verification bead for real cartledger dogfooding. Do not ship presets claiming external cartledger dogfooding until that follow-up bead is closed.
- **10a invariant-guard "hardcodes claude" anti-pattern** is subtle. The guard must resolve via the backends registry — any test that passes by matching a literal `"claude"` string will pass today and break on the next model rename.

**Context references.** The phase text cites sections from the canonical plan (e.g. `§1.7`, `§1.8`, `§1.9`, `§1.10`, `Phase 9a`). When research / analysis needs that context, open `swarm-do/docs/plan.md` and read the cited section directly — do NOT inline its content into notes.

**Lifecycle.** This file is ephemeral. Delete it after all seven phase reviews close; plan.md is the source of truth.

---

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
