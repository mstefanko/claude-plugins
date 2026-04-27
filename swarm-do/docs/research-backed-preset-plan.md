# Research-Backed Preset And Pipeline Plan

Date: 2026-04-27

This plan reconciles the local audit notes in `/tmp/swarmdaddy-preset-audit.md`
and `/tmp/swarmdaddy-multi-agent-sources.md` with an independent outside
review and a fresh inspection of the current SwarmDaddy preset catalog.

## Executive Decision

Make the product default a single-writer implementation flow with bounded,
clean-context review and complexity-scaled provider evidence. Keep broad
fan-out for research, planning, and review only when branches have genuinely
different prompts, sources, tools, or model families.

The practical target is:

```text
research -> analysis + clarify -> writer -> spec-review + provider-review
  -> clean-context codex/other-family review -> writer revision if needed
  -> final evidence synthesis + docs
```

Do not treat any LLM judge as an objective correctness oracle. Reviews should
produce evidence and findings; executable tests, static checks, source
citations, stable provider agreement, or human review decide correctness.

## Reviewer Notes (2026-04-27)

These notes capture a senior-developer pre-flight validation pass against
the actual code. They refine the plan in place; sections below have been
updated where necessary.

**Validated against the codebase:**

- The Claude-only invariant has THREE legs in `py/swarm_do/pipeline/validation.py:invariant_errors`,
  not two: (a) `orchestrator`, (b) `agent-code-synthesizer`, (c) every
  `merge.strategy=synthesize` merge `agent`. Item (c) is the load-bearing
  blocker for cross-model judging in `competitive`, `ultra-plan`, `design`,
  `research`, `review`, and `brainstorm`. P3 already targets the right rule;
  callouts below name the file and the test surface.
- `roles/agent-research/variants/` already contains `codebase-map.md`,
  `prior-art-search.md`, `risk-discovery.md` — the P0 research fix only
  needs a YAML edit. The schema's `variant_existence_errors` validator
  will catch typos for free.
- `roles/agent-brainstorm/variants/` is empty on disk. The P1 brainstorm
  fix is therefore three new variant files plus a new merge role
  (`role-specs/agent-brainstorm-merge.md`, generated agent doc, and a
  `catalog.py` registration); paths are now pinned in P1 below.
- The pipeline schema is a pure DAG with no loop primitive. P2's
  "bounded unrolled" framing is correct; concrete YAML is now in P2.
- `agent-review` already runs the test suite directly and explicitly
  distrusts the writer's pasted output, so executable grounding for the
  P2 repair-loop reviewer exists. The missing piece is *clean context*:
  it currently sees writer/spec-review notes. P2 below decides between a
  flag and a new role for that.
- Telemetry substrate already exists in `schemas/telemetry/`
  (`runs.schema.json`, `findings.schema.json`, `adjudications.schema.json`,
  `finding_outcomes.schema.json`, `provider_findings.v2.schema.json`).
  The Eval And Telemetry Gaps section now references these instead of
  implying greenfield dashboards.

**Concerns dropped after verification:**

- `agent-codex-review-phase0` is a generated alias of `agent-codex-review`,
  not a separate role. No reconciliation work needed.
- Repair-loop does not need new test-runner tooling. `agent-review` and
  `agent-writer-judge` already exercise tests as a tool call.
- `pipeline_version` bump is not load-bearing — the field is a constant
  with no migration logic. Can be left at `1` for these changes; flagged
  here only as a soft note.

**Concerns deferred (not actioned in this revision):**

- `agent-writer-judge` reframing from "judge" to "synthesizer". The role
  is tests-first by contract (Reflexion-grounded), so the bias risk only
  applies to secondary tiebreaks. Cross-model rotation in P3 covers the
  high-leverage mitigation; a deeper reframing is deferred until eval data
  exists.
- `mco-review-lab` keep/sunset/extend decision. Plan keeps it experimental;
  a separate eval is required before changing its status.
- `smart-friend`, `agentless-repair`, `large-project-manager` remain TBD
  designs in P4. They are placeholders, not actionable work in this plan.

