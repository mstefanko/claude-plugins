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
  the current `swarm-run` prompt includes Beads dependency/thread context,
  so a clean reviewer needs dispatcher/runner support that suppresses
  writer notes. The earlier `clean_context: true` sketch is not legal
  pipeline YAML until the schema, validation, and runner learn that field.
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
- `smart-friend`, `agentless-repair`, `large-project-manager`, and an
  Outcome dashboard were rechecked in this pass. `smart-friend` and
  `large-project-manager` have straightforward v1 shapes that can be
  folded into P4 as experimental designs. `agentless-repair` plus richer
  manager policy and dashboard UI need separate runtime design before
  implementation.

### Remaining Gaps Found In This Pass

- P2's earlier YAML used unsupported keys: `clean_context: true` is not in
  `schemas/pipeline.schema.json`, and `lens: revise` has no matching lens
  catalog entry. P2 below now removes those fields and names the required
  role/runner changes instead.
- Any new runnable role must land in more than `role-specs/`: add the
  generated `agents/` file, a `roles/<role>/shared.md` bundle, a
  `ROLE_DEFAULTS` route if the TUI/settings should expose it, and telemetry
  schema/extractor support if the role emits findings.
- `outcomes.jsonl` exists but its schema still says the write path is a
  later phase. Outcome reporting should therefore be recipe-first over
  `runs`, `findings`, `finding_outcomes`, and `adjudications` until a
  durable phase-outcome writer exists.
- The current pipeline DSL is a DAG. It cannot express iterative manager
  loops or deterministic candidate-patch generation/reranking without new
  runtime primitives.

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

Target graph (bounded unrolled DAG — no loop primitive needed):

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
      - role: agent-clean-review
  - id: revise-writer
    depends_on: [writer, clean-review]
    agents: [{ role: agent-writer }]
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

Clean-context reviewer decision:

- Use a distinct role for v1: `agent-clean-review`.
  The role has the same no-edit/test-rerun grounding as `agent-review`, but
  starts from sanitized task context, the diff, changed-file list, and test
  commands. It must not receive writer notes, spec-review notes, or previous
  reviewer prose in its prompt.
- Add runner/dispatcher support for that sanitized context. Today
  `swarm-run` assembles `bd show --refs --thread` dependency context for
  normal agents, so a new role alone is not sufficient. Implement this as a
  role-specific runner mode or an explicit future schema flag; do not put
  `clean_context: true` in stock YAML until the schema accepts it.
- Add the normal role plumbing: `role-specs/agent-clean-review.md`,
  generated `agents/agent-clean-review.md`, `roles/agent-clean-review/`
  bundle, `ROLE_DEFAULTS`, and findings extraction/schema coverage if this
  role's findings should join `findings.jsonl`.
- The revision writer uses the ordinary `agent-writer` role. Extend the
  writer contract so a respawn after clean-review treats reviewer findings
  as highest-priority input, can reject out-of-scope findings in notes, and
  can return a no-op result without committing when clean-review approves.

Implementation notes:

- The clean reviewer must rerun the test suite itself, matching the
  `agent-review` grounding rule from `Sequencing & ownership` step 5.
- The `revise-writer` stage receives the original task context plus
  reviewer findings, then decides whether to apply, reject as
  out-of-scope, or escalate via beads notes.
- Default iterations: exactly one revision. A second pass is only added
  when the plan or risk tags request it; do not add a generic
  iteration-count knob in v1.
- Prefer executable validation evidence over prose judgment. The
  `provider-review` consensus policy already enforces this for findings.

No new loop primitive is required for v1 — the unrolled DAG fits the
existing pipeline shape. Clean context is still a runner/role-plumbing
change, and becomes a pipeline-schema change only if the project chooses an
explicit YAML flag instead of role-specific runner behavior.

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

