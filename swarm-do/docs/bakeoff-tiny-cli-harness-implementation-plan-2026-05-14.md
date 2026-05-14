# Bakeoff Tiny CLI Harness — Implementation Plan

Date: 2026-05-14
Status: implemented through Phase 2 in `claude-plugins/bakeoff`; Phase 3 live dogfood pending; plugin launcher wrapper deferred

Related research:
- `docs/multi-agent-orchestrator-architecture-research-2026-05-14.md`
- Multi-agent patterns evidence brief (sources: Anthropic, ICLR 2025/2026, Selection Bottleneck, Stop Overvaluing MAD, position-bias studies)
- Prompt-template research: `/tmp/bakeoff-prompt-templates-research.md` (MT-Bench, G-Eval, CoVe, Anthropic XML/CoT/multi-agent docs)
- CLI UX brief — **SUPERSEDED.** The brief predates this plan. Where they conflict (`research|build` modes, `decision: synthesize`, single-pass judge, `--providers` rerun overlay), this plan wins.

## Why this revision

The previous draft drifted toward swarm-do scale: 11 modules, 4 schemas, 7 phases, two modes plus a LangGraph escape hatch. That shape killed the predecessor.

Cuts:

1. **Ship research only.** Build mode and worktrees are deleted from v1. If three-mode research with artifact-only judging doesn't beat manual fanout in a week of dogfood, build mode would not have either.
2. **Delete the LangGraph section.** `asyncio.gather` + subprocess + filesystem ledger covers v1 in ~500 lines with zero dependencies. Revisit only if dogfood reveals real resume/HITL friction.
3. **Compress modules.** Five files, one schema (with three type variants), three phases.

Adds:

1. **Three research modes** (`gather`, `compare`, `analyze`) share one pipeline and the same five files. The differences are three worker prompts, three judge contracts, three report renderers — all inline functions branching on a `type` parameter.
2. **Per-provider `scope`** (`codebase` / `web` / `mixed`) so the same harness covers internal codebase research, external web research, and mixed-source bakeoffs.
3. **Hard architectural caps** to keep mode dispatch from becoming a framework.

Second-pass refinements (2026-05-14, post-review):