## Evidence Rules To Adopt

1. Prefer the simplest workflow that works.
   Anthropic's agent guidance recommends adding complexity only when it
   demonstrably improves outcomes, and names prompt chaining, routing,
   parallelization, orchestrator-workers, and evaluator-optimizer as the
   practical workflow primitives.
   Source: https://www.anthropic.com/engineering/building-effective-agents

2. Use fan-out only when there is real diversity.
   Mixture-of-Agents supports heterogeneous proposer plus aggregator layers,
   while self-consistency is strongest when there is a discrete votable answer.
   Identical-prompt prose fan-out is therefore weak.
   Sources: https://arxiv.org/abs/2406.04692 and https://arxiv.org/abs/2203.11171

3. Keep writes single-threaded by default.
   Cognition's 2026 update says the multi-agent patterns working in practice
   keep writes single-threaded while extra agents contribute review, planning,
   routing, or context. Their earlier warning still applies to parallel writer
   swarms because write actions carry implicit design decisions.
   Sources: https://cognition.ai/blog/multi-agents-working and
   https://cognition.ai/blog/dont-build-multi-agents

4. Make clean-context review first-class.
   Cognition reports clean-context Devin Review catches about two bugs per PR,
   with roughly 58% severe, and works best when the reviewer starts without the
   writer's accumulated context but communicates findings back through the
   writer/manager that still has task context.
   Source: https://cognition.ai/blog/multi-agents-working

5. Add a bounded evaluator-optimizer preset.
   Anthropic names evaluator-optimizer as a core workflow. Reflexion improves
   HumanEval pass@1 from 80% to 91% using task feedback, Self-Refine improves
   seven tasks through feedback/refinement, and Chain-of-Verification reduces
   hallucinations by independently answering verification questions before
   revising.
   Sources: https://arxiv.org/abs/2303.11366,
   https://arxiv.org/abs/2303.17651, and https://arxiv.org/abs/2309.11495

6. Treat LLM judges as biased preference tools, not correctness gates.
   MT-Bench finds GPT-4 can match human preference agreement above 80% but
   documents position, verbosity, self-enhancement, and limited-reasoning
   biases. JudgeBench finds objective correctness judging for knowledge,
   reasoning, math, and coding is much harder, with strong models such as
   GPT-4o only slightly better than random guessing on that benchmark.
   Sources: https://arxiv.org/abs/2306.05685 and https://arxiv.org/abs/2410.12784

7. Use debate sparingly.
   Multiagent Debate shows gains for several reasoning and factuality tasks,
   but ACL 2024 follow-up work finds strong single-agent prompting can nearly
   match multi-agent discussions except in no-demonstration settings.
   Sources: https://arxiv.org/abs/2305.14325,
   https://arxiv.org/abs/2305.19118, and
   https://aclanthology.org/2024.acl-long.331/

8. Optimize the agent-computer interface and validation surface.
   SWE-agent shows a custom agent-computer interface improves software-agent
   performance, while Agentless shows a simple localization -> repair -> patch
   validation flow can beat more complex open-source agents on SWE-bench Lite.
   Sources: https://arxiv.org/abs/2405.15793 and https://arxiv.org/abs/2407.01489

## Current Catalog Findings

### Solid Or Close To Solid

- `default`: good baseline graph because it keeps a single writer and includes
  `provider-review` before final review. It should gain a clean-context
  reviewer/revision option before becoming the opinionated default.
- `balanced`: best current everyday preset. It keeps the default graph and
  cheaply routes docs/spec-review/clarify/simple-writer to Codex. Recommend it
  as the current TUI/README default until the repair-loop preset ships.
- `lightweight`: keep for small edits. It matches the "simplest workflow that
  works" rule and still has provider-review evidence.
- `ultra-plan` and `design`: prompt-variant analysis fan-outs are defensible
  because they use different lenses. Their merge stage should be evidence
  synthesis, not correctness judgment.
- `review`: prompt-variant review lenses are useful, especially for output-only
  review. Keep provider-review ahead of the lens fan-out.
