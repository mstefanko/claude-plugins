# Paper-Grade Experiment Analysis Implementation Plan (2026-06-05)

Status: proposed implementation plan, scope-cut after soundness and bloat
review. This file is intentionally a plan, not a behavior change.

## Short Version

Bakeoff already preserves a strong per-run ledger: the work order, prompts,
provider outputs, judge artifacts, decision, report, metadata, manifest, and
fingerprints. That is enough for exploratory analysis of individual runs.

The missing layer for paper-grade claims is explicit comparability across runs.
Bakeoff should support that by emitting stable per-run experiment labels and a
documented manifest/data contract. It should not become the scheduler,
statistics engine, evaluator-calibration harness, or trace-normalization system
for a full research platform.

Scope-cut decision:

1. **Keep in Bakeoff:** trimmed experiment metadata, projection into
   `meta.json`, `manifest.json`, `ls --json`, summary JSON, a stable manifest
   contract, and one examples script showing repetition with explicit run ids.
2. **Move outside Bakeoff:** scheduling, matrices, parallel execution,
   resume/retry policy, parent experiment bookkeeping, cross-run exports,
   statistics, evaluator calibration, human-label workflows, and paper tables.
3. **Defer until proven demand:** intentional single-agent baseline execution,
   evaluator-pack plumbing, and deeper provider trace capture.

The implementation should keep current flat run ledgers intact. Every child run
should remain an ordinary `runs/<run-id>/` directory so `show`, `ls`,
`runs verify`, build artifacts, triage, and existing manifests continue to
work. Experiments should live around Bakeoff; Bakeoff should remain the
auditable per-run evidence engine.

## Review Decision

Two plan-review passes drove this scope cut:

- [Soundness and implementation clarity](plan-review-soundness-and-clarity-2026-06-05.md)
  found the architecture direction sound, but only Phase 1 was close to
  execution-ready. Later scheduler/statistics/evaluator/trace phases had
  unresolved design choices.
- [Bloat risk](plan-review-bloat-risk-2026-06-05.md) found that scheduler,
  retries, shared state, aggregation, and calibration would erode Bakeoff's
  existing thin-product boundary.

The final decision is: **let the bloat review set the product boundary, and let
the soundness review govern the surviving narrow slice.**

## Research Basis

The recommendations below come from six focused research passes over Bakeoff
and external benchmark practice.

Experiment tracking systems separate experiment/task identity from individual
runs. MLflow models an experiment as a grouping of runs, with each run carrying
parameters, metrics, and artifacts: <https://www.mlflow.org/docs/latest/ml/tracking>.
Weights & Biases groups runs by shared purpose and run properties such as job
type: <https://docs.wandb.ai/models/runs/grouping>. OpenML separates task
identity from run identity, so comparability is anchored by a task definition
while runs record setups, tags, evaluations, and traces:
<https://docs.openml.org/concepts/tasks/> and
<https://docs.openml.org/reference/runs/>.

Repeated sampling is normal in agent and code-generation benchmarks. HumanEval
and the Codex paper use JSONL samples and `pass@k` estimates for repeated code
generation attempts: <https://github.com/openai/human-eval> and
<https://arxiv.org/abs/2107.03374>. Tau-bench introduces `pass^k` to measure
whether an agent succeeds consistently across repeated trials, not merely once:
<https://arxiv.org/abs/2406.12045>. Anthropic's agent-evals guidance frames
evaluation in terms of task, trial, harness, transcript, and outcome, and
recommends multiple trials plus isolated clean environments:
<https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>.
SWE-bench harnesses use run-id-scoped logs, per-instance reports, timeouts,
completed-run skipping, and parallel execution:
<https://www.swebench.com/SWE-bench/api/harness/>.

