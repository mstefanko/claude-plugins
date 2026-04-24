# Packaging history — Phases 0–8 (ARCHIVED)

**Status:** All phases documented here are **closed**. The `/swarm-do` plugin exists at `mstefanko-plugins/swarm-do/`; the migration from claude-mem's `/do` + `~/.swarm/` is complete. This file is audit reference only. **Do not re-execute these phases** — git history covers what was shipped.

**Canonical plan:** the active plan lives at `docs/plan.md`. It references this file under `# Part 3 — Packaging history (archived)`.

**Scope captured in this file:**
- Part 3 — imported inputs table, command family + modes, uniform flags, mode × command compatibility matrix, plugin config surface, operator console + telemetry scaffolding, pre-shipment retention gate.
- Senior-developer reflection on packaging direction.
- Target shape (plugin directory layout + marketplace manifest edit).
- Phased execution plan — Phases 1, 1.5, 2, 3, 4, 5, 6, 7 (all executed).
- Decided answers to the open questions from the original packaging plan.
- Gaps found in review / concerns acknowledged (both Part-3 era).
- New phases inserted — Phase 0 (backup), 2.5 (dogfood), 8 (rollback doc).

**Original packaging-plan context (2026-04-20):** `/do` was a fork of claude-mem's skill. The cache-vs-marketplace split silently reverted edits, and claude-mem couldn't be `/plugin update`d without losing changes. `~/.swarm/` hosted the M1 fallback with no slash-command surface. Packaging Phases 0–8 (below) resolved all of those issues.

---

## Part 3 — Already complete (imported inputs, do not re-decide)

These are **givens**. Their design, gates, and matrices live in Part 1 of this document. Part 3 content below records how they were moved into the plugin; it does not revisit the design decisions.

| Input | Status | Source path | Authority |
|---|---|---|---|
| M1 manual fallback runner (`swarm-run`, `swarm-claude`, `swarm-gpt`, `swarm-gpt-review`) | **Shipped** | `~/.swarm/bin/` | integration plan §4.5 |
| Role prompt bundles (`shared.md` + `claude.md`/`codex.md` overlays for writer / review / spec-review / codex-review) | **Shipped** | `~/.swarm/roles/` | integration plan §4.5 |
| Phase 0 cross-model review harness (`codex-review-phase`, `result-schema.json`, `rubric-template.md`) | **Tooling shipped** — experiment evaluation may still be pending per user | `~/.swarm/bin/codex-review-phase`, `~/.swarm/phase0/` | integration plan §2 |
| Model / effort matrix (Claude + Codex) | **Decided** — per-role resolution baked into runners | `~/.swarm/bin/swarm-run` (reads matrix) | integration plan §1.6 |
| Beads preflight contract (`bd where` hard-stop; no auto-init) | **Decided** | embedded in runners + SKILL.md | integration plan §2.7 (referenced) |
| Orchestrator role files (research, analysis, debug, clarify, writer, spec-review, review, docs, judges, synthesizer) | **Shipped** | `~/.claude/agents/agent-*.md` | existing swarm pipeline |

**Rollout status** (Phase 0 decision, Pattern 5 manual trial results, B1 dispatcher go/no-go, per-role primary-backend promotions) is persisted in the machine-readable state file **`${CLAUDE_PLUGIN_DATA}/state/rollout-status.json`** — not in plan prose. That file is authoritative; this plan is a design document. `bin/swarm status` reads it; Part 2's rollout logic writes to it; Phase 1/2/3 gating reads it. Schema pinned in Part 5 "Rollout state file schema" below.

The prose sections of this plan (Part 2) describe **when a decision is made and what its shape is**; the state file records **the actual value**. Updating rollout status means editing `rollout-status.json`, not editing this plan.

### Command family — shapes vs modes

The plugin exposes **five slash commands**, each representing a materially different pipeline shape. Mode toggles (claude-only / codex-only / balanced) are CLI subcommands on `bin/swarm`, **not** slash commands — they change config, not pipeline.

| Command | Argument contract | Role pipeline | bd issues created | Use case |
|---|---|---|---|---|
| `/swarm-do:do <plan-path>` | path to a plan file | full pipeline (research → analysis/debug + clarify → writer → spec-review → review + docs) | full chain (~7 issues per phase) | Main entry; executes a plan |
| `/swarm-do:resume <bd-id>` | bd issue ID of any stalled/interrupted role | resumes from that role forward, re-reads upstream notes | none new; updates the existing issue | Recovery after M1 handoff, worktree crash, rate-limit interruption |
| `/swarm-do:debug <bd-id>` | bd issue ID of a failed/ambiguous phase | agent-debug only | one debug issue linked to the source | Triage a failed phase without tearing down the pipeline |
| `/swarm-do:compete <analysis-bd-id>` | bd issue ID of a completed analysis | analysis (existing) → 2× writer (claude + codex parallel) → writer-judge | 3 new (writer-A, writer-B, judge) | Manual Pattern 5 trigger (integration §4). **Blocked until integration Phase 2 ships writer-judge.** |
| `/swarm-do:review <target>` | auto-detect: PR URL → `gh` lookup; `base..head` → git range; else file path list | research (read-only) → review + codex-review (if configured) | one review issue scoped to target | Spot-check existing code / PR / branch without running full /do |
| `/swarm-do:research <question>` | free-text question string | research only | one research issue | Ad-hoc fact-finding. Note persists for later re-use |
| `/swarm-do:brainstorm <topic>` | free-text topic string | outside-pipeline; transcript only | **zero** — brainstorm never touches bd | Pre-plan thinking; fills the gap before `/make-plan` |
| `/swarm-do:help` | none | none | none | Prints the decision tree (which command for which task) + mode matrix |

