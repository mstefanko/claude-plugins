# Artifact-Aware Continuation Implementation Plan

Date: 2026-05-21

Status: proposed, scope-cut after plan review

Scope: Claude plugin guidance first; no new Go orchestration and no dedicated
slash command in PR1

## Recommendation

Ship a small checkpointed continuation advisor, not a sequential work-order
system.

PR1 should not add `/bakeoff:continue`. The problem is plausible but not yet
proven by enough usage evidence to justify another command file that duplicates
`/bakeoff:run`'s drafting invariants. Users can already ask for the next step
from a prior run through `/bakeoff:run`, for example:

```text
/bakeoff:run draft an implementation plan from runs/task-progress-research/report.md
/bakeoff:run compare the two approaches in runs/parser-options/report.md
/bakeoff:run build the triaged finding in runs/review-auth/triage/triage.md
```

PR1 should touch only documentation and plugin-command contract files:

1. A short "Continuation Advisor" section to `skills/bakeoff/SKILL.md`.
2. A matching `/bakeoff:run` post-run recommendation rule in
   `commands/run.md`.
3. A small README note.
4. A `docs/work-orders.md` clarification that continuation is not a new schema.
5. Manual scenario coverage in `docs/task-fit-test-scenarios.md`.

Do not change Go code in PR1.

The advisor reads the completed run's artifacts, recommends the next normal
work-order shape when one is warranted, and is allowed to recommend no
follow-up Bakeoff run. It must not blindly offer continuation, automatically
chain phases, or jump from research to build without concrete implementation
evidence.

PR1 recommendations are session-scoped. The post-run line may rely on exact
artifact paths the just-completed `/bakeoff:run` already knows, including a
custom `--out` directory. Cross-session continuation requires the user to supply
artifact paths or a normal `/bakeoff:inspect`/`/bakeoff:history` lookup first;
do not assume `runs/<run-id>`.

Dedicated `/bakeoff:continue` can be reconsidered later only after usage shows
that post-run suggestions are not enough.

## Scope Control Guardrails

The bloat risk is real: a prompt-only advisor can accidentally grow into a
second drafting system if it tries to handle every historical artifact shape,
approval path, or future command case. PR1 earns its spot only if it stays
smaller than the problem it solves.

Keep PR1 constrained by these rules:

- one optional recommendation in the existing `/bakeoff:run` summary;
- no continuation-specific work-order skeletons or approval flow;
- no legacy free-text inference when structured artifact signals are ambiguous;
- no scenario coverage for split, multi-lens, task-fit, or approval behavior
  unless PR1 changes that behavior;
- no future `/bakeoff:continue` API details beyond the decision to defer it and
  the requirement that any future version start read-only/advisor-only;
- prefer omitting the recommendation or suggesting inspect/verify over adding
  another rule.

## Validated Corrections From Review

This plan was tightened against the current repo behavior:

- Exit `4` is real for research decision-incomplete states where the judge
  failed or did not converge. `bakeoff rerun <run-id> --judge-only` is currently
  research-only.
- Build judge-only rerun is not supported today. Build judge failure or
  unresolved build outcomes should recommend inspect, selected-patch review,
  or full build rerun when appropriate, not judge-only.
- `review` is not a work-order type. A review continuation drafts
  `type: "gather"` with `facet.id: "code-review"`.
- `plan` is not a work-order type. In v1 it is a user-facing label for a normal
  `type: "analyze"` work order with a planning goal.
- Multi-lens continuation is out of scope for PR1. If artifacts suggest
  multiple separate review lenses, recommend the existing explicit multi-lens
  `/bakeoff:run` flow rather than inventing continuation-specific behavior.
- Triage staleness is detectable today. `internal/triage/state.go` compares
  stored input hashes against current `decision.json`, `report.md`,
  `work-order.json`, and review-context artifacts.
- Review triage items do not carry verifier commands or full build acceptance
  criteria. Review-to-build advice must still require user-supplied or
  repo-discovered verifier and acceptance criteria through normal
  `/bakeoff:run` build drafting.

## Why Not Automatic Chaining

Most sequential value comes from human judgment between phases:

- Research can change the actual problem.
- Compare may produce a winner but leave integration details open.
- Analyze may identify root cause without proving the fix boundary.
- Review findings need triage/actionability before becoming build work.
- Build requires explicit acceptance criteria, edit scope, verifier commands,
  and sometimes protected paths.

Automatically moving from research to build would often spend provider budget on
stale assumptions. The checkpoint is not friction; it is the quality gate.

The product promise stays:

- one normal work order per run;
- durable artifacts in `<out>/<run-id>/`;
- no hidden synthesis;
- no patch application;
- explicit approval before writes and execution.

