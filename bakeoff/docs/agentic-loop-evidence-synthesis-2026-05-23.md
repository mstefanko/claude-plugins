# Agentic Loop Evidence Synthesis - 2026-05-23

Status: evidence synthesis for Bakeoff maintainers

Scope: this document merges the 2026 agentic loop, code-review, competitive
build, escalation, and dogfood-run evidence already present in the repository.
It does not add new external citations. URLs named below are already cited in
the source reports or run artifacts.

Primary local inputs:

- `docs/agentic-code-review-2026-report.md`
- `docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md`
- `runs/2026-05-23-0313` (`agentic-code-reviews-2026`, compare)
- `runs/2026-05-23-e476` (Gemini dispute escalation of `2026-05-23-0313`)
- `runs/2026-05-23-97e7` (`agentic-loops-2026-research`, gather)
- `docs/competitive-builds-evidence-2026-05-18.md`
- `docs/review-findings-evidence-and-competitive.md`
- Current-architecture cross-checks: `docs/research-basis.md`,
  `docs/work-orders.md`, `docs/cli-reference.md`, `README.md`,
  `skills/bakeoff-run/SKILL.md`

## 1. Executive Summary

The evidence-backed 2026 loop Bakeoff should converge toward is a bounded,
human-led, artifact-first loop:

```text
human scopes work -> agent(s) research/plan -> human approves material scope
-> two independent providers implement/review/research in isolated runs
-> objective gates, metrics, triage, or swapped judging decide what they can
-> explicit third-provider escalation only for risk, disputes, or uncertainty
-> human reviews residual risk before merge/apply/deploy
```

Across the reports and dogfood runs, the strongest agreement is not "more
agents everywhere." It is "independent evidence under a narrow contract, then a
small selector." Bakeoff's current thin design is aligned with that: exactly two
providers for normal work orders, one judge or verifier path, replayable
artifacts, no automatic patch application, and post-run escalation as a separate
run (`docs/research-basis.md`; `docs/work-orders.md`; `README.md`;
`runs/2026-05-23-0313`; `runs/2026-05-23-97e7`).

For code review, the best-supported default is: same scoped diff or branch, two
independent reviewers, union/dedupe, automatic triage, and human ownership of
the final decision. Cross-model review is best supported for high-risk,
merge-critical, security, migration, data-loss, concurrency, public API, and
large semantic-refactor work. Single-model review remains appropriate for fast
routine feedback. Same-family multi-lens review is a useful middle tier when
the lenses are concrete or the organization is constrained to one vendor, but
it is weaker against shared model-family blind spots
(`docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-0313`;
`runs/2026-05-23-e476`).

For build mode, the evidence says selection quality is the bottleneck. Bakeoff
should keep requiring shared gate verifiers, use metrics only when the work
order defines stable measurements, and call an LLM judge only when execution
evidence is inconclusive. Judge-only selection should be visibly degraded
confidence, not an equal peer of verifier-based selection
(`docs/competitive-builds-evidence-2026-05-18.md`; `docs/research-basis.md`;
`README.md`; `runs/2026-05-23-97e7`).

The main product posture should stay conservative: keep the normal path small,
make escalation legible, and resist hidden synthesis. The evidence supports
tightening code-review `witness` into an advisory adversarial audit of the
source report, but not adding a fourth public `adversarial` mode
(`docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md`;
`runs/2026-05-23-e476`; `docs/work-orders.md`).

## 2. Areas Of Multi-Report Agreement

