# Pipeline Composer And Lens Workbench Implementation Plan

Date: 2026-04-25

## Implementation Entry Point

When starting implementation in a new session, pass this file as the primary
plan and begin with **Phase 0.5: Lens Grounding Spike**. Do not start Phase 1
catalog APIs until the three ultra-plan lenses compile through catalog metadata
and current validation.

Use `docs/lens-catalog-v1-research.md` as supporting context for lens prompt
content, output contracts, compatibility rationale, and source notes. The main
plan carries the executable requirements; the research note carries the longer
evidence trail and per-lens sketches.

## Goal

Give swarm-do operators a practical way to choose or customize task-specific
pipelines without replacing the current preset/pipeline architecture.

The target experience is:

- Pick a pipeline by intent: brainstorm, research, design, implement, review,
  competitive implementation, or MCO-assisted review.
- Preview the execution graph before activating it.
- Fork a stock preset/pipeline into user-owned files before editing.
- Add or remove compatible pipeline modules through the TUI.
- Swap backend/model/effort routes at the preset, stage, agent, or fan-out
  branch level where the current runtime can already honor them.
- Apply task-specific prompt/rubric lenses where the runtime has a real
  execution path, without pretending generic personas are reliable.
- Validate budget, invariants, route resolution, provider readiness, and graph
  topology before saving or running.

## Current Architecture Fit

This is an incremental feature, not a new runtime.

The existing architecture already has the load-bearing pieces:

- Pipeline YAML is a DAG of stages with `agents`, `fan_out`, or `provider`
  stage kinds.
- Preset TOML binds a named pipeline to routing, budget, decomposition, and
  memory policy.
- Validation already checks graph shape, dependencies, prompt variant files,
  route resolution, budget ceilings, and structural invariants.
- The TUI already has dashboard, settings, presets, pipelines, graph preview,
  route editing, and validate/lint actions.
- MCO already exists as an experimental read-only provider stage that produces
  evidence for downstream Claude review.

The main missing pieces are:

- A first-class module catalog that describes which stage snippets are safe to
  add, remove, or configure.
- User pipeline persistence helpers. Today the TUI can set a user preset's
  pipeline, but it does not create or mutate user pipeline YAML.
- User preset/pipeline fork helpers. Route edits and pipeline selection are
  saved on presets, so the composer needs a single fork-first workflow for both
  TOML and YAML artifacts.
- A typed lens catalog. Today routing lenses live in presets, and prompt/rubric
  lenses only exist for `fan_out.variant: prompt_variants`.
- A TUI workbench that guides composition instead of showing raw graph text.

## Recommendation

Implement a hybrid model:

1. Keep a curated set of stock pipelines for common intents.
2. Let users fork stock presets/pipelines and customize them in the TUI.
3. Save all customizations as normal user-owned TOML/YAML artifacts.
4. Run the existing validators for every save, activation, and dry run.
5. Treat lenses as task/rubric overlays with explicit compatibility metadata,
   not as free-form personality prompts.
6. Add first-class single-agent prompt lenses only after the TUI ships the
   existing-compatible version.

Do not implement an ephemeral in-memory runtime graph. Reproducibility and
debuggability matter more than avoiding small user files.

An editor draft is still allowed inside the TUI. Draft state is an unsaved
transaction for multi-step edits such as fan-out count plus variants plus route
updates; it must be discarded or written as validated TOML/YAML, never used as
the runtime source of truth.

## Validated Research Updates

The follow-up lens-catalog research changed several implementation details:

- Prompt/rubric variants are additive overlays, not sibling roles. The current
  runtime support is documented in `skills/swarm-do/SKILL.md`: for
  `fan_out.variant: prompt_variants`, the Claude dispatcher loads
  `roles/<role>/variants/<name>.md` and appends it to the normal role prompt.
  There is no Python prompt-assembly path today; Python only validates variant
  file existence.
- `merge.agent` cannot accept a variant overlay in v1. The schema only accepts
  `merge.strategy` and `merge.agent`, and validation rejects unknown merge
  keys. Merge-bias lenses are out of scope until a separate schema design.
- Route-resolution invariants do not constrain prompt-variant roles by backend.
  Only the orchestrator, `agent-code-synthesizer`, and synthesize merge agents
  must resolve to Claude. If a security-sensitive lens should be Claude-only,
  that must be explicit catalog metadata and validation, not an implied runtime
  invariant.