## User-Facing Model

At the end of `/bakeoff:run`, keep the existing artifact summary. Add at most
one short continuation recommendation, with a brief artifact-based reason when
useful.

Good examples:

```text
Recommended next step for `docs-review`: no follow-up Bakeoff run recommended.
I inspected `report.md` and `decision.json`; both providers converged on a
docs-only answer and there is no obvious follow-up Bakeoff run.
```

```text
Recommended next step for `task-progress-research`: draft an implementation
plan from this run. I inspected `report.md` and `decision.json`; the report
converges on the direction, but the implementation boundary and verifier are
still design choices.
```

```text
Recommended next step for `parser-options`: compare the two open designs. I
inspected `report.md` and `decision.json`; the research found two viable
approaches and did not resolve the tradeoff.
```

```text
Recommended next step for `cache-build`: inspect the selected patch. I inspected
`decision.json` and `diagnostics.json`; this build already selected a winning
patch, so Bakeoff should not apply, merge, or rebuild it automatically.
```

Avoid:

```text
Want to continue?
```

The recommendation should be artifact-aware, not a blind funnel into more work.
If the artifacts do not support a clear next step, omit the continuation line.
If `decision.json` is missing or unparseable, omit the recommendation rather
than inferring from `report.md` prose alone.

## Mode Rules

The advisor should use the source run mode, decision state, and available
artifacts to choose a default next step.

| Source mode | Common recommendation | Recommend build next? |
| --- | --- | --- |
| `gather` / research | draft an implementation plan, compare, follow-up research, or stop | Rarely |
| `compare` | draft an implementation plan around winner, follow-up compare if unresolved, or stop | Only for tiny, verifier-obvious work |
| `analyze` | draft an implementation plan if root cause/design is clear, follow-up research if not, or stop | Sometimes, after concrete fix boundary exists |
| review (`gather` + `code-review`) | build a selected triaged finding, run narrower review, or stop | Only after actionable triage |
| `build` | inspect selected patch, review selected patch, full rerun if needed, or stop | No; build already ran |

### Gather / Research

Research should not default to build. It should recommend:

- `stop` when the answer is complete and no action follows;
- `compare` when multiple viable options remain;
- draft an implementation plan when the direction is clear but design choices
  remain;
- follow-up `gather` when evidence gaps or unknowns dominate;
- `build` only when the report identifies a small, concrete code change with
  obvious acceptance criteria and an existing verifier command.

### Compare

If compare has a canonical winner and implementation is still design-heavy,
recommend drafting an implementation plan. If the winner maps directly to a
small implementation and the user has supplied or the repo clearly exposes a
verifier, offer to draft a build work order for approval.

If compare ended in a tie or disagreement, recommend narrower compare or
additional research rather than build.

### Analyze

If analyze identifies root cause and a likely fix boundary, recommend drafting
an implementation plan or a build work order depending on verifier readiness.

If root cause remains uncertain, recommend follow-up research or a more focused
analyze run.

### Review

Review continuation should read triage artifacts when present.

Recommend build only for findings that are:

- classified as actionable, normally `classification: "real_issue"`;
- paired with a fix-oriented `recommended_action`, normally `fix_now`;
- still cited against current files;
- narrow enough to become a build scope;
- tied to a user-supplied or repo-discovered acceptance criterion and verifier
  command.

Use the existing triage state when available; stale triage is detectable from
stored input hashes. If triage is missing, stale, failed, or disabled, recommend
triage or inspect before build. Do not draft build directly from raw untriaged
findings unless the user explicitly overrides.

If the next review step is multi-lens, use the existing explicit multi-lens
drafting flow. Do not create a continuation-only multi-lens path.

### Build

Build continuation should never chain into another build automatically.

Recommend:

- inspect selected patch;
- review selected patch;
- full build rerun only when provider/verifier failure warrants it;
- stop when the handoff is complete.

Do not recommend judge-only rerun for build runs. `--judge-only` is currently
research-only.

Do not apply, merge, synthesize, commit, or open a PR as part of continuation.

## Target Mapping

Continuation targets are user-facing labels. They must map to existing work
orders only.

Use `draft an implementation plan` in user-facing copy for the planning target;
map it to `plan` in scenarios and to `type: "analyze"` in the work order. Avoid
presenting `plan` and `analyze` as two separate user choices for the same next
step.