| Area of agreement | Synthesis | Supporting sources / run IDs |
| --- | --- | --- |
| Keep the default loop small and auditable | Normal Bakeoff work should remain two providers plus one selector path. Third providers belong in explicit escalation, not the base schema. | `docs/agentic-code-review-2026-report.md`; `docs/research-basis.md`; `docs/work-orders.md`; `README.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-97e7` |
| Independent attempts beat self-approval | A writer/model checking its own work is useful as preflight, but not as the final gate. Fresh context and external feedback matter. | `docs/agentic-code-review-2026-report.md`; `docs/review-findings-evidence-and-competitive.md` citing Huang 2024 and Liang 2024; `runs/2026-05-23-97e7` F-010/F-021 |
| Human ownership remains required | AI review produces candidate findings and evidence. Humans still own scope, risk, merge, and deployment decisions. | `docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-97e7` F-043/F-045/F-050; `README.md`; `docs/work-orders.md` |
| Cross-model review is strongest for high-risk work | Different model families are the best-supported practical way to reduce shared blind spots, especially for high-stakes or security-sensitive review. | `docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-e476`; `docs/review-findings-evidence-and-competitive.md`; `runs/2026-05-23-97e7` F-011 |
| Same-family multi-lens is selective, not useless | Concrete lenses can improve coverage and fit single-vendor constraints, but do not provide the same family-diversity benefit as cross-model review. | `docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-0313` F-005/F-010; `runs/2026-05-23-e476` D-003/D-010; `runs/2026-05-23-97e7` F-005 |
| Execution evidence should outrank judge taste for code | For build tasks, gate and metric verifiers are more reliable selectors than LLM preference. Judges should break ties or handle written artifacts, not replace executable evidence. | `docs/competitive-builds-evidence-2026-05-18.md`; `docs/research-basis.md`; `docs/work-orders.md`; `README.md`; `runs/2026-05-23-97e7` F-031 |
| Green tests help but are not proof | Tests and gates can eliminate bad candidates, but public SWE-bench-style evidence shows passing tests can still overstate correctness. | `docs/competitive-builds-evidence-2026-05-18.md`; `docs/research-basis.md`; `runs/2026-05-23-97e7` F-025/F-031; `README.md` |
| LLM judges are useful but biased | Position bias, verbosity bias, self-enhancement, and family convergence are recurring risks. Position-swapped A/B and B/A judging is necessary but not sufficient for all bias classes. | `docs/competitive-builds-evidence-2026-05-18.md`; `docs/review-findings-evidence-and-competitive.md`; `docs/research-basis.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-e476`; `runs/2026-05-23-97e7` F-009/F-030 |
| Multi-agent benefit is task-shaped | Parallel breadth helps broad search, research, independent review, and candidate generation. It can degrade sequential tasks or tasks requiring shared context. | `docs/research-basis.md`; `docs/competitive-builds-evidence-2026-05-18.md`; `runs/2026-05-23-97e7` F-034/F-040/F-041/F-042/F-053/F-054 |
| Structured artifacts beat hidden chat state | The durable ledger, work order, report, decision, provider output, triage, and verifier artifacts are part of the value proposition. | `README.md`; `docs/work-orders.md`; `docs/cli-reference.md`; `docs/research-basis.md`; `docs/review-findings-evidence-and-competitive.md`; `runs/2026-05-23-97e7` F-024/F-026 |
| Escalation should remain post-run and advisory where appropriate | `independent`, `witness`, and `dispute` cover distinct follow-up needs. `witness` and `dispute` should not mutate the source run or replace its winner. | `docs/agentic-code-review-2026-report.md`; `docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md`; `docs/work-orders.md`; `docs/cli-reference.md`; `runs/2026-05-23-e476` |
| Do not auto-synthesize patches | Current Bakeoff should hand off selected provider patches and evidence. Combining or rewriting patches creates a derived change that needs fresh verification. | `docs/research-basis.md`; `README.md`; `docs/competitive-builds-evidence-2026-05-18.md`; `runs/2026-05-23-97e7` F-051/F-052 |

## 3. Contradictions And Tensions

