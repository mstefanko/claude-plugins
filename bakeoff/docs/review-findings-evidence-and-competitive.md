# Bakeoff — Competitive Landscape and Evidence Base

> Historical note: this memo predates the current Bakeoff design. It describes
> an older, heavier orchestration direction with beads, multi-phase pipelines,
> and synthesis roles. The current checkout is intentionally thinner: two
> providers, one judge or verifier path, replayable artifacts, and no automatic
> patch synthesis. Use [research-basis.md](research-basis.md) and the README as
> the current source of truth.

Research support for the user-friendly README rewrite. Drop-in citation lines live in the last section.

---

## 1. Competitive landscape

Bakeoff is a Claude Code plugin that runs multi-agent pipelines (researcher → analysis → writer → reviewer, plus competitive variants with two writers + judge, code synthesis, and cross-model review) backed by a `bd` beads issue tracker. Issues move through `ready → in_progress → closed`. The closest comparables fall into three families: (a) generic multi-agent orchestrators, (b) coding-agent frameworks, (c) Claude Code-native primitives.

| Tool | Approach | Coordination substrate | Distinction from bakeoff |
|---|---|---|---|
| **LangGraph** (LangChain) | Graph of nodes (agents/tools) with explicit edges; supervisor / handoff / network patterns. | In-memory `State` object passed across nodes; checkpointer for durability. | Bakeoff ships opinionated *pipelines* (research/competitive/synthesis) rather than a graph SDK. Bakeoff's coordination state is an external `bd` issue tracker, not an in-process state object. |
| **CrewAI** | Role-based "crews" of agents with `Sequential` or `Hierarchical` processes; a manager delegates and validates. | Crew memory + task outputs passed in chat history. | CrewAI focuses on role play and delegation; bakeoff is built around *adversarial/competitive* roles (two writers → judge, synthesizer) and explicit phase pumps, not delegation. |
| **Microsoft AutoGen / AgentChat** | Conversational agents in Teams (`SelectorGroupChat`, `Swarm`, `GraphFlow`, `Magentic-One`). | Shared chat context + selector function. | AutoGen relies on group chat as the substrate. Bakeoff uses durable issue rows as state, so runs survive process restarts and are inspectable with normal CLI tools. |
| **OpenAI Swarm** (now Agents SDK) | Lightweight handoffs between "routines"; explicitly educational. | In-process function returns and message history. | Swarm is single-process and ephemeral; bakeoff persists every phase transition and judge verdict in beads. |
| **MetaGPT** | "Software company" of fixed roles (PM, architect, engineer, QA) driven by Standard Operating Procedures (`Code = SOP(Team)`). | Shared message pool + structured artifacts. | MetaGPT bakes one SOP (build a product). Bakeoff is task-shape agnostic: research, competitive impl, synthesis, judge, and review pipelines compose. MetaGPT does not run two implementations head-to-head with a judge. |
| **AgentScope** | Message-passing agent framework with explicit pipeline DSL. | Pub/sub message hub. | Comparable layering, but no first-class competitive writer + judge or spec-driven review chain. |
| **Aider — architect/editor mode** | Two-model pipeline: architect proposes, editor turns proposal into edits. | Same chat session. | The first paper-thin competitive split (two models, two roles). Bakeoff generalizes this: N writers, an explicit judge, cross-model review, and persisted artifacts per role. |
| **Cline / Roo Code** | Single-agent IDE coding assistant with plan + act modes. | In-IDE session state. | Bakeoff is non-interactive batch orchestration; Cline is interactive. |
| **OpenHands (ex-OpenDevin)** | General software-engineering agent (SWE-bench focus). Composable Software Agent SDK. | Event stream and runtime state. | OpenHands is a single execution agent; bakeoff is a *meta*-runner that can call any agent (including OpenHands or Claude Code) as a phase. |
| **Claude Code subagents** | Spawn isolated sub-Claudes for parallel or context-isolating work. Built-in `/agents` mechanism. | Parent/child message passing; results return to parent. | Subagents are the *primitive* bakeoff sits on top of. Bakeoff turns them into named roles with phase ordering, judge verdicts, and durable beads issues — none of which subagents provide on their own. |
| **Continue.dev agent mode** | Single-agent IDE assistant with tools. | In-process. | Same gap as Cline. |
| **GitHub Spec Kit** | Spec-driven development toolkit; spec is the source of truth, code is generated against it. | Markdown specs + slash commands. | Spec Kit and bakeoff are complementary. Bakeoff's spec-review → code-review → codex-review chain operationalizes a spec-first workflow with adversarial reviewers across models. |

