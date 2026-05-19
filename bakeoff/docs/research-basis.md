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
- Wang et al.,
  ["Large Language Models are not Fair Evaluators"](https://arxiv.org/abs/2305.17926),
  and Zheng et al.,
  ["Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"](https://arxiv.org/abs/2306.05685):
  support treating LLM judges as useful but biased. Bakeoff uses swapped A/B
  and B/A judgment for `compare` and `analyze` so the first answer does not get
  an unearned advantage.
- Heuer,
  ["Psychology of Intelligence Analysis"](https://www.cia.gov/resources/csi/static/Pyschology-of-Intelligence-Analysis.pdf):
  supports analysis of competing hypotheses: list plausible explanations, map
  evidence against each one, look for evidence that could disprove them, and
  check how sensitive the conclusion is to key assumptions.

The short version:

| Type | Good fit | What tends to work | What Bakeoff does | Caveat |
| --- | --- | --- | --- | --- |
| `gather` | "Find the places, facts, files, sources, or citations." | Breadth first, then dedupe. Independent runs help because one provider may find evidence the other misses. | Runs both providers, then creates a structured union of supported claims and citations. | It is not proof of "every possible place" unless the task gives a searchable scope and the report explains the search paths used. |
| `compare` | "Pick between named options." | Name the options, name the criteria, apply hard constraints first, then compare tradeoffs. | Runs both providers, then uses swapped judging to pick a winner, consensus, or tie. | If criteria are vague or the top options are close, the right answer may be "pilot it" or "no clear winner." |
| `analyze` | "Explain why this happened" or "build the reasoning spine." | Start with evidence, test multiple explanations, and say what would change the conclusion. | Runs both providers, then uses swapped spine judging with deterministic fallback when judges disagree. | Agreement is not root-cause proof. Strong analysis needs logs, traces, repro steps, tests, or other direct evidence. |

Current implementation mapping:

- `gather` runs two providers, then a single structured-union judge.
- `compare` runs two providers, then swapped A/B and B/A judging.
- `analyze` runs two providers, then swapped spine judging with a deterministic
  fallback when the swapped judges disagree.

### Compare Guidance

Use `compare` when the choice can be written down before the run: "SQLite FTS
vs Tantivy vs OpenSearch for local product search" is good; "what should we do"
is usually too loose. A good compare work order should name:

- the options;
- the hard constraints that can eliminate an option immediately;
- the criteria that matter, such as correctness, latency, cost, migration risk,
  maintenance, licensing, and reversibility;
- any evidence that should count more than opinion, such as benchmarks,
  production constraints, or primary docs.

The simple mental model is: first remove options that cannot work, then compare
the survivors. If a small change in criteria would flip the winner, Bakeoff
should report that uncertainty instead of pretending the choice is settled.
That is why close calls should end as a tie, a pilot recommendation, or "no
clear winner."

This follows the same spirit as
[Multi-Criteria Decision Analysis guidance](https://www.gov.uk/government/publications/green-book-supplementary-guidance-multi-criteria-decision-analysis/use-of-multi-criteria-decision-analysis-in-options-appraisal-of-economic-cases):
make criteria explicit, compare options against those criteria, and stress-test
the result under changed assumptions.

### Analyze And Root-Cause Guidance

Use `analyze` when the output should read like a supported explanation, not a
bag of notes. For debugging and RCA-style work, the evidence ladder is:

- direct reproduction or a failing test;
- production traces, logs, database rows, or event history;
- code paths and state transitions that explain the symptom;
- rejected alternatives, especially plausible explanations that the evidence
  rules out.

An analysis is "confirmed" only when direct evidence connects the symptom to the
cause and a deterministic check supports it. It is "probable" when the evidence
is strong but no direct reproduction or decisive trace exists. It is
"insufficient" when the answer is mostly a plausible story, even if both
providers agree.

This is why Bakeoff asks for source-backed reasoning instead of a confident
narrative. Failure-reproduction work such as
[ReproCopilot](https://www.microsoft.com/en-us/research/publication/reprocopilot-llm-driven-failure-reproduction-with-dynamic-refinement/)
points in the same direction: reproducing the failure is a stronger artifact
than describing it. Trace systems such as
[OpenTelemetry](https://opentelemetry.io/docs/specs/otel/overview/) also matter
because traces preserve causal relationships across spans, which is exactly the
shape RCA needs.

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