| Tension | Evidence on side A | Evidence on side B | Why both may be conditionally true |
| --- | --- | --- | --- |
| Historical "heavy Bakeoff" vs current thin Bakeoff | `docs/review-findings-evidence-and-competitive.md` describes an older heavier direction: beads, multi-phase chains, synthesis roles, and adversarial pipelines. | `docs/research-basis.md` and `README.md` state the current checkout is a small pairwise artifact-ledger harness with no beads coordination, no spec-review -> code-review -> codex-review chain, and no patch synthesis. | The older memo is useful for background and citation inventory, but current architecture docs are the source of truth for product decisions. |
| Multi-agent systems improve performance vs single-agent systems can win under matched budgets | Anthropic's multi-agent research evidence in `runs/2026-05-23-97e7` F-034/F-039 reports strong breadth-first research gains, and local review/build docs support independent attempts. | `runs/2026-05-23-97e7` F-041/F-053 cites a 2026 study where single-agent systems outperformed multi-agent systems under matched thinking-token budgets. | Multi-agent wins are most plausible when extra breadth, independent search, or diverse failure modes matter. Single-agent loops can win when context must remain unified or when extra agents mostly add compute and coordination overhead. |
| Cross-model as "default" vs cross-model as "selective" | `runs/2026-05-23-0313` found consensus that cross-model review is the right 2026 default for high-stakes or merge-critical code review. `README.md` and `docs/work-orders.md` default generated work orders to Claude + Codex. | `docs/agentic-code-review-2026-report.md`, `docs/competitive-builds-evidence-2026-05-18.md`, and `runs/2026-05-23-e476` emphasize cost, latency, and orchestration complexity. | Bakeoff's ordinary two-provider default is already cross-model when Claude + Codex are available. The selective part is escalation beyond two providers and use on every routine diff. |
| Same-family multi-lens is prompt theater vs useful middle tier | One provider in `runs/2026-05-23-0313` argued same-family lenses cannot cover family-level blind spots. | The other provider and `runs/2026-05-23-e476` D-003/D-010 treat same-family multi-lens as valid for explicit coverage requests, refactors, and single-vendor constraints. | Lenses help direct attention to known risk classes. They are weaker than cross-family diversity for unknown blind spots, but still valuable when constraints or task shape make cross-model review impractical. |
| Cross-model agreement improves precision vs agreement is not proof | `runs/2026-05-23-0313` records a claim that cross-model consensus can reduce false positives by lowering correlated hallucination risk. | `runs/2026-05-23-e476` D-011 confirms cross-model agreement does not supersede deterministic testing, reproduction, citation checks, and human ownership. | Agreement is probabilistic evidence, not correctness proof. It can prioritize triage but should not become the merge gate by itself. |
| Position swap mitigates judge bias vs judge convergence bias remains | `docs/competitive-builds-evidence-2026-05-18.md`, `docs/research-basis.md`, and `runs/2026-05-23-97e7` F-030 support A/B plus B/A swaps for position bias. | `runs/2026-05-23-e476` D-002/D-006 confirms the local work order used a Claude judge over a panel including Claude, making same-family judge convergence a structural risk with no locally verified production solution. | Position swaps address ordering bias. They do not fully address model-family affinity or judge-family convergence. |
| Execution gates should decide vs green tests can be misleading | `docs/competitive-builds-evidence-2026-05-18.md` and `runs/2026-05-23-97e7` F-031 support execution-based selection over judge-only selection. | The same competitive-build memo and `runs/2026-05-23-97e7` F-025 cite evidence that passing tests can overstate correctness. | Gates are strong negative filters and the best available selector when shared verifiers are meaningful. They remain incomplete unless the tests encode the real behavior. |
| N=2 competitive builds are justified vs full multi-agent orchestration is rejected | `docs/competitive-builds-evidence-2026-05-18.md`, `docs/research-basis.md`, and `runs/2026-05-23-97e7` F-003 support small-N competitive implementation with verifiers. | `docs/research-basis.md` and `runs/2026-05-23-97e7` F-026/F-052 reject full orchestration because coordination, shared state, retries, and synthesis semantics add failure modes. | N=2 is justified when the task has a real comparison axis and verifier evidence. General-purpose agent swarms are a different product with different risks. |
| Synthesis/cherry-picking is a shipped pattern elsewhere vs Bakeoff should not synthesize patches | `docs/review-findings-evidence-and-competitive.md` and `runs/2026-05-23-97e7` F-006 mention a SwarmDaddy code-synthesizer role. | `docs/research-basis.md`, `README.md`, and `docs/competitive-builds-evidence-2026-05-18.md` say current Bakeoff does not synthesize or cherry-pick patches; Pattern 6 is explicitly unverified. | Artifact synthesis may be useful as a separate, verified follow-up in another system. It should not be hidden inside Bakeoff's selection step. |
| "Witness" is the right mode for fighting a report vs "witness" is poor UX naming | `docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md` says `witness` is the correct surface for "fight/audit this report" because `dispute` is narrower and `independent` optimizes recall. | The same v2 plan flags that the word "witness" reads like observation, not adversarial audit. | Keep the runtime mode for v1 to avoid schema churn, but improve routing copy and consider a future rename or alias to `audit`. |

