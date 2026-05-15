# Faceted Research and Review for Bakeoff - Implementation Plan

Date: 2026-05-15
Status: proposed
Scope: `bakeoff` CLI work orders, prompts, reports, and code-review recipe support

## Decision

Add an optional top-level `facet` field to work orders and add a `review` init
recipe that writes a `type: "gather"` work order with a code-review facet.

Do not add a fourth core module. Do not add provider-specific lenses, multi-lens
matrices, or debate swarms in this iteration.

This keeps Bakeoff's core model intact:

- `gather`: enumerate and deduplicate evidence.
- `compare`: defend and judge a decision.
- `analyze`: build and merge an explanation spine.

The new `facet` narrows the task focus inside those modes. It is a structured
task filter, not an agent persona and not a new execution topology.

## Current Constraints

Bakeoff is intentionally small and pairwise:

- The only core modes are `gather`, `compare`, and `analyze`
  (`MODES` in `src/bakeoff/work_order.py`).
- Work orders currently require exactly two providers
  (`_validate_providers` in `src/bakeoff/work_order.py`).
- Workers differ today only by backend, model, and scope. Scope is one of
  `codebase`, `web`, or `mixed`.
- Worker prompts are generated centrally in `src/bakeoff/providers.py` and are
  already mode-aware.
- Gather reports render corroboration from judge `sources`. That works only
  when the two workers were asked comparable questions.
- Post-judge triage already exists for verifying actionable report findings
  without mutating the original decision.

Those constraints are useful. The plan below keeps them instead of turning the
CLI into a general swarm/matrix orchestrator.

## External Research That Informed This

### Code Review

LLM code review seems useful when it is contextual, bounded, and checked by
humans, but it is vulnerable to false positives, irrelevant comments, and trust
issues.