- `provider-review`: this is one of the strongest pieces in the catalog. Its
  consensus policy already treats single-provider findings as
  `needs-verification` and requires exact agreement from at least two
  schema-valid providers for confirmed findings.

### Must Fix Before Promotion

- `hybrid-review`: the idea is right, but the current graph does not feed the
  Codex sidecar into downstream synthesis. `review` depends only on
  `spec-review`, and the graph omits `provider-review`. Fix this before
  promoting it.
- `research`: currently uses `variant: same` even though
  `roles/agent-research/variants/` already contains `codebase-map`,
  `prior-art-search`, and `risk-discovery`. Switch it to prompt variants.
- `brainstorm`: currently fans out three identical `agent-brainstorm` branches
  and merges with the same role. Add divergent brainstorm variants and a
  distinct merge/ranking role.
- `competitive`: cross-model writers are useful for isolated alternatives, but
  this should remain an opt-in lab. The current Claude merge is vulnerable to
  same-family preference when judging Claude-vs-Codex outputs, and parallel
  writers should not be the production default.

### Demote Or Relabel

- `claude-only`: keep as diagnostic/repro/rate-limit isolation, not a
  production quality preset.
- `codex-only`: keep as an operational fallback, but do not describe it as the
  best quality preset. In the current default graph it routes both writer and
  final `agent-review` to Codex, so it does not preserve an independent
  cross-family final review.
- `mco-review-lab`: keep experimental. Any value must come from different
  context or replay evidence, not from adding another same-family review pass.

## Default Policy

1. Recommended current default in docs/TUI: `balanced`.
   It is the safest existing everyday profile because it keeps the stock
   single-writer graph, preserves provider-review, and only promotes low-risk
   roles to Codex.

2. Future opinionated default: `repair-loop`.
   Once implemented, make a bounded evaluator-optimizer flow the recommended
   default for implementation work. It should run exactly one clean-context
   review/revision cycle by default, with an explicit cap for a second cycle on
   high-risk tasks.

3. Complexity-scaled review provider defaults:
   - Trivial/docs-only: provider-review `selection=auto`, effective max 0-1.
   - Normal coding: provider-review `selection=auto`, max 2, min success 1,
     single-provider output remains `needs-verification`.
   - Security/public API/data migration/high-risk: max 4, prefer at least 2
     schema-valid providers before confirming findings.

4. Do not silently pre-activate a stock preset unless the project decides the
   old measurement gate has been satisfied. Instead, make `balanced` the
   recommended one-click activation in `/swarmdaddy:quickstart` and the TUI.

## Pipeline Changes

### P0 - Quick Wins

1. Fix `pipelines/research.yaml`.
   Change the fan-out to:

   ```yaml
   fan_out:
     role: agent-research
     count: 3
     variant: prompt_variants
     variants: [codebase-map, prior-art-search, risk-discovery]
   merge:
     strategy: synthesize
     agent: agent-research-merge
   failure_tolerance:
     mode: quorum
     min_success: 2
   ```

2. Fix `pipelines/hybrid-review.yaml`.
   Add provider-review after writer, make final review depend on
   `spec-review`, `provider-review`, and `codex-review`, and keep Codex review
   fail-open. This turns Codex review from a sidecar into usable evidence.

3. Update preset descriptions.
   Mark `claude-only` and `codex-only` as diagnostic/operational. Mark
   `competitive` as opt-in alternative generation, not production default.

4. Update README "Choosing A Profile".
   Put `balanced` first as the recommended everyday profile. Put
   `lightweight` second for small edits. Put fixed `hybrid-review` or
   future `repair-loop` as high-confidence/high-risk profiles.

### P1 - Brainstorm And Review Shape