## 4. Evidence Strength Table

| Claim | Strength | Evidence type | Why this rating | Sources |
| --- | --- | --- | --- | --- |
| Normal Bakeoff work orders should stay exactly two providers plus one judge/verifier path. | Strong | Local architecture, local dogfood | Current docs, schema docs, README, and multiple completed dogfood runs all align. | `docs/work-orders.md`; `docs/research-basis.md`; `README.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-97e7` |
| Human review/approval remains required at planning, review, merge, and deploy boundaries. | Strong | Local architecture, vendor pattern, public benchmark | Local workflow requires approval before writing/running; vendor and code-review reports frame AI output as candidate evidence. | `docs/agentic-code-review-2026-report.md`; `docs/work-orders.md`; `README.md`; `runs/2026-05-23-97e7` F-043/F-045/F-050 |
| Self-review is a preflight, not an independent gate. | Strong | Public benchmark, inference, local agreement | Multiple reports cite self-correction failures and converge on fresh-context/external review. | `docs/agentic-code-review-2026-report.md`; `docs/review-findings-evidence-and-competitive.md`; `runs/2026-05-23-97e7` F-010/F-021 |
| For code generation/build tasks, execution evidence should outrank judge-only selection. | Strong | Public benchmark, local architecture | Competitive build docs, research basis, and run artifacts cite CodeT/MBR-EXEC/DOCE and implement gates before judge. | `docs/competitive-builds-evidence-2026-05-18.md`; `docs/research-basis.md`; `docs/work-orders.md`; `runs/2026-05-23-97e7` F-031 |
| LLM judges require bias controls, including position swapping. | Strong | Public benchmark, local dogfood | FairEval/MT-Bench-style evidence appears in multiple reports; `2026-05-23-0313` used swapped pass1/pass2 and found consensus. | `docs/competitive-builds-evidence-2026-05-18.md`; `docs/research-basis.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-97e7` F-030 |
| Cross-model review is best for high-risk and merge-critical review. | Moderate | Public benchmark, vendor pattern, local dogfood, inference | Dogfood consensus supports it, but direct apples-to-apples production PR false-positive benchmarks are missing. | `docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-e476`; `runs/2026-05-23-97e7` F-011 |
| Same-family multi-lens review is a useful selective tier. | Moderate | Local dogfood, inference, implementation plan | Multiple reports agree it can help concrete lenses but is weaker for family-level blind spots. | `docs/agentic-code-review-2026-report.md`; `runs/2026-05-23-0313`; `runs/2026-05-23-e476`; `runs/2026-05-23-97e7` F-005 |
| Code-review `witness` should become an adversarial audit contract. | Moderate | Local implementation analysis, vendor/pattern inference | v2 plan validates current code paths and cites already-present critic/audit patterns; no dogfood of the tightened prompt yet. | `docs/adversarial-code-review-escalation-plan-2026-05-23-v2.md`; `docs/work-orders.md`; `runs/2026-05-23-e476` |
| Multi-agent orchestration is beneficial only when task shape supports it. | Moderate | Public benchmark, vendor pattern, local inference | Evidence is consistent but conditional: parallel research helps, sequential tasks can degrade. | `docs/research-basis.md`; `docs/competitive-builds-evidence-2026-05-18.md`; `runs/2026-05-23-97e7` F-034/F-040/F-041/F-042 |
| 2026 cross-model token cost is negligible for all merge-critical review. | Weak | Vendor pricing pattern, inference | One provider argued this, but the dispute escalation upheld latency/integration/cost as real constraints and no local production cost telemetry exists. | `runs/2026-05-23-0313` provider artifacts; `runs/2026-05-23-e476` D-001/D-004/D-009 |
| Exact false-positive reduction rates for cross-model review on production PRs are known. | Weak | Public benchmark extrapolation | The escalation explicitly left production false-positive rates unresolved. | `runs/2026-05-23-e476` D-005; `runs/2026-05-23-0313` |
| N=2 heterogeneous providers approximate small-N homogeneous best-of-N for SWE-style tasks. | Unverified | Inference from public benchmarks | Local competitive-build evidence marks this as plausible by analogy but not directly proven. | `docs/competitive-builds-evidence-2026-05-18.md`; `runs/2026-05-23-97e7` F-055 |
| Complementary approach constraints improve two-source code synthesis. | Unverified | Internal heuristic | Pattern 6 exists in SwarmDaddy, but local evidence says no public benchmark shows function-level cherry-picking beats selecting a winner. | `docs/competitive-builds-evidence-2026-05-18.md`; `runs/2026-05-23-97e7` F-028/F-051 |
| Production systems have solved judge-convergence bias. | Unverified | Gap | The Gemini escalation explicitly could not verify production solutions from local evidence. | `runs/2026-05-23-e476` D-006 |
| Claude+Codex+Gemini has been directly benchmarked against same-family multi-lens review on the same 2026 PR corpus. | Unverified | Gap | Both the source run and escalation identify this direct comparison as absent. | `runs/2026-05-23-0313`; `runs/2026-05-23-e476` D-012 |