**Mode toggles (CLI, not slash) — thin aliases over presets:**

Preset is the single authoritative state concept (see §1.10). `swarm mode` is a muscle-memory alias that resolves to `swarm preset` calls:

```sh
swarm mode claude-only    # alias: swarm preset load claude-only
swarm mode codex-only     # alias: swarm preset load codex-only
swarm mode balanced       # alias: swarm preset load balanced
swarm mode custom         # alias: swarm preset clear  (no active preset; backends.toml alone drives routing)
swarm mode override <role> <backend>   # per-role override that writes to the active user preset's routing block
                                        # (if no user preset active, forks the current stock preset to a user copy first)
swarm mode status         # alias for swarm preset show  (prints active preset + overrides)
```

Affects every subsequent `/swarm-do:*` invocation until changed. One keystroke response to rate-limit pressure.

**One persistence model — no `current-mode.toml`.** The only state file is `${CLAUDE_PLUGIN_DATA}/current-preset.txt` (single-line filename, or empty). `balanced`, `claude-only`, `codex-only` are stock preset files. `custom` means empty `current-preset.txt` — `backends.toml` alone drives routing, which is the install-time default per §1.10 (preserves the measurement gate). CLI, TUI, and telemetry all read `current-preset.txt` + `presets/<name>.toml` — there is no parallel mode-state file to fall out of sync with.

**Scope — v1 is global (all repos).** `current-preset.txt` lives under `${CLAUDE_PLUGIN_DATA}/`, which is global per-user. Operators working in two repos at once will see the preset flip in both simultaneously. Per-repo preset is deferred to v2; document the v1 limitation explicitly so operators aren't surprised.

### Uniform flags across all commands

All commands accept these per-invocation override flags — cheaper than a full `swarm mode` change for one-off tweaks:

```sh
/swarm-do:do <plan> --backend codex                    # override all role backends for this run
/swarm-do:do <plan> --model gpt-5.4-mini --effort high # override specific axes
/swarm-do:do <plan> --dry-run                          # print bd issues + role pipeline, do not claim
/swarm-do:do <plan> --verbose                          # trace every bd invocation
```

**Override flags are per-invocation only** — they do not persist. Persistent changes are `swarm mode` territory. This coupling is load-bearing: without these flags, `/swarm-claude` / `/swarm-codex` become defensible commands again. The flags are why the rejection holds.

**`--dry-run` semantics:** prints the bd issues that would be created, the role pipeline, the resolved `{backend, model, effort}` triplet per role. Does not claim issues, does not invoke backends. Not the same as "run roles but don't commit."

### Mode × command compatibility matrix

Every command × mode cell has a defined behavior. Surprising runtime degradation is the worst outcome.

| Command | claude-only | codex-only | balanced | custom |
|---|---|---|---|---|
| `/swarm-do:do` | honor | honor | honor | honor |
| `/swarm-do:resume` | honor | honor | honor | honor |
| `/swarm-do:debug` | honor | honor | honor | honor |
| `/swarm-do:compete` | **REFUSE** with error | **REFUSE** with error | run normally | run normally |
| `/swarm-do:review` | honor (single-model review) | honor (single-model review) | honor (cross-model if configured) | honor |
| `/swarm-do:research` | honor | honor | honor | honor |
| `/swarm-do:brainstorm` | honor | honor | honor | honor |
| `/swarm-do:help` | n/a | n/a | n/a | n/a |

**Compete refuses under single-backend modes.** Compete's value is divergence; silent degradation to single-writer defeats the purpose. Error message: `/swarm-do:compete requires both backends. Current mode: <mode>. Run 'swarm mode balanced' or 'swarm mode custom' first, or pass --dry-run to preview.`

**Architectural constraint:** every slash command MUST route through `bin/swarm-run` with a role list. No bespoke orchestration inside command files. If a command needs new logic, it goes into `bin/swarm-run` as a new `--pipeline` preset (e.g., `--pipeline compete`, `--pipeline review-only`). This is the no-drift invariant.

**Commands explicitly rejected** (surface discipline):
- `/swarm-claude`, `/swarm-codex` — these are modes; use `swarm mode`. Adding them as commands duplicates the toggle and requires per-command prefixing.
- `/swarm-code-review` — subsumed by `/swarm-do:review`. "Code review" vs "review" is naming noise.

**Priority order — reordered to align with integration-plan maturity:**
1. `/swarm-do:do` — packaging Phase 2 (required, main entry)
2. `swarm mode` CLI + uniform `--backend/--model/--effort/--dry-run/--verbose` flags — packaging Phase 2 (cheap, pure config, zero infra deps)
3. `/swarm-do:resume` — packaging Phase 2 (required for first handoff-recovery scenario; wraps existing M1 runner logic)
4. `/swarm-do:help` — packaging Phase 2 (trivial static content; one command file)
5. `/swarm-do:debug` — packaging Phase 2 (cheap; wraps existing `agent-debug` role)
6. `/swarm-do:review` — packaging Phase 3 (depends on codex-review role; integration Phase 1 delivers that, and Phase 0 decision gates whether it auto-wires)
7. `/swarm-do:research` — packaging Phase 3 (utility; cheap)
8. `/swarm-do:brainstorm` — packaging Phase 3 (utility; assess whether make-plan covers it first)
9. `/swarm-do:compete` — **gated on integration Phase 2** (writer-judge role must exist; before that, command ships feature-flagged — startup check `swarm doctor` must verify `agent-writer-judge` role + both backends configured before compete accepts invocations)