1. Add brainstorm variants. Pin file paths so the schema validator
   (`variant_existence_errors`) accepts the YAML on first run:
   - `roles/agent-brainstorm/variants/expand-options.md` — generate broad
     alternatives.
   - `roles/agent-brainstorm/variants/constraints-and-failure-modes.md` —
     look for adoption blockers and ways ideas fail.
   - `roles/agent-brainstorm/variants/analogies-and-transfers.md` — import
     patterns from adjacent domains.

   Each variant must follow the existing overlay convention: keep the
   `agent-brainstorm` output schema, only bias the prompt.

2. Add `agent-brainstorm-merge` as a distinct role. Required artifacts:
   - `role-specs/agent-brainstorm-merge.md` — backend-neutral contract.
   - `agents/agent-brainstorm-merge.md` — generated alias (run
     `python3 -m swarm_do.roles gen --write` after the role-spec lands).
   - `py/swarm_do/pipeline/catalog.py` — register the role and its
     output contract so `pipelines/brainstorm.yaml` can reference it.
   - Update `pipelines/brainstorm.yaml` to set
     `variant: prompt_variants` with the three variants above and
     `merge.agent: agent-brainstorm-merge`.

   The merge role's contract: rank, cluster, de-duplicate, and name
   tradeoffs. Do not generate a free-form brainstorm. Do not pick a
   single winner — produce a ranked synthesis the operator can act on.

3. Add a strict output-only `review-strict` preset.
   Use provider-review with higher provider expectations and the existing
   five-lens review fan-out. Label output as evidence synthesis, not approval.

### P2 - Repair Loop Preset

Add `pipelines/repair-loop.yaml` and `presets/repair-loop.toml`.

Target graph (bounded unrolled DAG — no schema changes needed):

```yaml
stages:
  - id: research
    agents: [{ role: agent-research }]
  - id: analysis
    depends_on: [research]
    agents: [{ role: agent-analysis }]
  - id: clarify
    depends_on: [research]
    agents: [{ role: agent-clarify }]
  - id: writer
    depends_on: [analysis, clarify]
    agents: [{ role: agent-writer }]
  - id: clean-review
    depends_on: [writer]
    agents:
      - role: agent-review
        clean_context: true   # see "Clean-context reviewer" below
  - id: revise-writer
    depends_on: [writer, clean-review]
    agents: [{ role: agent-writer, lens: revise }]
    failure_tolerance: { mode: best-effort }   # if no findings, no-op
  - id: spec-review
    depends_on: [revise-writer]
    agents: [{ role: agent-spec-review }]
  - id: provider-review
    depends_on: [revise-writer]
    provider:
      type: swarm-review
      command: review
      selection: auto
      output: findings
      memory: false
      timeout_seconds: 1800
      max_parallel: 4
    failure_tolerance: { mode: best-effort }
  - id: review
    depends_on: [spec-review, provider-review]
    agents: [{ role: agent-review }]
  - id: docs
    depends_on: [spec-review]
    agents: [{ role: agent-docs }]
```

Clean-context reviewer — pick one (decision required before P2 starts):

- **Option A (smaller change):** add a `clean_context: bool` agent flag.
  When set, the orchestrator suppresses writer/spec-review notes from the
  agent's prompt; the reviewer starts from the diff and reruns only
  relevant discovery. Existing `agent-review` already runs tests directly,
  so the contract holds.
- **Option B (cleaner separation):** introduce `agent-clean-reviewer` as a
  distinct role-spec. Same grounding rules as `agent-review`, explicit
  "do not read writer notes" clause, and its own catalog entry.

Recommend Option A for v1; reassess after the first eval run.

Implementation notes:

- The clean reviewer must rerun the test suite itself (already required
  by the `agent-review` contract — `Sequencing & ownership` step 5).
- The `revise-writer` stage receives the original task context plus
  reviewer findings, then decides whether to apply, reject as
  out-of-scope, or escalate via beads notes.
- Default iterations: exactly one revision. A second pass is only added
  when the plan or risk tags request it; do not add a generic
  iteration-count knob in v1.
- Prefer executable validation evidence over prose judgment. The
  `provider-review` consensus policy already enforces this for findings.

No pipeline-schema changes are required for v1 — the unrolled DAG
fits the existing primitives.

### P3 - Cross-Model Merge And Judge Support