Sources: LangGraph docs (langchain-ai.github.io/langgraph), CrewAI docs (docs.crewai.com), Microsoft AutoGen AgentChat docs (microsoft.github.io/autogen), OpenAI Swarm README (github.com/openai/swarm), MetaGPT README & paper (github.com/FoundationAgents/MetaGPT, arXiv:2308.00352), Aider docs (aider.chat/docs/usage/modes.html), OpenHands README (github.com/OpenHands/OpenHands), Claude Code subagents docs (docs.claude.com/en/docs/claude-code/sub-agents), Spec Kit (github.com/github/spec-kit).

---

## 2. Bakeoff's distinguishing design choices

1. **Beads issue tracker as the coordination substrate.** Most orchestrators (AutoGen group chat, Swarm, MetaGPT message pool, LangGraph in-memory state) coordinate via in-process chat history or a graph state object. Bakeoff persists every phase transition as a `bd` issue row — runs are durable, restartable, inspectable with normal CLI tools, and immune to process death.
2. **Competitive generation with an LLM-as-judge selector** (writer-A vs writer-B → judge). No major framework ships this as a first-class pattern; aider's architect/editor is the closest split but is collaborative, not adversarial. Best-of-N research (§3.3) shows this is exactly where extra inference compute pays off.
3. **Cross-model review chain (spec-review → code-review → codex-review).** Single-model self-review degrades reasoning (Huang et al., ICLR 2024). Bakeoff routes reviews to a *different* model to dodge intra-model bias — directly aligned with the Panel-of-LLM-Judges result (Verga et al., 2024).
4. **Phased pumps with explicit role boundaries** (`ready → in_progress → closed`). Unlike free-form group chat, each role's input and output are inspectable artifacts on disk, which is what MetaGPT's SOP work argues *and* what spec-driven development (GitHub Spec Kit) calls for.
5. **Synthesizer role for code cherry-picking** between two candidate implementations. This is generative ensemble-over-artifacts, not just vote-or-pick — closer to multi-agent debate's "society of minds" than to majority voting.
6. **Composable pipelines over a coding SDK.** Where LangGraph/CrewAI/AutoGen hand you a graph or chat SDK and you assemble agents, bakeoff hands you opinionated pipelines (research, competitive impl, synthesis, judge, review) you parameterize — lower ceiling, higher floor.

---

## 3. Evidence base for multi-agent review

### 3.1 Multi-agent debate and review improve quality

- **Du, Li, Torralba, Tenenbaum, Mordatch — "Improving Factuality and Reasoning in Language Models through Multiagent Debate" (arXiv:2305.14325, 2023).** URL: https://arxiv.org/abs/2305.14325
  - > "multiple language model instances propose and debate their individual responses and reasoning processes over multiple rounds to arrive at a common final answer. Our findings indicate that this approach significantly enhances mathematical and strategic reasoning across a number of tasks."
  - > "improves the factual validity of generated content, reducing fallacious answers and hallucinations."
  - **Supports:** bakeoff's writer-A vs writer-B + judge pattern and analysis-judge variant.

