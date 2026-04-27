# New Preset Creation Flow Plan

## Goal

Add a first-class "New Preset" flow to the swarmdaddy TUI that can create a
fully usable preset from scratch without forcing users to rebuild known stock
graphs one stage at a time.

The flow must satisfy two jobs:

1. Fast path: recreate an existing preset family such as `balanced`, `research`,
   or `review` with minimal clicks and safe defaults.
2. Builder path: start from a blank graph and add stacks, modules, or individual
   stages manually.

The fast path is the primary UX. Blank graph editing is still supported, but it
is not the happy path for recreating an existing preset shape.

## Resolved Decisions

- Recipe specs are hand-authored in code, not auto-derived at runtime from stock
  TOML/YAML files. Tests compare them against stock fixtures so drift is caught.
- New recipe/catalog types live in a new module:
  `py/swarm_do/pipeline/recipes.py`.
- TUI-only creation draft helpers live in `py/swarm_do/tui/state.py`.
- Persistence helpers live beside existing preset mutation helpers in
  `py/swarm_do/pipeline/actions.py`.
- `NewPresetModal` lives in `py/swarm_do/tui/app.py` with the existing
  `ModalScreen` classes and is launched by `PresetWorkbenchScreen`.
- The new flow coexists with current fork, detach, route-edit, and save helpers.
  Existing stock and user presets are not migrated or rewritten.

## Current Constraints

- The Presets workbench is `PresetWorkbenchScreen` in
  `py/swarm_do/tui/app.py`. It already owns Overview, Graph, Routing, and Budget
  & Policy tabs.
- Existing graph edits operate on user presets with inline pipeline snapshots.
- `save_user_preset_graph(...)` assumes the user preset already exists.
- `schema_lint_pipeline(...)` rejects empty `stages`, so a blank graph can only
  be an unsaved TUI draft until at least one stage exists.
- `actions.activate_preset(name)` writes the active preset via
  `current_preset_path()` and `atomic_write_text(...)`.
- `validate_preset_mapping(...)` is the creation-time validation gate.
- `validate_pipeline_draft(...)` is the draft validation gate and also applies
  activation/profile readiness checks.

## File Layout

### `py/swarm_do/pipeline/recipes.py`

Owns stable, testable recipe data and pure builders.

Add:

- `PresetRecipeSpec`
- `RoutingPackageSpec`
- `GraphStackSpec`
- `NewPresetBuildResult`
- `list_preset_recipes()`
- `get_preset_recipe(recipe_id)`
- `list_routing_packages()`
- `get_routing_package(package_id)`
- `list_graph_stacks()`
- `get_graph_stack(stack_id)`
- `build_recipe_preset(recipe_id, name, description=None, routing_package_id=None)`
- `build_blank_preset_draft(name, description)`
- `apply_graph_stack(pipeline, stack_id, mode)`

This module may import graph templates from stock fixtures at test time, but the
runtime recipe definitions should be explicit Python data. Runtime creation must
not depend on reading stock `presets/*.toml` and `pipelines/*.yaml` files.

### `py/swarm_do/pipeline/actions.py`

Add persistence helpers:

- `create_user_preset_graph(preset_name, preset_mapping, *, activate=False)`
- `suggest_user_preset_name(stem, *, suffix="custom")`

`create_user_preset_graph(...)` should:

1. validate the preset name using `validate_preset_name`
2. reject existing preset or pipeline name collisions
3. require `origin = "user"`
4. require `pipeline_inline`
5. validate with `validate_preset_mapping(..., include_budget=False)`
6. write `${CLAUDE_PLUGIN_DATA}/presets/<name>.toml` with `render_toml`
7. call `activate_preset(name)` only when `activate=True`

It should not replace `fork_preset`, `fork_preset_and_pipeline`,
`detach_preset_graph`, or `save_user_preset_graph`.

### `py/swarm_do/tui/state.py`

Add TUI draft helpers:

- `PresetCreationDraft`
- `start_blank_preset_draft(name, description)`
- `new_preset_preview(recipe_id, name, routing_package_id)`
- `validate_creation_draft(draft)`
- `draft_apply_graph_stack(draft, stack_id, mode)`

Blank drafts may contain `stages = []`, but validation must report the existing
pipeline schema error and save/create must remain disabled until valid.

### `py/swarm_do/tui/app.py`

Add:

- `NewPresetModal(ModalScreen[NewPresetRequest | None])`
- `GraphStackModal(ModalScreen[GraphStackRequest | None])`
- `PresetWorkbenchScreen.action_new_preset`
- `PresetWorkbenchScreen.action_add_stack`

Bindings:

- `N` -> `new_preset`
- `M` -> `add_stack`
- keep existing `m` -> `add_module`
- keep existing `n` -> `edit_lenses`

`NewPresetModal` is pushed by `PresetWorkbenchScreen`. On dismiss:

- recipe request: build and write the preset immediately, refresh the gallery,
  select the new preset, and show Overview or Graph
- blank request: create an unsaved draft, switch to Graph, and show the empty
  validation rail
- create and activate request: write first, then call `actions.activate_preset`

The Graph tab should gain a visible action strip above `PipelineLayerBoard`:

- Add Stack
- Add Module
- Add Agent Stage
- Add Fan-Out
- Add Provider
- Edit Dependencies
- Remove

## Recipe Source Of Truth

Recipes are hand-authored from the current stock files. The writer should use
the stock files as fixtures and tests as drift protection, not as runtime input.

Stock fixture locations:

- presets: `presets/*.toml`
- pipelines: `pipelines/*.yaml`

Recipe tests must fail when the recipe output no longer matches the intended
stock graph or policy.

## Fast Path UX

Starting on the Presets screen:

1. User presses `N` or clicks `New Preset`.
2. `NewPresetModal` opens with `Implementation` selected.
3. Variant defaults to `Balanced default`.
4. Name is generated with the general collision rule.
5. Preview shows graph, routing, provider, budget, and validation status.
6. User presses `Enter` on `Create Preset`, or `A` for `Create & Activate`.
7. The TUI writes a user preset with `pipeline_inline`, refreshes the gallery,
   selects the new preset, and opens Overview.

For the default balanced recipe, the required actions after entering the Presets
screen are:

- `N`
- `Enter`

For create and activate:

- `N`
- `A`

No post-create activation prompt should appear.

## Name Collision Policy

Generated names use this algorithm:

1. Start from the recipe stem, for example `balanced`.
2. If no preset or pipeline exists with that name, use it.
3. Otherwise try `<stem>-custom`.
4. Otherwise try `<stem>-custom-2`, `<stem>-custom-3`, and so on.
5. Reject anything that fails `actions.NAME_RE`.
6. Reject names that collide with either `find_preset(name)` or
   `find_pipeline(name)`.

Typed names do not silently change. If the user edits the generated name to a
colliding or invalid value, show an inline error and disable Create.

## Validation Preview

The preview should build the exact preset mapping that would be written and run:

- `validate_preset_mapping(preset, preset_name, include_budget=False)`
- `pipeline_activation_error(pipeline_name, pipeline)` for the resolved graph

Preview states:

- Ready: no errors
- Warning: warnings only; Create remains enabled
- Blocked: errors; Create and Create & Activate are disabled

Blocked UI content:

- a one-line red status in the preview header
- first three errors visible
- "show all" expands the full error list
- the same errors appear in the Graph validation rail after blank draft creation

Creation should never write a preset when preview validation is blocked.

## Activation Behavior

`Create & Activate` performs creation first, then activation:

1. call `actions.create_user_preset_graph(..., activate=False)`
2. reload and revalidate the written preset
3. call `actions.activate_preset(name)`
4. refresh the gallery and status bar