1. **Six frozen prompt templates** (3 worker + 3 judge) added inline. Every design choice cites a paper or vendor doc (MT-Bench, G-Eval, CoVe, Anthropic XML/CoT/multi-agent). Prompts are no longer hand-wavy.
2. **`bakeoff validate` replaces `bakeoff cancel`** as the 8th verb. `validate` doubles as dry-run and is the seam a future plugin uses; cross-terminal cancel was infrastructure for a 5% case.
3. **JSONC for work orders** so commented templates are actually parseable.
4. **`schema_version: 1`** field for forward-compat migrations.
5. **Worker schema-validation is fail-fast** (`schema_error` → judge sees only the other worker). No re-prompt (that's a degenerate debate chain).
6. **`analyze` mode gets a deterministic position-swap tiebreak** (atomic-count, else worker A) — `analyze` needs a spine even when the swap disagrees.
7. **`runs/latest` symlink** for trivial "find my last run" shell use.
8. **Env-var model overrides cut** (violated work-order-as-config). **`bakeoff cancel` cut** (SIGINT covers).
9. **`bakeoff doctor` now does auth probes**, prints same-family-judge bias acknowledgement, and prints resolved default model IDs.
10. **Plugin seam designed but not built** — match swarmdaddy: one Skill per verb, `/bakeoff:prepare` approval gate, plugin shells out verbatim.

Fourth-pass corrections (2026-05-14, output-contract review):

1. **Swap resolution uses canonical provider ids, not positional labels.** Earlier draft's `resolve_swap` compared `winner_pass1 == winner_pass2` directly, which would turn real agreement (judge consistently picks the same provider) into a spurious tie because the positional label flips when the harness swaps the order. The harness now records `order_map` per pass and maps positional verdicts back to canonical provider ids before comparing. Same rule for `analyze` spine.
2. **Gather judge emits positional source labels (`A`/`B`), not provider names.** Earlier prompt asked for `sources: ["claude","codex"]`, which leaked provider identity into the judge prompt — violating the anonymized-judging invariant. The judge now uses positional labels; the harness translates to canonical ids before rendering.
3. **`decision.json` is mandatory and typed.** Earlier draft marked it conditional. Every terminal state writes one — including `single_provider_only` and `both_failed`. Schema and per-`decision_kind` field-population matrix added. This is the single source of truth the report renderer reads.
4. **Compare workers receive identical prompts, not opposing-side assignments.** Earlier compare worker prompt said "a peer worker defending a different proposal", but both workers see the same task and may pick the same answer. Workers now state their own `position`; judge detects same-position via comparing the two `position` fields and emits `relation: "consensus"` to surface the agreement-with-disagreements case. New `kept_from_nonwinner[]` / `consensus_strongest[]` / `consensus_disagreements[]` fields in the judge's output.
5. **Decision audit + non-winner-preservation are mandatory report sections** in every mode. The judge never becomes a black box that picks one answer and drops the rest — `kept_from_nonwinner` (for picks) or "Strongest material from each provider" (for ties/consensus) is always rendered.
6. **Single-provider path is unified across modes**: judge is skipped for `compare` and `analyze` (no second input to compare/overlay against) and for `gather` (nothing to dedupe). The surviving worker's result is rendered directly with a caveat. `decision_kind: "single_provider_only"`.

Third-pass corrections (2026-05-14, contract-level review):

1. **Worker/judge output is wrapped in `<final_json>...</final_json>` and extracted by regex.** Earlier draft had models emit `<thinking>` then bare JSON, which fails `json.loads(stdout)` whenever the model adds even a trailing newline of commentary. Reasoning lives in `<scratchpad>`; the runner takes the last `<final_json>` block.
2. **Scope is documented honestly as prompt-advisory, not CLI-enforced.** v1 cannot make a "web-scoped" worker stop reading the repo. CLI-level tool restriction is a Phase 2.5 follow-up if dogfood shows workers ignoring scope directives.
3. **Init templates fixed** to include `schema_version: 1` and canonical model IDs (`claude-sonnet-4-6`, `claude-opus-4-7`, `gpt-5.5`) — earlier draft used friendly names and omitted the required version field.
4. **JSONC comment stripper is a state machine, not a regex** — naive regex stripping would corrupt `//` inside URL strings and `/* */` inside `background` text.
5. **Single-provider judge path is mode-specific.** `gather` renders surviving worker's findings (no judge run); `compare`/`analyze` render the surviving result with a caveat (no judge run). Earlier table said "single-provider judge with caveat" generically, which doesn't work for `analyze` (can't pick a spine with one input).
6. **Heterogeneity rule made uniform across modes** — earlier draft had the validation section say "differ on backend/model/scope" while the Lessons section said "compare/analyze stricter than gather". Now it's one rule everywhere: reject identical `backend + model + scope`.
7. **`effort` restored to the schema.** Cut as "codex-specific" was wrong — both Anthropic (extended-thinking budget) and OpenAI (reasoning effort) expose this knob and it materially affects judge quality. Optional field, defaults to `high`, applies to workers and judge.
8. **"Deterministic union" → "structured union"** — an LLM judge performing dedupe is not deterministic. The mechanism is non-synthesizing structured merging, not bit-reproducible determinism.
9. **"N=2 forever" softened** — N=2 in v1 is a product simplicity choice, not a theorem. The literature shows "no consistent benefit past N=3", which is a weaker claim.

## Executive decision

Build `bakeoff research <work-order.json>` with three modes, two providers per run, one artifact-only judge. The work order's `type` field picks the mode. The CLI prints a status table, writes a `report.md`, exits.

No build mode. No worktrees. No diff gates. No DAG. No LangGraph. No TUI. No global config. No plugin system. No mode-specific modules.

## Project setup decision

Implementation home is `bakeoff/` in `github.com/mstefanko/claude-plugins`, as a sibling of `swarm-do/` and `tech-radar/`.

The standalone Python CLI lives under `bakeoff/src/bakeoff`. The repository also contains Claude plugin metadata and `bin/bakeoff` now so a later plugin layer can stay a launcher. Slash commands may draft and approve work orders, then shell out to the CLI; they must not reimplement validation, provider execution, judging, or report rendering.

Implementation marker (2026-05-14):
- Phase 1 implemented: package, `init`, `doctor`, `validate`, JSONC loader, inline validation, process runner, `<final_json>` extraction, status taxonomy, examples, and focused tests.
- Phase 2 implemented: `research` orchestration for gather/compare/analyze, fake-provider test path, position-swap resolution, partial-failure reports, decision/report artifacts, and prompt templates in `providers.py`.
- Phase 3 implementation surface wired: `ls`, `show`, `rerun`, `runs/latest`, and `meta.json`. Live dogfood quota remains pending.

## Goals

1. Automate the mechanical parts of multi-agent research that already work manually.
2. Use heterogeneous models (or heterogeneous scopes) and a separate judge — the patterns the evidence base supports.
3. Keep judgment with the human: work order content, scope, adoption.
4. Make every run a replayable filesystem artifact.
5. Stay small enough to read in one sitting — five files, three modes, one schema.

## Non-goals (v1)

- No build/implementation mode. No worktrees, diff gates, validation commands.
- No LangGraph, DAG, Beads, phase pump.
- No TUI, live token streaming, web UI.
- No global config, profiles, dotfiles.
- No plugin system. No custom providers (Claude + Codex only).
- No Claude Code plugin orchestration in v1. Plugin metadata and launcher wrappers may exist, but the CLI remains the implementation boundary. Slash commands must not make mid-run orchestration decisions.
- No auto-retry, cost-in-dollars tracking, telemetry.
- No debate rounds, critique chains, LLM-blend prose synthesis.
- No automatic adoption — `bakeoff` never mutates anything outside `runs/`.

## Evidence the design follows

Each rule below is selected because the literature supports it.

- **N = 2 providers, hard-capped in code.** ICLR 2025 (5 MAD frameworks × 9 benchmarks): no consistent benefit past N=3. Anthropic explicitly cautions against default subagent spawning.
- **Heterogeneity, via model or scope.** Selection Bottleneck (N=210, 42 tasks): diverse-team + judge wins 0.810 vs homogeneous 0.512. Heterogeneity can come from different models, different scopes, or both.
- **Identical task contract.** Anthropic: vague briefs cause duplicate work. Both workers get the same goal, background, and output schema; diversity comes from model and/or scope, never persona.
- **Judge ≠ workers.** Self-preference bias is well-documented (arXiv 2410.21819). Work-order validator enforces judge `backend + model` differs from both workers.
- **`pick_winner` for compare; never LLM-blend prose synthesis.** Selection Bottleneck: synthesis won 0/42 tasks. `gather` does structured union, `analyze` does annotation overlay — neither is prose-blend.
- **Position-swap is mandatory when the judge picks.** Judges pick the first response 60-75% of the time. `compare` and `analyze` (which pick a spine) run the judge twice with order flipped; only agreement counts.
- **Parallel + single-pass judge.** No debate rounds. Tran & Kiela 2026 showed single-agent matches MAS under matched budgets; rounds add cost without gain.
- **Artifact-only judging.** Judge receives normalized JSON, never raw transcripts. Transcripts live on disk for debugging only.
- **Temperature fixed at 0.7, not exposed.** v2 tuning surface, not a v1 design lever.

## The three modes

Mode is selected by the work order's `type` field. The user picks via `bakeoff init <type>` which writes the right template.

### `gather` — coverage research

**When**: "Find all the places X is used", "What's the state of langgraph?", "What patterns exist for Y on the web?". The deliverable is a coverage map, not a winner.

**Worker prompt**: each provider does independent discovery against its `scope`. Cite evidence (`file:line` for codebase, URL for web). Don't synthesize — return granular claims.

**Judge job**: deduplicate similar claims across providers, tag each claim with its source(s) (`claude-only`, `codex-only`, `both`), flag any pairs that conflict. Single pass — no position-swap, because there is no winner pick.

**Judge output (positional labels — harness maps to canonical provider ids before rendering)**:
```json
{
  "merged_claims": [
    { "id": "M-001", "claim": "...", "evidence": ["..."], "sources": ["A","B"], "confidence": "high" }
  ],
  "conflicts": [
    { "claim_a": "X", "claim_b": "not X", "evidence": {} }
  ],
  "unknowns_union": ["..."]
}
```

**Report leads with**: Decision audit (provider statuses, judge ran/skipped) → Findings (grouped by source: both / claude-only / codex-only) → Conflicts → Unknowns. (Source labels are derived from `decision.json.order_maps.pass1` applied to the judge's positional `sources: ["A","B"]`.)

### `compare` — which answer is right?

**When**: "Should we use X or Y?", "Is this approach correct?", "Which implementation is better?". The deliverable is a defended pick.

**Worker prompt**: each provider produces its full answer (claims + reasoning summary). Same task contract.

**Judge job**: position-swap. Run the judge twice, once with claude presented first, once with codex first. Both passes must name the same winner; otherwise the decision is `tie` and the report defers to the human.

**Judge output (per pass, positional labels — harness maps to canonical ids)**:
```json
{
  "relation": "consensus" | "compare",
  "winner": "A" | "B" | "tie" | null,
  "rationale": ["..."],
  "kept_from_nonwinner": ["..."],
  "consensus_strongest": ["..."],
  "consensus_disagreements": ["..."]
}
```

**Final decision**: `pick_winner: <canonical-id>` if both passes resolve to the same canonical provider; `consensus` if both passes report `relation: "consensus"`; else `tie`. See "Swap resolution for `compare`" below the prompt templates.

**Report leads with**: Decision → Decision audit (provider statuses, swap order maps, judge rationale) → Provider status → (Consensus or Comparison) → Disagreement → **Kept from non-winner** (or "Strongest material from each provider" when ties or consensus).

### `analyze` — explain X thoroughly

**When**: "What does this code do?", "Walk me through this design", "Explain the trade-offs of X". The deliverable is a single explanation, enriched with per-claim trust markers.

**Worker prompt**: each provider produces a thorough explanation with structured claims.

**Judge job**: position-swap pick of a *spine* (the better explanation), then annotate the spine's claims with per-claim verdicts (`agrees`, `disagrees`, `not_covered`) from the loser, plus append any useful claims the loser had that the spine missed.

**Position-swap tiebreak for `analyze`**: unlike `compare` (where the swap output can be `tie` and the report defers to the human), `analyze` needs a deterministic spine to overlay against. If the two passes disagree on spine winner, the tiebreak is: pick the analysis with more atomic claims; if still tied, pick worker `A` (the first provider in `work-order.json`). This is recorded in `decision.json` as `spine_tiebreak: "atomic_count" | "position_a"` so the audit trail explains the pick.

**Judge output (final)**:
```json
{
  "spine_winner": "claude",
  "agreement_swap": "yes",
  "claim_verdicts": [
    { "claim_id": "R-001", "loser_position": "agrees" | "disagrees" | "not_covered", "loser_note": "..." }
  ],
  "additions_from_loser": [
    { "claim": "...", "evidence": ["..."] }
  ]
}
```

**Report leads with**: Decision audit (provider statuses, swap order maps, spine tiebreak reason, judge rationale) → Primary explanation (the spine) with inline `[agrees|disagrees|adds]` annotations → Additions from loser (or, in a tie, "Strongest material from each provider") → Confidence notes.

### What the three modes share

- Same five files.
- Same `runner.py`, `work_order.py`, identical for all modes.
- Same JSON worker result schema (`claims[]` with `evidence[]`).
- Same artifact directory layout.
- Same partial-failure policy.
- Same hard caps (N=2, T=0.7, judge ≠ workers).

What differs per mode lives in three branches inside `providers.py` (worker prompt + judge prompt) and three branches inside `report.py` (renderer). No mode-specific modules.

## User surface

Eight verbs. Adding a verb requires deleting one. Adding a mode requires deleting one. Hard caps.

```
bakeoff                              # orientation
bakeoff init {gather|compare|analyze} # write example work order
bakeoff validate <work-order>        # validate + dry-run (prints resolved providers/budgets/judge, exits)
bakeoff research <work-order>        # run research bakeoff (mode read from work order)
bakeoff rerun <run-id>               # identical-replay of a prior work order with a fresh run-id
bakeoff ls                           # list past runs
bakeoff show <run-id>                # print report.md (also --judge / --judge-prompt)
bakeoff doctor                       # check provider CLIs, auth, and env
```

**`rerun` semantics**: identical-replay only. The previous work order is copied verbatim into a new run-id. No `--providers` overlay, no model substitution. To vary models, edit the work order and run `bakeoff research` again.

**`validate` doubles as dry-run**: it loads the work order, runs the inline-dict validators, resolves provider IDs against `DEFAULT_MODEL_IDS`, and prints the budget/provider/judge block — without invoking any provider. Cheap insurance against typos and the foundation a future plugin layer needs (so plugin authors don't reinvent validation).

**Cancel**: SIGINT (Ctrl-C) in the foreground terminal is the only cancel path in v1. Cross-terminal cancel was cut to keep the verb count at 8 and avoid sentinel-file infrastructure for a 5% use case.

### First-run experience

```
$ pip install bakeoff
$ bakeoff
bakeoff — run the same research task across multiple agents, then judge.

Three modes. Pick one based on what you want:
  gather   coverage research        ("find all X", "what's the state of Y")
  compare  defended pick            ("X or Y?", "is this approach correct?")
  analyze  thorough explanation     ("walk me through X", "what does this do?")

Get started:
  bakeoff init gather       # writes gather.work-order.json in CWD
  bakeoff research gather.work-order.json

Provider CLIs required on PATH: `claude`, `codex`.
Run `bakeoff doctor` to check.
```

### Running it

```
$ bakeoff research gather.work-order.json
bakeoff research  run-id: 2026-05-14-a3f2
  mode:           gather
  run dir:        runs/2026-05-14-a3f2/
  providers:      claude (sonnet, codebase), codex (gpt-5.5, web)
  budgets:        900s wall, 60KB out
  judge:          opus (dedupe + conflict flag, single pass)

[claude]  launching...
[codex]   launching...
[claude]  running   120s elapsed
[codex]   running   120s elapsed
[claude]  ok        342s   18.1 KB
[codex]   ok        411s   22.4 KB
[judge]   running...
[judge]   ok        64s

merged claims:  37  (both: 14, claude-only: 12, codex-only: 11)
conflicts:      2
report:         runs/2026-05-14-a3f2/report.md

next:  bakeoff show 2026-05-14-a3f2
```

Status lines per state transition. No streaming tokens. Heartbeat every 60s. The report is the deliverable; results never print to stdout. `bakeoff show` is how you pipe.

## Configuration philosophy

**The work order IS the config.** Zero global config in v1.

| Concern              | Where it lives                    | Why                                       |
|----------------------|-----------------------------------|-------------------------------------------|
| Mode                 | Work order `type`                 | Per-task                                  |
| Which models         | Work order `providers[]`          | Per-task                                  |
| Scope per provider   | Work order `providers[*].scope`   | Per-task; supports mixed-scope bakeoffs   |
| API keys             | Provider CLI env (we don't touch) | `claude` / `codex` handle their own auth  |
| Parallelism          | Fixed: one process per provider   | Not a knob                                |
| Output format        | Hardcoded: markdown report        | No `--format json` in v1                  |
| Output dir           | `--out runs` (default)            | Per-invocation flag                       |
| Task prompt          | Work order `goal` + `background`  | The whole point                           |
| Temperature          | Not exposed (fixed T=0.7)         | v2 tuning surface                         |

No dotfiles. No profiles. No `bakeoff config`. Editing the work order with `$EDITOR` is the configuration UX.

## Work order schema (one schema, three type variants)

Work orders are **JSONC** — JSON with `//` line comments and `/* ... */` block comments stripped on load. `bakeoff init` writes commented templates; the load path strips comments before parsing with stdlib `json`. No new dependency.

**Comment stripper is a tiny state machine, not a regex.** A regex stripper breaks on `//` inside URLs and `/* */` inside quoted strings — both of which appear in `background` content. The implementation walks the file char-by-char, tracking three states (`NORMAL`, `IN_STRING`, `IN_LINE_COMMENT`, `IN_BLOCK_COMMENT`) and respecting JSON's `\"` and `\\` escapes inside strings. ~40 lines in `work_order.py`. Test corpus must include: URLs in strings, `/*` inside strings, escaped quotes, backslashes before quotes.

```jsonc
{
  // schema_version is the only field bakeoff itself reads for migration.
  // Don't edit this; older work orders are auto-rejected if the validator changes incompatibly.
  "schema_version": 1,

  "id": "rfc-routing",              // unique short slug. Used as run-dir prefix and in `bakeoff ls`.
  "type": "gather",                  // one of: gather | compare | analyze
  "goal": "One sentence outcome statement.",
  "background": "Compact context brief. Files, links, constraints.",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6",     "scope": "codebase" },
    { "id": "codex",  "backend": "codex",  "model": "gpt-5.5",               "scope": "web" }
  ],
  "judge": {
    "backend": "claude",
    "model":   "claude-opus-4-7"
  },
  "budgets": {
    "wall_clock_seconds": 900,
    "max_output_bytes": 60000
  }
}
```

### Validation rules

- `schema_version`, `id`, `type`, `goal`, `providers`, `judge`, `budgets` required.
- `schema_version` must equal `1` in v1. Future-incompatible changes bump this number; older work orders are rejected with a migration message rather than silently misinterpreted.
- `id` must be a non-empty slug. Reject `id` matching `^TODO[-_]` (case-insensitive) — that's the init-template placeholder; running it unmodified is always a mistake.
- `type` must be one of `gather`, `compare`, `analyze`.
- `providers` must have exactly 2 entries (hard cap in code).
- `providers[*].id` unique.
- `providers[*].backend` ∈ {`claude`, `codex`}.
- `providers[*].scope` ∈ {`codebase`, `web`, `mixed`}. `mixed` means the worker has access to both codebase context and web search; defaults to `mixed`.
- `judge.backend + judge.model` (the full pair) must differ from each worker's `backend + model` pair. Same backend with a different model (e.g., `claude/opus` judge alongside `claude/sonnet` worker) is allowed — see "Model selection" below for the rationale.
- Workers must differ on at least one of `backend`, `model`, or `scope`. Two providers with identical `backend + model + scope` are rejected — that's just running the same configuration twice. This rule is **uniform across all three modes**; there is no stricter rule for compare/analyze. The "same-backend, same-scope, different-model" pair (e.g., claude/sonnet + claude/opus on codebase) is legal everywhere but recommended only for cost-vs-quality comparisons within a family.
- `budgets.wall_clock_seconds` and `budgets.max_output_bytes` positive.
- No `decision` field — the mode determines judge behavior, not a per-run flag.
- `providers[*].effort` is optional ∈ {`low`, `medium`, `high`}; defaults to `high`. Both Anthropic and OpenAI expose this knob at the API/CLI level; the harness passes it through as `--effort` for Claude Code and `model_reasoning_effort` for Codex. It also applies to `judge.effort` (default `high`).
- No `synthesize` decision exists. Anywhere.

Inline dict validators only. No `jsonschema` dependency. No `schemas/` directory.

Validator error messages must name the offending field and quote the rule (e.g., `providers[1].backend must be one of: claude, codex (got "anthropic")`). "Inline validation" is not an excuse for terrible errors — Phase 1 exit criteria check this.

## Model selection and defaults

Every run uses **2 workers + 1 judge = 3 model invocations**. The work order's `providers[]` defines workers; `judge` defines the judge. Model choice is per-task — there is no global default outside the templates `bakeoff init` writes.

### The shape of the default ensemble

For every mode, the default is **Claude Sonnet + Codex GPT-5.5 as workers, Claude Opus as judge.**

Rationale:

- **Sonnet workers, Opus judge** is the cheap-but-good shape. Two cheaper workers do parallel exploration; one strong judge does the harder synthesis/picking step. Selection Bottleneck explicitly found "a weaker model improves performance while reducing cost" (p < 1e-4) — Opus on every worker triples cost without proportional quality gain.
- **Claude + Codex as workers** gives cross-family heterogeneity, which Selection Bottleneck (0.810 diverse vs 0.512 homogeneous) shows matters more than raw model strength.
- **Opus as the judge** satisfies the `judge ≠ workers` rule (the pair `claude+opus` ≠ `claude+sonnet`) while keeping judging in a strong reasoning model. Same-family bias risk (Claude judging Claude) is accepted because position-swap is the primary bias mitigation for the picking modes, and gather's judge does no picking.

### What `bakeoff init <type>` writes

The three init templates are identical except for `type` and the default scopes per provider. The user edits `goal`, `background`, and (if desired) scopes/models, then runs.

`bakeoff init gather` writes (canonical model IDs, JSONC with header comments):

```jsonc
// bakeoff gather work order — edit `id`, `goal`, `background`, then run:
//   bakeoff validate <this-file>   # dry-run + typecheck
//   bakeoff research <this-file>
{
  "schema_version": 1,
  "id": "TODO-rename-this",
  "type": "gather",
  "goal": "ONE SENTENCE: what coverage are you looking for?",
  "background": "MULTI-LINE: relevant files, links, what you already know.",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "effort": "high", "scope": "codebase" },
    { "id": "codex",  "backend": "codex",  "model": "gpt-5.5",           "effort": "high", "scope": "web" }
  ],
  "judge":   { "backend": "claude", "model": "claude-opus-4-7" },
  "budgets": { "wall_clock_seconds": 900, "max_output_bytes": 60000 }
}
```

Templates always write **canonical model IDs** (`claude-sonnet-4-6`, `claude-opus-4-7`, `gpt-5.5`), never friendly names, so the work order is reproducible months later. Friendly names are pass-through if the user writes them, but `init` does not.

`bakeoff init compare` writes the same shape with `type: "compare"` and both workers at `scope: "mixed"` (compare questions usually benefit from each worker having access to both codebase and web).

`bakeoff init analyze` writes the same shape with `type: "analyze"` and both workers at `scope: "codebase"` (analyze tasks are usually local code explanation).

The split-scope default for `gather` (codebase + web) is deliberate: it's the most ergonomic starting point for both "research langgraph" (user edits both to `web`) and "find all uses of X" (user edits both to `codebase`).

### How this answers concrete questions

- **`bakeoff research langgraph`** → user runs `bakeoff init gather`, edits goal, changes both scopes to `web`, runs. Models in play: Claude Sonnet + Codex GPT-5.5 doing web research; Claude Opus judging the merged findings.
- **"Are there bugs in this file?"** → `bakeoff init gather`, edit goal, leave codebase scope on worker A, change worker B to `codebase`. Same three models.
- **"Should we use X or Y?"** → `bakeoff init compare`, edit goal/background, run as-is (defaults are mixed scope). Same three models, with position-swap on the judge.

In every case, **Sonnet + GPT-5.5 + Opus is the default ensemble.** The user changes models per task by editing the work order.

### Supported models per backend (v1)

| Backend  | Friendly name | Default canonical ID (as of 2026-05-14) | Notes                                            |
|----------|---------------|------------------------------------------|--------------------------------------------------|
| `claude` | sonnet        | `claude-sonnet-4-6`                      | Worker default                                   |
| `claude` | opus          | `claude-opus-4-7`                        | Judge default                                    |
| `claude` | haiku         | `claude-haiku-4-5-20251001`              | Worker option; not recommended as judge          |
| `codex`  | gpt-5.5       | `gpt-5.5` (CLI default at install time)  | Worker default; `effort` low/medium/high         |
| `codex`  | gpt-5         | `gpt-5`                                  | Worker option                                    |

### Model versioning — how to stay current without churn

Three rules:

1. **Init templates write canonical model IDs into the work order, not friendly names.** A work order written today still invokes the exact same model six months from now. Reproducibility is the default.
2. **Bakeoff has one place that holds the current canonical IDs**: a `DEFAULT_MODEL_IDS` constant in `providers.py`. Updating defaults when a new model ships = changing one constant + cutting a release. Users who upgrade bakeoff get new defaults; existing work orders are unaffected.
3. **`meta.json` records the resolved model ID per provider after each run** (from `--model` in the CLI invocation). The audit trail always shows what actually ran.
4. **Model strings in work orders are pass-through.** If you write `"model": "sonnet"`, bakeoff sends `--model sonnet` to the CLI verbatim — bakeoff does no alias resolution at run time. Whether that works depends on the CLI; bakeoff's own tooling always emits canonical IDs.

No env var overrides for default model IDs in v1. They were considered (`BAKEOFF_MODEL_CLAUDE_SONNET=...` etc.) and cut — they violate the "work order IS the config" principle and split the source of truth between the artifact and machine state. Power users who want different defaults edit the work order after `init`, or wait one bakeoff release for the new canonical ID to ship in `DEFAULT_MODEL_IDS`.

Why not a global config file (`~/.bakeoff/models.toml`)? Same reason. Two users running the same work order in different weeks must invoke the same models. Reproducibility is a v1 goal; ergonomic shorthand isn't.

### When to override the defaults

| Want                                       | Edit                                                          |
|--------------------------------------------|---------------------------------------------------------------|
| Opus on both workers (harder task)         | Set both `providers[*].model` to `opus`. Cost ~3x.            |
| Both workers researching the web           | Set both `providers[*].scope` to `web`.                       |
| Both workers in the codebase               | Set both `providers[*].scope` to `codebase`.                  |
| Codex as the judge                         | Set `judge.backend` to `codex`, `judge.model` to `gpt-5.5`.   |
| A third opinion                            | Not supported. N=2 is a hard cap.                             |
| Different temperature                      | Not supported in v1. Fixed at 0.7.                            |

### Validator interaction with these defaults

- `judge.backend + judge.model = claude + opus` differs from `worker[0].backend + model = claude + sonnet` (the *pair* differs). Valid.
- It also differs from `worker[1].backend + model = codex + gpt-5.5`. Valid.
- Workers differ on backend (claude vs codex), model (sonnet vs gpt-5.5), and scope (codebase vs web for gather). All three axes are heterogeneous in the default templates.

Same-family bias (Claude/opus judging Claude/sonnet output) is an accepted v1 risk. The position-swap mitigates the more-studied position bias; same-family preference is less well-characterized in the literature and the cost of forcing cross-backend judging (requiring a third backend) outweighs the benefit in v1. Revisit if dogfood shows judge agreement skews toward Claude workers.

## Module set (five files)

```
bakeoff/
  .claude-plugin/plugin.json
  bin/bakeoff
  pyproject.toml
  README.md
  src/bakeoff/
    __init__.py
    cli.py         # argparse, dispatch, init/doctor/validate/ls/show/rerun
    work_order.py  # JSONC load (strip comments) + inline-dict validation (3 type variants)
    runner.py      # asyncio subprocess, process-group kill, timeout, output cap
    providers.py   # argv + prompts for workers and judge, branches on type/scope
    report.py      # render report.md, branches on type
  tests/
    test_work_order.py
    test_runner.py
    test_modes_end_to_end.py
    test_decisions.py
    test_report.py
  examples/
    gather.work-order.json
    compare.work-order.json
    analyze.work-order.json
```

Five source files. Three example work orders. Per-mode logic is **branches inside `providers.py` and `report.py`**, not new files. If `providers.py` or `report.py` ever exceeds ~500 lines, the next refactor is to extract pure helpers, not to add mode-specific modules.

Dependencies: stdlib only — `argparse`, `asyncio`, `subprocess`, `json`, `pathlib`. `pytest` for tests. No `jsonschema`, `pydantic`, `rich`, `langgraph`.

## Concurrency model

`asyncio` everywhere. `runner.py` exposes `async def run_provider(...)`. The research pipeline does:

```python
worker_results = await asyncio.gather(*[run_provider(p) for p in providers], return_exceptions=True)
# then dispatch to mode-specific judge handling
if mode in ("compare", "analyze"):
    pass1 = await run_judge(prompt_swap_order(worker_results, "ab"))
    pass2 = await run_judge(prompt_swap_order(worker_results, "ba"))
    decision = resolve_swap(pass1, pass2)
else:  # gather
    decision = await run_judge(prompt_single(worker_results))
```

`return_exceptions=True` is load-bearing: a raised exception in one provider must not nuke siblings' partial results. The runner catches its own exceptions and returns a status object; it never raises out.

## Partial-failure policy

For each provider, the runner returns exactly one status: `ok`, `timeout`, `output_cap`, `exit_error`, `schema_error`, `missing_provider`.

| Provider statuses        | Per-mode behavior                                                                          | Exit code |
|--------------------------|---------------------------------------------------------------------------------------------|-----------|
| both `ok`                | full mode behavior (run judge as specified)                                                 | 0         |
| one `ok`, one non-`ok`   | **per-mode**, see below — judge is skipped except in gather                                 | 0         |
| both non-`ok`            | skip judge entirely; report lists provider statuses and stderr pointers                     | 2         |

**Single-provider success (one worker ok, one failed) — per mode:**

- **`gather`**: render the surviving worker's findings directly in the report (no dedupe needed — there's nothing to merge against). Mark each claim with `sources: ["<surviving-id>"]` so downstream readers know coverage is half. Skip the judge — the judge prompt requires two outputs and has no merge to perform with one. Decision: `single_provider_only`. Report opens with a `## Provider status` block flagging the failed provider.
- **`compare`**: skip the judge — there's no second position to compare against. Render the surviving worker's defended position with a clear caveat: "no comparison possible — surfacing single result." Decision: `single_provider_only`.
- **`analyze`**: skip the judge — there's no second analysis to overlay against. Render the surviving worker's analysis with a caveat: "no overlay possible — single analysis surfaced." Decision: `single_provider_only`.

In all three modes, the report's `## Provider status` section points at `providers/<failed-id>/stderr.txt` so the user can triage. Partial success is success. No auto-retry. The user reruns explicitly.

## Signal handling and idempotency

- SIGINT (Ctrl-C) in the foreground terminal: cancel `asyncio` tasks, kill all provider process groups, write `status: cancelled` per provider, exit non-zero. Run dir left intact.
- Re-running with the same `--run-id` against an existing dir: refuse unless `--force`. No partial-resume in v1.
- No cross-terminal cancel verb. If you need to kill a backgrounded run, find it with `ps`/`pgrep` and signal it. This was a deliberate cut — sentinel-file plumbing for the 5% case wasn't worth the verb.

## Artifact layout

```
runs/<run-id>/
  work-order.json            # exact copy of input
  meta.json                  # run-id, type, started_at, finished_at, bakeoff version, provider CLI versions
  providers/
    <provider-id>/
      prompt.txt
      stdout.txt
      stderr.txt
      final.json             # parsed result JSON (absent if schema_error)
      status.json             # { status, exit_code, wall_seconds, output_bytes }
  judge/
    prompt-pass1.txt          # compare/analyze only (absent if judge skipped)
    result-pass1.json         # absent if judge skipped
    prompt-pass2.txt          # compare/analyze only (absent if judge skipped)
    result-pass2.json         # absent if judge skipped
    prompt.txt                # gather only (absent if judge skipped)
    result.json               # gather only (absent if judge skipped)
  decision.json               # ALWAYS written. Final decision, audit trail, kept-from-nonwinner material.
  report.md
runs/latest                   # symlink to most recent run-id directory
```

**`decision.json` is mandatory** — every terminal run state (success, tie, consensus, partial-success, both-fail) writes one, never absent. It is the single source of truth the report renderer reads. Schema:

```json
{
  "decision_kind": "pick_winner" | "tie" | "consensus" | "single_provider_only" | "both_failed" | "structured_union",
  "mode": "gather" | "compare" | "analyze",
  "judge_ran": true,
  "provider_statuses": {
    "claude": { "status": "ok", "wall_seconds": 342, "output_bytes": 18512 },
    "codex":  { "status": "ok", "wall_seconds": 411, "output_bytes": 22937 }
  },
  "order_maps": {
    "pass1": { "A": "claude", "B": "codex" },
    "pass2": { "A": "codex",  "B": "claude" }
  },
  "canonical_winner": "claude",
  "spine_tiebreak": "swap_agreement",
  "judge_rationale": ["...one or two sentences per pass..."],
  "kept_from_nonwinner": [
    { "claim": "...", "evidence": ["..."], "source_provider": "codex" }
  ],
  "consensus_strongest": [],
  "consensus_disagreements": [],
  "caveats": ["single_provider_only: codex schema_error; rendering claude result only"]
}
```

Fields populated per `decision_kind`:

| Field                       | pick_winner | tie     | consensus | single_provider_only | both_failed | structured_union (gather) |
|-----------------------------|-------------|---------|-----------|----------------------|-------------|---------------------------|
| `judge_ran`                 | true        | true    | true      | false                | false       | true                      |
| `order_maps`                | both passes | both    | both      | omitted              | omitted     | pass1 only                |
| `canonical_winner`          | provider-id | null    | null      | surviving id         | null        | null                      |
| `spine_tiebreak`            | analyze only| analyze | omitted   | omitted              | omitted     | omitted                   |
| `kept_from_nonwinner`       | populated   | omitted | omitted   | omitted              | omitted     | omitted                   |
| `consensus_strongest`       | omitted     | omitted | populated | omitted              | omitted     | omitted                   |
| `consensus_disagreements`   | omitted     | omitted | populated | omitted              | omitted     | omitted                   |
| `caveats`                   | usually empty | as needed | as needed | required           | required    | usually empty             |

`gather`'s `structured_union` outputs `merged_claims[]` (in `judge/result.json`) and refers to it from `decision.json` rather than duplicating; the report renderer reads both.

This way the report **never silently drops useful loser material**: `kept_from_nonwinner` (for `compare`/`analyze` picks) and `consensus_strongest` (for ties/consensus) are first-class fields the renderer must surface.

`runs/latest` is a symlink updated atomically at run start. Enables `bakeoff show $(readlink runs/latest)`, makes "find my last run" trivial in shell scripts. One line of code; no infrastructure.

Filesystem IS the ledger. No SQLite, no index.

### Retention

Retention is **manual** in v1. Each run is a self-contained directory under `runs/`; delete with `rm -rf runs/<run-id>`. Approximate footprint: ~100 KB/run (prompts + stdouts + JSON), so 100 runs ≈ 10 MB. No `bakeoff prune` verb, no auto-cleanup, no retention policy. If dogfood reveals users actually want pruning, it's a one-verb addition documented in the Future section.

## Worker result schema (constant across modes)

```json
{
  "status": "complete",
  "claims": [
    { "id": "R-001", "claim": "Short factual claim.", "evidence": ["file/path:line or URL"], "confidence": "high" }
  ],
  "conflicts": [],
  "unknowns": [],
  "recommended_next_checks": []
}
```

Allowed statuses: `complete`, `complete_with_concerns`, `needs_context`, `blocked`.

`confidence` is a discrete enum: exactly one of `high`, `medium`, `low`. G-Eval found discrete buckets outperform free-text confidence; the validator enforces the enum so judges can rely on it.

Evidence format varies by `scope` (codebase → `"path:line"`, web → `"https://..."`) but the schema is `array[string]` either way. The worker prompt enforces the format expected for its declared scope.

**Worker output validation is fail-fast.** If a worker returns invalid JSON or a JSON object that doesn't match this schema, the runner records `status: schema_error` and writes `final.json` as absent. This degrades into the "one ok, one non-ok" partial-failure path: the judge is **not** run (see Partial-failure policy for per-mode behavior — `compare` and `analyze` cannot judge with one input, and `gather` has nothing to dedupe against). No re-prompt loop: re-prompting is a degenerate debate chain, and debate chains are banned.

## Prompt templates (frozen for v1)

These templates are the highest-leverage code in the harness. They live in `providers.py` as constants with `{PLACEHOLDER}` fields filled at call time. Every design choice below traces to a paper or vendor doc; do not improvise.

**Cross-cutting design choices (apply to all six prompts):**

- **XML scaffolding** (`<task>`, `<rules>`, `<output_format>`, `<scratchpad>`, `<final_json>`) — Anthropic prompting docs; reduces instruction/data confusion. Portable across Claude and Codex.
- **`<scratchpad>` reasoning before `<final_json>` block** — G-Eval (arxiv 2303.16634) and Anthropic CoT guide: reasoning-first improves both judge agreement with humans (~10–15 pts) and structured-output validity. The harness extracts the JSON from the **last** `<final_json>...</final_json>` block in the stdout — never `json.loads(stdout)` directly. If no `<final_json>` block is found, or its contents are not valid JSON matching the schema, the runner records `status: schema_error`.
- **`<final_json>` extractor implementation**: regex `r"<final_json>\s*(.*?)\s*</final_json>"` with `re.DOTALL`, take the last match, parse with stdlib `json`. ~5 lines in `runner.py`.
- **"Do not invent citations" + "uncited" bucket** — Chain-of-Verification (arxiv 2309.11495); Anthropic's legal-tech case study (19% → <4% hallucination).
- **Discrete `{high,medium,low}` confidence and 1–5 rubric scores** — G-Eval form-filling paradigm; discrete enums reduce variance.
- **"Length is NOT a virtue"** in judge prompts — verbosity-bias mitigation; MT-Bench and Arize evidence-based prompting.
- **Identical worker prompts across the two workers** — Anthropic multi-agent research blog (2025): heterogeneity comes from the model, not personas. Diverging the prompts splits the source of variance.
- **No model identity in judge prompts** — `final.json` and `status.json` are stripped of `provider.id` before being shown to the judge. Mitigates self-preference and same-family bias.

Full research and citations: `/tmp/bakeoff-prompt-templates-research.md`.

### Worker prompt — `gather`

```
You are a research worker. Your job is to enumerate facts, references, and existing artifacts relevant to the question — NOT to synthesize, recommend, or pick a winner. A separate judge will deduplicate your output against a peer worker's output later.

<question>
{GOAL}
</question>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- Enumerate findings. Do NOT synthesize, rank, or recommend.
- Every claim MUST carry a citation: file:line, URL, or doc heading. If you cannot cite it, omit it from `claims` and add it to `unknowns`.
- Do not invent citations. If a source is not in <context> and not retrievable, do not claim it.
- Prefer breadth over depth. Surface 5–15 distinct findings rather than 2 exhaustive ones.
- If two findings contradict, list both — do not resolve the conflict.
- If you do not know, return `unknowns` rather than guessing.
- Confidence is one of: high, medium, low. Default to medium when uncertain.
</rules>

<process>
1. In <scratchpad> tags, list candidate findings and their sources. Cross out any you cannot cite.
2. For each remaining finding, ask: "Is this a fact, or my opinion?" Drop opinions.
3. Emit the JSON object matching the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema (status, claims[], conflicts[], unknowns[], recommended_next_checks[]). No content after </final_json>.
</output_format>
```

`{SCOPE_INSTRUCTIONS}` is injected per provider based on `providers[*].scope`:
- `codebase`: "Search the current working directory and cite as `path/to/file.ext:line`. Do not invoke web search."
- `web`: "Search the web and cite as full URLs. Do not assume the user's codebase is available."
- `mixed`: "Use both the codebase and web search. Cite as `path:line` for code, full URLs for web."

**Scope is prompt-advisory in v1 — not CLI-enforced.** The provider CLIs (`claude`, `codex`) run in the user's shell with whatever tools they're configured to expose. A "web-scoped" claude worker invoked in a git checkout can still read files; a "codebase-scoped" worker can still call its web tool if enabled. The plan deliberately accepts this — CLI-level tool restriction (`--allowedTools`/`--disallowedTools` for `claude`, equivalent for `codex`) is a Phase 2.5 follow-up if dogfood shows workers ignoring scope directives. For v1, scope's job is to vary the *prompt context* the two workers receive, which is sufficient to produce heterogeneity in outputs even if both workers technically have access to the same tools. This is documented honestly in `bakeoff doctor` output: "Scope is advisory; providers may use any tool their CLI permits."

### Worker prompt — `compare`

Both workers receive **identical prompts** — they are not pre-assigned opposing sides. Each worker reaches its own position on the question and then defends it. If both workers happen to reach the same position, the judge surfaces that as `consensus` (see judge prompt).

```
You are answering a comparison question. Your job:
1. Reach a position on the question — pick one option, or "neither", or "either is acceptable".
2. Mount the strongest honest defense of the position you reach — not a balanced essay. A judge will later weigh your case against a peer worker who answered the same question independently.

<question>
{GOAL}
</question>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- First decide your position; then defend it. Do not hedge after you've decided.
- State your `position` as a single declarative sentence ("X is the right choice because...", "Neither X nor Y because...", "X and Y are equivalent for this use case").
- Honesty constraint: if a fact undercuts your position, acknowledge it in tradeoffs rather than hiding it. Hidden weaknesses cost you credibility with the judge.
- Cite evidence as file:line, URL, or doc heading. Do not invent citations.
- Distinguish CLAIM (what you assert) from EVIDENCE (why a third party should believe it) from TRADEOFF (what you give up).
- If you cannot defend a sub-claim, drop it rather than weakening it with "may" / "might" / "could potentially".
- Confidence is one of: high, medium, low.
</rules>

<process>
1. In <scratchpad>, decide your position. List the 3–5 strongest claims for it and the 2–3 strongest counter-arguments you must address.
2. For each claim, locate concrete evidence. Drop claims you cannot ground.
3. Decide which tradeoffs to surface honestly (judges penalize hidden ones).
4. Emit the JSON object per the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema, plus a top-level `position` field (the one-sentence thesis you defended). The `claims[]` array carries the position's claims; the `conflicts[]` array carries the position's acknowledged tradeoffs (claims against your own position you choose to surface). No content after </final_json>.
</output_format>
```

The work order schema for `compare` workers therefore includes a top-level `position: string` field in addition to the standard worker result schema. The judge uses it to detect the same-position case.

### Worker prompt — `analyze`

```
You are producing an analysis/explanation of the subject below. A judge will later select your analysis or a peer's as the "spine" and overlay the loser's annotations onto the winner. Optimize for: a clear spine of reasoning, with each step independently checkable.

<subject>
{GOAL}
</subject>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- Produce a linear chain of reasoning steps. Each step is a discrete, atomic claim that a peer could independently mark "agrees", "disagrees", or "adds nuance".
- Number your steps. Avoid forward references ("as discussed below"); a later merger may overlay annotations on each step independently.
- Cite evidence per step (file:line, URL, or doc heading). Do not invent citations.
- Mark each step with a confidence in {high, medium, low}. Low-confidence steps invite peer corrections.
- If a step depends on an assumption, surface the assumption explicitly as its own step.
- Do not summarize at the end. The judge handles synthesis.
</rules>

<process>
1. In <scratchpad>, sketch the spine: what is the minimum sequence of steps a reader needs to reach the conclusion?
2. For each step, write one atomic claim + its evidence. Split compound steps.
3. Self-check: can a reader disagree with any single step without invalidating the whole? If not, split further.
4. Emit JSON per the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema. The `claims[]` array IS your spine — each entry is one atomic step, in order, with its own evidence and confidence. No content after </final_json>.
</output_format>
```

### Judge prompt — `gather`

Single pass. No position swap (judge picks no winner).

```
You are a deduplication and conflict-flagging judge. You receive two coverage outputs (A and B) from research workers. Your job: produce a single unified union — merge duplicates, surface conflicts, preserve citations. Do NOT pick a winner.

You do not know which model produced A or B. Use the positional labels "A" and "B" only.

<worker_a_output>
{FINAL_JSON_A}
</worker_a_output>

<worker_b_output>
{FINAL_JSON_B}
</worker_b_output>

<rules>
- Merge claims that make the SAME assertion about the SAME entity, regardless of wording. Preserve all citations from both sources on the merged claim, and tag `sources` using the positional labels: `["A"]`, `["B"]`, or `["A","B"]`.
- If two claims make CONFLICTING assertions (e.g., A says X is true, B says X is false), do NOT pick a side. Emit a conflict entry listing both claims (`claim_a`, `claim_b`), both citations, and a one-line description of the disagreement.
- Preserve confidence. If two merged claims have different confidences, take the lower.
- Do not introduce new claims. You may only union, dedupe, and flag.
- Leave near-duplicates separate when in doubt. Over-merging is the dominant failure mode of dedupe judges.
</rules>

<process>
1. In <scratchpad>, pair up claims that appear to be the same assertion. Note any near-duplicates you are unsure about — leave them separate if in doubt.
2. Identify direct conflicts (same entity, opposing assertions).
3. Emit the unified JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: merged_claims[] (with claim, evidence[], sources[] in {"A","B"}, confidence), conflicts[] (with claim_a, claim_b, evidence), unknowns_union[]. No content after </final_json>.
</output_format>
```

The judge emits positional labels (`A`/`B`); the harness uses `order_map` (same mechanism as the picking judges) to translate `sources: ["A","B"]` into canonical provider ids before rendering the report. Gather has a single pass (no swap), so there's only one `order_map`. This keeps provider identity out of the judge prompt — preserving the anonymized-judging guarantee — while still letting the report attribute findings to `claude`/`codex` correctly.

### Judge prompt — `compare`

Position-swap mandatory. The harness calls this prompt twice with workers A and B swapped, then enforces agree-or-tie.

```
You are a pairwise judge. You will see two defended positions, A and B. Read each position's `position` field first.

If A and B defend the SAME position (semantically — same answer to the underlying question), emit `relation: "consensus"`, do NOT pick a winner, and instead identify (a) the strongest evidence each side brings and (b) any disagreements within the shared position.

If A and B defend DIFFERENT positions, emit `relation: "compare"` and pick a winner OR declare a tie. Be strict: prefer well-evidenced reasoning over verbose advocacy.

You do not know which model produced A or B. Use positional labels only.

<position_a>
{FINAL_JSON_A}
</position_a>

<position_b>
{FINAL_JSON_B}
</position_b>

<rubric>
Score each position on a 1–5 scale on each of:
1. Evidence quality — are claims grounded in verifiable citations?
2. Argument coherence — do claims actually support the thesis?
3. Tradeoff honesty — does the position acknowledge real costs?
4. Rebuttal strength — does it engage anticipated objections?

Length is NOT a virtue. A concise, well-evidenced position beats a verbose, weakly-evidenced one.
</rubric>

<rules>
- Determine `relation` first ("consensus" or "compare") based on the `position` fields.
- Explain reasoning BEFORE the verdict. Score each position on each rubric dimension before naming a winner.
- The harness will call you TWICE with positions swapped. Your verdict must be driven by the rubric, not by which position appears first. If the two positions are within rubric-noise of each other (max margin < 1 point on any dimension that swings the verdict), declare TIE.
- A verdict of "tie" is valid and expected when both positions defend their cases roughly equally well, or when both have similar critical flaws.
- In the `consensus` case, populate `consensus_strongest[]` with the best-evidenced claim from each side (one from A, one from B) and `consensus_disagreements[]` with any sub-claim disagreements within the shared position. Set `winner` to `null`.
- Do not penalize a position for being shorter if it covers the rubric.
- Do not invent evidence that neither position cited.
</rules>

<process>
1. In <scratchpad>, compare the `position` fields to decide `relation`.
2. Score A on each rubric dimension (1–5). Then score B. Then compare margins.
3. Emit the JSON verdict.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: relation in {"consensus","compare"}, scores_a {evidence, coherence, tradeoff_honesty, rebuttals}, scores_b {...}, winner in {"A","B","tie",null}, rationale (2–4 sentences citing rubric dimensions), kept_from_nonwinner[] (claims worth preserving — from the loser in `compare`, or one from each side in `consensus`), consensus_strongest[] (populated only when relation="consensus"), consensus_disagreements[] (populated only when relation="consensus"). No content after </final_json>.
</output_format>
```

**Swap resolution for `compare`** — the judge emits positional verdicts (`A`/`B`/`tie`) which are *local to that pass*, because position A in pass 1 is a different provider from position A in pass 2. The harness must map both passes back to canonical provider IDs before comparing:

1. Pass 1 records `order_map_pass1 = {"A": "claude", "B": "codex"}` (whatever order the work order lists).
2. Pass 2 records `order_map_pass2 = {"A": "codex",  "B": "claude"}` (swapped).
3. For each pass's verdict, look up the canonical winner: `canonical_winner_pass1 = order_map_pass1[verdict_pass1.winner]` (skipping `tie`).
4. Final decision: `pick_winner: <canonical-id>` iff both passes resolved to the **same canonical provider id**. Any disagreement, or either pass emitting `tie`, → final decision is `tie`.

If one worker had `schema_error`/non-ok and the other was `ok`, no swap is run — decision is `single_provider_only` and the surviving worker is rendered with a caveat.

Naive resolution (comparing `verdict_pass1.winner == verdict_pass2.winner` as raw strings) would turn real agreement into spurious ties whenever the judge picks a consistent provider — because the *positional label* of that provider flips between passes. The order-map step is load-bearing.

### Judge prompt — `analyze`

Position-swap mandatory. Tiebreak: more atomic claims wins; else position A.

```
You are a synthesis judge. You receive two analyses (A and B) of the same subject. Your job:
1. Pick one analysis as the SPINE (the better backbone of reasoning).
2. Walk through the spine step-by-step. For each spine step, find the closest matching step in the loser and emit an annotation: `agrees`, `disagrees` (with one-line reason), `adds` (with one-line addition), or `not_covered`.
3. Append loser steps that do not map to any spine step as `additions_from_loser[]`.

<analysis_a>
{FINAL_JSON_A}
</analysis_a>

<analysis_b>
{FINAL_JSON_B}
</analysis_b>

<rubric>
Score each analysis on a 1–5 scale on each of:
1. Step atomicity — can each step be independently checked?
2. Citation grounding — are steps evidenced?
3. Assumption transparency — are hidden premises surfaced?
4. Coherence — do the steps actually compose into the conclusion?

Length and verbosity do NOT favor a spine.
</rubric>

<rules>
- Explain reasoning BEFORE the verdict. Score both analyses on the rubric before picking the spine.
- The harness calls you twice with positions swapped. Your spine choice must be rubric-driven, not position-driven.
- For each spine step, the annotation must reflect the LOSER's actual content. If the loser does not address a step, use `not_covered`.
- Do not invent agreements or disagreements. If you cannot tell whether the loser agrees, use `not_covered` with a note.
- `adds` annotations MUST cite the loser's claim id. `disagrees` annotations MUST cite both sides.
</rules>

<process>
1. In <scratchpad>, score both analyses on the rubric. Pick the spine.
2. For each spine step, scan the loser for the closest semantic match. Decide: agrees, disagrees, adds, or not_covered.
3. List loser steps with no spine match in additions_from_loser.
4. Emit the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: scores_a, scores_b, spine_winner in {"A","B"}, spine_rationale (2–3 sentences), claim_verdicts[] (each with claim_id, loser_position in {agrees, disagrees, not_covered, adds}, loser_note), additions_from_loser[] (each with claim, evidence[]). No content after </final_json>.
</output_format>
```

**Swap resolution for `analyze`** — same order-map pattern as `compare`. Both passes emit a positional `spine_winner` (`A` or `B`); the harness maps each back to a canonical provider id, then compares.

- If both passes resolve to the **same canonical provider**, that provider is the spine. `spine_tiebreak: "swap_agreement"`.
- If the passes disagree (each picks a different canonical provider as spine), tiebreak by **atomic-claim count** (`len(worker.claims)`): the analysis with more atomic claims is the spine. `spine_tiebreak: "atomic_count"`.
- If atomic counts are equal, fall back to **worker A** (the first provider in the work order). `spine_tiebreak: "position_a"`.
- The chosen `spine_tiebreak` and `order_map_pass1` / `order_map_pass2` are recorded in `decision.json` so the audit trail explains the pick.

`claim_verdicts[]` and `additions_from_loser[]` from the *winning pass* (the pass whose canonical spine matches the final spine) are used to render the report.

## Phases (three, not seven)

### Phase 1: Skeleton + runner + work-order

- Create package, `cli.py`, `work_order.py`, `runner.py`.
- `bakeoff init {gather|compare|analyze}` writes three commented (JSONC) example work orders.
- `bakeoff doctor` checks:
  1. `claude`, `codex`, and `git` are on PATH; prints `--version` output.
  2. Auth probe per provider — a 1-token "hello" call confirms each CLI is authenticated. If `ANTHROPIC_API_KEY` / Codex auth is missing, fail here rather than 5 minutes into a real run.
  3. Resolved `DEFAULT_MODEL_IDS` are printed so the user sees what `bakeoff init` will write.
  4. CWD is writable (the run directory will be created here).
  5. Prints the same-family-judge bias acknowledgement: "Default judge is claude/opus alongside claude/sonnet workers. Position-swap is the primary bias mitigation; same-family bias is an accepted v1 risk."
- `bakeoff validate <wo.json>` (Phase 1): loads + validates the work order, resolves provider IDs, prints the budget/provider/judge block, exits 0 on valid / 2 on invalid. No provider invocation.
- `runner.py`: `async def run_provider(argv, prompt, budgets)` with process-group kill, wall-clock timeout, output-byte cap, full status enum.
- `work_order.py`: validation for all three types including heterogeneity check.
- Test with fake provider scripts (sleep, garbage output, non-zero exit, output-cap exceed, malformed JSON).

Exit criteria:
- runner returns each documented status correctly (including `schema_error` for missing/malformed `<final_json>` block)
- `<final_json>` extractor handles: trailing whitespace, content after `</final_json>` (last block wins), multiple `<final_json>` blocks (last wins), no `<final_json>` block (schema_error), malformed JSON inside the block (schema_error)
- SIGINT kills the fake provider's process group
- JSONC state-machine stripper handles: `//` inside URL strings (`"https://x.com"`), `/*` inside strings, escaped quotes (`\"`), backslash sequences (`\\`), commented templates round-trip
- work-order validation catches: missing fields, `schema_version != 1`, `id` matching `^TODO[-_]`, judge==worker pair, providers identical on backend+model+scope, unknown type, wrong provider count, illegal scope value, illegal effort value
- validator error messages name the offending field and quote the rule
- `bakeoff init`, `bakeoff doctor`, and `bakeoff validate` work standalone

### Phase 2: Three modes end-to-end with fake providers

- `providers.py`: implement worker prompt construction with `mode` and `scope` parameters; implement judge prompt construction per mode.
- `cli.py`: wire `bakeoff research`. Dispatch on `type`. For compare/analyze, run judge twice with position swap; for gather, run once.
- `report.py`: implement three renderers branching on `type`.
- Fake providers return canned JSON covering: both-agree, both-disagree, one-times-out, malformed-JSON, conflicting-claims, complementary-claims.

Exit criteria:
- `gather`: union renders correctly, sources tagged per claim, conflicts surfaced
- `compare`: position-swap test passes — when fakes return same content, agreement; when biased fake favors position-1, swap catches it and decision is `tie`
- `analyze`: spine pick selected, per-claim verdicts overlay correctly, additions from loser appended
- one-provider-fails case proceeds with single-provider report and exit 0 (or `single_provider_only` for compare)
- both-providers-fail case skips judge, exit 2

### Phase 3: Live dogfood (all three modes)

- Wire `bakeoff ls`, `bakeoff show`, `bakeoff rerun`.
- Run **at least 12 real bakeoffs** over a week, distributed: 5 gather, 4 compare, 3 analyze. Mix of scopes per mode (codebase, web, mixed).
- For each run, the human records:
  - did the bakeoff save time vs manually launching two agents?
  - did the mode's primary deliverable answer the question?
  - did the report surface something the human cared about that they'd have missed alone?

Dogfood pass/fail bar (per mode):

- **gather pass**: ≥4/5 runs surface findings the human would have missed solo
- **compare pass**: ≥3/4 runs, judge agrees with human pick *or* declares tie when human is genuinely torn
- **analyze pass**: ≥2/3 runs, the spine + annotations is preferred over a single-model explanation
- **Overall pass**: all three modes pass their bar AND ≥9/12 runs save time vs manual

If any mode fails its bar, that mode is killed (not patched). Surviving modes ship; failed modes leave a postmortem in `docs/`.

## Lessons encoded as requirements

- **Advisory budgets fail.** Timeouts + output caps live in `runner.py`, enforced outside the model. Provider-reported budgets are informational only.
- **Judges should not read long transcripts.** Judge sees `final.json` and `status.json` only. No transcript flag.
- **Position bias is real.** Whenever the judge picks (`compare`, `analyze`), it runs twice with order flipped. Single-pass judge is not a valid implementation for picking modes.
- **Self-preference bias is real.** Judge backend+model must differ from both workers; validator enforces.
- **Synthesis blends out the standout candidate.** No mode does LLM-blend prose merging. `gather` uses structured union; `analyze` uses annotation overlay.
- **Heterogeneity is required.** Validator rejects identical `backend + model + scope` provider pairs in every mode (rule is uniform — see Validation rules).
- **Spawning explosions kill MAS.** N=2, hard-capped. Three modes, hard-capped.

## Hard architectural caps

These are not goals; they're invariants. Violating any of them is a signal we're rebuilding swarm-do.

1. **N = 2 providers per run in v1.** No `--providers 3`. No work-order with 3+ entries. (Note: "forever" overstates the literature — the empirical claim is "no consistent benefit past N=3", not "N=2 is provably optimal". v1 picks N=2 for product simplicity; the cap is policy, not theorem. Revisit only via the explicit "Future" trigger.)
2. **Three modes. Forever.** Adding a fourth requires deleting one and a written postmortem on why it's necessary.
3. **Five source files. Compress before adding a sixth.**
4. **Stdlib only.** Adding a dependency requires deleting a feature.
5. **No LLM-blend prose synthesis in any mode, ever.** Selection is fine. Annotation is fine. Deterministic union is fine. Prose merging is not.
6. **No mode-specific module.** Mode logic lives as branches inside `providers.py` and `report.py`. If a mode wants its own file, that mode is too complex and should be cut.
7. **Judge ≠ workers, always.** Validator enforces. No `--allow-self-judge` flag.
8. **Position-swap is mandatory for picking modes.** No single-pass `compare` or `analyze` for "speed."

## Future (deferred, named, capped)

Each item below is explicitly deferred. None of them get prototyped in v1.

- **Claude Code launcher commands (`/bakeoff:gather`, `/bakeoff:compare`, `/bakeoff:analyze`).** The project directory and plugin metadata are scaffolded now, but slash commands stay deferred until the CLI verbs work. The launcher is a thin frontend where Claude helps the user *draft* a work order in conversation, shows it for approval, then invokes the CLI as a subprocess. Claude is a launcher, never an orchestrator — it doesn't decide mid-run. Ship the CLI standalone first; wire the launcher only after dogfood shows the JSON-writing friction matters.

  **Plugin seam (designed, not built):**
  - Pattern: match swarmdaddy. One Skill per verb. A `/bakeoff:prepare` step writes the work order to a temp path and shows it to the user for approval before any provider invocation.
  - Boundary: plugin invokes the CLI verbatim — no orchestration in the plugin layer. The CLI's `bakeoff validate <wo>` (already in v1) is what the plugin uses to typecheck the work order before running. This is the reason `validate` is in v1: it removes the temptation for a future plugin author to reimplement the validator in TypeScript.
  - Output: the plugin `cat`s `report.md` into the conversation. Claude Code renders markdown natively; no JSON output format needed in v1.
  - Cancel: SIGINT is sent by the plugin to the subprocess on user interruption.
  - Patterns to deliberately reject from swarmdaddy: BEADS issue tracker integration, phase pump, swarm worktrees.
- **`build` mode.** Worktrees + diff gate + validation. Out of scope until research is dogfooded and proven to save time.
- **LangGraph engine.** Only if dogfood reveals that resume-after-partial-failure or HITL approval would remove real friction. Otherwise never.
- **N>2 (a fourth provider, a "tie-breaker" model).** Only if compare/analyze tie-rates after position-swap exceed 30% in dogfood — and the fix is N=3 voting, not N=2 with a better judge.
- **Dual-judge mode (Opus + Codex GPT-5.5 each run with position-swap = 4 judge calls).** Each component has literature support — judge ensembling reduces single-judge bias (PandaLM/JudgeLM/Auto-J), and position-swap reduces position bias (Zheng et al., systematic position-bias study) — but the *combination* isn't independently benchmarked that we've found. Cost doubles on the judge side (2 calls → 4). Decision rule would be "winner only if all 4 passes agree, else tie." Trigger to ship: if dogfood shows the single-judge same-family bias is real (e.g., Claude/opus consistently picks the Claude worker even after swap, in a way the human disagrees with). Don't ship preemptively.
- **Cost tracking in dollars.** Only if dogfood reveals users hit budget anxiety. The hard stops (wall clock + output bytes) are already enforced.
- **A fourth mode.** Only if a real recurring use case fits none of gather/compare/analyze and we're willing to delete one of the three.

Anything not on this list is out of scope, full stop. Adding to this list requires a written rationale.

## Open decisions

1. **Run-id format.** Recommendation: `YYYY-MM-DD-<4-char-hash>` where the hash is random (not content-derived) to avoid collisions on `rerun` (which copies the work order verbatim — content-hash would always match the source). Users override with `--run-id`.
2. **Output-cap semantics.** When `max_output_bytes` is exceeded, the runner kills the provider, marks `status: output_cap`, and writes the truncated output to `stdout.txt` with a trailing `[TRUNCATED at N bytes]` marker. Judge does not see a partial `final.json` from an output_cap provider — `schema_error` path applies (judge gets only the other worker).

Decisions made in the 2026-05-14 revision (not open):
- Project home is the `bakeoff/` subdirectory in `mstefanko/claude-plugins`, beside `swarm-do/` and `tech-radar/`.
- JSONC for work orders (strip comments on load; no new dependency).
- `bakeoff validate` in v1; removes plugin-reimplementation risk.
- No env-var model overrides; no `BAKEOFF_MODEL_*`.
- `effort` is optional in the schema (low/medium/high, default high) — both Anthropic and OpenAI expose this knob, so keeping it is portable.
- No `bakeoff cancel` verb; SIGINT only.
- `analyze` position-swap tiebreak: more atomic claims, else worker A.
- Worker schema validation is fail-fast; no re-prompt.
- Retention is manual; no `bakeoff prune` in v1.

That's it.

## Success criteria

`bakeoff research` succeeds if, after a week of dogfood:

- the user prefers it to manual fanout on most bounded research tasks across all three modes
- the codebase fits in five files of stdlib Python and stays there
- every run is a self-contained directory the user can grep, diff, and replay
- the report is useful without opening any `stdout.txt`
- nothing in this document needed to be expanded mid-build
- at least two of the three modes pass their dogfood bar

It fails if:

- users start asking for a config file, plugin system, "just one more provider," or "just one more mode"
- module count grows past 5 without a concrete dogfood-driven reason
- any mode's judge gains a `synthesize` decision or LLM-blend prose output
- LangGraph, Beads, a DAG composer, or a TUI appears anywhere
- the `Future` section gains entries faster than dogfood evidence justifies

## Bottom line

`bakeoff research` is a dispatcher with three modes that share one pipeline. It launches two heterogeneous workers on the same bounded question, runs an artifact-only judge tuned to the mode, and writes a markdown report. Five files. Three phases. One schema. Two providers per run. Three modes total, forever. Zero new dependencies.

If a future feature makes the code harder to audit than the manual workflow, reject it until dogfood proves it saves time or improves quality.