- **Liang, He, Jiao, et al. — "Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate" (EMNLP 2024, arXiv:2305.19118).** URL: https://arxiv.org/abs/2305.19118
  - > "such reflection-style methods suffer from the Degeneration-of-Thought (DoT) problem: once the LLM has established confidence in its solutions, it is unable to generate novel thoughts later through reflection even if its initial stance is incorrect."
  - > "we propose a Multi-Agent Debate (MAD) framework, in which multiple agents express their arguments in the state of 'tit for tat' and a judge manages the debate process to obtain a final solution."
  - **Supports:** the case for two *independent* writers over one writer that self-revises, and the use of a judge role.

- **Madaan et al. — "Self-Refine: Iterative Refinement with Self-Feedback" (NeurIPS 2023, arXiv:2303.17651).** URL: https://arxiv.org/abs/2303.17651
  - > "Across all evaluated tasks, outputs generated with Self-Refine are preferred by humans and automatic metrics over those generated with the same LLM using conventional one-step generation, improving by ~20% absolute on average in task performance."
  - **Supports:** bakeoff's reviewer phases that feed structured feedback back into a follow-up writer phase.

### 3.2 Cross-model review beats single-model self-review

- **Huang, Chen, Mishra, et al. — "Large Language Models Cannot Self-Correct Reasoning Yet" (ICLR 2024, arXiv:2310.01798).** URL: https://arxiv.org/abs/2310.01798
  - > "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction."
  - **Supports:** the existence of bakeoff's `codex-review` (different model) instead of having the original writer self-review.

- **Verga, Hofstätter, Althammer, et al. — "Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models" (arXiv:2404.18796, 2024).** URL: https://arxiv.org/abs/2404.18796
  - > "using a PoLL composed of a larger number of smaller models outperforms a single large judge, exhibits less intra-model bias due to its composition of disjoint model families, and does so while being over seven times less expensive."
  - **Supports:** bakeoff's cross-model `codex-review` and the design of a separate judge role; also the cost story for using cheaper reviewers.

- **Zheng, Chiang, Sheng, et al. — "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (NeurIPS 2023 Datasets & Benchmarks, arXiv:2306.05685).** URL: https://arxiv.org/abs/2306.05685
  - > "strong LLM judges like GPT-4 can match both controlled and crowdsourced human preferences well, achieving over 80% agreement, the same level of agreement between humans."
  - > Documents "position, verbosity, and self-enhancement biases" of LLM judges — extra motivation for using a *different* model as judge.
  - **Supports:** the LLM-as-judge step itself and the explicit choice to use a non-author model.

### 3.3 Competitive generation / best-of-N / inference-time compute scaling

- **Wang, Wei, Schuurmans, et al. — "Self-Consistency Improves Chain of Thought Reasoning in Language Models" (ICLR 2023, arXiv:2203.11171).** URL: https://arxiv.org/abs/2203.11171
  - > "self-consistency boosts the performance of chain-of-thought prompting with a striking margin on a range of popular arithmetic and commonsense reasoning benchmarks, including GSM8K (+17.9%), SVAMP (+11.0%), AQuA (+12.2%), StrategyQA (+6.4%) and ARC-challenge (+3.9%)."
  - **Supports:** the basic premise that *running multiple candidates and selecting* beats one-shot generation.

- **Brown, Juravsky, Ehrlich, et al. — "Large Language Monkeys: Scaling Inference Compute with Repeated Sampling" (arXiv:2407.21787, 2024).** URL: https://arxiv.org/abs/2407.21787
  - > "we apply repeated sampling to SWE-bench Lite, the fraction of issues solved with DeepSeek-Coder-V2-Instruct increases from 15.9% with one sample to 56% with 250 samples, outperforming the single-sample state-of-the-art of 43%."
  - > "coverage … scales with the number of samples over four orders of magnitude. … the relationship between coverage and the number of samples is often log-linear."
  - **Supports:** the central premise of bakeoff's *competitive* mode — two independent writers, then a judge — as a small-N instance of inference-time scaling.