**Footgun mitigation:** any command that depends on a role not yet shipped checks preconditions on startup and refuses with a clear error. `compete` is the flagship example; `debug` is safe today (role exists); `review` needs codex-review role which ships with integration Phase 1.

### Plugin config surface this migration must support

§1.7 (per-role routing) requires the plugin to load a user-configurable **routing matrix** — not a flat role→backend map. Backend alone is too coarse: the operator needs to choose a specific model within each backend (current Codex lineup: `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.3-codex` — see §1.6 for canonical IDs; Claude side: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`) and the reasoning effort independently. `codex-cli 0.121.0` already exposes `-m/--model`, and the existing `swarm-run:178` already passes `-m "$MODEL"` — the plugin config just needs to expose all three axes.

**Config contract — full triplet per (role, complexity):**
```toml
# ${CLAUDE_PLUGIN_DATA}/backends.toml

[roles.agent-writer.simple]
backend = "codex"
model   = "gpt-5.4-mini"          # cheap coding lane
effort  = "medium"

[roles.agent-writer.moderate]
backend = "claude"
model   = "claude-sonnet-4-6"
effort  = "high"

[roles.agent-writer.hard]
backend = "claude"
model   = "claude-opus-4-7"
effort  = "xhigh"

[roles.agent-docs]                # no complexity-gate needed for this role
backend = "codex"
model   = "gpt-5.4-mini"
effort  = "medium"

[fallback]
on_failure = "fallback"           # "fallback" | "halt"
fallback_backend = "claude"       # where to redirect on primary failure
```

Config keys that must be first-class (do not flatten):
- **Per-role, per-complexity triplet:** `{backend, model, effort}` — not just `primary`.
- **Complexity axes:** `simple | moderate | hard`. A role may omit complexity keys if it's uniform (docs, spec-review); writers must support all three.
- **Fallback behavior:** separate from primary routing. `on_failure` + `fallback_backend` as top-level keys.

**Runner resolution order** in `bin/swarm-run`: operator `--backend`/`--model`/`--effort` flags (each independent) → plugin config lookup by (role, complexity) → role default → hardcoded `claude-opus-4-7 / high`.

**`## Backend Run` note block** extended with `Setting source: plugin-config | operator-override | quota-bias` AND explicit `Model:` and `Effort:` lines (already present).

**Default config ships empty.** `backends.example.toml` is a commented template. No role is promoted to codex-primary until the operator records a measurement and enables the promotion. Keeps the §1.7 measurement gate honest.

### Operator console + telemetry — infra this migration must reserve

Integration plan §1.8 ships an operator console (CLI + TUI — **TUI promoted to V1 as of 2026-04-23**);
§1.9 adds a continuous-measurement architecture; §1.10 adds swappable presets +
pipelines. Reserve scaffolding for all three now:

- **State dir:** `${CLAUDE_PLUGIN_DATA}/` — Anthropic-sanctioned persistent data path (verified live in env today for other plugins). Holds config + in-flight locks + telemetry ledgers.
- **Config file:** `${CLAUDE_PLUGIN_DATA}/backends.toml` — persists across plugin updates.
- **In-flight locks:** `${CLAUDE_PLUGIN_DATA}/in-flight/bd-<id>.lock` — created on `bd --claim` success, deleted on role close. Lockfile content is a JSON blob (atomically written via tempfile + rename) with the schema:
  ```json
  {
    "issue_id": "bd-42",
    "role": "agent-writer",
    "backend": "claude",
    "model": "claude-opus-4-7",
    "effort": "high",
    "preset_name": "balanced",
    "pipeline_name": "default",
    "started_at": "2026-04-23T10:15:32Z",
    "pid": 12345,
    "host": "macbook.local"
  }
  ```
  Powers the TUI dashboard's in-flight table + hotkeys (`c` cancel signals `pid`). Schema version pinned at v1; additive changes only. A stale lockfile whose `pid` is dead is detected by the TUI and displayed with a "stale — sweep?" hint; sweep runs `bin/swarm lock-sweep` which validates process liveness and removes orphans.
- **Telemetry dir:** `${CLAUDE_PLUGIN_DATA}/telemetry/` (new — per integration §1.9):
  - `runs.jsonl` — one row per invocation (schema per integration §1.8)
  - `findings.jsonl` — one row per finding (append-only)
  - `outcomes.jsonl` — append-only ex-post outcome joins (hotfix-within-14d, maintainer_action, recurrence)
  - `adjudications.jsonl` — append-only blinded-verdict rows from monthly adjudication
  - `index.sqlite` — **derived** index (rebuildable from JSONL). FTS5 over finding summaries + joins for scorecard queries. Not load-bearing for core swarm — `bin/swarm-run` writes JSONL directly; SQLite is a cached view.
  - `schemas/` — frozen JSONSchema for each ledger; indexer fails loudly on drift.
- **Ledgers writer:** `bin/swarm-run` appends to `runs.jsonl` on every invocation and `findings.jsonl` per finding extracted from role output. Telemetry errors must **fail-open** — a broken ledger write never blocks the pipeline.
- **`bin/swarm` dispatcher:** single shell entry exposing `swarm status`, `swarm handoff <bd-id> --to <backend>`, `swarm config edit`, plus `swarm preset load/save/diff/list` and `swarm pipeline show/lint/list` (per §1.10). Grows into the full console.
- **`bin/swarm-telemetry` dispatcher (new):** separate binary so the hot path (`swarm-run` writing ledgers) stays minimal. Subcommands: `append`, `rebuild-index`, `query`, `report`, `join-outcomes`, `sample-for-adjudication`. Report output is recommendations only — never rewrites config, prompts, or routing (see integration §1.9 "Analyst, not judge").
- **`bin/swarm-tui` launcher (new — V1 scope per §1.8):** wraps venv bootstrap and launches the Textual TUI. First-run prompts the operator to create `swarm-do/tui/.venv` + `pip install -r requirements.txt` (textual + deps). Install is opt-in — CLI continues to work without the TUI.
- **`bin/swarm-validate` (new — blocks §1.10 user-preset loading):** validates a preset/pipeline against JSONSchema + role existence + invariant guards + cycle detection + budget preview. Never loads a preset that fails validation.
- **Preset dir:** `${CLAUDE_PLUGIN_DATA}/presets/<name>.toml` for user presets; stock presets live under plugin root at `${CLAUDE_PLUGIN_ROOT}/presets/` (read-only). Active-preset pointer: `${CLAUDE_PLUGIN_DATA}/current-preset.txt`.
- **Pipeline dir:** `${CLAUDE_PLUGIN_ROOT}/pipelines/<name>.yaml` (stock, read-only) + `${CLAUDE_PLUGIN_DATA}/pipelines/<name>.yaml` (user).
- **Schema dir:** `${CLAUDE_PLUGIN_ROOT}/schemas/` — JSONSchema for preset.schema.json, pipeline.schema.json, telemetry/*.schema.json. Frozen at v1 — breaking changes bump the version per the ADR in Phase 10f.

**Separation of raw vs. ledger.** Phase 0's per-experiment raw artifacts stay under `~/.swarm/phase0/runs/<date>/<phase>/` (full fidelity, longer retention, audit trail). Production telemetry under `${CLAUDE_PLUGIN_DATA}/telemetry/` is the roll-up (queryable, shorter retention per ADR). They're not duplicated storage — different purposes, different retention. The indexer reads only `telemetry/*.jsonl`, never the raw phase0 tree.

**Pre-shipment gate — retention/privacy.** Before the plugin ships to anyone beyond mstefanko's own workflow, the retention window, PII scrubbing policy, and cross-repo sensitivity tier must be logged as an ADR (proposed path: `swarm-do/docs/adr/0001-telemetry-retention.md`). Findings contain file paths and code snippets; treating them as non-sensitive by default would be wrong. See integration §1.9 "Retention and privacy" for the open questions.

Cheap reservations — JSONL + lockfiles are a few lines; SQLite indexer is deferrable until the JSONL dataset justifies it. Not building the dir structure now means retrofitting the data model later.

---

## Senior-developer reflection: is this the right direction?

**Yes.** Three independent signals point the same way:

1. **Separation of concerns.** claude-mem's stated purpose is *persistent memory / context compression*. Orchestrating a multi-agent beads pipeline is a different product. Bundling them couples the two release cycles and blocks upstream updates.
2. **Prior art.** `obra/superpowers` ships exactly this shape: `.claude-plugin/plugin.json` + `commands/*.md` + `skills/*/SKILL.md` + `agents/*.md` in one owned repo. It's the idiomatic way to register a slash command that composes agents and skills.
3. **The bug we hit is structural.** Edits landed in `~/.claude/plugins/marketplaces/thedotmack/plugin/skills/do/SKILL.md`, but Claude Code loads from `~/.claude/plugins/cache/thedotmack/claude-mem/10.5.2/skills/do/SKILL.md`. Any `/plugin update` would wipe our work regardless. Forking a third-party plugin via in-place edits is never durable.

**One real risk to name up front:** slash-command collisions. If we publish `/do` in our own plugin and claude-mem keeps shipping `/do`, Claude Code picks one and hides the other silently. We rename the user-facing command to avoid ambiguity (see Phase 5).

---

## Target shape

Lives as a new sibling in the existing `mstefanko-plugins` marketplace (GitHub: `mstefanko/claude-plugins`) alongside `obsidian-notes/` and `tech-radar/`. No new marketplace needed.

```
mstefanko/claude-plugins/                     # existing repo — swarm-do joins as sibling
├── .claude-plugin/
│   └── marketplace.json                      # update: add swarm-do entry to plugins array
├── obsidian-notes/                           # existing plugin — untouched
├── tech-radar/                               # existing plugin — untouched
└── swarm-do/                                 # NEW plugin dir, sibling pattern
    ├── .claude-plugin/
    │   └── plugin.json                       # plugin manifest (per-plugin, not marketplace)
    ├── commands/
    │   ├── do.md                             # /swarm-do:do — full orchestrator (main entry)
    │   ├── resume.md                         # /swarm-do:resume — re-enter a pipeline at a bd issue
    │   ├── debug.md                          # /swarm-do:debug — agent-debug on existing bd issue
    │   ├── compete.md                        # /swarm-do:compete — Pattern 5 (two writers + judge), manual
    │   ├── review.md                         # /swarm-do:review — review-only on existing code/PR
    │   ├── research.md                       # /swarm-do:research — ad-hoc research role, no writer
    │   ├── brainstorm.md                     # /swarm-do:brainstorm — pre-plan exploration
    │   └── help.md                           # /swarm-do:help — decision tree for which command to use
    ├── skills/
    │   └── swarm-do/SKILL.md                 # orchestration prompt (moved from claude-mem)
    ├── agents/
    │   ├── agent-research.md
    │   ├── agent-analysis.md
    │   ├── agent-debug.md
    │   ├── agent-clarify.md
    │   ├── agent-writer.md
    │   ├── agent-spec-review.md
    │   ├── agent-review.md
    │   ├── agent-docs.md
    │   ├── agent-analysis-judge.md
    │   ├── agent-writer-judge.md
    │   ├── agent-code-synthesizer.md
    │   └── agent-research-merge.md
    ├── bin/                                  # absorbed from ~/.swarm/bin/ + new entries
    │   ├── swarm-run
    │   ├── swarm-claude
    │   ├── swarm-gpt
    │   ├── swarm-gpt-review
    │   ├── codex-review-phase
    │   ├── swarm                             # NEW — dispatcher (swarm mode / status / preset / pipeline)
    │   ├── swarm-telemetry                   # NEW — ledger tools (§1.9)
    │   ├── swarm-validate                    # NEW — preset/pipeline validation gates (§1.10 Phase 10a)
    │   └── swarm-tui                         # NEW — Textual TUI wrapper (venv mgmt + launch)
    ├── roles/                                # absorbed from ~/.swarm/roles/
    │   └── agent-*/{shared,codex,claude}.md
    ├── presets/                              # NEW — stock swarm presets (§1.10)
    │   ├── balanced.toml
    │   ├── claude-only.toml
    │   ├── codex-only.toml
    │   ├── ultra-plan.toml
    │   ├── competitive.toml
    │   └── lightweight.toml
    ├── pipelines/                            # NEW — stock pipeline YAMLs (§1.10)
    │   ├── default.yaml
    │   ├── ultra-plan.yaml
    │   ├── compete.yaml
    │   └── lightweight.yaml
    ├── schemas/                              # NEW — JSONSchema for validation
    │   ├── preset.schema.json
    │   ├── pipeline.schema.json
    │   └── telemetry/{runs,findings,outcomes,adjudications}.schema.json
    ├── tui/                                  # NEW — Textual TUI module (§1.8 V1)
    │   ├── requirements.txt                  # textual>=0.80, tomli, pydantic
    │   ├── app.py                            # Textual App entrypoint
    │   ├── screens/{dashboard,settings,presets,pipelines}.py
    │   ├── widgets/{matrix,status_bar,stage_graph}.py
    │   ├── styles/app.tcss                   # Textual CSS
    │   └── README.md                         # dev-console setup instructions
    ├── docs/
    │   └── adr/                              # NEW — ADRs (retention, invariants, version policy)
    ├── phase0/                               # absorbed from ~/.swarm/phase0/
    └── README.md
```

**Marketplace manifest edit** (`mstefanko/claude-plugins/.claude-plugin/marketplace.json`): add a third entry to the `plugins` array.

```json
{
  "name": "swarm-do",
  "source": "./swarm-do",
  "description": "Beads-backed multi-agent swarm orchestration: plans, writer/review pipeline, Claude+Codex routing.",
  "category": "orchestration"
}
```

**After the move:**
- claude-mem returns to upstream pristine — can `/plugin update` freely. Keep only `mem-search`, `smart-explore`, and memory hooks from it.
- orchestration lives in one owned repo with one source of truth for the beads preflight.
- `/swarm-do <plan>` and the `~/.swarm/bin/*` runners share the same role files and beads conventions — no more drift between the skill and the fallback runner.

---

## Phased execution plan

### Phase 1: Scaffold the plugin in mstefanko/claude-plugins (complexity: simple, kind: feature) — EXECUTED (do not re-run)

Clone the marketplace repo into a real working dir if not already present (check where `tech-radar/` gets edited from today — use the same location). Then:

- `mkdir -p <repo>/swarm-do/{.claude-plugin,commands,skills/swarm-do,agents,bin,roles,phase0}`
- Write `swarm-do/.claude-plugin/plugin.json` with explicit fields: `name, version, description, author, repository, license, keywords`. No `mcp` or `hooks` fields. Match the shape `tech-radar/.claude-plugin/plugin.json` uses — inherit existing conventions.
- Edit `<repo>/.claude-plugin/marketplace.json` — append the swarm-do entry to the `plugins` array (three entries total: obsidian-notes, tech-radar, swarm-do).
- Commit `feat: add swarm-do plugin (scaffold)` and push to `mstefanko/claude-plugins`.
- In Claude Code: `/plugin marketplace update mstefanko-plugins` → `/plugin install swarm-do@mstefanko-plugins`.

**Dev-loop pattern (matches how tech-radar is likely iterated):**

Claude Code installs plugins by *copying* from the marketplace source into `~/.claude/plugins/cache/mstefanko-plugins/swarm-do/<sha>/`. Editing the cache directly does **not** propagate — that's the bug we're fixing. Two options:

1. **Push-pull cycle (production semantics):** edit in working repo → commit → push → `/plugin marketplace update mstefanko-plugins` → `/plugin install swarm-do@mstefanko-plugins --force`. Slow but authoritative. Use for anything touching the config contract.
2. **Symlink-install (fast dev iteration):** after initial install, replace the cache dir with a symlink pointing at your working clone:
   ```sh
   rm -rf ~/.claude/plugins/cache/mstefanko-plugins/swarm-do/<sha>
   ln -s /path/to/<working-repo>/swarm-do \
         ~/.claude/plugins/cache/mstefanko-plugins/swarm-do/<sha>
   ```
   Edits become live. Break the symlink before any `/plugin marketplace update` to avoid the update overwriting your symlink with a fresh copy.

**Verify:** `/plugin list` shows `swarm-do@mstefanko-plugins`, `/help` lists the new command (after Phase 2 lands), the cache dir exists under `mstefanko-plugins/swarm-do/`.

### Phase 1.5: Command-wrapper + namespace spike — RESOLVED 2026-04-20 — EXECUTED (do not re-run)

Evidence gathered from installed plugins (tech-radar, enovis-trello, context-mode) plus a scratch plugin built at `/tmp/swarm-do-spike/` (files ready for live install if the user wants final confirmation).

**Findings:**

1. **Invocation surface is structural, not optional.** Commands are `/<plugin>:<command>`, skills are `<plugin>:<skill>`. Verified: this session's skill list contains `tech-radar:scan`, `tech-radar:setup`, `tech-radar:tech-radar`, `claude-mem:do`, etc. There is no way to publish a bare `/swarm-do`.
   - **Decision:** slash command invoked as `/swarm-do:do`. Skill auto-trigger key is `swarm-do:swarm-do` (matching tech-radar convention of naming the "main" skill identically to the plugin).
2. **`${CLAUDE_PLUGIN_ROOT}` expansion is shell-scoped, not markdown-scoped.** Confirmed working in:
   - `plugin.json` `mcpServers.args` (context-mode uses `"${CLAUDE_PLUGIN_ROOT}/start.mjs"`)
   - command body **bash code blocks** (enovis-trello uses `${CLAUDE_PLUGIN_ROOT}/scripts/trello-query $ARGUMENTS`)
   - Not verified: expansion inside prose Read instructions like `Read ${CLAUDE_PLUGIN_ROOT}/agents/agent-writer.md`. Treat as unsupported.
3. **`${CLAUDE_PLUGIN_DATA}` exists** in the running env (context-mode sets it to `~/.claude/plugins/data/<slug>/`). Safe to target for the runs.jsonl + lockfiles.
4. **Command and skill frontmatter shapes confirmed** (tech-radar conventions):
   - Command: `description`, `argument-hint`.
   - Skill: `name`, `description`, `allowed-tools`, `author`.
5. **Fat-command / thin-skill is the community pattern.** tech-radar's `commands/scan.md` contains the phases of work; `skills/tech-radar/SKILL.md` is the auto-trigger surface. Same shape fits swarm-do.

**Consequent design rules for Phase 2 path rewrites:**

- **Never write `Read ${CLAUDE_PLUGIN_ROOT}/...` in prose.** Expansion there is unverified.
- **Always access plugin-internal files via a bash block** in the SKILL/command body. Example:
  ```bash
  ROLE_CONTENT=$(cat "${CLAUDE_PLUGIN_ROOT}/agents/agent-writer.md")
  ```
  Or spawn a helper: `${CLAUDE_PLUGIN_ROOT}/bin/load-role.sh agent-writer`.
- **The role-file rewrite** changes from `Read ~/.claude/agents/agent-<role>.md` to a bash helper invocation. Not a prose Read. This is a non-trivial rewrite of the existing SKILL.md's Agent-spawning instructions — budget for it in Phase 2.
- **`bin/*.sh` must be `chmod +x` committed** to the repo. Install does preserve the executable bit from git blob mode, but only if it was set at commit time.

**Live-test artifacts (optional — run if you want a final sanity check):**

Scratch plugin lives at `/tmp/swarm-do-spike/` with 5 files: manifest, marketplace, command, skill, probe script. To verify live:

```sh
/plugin marketplace add /tmp/swarm-do-spike
/plugin install swarm-do-spike@swarm-spike
/swarm-do-spike:do hello world
```

Expected output: probe script prints `PLUGIN_ROOT=<path>`, `PLUGIN_DATA=<path>`, the plugin root listing, and ARGUMENTS=`hello world`. Remove after:

```sh
/plugin uninstall swarm-do-spike@swarm-spike
/plugin marketplace remove /tmp/swarm-do-spike
rm -rf /tmp/swarm-do-spike
```

**Phase 1.5 outcome: Phase 2 is unblocked.** Path rewrites follow the bash-block pattern above.

### Phase 2: Copy + cutover orchestration assets (complexity: moderate, kind: refactor) — EXECUTED (do not re-run)

**Pattern: copy → cutover → delete later.** Do *not* move/rename files. Copy into the plugin, run in parallel with the old paths for a cutover window, then delete originals only after the new paths have run successfully against real work. This keeps the fallback path (direct `~/.swarm/bin/swarm-gpt` from a shell, independent of the plugin) working throughout the migration.

1. **Copy** (leave originals in place):
   - `~/.claude/plugins/marketplaces/thedotmack/plugin/skills/do/SKILL.md` → `~/code/swarm-do/skills/swarm-do/SKILL.md`. Rename skill to `swarm-do`. **Narrow the `description:` frontmatter** so it stops auto-triggering mid-conversation outside `/swarm-do`.
   - `~/.claude/agents/agent-*.md` → `~/code/swarm-do/agents/`.
   - `~/.swarm/bin/*` → `~/code/swarm-do/bin/`.
   - `~/.swarm/roles/*` → `~/code/swarm-do/roles/`.
   - `~/.swarm/phase0/*` → `~/code/swarm-do/phase0/`.
2. **Rewrite paths** in the copies (pattern confirmed by Phase 1.5 spike):
   - SKILL.md: **never write `Read ${CLAUDE_PLUGIN_ROOT}/...` in prose.** Expansion is shell-scoped. Replace `Read ~/.claude/agents/agent-<role>.md` with a bash-block invocation of a helper script (e.g. `${CLAUDE_PLUGIN_ROOT}/bin/load-role.sh agent-writer`) whose output the agent consumes. Add `bin/load-role.sh` as part of this phase.
   - `bin/swarm-run`, `bin/swarm-gpt`, `bin/swarm-claude`, `bin/swarm-gpt-review`, `bin/codex-review-phase`: audit every `~/.swarm/roles/...` and `~/.swarm/phase0/...` reference. Replace with `${CLAUDE_PLUGIN_ROOT}`-relative resolution (or a single sourced `_lib/paths.sh`).
   - Verify worktree safety: no path resolves relative to CWD. Writers run in git worktrees; CWD-relative paths break.
3. **Install-time checks:** executable bit on `bin/*` (plugin install may not preserve it), `${CLAUDE_PLUGIN_ROOT}` resolves correctly, copied SKILL loads.
4. **Cutover window:** run new `/swarm-do` and old `~/.swarm/bin/swarm-gpt` side by side for at least one real phase.
5. **Delete originals** only after Phase 7 verification passes. Until then, both paths work — fallback to direct shell invocation remains available if the plugin breaks.

**Verify:** `/swarm-do <trivial-plan>` runs end-to-end against a scratch repo with `bd init --stealth`. Directly-invoked `~/.swarm/bin/swarm-gpt <bd-id>` still works unchanged.

### Phase 3: Single-source the beads preflight (complexity: moderate, kind: refactor) — EXECUTED (do not re-run)
Currently the hard-stop is duplicated across `SKILL.md`, `swarm-run`, `swarm-gpt`, `swarm-claude`. Drift risk is real.
- Extract to `bin/_lib/beads-preflight.sh` — one function: `bd_preflight_or_die` that runs `bd where`, prints the canonical remediation message, exits 1 on failure.
- Source from every `swarm-*` runner. The skill prompt's Preflight section reads "run `bin/beads-preflight.sh` — follow its instructions" instead of duplicating the check.
- **Verify:** unset `BEADS_DIR` + cd into a no-beads repo + invoke each of `/swarm-do`, `swarm-run`, `swarm-gpt`, `swarm-claude` — all must halt with the same setup message.

### Phase 4: Unfork claude-mem (complexity: simple, kind: refactor) — EXECUTED (do not re-run)
- Diff our `~/.claude/plugins/marketplaces/thedotmack/plugin/skills/do/SKILL.md` against the upstream 10.5.2 tag. Stash anything still needed, then reset the marketplace clone.
- `/plugin update claude-mem@thedotmack` — refresh the cache from upstream.
- **Verify:** `diff ~/.claude/plugins/cache/thedotmack/claude-mem/10.5.2/skills/do/SKILL.md <upstream-tarball>` is empty. Our orchestration is now only in `swarm-do`.

### Phase 5: Rename user-facing command to avoid collision (complexity: simple, kind: refactor) — EXECUTED (do not re-run)
- claude-mem ships its own `/do` in future versions. To prevent shadow-registration:
  - Command name: `/swarm-do` (unambiguous — it's our orchestration, not memory's).
  - Update any muscle memory / notes / README in `~/.swarm/` that still say `/do`.
  - Keep an alias `/do` → `/swarm-do` only if we're certain claude-mem will not reintroduce it (probably don't — safer to retire `/do` in our workflow).
- **Verify:** `/help` shows `/swarm-do` under the `swarm-do` plugin, no duplicate `/do` entries.

### Phase 6: Enforce beads-first on every repo we touch (complexity: simple, kind: feature) — EXECUTED (do not re-run)
Gap the user flagged: most repos in our workspace have no beads rig. cartledger right now fails `bd where`. Two defenses:
1. **Hard stop at command level** (already in `skills/do/SKILL.md` Phase 0). Do not auto-init — the user wants an explicit `bd init --stealth` or `BEADS_DIR` choice.
2. **Optional convenience command**: `/swarm-init-beads` — one-liner that runs `bd init --stealth` with the right gitignore entries. Still explicit; user invokes it. Not auto-run.

### Phase 7: Verification (complexity: moderate, kind: feature) — EXECUTED (do not re-run)
- Dogfood `/swarm-do` on a real cartledger plan phase end-to-end with beads initialized.
- Trigger an explicit M1 handoff: stop the Claude-side writer mid-phase, take the writer bd id, run `swarm-gpt bd-<id> --mode fallback`, confirm notes flow back into the same issue.
- Confirm `/plugin update claude-mem@thedotmack` does not break `/swarm-do`.

---

## Decided answers to the open questions

1. **Command invocation surface:** resolved empirically in Phase 1.5 spike. Skills are plugin-namespaced (`plugin:skill` verified via this session's skill list). Likely form: `/swarm-do:do` or `/swarm-do`. Do not freeze the name until the spike confirms.
2. **Repo location: `mstefanko/claude-plugins` — join the existing `mstefanko-plugins` marketplace as a sibling to `obsidian-notes/` and `tech-radar/`.** Clone the repo to a real working dir (e.g. `~/code/mstefanko-plugins/` or wherever `tech-radar/` is edited today) for iteration. Do **not** edit the marketplace cache at `~/.claude/plugins/marketplaces/mstefanko-plugins/` — that's Claude Code's local clone and gets overwritten on `/plugin marketplace update`. During transition, symlink `~/.swarm/bin` → `<working-repo>/swarm-do/bin` so existing PATH invocations keep working.
3. **Publish: push directly to `mstefanko/claude-plugins`.** The marketplace already exists, already works for `obsidian-notes` + `tech-radar`, and already gives you cache-versioning via GitHub commit SHAs. No 30-day holding pattern — the infrastructure you wanted already exists. Commit + push + `/plugin marketplace update mstefanko-plugins` + `/plugin install swarm-do@mstefanko-plugins`.
4. **Role-file home: plugin-owned, not symlink.** Symlinks into the plugin break silently after `/plugin uninstall` (dangling symlink, no clear error). One-time edit to `Read ~/.claude/agents/...` → `Read ${CLAUDE_PLUGIN_ROOT}/agents/...` (both env vars confirmed live today). Also audit `bin/*` runners for hardcoded `~/.swarm/roles/...` paths.

---

## Gaps found in review — added to phase work

- **Phase 1:** `plugin.json` must declare fields explicitly: `name, version, description, author, repository, license, keywords`. Decide whether to declare `commands/skills/agents` dirs or rely on conventions (superpowers uses conventions). Confirm no `mcp` or `hooks` fields needed, and state it.
- **Phase 1:** Pin the exact `marketplace.json` shape for a local-path plugin before writing.
- **Phase 2:** Narrow the `do` skill's `description:` frontmatter so it **stops auto-triggering** mid-conversation outside `/swarm-do`. Dual-entry (skill auto-trigger + explicit command) must be an explicit choice, not an accident.
- **Phase 2:** Audit **every** hardcoded path — not just SKILL.md. `bin/swarm-run`, `bin/swarm-gpt`, `bin/swarm-claude` all reference `~/.swarm/roles/...`. Plugin-root-relative resolution everywhere.
- **Phase 2:** Add an install-time (or first-run) check that `bin/*` has the executable bit set. Plugin install does not guarantee it survives.
- **Phase 2:** Verify worktree compatibility — any path resolution relative to CWD breaks when writers run in worktrees. Paths must resolve to the plugin root, not the worktree.

## Concerns acknowledged

- **Phase 4 "unfork" is not a clean diff.** The marketplace clone has diverged from upstream 10.5.2. Capture the fork diff as a patch file in `docs/provenance/` inside the new plugin before hard-resetting — preserves the audit trail.
- **`/swarm-init-beads` is a drift vector.** Kept in Phase 6 as a *thin* shell-out to `bd init --stealth` only. No custom logic. If it needs to do more, it becomes a README one-liner the user copies, not a command.
- **Phase 6 was mixing enforcement + convenience.** Split: hard-stop ships in Phase 3 (already there). The convenience `/swarm-init-beads` defers to Phase 8 (new) or drops entirely if we don't need it.
- **In-flight migration safety.** Do not migrate while a swarm is running. Orchestrator's loaded SKILL is in-context; sub-agents re-read role files and would see a torn state. Add to README as a warning.

---

## New phases inserted

### Phase 0: Backup (complexity: simple, kind: feature) — EXECUTED (do not re-run)
Before touching anything:
```bash
tar czf ~/swarm-backup-$(date +%s).tgz \
  ~/.swarm \
  ~/.claude/agents/agent-*.md \
  ~/.claude/plugins/marketplaces/thedotmack/plugin/skills/do
```
One line, saves the migration.

### Phase 2.5: Dogfood before single-sourcing (complexity: moderate, kind: feature) — EXECUTED (do not re-run)
Between Phase 2 (move assets) and Phase 3 (extract shared preflight), run `/swarm-do` against one real phase of a cartledger plan. Catches path / executable-bit / worktree bugs **before** refactoring the preflight logic compounds them.

### Phase 8: Rollback procedure (complexity: simple, kind: feature) — EXECUTED (documentation-only; do not re-run)
Document in README — not executed unless needed:
1. `/plugin uninstall swarm-do@swarm-do`
2. `tar xzf ~/swarm-backup-<ts>.tgz -C /`
3. `/plugin update claude-mem@thedotmack` (restores pre-edit upstream)
4. Verify `/do` works via claude-mem.

---
