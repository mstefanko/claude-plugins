# Research Basis

This page collects the design rationale and bibliography used by the README.
It is intentionally scoped to the current checkout: Bakeoff is a small,
pairwise, artifact-ledger harness for two-provider research, review, and build
runs. It does not use beads as a coordination substrate, does not ship a
spec-review -> code-review -> codex-review chain, and does not synthesize or
cherry-pick a third patch from provider outputs.

## Research, Compare, And Analyze

Bakeoff uses independent provider runs because independent samples can expose
different evidence, assumptions, and failure modes. It then compares or merges
the artifacts instead of treating either provider as authoritative.

- Wang et al.,
  ["Self-Consistency Improves Chain of Thought Reasoning in Language Models"](https://arxiv.org/abs/2203.11171):
  supports the general idea that sampling multiple reasoning paths can improve
  robustness when outputs are aggregated.
- Anthropic Engineering,
  ["How we built our multi-agent research system"](https://www.anthropic.com/engineering/multi-agent-research-system):
  supports breadth-first parallel research for broad search tasks, while also
  noting high token costs and that many coding tasks have fewer parallelizable
  subtasks.
- Du et al.,
  ["Improving Factuality and Reasoning in Language Models through Multiagent Debate"](https://arxiv.org/abs/2305.14325):
  supports independent candidate generation and cross-checking. Bakeoff does
  not run debate swarms.

Current implementation mapping:

- `gather` runs two providers, then a single structured-union judge.
- `compare` runs two providers, then swapped A/B and B/A judging.
- `analyze` runs two providers, then swapped spine judging with a deterministic
  fallback when the swapped judges disagree.

## Review And Facets

Bakeoff treats review as `gather` plus a `code-review` facet. A facet is a task
filter, not a persona: it gives both providers and the judge the same include,
exclude, and focus constraints.

- ["Automated Code Review Using Large Language Models at Ericsson: An Experience Report"](https://arxiv.org/abs/2507.19115):
  supports bounded, contextual LLM review and highlights false-positive risk.
- ["LAURA: Enhancing Code Review Generation with Context-Enriched Retrieval-Augmented LLM"](https://arxiv.org/abs/2512.01356):
  supports the value of contextual retrieval for review generation.
- ["Rethinking Code Review Workflows with LLM Assistance"](https://arxiv.org/abs/2505.16339):
  supports review assistance use cases while noting trust and false-positive
  concerns.
- Zheng et al.,
  ["When 'A Helpful Assistant' Is Not Really Helpful"](https://arxiv.org/abs/2311.10054):
  supports avoiding overclaiming persona prompting as a factuality strategy.
- Huang et al.,
  ["Large Language Models Cannot Self-Correct Reasoning Yet"](https://arxiv.org/abs/2310.01798):
  supports using independent provider outputs and external triage instead of
  asking one model to simply review itself.
- Verga et al.,
  ["Replacing Judges with Juries"](https://arxiv.org/abs/2404.18796):
  supports the general concern about single-judge bias. Bakeoff v1 uses
  heterogeneous providers and position swaps, not a full jury architecture.

Deeper local rationale:

- [faceted-research-implementation-plan-2026-05-15.md](faceted-research-implementation-plan-2026-05-15.md)

## Competitive Build

Build mode is a small-N implementation harness: generate two isolated patches,
capture artifacts, run gates and optional metrics, and judge only when evidence
cannot decide.

- Chen et al.,
  ["Evaluating Large Language Models Trained on Code"](https://arxiv.org/abs/2107.03374):
  supports candidate diversity under a strong selector.
- Li et al.,
  ["Competition-Level Code Generation with AlphaCode"](https://arxiv.org/abs/2203.07814):
  supports generation plus filtering and clustering by execution behavior.
- Brown et al.,
  ["Large Language Monkeys: Scaling Inference Compute with Repeated Sampling"](https://arxiv.org/abs/2407.21787):
  supports repeated sampling as a scaling idea. Bakeoff is the auditable
  small-N version, not a claim that N=2 matches large best-of-N systems.
- [CodeT](https://arxiv.org/abs/2207.10397),
  [MBR-EXEC](https://arxiv.org/abs/2204.11454), and
  [DOCE](https://arxiv.org/abs/2408.13745):
  support execution-based selection when executable evidence exists.
- Wang et al.,
  ["Are Solved Issues in SWE-bench Really Solved Correctly?"](https://arxiv.org/abs/2503.15223):
  supports treating tests as evidence and gates, not proof that a patch is
  correct.
- [MT-Bench / Chatbot Arena](https://arxiv.org/abs/2306.05685) and
  [FairEval](https://arxiv.org/abs/2305.17926):
  support mitigating judge position and presentation bias.
- [Agentless](https://arxiv.org/abs/2407.01489):
  supports the idea that simple repository-level repair pipelines can compete
  with heavier agent systems.

Deeper local rationale:

- [competitive-builds-evidence-2026-05-18.md](competitive-builds-evidence-2026-05-18.md)

## Thin Launcher Rationale

Bakeoff stays narrow because full multi-agent orchestration adds scheduling,
role coordination, shared state, termination, retries, and synthesis semantics.
Those are real product choices, and the current implementation chooses a
smaller property: replayable, pairwise, auditable runs.

- Anthropic Engineering,
  ["How we built our multi-agent research system"](https://www.anthropic.com/engineering/multi-agent-research-system):
  supports the usefulness of parallel breadth on broad research tasks while
  documenting cost and task-fit caveats.
- ["MAST: A Multi-Agent Systems Failure Taxonomy"](https://arxiv.org/abs/2503.13657):
  supports taking coordination and role failures seriously.
- [Agentless](https://arxiv.org/abs/2407.01489):
  supports simple, repository-level approaches as a serious baseline.

Bakeoff's current boundary is explicit: build reports and selected patches are
handoff artifacts. Applying, combining, rewriting, committing, pushing, or
publishing a patch is a separate request and needs fresh verification.