| User-facing target | Work-order shape | Notes |
| --- | --- | --- |
| `plan` | `type: "analyze"` | Goal: turn prior artifacts into an implementation plan with risks, phases, and validation. No code edits. |
| `research` | `type: "gather"` | Use when prior artifacts expose evidence gaps or unknowns. |
| `compare` | `type: "compare"` | Use when prior artifacts identify named options and criteria. |
| `analyze` | `type: "analyze"` | Use for root cause, architecture reasoning, or synthesis. |
| `review` | `type: "gather"` + `facet.id: "code-review"` | Requires bounded branch, diff, file set, or local-change scope. |
| `build` | `type: "build"` | Requires normal build fields: acceptance criteria, edit scope, verifier command, and protected paths when relevant. |

`plan` goal template:

```text
Turn prior Bakeoff run <run-id> into a concrete implementation plan. Use the
prior report and decision as source context. Identify the recommended product or
code path, rejected alternatives, implementation phases, validation strategy,
risks, and open questions. Do not implement code or invent requirements not
supported by the prior artifacts.
```

Prior artifacts should be cited in `background` by path, not copied wholesale:

```text
Prior Bakeoff run: task-progress-research.
Use these artifacts as source context:
- runs/task-progress-research/report.md
- runs/task-progress-research/decision.json
```

Use exact paths from the just-finished run summary, user-supplied paths, or
inspect/history output. Preserve custom `--out` directories and do not construct
`runs/<run-id>` paths unless that is the actual path already surfaced.

## Artifact Signal Contract

PR1 is prompt-resident, so it needs a small explicit field contract. The
Continuation Advisor may rely on only these stable signals. If a required
decision signal is missing, malformed, or unsupported, omit the recommendation
or downgrade to inspect/triage/plan instead of guessing. Do not attempt
prompt-only stale-decision detection in PR1; reserve staleness checks for
triage, where existing input hashes already support it.

Always-required decision context:

- parseable `decision.json`;
- `decision.json.mode`;
- `decision.json.decision_kind`;
- `decision.json.provider_statuses[*].status`;
- `work-order.json.type`;
- `work-order.json.facet.id` when present, especially `code-review`.

Mode-specific or nullable decision context:

- `decision.json.canonical_winner` may be null. Null is valid for unresolved
  compare/build outcomes and for modes that do not select a winner. Treat a
  non-null canonical winner as required only when recommending a selected patch,
  winner inspection, or winner-centered plan.
- Judge-only retry advice is research-only. Recommend it only when structured
  artifacts or the just-completed run summary explicitly show a research
  decision-incomplete state where providers succeeded and the judge failed or
  did not converge. Do not infer judge failure from older free-text caveats in
  PR1; for older or ambiguous artifacts, recommend inspect/verify instead.

`judge_attempted` and `judge_completed` are useful when present but must not be
mandatory for every run artifact. Their absence should narrow the advisor's
confidence, not trigger free-text inference.

Optional enrichment only:

- `meta.json` and `manifest.json` may provide timestamps, `exit_code`, artifact
  paths, triage summaries, and resolved model details;
- they are not the source of truth for `decision_kind`, canonical winner, or
  provider success when `decision.json` exists.

Review signals:

- triage state from existing triage state logic or a manifest summary that was
  produced by that logic;
- `triage/final.json.items[*].classification`;
- `triage/final.json.items[*].recommended_action`;
- `triage/final.json.items[*].supporting_evidence`;
- citation freshness only when the existing triage state reports current
  inputs. If current-file validation is unavailable in PR1, do not upgrade raw
  or stale findings into build advice.

Build signals:

- `decision.json.canonical_winner`;
- provider `build/diff.patch` path only for the canonical winner;
- verifier/gate status only when surfaced by structured `decision.json`,
  `diagnostics.json`, or manifest fields. Use those fields as evidence that a
  build run already verified or failed; do not infer verifier readiness from
  report prose alone;
- no selected patch when `canonical_winner` is null, even if provider patch
  artifacts exist.

Narrative context:

- `report.md` may explain why the next step is plan, compare, research, review,
  build, or stop;
- `report.md` must not override missing or contradictory structured decision
  signals.

## PR1 Behavior

### In `skills/bakeoff/SKILL.md`

Add a short "Continuation Advisor" section immediately after
`## Artifact Summary Contract` and before `## Permission Semantics`.

Keep this section concise and reference existing sections instead of restating
them wholesale:

- Read the completed run's report/decision/triage/build artifacts before
  recommending a next step.
- Enumerate the artifact signal contract above, especially the decision fields
  the advisor may rely on.
- Omit the recommendation when `decision.json` is missing, unparseable, or too
  ambiguous to support a specific next step.
- Preserve exact prior artifact paths, including custom `--out`; never assume
  `runs/<run-id>` unless that exact path was surfaced.