Activation uses the existing action helper, which writes
`${CLAUDE_PLUGIN_DATA}/current-preset.txt` through `current_preset_path()`.

If activation fails after write, keep the new preset and show "Preset created,
activation refused" with validation errors.

## Graph Stack Semantics

`Add Stack` inserts an ordered graph stack into the current draft.

On an empty graph:

- apply the selected stack immediately

On a non-empty graph:

- show mode choices: `Append missing`, `Replace graph`, `Cancel`
- default focus is `Cancel`

Append missing:

- add only stack stages whose IDs are not already present
- refuse if a stage ID collides but the existing stage differs from the stack
  template
- refuse if any dependency points to a missing stage after append resolution
- preserve existing preset policy, routing, name, and description

Replace graph:

- replace only `pipeline_inline.stages` and graph-level metadata supplied by the
  stack
- preserve preset name, description, routing, budget, decompose, memory priming,
  and review provider policy unless the user explicitly chooses "replace policy"
  in an advanced option

## Dependency Defaults

Do not use fuzzy language like "nearest valid review input." Use deterministic
rules.

When adding individual modules/stages, default `depends_on` as follows:

- `analysis`: `["research"]` when `research` exists, otherwise none
- `clarify`: `["research"]` when `research` exists, otherwise none
- `exploration`: `["research"]` when `research` exists, otherwise none
- `advisor`: `["analysis", "clarify"]` for whichever of those stages exist
- `writer`: `["analysis", "clarify"]` for whichever exist; if neither exists,
  require the user to choose dependencies
- `writers`: same as `writer`
- `clean-review`: `["writer"]`
- `revise-writer`: `["writer", "clean-review"]`
- `spec-review`: first existing writer output from `revise-writer`, `writers`,
  then `writer`
- `provider-review`: first existing writer output from `revise-writer`,
  `writers`, then `writer`
- `mco-review`: first existing writer output from `revise-writer`, `writers`,
  then `writer`
- `codex-review`: `["spec-review"]` when present, otherwise require user input
- `review`: all existing final review inputs from `spec-review`,
  `provider-review`, `mco-review`, and `codex-review`; if none exist, use the
  first existing writer output from `revise-writer`, `writers`, then `writer`
- `docs`: `["spec-review"]` when present, otherwise require user input

After applying defaults, always run topological validation.

## Routing Packages

Routing packages live in `py/swarm_do/pipeline/recipes.py` as explicit
`RoutingPackageSpec` values.

### `balanced`

Routes:

- `roles.agent-docs`: codex, `gpt-5.4-mini`, medium
- `roles.agent-spec-review`: codex, `gpt-5.4-mini`, medium
- `roles.agent-clarify`: codex, `gpt-5.4-mini`, medium
- `roles.agent-writer.simple`: codex, `gpt-5.4-mini`, medium

### `claude-only`

Routes:

- `roles.agent-research`: claude, `claude-sonnet-4-6`, high
- `roles.agent-analysis`: claude, `claude-opus-4-7`, xhigh
- `roles.agent-debug`: claude, `claude-opus-4-7`, xhigh
- `roles.agent-clarify`: claude, `claude-sonnet-4-6`, medium
- `roles.agent-writer.simple`: claude, `claude-haiku-4-5`, medium
- `roles.agent-writer.moderate`: claude, `claude-sonnet-4-6`, high
- `roles.agent-writer.hard`: claude, `claude-opus-4-7`, high
- `roles.agent-spec-review`: claude, `claude-sonnet-4-6`, medium
- `roles.agent-review`: claude, `claude-opus-4-7`, high
- `roles.agent-docs`: claude, `claude-sonnet-4-6`, medium
- `roles.agent-codex-review`: claude, `claude-opus-4-7`, high

### `codex-only`

Routes:

- `roles.agent-research`: codex, `gpt-5.4`, high
- `roles.agent-analysis`: codex, `gpt-5.4`, xhigh
- `roles.agent-debug`: codex, `gpt-5.4`, xhigh
- `roles.agent-clarify`: codex, `gpt-5.4-mini`, medium
- `roles.agent-writer.simple`: codex, `gpt-5.4-mini`, medium
- `roles.agent-writer.moderate`: codex, `gpt-5.4`, high
- `roles.agent-writer.hard`: codex, `gpt-5.4`, xhigh
- `roles.agent-spec-review`: codex, `gpt-5.4-mini`, medium
- `roles.agent-review`: codex, `gpt-5.4`, high
- `roles.agent-docs`: codex, `gpt-5.4-mini`, medium
- `roles.agent-codex-review`: codex, `gpt-5.4`, high
- `roles.agent-analysis-judge`: claude, `claude-opus-4-7`, high
- `roles.agent-writer-judge`: claude, `claude-opus-4-7`, high
- `roles.agent-code-synthesizer`: claude, `claude-opus-4-7`, xhigh

### Recipe-Specific Packages

These may be represented as package IDs or embedded recipe routing:

- `lightweight`: `roles.agent-clarify` and `roles.agent-writer.simple` to
  codex `gpt-5.4-mini` medium
- `hybrid-review`: `roles.agent-codex-review` to codex `gpt-5.4` high
- `ultra-plan`: `roles.agent-analysis.hard` to Claude Opus xhigh,
  `roles.agent-analysis-judge` to Claude Opus high, and
  `roles.agent-writer.hard` to Claude Opus high
- `repair-loop`: balanced routes plus `roles.agent-clean-review` to codex
  `gpt-5.4` high
- `smart-friend`: balanced routes plus named route `smart-advisor` to Claude
  Opus high
- `competitive`: `roles.agent-analysis` to Claude Opus xhigh and
  `roles.agent-writer-judge` to codex `gpt-5.4` high
- `research`: `roles.agent-research` to Claude Sonnet high and
  `roles.agent-research-merge` to Claude Opus high
- `brainstorm`: `roles.agent-brainstorm` to Claude Sonnet high and
  `roles.agent-brainstorm-merge` to Claude Opus high
- `design`: `roles.agent-research` to Claude Sonnet high,
  `roles.agent-analysis` to Claude Opus xhigh,
  `roles.agent-analysis-judge` to Claude Opus high, and
  `roles.agent-clarify` to Claude Sonnet medium
- `review` and `review-strict`: `roles.agent-review` to Claude Opus high

## Recipe Catalog

All recipes should produce user presets with `origin = "user"` and an inline
pipeline graph.

### Balanced Default

Intent: Implementation

Graph:

- `research`: agents `agent-research`
- `analysis`: depends on `research`, agents `agent-analysis`
- `clarify`: depends on `research`, agents `agent-clarify`
- `writer`: depends on `analysis`, `clarify`, agents `agent-writer`
- `spec-review`: depends on `writer`, agents `agent-spec-review`
- `provider-review`: depends on `writer`, provider `swarm-review`, command
  `review`, selection `auto`, output `findings`, memory false,
  timeout_seconds 1800, max_parallel 4, failure_tolerance best-effort
- `review`: depends on `spec-review`, `provider-review`, agents `agent-review`
- `docs`: depends on `spec-review`, agents `agent-docs`

Policy:

- routing package `balanced`
- review_providers selection auto, min_success 1, max_parallel 4
- budget 80 agents, $20, 14400 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff
- decompose off
- mem_prime off, 500 tokens, 90 days, min_relevance 0.6, adapter
  `dispatch_file`

### Claude-Only Diagnostic

Use the Balanced Default graph and the `claude-only` routing package.

Policy differences:

- budget estimated cost $30

### Codex-Only Fallback

Use the Balanced Default graph and the `codex-only` routing package.

Policy differences:

- budget estimated cost $20

### Lightweight

Graph:

- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writer`: depends on `analysis`, `clarify`
- `provider-review`: depends on `writer`, same provider settings as balanced
- `review`: depends on `writer`, `provider-review`

Policy:

- recipe-specific lightweight routes
- review_providers selection auto, min_success 1, max_parallel 4
- budget 40 agents, $10, 7200 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff
- decompose off
- mem_prime default off settings

### Hybrid Review

Graph:

- Balanced Default graph plus `codex-review`
- `codex-review`: depends on `spec-review`, agents `agent-codex-review` with
  backend codex, model `gpt-5.4`, effort high, failure_tolerance best-effort
- final `review`: depends on `spec-review`, `provider-review`, `codex-review`

Policy:

- recipe-specific hybrid-review route
- review_providers selection auto, min_success 1, max_parallel 4
- budget 100 agents, $25, 14400 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff

### Ultra Plan

Graph:

- `research`: agents `agent-research`
- `exploration`: depends on `research`, fan_out role `agent-analysis`, count 3,
  variant `prompt_variants`, variants `explorer-a`, `explorer-b`,
  `explorer-c`, merge synthesize by `agent-analysis-judge`,
  failure_tolerance quorum min_success 2
- `clarify`: depends on `research`, agents `agent-clarify`
- `writer`: depends on `exploration`, `clarify`, agents `agent-writer`
- `spec-review`: depends on `writer`
- `provider-review`: depends on `writer`, same provider settings as balanced
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy:

- recipe-specific ultra-plan routes
- review_providers selection auto, min_success 1, max_parallel 4
- budget 120 agents, $35, 21600 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff

### Repair Loop

Graph:

- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writer`: depends on `analysis`, `clarify`
- `clean-review`: depends on `writer`, agents `agent-clean-review`
- `revise-writer`: depends on `writer`, `clean-review`, agents
  `agent-writer`, failure_tolerance best-effort
- `spec-review`: depends on `revise-writer`
- `provider-review`: depends on `revise-writer`, same provider settings as
  balanced
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy:

- recipe-specific repair-loop routes
- review_providers selection auto, min_success 1, max_parallel 4
- budget 100 agents, $28, 18000 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff

### Smart Friend

Graph:

- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `advisor`: depends on `analysis`, `clarify`, agents
  `agent-implementation-advisor` routed through named route `smart-advisor`
- `writer`: depends on `analysis`, `clarify`, `advisor`
- `spec-review`: depends on `writer`
- `provider-review`: depends on `writer`, same provider settings as balanced
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy:

- recipe-specific smart-friend routes
- review_providers selection auto, min_success 1, max_parallel 4
- budget 100 agents, $25, 18000 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff

### Competitive Implementation

Graph:

- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writers`: depends on `analysis`, `clarify`, fan_out role `agent-writer`,
  count 2, variant `models`
- writer branch route 1: claude, `claude-opus-4-7`, xhigh
- writer branch route 2: codex, `gpt-5.4`, xhigh
- merge: strategy synthesize, agent `agent-writer-judge`
- failure_tolerance: strict
- `spec-review`: depends on `writers`
- `review`: depends on `spec-review`
- `docs`: depends on `spec-review`

Policy:

- recipe-specific competitive routes
- no provider stage
- no provider timeout values apply
- no review_providers table required
- budget 120 agents, $40, 21600 seconds, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff

### Research Memo

Graph:

- `research`: fan_out role `agent-research`, count 3, variant
  `prompt_variants`, variants `codebase-map`, `prior-art-search`,
  `risk-discovery`, merge synthesize by `agent-research-merge`,
  failure_tolerance quorum min_success 2

Policy:

- recipe-specific research routes
- budget 20 agents, $8, 7200 seconds
- output-only

### Brainstorm

Graph:

- `brainstorm`: fan_out role `agent-brainstorm`, count 3, variant
  `prompt_variants`, variants `expand-options`,
  `constraints-and-failure-modes`, `analogies-and-transfers`, merge synthesize
  by `agent-brainstorm-merge`, failure_tolerance quorum min_success 2

Policy:

- recipe-specific brainstorm routes
- budget 20 agents, $8, 7200 seconds
- output-only

### Design Plan

Graph:

- `research`: agents `agent-research`
- `exploration`: depends on `research`, fan_out role `agent-analysis`, count 4,
  variant `prompt_variants`, variants `explorer-a`, `explorer-b`,
  `explorer-c`, `security-threat-model`, merge synthesize by
  `agent-analysis-judge`, failure_tolerance quorum min_success 3
- `clarify`: depends on `research`, agents `agent-clarify`
- `recommendation`: depends on `research`, `exploration`, `clarify`, agents
  `agent-analysis`

Policy:

- recipe-specific design routes
- budget 60 agents, $20, 14400 seconds
- output-only

### Review Evidence

Graph:

- `provider-review`: provider `swarm-review`, command `review`, selection
  `auto`, output `findings`, memory false, timeout_seconds 1800,
  max_parallel 4, failure_tolerance best-effort
- `review`: depends on `provider-review`, fan_out role `agent-review`, count 5,
  variant `prompt_variants`, variants `correctness-rubric`, `api-contract`,
  `security-threat-model`, `performance-review`, `edge-case-review`, merge
  synthesize by `agent-review`, failure_tolerance quorum min_success 3

Policy:

- recipe-specific review route
- review_providers selection auto, min_success 1, max_parallel 4
- budget 30 agents, $12, 7200 seconds
- output-only

### Strict Review Evidence

Graph:

- same as Review Evidence, except provider-review failure_tolerance is quorum
  min_success 2

Policy:

- recipe-specific review route
- review_providers selection auto, min_success 2, max_parallel 4
- budget 35 agents, $16, 9000 seconds
- output-only

## Blank Builder Path

Blank graph creation flow:

1. User presses `N`.
2. User chooses `Blank graph`.
3. User enters or accepts generated name and description.
4. TUI creates an unsaved `PresetCreationDraft`.
5. TUI switches to Graph.
6. Validation rail shows `pipeline: stages must be a non-empty array`.
7. User adds a stack, module, or stage.
8. Save becomes enabled only after validation passes.

Manual recreation of `balanced` through blank builder:

1. `N`
2. choose `Blank graph`
3. `Add Stack`
4. choose `Default implementation`
5. accept selected modules
6. choose routing package `balanced`
7. save

This path is intentionally longer than the recipe path because the user chose
custom graph building.

## Backwards Compatibility

The new flow is additive.

- Existing stock presets stay read-only.
- Existing user presets continue to load, edit, detach, save, rename, delete,
  diff, and activate through current helpers.
- Existing `pipeline = "stock-name"` user presets are not migrated to inline
  graphs.
- New recipe-created presets use `pipeline_inline` because they are user-owned
  created artifacts.
- Existing `fork_preset_and_pipeline` remains available for stock-edit flows.
- Existing `save_user_preset_graph` remains the save path for an existing user
  preset graph draft.
- New blank drafts use the new creation helper on first save, then use existing
  save behavior after the preset exists.

## Test Plan

### Pipeline Recipe Unit Tests

File: `py/swarm_do/pipeline/tests/test_recipes.py`

Assertions:

- `list_preset_recipes()` includes every recipe ID named in this plan.
- `build_recipe_preset("balanced-default", "balanced-custom")` validates with
  `validate_preset_mapping`.
- generated balanced graph stages exactly match `pipelines/default.yaml` in IDs,
  dependencies, stage kinds, provider settings, and failure tolerance.
- generated balanced preset policy exactly matches `presets/balanced.toml`
  except for `name`, `origin`, graph source form, and generated metadata.
- high-confidence recipes produce the exact stage IDs and dependency edges
  listed in this plan.
- competitive recipe has writer fan_out count 2, model routes, synthesize merge
  by `agent-writer-judge`, and strict failure_tolerance.
- routing packages contain the exact route keys and backend/model/effort values
  listed in this plan.
- output-only recipes validate and are marked output-only.

### Action/Persistence Tests

File: `py/swarm_do/pipeline/tests/test_pipeline_actions.py`

Assertions:

- `create_user_preset_graph` writes a TOML file under the temp
  `${CLAUDE_PLUGIN_DATA}/presets` directory.
- written preset reloads through `load_preset` and validates.
- helper rejects invalid names.
- helper rejects preset and pipeline name collisions.
- helper rejects mappings without `pipeline_inline`.
- `activate=True` writes `current-preset.txt`.
- activation failure after write leaves the created preset file in place and
  reports activation failure.

### TUI State Tests

File: `py/swarm_do/tui/tests/test_state.py`

Assertions:

- `start_blank_preset_draft` starts with empty stages and validation blocked.
- applying `default-implementation` stack to an empty draft yields the balanced
  stage order and default dependencies.
- applying a stack to a non-empty graph with append mode refuses incompatible ID
  collisions.
- replace mode replaces stages and preserves preset policy.
- dependency defaults for `review`, `provider-review`, `docs`, and
  `revise-writer` match this plan.

### TUI App Tests

File: `py/swarm_do/tui/tests/test_app.py`

Assertions:

- Preset command palette includes "Create new preset".
- `PresetWorkbenchScreen` has binding `N -> new_preset`.
- `NewPresetModal` defaults to Implementation / Balanced default.
- creating balanced through the modal writes a user preset, selects it in the
  gallery, and shows valid preview state.
- `Create & Activate` calls the action path that updates active preset state.
- blank graph flow opens the Graph tab and shows the empty-stage validation
  message.

## Per-Workstream Definition Of Done

### Recipe Catalog

Done when:

- `py/swarm_do/pipeline/recipes.py` defines all recipe, routing package, and
  graph stack specs named in this plan.
- every recipe builds a preset mapping with `origin = "user"` and
  `pipeline_inline`.
- recipe unit tests validate all recipes and compare stock-equivalent recipes to
  stock fixtures.

### Persistence

Done when:

- `create_user_preset_graph` writes atomically through existing action helpers.
- collisions and invalid names are rejected before writing.
- create and activate behavior is covered by unit tests.
- existing fork/detach/save tests still pass.

### TUI State And Builder

Done when:

- blank preset drafts can exist without being saved.
- graph stacks can be applied with empty, append, and replace semantics.
- dependency defaults are deterministic and covered by tests.
- invalid drafts keep Save/Create disabled and show validation errors.

### TUI Modal And Workbench Integration

Done when:

- `N` opens `NewPresetModal` from `PresetWorkbenchScreen`.
- recipe creation takes `N`, `Enter` for the balanced default happy path.
- `N`, `A` creates and activates.
- Graph tab exposes the action strip.
- modal, preview, gallery refresh, selection, and status behavior are covered by
  Textual `run_test` tests.

### Documentation

Done when:

- `tui/README.md` documents New Preset, recipe creation, blank builder, and
  activation behavior.
- `README.md` command/TUI overview mentions user-created inline presets.
- this plan remains linked or referenced from implementation PR notes.

## Validation Checklist For This Plan

- Bootstrap/file layout gaps are resolved by the File Layout section.
- NewPresetModal parent, pattern, bindings, and tab integration are specified in
  the TUI file layout and Fast Path UX sections.
- Recipe source is specified as hand-authored specs with stock fixture tests.
- High-confidence and competitive graphs are fully enumerated in the Recipe
  Catalog.
- Routing packages and recipe-specific routes are catalogued.
- Name collision, Add Stack non-empty semantics, dependency defaults, validation
  preview, and Create & Activate behavior are specified.
- Test files, fixture patterns, and assertion granularity are specified.
- Each implementation workstream has a Definition of Done.
- Backwards compatibility is explicitly additive and requires no migration.