- Current fan-out schema chooses exactly one branch variation mode:
  `same`, `prompt_variants`, or `models`. A single fan-out cannot mix prompt
  variants and per-branch model routes until a future schema extension.
- The questionable "Persona Non Grata" citation is real
  (`arXiv:2604.11120`, submitted April 13, 2026; revised April 14, 2026), but
  it is a very recent preprint and should remain supporting context only. The
  load-bearing evidence for v1 is PersonaGym, question-specific rubric work,
  and agent-scaling architecture results.

## Non-Goals

- No second dispatcher.
- No new graph execution engine.
- No provider-owned merge, approval, or Beads state decisions.
- No invariant bypass or force-over-budget mode.
- No free-form arbitrary YAML editor as the primary UX.
- No visual node-canvas editor as the primary v1 UX.
- No default-on MCO stage.
- No MCO write mode.

## Product Model

Use these user-facing concepts in the TUI, mapped to existing implementation
primitives:

| User Concept | Existing Primitive | Notes |
| --- | --- | --- |
| Pipeline | `pipelines/*.yaml` | Full DAG shape. |
| Preset | `presets/*.toml` | Pipeline selection plus routing and budget. |
| Module | Stage snippet | New catalog metadata; saved into pipeline YAML. |
| Route lens | Preset routing, stage overrides, or `fan_out.variant: models` | Already supported; must be editable at the right scope. |
| Task/rubric lens | `roles/<role>/variants/*.md` with catalog metadata | Currently fan-out only. |
| Review lens | Extra review stage | Codex review and MCO review fit here. |
| Process lens | Optional workflow stage | Clarify, docs, spec-review, MCO, etc. |

## Lens Model

Use the word "lens" for a narrow, testable change in how a role evaluates or
produces work. Avoid presenting lenses as broad personas. The strongest
available patterns from metaswarm, ChatDev, MetaGPT, AutoGen, and CAMEL are
role specialization, explicit output contracts, structured review rubrics, and
orchestrated handoffs. Persona-prompting research is more mixed: task-aligned
or instance-aligned personas can help, but generic roles often have small,
unstable, or random effects.

Reference anchors:

- [metaswarm](https://github.com/dsifry/metaswarm): specialist agents,
  parallel review gates, cross-model review, and knowledge priming rather than
  ad hoc personas.
- [ChatDev](https://aclanthology.org/2024.acl-long.810/),
  [MetaGPT](https://huggingface.co/papers/2308.00352),
  [AutoGen](https://www.microsoft.com/en-us/research/publication/autogen-enabling-next-gen-llm-applications-via-multi-agent-conversation-framework/),
  and [CAMEL](https://huggingface.co/papers/2303.17760): role specialization
  works best when it is paired with explicit protocols, communication structure,
  or SOPs.
- Persona-prompting studies such as
  [Hu and Collier 2024](https://aclanthology.org/2024.acl-long.554/),
  [Zheng et al. 2024](https://aclanthology.org/2024.findings-emnlp.888/),
  [Lutz et al. 2025](https://aclanthology.org/2025.findings-emnlp.1261/),
  [Kim et al. 2025](https://aclanthology.org/2025.findings-ijcnlp.51/), and
  [Solo Performance Prompting](https://arxiv.org/abs/2307.05300) all support a
  cautious stance: prefer task-aligned, instance-aware, measurable lenses over
  generic social-role prompts.
- [PersonaGym](https://aclanthology.org/2025.findings-emnlp.368/) reinforces
  that persona behavior needs task-specific evaluation rather than trust in a
  generic role label.
- [Rubric Is All You Need](https://doi.org/10.1145/3702652.3744220)
  (ACM ICER 2025) is directly relevant to the review-lens design: narrow,
  question-specific rubrics outperformed question-agnostic rubrics for
  LLM-based code evaluation.
- [Google Research's agent-scaling study](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)
  supports central orchestration for parallelizable work and warns against
  adding agents to sequential or tool-heavy tasks without a reason.

Therefore every non-route lens in the catalog should include:

- Stable lens id, label, description, and category.
- Compatible roles and stage kinds.
- Whether it is `fan_out_only`, `single_agent`, `review_only`, or
  `provider_evidence`.
- Output contract and merge expectations.
- Conflicts or stacking limits.
- Safety notes, including whether the lens is adversarial, security-sensitive,
  or experimental.
- Evaluation tags for later telemetry comparison.

Good v1 lenses should read like task lenses or rubrics: `architecture-risk`,
`api-contract`, `state-data`, `security-threat-model`,
`correctness-rubric`, `performance-review`, `edge-case-review`,
`prior-art-search`, `codebase-map`, and `risk-discovery`. `ux-flow` stays
deferred until the runtime has a UI-aware evidence path. Open-ended
demographic, temperament, or style personas need more evidence before they
belong in stock catalogs.

### Lens Catalog Contract

The canonical metadata source is `py/swarm_do/pipeline/catalog.py`. Variant
Markdown files remain prompt prose only. Do not split metadata between Markdown
frontmatter and a Python/sidecar catalog unless one side is generated from the
other.

Each prompt/rubric lens entry must include:

- `lens_id`, display label, category, description, and stability level.
- `role`, `stage_kinds`, and execution mode (`fan_out_only` for all v1 prompt
  lenses).
- `variant_name` and `variant_path`, because the public lens id may differ from
  the existing file basename such as `explorer-a`.
- Host role output contract sections, allowed tags inside those sections, and
  a hard "do not change output schema" rule.
- Merge agent expectation, conflict list, stacking policy, safety notes,
  route constraints if any, and telemetry/evaluation tags.

Compatibility matrix for v1 prompt lenses:

| Lens | `agent-research` fan-out | `agent-analysis` fan-out | `agent-review` fan-out | Provider stage | Normal `agents` / merge |
| --- | --- | --- | --- | --- | --- |
| `architecture-risk` |  | yes |  |  | Phase 5+ only |
| `api-contract` |  | yes | yes |  | Phase 5+ only |
| `state-data` |  | yes |  |  | Phase 5+ only |
| `prior-art-search` | yes |  |  |  | Phase 5+ only |
| `codebase-map` | yes |  |  |  | Phase 5+ only |
| `risk-discovery` | yes |  |  |  | Phase 5+ only |
| `security-threat-model` |  | yes | yes |  | Phase 5+ only |
| `correctness-rubric` |  |  | yes |  | Phase 5+ only |
| `performance-review` |  |  | yes |  | Phase 5+ only |
| `edge-case-review` |  |  | yes |  | Phase 5+ only |
| `mco-evidence` |  |  |  | MCO review only | no |
| `ux-flow` | deferred | deferred | deferred |  | no |

The first catalog implementation should seed the existing ultra-plan triad:

| Lens id | Existing variant file | Output contract rule |
| --- | --- | --- |
| `architecture-risk` | `roles/agent-analysis/variants/explorer-a.md` | Preserve `agent-analysis` sections; bias `Risks`, `Why Not`, and `Out of Scope` toward coupling, reversibility, and migration risk. |
| `api-contract` | `roles/agent-analysis/variants/explorer-b.md` | Preserve `agent-analysis` sections; bias assumptions, risks, and tests toward CLI/API/schema/file-format compatibility. |
| `state-data` | `roles/agent-analysis/variants/explorer-c.md` | Preserve `agent-analysis` sections; bias risks and tests toward persisted state, ledgers, hashes, migrations, and cross-run comparability. |

`security-threat-model` is safety-sensitive but not Claude-pinned by the
current runtime. If Phase 1 chooses to pin it, add an explicit catalog
`route_constraint` and validation error.

Research to keep tracking:

- Whether task/rubric lenses measurably improve swarm-do outcomes by role.
- Whether single-agent lenses reduce quality compared with fan-out plus merge.
- Whether lens stacking helps or just creates prompt conflict.
- Whether lens effectiveness changes by backend/model family.

## Proposed Stock Pipelines

Add or confirm these stock/user-visible intents:

- `brainstorm`: multi-agent ideation and synthesis, no writer.
- `research`: research fan-out plus merge, no writer.
- `design`: research, analysis/design fan-out, clarify, synthesis, no writer.
- `review`: spec/code review lanes only, no writer.
- `default`: existing end-to-end implementation pipeline.
- `lightweight`: existing small-change implementation pipeline.
- `ultra-plan`: existing planning fan-out before implementation.
- `competitive`: existing two-writer judged implementation pipeline.
- `mco-review-lab`: existing experimental MCO review evidence pipeline.

Important: output-only pipelines require command/profile work because
`/swarm-do:do` is currently plan-implementation oriented. A composer that can
create only non-runnable pipelines is a dead-end UX, so ship one minimal
research command/profile early and keep the remaining output-only command work
in Phase 4. Before a command/profile lands for a given intent, that pipeline
may be listed, previewed, linted, forked, and saved, but the TUI and CLI must
mark it `preview_only` or block activation.

## Phase 0.5: Lens Grounding Spike

### Scope

Spend 1-2 days proving the catalog shape before Phase 1 implementation locks
it in.

### Work

1. Convert three lenses into real catalog entries:
   `architecture-risk`, `api-contract`, and `state-data`.
   - Keep the existing `explorer-a/b/c` variant files runnable.
   - Map stable public lens ids to the existing `variant_name` values.
   - Record output-contract metadata and merge expectations in the catalog
     shape, not only in prose.
2. Dry-run `ultra-plan` through the existing validators and graph preview.
3. Add or prototype a deterministic prompt-bundle helper only if needed for
   tests. The runtime dispatcher remains the Claude skill; the helper's job
   would be to prove that role prompt plus overlay files resolve cleanly.
4. Confirm the TUI can display the three entries with compatibility, output
   contract, and fan-out-only status.

### Acceptance Criteria

- The three catalog entries compile from metadata to the existing
  `fan_out.variant: prompt_variants` pipeline shape.
- Missing variant files still fail validation.
- The catalog can explain why the same lens cannot be applied to a normal
  `agents` stage or a synthesize merge agent in v1.
- If the metadata cannot express the ultra-plan triad without special cases,
  redesign the catalog before starting Phase 1.

## Phase 1: Catalog And Persistence Foundation

### Scope

Add deterministic helpers with no Textual dependency.

### Files

- `py/swarm_do/pipeline/catalog.py`
- `py/swarm_do/pipeline/diff.py`
- `py/swarm_do/pipeline/render_yaml.py`
- `py/swarm_do/pipeline/actions.py`
- `py/swarm_do/pipeline/tests/test_catalog.py`
- `py/swarm_do/pipeline/tests/test_pipeline_actions.py`

### Work

1. Create a module catalog.
   - Include stable module ids, labels, descriptions, stage templates, allowed
     insertion points, required upstream/downstream stage ids, and whether the
     module is read-only, write-capable, provider-backed, or experimental.
   - Include `preview_only` and `requires_command_profile` flags for
     non-implementation pipeline intents that are not runnable through
     `/swarm-do:do`.
   - Include `requires_provider_doctor` and `experimental` metadata for MCO
     modules. Basic MCO validation and doctor gating ship here; Phase 6 is only
     advanced TUI hardening.
   - Start with: research, clarify, analysis, analysis fan-out, writer,
     spec-review, review, docs, codex-review, mco-review.

2. Create a lens catalog.
   - List route lenses from preset routing keys, stage agent overrides, named
     route references, and `fan_out.variant: models` route entries.
   - List prompt variants by scanning `roles/<role>/variants/*.md`, then enrich
     each with catalog metadata rather than exposing files as untyped personas.
   - Keep metadata canonical in `catalog.py`; variant Markdown files contain
     only the additive prompt/rubric overlay.
   - Store stable `lens_id` separately from `variant_name` so existing
     `ultra-plan` files do not need a disruptive rename.
   - Include output-contract sections, merge expectations, conflicts, safety
     notes, route constraints, and telemetry tags for every stock lens.
   - Mark prompt variants as `fan_out_only` for v1.
   - Reject incompatible role/stage/lens combinations before save.
   - Reject attempts to combine prompt-variant lenses and per-branch model
     routes in one fan-out until the schema supports both.

3. Add user preset and pipeline persistence helpers.
   - `fork_preset(source_name, new_name)`.
   - `fork_pipeline(source_name, new_name)`.
   - `fork_preset_and_pipeline(source_preset, source_pipeline, new_name)`.
   - `save_user_pipeline(name, pipeline_mapping)`.
   - `set_user_preset_pipeline(...)`.
   - `set_user_preset_route(...)`.
   - `set_stage_agent_route(...)` for inline `agents[*]` route overrides.
   - `set_fan_out_routes(...)` for `fan_out.variant: models`.
   - `reset_stage_agent_route(...)` and `reset_fan_out_routes(...)` to return
     to resolver defaults.
   - `set_user_pipeline_stage(...)` or narrow add/remove helpers.
   - Validate with `schema_lint_pipeline`, `role_existence_errors`,
     `variant_existence_errors`, route resolution where preset data is
     available, and `topological_layers`.
   - Fork names must be unique. Name collisions prompt/return a structured
     conflict; never silently overwrite a user preset or pipeline.
   - Coupled preset+pipeline forks use a staged temp-write-and-swap flow:
     validate both draft mappings, write both temp files, fsync, replace the
     pipeline, replace the preset, then clean up. If a crash leaves an orphaned
     pipeline before the preset swap, it is ignored by activation and surfaced
     by drift/cleanup tooling rather than silently becoming active.
   - User pipeline YAML should include optional metadata such as
     `forked_from`, `forked_from_hash`, and `generated_by` so stock drift and
     diffs can be computed. Existing pipelines without metadata remain valid.

4. Add a small YAML renderer for the supported pipeline subset.
   - Use structured mappings, not string concatenation in TUI code.
   - Keep output stable for diffs.
   - Declare renderer output generated-owned. Comments and unsupported
     hand-edits are not round-tripped; the TUI may refuse or warn before
     rewriting files outside the supported subset.

5. Preserve stock immutability.
   - Any mutation of a stock pipeline or stock preset must require forking.

6. Add stock-diff helpers.
   - Show user preset and user pipeline diffs against their recorded source
     artifact.
   - Detect stock drift with stored source hashes and surface advisory
     warnings. Automatic fork migration is explicitly out of scope for this
     iteration.

### Acceptance Criteria

- Unit tests cover catalog listing, stock preset fork, stock pipeline fork,
  coupled preset/pipeline fork, invalid pipeline rejection, stable YAML output,
  stock mutation rejection, route reset behavior, name collision rejection,
  coupled-fork partial failure behavior, and stock drift detection.
- Existing pipeline validation tests still pass.
- No Textual dependency is introduced below `py/swarm_do/pipeline`.

## Phase 2: TUI Pipeline Workbench

### Scope

Turn the current pipeline screen from a list/preview into a guided editor.

### Files

- `py/swarm_do/tui/app.py`
- `py/swarm_do/tui/state.py`
- `py/swarm_do/tui/app.tcss`
- `py/swarm_do/tui/tests/test_state.py`
- `tui/README.md`

### Work

1. Replace or extend `PipelinesScreen` with a workbench layout.
   - Left: pipeline gallery grouped by intent.
   - Center: selectable stage graph by topological layer.
   - Right: selected stage inspector.
   - Bottom/status: validation, budget, provider readiness, and active preset.
   - Use Textual primitives that are stable today: `ListView` or `DataTable`
     for the gallery, `Tree` or layered `DataTable` for the graph, `Static`
     for read-only details, `Select` for backend/effort/route options, `Input`
     for model ids and numeric values, `SelectionList` or checkboxes for
     provider/module multi-select, and `ModalScreen` for fork/confirm dialogs.

2. Use a table/tree graph as the primary v1 editor, not a freeform node canvas.
   - A visual node canvas is possible in Textual by implementing a custom
     `Widget` that renders Rich segments or box-drawing lines and maps mouse
     coordinates back to stage ids.
   - It is not the best primary v1 UX because this workflow is keyboard-first,
     graph edits are constrained catalog actions, and Textual does not provide
     built-in draggable nodes or edge editing.
   - Prefer a stable layered graph with selectable rows, stage badges,
     dependency text, and inspector-driven edits. Revisit a custom canvas later
     as a read-only overview if real pipelines become too dense for the table.
   - Fan-out stages need a branch table in the inspector. A single graph row can
     summarize the stage, but branch-level lens names, route entries, and
     failure-tolerance status must be visible without opening raw YAML.

3. Add graph selection behavior.
   - Selecting a stage shows role, backend/model/effort, dependencies,
     failure tolerance, merge behavior, and provider config.
   - Fan-out stages show branch count, variant kind, route entries, and merge
     agent.
   - Provider stages show provider type, selected providers, timeout, and
     read-only status.

4. Add fork-first editing.
   - If a stock pipeline/preset is selected, edit actions open a fork dialog.
   - If an edit touches both TOML and YAML, fork or create both artifacts in one
     guided transaction.
   - User-owned pipeline edits save only after validation succeeds.
   - Maintain an in-memory edit draft for multi-step changes and clearly show
     dirty, invalid, saved, and discarded states.
   - Maintain undo/redo inside the edit session. Discard-all remains available,
     but it is not the only recovery path for multi-step edits.
   - Fork dialogs must handle name collisions explicitly and offer a generated
     unique name instead of overwriting.

5. Add module palette.
   - Show only modules compatible with the selected pipeline shape.
   - For v1, use narrow add/remove actions instead of arbitrary dependency
     rewiring.
   - Include warning copy for MCO and other experimental modules.
   - MCO modules stay disabled until provider doctor/config validation passes,
     unless the user is only previewing and linting without activation.

6. Add route editor controls.
   - For normal `agents` stages, allow per-agent backend/model/effort override,
     named route selection, and reset-to-resolved-default.
   - For `fan_out.variant: models`, show one route row per branch and allow
     Claude/Codex mixing directly in the pipeline.
   - Show effective route source: stage override, named preset route, preset
     role route, base `backends.toml`, or role default.
   - Keep Claude-backed orchestrator and synthesize-merge invariants as hard
     blockers.

7. Add validation rail.
   - Reuse existing pipeline/preset validation.
   - Show hard blockers separately from warnings, grouped by severity and
     stage.
   - Allow muting advisory warnings only. Structural errors, budget breaches,
     invariant failures, missing roles/variants, and provider-doctor failures
     for active MCO stages cannot be muted.
   - Add small fix-it affordances where deterministic helpers exist, such as
     fork stock artifact, rename fork, reset route, remove incompatible module,
     or run provider doctor.
   - Include budget preview when a plan path is supplied or default to
     one-phase estimates.
   - Include provider doctor result when the graph contains MCO.
   - Block activation of `preview_only` pipelines until Phase 4 command/profile
     support exists.
   - Show diff against the source stock preset/pipeline for user forks.

### Acceptance Criteria

- TUI can browse stock pipelines, fork one, add/remove at least one safe module,
  validate it, and set it on a user preset when the pipeline is runnable.
- TUI can show and diff a user fork against its source stock artifact.
- TUI can show a non-implementation pipeline as preview-only before Phase 4 and
  refuses to activate it.
- TUI can switch an editable stage or fan-out branch between Claude and Codex
  without changing every role in the preset.
- Validation failures do not mutate files.
- Undo works within an edit session for at least route, module, and lens
  changes.
- The preview graph updates after edits.
- Stock pipelines remain read-only.
- TUI docs describe the workbench flow.

## Phase 2.5: Minimal Research Command Profile

### Scope

Ship one non-implementation command/profile before lens controls, so the
workbench has at least one output-only pipeline that can actually run.

### Files

- `commands/research.md`
- `skills/swarm-do/SKILL.md`
- possibly `py/swarm_do/pipeline/cli.py`

### Work

1. Add a research command/profile that selects a research-only preset/pipeline.
2. Reuse normal preflight, validation, permissions checks, and budget preview.
3. Define terminal behavior as an evidence memo or Beads synthesis note, with
   no writer branch, no PR, and no implementation handoff.
4. Mark the research pipeline as runnable in catalog metadata once the command
   binding exists. Brainstorm, design, and review remain `preview_only` until
   Phase 4.

### Acceptance Criteria

- A research-only pipeline can run without opening writer branches or PRs.
- The workbench can activate the research profile while continuing to block
  other preview-only non-implementation intents.

## Phase 3: Lens Controls V1

### Scope

Expose lenses that the current runtime can already execute.

### Files

- `py/swarm_do/pipeline/catalog.py`
- `py/swarm_do/pipeline/actions.py`
- `py/swarm_do/tui/app.py`
- `roles/*/variants/*.md` as needed
- tests under `py/swarm_do/pipeline/tests/` and `py/swarm_do/tui/tests/`

### Work

1. Model route lenses.
   - Show effective route from `BackendResolver`.
   - Allow preset-level route edits through existing preset routing helpers.
   - Allow stage-level route overrides for normal `agents` stages.
   - Allow per-branch route edits for `fan_out.variant: models`, including
     mixed Claude/Codex fan-out branches.
   - Allow reset-to-default and conversion between inline route objects and
     named preset route references.
   - Keep invariant-checked route validation.

2. Model task/rubric lenses for fan-out stages.
   - List available typed lens catalog entries for the stage role.
   - Allow selecting existing variants only.
   - Show lens category, output contract, merge expectation, and conflicts.
   - Enforce `count == len(variants)`.

3. Add more prompt variants where useful.
   - Research: codebase map, prior-art search, risk discovery.
   - Analysis/design: architecture risk, API contract, state/data, security.
   - Review: correctness, API contract, security, performance, edge cases.
   - Defer `ux-flow` until a UI-aware research/review role can inspect actual
     frontend artifacts or screenshots without changing the host output
     contract.

4. Keep single-agent prompt lenses out of v1 runtime.
   - The TUI can show the limitation clearly.
   - Do not invent a fake single-agent lens behavior.

### Acceptance Criteria

- A user can configure an `ultra-plan` style prompt-variant fan-out in the TUI.
- Dangling variant names are rejected by validation.
- Route edits still respect Claude-backed orchestrator and synthesis
  invariants.
- A user can see whether a lens is fan-out-only, single-agent-capable,
  review-only, or experimental before applying it.

## Phase 4: Remaining Command/Profile Support For Non-Implementation Pipelines

### Scope

Make brainstorm, design, and review pipelines runnable without pretending they
are implementation plans. Research may already be runnable from Phase 2.5; if
so, keep it here only for parity cleanup and shared profile plumbing.

### Files

- `commands/design.md`
- `commands/brainstorm.md`
- `commands/review.md`
- `commands/research.md` if Phase 2.5 did not ship it
- `skills/swarm-do/SKILL.md`
- possibly `py/swarm_do/pipeline/cli.py`

### Work

1. Add command profiles or dedicated slash commands.
   - Each command selects a preset/profile and terminal behavior.
   - Research/design/brainstorm should produce artifacts or Beads notes, not
     writer branches or PRs.

2. Keep shared preflight and validation.
   - Reuse pipeline lint, preset dry-run, permissions checks where relevant,
     and provider doctor.

3. Define terminal semantics.
   - Brainstorm: synthesis note.
   - Research: evidence memo.
   - Design: recommendation and execution-ready plan.
   - Review: findings/evidence summary.

4. Avoid changing `/swarm-do:do` into a multi-purpose mode switch unless that
   stays simpler than separate command files.

5. Mark supported command/profile bindings in the pipeline or catalog metadata.
   - Once a binding exists, the TUI can offer activation/run actions for that
     pipeline intent.
   - Until then, the workbench remains browse/fork/lint/save only for that
     intent.

### Acceptance Criteria

- Each non-implementation command has explicit output expectations.
- No non-implementation command opens a PR.
- Existing `/swarm-do:do` behavior remains unchanged for implementation plans.
- Preview-only activation guards are removed only for intents with a real
  command/profile binding.

## Phase 5: Single-Agent Lens Schema

### Scope

Add first-class lenses for normal `agents` stages only after the v1 composer
proves useful.

### Proposed Schema Extension

```yaml
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lens: architecture-risk
```

or:

```yaml
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lenses: [architecture-risk, api-contract]
```

Prefer singular `lens` for v1. `lenses: [...]` is a future schema, not a v1
alias, unless a measurement phase shows stacking improves outcomes without
prompt conflict.

### Work

1. Extend `schemas/pipeline.schema.json` with optional `agents[*].lens`.
   Existing pipelines remain valid because the new field is optional and
   defaults to no overlay; no migration is required.
2. Extend `schema_lint_pipeline` and variant existence validation.
   - Add `lens` to allowed agent keys.
   - Reject `lenses` unless/until a stacking schema ships.
   - Validate compatibility against the same catalog used for fan-out lenses.
3. Extend the dispatcher prompt contract to load the role variant overlay for
   normal agent stages.
4. Extend lens catalog metadata so single-agent lenses declare role
   compatibility, output contract, conflict rules, and evaluation tags.
5. Add tests for valid, missing, conflicting, and incompatible lenses.
6. Add TUI controls for single-agent lens selection.

### Acceptance Criteria

- Normal `agents` stages can apply one prompt overlay.
- Existing pipelines remain valid.
- Fan-out prompt variants continue to work unchanged.
- Missing lens files fail validation before a run.
- Merge agents still cannot carry variants unless a later schema explicitly
  changes `merge`.
- Lens stacking remains disabled unless a follow-up measurement phase shows it
  improves outcomes without prompt conflict.

## Phase 6: MCO Module Polish

### Scope

Keep MCO as opt-in read-only evidence, but make it easier and safer to use from
the TUI. Basic provider doctor/config validation is already required in Phases
1-2 before users can activate an MCO-bearing pipeline; this phase adds better
controls and result visibility.

### Work

1. Add MCO module controls.
   - Providers multi-select, capped by schema limits.
   - Timeout input with schema range.
   - Failure tolerance selector, default `best-effort`.

2. Run provider doctor from the TUI when MCO is present.
   - Surface missing `mco`, malformed doctor output, and unavailable providers.

3. Preserve boundaries from the provider ADR.
   - Provider output remains evidence only.
   - No provider stage owns merge, approval, memory, or repo writes.

4. Improve provider result preview when prior artifacts exist.
   - Show provider count, status, provider errors, and finding count.

### Acceptance Criteria

- TUI refuses invalid MCO provider configs before save.
- MCO remains opt-in and visibly experimental.
- Provider doctor status is visible before activation.

## Validation Strategy

Run focused tests after each phase:

```bash
PYTHONPATH=py python3 -m unittest \
  py.swarm_do.pipeline.tests.test_pipeline_validation \
  py.swarm_do.tui.tests.test_state
```

Add new test modules for catalog, YAML rendering, user preset/pipeline
persistence, route override/reset helpers, preview-only activation guards, and
TUI state helpers as those pieces land.

Manual smoke checks:

```bash
bin/swarm pipeline list
bin/swarm pipeline show ultra-plan
bin/swarm preset dry-run <user-preset> <plan-path>
bin/swarm providers doctor --mco --json
bin/swarm-tui
```

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| TUI becomes a fragile YAML editor | Use a module catalog and structured helpers. |
| Stock pipeline edits break upgradeability | Require fork-first editing. |
| Lenses imply behavior the runtime does not support | Mark v1 prompt lenses as fan-out only and require typed compatibility metadata. |
| Generic personas produce unstable or biased behavior | Prefer task/rubric lenses, measure outcomes, and keep open-ended personas out of stock catalogs. |
| Stage route edits accidentally become global role edits | Separate preset-level routes, stage overrides, named routes, and fan-out branch routes in the TUI. |
| Non-implementation pipelines collide with `/swarm-do:do` semantics | Add dedicated command profiles with explicit terminal behavior. |
| Preview-only pipelines get activated before command support exists | Block activation until a command/profile binding is present. |
| A node canvas becomes expensive before it improves editing | Use a table/tree graph for v1 and revisit a read-only canvas only if pipeline density demands it. |
| MCO expands beyond safe evidence mode | Keep provider ADR boundaries and validation hard rejects. |
| Pipeline variations become hard to compare | Persist every customized graph as user YAML/TOML and keep config hashes. |

## Caveats To Declare

1. v1 lens effectiveness is unmeasured. Ship lenses with telemetry/evaluation
   tags and expect prompt/rubric tuning.
2. Preview-only pipelines are deliberately non-runnable until a matching
   command/profile exists. Phase 2.5 should make `research` the first exception.
3. The YAML renderer is one-way for generated pipeline YAML. Hand comments and
   unsupported edits below module boundaries are not preserved.
4. Stock-fork drift detection and diff are in scope, but automatic fork
   migration is not. Users own migration decisions for this iteration.
5. Single-agent prompt lenses are explicitly out until Phase 5.

## Suggested Build Order

1. Phase 0.5 lens grounding spike.
2. Catalog and user pipeline persistence, including stock diff/drift helpers
   and basic MCO doctor gating.
3. TUI workbench with fork, graph, inspector, undo, diff, and validation rail.
4. Minimal research command/profile so one output-only flow is runnable early.
5. Existing-compatible fan-out lens controls.
6. Remaining command/profile support for brainstorm, design, and review.
7. Single-agent lens schema extension.
8. MCO TUI polish.

This order gives operators value before committing to schema changes, and keeps
the architecture anchored to the current preset/pipeline contracts.