- State that post-run recommendations are session-scoped. Cross-session
  continuation needs user-supplied paths or an inspect/history lookup.
- Do not offer blind continuation.
- Prefer `draft an implementation plan` between research and build unless the
  implementation is tiny, concrete, and verifier-obvious.
- Map `plan` to `type: "analyze"`.
- For review continuation, refer to the existing Work-Order Classification rule
  that review is `type: "gather"` with the `code-review` facet.
- For review-to-build advice, require actionable triage plus user-supplied or
  repo-discovered acceptance criteria and verifier. Triage does not provide a
  verifier field.
- Keep build continuation strict: all build drafting invariants, filename/run-id
  collision policy, Competitive Build Handoff, and Permission Semantics still
  apply.

Add a sync note to `## Artifact Summary Contract` matching the existing
Drafting Invariants pattern: this section and
`commands/run.md -> ## Execution And Summary` must stay in sync. In the same PR,
fix the current drift so exit `4` judge-only guidance is scoped to research
runs; build runs should not recommend `--judge-only` until the CLI supports it.

### In `commands/run.md`

Update `## Execution And Summary` so completed runs may include one
continuation recommendation.

Constraints:

- Do not make the final response much longer.
- Keep this section in sync with `skills/bakeoff/SKILL.md ->
  ## Artifact Summary Contract`.
- Do not offer continuation when artifacts are missing, unreadable, outside
  allowed paths, or not safe to trust as source context.
- Do not infer a recommendation from `report.md` prose when `decision.json` is
  missing or unparseable.
- Preserve exact artifact paths from the run summary, including custom `--out`.
- For research exit `4`, prefer existing judge-only retry guidance when
  providers succeeded and the judge failed.
- For exit `4`, the judge-only guidance must be explicitly research-only in
  both `commands/run.md` and `skills/bakeoff/SKILL.md`; build runs should direct
  users to inspect diagnostics or run a full build rerun when warranted.
- For build runs, prefer inspect/review selected patch, not another build.
- Do not invent a second approval flow inside `/bakeoff:run`; if the user wants
  the next run, they should issue a normal `/bakeoff:run` request or reply in a
  way the existing command flow can preview and approve.
- Preserve the existing task-fit gate and wording: "This may not need Bakeoff"
  and `draft anyway` as the only opt-out phrase.
- Preserve approval phrases: single work orders accept explicit affirmatives
  such as `yes`, `y`, `approve`, `run it`, or `write and run` after preview;
  split and multi-lens runs still require exact `write and run`.

### Documentation

Update:

- `README.md`: mention that completed runs may recommend a next normal work
  order when artifacts make one obvious.
- `docs/work-orders.md`: clarify continuation is not a batch schema; each
  continuation remains a normal work order.
- `docs/task-fit-test-scenarios.md`: add manual scenarios for continuation
  recommendations.

Do not update `docs/cli-reference.md` with `/bakeoff:continue` in PR1 because
the command is not being added.

## Definition Of Done

Add a small set of manual regression scenarios with fixture-style run ids. Keep
them as lightweight documented artifact summaries in
`docs/task-fit-test-scenarios.md`; they do not need to be full committed run
directories in PR1.

Use this compact format for each scenario:

- source artifact summary;
- simulated user request or completed-run state;
- expected recommendation text;
- forbidden recommendation text;
- approval behavior when a next work order is drafted.

| Fixture run id | Source shape | Pass assertion | Fail if |
| --- | --- | --- | --- |
| `cont-research-plan` | `type=gather`, providers agree on product direction, no verifier or edit scope | Recommends drafting an implementation plan; explains build is premature | Offers build as default |
| `cont-research-compare` | `type=gather`, report leaves two named options unresolved | Recommends `compare` with option names | Recommends build or generic "continue" |
| `cont-research-stop` | `type=gather`, answer complete, no action requested | Says no follow-up Bakeoff run is recommended, or omits continuation | Offers another run blindly |
| `cont-compare-plan` | `type=compare`, canonical winner, integration details open | Recommends drafting an implementation plan around the winner | Drafts build without verifier/edit scope |
| `cont-review-build-ready` | review run with triaged actionable finding, current citations, narrow scope, plus user-supplied or repo-discovered verifier and AC in the follow-up request | Offers to draft a build work order for approval | Runs or writes before approval |
| `cont-review-raw` | review run without triage or with stale triage | Recommends triage/inspect before build | Drafts build from raw findings |
| `cont-build-winner` | build run with canonical winner and patch artifact | Recommends inspect/review selected patch | Applies patch, opens PR, or recommends another build |
| `cont-build-unresolved` | build run with no canonical winner / exit `3`, even when provider patches exist | Recommends inspect diagnostics or full rerun if evidence warrants; says no selected patch | Recommends judge-only or treats any provider patch as selected |
| `cont-missing-decision` | missing or corrupt `decision.json` but readable `report.md` | Omits recommendation and suggests inspect/verify | Infers from report prose |
| `cont-custom-out` | completed run under custom `--out /tmp/example-runs` | Preserves exact `/tmp/example-runs/<run-id>/...` paths | Mentions `runs/<run-id>` |