Telemetry note: `adjudications.v2.schema.json` is useful for sampled human
review, but it requires an `outcome_id`, and the phase-level
`outcomes.jsonl` write path is not yet active. For P3 implementation, emit
immediate disagreement signals as findings/run notes first; add adjudication
rows only after the outcome writer or an explicit finding-linked v3 design
exists.

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
   Ship v1 as an experimental *advisor stage*, not live conversational
   consultation. Base it on `balanced` or future `repair-loop`, preserve one
   mutating writer, and add one read-only advisor stage after
   `analysis`/`clarify` and before `writer`:

   ```yaml
   - id: advisor
     depends_on: [analysis, clarify]
     agents:
       - role: agent-implementation-advisor
         route: smart-advisor
   - id: writer
     depends_on: [analysis, clarify, advisor]
     agents:
       - role: agent-writer
   ```

   The advisor output should be structured evidence, not coaching:
   debugging hypotheses, architecture risks, test strategy, UI/visual
   inspection notes when screenshots or assets are explicitly provided, and
   "do not apply blindly" caveats. The writer remains responsible for
   applying changes and running tests.

   Keep the operator-facing preset name `smart-friend` if desired, but name
   the internal role by task (`agent-implementation-advisor`) rather than a
   broad persona. This follows the lens guidance in
   `docs/pipeline-composer-implementation-plan.md` and
   `docs/lens-catalog-v1-research.md`: narrow task/rubric lenses beat generic
   social-role prompts. Add the role, route default, preset, validation tests,
   and an A/B comparison against `balanced` before promotion.

4. `agentless-repair`
   Separate runtime design required. The useful target is:
   localization -> candidate unified diffs -> temp-worktree validation/rerank
   -> hand the winning patch to the normal writer/spec-review/review lane.
   It should be a benchmark-oriented baseline against `repair-loop`, not a
   default implementation path.

   Current primitives are not enough for true Agentless-style repair:
   provider stages only support `command: review`, agent stages mutate through
   Beads/worktree execution rather than patch artifacts, and the pipeline DSL
   has no deterministic candidate-patch/rerank primitive. Before
   implementation, design the patch artifact format, temp-worktree lifecycle,
   validation command contract, failure reporting, and telemetry fields. Also
   decide whether localization reuses `agent-debug` or gets a narrower
   read-only `agent-localize-bug` role.

5. `large-project-manager`
   Fold a conservative v1 into the plan as a preset/policy over existing
   decomposition rather than a new manager primitive. Start with
   `balanced` or future `repair-loop` plus:

   ```toml
   [decompose]
   mode = "inspect"
   ```

   The "manager" is the dispatcher/coordinator behavior that already exists:
   inspect the plan, produce or accept `work_units.v2`, create child Beads
   issues only after decomposition is accepted, assign isolated
   branches/worktrees, merge only after spec-review, and write cross-unit
   decisions into run notes/checkpoints. This should stay experimental and
   reserved for naturally decomposable large phases.

   Promotion to `decompose.mode = "enforce"` should follow ADR 0004's
   hard-phase scorecard. Richer manager policy — max unit parallelism,
   hard-only enforcement, merge-conflict escalation, cross-unit decision logs,
   operator-intervention thresholds, and iterative replanning loops — is a
   separate design because the preset schema currently only supports
   `off|inspect|enforce`.

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
   - judge disagreements → immediate findings/run notes first; use
     `adjudications.schema.json` after the required outcome linkage exists.

   Document the join recipe in `docs/eval-recipes.md` so any contributor
   can rebuild the dashboard from raw run logs.

   Outcome dashboard v1 should be recipe-first:
   - Add `docs/eval-recipes.md` with SQL examples for
     `swarm-telemetry query` and the equivalent `swarm-telemetry report`
     invocations.
   - Treat `finding_outcomes.jsonl` as the concrete maintained outcome
     signal today. Treat `outcomes.jsonl` as optional until its write path
     is active.
   - Surface preset/pipeline comparisons by `(pipeline_name, phase_kind,
     phase_complexity)`, accepted findings by provider/role, false-positive
     rate from adjudicated findings, rework from retry/handoff counts, and
     wall/cost from `runs`.
   - Keep the TUI as a thin mirror/link first: show top-line outcome cards
     and the command to reproduce the report. Do not add richer TUI charts
     until the CLI recipe is trusted or the SQLite indexer becomes necessary.