## 5. Implications For Bakeoff Architecture And Options

### Supported Defaults

- Keep normal work orders at exactly two providers and one judge. This is the
  central thin-harness property supported by current docs and dogfood runs.
- Keep generated defaults as Claude + Codex with a Claude judge when available,
  while continuing to permit Gemini and Copilot as optional peers through the
  catalog.
- Keep `gather`, `compare`, and `analyze` as normal research modes with
  mode-specific selectors: structured union for gather, swapped judging for
  compare/analyze, and deterministic fallback when applicable.
- Keep review as `gather` plus `facet.id: "code-review"`: same scope, two
  independent reviews, union/dedupe, automatic triage, and no winning reviewer.
- Keep build mode verifier-first: two isolated patches, protected paths, shared
  gates, optional metrics, and LLM judging only after verifier evidence is
  inconclusive.
- Keep artifacts explicit and replayable: work order, provider prompts/output,
  report, decision, manifest, triage, verifier results, and selected patch
  handoff when there is a canonical build winner.
- Keep the source checkout untouched by default. Applying, combining,
  committing, pushing, opening PRs, or synthesizing patches should require a
  separate explicit user request and fresh verification.
- Keep explicit preview/approval checkpoints before writing work orders,
  launching runs, and spending escalation calls.

### Options That Should Stay Selective

- `independent` escalation: use for unresolved runs, surprising consensus,
  missing recall, or a fresh third answer. It costs one provider plus a judge in
  compare/analyze or union in gather/review.
- `witness` escalation: use for broad audit of the current report, decision,
  judge passes, and triage. For code-review runs, tighten it into an
  adversarial audit of source findings and keep it advisory.
- `dispute` escalation: use for named contested points, ties, unknowns,
  consensus disagreements, and triage gaps. Keep it packet-driven and bounded.