- **ChatEval — Chan, Chen, Su, et al. (arXiv:2308.07201, 2023).** URL: https://arxiv.org/abs/2308.07201
  - > "a multi-agent referee team called ChatEval to autonomously discuss and evaluate the quality of generated responses from different models on open-ended questions."
  - **Supports:** bakeoff's judge/reviewer roles when the output is a written artifact rather than verifiable code.

### 3.4 Spec-driven development and structured roles

- **GitHub Engineering Blog — "Spec-driven development with AI: Get started with a new open source toolkit" (Den Delimarsky, Sep 2, 2025).** URL: https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/
  - > "We treat coding agents like search engines when we should be treating them more like literal-minded pair programmers. They excel at pattern recognition but still need unambiguous instructions."
  - > "specifications — not as static documents, but as living, executable artifacts … Specs become the shared source of truth."
  - **Supports:** bakeoff's spec-review-first chain (spec-review → code-review → codex-review). The spec is the contract reviewers check against.

- **Hong, Zhuge, Chen, et al. — "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework" (ICLR 2024, arXiv:2308.00352).** URL: https://arxiv.org/abs/2308.00352
  - > "Solutions to more complex tasks … are complicated through logic inconsistencies due to cascading hallucinations caused by naively chaining LLMs."
  - > "MetaGPT encodes Standardized Operating Procedures (SOPs) into prompt sequences … allowing agents with human-like domain expertise to verify intermediate results and reduce errors."
  - **Supports:** bakeoff's case for explicit phased roles with structured handoffs over free-form chat.

- **Bai et al. — "Constitutional AI: Harmlessness from AI Feedback" (Anthropic, arXiv:2212.08073, 2022).** URL: https://arxiv.org/abs/2212.08073
  - Establishes the broader pattern of using one model's critique-and-revise on another's outputs as a quality-control mechanism — the same shape as bakeoff's reviewer chain.

### 3.5 Issue-tracker / external state as coordination substrate

There is less direct peer-reviewed work on "issue tracker as agent substrate" specifically, but the supporting evidence comes from three angles:

- **MetaGPT (arXiv:2308.00352, above)** explicitly identifies "cascading hallucinations caused by naively chaining LLMs" via raw message-passing and proposes *structured artifacts* (specs, designs, code) as the handoff format. Bakeoff's beads rows are the durable equivalent.
- **Huang et al. (arXiv:2310.01798, above)** shows in-process self-correction degrades quality — i.e., the *coordinator* needs to be external to the generator. A separate issue tracker is one realization.
- **Brown et al. (arXiv:2407.21787, above)** notes that majority voting and reward models "plateau beyond several hundred samples." This is an argument for *richer* selection state (structured judge verdicts attached to each candidate) than what fits in chat history — i.e., for something like a beads row per candidate.