The blocker lives in `py/swarm_do/pipeline/validation.py:invariant_errors`.
Three rules force Claude resolution today: (a) `orchestrator`,
(b) `agent-code-synthesizer`, (c) every `merge.strategy=synthesize`
merge `agent`. Rule (c) is what blocks cross-model judging in
`competitive`, `ultra-plan`, `design`, `research`, `review`, and the new
`brainstorm`/`repair-loop` graphs.

Change one of these:

1. Minimal: drop rule (c). Keep (a) and (b) — orchestrator stays Claude
   because it owns plan rendering and the dispatch contract; synthesizer
   stays Claude because its decision framework relies on Claude tool
   semantics. Add an explicit test in
   `py/swarm_do/pipeline/tests/test_pipeline_validation.py` covering a
   Codex-routed `merge.agent` to lock the relaxation.
2. Better: add explicit `merge.route` or `merge.backend/model/effort`
   support so individual presets can opt in without a global rule change.
3. Best: add paired judge support for model competitions:
   - judge A sees writer outputs in order A/B;
   - judge B sees writer outputs in order B/A or uses the other backend;
   - disagreements emit a `NEEDS_HUMAN` finding written to the run's
     beads issue notes (no new schema primitive — reuse the existing
     `findings` schema). The pipeline does not block on it; the operator
     decides.

Apply this first to `competitive`, then optionally to `ultra-plan`,
`design`, and `review` merges. **Do not touch `agent-code-synthesizer`
or `orchestrator` routing** — those stay Claude even after the rule
relaxes.

### P4 - Missing Presets

Add these in order:

1. `codebase-map`
   Output-only read-only localization using the existing `codebase-map`
   research lens. Useful before large refactors and for human planning.

2. `research-orchestrator`
   Breadth-first research with explicit subquestions, source-quality rules,
   citation verification, and complexity-scaled fan-out. Start static with the
   three existing research variants; only add dynamic subagents after evals.

3. `smart-friend`
   Primary writer stays single-threaded and can consult a stronger or
   differently capable model for hard debugging, tests, visual reasoning, or
   architecture. This requires careful context transfer and should ship as
   experimental first.

4. `agentless-repair`
   Localization -> candidate patch -> validation/rerank. This is a simple,
   interpretable baseline inspired by Agentless and should be measured against
   heavier agent flows.

5. `large-project-manager`
   Manager decomposes work into isolated branches/worktrees, child agents work
   on bounded units, and the manager synthesizes shared decisions. This should
   be reserved for large projects with natural decomposition.

## Eval And Telemetry Gaps

The repo already ships telemetry schemas under `schemas/telemetry/`
(`runs.schema.json`, `findings.schema.json`, `finding_outcomes.schema.json`,
`adjudications.schema.json`, `provider_findings.v2.schema.json`,
`run_events.schema.json`, `observations.schema.json`). The work here is
to plug into them, not to design new ones.

1. Define the preset-promotion metric set on top of existing schemas.
   Map to existing fields wherever possible:
   - false-positive rate, true bugs found, maintainer-applied findings →
     join `findings.schema.json` with `finding_outcomes.schema.json`.
   - rollback / rework rate → `runs.schema.json` retry/handoff counts.
   - wall time, cost → already on `runs.schema.json`.
   - judge disagreements → `adjudications.schema.json`.

   Document the join recipe in `docs/eval-recipes.md` so any contributor
   can rebuild the dashboard from raw run logs.

2. Capture a `balanced` baseline before P0 ships.
   Run the `balanced` preset on a fixed set of representative tasks and
   record the metric set above. Without a baseline, P3's "beat balanced"
   gate cannot fire. **This is now Step 0 of the Ordered Implementation
   Plan below.**

3. Calibrate provider-review consensus on labeled local samples.
   The code already has `providers calibrate-consensus`; make it part of
   the release checklist for any provider-review default change.

