# Implementation Plan — Code-Review Plugin + Bakeoff Prompt Backfill

**Status:** DRAFT, reviewed and corrected. Nothing here is built yet.
**Date:** 2026-06-02
**Author:** synthesized from the research + prompt artifacts in this directory.

> **For the reviewing agent:** This plan exists so you can sanity-check the *direction* before any
> code is written. Section 1 links every source. Section 2 records the decisions and their rationale
> (challenge these). Section 3 is the architecture. Sections 4–7 are the phased steps. Section 8 records
> the resolved review questions and current recommendations. If a decision looks wrong, flag it against
> its ID (D1–D8).

---

## 1. Source material (read these first)

**Research reports (the "why"):**
- [`00-synthesis.md`](./00-synthesis.md) — the one-doc synthesis of all five reports
- [`01-llm-nondeterminism.md`](./01-llm-nondeterminism.md) — why runs differ; run-N-times for high stakes
- [`02-intent-in-code-review.md`](./02-intent-in-code-review.md) — isolate intent (diff-blind defect pass + separate conformance pass)
- [`03-context-amount.md`](./03-context-amount.md) — curated, not maximal, not minimal context
- [`04-prompts-and-swarms.md`](./04-prompts-and-swarms.md) — prompt anatomy, swarms, cross-model; original draft prompts
- [`05-chunking-vs-large-diff.md`](./05-chunking-vs-large-diff.md) — chunk by cohesive slice + integration pass

**Web scan (newer, partly contradictory findings folded into the prompts):**
- [`06-web-prompt-scan.md`](./06-web-prompt-scan.md) — Refute-or-Promote kill-mandate critic, consensus≠correctness, cross-family critics, optional fixes, no long debate loops

**The deliverable prompts (the "what"):**
- [`prompts/01-single-agent-routine.md`](./prompts/01-single-agent-routine.md) — single-pass routine reviewer
- [`prompts/02-swarm-multi-lens.md`](./prompts/02-swarm-multi-lens.md) — multi-lens swarm + refutation critic + judge
- [`prompts/03-bakeoff-gap-analysis.md`](./prompts/03-bakeoff-gap-analysis.md) — bakeoff vs. the prompts; plugin recommendation