- Multi-lens review: use only when the user explicitly asks for separate
  concrete lenses. Keep the normal limit at 2-3 lenses and keep synthesis as a
  separate follow-up.
- Competitive build: use for tasks with meaningful verifiers or comparison axes
  such as performance, robustness, migrations, refactors, concurrency, or
  partial-test UX changes.
- Parallel split/fanout: use only for clean independent parts with explicit run
  ids. Do not rely on `latest` for concurrent children.
- Cross-model escalation beyond the default pair: reserve for high-risk,
  disputed, surprising, or merge-critical situations where the extra latency,
  cost, and provider complexity are justified.

### Options To De-Emphasize

- Unbounded agent swarms, debate loops, and per-finding fanout as default
  product behavior. The local evidence repeatedly identifies coordination cost
  and fatigue as real failure modes.
- Judge-only code selection when executable verifiers are available. If
  `allow_judge_only` remains, reports should label it degraded confidence.
- Automatic patch synthesis or cherry-picking between providers. Pattern 6 is
  unverified and not part of current Bakeoff's thin contract.
- Auto-apply, auto-commit, auto-push, auto-PR, or PR shepherding inside the
  Bakeoff run. These erase the handoff boundary that makes the tool auditable.
- Large default patches or huge judge contexts. Existing evidence flags
  verbosity and long-context judge weakness; `patch_max_bytes` should remain
  conservative.
- Report.md fallback parsing for witness target selection. The v2 escalation
  plan correctly treats structured triage artifacts as the source when present
  and the full report as background when not.
- Treating single-witness verbal `confidence` as a reliable gate. Confidence
  should not drive automatic action without calibration, family diversity, or
  self-consistency.

## 6. Open Gaps Worth Researching Next

1. Run an internal review benchmark across real target repositories comparing
   single-model, same-family multi-lens, and cross-model review on accepted
   findings, false positives, latency, provider cost, and developer triage time.
2. Measure judge-convergence bias locally by rotating the judge family on the
   same completed provider outputs, especially Claude-judging-Claude+Codex
   cases.
3. Dogfood the v2 code-review `witness` contract: bounded
   `<review_claim_targets>`, missing-control pass, file:line proof obligations,
   and advisory report rendering.
4. Verify `ValidateEscalationWitnessResult` accepts structured objects in
   `material_errors`, `missed_material`, and `triage_concerns`, or decide on the
   v2 per-claim verdict schema.
5. Test whether `--prefer-different-family` or a hard different-family rule for
   witness escalation improves calibration without making provider availability
   brittle.
6. Compare N=2 heterogeneous providers against small-N homogeneous best-of-N on
   SWE-style tasks under equal budget, including verifier strength and wall
   clock.
7. Evaluate whether any code synthesis follow-up can beat "pick the selected
   patch and verify it" without increasing state desync, hidden merge debt, or
   reviewer fatigue.
8. Calibrate metric verifier defaults for performance work. The evidence warns
   that single-run benchmarks are noisy; Bakeoff needs local guidance for
   `min_delta_percent`, `noise_floor_percent`, and `min_runs` by language/tool.
9. Collect production telemetry for Bakeoff runs: task type, provider pair,
   model aliases, wall time, output truncation, judge result, triage class,
   accepted findings, reruns, and post-merge defects.
10. Research current vendor/framework maturity only where it affects a product
    decision: Gemini/Copilot review false-positive rates, Devin-style autonomy,
    Cursor/Jules background-agent workflows, AutoGen GraphFlow/Magentic-One, and
    LangGraph persistence tradeoffs.
11. Build a task-fit rubric that predicts when Bakeoff should warn, draft a
    normal run, draft a build run, suggest multi-lens review, or recommend a
    simpler single-agent command.
12. Decide UX naming for `witness`: keep the internal mode with clearer
    "audit/fight the report" copy, or introduce an `audit` alias before users
    build habits around the older term.