Multi-agent and debate papers compare multi-agent methods against explicit
single-agent or non-debate baselines on the same task set, rather than treating
a failed ensemble member as a baseline. Relevant examples include Multiagent
Debate (<https://arxiv.org/abs/2305.14325>), ChatEval
(<https://arxiv.org/abs/2308.07201>), AgentBench
(<https://arxiv.org/abs/2308.03688> and
<https://github.com/THUDM/AgentBench>), SWE-bench
(<https://www.swebench.com/>), and Anthropic's multi-agent research system
writeup (<https://www.anthropic.com/engineering/multi-agent-research-system>).

LLM-as-judge evidence should be versioned and calibrated. OpenAI evaluation
guidance recommends clear rubrics, pairwise or pass/fail grading, bias
controls, and validating LLM judges against human labels before scaling:
<https://developers.openai.com/api/docs/guides/evaluation-best-practices#llm-as-a-judge-and-model-graders>.
GDPval uses blind expert graders and detailed rubrics while treating automated
grading as not yet a full expert replacement:
<https://openai.com/index/gdpval/>. MT-Bench/Chatbot Arena, FairEval, G-Eval,
and PoLL document position, verbosity, self-enhancement, calibration, and
multi-judge concerns: <https://arxiv.org/abs/2306.05685>,
<https://arxiv.org/abs/2305.17926>, <https://arxiv.org/abs/2303.16634>, and
<https://arxiv.org/abs/2404.18796>. Anthropic recommends uncertainty reporting,
paired differences, confidence intervals, and power analysis for model evals:
<https://www.anthropic.com/research/statistical-approach-to-model-evals>.

External analysis should start with transparent rows and conservative aggregate
statistics. Bakeoff should provide stable inputs for that work, not own the
statistics. Chatbot Arena moved from online Elo to Bradley-Terry MLE with
bootstrap confidence intervals for pairwise model comparison:
<https://www.lmsys.org/blog/2023-12-07-leaderboard/>. HELM emphasizes
multi-metric transparent reporting:
<https://github.com/stanford-crfm/helm>. The EleutherAI
`lm-evaluation-harness` supports output paths, logged samples, integrity
checks, seeds, and bootstrap stderr controls:
<https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/interface.md>.
Failure taxonomies should remain grounded in auditable evidence; AgentRx is a
useful precedent for trajectory-grounded failure categories:
<https://www.microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework/>.

Future trace capture, if needed, should follow structured observability
standards where provider backends expose them. This is intentionally out of
scope for the lean Bakeoff-core plan because it creates per-backend maintenance
across moving CLIs. OpenTelemetry GenAI conventions define spans for model
calls, tools, agents, workflows, tokens, and errors, while treating prompts and
tool contents as sensitive:
<https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/> and
<https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/>.
OpenAI Agents SDK tracing records LLM generations, tool calls, guardrails,
handoffs, custom spans, IDs, parentage, timestamps, metadata, and sensitive-data
controls: <https://openai.github.io/openai-agents-python/tracing/>. Codex CLI
documents `codex exec --json` as newline-delimited JSON events:
<https://developers.openai.com/codex/cli/reference>. Claude Code documents
`stream-json` output and OpenTelemetry traces:
<https://code.claude.com/docs/en/cli-reference> and
<https://code.claude.com/docs/en/monitoring-usage>. Gemini CLI documents
OpenTelemetry telemetry for tool calls, file operations, API requests,
responses, token counts, and truncation events:
<https://google-gemini.github.io/gemini-cli/docs/cli/telemetry.html>.

## Current Bakeoff Behavior

The current codebase already has several durable primitives that should be
reused.

- Work orders define the input contract in `internal/workorder/workorder.go`.
  They currently require exactly two providers and one judge for normal work
  orders.
- Research and build run creation write `work-order.json`, provider artifacts,
  `decision.json`, `report.md`, `meta.json`, and `manifest.json` in
  `internal/commands/researchcmd/run.go` and `internal/commands/buildcmd/`.
- Provider artifacts already include `prompt.txt`, `stdout.txt`, `stderr.txt`,
  `status.json`, `final.json` or `failure.json`, and sometimes
  `last-message.txt`.
- Judge artifacts already preserve judge prompts, status, stdout/stderr, and
  result JSON. Compare/analyze/build use swapped A/B passes where appropriate.
- `meta.json` is written from `internal/artifact/artifact.go` and already
  records run type, facet, resolved models, timestamps, input hashes, provider
  status, and extra fields.
- `manifest.json` is written from `internal/manifest/manifest.go` and already
  hoists list-friendly fields such as run id, type, facet, decision, providers,
  judge, triage state, artifacts, fingerprints, rerun/escalation fields, and
  telemetry.
- `bakeoff ls`, `show`, `bundle`, `rerun`, `triage`, and `runs verify` already
  operate over run ledgers. New experiment behavior should not break these
  surfaces.

Important current limitations:

- There is no typed experiment or condition metadata.
- There is no parent experiment artifact.
- Split and multi-lens workflows are plugin fanout into separate normal runs,
  not work-order schema features.
- `single_provider_only` means a two-provider run degraded after one provider
  failed; it is not an intentional single-agent baseline.
- Judge rubrics live inside prompt fixtures rather than versioned evaluator
  artifacts.
- `ls --json` provides compact run rows, not analysis-grade run/provider/
  comparison/aggregate exports.
- Process stdout/stderr are captured, but provider-internal tool/action/state
  events are only visible when the backend emits them.

## Product Rule

Paper-grade analysis needs explicit comparability.

A run should be analyzable later only when Bakeoff and any external study
harness can jointly answer:

- What task was being evaluated?
- Which condition was this run part of?
- Which provider(s), model strings, scopes, budgets, prompt variants, and
  external evaluator or trace references were used?
- Was this a pairwise bakeoff, multi-lens child, split child, rerun,
  escalation, or externally recorded baseline?
- Which repetition and slot did this run occupy?
- Which artifacts and external evaluator outputs support the outcome?
- Which limitations affected the run, such as truncation, provider failure,
  missing structured traces, no cost data, or no human calibration?

## Recommended Architecture

The revised architecture has two layers: a small Bakeoff-core data spine and an
external experiment harness.

### Keep In Bakeoff: Experiment Labels

Add optional top-level `experiment` metadata to work orders. This object is
closed and deliberately small.

```json
{
  "experiment": {
    "id": "review-auth",
    "task_id": "auth-review",
    "condition_id": "pairwise.security",
    "run_kind": "pairwise",
    "repetition_index": 1,
    "slot_id": "security",
    "slot_attempt": 1
  }
}
```

Required fields when `experiment` is present:

- `id`
- `task_id`
- `condition_id`
- `run_kind`
- `repetition_index`

Optional fields:

- `slot_id`
- `slot_attempt`

Validation:

- Use the existing run/work-order slug shape,
  `^[A-Za-z0-9][A-Za-z0-9._-]*$`, for id-like fields.
- `repetition_index` is 1-based.
- `slot_attempt` is 1-based and only meaningful when `slot_id` is present.
- Unknown keys are rejected in this object so the initial contract stays small.
- `run_kind` is one of `pairwise`, `multi_lens_child`, `split_child`, `rerun`,
  or `ad_hoc`.
- `single_agent_baseline` is reserved but not executable in this phase.

Projection:

- Copy the full `experiment` object into `meta.json`.
- Hoist `experiment_id`, `task_id`, `condition_id`, `run_kind`,
  `repetition_index`, `slot_id`, and `slot_attempt` into `manifest.json`.
- Add the same fields to `ls --json`.
- Add `bakeoff ls --experiment ID` and `bakeoff ls --condition ID`.
- Add an optional `experiment` object to both research and build JSON summaries.

This is metadata only. It does not change provider count, judge semantics,
prompt construction, worktree behavior, retry behavior, or `latest`.

### Keep In Bakeoff: Stable Manifest Contract

Document a stable, nullable manifest contract for external scripts and
notebooks. Bakeoff's responsibility is to emit durable per-run evidence; it
does not need to compute paper statistics.

Stable fields should include:

- `run_id`
- `type`
- `facet_id`
- `started_at`
- `finished_at`
- `decision_kind`
- `canonical_winner`
- `judge_ran`
- `judge_attempted`
- `judge_completed`
- `providers`
- `judge`
- `triage`
- `artifacts`
- `artifact_fingerprints`
- `telemetry`
- `experiment_id`
- `task_id`
- `condition_id`
- `run_kind`
- `repetition_index`
- `slot_id`
- `slot_attempt`

Fields added for experiments must be nullable or omitted when absent so old
runs remain readable.

### Keep In Bakeoff: Repetition Example

Add one example script under `examples/` showing external repetition over
ordinary Bakeoff runs. The script should demonstrate:

- deterministic run ids,
- generated work orders with trimmed `experiment` metadata,
- `bakeoff validate`,
- `bakeoff research` or `bakeoff build` with explicit `--run-id`,
- manifest-presence skipping for resume,
- `bakeoff runs verify --json`,
- retry by creating a new attempt run id, never by using `--force` on counted
  evidence.

This script is instructional. It should not become a hidden scheduler contract.

### Move Out: Experiment Harness

Scheduling, matrix expansion, parallel execution, resume state, retry policy,
parent experiment manifests, and aggregate summaries belong outside Bakeoff for
now. An external harness can:

1. Define a study plan file with tasks, conditions, repetitions, run-id
   templates, work-order templates, and rubric hashes.
2. Generate ordinary work orders that include the trimmed `experiment` block.
3. Invoke Bakeoff with explicit run ids.
4. Skip completed slots by checking `runs/<run-id>/manifest.json`.
5. Create new attempt ids for retries.
6. Analyze results from `manifest.json`, `meta.json`, `decision.json`, provider
   artifacts, verifier artifacts, and triage artifacts.

This keeps Bakeoff small while still enabling serious experiments.

### Move Out: Analysis And Statistics

Cross-run exports, CSV generation, bootstrap confidence intervals, Wilson
intervals, Bradley-Terry/Elo, `pass@k`, `pass^k`, cost-quality curves, and
paper tables should live in notebooks or external scripts. Bakeoff should
document the stable input data; it should not own the statistical method.

This is especially important because:

- research/analyze/compare wins are LLM-judge preference evidence, not objective
  task success;
- `pass@k` is only meaningful when a condition has objective success labels,
  such as verifier-gated build outcomes;
- repeated runs are often clustered by task or source run, so naive bootstrap
  over run rows can overstate confidence;
- statistics methodology should be easy to revise without changing the run
  engine.

### Move Out: Evaluator Calibration

Rubrics, human labels, judge-human agreement, confusion matrices, and
calibration reports are valid research-methodology tools. They do not belong in
Bakeoff core yet.

External tools can store rubric files and calibration datasets, then reference
their hashes from experiment metadata or work-order background. A future small
core addition may copy a simple `evaluator_ref` string or hash into
`meta.json`/`manifest.json`, but this plan does not add evaluator pack loading,
prompt injection, `bakeoff evaluator validate`, or calibration commands.

### Defer: Single-Agent Baseline Execution

Intentional single-agent baselines are a real gap: `single_provider_only` means
a degraded two-provider run, not a designed baseline. But executing baselines
inside Bakeoff requires changes to provider-count validation, judge optionality,
prompt wording, decision kinds, report language, summaries, manifests, and
build patch semantics.

Do not add validation-only baseline metadata that cannot execute. Either defer
single-agent baseline entirely, or implement a complete minimal baseline mode
in a separate plan after a real experiment requires it.

### Defer: Trace Depth

Structured traces are useful only when provider CLIs expose stable structured
events. A normalized trace subsystem would require ongoing backend-specific
maintenance for Codex, Claude, Gemini, Copilot, and any future provider.

For now, Bakeoff should rely on current process-level artifacts:
`prompt.txt`, `stdout.txt`, `stderr.txt`, `status.json`, `final.json`,
`failure.json`, `last-message.txt` when supported, build patch artifacts, and
verifier outputs. External wrappers can capture provider-specific traces and
record their hashes in experiment metadata if a study needs them.

## Implementation Phases

### Phase 1: Metadata-Only Experiment Labels

Files:

- `internal/workorder/workorder.go`
- `internal/workorder/workorder_test.go`
- `internal/artifact/artifact.go`
- `internal/manifest/manifest.go`
- `internal/manifest/manifest_test.go`
- `internal/commands/lscmd/ls.go`
- `internal/commands/lscmd/ls_test.go`
- `internal/summary/summary.go`
- `docs/work-orders.md`
- `docs/cli-reference.md`
- `skills/bakeoff-run/SKILL.md`

Changes:

1. Add `ExperimentSpec`.
2. Reject unknown keys in `experiment`.
3. Validate id-like fields with the existing slug shape.
4. Validate `run_kind` against the lean enum.
5. Validate 1-based `repetition_index` and `slot_attempt`.
6. Reserve `single_agent_baseline` but do not allow it as an executable
   `run_kind` yet.
7. Copy the full experiment object into `meta.json`.
8. Hoist selected fields into `manifest.json`.
9. Add `ls --experiment` and `ls --condition`.
10. Add optional experiment fields to research and build JSON summaries.
11. Document that this is labeling metadata, not orchestration.

Acceptance tests:

- Valid experiment metadata passes validation.
- Bad slugs/enums fail validation.
- Unknown `experiment` keys fail validation.
- Zero or negative indexes fail validation.
- Existing work orders without `experiment` remain unchanged.
- `manifest.json` includes experiment fields when present.
- `ls --json --experiment ID` filters and projects fields correctly.
- `ls --json --condition ID` filters and projects fields correctly.
- Human `ls` output remains compact for non-experiment runs.

### Phase 2: Stable Data Contract Documentation

Files:

- `docs/artifacts-and-ledger.md`
- `docs/cli-reference.md`
- `docs/work-orders.md`
- `README.md`

Changes:

1. Document the stable manifest fields external tools can depend on.
2. Mark experiment fields as nullable/omitted when absent.
3. Explain that Bakeoff emits per-run evidence; external tools own
   orchestration and analysis.
4. Explain that LLM judge preference, build verifier success, triage-confirmed
   findings, and human labels are different evidence types.

Acceptance tests:

- Docs name the new fields consistently.
- Docs do not promise a scheduler, parent experiment directory, or statistics
  command.
- The README still presents Bakeoff as a small pairwise evidence harness.

### Phase 3: Repetition Example Script

Files:

- `examples/README.md`
- new `examples/repetition-loop.sh` or `examples/repetition-loop.py`
- optional fixture work orders under `examples/`

Changes:

1. Show how to run repeated trials externally with explicit run ids.
2. Generate or reference work orders with trimmed `experiment` metadata.
3. Skip completed runs by checking `runs/<run-id>/manifest.json`.
4. Verify completed runs with `bakeoff runs verify --json`.
5. Show retry as a new attempt id, not `--force`.
6. State that the script is an example, not a stable orchestration API.

Acceptance tests:

- The script has shellcheck-like or unit coverage if practical.
- The script can run against fake providers or documented dry fixtures.
- The script never uses `--force` for counted evidence.

### Explicitly Out Of Scope For This Plan

The following remain outside Bakeoff core:

- `bakeoff experiment run`
- provider/lens matrix expansion
- `--parallel` scheduling
- `--resume`
- retry policies and counted-evidence selection
- parent `runs/experiments/<id>/experiment.json`
- `bakeoff analysis export`
- CSV/Markdown/statistical report generation
- bootstrap/Wilson/Bradley-Terry/pass@k/pass^k calculations
- evaluator pack loading, prompt injection, validation, or calibration
- human-label schemas and agreement metrics
- `--trace-depth` and normalized provider trace sidecars

The following are deferred until a concrete experiment proves the external
approach insufficient:

- intentional `single_agent_baseline` execution,
- simple evaluator/rubric reference hashing,
- provider trace capture beyond current process-level artifacts.

## Analysis Fields To Keep Stable

Future export and paper appendices should be able to rely on these fields:

- `experiment_id`
- `task_id`
- `condition_id`
- `run_kind`
- `repetition_index`
- `slot_id`
- `slot_attempt`
- `decision_kind`
- `selection_basis`
- `canonical_winner`
- `judge_ran`
- `judge_attempted`
- `judge_completed`
- `providers`
- `judge`
- `triage`
- `telemetry`
- `artifact_fingerprints`

These fields are the Bakeoff-core contract. External experiment harnesses may
maintain richer study-level fields such as provider-pair matrices, evaluator
hashes, trace locations, source snapshots, attempt policies, and statistical
labels in their own study files.

## Risks And Open Questions

### Experiment Metadata vs Orchestration

Do not let metadata become an implicit scheduler. The first patch labels runs
and improves listing/filtering only. It must not add child-run lifecycle state,
parent experiment state, retry policy, or aggregate summaries.

### Closed vs Open Experiment Object

The lean plan uses a closed `experiment` object. This keeps the public contract
small and prevents speculative placeholder fields from becoming permanent. If an
external harness needs additional study-specific fields, it should store them
in its own study plan and use the stable ids to join back to Bakeoff manifests.

### Baseline Naming

Build already uses "baseline" for source-tree verifier checks. User-facing
docs should reserve `single_agent_baseline` for a future agent-baseline feature
and avoid implying that Phase 1 can execute one-provider runs.

### `canonical_winner` Compatibility

Some external tools may use `canonical_winner` for current two-provider runs.
Phase 1 does not change this field. Future single-agent baseline work must not
silently overload it.

### Judge Evidence Is Not Objective Quality

LLM judge wins are preference evidence. External analysis must separate judge
preference from verifier success, human labels, calibration, and
triage-confirmed findings.

### Provider Model Identity

Bakeoff records requested model strings today. Provider-resolved dated model ids,
seeds, temperature, usage, and hidden provider settings may not be available
from all CLIs. Record what Bakeoff asked for, what the CLI exposes, and any
known limitations.

### Trace Completeness

Structured trajectories depend on provider support and are out of scope for
this plan. Bakeoff cannot reconstruct hidden reasoning, hidden tool calls, or
internal state that was not emitted.

### Cost Accounting

Cost-quality analysis belongs outside Bakeoff for now. Wall time and output
bytes are available, but they are not a substitute for billed usage.

### Privacy

External evaluator labels and full traces may include sensitive content. Any
external study harness should hash rater ids and avoid copying sensitive trace
content into normal Bakeoff run ledgers unless the user explicitly opts in.

## Suggested First PR

The first PR should be small:

1. Add `experiment` metadata to work orders.
2. Copy it to `meta.json`.
3. Hoist selected fields into `manifest.json`.
4. Add `ls --experiment`, `ls --condition`, and JSON projection.
5. Add the optional experiment object to research/build JSON summaries.
6. Add docs and tests.

This PR would not run multiple children, would not add single-agent execution,
would not change judge behavior, would not add parent experiment artifacts, and
would not add statistics. It creates the metadata spine external experiment
tools can use.
