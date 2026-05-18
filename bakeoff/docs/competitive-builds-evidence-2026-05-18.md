# Competitive Builds — Evidence Memo

Date: 2026-05-18
Companion to: `competitive-builds-implementation-plan-2026-05-18.md`
Scope: Does the plan's "two writers + verifier + judge" pattern match the public evidence on best-of-N / tournament code generation, or is it feature bloat?

## 1. Evidence Summary

### Sampling N candidates helps — selection is the bottleneck

- **AlphaCode** generates millions of programs, then filters with example tests and clusters by execution behavior to submit only ~10. Diversity comes from language, random tags/ratings, and high temperature. The published result depends on *execution-based selection*, not on more samples alone ([Li et al., 2022](https://arxiv.org/abs/2203.07814); [DeepMind PDF](https://storage.googleapis.com/deepmind-media/AlphaCode/competition_level_code_generation_with_alphacode.pdf)).
- **Codex/HumanEval**: 28.8% pass@1 → 70.2% pass@100 *only when an oracle picks the right sample* ([Chen et al., 2021](https://arxiv.org/abs/2107.03374)). The gain collapses without a strong selector.
- **CodeT** (HumanEval pass@1 47% → 65.8%) shows execution-against-generated-tests beats text-preference selection ([Chen et al., 2022](https://arxiv.org/abs/2207.10397)).
- **MBR-EXEC / DOCE** confirm: execution-based selection > execution-unaware selection ([Shi 2022](https://arxiv.org/abs/2204.11454); [Li 2024](https://arxiv.org/abs/2408.13745)).
- **Self-certainty (NeurIPS 2025)** and **Majority-of-the-Bests (2511.18630)** are newer selectors that scale with N but still rely on grouping/agreement, not LLM taste.

Takeaway: candidate generation is cheap signal; **selection quality dominates outcome**.

### N=2 vs N≥3

- AlphaCode-class wins come from N in the thousands; HumanEval saturation curves show pass@N is logarithmic in N for a fixed model (Codex paper, Fig 2). Most gain between N=1 and N≈10; marginal beyond that for one model.
- For *heterogeneous* providers (different model families) the diversity-per-sample is higher, so small N (2-3) captures most of the win. No paper isolates "N=2 heterogeneous vs N=5 homogeneous" for SWE-style tasks, so [UNVERIFIED] N=2 heterogeneous ≈ small-N homogeneous in practice — defensible but not proven.

### LLM judges are biased, and position-swap is the standard mitigation

- MT-Bench / Chatbot Arena: position, verbosity, self-enhancement bias confirmed ([Zheng 2023](https://arxiv.org/abs/2306.05685)).
- FairEval proposes balanced position calibration — exactly the A/B + B/A swap the plan uses ([Wang 2023](https://arxiv.org/abs/2305.17926)).
- "Bias in the Loop" (SE-specific, 2026) audits judges and finds **position bias flips winners; pairwise accuracy ~60%; verbosity and self-enhancement are prompt-sensitive** ([arxiv 2604.16790](https://arxiv.org/html/2604.16790v1)).
- "One Token to Fool LLM-as-a-Judge" ([2507.08794](https://arxiv.org/html/2507.08794v1)): judges are exploitable by trivial surface tokens.

Takeaway: judge-only selection has a ceiling around 60% pairwise accuracy. Use judges as tiebreakers, not primary selectors.

### Tests are a gate, not always a selector

- **SWE-bench plausibility study**: 7.8% of "correct" patches fail developer tests; 29.6% diverge from ground truth; top agent's score drops 78.8% → 62.2% under stronger suites ([Wang 2025, 2503.15223](https://arxiv.org/abs/2503.15223)). Green tests overstate correctness.
- **SWE-ABS**: strengthening 50.2% of instances rejects 19.78% of previously passing patches ([2603.00520](https://arxiv.org/html/2603.00520v1)).
- Reward hacking literature confirms LLMs game verifiers when given the chance ([Lilian Weng, 2024](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/); [LLMs Gaming Verifiers, 2604.15149](https://arxiv.org/html/2604.15149)).

### Multi-agent overhead has a known failure profile

- **MAST taxonomy** (Cemri 2025, [2503.13657](https://arxiv.org/abs/2503.13657)): **79% of multi-agent failures are spec/coordination, not base-model limits**. 14 failure modes across spec ambiguity, role unclarity, missing constraints, verification gaps. Adding agents adds these failure modes.
- **Agentless** ([Xia 2024](https://arxiv.org/abs/2407.01489)) shows a 3-step pipeline (localize → repair → validate) competitive with full agents on SWE-bench Lite — simpler beats orchestration when the verifier is good.

### Diversifying writer prompts ("complementary approach constraints")

- AlphaCode randomizes tags/ratings/language to widen the distribution; this raises pass@k. The mechanism is *distributional* diversity, not "agent A does X, agent B does Y."
- Self-consistency literature ([prompt sampling](https://www.promptingguide.ai/techniques/consistency)) supports temperature/path diversity but **does not test the specific "instruct writer A to use approach X, B to use Y" intervention**.
- swarm-do's Pattern 6 synthesizer ([role-specs/agent-code-synthesizer.md](file:///Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/role-specs/agent-code-synthesizer.md)) prescribes complementary directives, but this is an internal heuristic with no public benchmark backing. Verdict: [UNVERIFIED] for code; plausible by analogy to AlphaCode diversity, not directly evidenced.

## 2. Where the Plan Agrees With Evidence

- **N=2 only, evidence-first selector hierarchy** (plan §Decision, §Decision Policy) — exactly matches CodeT/MBR-EXEC/DOCE: execution > judge.
- **Position-swapped judge** (plan §Build Judge) — matches FairEval and MT-Bench mitigation.
- **Gate vs metric vs advisory verifiers, thresholded metrics with noise floor** (plan §Comparative verifiers) — directly addresses the SWE-bench plausibility gap and benchmark noise.
- **Heterogeneous providers (claude + codex)** — closest cheap analogue to AlphaCode's tag/language diversity.
- **No automatic apply, no PR shepherding, no DAG, no test-writing agent** (plan §Non-Goals) — matches MAST: every extra coordination surface is a new failure mode.
- **Provider-authored tests/benchmarks recorded but not decisive** (plan §Test, Benchmark…) — defends against reward hacking / verifier gaming.

## 3. Where the Plan Disagrees or Lacks Evidence

- **"Complementary approach constraints"** — referenced in swarm-do Pattern 6 but the bakeoff plan itself uses identical worker prompts per provider. Plan does *not* claim diversity prompts; it relies on provider heterogeneity. That's the safer call — the swarm-do Pattern 6 framing is the speculative bit, not the bakeoff plan. [UNVERIFIED] whether enforced diverse prompts beat identical prompts for N=2 heterogeneous.
- **`allow_judge_only` mode** (plan §Work Order Shape) — judge-only pairwise accuracy is ~60% per "Bias in the Loop." The plan permits this but should label it as **degraded confidence**, not just an option flag. Plan doesn't quantify expected error rate.
- **"Performance-sensitive changes" as a primary use case** (plan §Research Basis) — Mercury/COFFE cited but the plan stops short of stating that **single-run benchmarks are noisy enough that `min_delta_percent: 10` may be too low** for sub-second microbenchmarks. The threshold defaults are not evidence-backed.
- **Pattern 6 synthesis (cherry-picking from two writers)** — exists in swarm-do but **not in this plan**, and rightly so. No public evidence that two-source synthesis at function granularity outperforms picking the winner. Synthesis is a known failure-mode amplifier (state desync, MAST cat 2).

## 4. Practical Recommendations

**Defaults that match evidence**:
- N=2 heterogeneous (claude + codex) — keep.
- Gate verifier required by default — keep.
- Judge only when gate ties and metric inconclusive — keep.
- Position swap mandatory — keep.

**Enable competitive builds when**:
- Task has a real comparison axis (latency, allocations, query count, bundle size, API surface)
- Existing tests are weak or known-incomplete (SWE-bench-style under-specification)
- Migration / refactor where "both work, one is better"
- Concurrency, race, or robustness work where stress/fuzz can separate

**Skip competitive builds when**:
- Mechanical edits, formatters, single-file fixes
- Strong existing regression test already exists (gate decides without N=2)
- Task is judge-only with no verifier — accuracy ceiling ~60%, not worth 2x cost

**Cost rule of thumb**: bakeoff is 2x provider cost + judge cost. Worth it only when expected error reduction > 2x marginal cost. For tasks where a single-shot agent succeeds >80% of the time, N=2 is wasted spend.

## 5. Bloat Assessment

The plan is **already conservative**. Most of the candidate-bloat items the user worried about are explicitly listed as non-goals (DAGs, beads integration, auto-apply, debate loops, test-writing agent, more providers, recursive decomposition). Cuts to consider:

- **`allow_judge_only` mode** — evidence says judge-only is ~60% accurate. Either drop, or rename to make degraded confidence loud in the report. Currently it reads as a peer of gate/metric.
- **`advisory` verifier kind** — three kinds (gate/metric/advisory) when only two are decisive. Advisory adds ledger surface for evidence that the judge could just read from logs. Consider folding into "judge inputs" without a verifier slot.
- **`comparison_goal` free-text field** (plan §How to make work testable) — risk of becoming a judge-priming axis the LLM optimizes for verbosely. Either require it to map to a declared metric, or label it as judge-only context.
- **`patch_max_bytes` at 500KB default with 5MB cap** — large patches dilute judge attention (verbosity bias). 500KB is generous; consider 100KB default. Evidence: judges degrade on long contexts.
- **Phase 6 dogfood scope** — four manual dogfoods listed; the "deliberately ambiguous, `allow_judge_only`" one is testing a mode the evidence suggests should be deprecated. Drop or fold into a single "judge-only ablation" study.

**Do not cut**:
- Baseline verifier run, dirty-base rejection, submodule rejection, patch capture via staged-index diff — all guardrails against MAST-class spec/state bugs.
- Position swap, provider-authored test labelling, manifest verification — direct mitigations for documented bias / hacking modes.
- `--keep-worktrees` debug switch — needed when verifier evidence is degraded and a human must inspect.

## Sources

- Best-of-N / sampling: [Codex/HumanEval (Chen 2021)](https://arxiv.org/abs/2107.03374); [AlphaCode (Li 2022)](https://arxiv.org/abs/2203.07814); [Self-Certainty BoN (NeurIPS 2025)](https://arxiv.org/abs/2502.18581); [Majority-of-the-Bests (2511.18630)](https://arxiv.org/abs/2511.18630)
- Execution-based selection: [CodeT (Chen 2022)](https://arxiv.org/abs/2207.10397); [MBR-EXEC (Shi 2022)](https://arxiv.org/abs/2204.11454); [DOCE (Li 2024)](https://arxiv.org/abs/2408.13745)
- Judge bias: [MT-Bench (Zheng 2023)](https://arxiv.org/abs/2306.05685); [FairEval (Wang 2023)](https://arxiv.org/abs/2305.17926); [Bias in the Loop SE (2604.16790)](https://arxiv.org/html/2604.16790v1); [One Token to Fool (2507.08794)](https://arxiv.org/html/2507.08794v1)
- Benchmark weakness: [SWE-bench plausibility (Wang 2025, 2503.15223)](https://arxiv.org/abs/2503.15223); [SWE-ABS (2603.00520)](https://arxiv.org/html/2603.00520v1)
- Multi-agent failures: [MAST (Cemri 2025, 2503.13657)](https://arxiv.org/abs/2503.13657); [Agentless (Xia 2024)](https://arxiv.org/abs/2407.01489); [SWE-agent (Yang 2024)](https://arxiv.org/abs/2405.15793)
- Reward hacking: [Lil'Log 2024](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/); [LLMs Gaming Verifiers (2604.15149)](https://arxiv.org/html/2604.15149)
- Internal: `swarm-do/role-specs/agent-writer-judge.md` (Pattern 5); `swarm-do/role-specs/agent-code-synthesizer.md` (Pattern 6); `swarm-do/py/swarm_do/pipeline/recipes.py:198,428,700` (competitive routing); claude-mem obs #12990, #12991, #12992 (existing competitive judging capability)
