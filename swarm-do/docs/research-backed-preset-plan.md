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

1. Add brainstorm variants:
   - `expand-options`: generate broad alternatives.
   - `constraints-and-failure-modes`: look for adoption blockers and ways ideas
     fail.
   - `analogies-and-transfers`: import patterns from adjacent domains.

2. Add `agent-brainstorm-merge` or equivalent.
   The merge role should rank, cluster, de-duplicate, and name tradeoffs. It
   should not generate another free-form brainstorm.

3. Add a strict output-only `review-strict` preset.
   Use provider-review with higher provider expectations and the existing
   five-lens review fan-out. Label output as evidence synthesis, not approval.

### P2 - Repair Loop Preset

Add `pipelines/repair-loop.yaml` and `presets/repair-loop.toml`.

Target graph:

```text
research -> analysis + clarify -> writer
  -> local validation summary
  -> clean-context review
  -> revision writer
  -> spec-review + provider-review
  -> final review
  -> docs
```

Implementation notes:

- The reviewer should start from the diff and rerun only relevant context
  discovery.
- The revision writer should see the original task context plus reviewer
  findings, then decide whether to apply, reject as out-of-scope, or escalate.
- Cap default iterations at one revision. Add a preset budget field or pipeline
  convention for a second pass only when the plan or risk tags request it.
- Prefer executable validation evidence over prose judgment.

This may require runtime work because the current pipeline schema is a DAG with
stage dependencies, not an explicit loop primitive. A bounded unrolled loop is
enough for v1.

### P3 - Cross-Model Merge And Judge Support

Current validation forces every `merge.strategy=synthesize` agent to resolve to
Claude. That blocks the lowest-cost mitigation for Claude-vs-Codex judging:
routing the merge/judge to the other family or running paired judges.

Change one of these:

1. Minimal: loosen the invariant so only `orchestrator` and
   `agent-code-synthesizer` must be Claude-backed.
2. Better: add explicit `merge.route` or `merge.backend/model/effort` support.
3. Best: add paired judge support for model competitions:
   - judge A sees writer outputs in order A/B;
   - judge B sees writer outputs in order B/A or uses the other backend;
   - disagreements become `NEEDS_HUMAN` or a follow-up validation task.

Apply this first to `competitive`, then optionally to `ultra-plan`, `design`,
and `review` merges.

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

1. Add preset-level outcome dashboards.
   Track false positives, true bugs found, maintainer-applied findings,
   rollback/rework rate, wall time, and cost per accepted fix.

2. Calibrate provider-review consensus on labeled local samples.
   The code already has `providers calibrate-consensus`; make it part of the
   release checklist for any provider-review default change.

3. Add A/B gates before promoting `repair-loop`, `hybrid-review`, or
   `competitive`.
   A preset should not become default because it feels more sophisticated. It
   should beat `balanced` on accepted findings, fewer rework cycles, or user
   time saved at acceptable cost.

4. Document benchmark humility.
   SWE-bench-style numbers are useful but can drift or be contaminated. Keep
   local task evals closer to the actual SwarmDaddy workflows.

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

1. Patch `research` and `hybrid-review` pipeline YAML and README descriptions.
2. Add brainstorm variants plus a distinct brainstorm merge role.
3. Add `repair-loop` as a bounded unrolled DAG preset.
4. Add telemetry/eval docs for preset promotion gates.
5. Relax or extend merge routing so cross-model adjudication is possible.
6. Add `codebase-map`, then `research-orchestrator`.
7. Add `smart-friend` and `agentless-repair` only as experimental presets with
   explicit eval criteria.
8. Revisit whether the TUI should activate `balanced` by default after the
   measurement gate decision is documented.