4. Add A/B gates before promoting `repair-loop`, `hybrid-review`, or
   `competitive`. A preset should not become default because it feels more
   sophisticated. Concrete gate: ≥10 representative tasks, beat `balanced`
   on accepted findings *or* rework rate *or* wall-time-per-accepted-fix
   at a cost delta ≤ +25 percent. Tie ⇒ stay on `balanced`.

5. Document benchmark humility.
   SWE-bench-style numbers are useful but can drift or be contaminated.
   Keep local task evals closer to the actual SwarmDaddy workflows.

## Proposed Catalog After Changes

Recommended:

- `balanced`: everyday implementation default until `repair-loop` is ready.
- `lightweight`: small/local changes.
- `repair-loop`: future default for normal coding.
- `hybrid-review`: high-confidence review once fixed.

Specialized:

- `ultra-plan`: high-risk planning before implementation.
- `design`: output-only architecture/design plan.
- `research`: output-only evidence memo with prompt-variant fan-out.
- `review`: output-only review evidence.
- `codebase-map`: read-only localization.

Experimental:

- `smart-friend`
- `agentless-repair`
- `large-project-manager`
- `mco-review-lab`
- `competitive`

Diagnostic/operational:

- `claude-only`
- `codex-only`

## Ordered Implementation Plan

0. **Capture a `balanced` baseline.** Run on ≥10 representative tasks,
   record the metric set in *Eval And Telemetry Gaps §1*. Blocks P3 gates;
   does not block P0–P2 work.
1. Patch `pipelines/research.yaml` and `pipelines/hybrid-review.yaml`;
   update preset descriptions for `claude-only`, `codex-only`, `competitive`;
   update README's "Choosing A Profile".
2. Add brainstorm variants and `agent-brainstorm-merge` role; pin file
   paths per P1 above; register in `catalog.py`; switch
   `pipelines/brainstorm.yaml` to `prompt_variants`.
3. Add `repair-loop` preset (`pipelines/repair-loop.yaml`,
   `presets/repair-loop.toml`). Decide Option A vs B for the clean-context
   reviewer first.
4. Plug preset-promotion metrics into existing `schemas/telemetry/*`;
   write `docs/eval-recipes.md`.
5. Relax `validation.py:invariant_errors` rule (c); add the regression
   test. Then route the `competitive` writer-judge cross-model.
6. Add `codebase-map`, then `research-orchestrator` presets.
7. Treat `smart-friend`, `agentless-repair`, and `large-project-manager`
   as separate-design TBDs. Do not implement under this plan.
8. Document the measurement gate.
9. After step 8 lands and a baseline + one A/B comparison exists,
   evaluate whether the TUI default should switch from `balanced` to
   `repair-loop`. (Split from step 8 — separate decision.)

## Touched / Added / Deferred Map

| Section | Status |
|---|---|
| Reviewer Notes (2026-04-27) | **Added** — validates findings against code, drops false positives. |
| Executive Decision | Untouched. |
| Evidence Rules To Adopt | Untouched. |
| Current Catalog Findings | Untouched — assertions verified true on disk. |
| Default Policy | Untouched. |
| P0 - Quick Wins | Untouched (research variants verified to exist). |
| P1 - Brainstorm And Review Shape | **Updated** — file paths pinned; catalog-registration step added. |
| P2 - Repair Loop Preset | **Updated** — concrete YAML; clean-context reviewer Option A vs B decision; confirmed no schema change needed. |
| P3 - Cross-Model Merge And Judge Support | **Updated** — names `validation.py:invariant_errors` and the three rules; reuses existing `findings` schema for `NEEDS_HUMAN`; explicit guard against touching synthesizer/orchestrator routing. |
| P4 - Missing Presets | Untouched — `smart-friend`, `agentless-repair`, `large-project-manager` flagged as TBD in Reviewer Notes. |
| Eval And Telemetry Gaps | **Updated** — references existing `schemas/telemetry/*`; adds Step 0 baseline; adds concrete A/B gate thresholds. |
| Proposed Catalog After Changes | Untouched. |
| Ordered Implementation Plan | **Updated** — Step 0 baseline added; step 8 split; absolute paths added. |