- Ericsson's experience report on LLM code review emphasizes that naive prompts
  are not enough; useful reviews depend on the right code context, prompt shape,
  and validation loop. The report also describes specialized prompts including
  detailed review, security review, few-shot review, and issue-topic review.
  Source: [Automated Code Review Using Large Language Models at Ericsson: An
  Experience Report](https://arxiv.org/abs/2507.19115).
- LAURA found that code-review generation improves when the model gets review
  exemplars, contextual augmentation, and systematic guidance. Its human
  evaluation reported comments that were completely correct or at least helpful
  in 42.2% and 40.4% of cases for the two LLM variants. Source:
  [LAURA: Enhancing Code Review Generation with Context-Enriched
  Retrieval-Augmented LLM](https://arxiv.org/abs/2512.01356).
- A field study of LLM-assisted code review found opportunities such as PR
  summarization, but also concerns around false positives and trust. It used RAG
  to assemble contextual review information and found preference depended on
  codebase familiarity and PR severity. Source: [Rethinking Code Review
  Workflows with LLM Assistance](https://arxiv.org/abs/2505.16339).

Implication: Bakeoff should improve review prompts and evidence handling, not
add broad "reviewer personas" or unconstrained swarms.

### Personas And Lenses

The strongest evidence does not support role-play as a reliable way to improve
factual accuracy.

- "Playing Pretend" found that in-domain expert personas generally did not
  improve accuracy over a no-persona baseline on difficult objective benchmarks,
  while low-knowledge personas were often harmful. Source: [Prompting Science
  Report 4: Playing Pretend](https://arxiv.org/abs/2512.05858).
- Zheng et al. evaluated 162 persona roles across 2,410 factual questions and
  found that adding personas did not improve performance over no-persona
  controls; automatically selecting the best persona was also unreliable.
  Source: [When "A Helpful Assistant" Is Not Really
  Helpful](https://arxiv.org/abs/2311.10054).

Implication: The new concept should be called `facet`, not `persona` or
`role`. It should define a narrow evidence/rubric focus such as "security" or
"frontend behavior", while explicitly saying it does not change citation,
schema, or scope rules.

### Multi-Agent Debate And Cost

Multiple calls can improve reasoning, but debate/swarm setups are not free wins.

- Self-consistency improves some reasoning tasks by sampling multiple reasoning
  paths and aggregating the most consistent answer. Treat this as the cheap
  robustness alternative before adding debate/swarm topology. Source:
  [Self-Consistency Improves Chain of Thought Reasoning in Language
  Models](https://arxiv.org/abs/2203.11171).
- Anthropic's production multi-agent research writeup supports multi-agent
  systems for breadth-first research with independent search trajectories, but
  also reports high token cost and warns that most coding tasks have fewer truly
  parallelizable subtasks than research. Source: [How we built our multi-agent
  research system](https://www.anthropic.com/engineering/multi-agent-research-system).
- NeurIPS 2024 work on multi-LLM debate warns that similar model capabilities or
  similar responses can produce static debate dynamics that converge on a
  majority view, including a shared misconception. Source: [Multi-LLM Debate:
  Framework, Principals, and Interventions](https://papers.nips.cc/paper_files/paper/2024/hash/32e07a110c6c6acf1afbf2bf82b614ad-Abstract-Conference.html).
- A controlled study of LLM debate found that intrinsic reasoning strength and
  group diversity are the dominant drivers of success, while many structural
  settings add limited gains. Source: [Can LLM Agents Really
  Debate?](https://arxiv.org/abs/2511.07784).

Implication: Bakeoff should stay pairwise and auditable. A multi-facet or
multi-model matrix may be useful later as a launcher/batch layer, but it should
not be folded into the three core modes.

## Use Case Mapping

### Code Review A Branch

Use `bakeoff init review`, which produces a `type: "gather"` work order with a
shared `code-review` facet. Both providers get the same branch/diff context and
the same review filter. The gather judge deduplicates actionable findings and
preserves citations. `bakeoff research` auto-runs triage for this recipe unless
the caller passes `--no-triage`.

This improves the code-review workflow without adding a new mode or making
review-specific claims first-class before we know the generic claim schema is
insufficient.

### Research A Pattern And Inspect This Codebase

Use a normal `gather` or `analyze` work order with `scope: "mixed"` and, when
helpful, a shared facet such as `pattern-applicability`.

This should be one combined work order, not two independent bakeoffs. The web
evidence and local code evidence are coupled, and separating them would force a
human or a later judge to stitch together two partial reports.

### Same Model, Different Set Of Eyes

Do not support same-run provider-specific lenses in v1. Same model with
different `scope` is already structurally supported when the provider
backend/model/scope triples differ. Same model with different `facet` should use
separate pairwise runs, or a later `facet_matrix` launcher that creates separate
runs and then synthesizes their reports.

This keeps gather corroboration meaningful. If one worker is asked for security
and the other is asked for frontend behavior, a single-source finding no longer
means "only one model noticed this"; it may simply mean "only one worker was
asked to look there."

## Proposed Work Order Shape

Add an optional top-level `facet` object:

```jsonc
{
  "schema_version": 1,
  "id": "review-auth-cache",
  "type": "gather",
  "goal": "Review the branch diff for actionable defects.",
  "background": "Base branch: main. Review branch: feature/auth-cache. Focus on changed files and directly coupled call sites.",
  "facet": {
    "id": "code-review",
    "kind": "generic",
    "focus": "Find actionable defects introduced or exposed by the change.",
    "include": [
      "correctness bugs and edge cases",
      "security issues with concrete data-flow or control-flow evidence",
      "user-visible regressions",
      "missing or misleading tests for changed behavior",
      "maintainability risks likely to cause future defects"
    ],
    "exclude": [
      "style-only preferences without project convention evidence",
      "large rewrites unrelated to the changed behavior",
      "speculation without file:line evidence"
    ]
  },
  "providers": [
    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "judge": { "backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh" },
  "budgets": { "wall_clock_seconds": 900, "max_output_bytes": 60000 }
}
```

### Facet Semantics

A facet is:

- A narrow search/rubric focus applied to both workers and the judge.
- A way to make tasks such as code review, security review, frontend review, or
  architecture review more explicit.
- Audit metadata that should appear in `work-order.json`, `meta.json`, prompts,
  and reports.
- A flat, singular object. v1 intentionally has no composition, no provider-level
  facets, and no branching by facet kind.

A facet is not:

- A provider-specific persona.
- A replacement for `scope`; `scope` still controls codebase/web/mixed access.
- A fourth mode.
- A request to produce prose in a different voice.
- Permission to drop citations, skip schemas, or broaden beyond the work order.

### Validation Rules

Keep validation strict enough that facets guide rather than distract:

- `facet` is optional.
- When present, it must be an object.
- `facet` is closed-schema in v1. Allowed keys are `id`, `kind`, `focus`,
  `include`, `exclude`, and `notes`.
- `facet.id` is required and must use the same slug rules as provider ids.
- `facet.id` must not collide with any provider id in the same work order.
- `facet.kind` is reserved for future compatibility. It may be absent or
  `"generic"`; reject every other value.
- `facet.focus` is required, non-empty, and should be one sentence.
- `facet.include` is required and must contain 1-8 non-empty strings.
- `facet.exclude` is optional and must contain 0-8 non-empty strings.
- `facet.notes` is optional and should be reserved for concrete project
  constraints, not extra role-play.
- Validation errors should name the precise field, for example
  `facet.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$`,
  `facet.id must not duplicate a provider id`, or
  `facet.kind must be "generic" when present`.

Do not allow provider-level facets in v1. If providers have different facets in
the same gather run, `corroboration` stops meaning "two independent workers
found the same claim" and starts meaning "two different task filters happened
to overlap." That muddies the report.

## Prompt Contract

Inject the facet after `<scope>` and before mode-specific rules:

```text
<facet>
Facet id: security
Focus: Find concrete security risks introduced or exposed by this change.

This is a task focus, not a persona. Do not role-play. Apply the facet only
after the work-order goal, scope, citation rules, and output schema.

Include:
- authorization and authentication regressions
- unsafe parsing or input validation gaps
- secret handling, logging, or data exposure risks

Exclude:
- generic best-practice advice without file:line evidence
- theoretical attacks with no reachable path in this codebase
</facet>
```

Worker prompt rules should add:

- Prefer findings inside the facet.
- Do not invent domain facts to satisfy the facet.
- If a severe issue outside the facet is noticed, place it in
  `recommended_next_checks` with a citation instead of expanding the main
  `claims` set.
- The facet never overrides output schema, citation requirements, or scope
  enforcement.

Judge prompt rules should add:

- Preserve only claims that satisfy the facet or are clearly severe
  out-of-facet next checks.
- Do not reward a worker for broadening beyond the facet.
- Do not penalize a worker for omitting material that the facet excluded.
- For gather only, when a claim is dropped solely because it is out of facet,
  include it in optional `out_of_facet_claims[]` with source labels, evidence,
  and a short reason. This is observability only; do not put these claims in
  `merged_claims`.

The gather validator can accept this optional field without changing the
required judge schema because extra fields are already tolerated. The report
should render an `Out-of-Facet Claims` section when the field is present, but
that section should not be included in triage source selection.

## Code Review Recipe

Add a recipe, not a new mode:

```text
bakeoff init review [--force]
```

Implementation details:

- Keep `MODES = ("gather", "compare", "analyze")` unchanged.
- Add `INIT_KINDS = (*MODES, "review")` for the init parser choices only.
- In `cmd_init`, branch before indexing `MODE_EFFORT_DEFAULTS`:
  - `review` writes `review.work-order.json`.
  - The serialized work order has `"type": "gather"`.
  - Defaults come from `MODE_EFFORT_DEFAULTS["gather"]`, so no
    `MODE_EFFORT_DEFAULTS["review"]` mapping is needed.
- Print `recipe: review (mode gather)` after writing the file.

It writes `review.work-order.json` with:

- `"type": "gather"`.
- `scope: "codebase"` for both providers.
- high worker and xhigh judge effort by default while dogfooding quality.
- a top-level `facet.id` of `code-review`.
- background placeholders for base branch, review branch, diff command, changed
  files, acceptance criteria, and known risk areas.

The recipe should say that Bakeoff does not compute branch diffs in v1. The user
provides the branch/diff context in `background`. Automatic GitHub/PR/Gerrit
integration stays out of scope.

## Triage Policy

Keep the existing recommendation-only behavior for normal gather/compare/analyze
runs. For `facet.id == "code-review"`, auto-run triage after a successful
research run unless the caller passes `--no-triage`.

Reasoning:

- Code-review findings are meant to drive immediate fixes, so untriaged false
  positives are more expensive than in ordinary research reports.
- Auto-triage costs one additional provider call, but the review recipe is
  already an explicitly higher-stakes workflow.
- The escape hatch keeps exploratory or low-budget runs cheap.

Implementation details:

- Add `--no-triage` to `bakeoff research`.
- Add `should_auto_triage(work_order, decision) -> str | None` in
  `src/bakeoff/triage.py`.
- Return a reason for `facet.id == "code-review"` when the research phase
  produced a report and did not already fail.
- If auto-triage runs and fails, keep the research report and triage artifacts,
  but return the triage exit code unless the research phase already failed.
- `should_recommend_triage` should also return a code-review-specific reason so
  `bakeoff show` can still guide users when auto-triage was skipped or stale.
- `run_triage` should include parsed `facet` metadata in the triage payload in
  addition to the raw `work_order_json`. The triage prompt should treat the
  facet as context for actionability, not as a new schema.
- `triage_state` should compare the existing `work_order_sha256` from
  `compute_input_hashes`, not only `decision_sha256` and `report_sha256`. That
  makes changing only the facet invalidate stale triage.

## Implementation Steps

1. Update `src/bakeoff/work_order.py`.
   - Add `_validate_facet`.
   - Normalize optional `facet` in `validate_work_order`.
   - Reject unknown facet keys, invalid `facet.kind`, duplicate provider/facet
     ids, and invalid `facet.id` with precise `ValidationError` messages.
   - Add a dedicated `review_template()` for the review recipe.
   - Do not add commented facet stubs to the regular gather/compare/analyze
     templates. Only the review recipe carries a facet by default.
   - Keep `schema_version` at 1 because this is an optional backward-compatible
     field.

2. Update `src/bakeoff/providers.py`.
   - Add one seam: `render_facet_block(facet)`.
   - Insert a `{FACET_INSTRUCTIONS}` placeholder into worker prompts after
     `<scope>`.
   - Add facet-aware judge guidance to gather, compare, and analyze prompts.
   - Add optional gather judge `out_of_facet_claims[]` instructions for
     observability.
   - Keep all existing output schemas unchanged.

3. Update `src/bakeoff/cli.py`.
   - Add `INIT_KINDS = (*MODES, "review")` for init parser choices.
   - Let `bakeoff init review` write a gather work order from a review recipe
     without adding `"review"` to `MODES`.
   - Add `--no-triage` to `bakeoff research`.
   - Auto-run triage after successful `code-review` research unless
     `--no-triage` is set.
   - Print `facet: <id>` in `print_validation_summary` and `print_run_header`
     when present.
   - Store facet metadata in `meta.json`.
   - Keep provider execution topology unchanged.

4. Update `src/bakeoff/report.py`.
   - Render `Facet: <id>` near the report mode/decision.
   - Optionally render `Facet Focus: <focus>` if present.
   - For faceted gather reports, explicitly say corroboration is worker overlap
     within the shared facet, not proof of correctness.
   - Render optional gather judge `out_of_facet_claims[]` under a non-actionable
     section.

5. Update `src/bakeoff/triage.py`.
   - Add `should_auto_triage`.
   - Make `should_recommend_triage` facet-aware for `code-review`.
   - Compare `work_order_sha256` in `triage_state`.
   - Keep facet handling opaque: triage receives it in payload and prompt, but
     does not branch on facet internals except for recommendation and
     auto-triage policy.

6. Add examples and docs.
   - Add `examples/review.work-order.json`.
   - Document facets in `README.md`.
   - Keep wording clear that facets are task filters, not personas.

7. Add tests.
   - Work-order validation accepts a valid facet and rejects invalid shape.
   - Validation rejects `facet.id` collisions with provider ids.
   - Prompt tests verify facet wording says "not a persona" and preserves
     citation/schema priority.
   - Init tests verify `init review` writes `type: "gather"`.
   - End-to-end fake-provider tests verify facet metadata lands in `meta.json`
     and the report header.
   - Rerun tests verify facet metadata and work-order hashes round-trip.
   - Triage tests verify `code-review` auto-triage policy, `--no-triage`, and
     stale detection when only `work-order.json`/facet changes.
   - Gather report tests verify single-worker corroboration wording under a
     shared facet and rendering of optional `out_of_facet_claims[]`.

## Rejected Alternatives

### Add A `review` Core Module

Rejected for v1. Code review is a strong use case, but it is still mostly
coverage research plus post-judge triage. A new mode would require new schemas,
new judge contracts, new report rendering, and new triage logic before repeated
usage proves the generic claim model is insufficient.

### Add `--recipe review` Instead Of `init review`

Rejected for v1. A recipe flag is technically tidy, but it makes the common path
less discoverable and introduces a second init dispatch concept. `init review`
is clear as long as `review` is kept out of `MODES` and handled as an init-only
kind.

### Add A Separate `bakeoff review` Subcommand

Rejected for v1. It would imply a separate execution path. The recipe should
produce an ordinary gather work order so validation, rerun, reports, and triage
stay on the existing ledger model.

### Add Provider-Level Lenses

Rejected for v1. Provider-specific lenses are appealing for "security model vs
frontend model" experiments, but they break the current meaning of gather
corroboration and make compare/analyze scoring harder to interpret. If this
becomes necessary, implement it as a later explicit `facet_matrix` or launcher
workflow that creates multiple normal pairwise runs and a final synthesis run.

### Add Multi-Agent Debate Or Swarms

Rejected. The research is mixed, cost scales quickly, and Bakeoff's strongest
property is that a run is small, replayable, and auditable. Swarms would require
new scheduling, budgeting, topology, and report semantics.

### Use Persona Prompts

Rejected. The evidence is too mixed for factual/code tasks. Facets should say
what evidence to prioritize, not who the model should pretend to be.

## Follow-Up Work If The Recipe Proves Valuable

Only consider these after several real review runs:

- A `facet_matrix` launcher outside the core modes that runs separate pairwise
  bakeoffs for `security`, `frontend`, and `architecture`, then creates a final
  `gather` work order over the generated reports.
- A stricter code-review claim schema with optional `category`, `severity`, and
  `recommended_action`, but only if report and triage consumers need those
  fields.
- A branch-diff helper that writes context into `background`, while still making
  the user approve the generated work order before running providers.

## Success Criteria

- Existing gather/compare/analyze work orders behave exactly as before.
- A faceted work order produces prompts that narrow attention without changing
  schemas or citation requirements.
- `review` gives users a useful code-review starting point without creating a
  new module.
- `code-review` runs auto-triage by default and can skip it with `--no-triage`.
- Reports and meta artifacts make the facet auditable.
- Stale triage detection catches changes to decision, report, or work order
  facet.