**Adjacent plugin references (patterns to borrow / avoid):**
- [`ai-foundry-core/ril-agents/plugins/agent-teams`](https://github.com/AI-Foundry-Core/ril-agents/tree/main/plugins/agent-teams) — generic Agent Teams orchestration; useful structure, not a replacement
- [Claude Agent Teams docs](https://code.claude.com/docs/en/agent-teams) — confirms Agent Teams is experimental and requires explicit enablement
- [`anthropics/claude-code/plugins/code-review`](https://github.com/anthropics/claude-code/tree/main/plugins/code-review) — high-signal review, candidate validation, false-positive filtering
- [`openai/codex-plugin-cc`](https://github.com/openai/codex-plugin-cc) — read-only Codex handoff and adversarial review command patterns
- [`hamelsmu/claude-review-loop`](https://github.com/hamelsmu/claude-review-loop) — durable review artifact/report ideas; automatic stop-hook loop is too heavy for default use
- [`wshobson/agents/plugins/comprehensive-review`](https://github.com/wshobson/agents/tree/main/plugins/comprehensive-review) — long-form audit machinery; useful contrast for what `review-kit` should not become

---

## 2. Decisions & rationale (challenge these — IDs D1–D8)

| ID | Decision | Rationale | Confidence |
|----|----------|-----------|-----------|
| **D1** | Build a NEW plugin as a thin **context-assembly + routing + intent-fencing** layer; **delegate ledgered multi-agent execution to bakeoff**. Do not fork bakeoff's executor. | Bakeoff already runs provider CLIs, persists replayable artifacts, and judges two-provider runs. The user's goal ("Claude builds the prompt with just-enough context, no rot") is the assembly/routing layer — the one piece nothing owns today. Extending bakeoff to own repo-specific context curation, enovis lookups, single-vs-swarm routing, and confidence filtering would bloat the tool beyond its tight/light mission. See [`prompts/03`](./prompts/03-bakeoff-gap-analysis.md). | High |
| **D2** | Backfill bakeoff with the review-contract improvements it can own cleanly: severity support, stronger worker/judge calibration, safer intent handling, and report/triage compatibility. Treat the refutation critic as a follow-on orchestration feature unless bakeoff grows an explicit stage hook. | The delegated run should not confuse severity with confidence or promote consensus into correctness. **Correction:** this is not "prompt/fixture-only"; severity touches validators/reporting, and a true critic between workers and judge needs orchestration support. | High |
| **D3** | Reuse bakeoff's **CLI-level generated review context** where helpful, but do NOT assume `internal/reviewcontext`/`internal/repocontext` solve curated dependency/context assembly. | Verified: `reviewcontext` captures metadata, diffstat, changed files, and optional patch. `repocontext` provides repo-layout/path validation helpers. Neither gathers immediate deps, conventions, or enovis domain facts. The new plugin should call bakeoff as a CLI and keep richer curation in the skill layer. | High |
| **D4** | New plugin is **skill-based (markdown + commands)**, mirroring `obsidian-notes`/`tech-radar`, NOT a second Go binary. It orchestrates: git → enovis-context → curated context → route → direct prompt or bakeoff handoff. | The "Claude assembles context and builds the prompt" goal is orchestration, best expressed as a skill the model drives. Heavy execution stays in bakeoff. Add a small bakeoff CLI helper later only if the skill needs a reusable exporter. | High |
| **D5** | Context recipe = **changed files + immediate deps + only-relevant conventions**, using the `enovis-context` CLI to pull touched models' fields, routes, association paths, graph neighbors, form fields, and feature flags instead of dumping CLAUDE.md. | Report 03 (context rot); enovis-context is already installed and high-signal/low-token for this repo. **Correction:** the command is `get-feature-flags`, not `feature-flags`. | High |
| **D6** | **Router by diff size/risk/user request:** small routine → single-agent prompt; small-but-high-stakes or explicitly "extra eyes" → focused swarm; large/cross-layer/high-risk → full or chunked swarm + integration. | Research supports the size/risk split (reports 01, 04, 05). Priority/visibility/user override is a product requirement, not a research finding: a small diff can still deserve extra review surface when the cost of a miss is high. | High |
| **D7** | **Cross-family for the refutation critic specifically** (e.g. Codex/GPT as critic of Claude lenses), not a blanket "more model families is better" rule. | Web scan §C2: same-family reviewers share correlated errors. Report 04 cautions that mixed-model aggregation can lower quality unless the model has a lens-aligned strength. Use cross-family deliberately for the cold-start critic. | High |
| **D8** | Make **run-N aggregation** and the **confidence-drop gate** first-class review-plan controls for high-stakes paths. | Report 01 says multiple fresh runs are the main nondeterminism mitigation. Web scan §B2/§C2 says confidence thresholding/refutation is the strongest noise-control lever. These are more evidence-backed than most config knobs. | High |

**Product naming note (not a research outcome):** keep `review-kit` as the working name (skill `review`, command `/review-kit:review`). It is clear, tool-like, and avoids colliding with existing marketplace plugins named `code-review`.

**Five alternatives worth considering:**
- `review-router` — emphasizes the plugin's real job: route by risk/size and choose direct prompt vs. bakeoff.
- `review-lens` — short, memorable, and aligned with single-lens vs. multi-lens review.
- `diff-lens` — signals changed-code focus and avoids sounding like a generic PR bot.
- `review-context` — very literal; good if context assembly remains the main differentiator.
- `pr-review` — obvious and user-facing, but a bit more generic than `review-kit`.

**Adjacent plugin scan:** no local `team_review`/`team-review` plugin was found. The closest local equivalents are local/official `code-review`, `pr-review-toolkit`, `swarm-do` review flows, Codex review skills, and bakeoff. External scan found meaningful overlap in `agent-teams`, Anthropic's official `code-review`, OpenAI's `codex-plugin-cc`, `claude-review-loop`, and `comprehensive-review`, but no replacement-level match. They provide useful patterns, but none owns the full intended scope: curated context assembly, intent fencing, small-vs-ledgered routing, optional bakeoff handoff, and a synthesized final report.

---

## 3. Architecture overview

```
/review-kit:review <base-ref>            (new plugin — skill-driven orchestration)
        │
        ├─ 1. Gather raw context
        │     git diff --stat / numbered diff; changed-file contents
        │     enovis-context CLI: get-model-fields / get-routes / get-feature-flags
        │     optional bakeoff CLI context: review-context metadata / diffstat / changed files / patch
        │
        ├─ 2. Curate  → drop to changed files + immediate deps + ONLY relevant conventions
        │     fence intent: PR description/ticket separated into an <intent> block
        │
        ├─ 3. Route by size/risk/user request
        │        small/medium ──► single-agent prompt (prompts/01)  ──► one strong model
        │        high-stakes small ─► focused swarm (correctness + tests + relevant lens + judge)
        │        large/high-risk ─► full swarm (prompts/02)
        │        large multi-slice ─► chunk by cohesive slice ─► swarm via BAKEOFF (delegated)
        │
        ├─ 4. Write a review plan artifact
        │     requested mode, risk signals, selected route, chunks, lenses, exclusions,
        │     repeat policy, confidence gate, context manifest, report contract,
        │     and optional bakeoff work-order mappings
        │
        └─ 5. Execute
                 single-agent: run the filled prompt directly in-session
                 swarm/ledgered: hand a curated work order to bakeoff →
                        reviewers (Claude + Codex today) → judge/triage
                 high-stakes follow-on: repeat risky lenses with fresh context,
                        then run a cold-start cross-family witness/critic
                 chunked: run cohesive chunks, then cross-chunk integration pass
                 final: apply confidence-drop gate, then synthesize the report
```

Bakeoff files this touches (all under `~/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/`):
- `internal/workorder/templates/review.work-order.json` — facet include/exclude
- `internal/prompt/prompt.go` + `internal/prompt/fixtures/worker-gather-{claude,codex,generic-terminal-agent}.txt` — generated reviewer prompt contract and fixtures
- `internal/prompt/fixtures/judge-gather.txt` — judge/dedup contract
- `internal/workorder/workorder.go` — worker/judge result validators if `severity` becomes schema-level
- `internal/report/`, `internal/triage/` — display and downstream compatibility for severity / confidence
- `internal/commands/researchcmd/` or `internal/commands/escalatecmd/` — only if a real critic stage is added rather than handled by the new plugin as a follow-on run
- `internal/reviewcontext/`, `internal/repocontext/` — reuse as CLI-level helpers only; do not treat them as dependency/context-curation engines

---

## 4. Phase 0 — Verification findings (completed)

These findings replace the earlier `UNVERIFIED` assumptions.

1. **Bakeoff context modules are narrower than D3 assumed.**
   - `internal/reviewcontext/reviewcontext.go` produces metadata, diffstat, changed-file name/status, and optional unified patch, then writes `review-context.md/json` when `bakeoff research` is run with review-context flags.
   - `internal/repocontext/repocontext.go` provides a compact repo-layout block and prose-path validation/suggestions. It does not assemble immediate dependencies or conventions.
   - Recommendation: call bakeoff's CLI for generated review context when useful, but keep curated dependency/context assembly in `review-kit`.
2. **Bakeoff prompt source-of-truth is not just fixture text.**
   - The embedded fixtures are stable prompt templates/snapshots, but `internal/prompt/prompt.go` builds the actual worker and judge prompts.
   - Recommendation: update prompt generator contracts, validators, reports, and fixtures together; do not edit fixture text only.
3. **Bakeoff headless handoff is clean for normal review runs.**
   - Confirmed command shape: `bakeoff research WORK_ORDER --base <ref> --diff --changed-files`.
   - The CLI writes `source-work-order.json`, `work-order.json`, `review-context.md`, and `review-context.json` into the run directory.
   - There is no separate "work-order injection" flag beyond passing the work-order path.
4. **A true refutation critic is not a low-risk fixture-only edit.**
   - Current gather mode runs two providers, then one union judge. `bakeoff escalate --mode witness` is adjacent and already adversarial for code-review runs, but it is post-run advisory rather than an in-between critic stage.
   - Recommendation: Phase 1 should harden bakeoff's review schema/prompt contract first. `review-kit` can run an advisory cold-start critic as a follow-on, or bakeoff can later grow an explicit critic stage.
5. **enovis-context commands are confirmed with one correction.**
   - Real commands include `get-model-fields`, `get-routes`, `get-feature-flags`, `find-association-path`, `graph-neighbors`, `get-form-fields`, and related query helpers.
   - Correction: use `get-feature-flags`, not `feature-flags`.
6. **Similar plugin overlap is meaningful but not disqualifying.**
   - `code-review` provides parallel review agents and confidence filtering, but is PR/GitHub oriented and does not own local context routing or bakeoff handoff. It should not be the default replacement for `review-kit`.
   - `pr-review-toolkit` has useful specialist-agent and taxonomy ideas, but its aggregate output is broader than this plugin should default to.
   - `swarm-do` has durable review orchestration and strong output-only scope guards, but it is heavier than a thin context/router plugin.
   - Bakeoff remains the right ledgered execution primitive; `review-kit` remains the right coordinator.
7. **Output shape should be a synthesized report, not raw findings.**
   - The `team_review` screenshot is strongest because it reads like a review captain's merge-readiness synthesis: scope paragraph, severity buckets, verified-clean checks, and out-of-scope follow-up.
   - Recommendation: make this a UX/product contract for the plugin, not a research-backed claim.
8. **External plugin overlap is medium, not replacement-level.**
   - `agent-teams` is a generic experimental Agent Teams wrapper with commands, agents, and orchestration skills. Copy its lightweight plugin layout, dimension isolation, dedupe, and severity calibration ideas. Do not make Agent Teams a hard dependency; it requires explicit experimental enablement and is broader than this plugin's purpose.
   - Anthropic's official `code-review` plugin has the best noise-control pattern: preflight gating, candidate validation, high-signal-only reporting, and explicit false-positive filtering. Copy these rules into `review-kit`'s report gate.
   - OpenAI's `codex-plugin-cc` has the cleanest optional handoff pattern: read-only review/adversarial-review commands, preserved user args, foreground/background choice by scope, and compact gate contracts. This is closer to `review-kit`'s bakeoff/Codex handoff than Agent Teams.
   - `claude-review-loop` has useful durable artifact ideas (`reviews/review-<id>.md`, state file, consolidated report), but its automatic Stop hook loop and permissive default Codex flags are too heavy/risky for `review-kit`.
   - `comprehensive-review` is intentionally a long-form audit phase machine. It is useful as a contrast: `review-kit` should stay a focused router/report synthesizer, not grow `.full-review/` checkpoints by default.
   - These are plugin-scan findings. They inform taste/scope, but the implementation contract should only carry the high-leverage pieces in §6.8.

---

## 5. Phase 1 — Minimal bakeoff hardening (D2)

This phase keeps bakeoff tight/light: improve the generic review contract and ledgered output shape without making bakeoff a repo-specific context curator.

1. **Add a `severity` axis** (`blocker|high|medium|low`) to code-review gather claims, distinct from existing `confidence`.
   - Update worker prompt schema, judge schema, and validation in `internal/workorder/workorder.go`.
   - Update `internal/report/` rendering so report bullets show severity and confidence separately.
   - Confirm automatic triage still maps source findings correctly; triage already has severity downstream, but source review claims do not.
2. **Strengthen intent handling without pretending bakeoff can fully isolate intent.**
   - Worker prompts should treat acceptance criteria / PR descriptions as untrusted claims.
   - The stronger two-pass split belongs in `review-kit`, because `review-kit` can construct separate defect and conformance prompts before handoff.
3. **Update worker calibration.**
   - Keep citation-or-drop.
   - Add cross-function confidence cap.
   - Make suggested fixes optional.
   - Require concrete scenarios for high/blocker severity.
4. **Update judge calibration.**
   - Do not raise severity because both providers agree.
   - Corroboration may raise confidence/attention, not impact.
   - Drop or demote vague claims lacking a concrete scenario.
5. **Handle refutation as a separate design item, not a hidden fixture edit.**
   - Short term: `review-kit` can run `bakeoff escalate --mode witness` or a direct cold-start critic after a normal run.
   - Longer term: add a first-class bakeoff critic stage only if we want it as a reusable, ledgered primitive.

**Validation:** run targeted Go tests for `internal/prompt`, `internal/workorder`, `internal/report`, and `internal/triage`; then run a small code-review bakeoff and confirm severity appears, agreement does not inflate severity, and triage/report rendering remains stable.

---

## 6. Phase 2 — Scaffold the new `review-kit` plugin (D1, D4)

Mirror the `obsidian-notes` / `tech-radar` plugin shape inside the **same marketplace**
(`~/.claude/plugins/marketplaces/mstefanko-plugins/`).

1. **Create plugin dir** `review-kit/` with:
   - `.claude-plugin/plugin.json` (mirror bakeoff's manifest fields: name, description, author, keywords)
   - optional `.codex-plugin/plugin.json` only if we want Codex-side plugin availability too
   - `skills/review/SKILL.md` — the orchestration skill (the heart of the plugin)
   - `commands/review.md` — `/review-kit:review` entry point
   - `docs/` — copy/symlink-reference these research + prompt files for provenance
2. **Register** the plugin in `.claude-plugin/marketplace.json` (append a 5th entry, category
   `orchestration`).
3. **`SKILL.md` defines the orchestration steps** (D5/D6): gather → curate → fence intent → route →
   execute → synthesize report. Embed (or reference) the two prompts from `prompts/01` and `prompts/02`.
   Keep the conventions slice LEAN (D5) — explicitly instruct against dumping all of CLAUDE.md.
4. **Context recipe helper:** the skill calls the `enovis-context` CLI for touched models/routes/flags,
   uses git for changed files and immediate deps, and optionally invokes bakeoff's generated review context
   for metadata/diffstat/patch capture.
5. **Command surface: keep v1 to one real command.**
   - Ship `/review-kit:review` as the only primary command.
   - Do not require users to pick `/review-kit:single` vs. `/review-kit:swarm`; the command should auto-route and record why.
   - Support explicit mode overrides through args or natural language: `--mode auto|single|focused-swarm|swarm|chunked-swarm`, "run a swarm review", "extra eyes", "priority fix", etc.
   - Honor explicit user overrides. If the user asks for a swarm on a light PR, run a swarm or focused swarm and record `user_requested_extra_eyes` as the route reason.
   - Do not add separate commands initially. If discoverability becomes a problem, add thin aliases later (`/review-kit:swarm` → `/review-kit:review --mode swarm`) with no separate logic.
6. **Use a `review-plan` artifact, not a second bakeoff work-order system.**
   - Before execution, write or construct a small `review-plan.json` plus a human-readable `review-brief.md`.
   - The review plan owns context curation and routing; bakeoff work orders own ledgered provider execution.
   - For single-agent runs, the review plan feeds the direct prompt.
   - For ledgered swarm runs, the review plan compiles to one or more bakeoff work orders, one per chunk/facet where needed.
   - Keep the schema intentionally small:
     `version`, `base_ref`, `head_ref`, `command_args`, `requested_mode`, `route_decision`,
     `route_reasons`, `risk_signals`, `changed_files`, `context_manifest`, `intent_block`,
     `chunks`, `lenses`, `repeat_policy`, `confidence_gate`, `runner`, `bakeoff_work_orders`,
     `exclusions`, `report_contract`.
   - Store run artifacts outside normal tracked project files by default (for example `tmp/review-kit/<run-id>/` or a configured artifact dir).
7. **Configuration: optional, small, and repo-scoped.**
   - No config should be required for the command to work.
   - If present, read `.review-kit.yml` or `review-kit.yml` from the repo root.
   - Supported v1 config should be limited to `artifact_dir`, `single_loc_threshold`, and
     `chunk_loc_threshold`.
   - Defer `default_mode`, `default_runner`, `swarm_file_threshold`, `high_risk_paths`,
     `high_risk_keywords`, `enabled_context_adapters`, `default_lenses`, and posting controls until
     real usage proves they are needed.
   - Do not add per-provider orchestration complexity here; bakeoff remains responsible for provider details.
8. **Adopt only the proven/high-leverage external patterns.**
   - Confidence filtering is mandatory: high-signal, file:line anchored, false-positive-aware, and
     drop low-confidence non-blockers before the final report.
   - Bakeoff facet discipline applies only when compiling review plans into ledgered bakeoff work
     orders: short `facet.focus`, explicit `facet.include`, explicit `facet.exclude`.
   - Keep review commands read-only/output-only by default: do not create branches, PRs, GitHub posts,
     handoffs, or implementation plans from `/review-kit:review`.
   - Treat `agent-teams`, `codex-plugin-cc`, `claude-review-loop`, and `comprehensive-review` as
     provenance/inspiration, not an implementation checklist.

**Validation:** `/review-kit:review` on a small real branch produces a curated context bundle + a filled
single-agent prompt, without pasting the whole repo or all of CLAUDE.md.

### Final report contract (UX/product contract, not a research outcome)

`review-kit` must synthesize a final report. It should not show the user every provider/lens finding or a transcript of reviewer reasoning.

Default report sections:

```md
## Review Kit — <pass type>

<One concise paragraph stating scope, sources cross-referenced, exclusions, and overall confidence.
Mention code-side/UI-side/security-side/perf-side as applicable. Mention tests/coverage only when relevant.>

### Must fix

- **<short issue title>** — `<file or function>` <specific evidence>.
  <impact/consequence.> Fix: <concrete expected change.>

### Should fix

- **<short issue title>** — `<file or function>` <specific evidence>.
  <why it matters.> Fix: <recommended change or direction.>

### Clarify / verify

- **<short question/risk>** — `<file/view/behavior>` <what is uncertain>.
  <manual check, owner question, or product decision needed.>

### Verified clean

<Compact paragraph or short bullets listing important scary things checked and dismissed:
auth, permissions, SQL safety, XSS, N+1, broadcast scope, test coverage, etc.>

### Follow-up (owned separately)

<Real work discovered during review but outside this pass or not merge-blocking.>

---

Generated by `/review-kit:review`. Severity reflects the highest surviving non-refuted concern.
Resolved, duplicate, or explicitly dismissed low-confidence items omitted: <brief note, optional>.
```

Section rules:
- **Must fix:** only merge blockers with reproducible evidence or very high-confidence risk.
- **Should fix:** meaningful quality, UX, performance, or maintainability defects worth addressing before merge when practical.
- **Clarify / verify:** uncertainty that needs manual repro, product confirmation, or owner intent; never softer opinion.
- **Verified clean:** short confidence-building checks, only for concerns someone would reasonably ask about.
- **Follow-up:** prevents scope creep while preserving important discovered work.

Noise rules:
- No flat list of observations.
- No mixing verified bugs with speculative concerns.
- No repeating inline comments without synthesis.
- No long code quotes.
- No cosmetic commentary in the same report as merge-blocking code risk.
- Low-confidence non-blockers are omitted or moved to `Clarify / verify`; high-impact uncertain risks can stay with explicit uncertainty.

---

## 7. Phase 3 — Routing + delegation + chunking (D6, D1)

1. **Size/risk/user-request router** in the skill. Make thresholds documented knobs, but start with
   these defaults:
   - **Single-agent:** cohesive diff, roughly ≤ 200 changed LOC, one subsystem, no sensitive domain,
     and no user request for extra coverage.
   - **Focused swarm:** small/medium diff where a miss is expensive, or the user asks for "swarm",
     "extra eyes", "priority fix", "high visibility", "needs to be right", "pre-merge confidence",
     or similar. Run correctness + tests + the most relevant specialist lens, then judge/synthesize.
   - **Full swarm:** multi-file or cross-layer change, security/authz/tenant/PHI/money/data-loss risk,
     schema/API/permission contract changes, background/asynchronous/evented flows, complex SQL/search,
     migrations, external integrations, or meaningful new behavior with weak/no tests.
   - **Chunked swarm:** > ~400 changed LOC, or more than one cohesive feature/subsystem slice. Chunk by
     feature/subsystem with coupled cross-layer context and finish with a cross-chunk integration pass.
   - **Forced mode:** an explicit user mode always wins unless the request is impossible or unsafe. A
     small PR can still get a swarm review when the user wants more surface area.
   - **File counts are secondary heuristics, not thresholds.** They can signal fragmentation or
     cross-layer coupling, but the research-backed numeric anchor is the 200–400 LOC focused-review band.
2. **Route reasons are required.** Every review plan must record `route_decision` and `route_reasons`
   so the user can challenge the choice. Examples: `changed_loc_over_threshold`, `cross_layer_contract`,
   `authz_or_tenant_scope`, `weak_tests_for_new_behavior`, `user_requested_extra_eyes`,
   `priority_or_high_visibility_fix`.
3. **Swarm delegation:** for the swarm path, the skill builds curated work orders and invokes the
   Phase-1-upgraded bakeoff for ledgered reviewer + judge runs. If a cold-start critic is needed before
   bakeoff has a first-class critic stage, run it as a follow-on witness/direct prompt and feed the result
   into the integration summary.
4. **Chunking + cross-chunk integration** (report 05 / `prompts/02` §A, §D): split large diffs by cohesive
   feature slice carrying coupled cross-layer context; finish with the integration pass. Never a blind
   layer-only split.
5. **High-stakes repeat policy** (D8 / report 01): re-run risky lenses with fresh context (not a
   same-session debate loop — web scan §contradiction 3). Default to 2 runs for focused/high-stakes
   review and 2–3 runs for the riskiest correctness/security/data-loss lenses. Aggregate explicitly:
   - `union_for_coverage`: keep every non-refuted finding, then judge/dedup/confidence-gate.
   - `k_of_n_for_precision`: require repeated emergence for lower-impact findings, while preserving
     one-off high-impact findings in `Clarify / verify`.
6. **Mandatory confidence-drop gate** (D8 / web scan §B2): before the final report, drop low-confidence
   non-blockers; cap confidence for cross-function/cross-file reasoning unless the exact path is traced;
   preserve low-confidence high-impact security/data/PHI/money risks only with explicit uncertainty in
   `Clarify / verify`.

**Validation:** dogfood on one large historical PR; confirm chunking is by feature slice and the
integration pass catches a cross-chunk contract issue (seed one if needed).

---

## 8. Resolved reviewer questions

1. **D1 vs. extend-only:** build the new plugin. Extend-only leaves the core ask manual: context assembly, intent fencing, routing, and chunking. Bakeoff should remain a reusable execution/ledger tool.
2. **D3/D4, Go vs. skill split:** keep the new logic in a skill/command plugin. Call bakeoff as a CLI. Do not depend on bakeoff internal Go packages from `review-kit`.
3. **Plugin name:** keep `review-kit` as the working name. Revisit the five alternatives in §2 before scaffolding if the name still feels bland.
4. **Marketplace placement:** put `review-kit` in the same `mstefanko-plugins` marketplace as bakeoff. `enovis-context` should be an optional repo-specific adapter, not the marketplace identity for this plugin.
5. **Single-agent execution:** run the small/routine single-agent prompt directly in-session and save the curated context/prompt artifact. Use bakeoff when the user wants a ledgered multi-provider run or the router selects swarm/high-risk.
6. **Confidence-drop gate:** `review-kit` should own a mandatory post-processing gate. Drop low-confidence non-blockers by default; preserve low-confidence high-impact security/data/PHI/money findings with explicit uncertainty notes. This is a core D8 control, not a config preference.
7. **Use an existing plugin instead?:** no. Reuse patterns from `code-review`, `pr-review-toolkit`, `swarm-do`, and bakeoff, but keep `review-kit` because no existing plugin combines curated context routing, intent fencing, bakeoff delegation, and the synthesized report contract.
8. **Use `agent-teams` instead?:** no. `agent-teams` is valuable prior art for structure, specialist lenses, and dedupe, but it is a generic experimental Agent Teams wrapper. `review-kit` should not require `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; add an adapter later only if Agent Teams becomes stable and clearly improves the swarm path.
9. **Adopt `claude-review-loop` or `comprehensive-review` instead?:** no for the default workflow. Borrow durable report artifacts from `claude-review-loop`, but avoid automatic Stop hooks and review/implementation loops. Treat `comprehensive-review` as an audit-mode reference, not the normal review command shape.
10. **One command or many?:** one primary command for v1: `/review-kit:review`. Mode is an argument/intent, not a separate command family. This keeps the plugin barebones while still letting users force a swarm when they want extra eyes.
11. **Work order or something else?:** use a lighter `review-plan`, not a full bakeoff-style work-order clone. The review plan records context, route, chunks, lenses, exclusions, and report contract. It compiles to bakeoff work orders only when using the ledgered swarm path.
12. **Configuration?:** yes, but optional and very small. V1 config should only set `artifact_dir`, `single_loc_threshold`, and `chunk_loc_threshold`. Defer default runners, path/keyword risk maps, context-adapter lists, default lenses, and posting controls until real usage proves they are needed.
13. **Are swarm cases clear enough?:** yes after making D6 concrete, with one correction: changed file counts are illustrative signals, not research-backed thresholds. Auto-swarm is based on changed LOC, cross-layer coupling, sensitive domains, weak tests around new behavior, and explicit user priority/extra-eyes language. Complexity is not the only trigger.
14. **Run-N aggregation?:** make it first-class for high-stakes paths. For coverage, union fresh-run findings and then refute/dedup/gate. For precision, require repeated emergence for lower-impact findings while preserving one-off high-impact risks as `Clarify / verify`.

## 9. Acceptance criteria (definition of done)

- [x] Phase 0 findings recorded; D3/D4/D5 confirmed or corrected.
- [ ] Bakeoff gather review emits `severity` (distinct from confidence), treats intent/acceptance criteria
      as untrusted claims, and the judge no longer promotes on consensus.
- [ ] Existing bakeoff Go tests still pass.
- [ ] `review-kit` plugin registered and `/review-kit:review` runs end-to-end on a small branch with
      curated (not maximal) context and a synthesized report in the §6 format.
- [ ] `/review-kit:review` produces a `review-plan` artifact with mode request, route decision,
      route reasons, context manifest, repeat policy, confidence gate, chunks/lenses when applicable,
      and report contract.
- [ ] Auto-routing chooses single, focused swarm, full swarm, or chunked swarm from the documented D6
      criteria, and explicit user swarm/extra-eyes requests override the default route.
- [ ] Optional repo config is limited to `artifact_dir`, `single_loc_threshold`, and
      `chunk_loc_threshold`; the command works without config.
- [ ] High-stakes paths can run fresh-context repeat reviews and aggregate via
      `union_for_coverage` or `k_of_n_for_precision`.
- [ ] External plugin patterns are captured only where they serve the core contract: high-signal
      confidence-gated validation and read-only/output-only review; Agent Teams remains optional, not required.
- [ ] Large-PR path chunks by cohesive slice and runs a cross-chunk integration pass; bakeoff handles
      ledgered provider/judge runs where appropriate.
- [ ] High-risk path can run a cross-family cold-start critic either as a `review-kit` follow-on step or
      through a first-class bakeoff critic stage if that is added.
- [ ] A short README in the plugin links back to this plan and the prompt files.
