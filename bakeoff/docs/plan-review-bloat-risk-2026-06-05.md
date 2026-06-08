# Plan Review: Bloat Risk

Narrow review of one concern only: **does the paper-grade experiment-analysis
plan add bloat to bakeoff?** Reviewing
`docs/paper-grade-experiment-analysis-implementation-plan-2026-06-05.md`
against bakeoff's stated design contract.

The governing constraint comes from bakeoff's own README, section **"Why Bakeoff
Stays Thin"**:

> Full orchestration adds scheduling, role coordination, shared state, retries,
> and synthesis semantics — Bakeoff's strongest property is that every run is
> small, pairwise, replayable, and auditable, and that property erodes fast as
> you add machinery.

The plan proposes adding, almost verbatim: a **scheduler**, **retries**,
**shared parent state**, and **aggregation/synthesis**. That is the exact list
the plugin was designed to keep out. Three of the six layers are the machinery
the README warns against.

A second existing precedent: multi-lens review already declines to do
cross-run synthesis ("Synthesis into one prioritized fix plan is a separate
follow-up app"). The plan re-proposes cross-run aggregation as a core CLI
feature, contradicting an established product decision.

## Verdict Table

| Layer / Piece | Verdict | One-line rationale |
| --- | --- | --- |
| **L1: Experiment grouping metadata** (optional `experiment` block, hoisted to meta/manifest/ls) | **KEEP (trimmed)** | Pure data on existing ledgers, near-zero surface area; this is the one piece that earns its keep. Trim the field set hard. |
| **L2: Controlled repetition scheduler** (`bakeoff experiment run`, matrix, `--parallel`, `--resume`, retry policy) | **MOVE OUT** | This is the "scheduling + retries + shared state" the README explicitly excludes. Belongs in a shell loop / Makefile / external harness. |
| **L2a: Parent `experiment.json` artifact + child scan** (Phase 2) | **DEFER** | Useful only once you actually have multi-run experiments; YAGNI until L1 metadata exists and is proven. A grouping convention (run-id prefix) may suffice. |
| **L3: Single-agent baseline run kind** | **DEFER (partial KEEP)** | Genuinely a gap (`single_provider_only` is overloaded), but it is an eval-design feature, not core bakeoff. Add only the `run.kind` enum + validation if a real experiment needs it; defer baseline prompt variants. |
| **L4: Evaluator packs** (versioned rubric/calibration packs, copy+hash, `evaluator validate/calibrate`) | **MOVE OUT / CUT** | A whole rubric-management + human-labeling + calibration subsystem. Disproportionate. Rubrics-as-files is fine; calibration tooling is a separate research project. |
| **L5: Analysis & export** (`bakeoff analysis export`, JSONL/CSV/MD, bootstrap CIs, Wilson, Bradley-Terry, pass@k, pass^k) | **MOVE OUT** | Stats/aggregation across runs do not belong in a lean CLI. Bakeoff should emit clean per-run data; analysis lives in a notebook/script. |
| **L5a: Stable export field contract** | **KEEP (as data, not as command)** | Worth guaranteeing manifest fields stay stable so *external* tools can read them. That is the real deliverable, not the stats engine. |
| **L6: Trace depth capture** (`--trace-depth`, normalized `trace.json`, per-backend NDJSON/OTel normalizers) | **DEFER (CUT for now)** | Large new per-backend subsystem with ongoing maintenance pinned to four CLIs' output formats. High burden, speculative value. |

Net: **1 KEEP, 1 KEEP-as-data, 2 DEFER, 3 MOVE OUT/CUT.**

## Narrative — the contentious calls

### The core question: does experiment analysis belong in bakeoff at all?

Mostly no. Bakeoff's entire identity is *one run = small, pairwise, replayable,
auditable*. Experiment analysis is the opposite shape: it is *many runs,
cross-run state, aggregate statistics, longitudinal comparison*. Bolting that
onto the run engine couples two things that have different lifecycles and
different change rates (stats methodology churns; the run engine should be
stable).

The clean architecture is the one the plan itself half-discovers but then
overrides: **bakeoff emits clean, stable, structured per-run data; analysis
lives outside.** L1 metadata + a stable manifest contract delivers exactly
that. Everything past it (scheduler, packs, export stats, traces) is the
analysis layer trying to move *inside* the tool.

### L1 metadata — keep, but trim

This is the only layer that fits. It adds optional fields to artifacts that
already exist (`meta.json`, `manifest.json`, `ls --json`) and changes no run
behavior. The "Suggested First PR" is appropriately small. Caveat: the proposed
`experiment` object is sprawling (nested `sampling`, `artifacts`, snapshot
hashes, trace depth). Most of those fields are placeholders for *later* layers
that should not be built. Trim L1 to the fields that are meaningful with zero
other layers present: `experiment_id`, `task_id`, `condition_id`, `run_kind`,
`repetition_index`. Adding fields for subsystems that don't exist is
speculative schema bloat.

### L2 scheduler — the clearest MOVE OUT

`bakeoff experiment run --repetitions N --matrix ... --parallel M --resume
--retry ...` is a parallel job scheduler with resume and retry semantics. The
README names "scheduling" and "retries" as the two things that erode bakeoff's
core property. Worse, it duplicates capability that already exists *outside*
bakeoff: a `for` loop over `bakeoff run` with deterministic `--run-id`s does the
repetition; `--resume` is "skip run-ids that already have a manifest" — three
lines of shell. If repetition must be ergonomic, ship a documented example
script in `examples/`, not a stateful subcommand in the binary. Retry-without-
overwriting-evidence is real complexity (attempt tracking, counted-evidence
selection) for a problem a human re-running one slot solves by hand.

### L4 evaluator packs — disproportionate

This is the single largest surface-area grab. It introduces: a pack file
format, a loader/validator/hasher, a copy-into-ledger step, prompt-injection
plumbing, a `prompt-manifest.json`, plus **two new CLI verbs** (`evaluator
validate`, `evaluator calibrate`) and an entire human-labeling + agreement-
metrics + confusion-matrix pipeline. Calibration against human labels is a
legitimate research activity — but it is *research methodology tooling*, not a
second-opinion CLI feature. The valuable 10% (rubrics should be versioned files
with a hash, not buried in prompt fixtures) can be done as a small refactor.
The other 90% (calibration harness, human-label JSONL schema, agreement stats)
should live in the user's analysis layer or a separate repo. Bundling it here
roughly doubles bakeoff's maintainable concept count.

### L5 analysis/export — emit data, don't compute stats

There are two separable things here. (a) **Export**: collecting per-run rows
into JSONL/CSV — low harm, but it is just iterating manifests, which an external
script does equally well. (b) **Statistics**: bootstrap CIs, Wilson intervals,
Bradley-Terry MLE, Elo, pass@k, pass^k. This is a statistics library living
inside a CLI whose job is running two agents. Stats methodology is exactly the
kind of thing that gets revised, debated, and version-churned; pinning it inside
the run engine is a maintenance liability with no upside over a 50-line Python
notebook. **Keep the data contract stable; cut the stats engine.** If any export
ships, it should be a dumb `--format jsonl` dump of existing manifest fields and
nothing more.

### L6 trace depth — defer hard

Per-backend NDJSON/OTel normalizers (`codex exec --json`, Claude `stream-json`,
Gemini OTel, Copilot fallback) are a standing maintenance commitment tied to
four external CLIs' output formats, all of which change independently. The
plan's own "Hard rule" admits bakeoff often *cannot* capture the interesting
state anyway. High burden, speculative payoff, four moving external
dependencies. Not now.

## Duplication / existing-capability check

- **Repetition + resume** duplicate trivial shell-loop behavior over the
  existing `--run-id` and manifest-presence mechanics.
- **Cross-run synthesis/aggregation** re-litigates a settled decision: multi-lens
  review already declares synthesis "a separate follow-up app."
- **Escalation** already covers "bring in a third provider for another view"
  without changing the two-provider shape — the plan's multi-agent-vs-baseline
  framing partly overlaps this.
- **Single-agent**: `single_provider_only` exists but is semantically a degraded
  bakeoff; the plan is right that an *intentional* baseline is distinct. This is
  the one genuine, non-duplicative gap among the heavy layers.

## Recommended Lean Cut

Ship only this, and stop:

1. **L1 metadata, trimmed.** Optional `experiment` block with five fields
   (`experiment_id`, `task_id`, `condition_id`, `run_kind`, `repetition_index`),
   validated and hoisted into `meta.json` / `manifest.json` / `ls --json`. This
   is the "Suggested First PR," minus the speculative nested sub-objects.

2. **A documented stable manifest field contract** (the "Analysis Fields To Keep
   Stable" list, pruned to fields that exist). Promise external tools these
   fields won't churn. This is the actual deliverable that enables paper-grade
   analysis — *without* putting analysis in the plugin.

3. **One `examples/` script** showing repetition via a shell loop over
   `bakeoff run` with deterministic run-ids and manifest-presence skipping.
   Replaces the entire L2 scheduler.

4. **Optional, only if a real experiment demands it:** the `run.kind:
   single_agent_baseline` enum + validation rule (L3 core only — no prompt-
   variant system, no new decision-kind sprawl yet).

Defer L2 (as a binary feature), L2a parent artifact, L4 calibration, L5 stats,
and L6 traces until there is a concrete, repeated, in-hand need that the
external/script approach has demonstrably failed to meet. Re-evaluate each only
on proven demand.

**Guiding line:** bakeoff should produce clean, stable, structured evidence per
run. The moment it starts scheduling many runs and computing statistics across
them, it stops being a thin second-opinion machine and becomes an experiment
platform — which is precisely the erosion its own README warns against.