(If the reader wants a peer-reviewed citation for "external durable state for agents," Anthropic's [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) blog post and the [LangGraph persistence docs](https://langchain-ai.github.io/langgraph/concepts/persistence/) are the closest practitioner sources.)

---

## 4. README-ready cited sentences

Drop these into the README; footnote numbers correspond to the source list below.

1. "Multi-agent debate **'significantly enhances mathematical and strategic reasoning across a number of tasks'** and **'improves the factual validity of generated content, reducing fallacious answers and hallucinations.'** [^du2023]"
2. "A single model trying to fix its own work hits the *Degeneration-of-Thought* trap: **'once the LLM has established confidence in its solutions, it is unable to generate novel thoughts later through reflection even if its initial stance is incorrect.'** [^liang2024] In fact, **'LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction.'** [^huang2024]"
3. "Bakeoff routes review to a *different* model. A panel of diverse evaluators **'outperforms a single large judge, exhibits less intra-model bias due to its composition of disjoint model families, and does so while being over seven times less expensive.'** [^verga2024]"
4. "Strong LLM judges **'can match both controlled and crowdsourced human preferences well, achieving over 80% agreement, the same level of agreement between humans'** — but only when you control for position, verbosity, and self-enhancement biases. [^zheng2023] Bakeoff's judge role applies these mitigations by default."
5. "Why run two writers? Inference-time scaling: on SWE-bench Lite, **'the fraction of issues solved with DeepSeek-Coder-V2-Instruct increases from 15.9% with one sample to 56% with 250 samples'** [^brown2024]. Two competing writers + a judge is the smallest pragmatic instance of that curve."
6. "Self-Refine — same-model critique-and-rewrite — already buys **'~20% absolute on average in task performance'** across seven diverse tasks [^madaan2023]; bakeoff layers cross-model review on top of that for the cases where same-model self-correction stalls."
7. "Even simple majority voting (self-consistency) yields **'+17.9% on GSM8K, +11.0% on SVAMP, +12.2% on AQuA'** over single-shot generation [^wang2023] — the bakeoff judge-over-candidates pattern is a richer realization of the same idea."
8. "Naively chaining LLMs causes **'logic inconsistencies due to cascading hallucinations'** [^hong2024]; bakeoff's phased issue-tracker handoffs and structured per-role artifacts (spec, analysis, code, review) are the same fix MetaGPT prescribed."
9. "GitHub's Spec Kit team puts it directly: **'we should be treating [coding agents] more like literal-minded pair programmers'** that need **'unambiguous instructions'**, with specs as **'living, executable artifacts'** [^speckit2025]. Bakeoff operationalizes that with a spec-review → code-review → codex-review chain."

### Footnotes

- [^du2023]: Du, Li, Torralba, Tenenbaum, Mordatch. *Improving Factuality and Reasoning in Language Models through Multiagent Debate.* arXiv:2305.14325, 2023. https://arxiv.org/abs/2305.14325
- [^liang2024]: Liang, He, Jiao, Wang, Wang, Wang, Yang, Shi, Tu. *Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate.* EMNLP 2024. arXiv:2305.19118. https://arxiv.org/abs/2305.19118
- [^huang2024]: Huang, Chen, Mishra, Zheng, Yu, Song, Zhou. *Large Language Models Cannot Self-Correct Reasoning Yet.* ICLR 2024. arXiv:2310.01798. https://arxiv.org/abs/2310.01798
- [^verga2024]: Verga, Hofstätter, Althammer, Su, Piktus, Arkhangorodsky, Xu, White, Lewis. *Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models.* arXiv:2404.18796, 2024. https://arxiv.org/abs/2404.18796
- [^zheng2023]: Zheng, Chiang, Sheng, et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023 D&B. arXiv:2306.05685. https://arxiv.org/abs/2306.05685
- [^brown2024]: Brown, Juravsky, Ehrlich, Clark, Le, Ré, Mirhoseini. *Large Language Monkeys: Scaling Inference Compute with Repeated Sampling.* arXiv:2407.21787, 2024. https://arxiv.org/abs/2407.21787
- [^madaan2023]: Madaan, Tandon, Gupta, et al. *Self-Refine: Iterative Refinement with Self-Feedback.* NeurIPS 2023. arXiv:2303.17651. https://arxiv.org/abs/2303.17651
- [^wang2023]: Wang, Wei, Schuurmans, Le, Chi, Narang, Chowdhery, Zhou. *Self-Consistency Improves Chain of Thought Reasoning in Language Models.* ICLR 2023. arXiv:2203.11171. https://arxiv.org/abs/2203.11171
- [^hong2024]: Hong, Zhuge, Chen, et al. *MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework.* ICLR 2024. arXiv:2308.00352. https://arxiv.org/abs/2308.00352
- [^speckit2025]: Delimarsky, D. *Spec-driven development with AI: Get started with a new open source toolkit.* The GitHub Blog, Sep 2, 2025. https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/