Do not add continuation-specific split, multi-lens, task-fit, or approval-matrix
scenarios in PR1. Those belong to the existing command-flow coverage unless a
future continuation command owns new behavior.

For every scenario:

- The recommendation must name the source run id.
- The recommendation must name the inspected artifact class, such as report,
  decision, triage, diagnostics, or patch.
- The recommendation must be one of: stop, inspect, judge-only rerun for
  research, draft an implementation plan, gather/research, compare, review, or
  draft a build work order for approval.
- Drafting a build work order must never bypass existing build missing-field
  checks.
- Recommendations must preserve exact artifact paths, including custom `--out`.
- User-facing recommendation examples must name the source run id and the
  inspected artifact class.

Cover the exit-`4` judge-only drift separately where the run-summary contract is
updated: research decision-incomplete runs may recommend judge-only rerun when
structured evidence supports it; build runs must not.

## Schema-Drift Mitigation

PR1 is prompt-resident, so keep it deliberately thin:

- Do not duplicate full work-order JSON skeletons in the continuation section.
- Use existing `/bakeoff:run` drafting paths for any next work order.
- Validate every drafted next work order with `bakeoff validate` before running.
- Prefer artifact paths and short summaries in `background`; do not invent a
  continuation metadata schema.
- Keep target mappings limited to existing work-order types.
- Keep the artifact signal contract explicit in skill text so schema renames
  surface during review.
- Keep `commands/run.md -> ## Execution And Summary` and
  `skills/bakeoff/SKILL.md -> ## Artifact Summary Contract` synchronized with a
  written sync note in the skill file.

If a future `/bakeoff:continue` command is added, it should either remain
advisor-only or be backed by a small Go helper that emits a stable
machine-readable artifact-summary JSON over existing run artifacts. Do not
duplicate `/bakeoff:run`'s full drafting and approval contract in a second
command file without a contract test or helper that catches schema drift.

## Deferred `/bakeoff:continue`

Reconsider a dedicated command only after usage evidence shows that post-run
suggestions are not enough. PR1 should not freeze syntax, allowed tools, or
target flags for that future command.

If a future command is proposed, start with an advisor-only, read-only design:
inspect artifacts, summarize the safest next step, then hand any drafting,
approval, validation, and execution back to the normal `/bakeoff:run` flow. Do
not add a `--to`-style draft-and-run path until there is a clear contract test
or helper that prevents duplicating `/bakeoff:run` behavior.

## Native Task Progress

If Claude native task tools are available, use them only for outer workflow
visibility:

- `Inspect prior run`
- `Recommend continuation`
- `Draft next work order`
- `Validate next work order`
- `Run next work order`
- `Summarize continuation`

Mark later tasks as blocked until user approval. Do not attempt to mirror nested
provider progress into native tasks.

For Codex, use `update_plan` for the same outer checklist when available. Codex
does not currently have the same Claude TaskCreate/TaskUpdate surface, so do
not promise dependency-aware native task tracking there.

## Non-Goals

- No `sequence` or `pipeline` work-order type.
- No array of work orders in schema v1.
- No automatic phase transition after a provider run.
- No dedicated `/bakeoff:continue` command in PR1.
- No shared mutable state between runs.
- No hidden synthesis across reports.
- No automatic build from research by default.
- No automatic multi-lens continuation path.
- No automatic patch application, merge, commit, PR, or branch creation.
- No build judge-only rerun recommendation until the CLI supports it.
- No provider-progress mirroring into native task tools.

## Suggested First PR

Keep the first PR prompt-only and documentation-only:

1. Add the continuation section to `skills/bakeoff/SKILL.md`.
2. Add a short post-run continuation note to `commands/run.md`.
3. Update README and work-order docs.
4. Add the manual scenarios above to `docs/task-fit-test-scenarios.md`.
5. Fix the current exit-`4` contract drift in `commands/run.md` and
   `skills/bakeoff/SKILL.md` so judge-only is research-only.
6. Add the summary-contract sync note between `commands/run.md` and
   `skills/bakeoff/SKILL.md`.

Do not change Go code unless an existing artifact summary cannot expose the
needed paths. The current ledger and report files are already the source of
truth.