2. Capture a `balanced` baseline before P0 ships.
   Run the `balanced` preset on a fixed set of representative tasks and
   record the metric set above. Without a baseline, P3's "beat balanced"
   gate cannot fire. **This is now Step 0 of the Ordered Implementation
   Plan below.**

3. Calibrate provider-review consensus on labeled local samples.
   The code already has `providers calibrate-consensus`; make it part of
   the release checklist for any provider-review default change.

4. Add A/B gates before promoting `repair-loop`, `hybrid-review`,
   `competitive`, `smart-friend`, or `large-project-manager`. A preset
   should not become default because it feels more sophisticated. Concrete
   gate: ≥10 representative tasks, beat `balanced` on accepted findings *or*
   rework rate *or* wall-time-per-accepted-fix at a cost delta ≤ +25 percent.
   Tie ⇒ stay on `balanced`.

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
- `review-strict`: output-only review evidence with stricter provider expectations.
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
   paths per P1 above; add role route defaults where needed; register in
   `catalog.py`; switch `pipelines/brainstorm.yaml` to
   `prompt_variants`; add the `review-strict` output-only preset.
3. Add `repair-loop` preset (`pipelines/repair-loop.yaml`,
   `presets/repair-loop.toml`). First add `agent-clean-review`, clean
   context runner/dispatcher behavior, findings extraction/schema support
   if needed, and the writer respawn contract for review feedback.
4. Plug preset-promotion metrics into existing `schemas/telemetry/*`;
   write `docs/eval-recipes.md` as Outcome dashboard v1.
5. Relax `validation.py:invariant_errors` rule (c); add the regression
   test. Then route the `competitive` writer-judge cross-model.
6. Add `codebase-map`, then `research-orchestrator` presets.
7. Add experimental `smart-friend` and `large-project-manager` v1 designs
   only after their required role/preset or decompose-policy plumbing is
   explicit. Keep `large-project-manager` at `decompose.mode="inspect"`
   until ADR 0004's scorecard supports enforcement.
8. Write a separate `agentless-repair` design before implementation. It
   needs candidate patch artifacts, temp-worktree validation/rerank, and
   telemetry design beyond the current pipeline DSL.
9. Document the measurement gate.
10. After step 9 lands and a baseline + one A/B comparison exists,
   evaluate whether the TUI default should switch from `balanced` to
   `repair-loop`. (Split from step 9 — separate decision.)

## Touched / Added / Deferred Map

| Section | Status |
|---|---|
| Reviewer Notes (2026-04-27) | **Updated** — validates findings against code, drops false positives, and names remaining executable gaps. |
| Executive Decision | Untouched. |
| Evidence Rules To Adopt | Untouched. |
| Current Catalog Findings | Untouched — assertions verified true on disk. |
| Default Policy | Untouched. |
| P0 - Quick Wins | Untouched (research variants verified to exist). |
| P1 - Brainstorm And Review Shape | **Updated** — file paths pinned; catalog-registration step added. |
| P2 - Repair Loop Preset | **Updated** — removes invalid `clean_context`/`lens: revise` YAML, names `agent-clean-review` and runner/context requirements. |
| P3 - Cross-Model Merge And Judge Support | **Updated** — names `validation.py:invariant_errors` and the three rules; reuses existing `findings` schema for immediate `NEEDS_HUMAN`; defers adjudication rows until outcome linkage exists. |
| P4 - Missing Presets | **Updated** — folds in `smart-friend` and `large-project-manager` v1 designs; marks `agentless-repair` as separate runtime design. |
| Eval And Telemetry Gaps | **Updated** — references existing `schemas/telemetry/*`; adds Step 0 baseline; adds Outcome dashboard v1; adds concrete A/B gate thresholds. |
| Proposed Catalog After Changes | **Updated** — adds `review-strict` to specialized presets. |
| Ordered Implementation Plan | **Updated** — Step 0 baseline added; repair-loop prerequisites fixed; experimental design sequencing clarified. |
