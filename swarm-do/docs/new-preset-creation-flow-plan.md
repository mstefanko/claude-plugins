# New Preset Creation Flow — Phased Execution Plan

## Goal

Add a first-class "New Preset" flow to the swarmdaddy TUI that can create a
fully usable preset from scratch without forcing users to rebuild known stock
graphs one stage at a time.

The flow must satisfy two jobs:

1. **Fast path**: recreate an existing preset family such as `balanced`,
   `research`, or `review` with minimal clicks and safe defaults.
2. **Builder path**: start from a blank graph and add stacks, modules, or
   individual stages manually.

The fast path is the primary UX. Blank graph editing is supported but is not
the happy path.

## Resolved Decisions (Locked)

- Recipe specs are hand-authored Python data, not auto-derived from stock
  TOML/YAML at runtime. Tests compare them against stock fixtures so drift is
  caught.
- New recipe/catalog types live in **`py/swarm_do/pipeline/recipes.py`** (new
  module).
- TUI-only creation draft helpers live in **`py/swarm_do/tui/state.py`**.
- Persistence helpers live beside existing preset mutation helpers in
  **`py/swarm_do/pipeline/actions.py`**.
- `NewPresetModal` lives in **`py/swarm_do/tui/app.py`** with the existing
  `ModalScreen` classes and is launched by `PresetWorkbenchScreen`.
- The new flow coexists with current fork, detach, route-edit, and save
  helpers. Existing stock and user presets are not migrated or rewritten.

---

### Phase 0 — Documentation Discovery & API Surface Verification

**Goal:** Lock the exact existing APIs, signatures, and file locations the
implementation will call into. No code edits in this phase. Output is the
"Allowed APIs" list below — implementation phases must only call functions on
this list (or new ones they introduce).

### Verified Source Locations (read these before implementing)

| File | Purpose |
| --- | --- |
| `py/swarm_do/pipeline/actions.py` | Preset/pipeline mutation helpers |
| `py/swarm_do/pipeline/validation.py` | Preset & pipeline validation gates |
| `py/swarm_do/pipeline/catalog.py` | Preset/pipeline lookup + activation gate |
| `py/swarm_do/tui/app.py` | All Textual screens & ModalScreens |
| `py/swarm_do/tui/state.py` | TUI dataclasses and pure UI state helpers |
| `presets/*.toml` | Stock preset fixtures (balanced, research, review, …) |
| `pipelines/*.yaml` | Stock pipeline fixtures (default, lightweight, …) |
| `schemas/preset.schema.json` | Preset JSON schema (already enforces `oneOf` for `pipeline` vs `pipeline_inline`) |

### Allowed APIs (verified to exist)

From `py/swarm_do/pipeline/actions.py`:

- `NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")` — line 45
- `atomic_write_text(path, text)` — line 97
- `render_toml(data)` — line 303
- `activate_preset(name)` — line 342
- `validate_preset_name(name)` — line 349
- `fork_preset(source_name, new_name)` — line 469
- `fork_preset_and_pipeline(...)` — line 512
- `detach_preset_graph(name)` — line 573
- `save_user_preset_graph(preset_name, pipeline_mapping, *, expected_hash=None)` — line 622
- `find_preset(name)` and `find_pipeline(name)` (via `pipeline.catalog`)
- `current_preset_path()` (already used by `activate_preset`)

From `py/swarm_do/pipeline/validation.py`:

- `schema_lint_pipeline(pipeline)` — line 324 (rejects empty `stages`)
- `validate_preset_mapping(...)` — line 796

From `py/swarm_do/pipeline/catalog.py`:

- `pipeline_activation_error(pipeline_name, pipeline)` — line 1020

From `py/swarm_do/tui/app.py`:

- `PresetWorkbenchScreen` — defined at line 1710 (Screen) **and** line 2757
  (`_LegacyPipelineEditor` extension). New bindings/actions must be added to
  the live class actually launched today; resolve which is active before
  editing. Existing modal pattern: lines 935–1271 (`MessageModal`,
  `ConfirmModal`, `PresetValueModal`, `RouteModal`, `ForkPipelineModal`,
  `BranchRouteModal`, `ModuleModal`, `McoConfigModal`,
  `ProviderReviewConfigModal`, `LensModal`).
- Existing actions to preserve: `action_edit_lenses`, `action_add_module`.

### Anti-Patterns To Avoid

- ❌ Inventing helpers like `validate_pipeline_draft(...)` without first
  verifying they exist (the design called for one — Phase 0 must confirm or
  add it explicitly to Phase 3).
- ❌ Reading `presets/*.toml` or `pipelines/*.yaml` at runtime to build a
  recipe — they are **fixtures only**.
- ❌ Replacing `save_user_preset_graph`, `fork_preset`,
  `fork_preset_and_pipeline`, or `detach_preset_graph`. The new flow is
  additive.
- ❌ Calling `activate_preset` before write succeeds.
- ❌ Skipping `validate_preset_mapping(..., include_budget=False)` before
  writing a created preset.
- ❌ Generating `pipeline = "<stock>"` references in created presets.
  Created presets must use `pipeline_inline`.

#### Phase 0 Verification Checklist (sub-section)

- [ ] Confirm `validate_pipeline_draft(...)` exists in
      `py/swarm_do/pipeline/validation.py`. If absent, add a Phase 3.0 task
      to introduce it (signature must accept a pipeline mapping and return
      a list of errors usable by the Graph validation rail).
- [ ] Confirm which `PresetWorkbenchScreen` (line 1710 vs 2757) is the live
      class wired into the Presets tab. Phase 4 binds `N` and `M` to the
      live class.
- [ ] Read `presets/balanced.toml` and `pipelines/default.yaml` end-to-end
      to anchor the Balanced Default recipe spec.

---

### Phase 1 — Recipe Catalog Module (`recipes.py`)

**File to create:** `py/swarm_do/pipeline/recipes.py`

### What to implement (copy from anchors, do not transform)

Define dataclasses (use stdlib `dataclass(frozen=True)` to match existing
state pattern):

- `PresetRecipeSpec` — fields: `recipe_id`, `display_name`, `intent`
  (`Implementation` | `Output-only`), `default_routing_package_id`,
  `graph_builder` (callable returning the inline pipeline mapping),
  `policy_builder` (callable returning policy fields:
  `review_providers`, `routing`, `budget`, `decompose`, `mem_prime`).
- `RoutingPackageSpec` — fields: `package_id`, `display_name`,
  `routes` (mapping of `roles.*` keys → `{backend, model, effort}` plus
  any named-route entries).
- `GraphStackSpec` — fields: `stack_id`, `display_name`, `stage_templates`
  (ordered list of stage mappings), `default_dependencies` (per stage id).
- `NewPresetBuildResult` — fields: `preset_mapping`, `pipeline_mapping`,
  `errors`, `warnings`.

Public functions:

- `list_preset_recipes() -> list[PresetRecipeSpec]`
- `get_preset_recipe(recipe_id: str) -> PresetRecipeSpec`
- `list_routing_packages() -> list[RoutingPackageSpec]`
- `get_routing_package(package_id: str) -> RoutingPackageSpec`
- `list_graph_stacks() -> list[GraphStackSpec]`
- `get_graph_stack(stack_id: str) -> GraphStackSpec`
- `build_recipe_preset(recipe_id, name, description=None, routing_package_id=None) -> NewPresetBuildResult`
- `build_blank_preset_draft(name, description) -> NewPresetBuildResult`
- `apply_graph_stack(pipeline, stack_id, mode) -> NewPresetBuildResult`
  where `mode in {"empty", "append-missing", "replace"}`.

All builders must produce `origin = "user"` and `pipeline_inline` (no
`pipeline = "<stock-name>"`).

### Recipe Catalog (anchor data)

Recipes to register (each must produce a valid preset mapping):

| Recipe ID | Intent | Default Routing | Anchor Fixture |
| --- | --- | --- | --- |
| `balanced-default` | Implementation | `balanced` | `presets/balanced.toml` + `pipelines/default.yaml` |
| `claude-only-diagnostic` | Implementation | `claude-only` | `presets/claude-only.toml` |
| `codex-only-fallback` | Implementation | `codex-only` | `presets/codex-only.toml` |
| `lightweight` | Implementation | `lightweight` (recipe-specific) | `presets/lightweight.toml` |
| `hybrid-review` | Implementation | `hybrid-review` (recipe-specific) | `presets/hybrid-review.toml` |
| `ultra-plan` | Implementation | `ultra-plan` (recipe-specific) | `presets/ultra-plan.toml` |
| `repair-loop` | Implementation | `repair-loop` (recipe-specific) | `presets/repair-loop.toml` |
| `smart-friend` | Implementation | `smart-friend` (recipe-specific) | `presets/smart-friend.toml` |
| `competitive-implementation` | Implementation | `competitive` (recipe-specific) | `presets/competitive.toml` |
| `research-memo` | Output-only | `research` | `presets/research.toml` |
| `brainstorm` | Output-only | `brainstorm` | `presets/brainstorm.toml` |
| `design-plan` | Output-only | `design` | `presets/design.toml` |
| `review-evidence` | Output-only | `review` | `presets/review.toml` |
| `strict-review-evidence` | Output-only | `review-strict` | `presets/review-strict.toml` |

Detailed graph and policy values for each recipe are listed in the
**Recipe Catalog Reference** appendix at the bottom of this file. Copy from
those tables; do not invent shapes.

### Documentation references

- Stock balanced policy: `presets/balanced.toml`
- Stock balanced graph: `pipelines/default.yaml`
- Schema enforced on output: `schemas/preset.schema.json` (`oneOf` requires
  exactly one of `pipeline` / `pipeline_inline`)

### Verification checklist

- [ ] `from swarm_do.pipeline.recipes import list_preset_recipes` returns
      every recipe ID in the table above.
- [ ] `build_recipe_preset("balanced-default", "balanced-custom")` returns
      a mapping where `validate_preset_mapping(..., include_budget=False)`
      returns no errors.
- [ ] Generated balanced graph stage IDs, dependencies, kinds, provider
      settings, and failure tolerance match `pipelines/default.yaml` byte
      for byte (drift test).
- [ ] Generated balanced policy matches `presets/balanced.toml` except for
      `name`, `origin`, graph form, and generated metadata.
- [ ] Competitive recipe: writer fan_out count == 2, both branch routes
      present, synthesize merge by `agent-writer-judge`,
      `failure_tolerance == "strict"`.
- [ ] Output-only recipes (`research-memo`, `brainstorm`, `design-plan`,
      `review-evidence`, `strict-review-evidence`) are flagged output-only
      and validate.

### Tests to author

`py/swarm_do/pipeline/tests/test_recipes.py` (new).

### Anti-pattern guards

- ❌ Do not call `load_toml_file(presets/...)` from `recipes.py` at runtime.
  Stock files are **test fixtures only**.
- ❌ Do not call `validate_preset_mapping(..., include_budget=True)` for
  output-only recipes that intentionally omit some budget fields — the
  default `include_budget=False` matches the create-time gate.

---

### Phase 2 — Persistence Helpers (`actions.py` additions)

**File to edit:** `py/swarm_do/pipeline/actions.py`

### What to implement

Add two helpers next to `save_user_preset_graph` (line 622). Do not modify
any existing helper.

```
def suggest_user_preset_name(stem: str, *, suffix: str = "custom") -> str: ...
def create_user_preset_graph(
    preset_name: str,
    preset_mapping: Mapping[str, Any],
    *,
    activate: bool = False,
) -> Path: ...
```

`suggest_user_preset_name` algorithm:

1. If neither `find_preset(stem)` nor `find_pipeline(stem)` exists → return
   `stem`.
2. Else try `f"{stem}-{suffix}"`.
3. Else try `f"{stem}-{suffix}-2"`, `…-3`, … up to a sane cap (e.g. 99).
4. Reject any candidate that does not match `NAME_RE`.

`create_user_preset_graph` order of operations (must be exact):

1. `validate_preset_name(preset_name)` (raises on invalid).
2. Reject if `find_preset(preset_name)` or `find_pipeline(preset_name)`
   already exists.
3. Require `preset_mapping["origin"] == "user"`.
4. Require `"pipeline_inline" in preset_mapping` (and not `"pipeline"`).
5. `validate_preset_mapping(preset_mapping, preset_name, include_budget=False)` — raise on errors.
6. Render with `render_toml(preset_mapping)` and write atomically to
   `${CLAUDE_PLUGIN_DATA}/presets/<preset_name>.toml` via `atomic_write_text`.
7. Only when `activate=True`: call `activate_preset(preset_name)` — and if
   that raises, leave the file in place and re-raise.

### Documentation references

- Existing patterns to mirror: `save_user_preset_graph` (line 622),
  `fork_preset` (line 469), `activate_preset` (line 342).
- Atomic write helper: `atomic_write_text` (line 97).
- TOML rendering: `render_toml` (line 303).
- Name validation: `validate_preset_name` (line 349) and `NAME_RE` (line 45).

### Verification checklist

- [ ] Helper appears between `save_user_preset_graph` and the next existing
      helper (or at end of preset-helpers cluster) — no reordering of
      existing functions.
- [ ] No call site of `save_user_preset_graph`, `fork_preset`,
      `fork_preset_and_pipeline`, or `detach_preset_graph` is changed.
- [ ] `grep -n "create_user_preset_graph" py/swarm_do/pipeline/actions.py`
      returns exactly one definition site.

### Tests to author

Add to `py/swarm_do/pipeline/tests/test_pipeline_actions.py` (existing):

- Writes a TOML file under temp `${CLAUDE_PLUGIN_DATA}/presets/`.
- Round-trip: written file reloads through preset loader and validates.
- Rejects invalid names (`NAME_RE` fail).
- Rejects collisions with existing preset **and** existing pipeline names.
- Rejects mapping without `pipeline_inline`.
- Rejects mapping with `origin != "user"`.
- `activate=True` writes `current-preset.txt` via `current_preset_path()`.
- Activation failure after successful write: file remains, error surfaces.

### Anti-pattern guards

- ❌ Do not introduce a separate writer for created presets — reuse
  `atomic_write_text` and `render_toml`.
- ❌ Do not call `activate_preset` inside the same try/except as the write;
  failure semantics differ (write must succeed first).

---

### Phase 3 — TUI Draft State Helpers (`state.py` additions)

**File to edit:** `py/swarm_do/tui/state.py`

### What to implement

Add a draft container and pure helpers (no Textual widgets). Place after the
existing pipeline graph dataclasses (search for `class PipelineGraphModel`).

```
@dataclass(frozen=True)
class PresetCreationDraft:
    name: str
    description: str
    preset_mapping: Mapping[str, Any]   # may have empty stages
    recipe_id: str | None
    routing_package_id: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    is_blank: bool
```

Public functions:

- `start_blank_preset_draft(name: str, description: str) -> PresetCreationDraft`
- `new_preset_preview(recipe_id: str, name: str, routing_package_id: str | None) -> PresetCreationDraft`
- `validate_creation_draft(draft: PresetCreationDraft) -> PresetCreationDraft`
  (returns a new draft with `errors`/`warnings` filled in by running
  `validate_preset_mapping(..., include_budget=False)` and
  `pipeline_activation_error(name, pipeline)` on the resolved graph).
- `draft_apply_graph_stack(draft: PresetCreationDraft, stack_id: str, mode: str) -> PresetCreationDraft`
  where `mode in {"empty", "append-missing", "replace"}`.

Blank drafts may carry `stages = []`. Validation must surface the existing
schema error (`schema_lint_pipeline` returns `pipeline: stages must be a
non-empty array`) and Save/Create stays disabled until the draft validates.

### Dependency Defaults (deterministic — used by `draft_apply_graph_stack`
and individual stage adds)

When adding modules/stages, default `depends_on` as follows:

- `analysis` → `["research"]` if `research` exists, else `[]`
- `clarify` → `["research"]` if `research` exists, else `[]`
- `exploration` → `["research"]` if `research` exists, else `[]`
- `advisor` → existing of `["analysis", "clarify"]`
- `writer` → existing of `["analysis", "clarify"]`; if neither exists,
  return error `"writer requires explicit dependencies"`
- `writers` → same rule as `writer`
- `clean-review` → `["writer"]`
- `revise-writer` → `["writer", "clean-review"]`
- `spec-review` → first existing of `["revise-writer", "writers", "writer"]`
- `provider-review` → first existing of `["revise-writer", "writers", "writer"]`
- `mco-review` → first existing of `["revise-writer", "writers", "writer"]`
- `codex-review` → `["spec-review"]` if present, else error
- `review` → existing of `["spec-review", "provider-review", "mco-review", "codex-review"]`;
  if none, fall back to first existing writer output from
  `["revise-writer", "writers", "writer"]`
- `docs` → `["spec-review"]` if present, else error

After applying defaults, run topological validation; refuse the apply if
the resulting graph has cycles or dangling deps.

### `apply_graph_stack` modes

- **empty graph** → apply unconditionally.
- **`append-missing`** → add only stack stages whose IDs are not already
  present. Refuse if a stage ID collides but the existing stage differs
  from the stack template. Refuse if any dependency points to a missing
  stage after append resolution. Preserve preset name, description,
  routing, and policy.
- **`replace`** → replace `pipeline_inline.stages` and graph-level metadata
  the stack supplies. Preserve preset name, description, routing, budget,
  decompose, mem_prime, and review-provider policy unless the user
  explicitly opts into "replace policy" (advanced).

### Documentation references

- Existing draft pattern: search `state.py` for `Draft` (TUI uses immutable
  dataclasses returned by `_replace`-style helpers).
- Validation gates to call: `validate_preset_mapping` (validation.py:796),
  `pipeline_activation_error` (catalog.py:1020), `schema_lint_pipeline`
  (validation.py:324).

### Verification checklist

- [ ] `start_blank_preset_draft("x", "y")` returns draft with empty stages
      and at least one error.
- [ ] Applying `default-implementation` stack (id matching balanced graph)
      to an empty draft yields the balanced stage order and the dependency
      defaults above.
- [ ] Applying a stack to a non-empty graph in `append-missing` mode
      refuses incompatible ID collisions.
- [ ] `replace` mode replaces stages and preserves preset policy.
- [ ] Dependency defaults for `review`, `provider-review`, `docs`, and
      `revise-writer` match the table above.

### Tests to author

Add to `py/swarm_do/tui/tests/test_state.py` (existing).

### Anti-pattern guards

- ❌ Do not import Textual widgets in `state.py`.
- ❌ Do not call action helpers (no writes during preview).
- ❌ Do not use fuzzy phrases like "nearest valid review input" — defaults
  are the deterministic table above.

---

### Phase 4 — TUI Modal & Workbench Integration (`app.py`)

**File to edit:** `py/swarm_do/tui/app.py`

### What to implement

New ModalScreen classes (place near existing modals, lines 935–1271):

- `NewPresetModal(ModalScreen[NewPresetRequest | None])` where
  `NewPresetRequest` is a small dataclass: `{recipe_id | None,
  routing_package_id | None, name, description, blank: bool, activate: bool}`.
- `GraphStackModal(ModalScreen[GraphStackRequest | None])` where
  `GraphStackRequest = {stack_id, mode}`.

`PresetWorkbenchScreen` additions (apply to the **live** class identified in
Phase 0):

- New bindings:
  - `N` → `new_preset`
  - `M` → `add_stack`
  - keep `m` → `add_module`
  - keep `n` → `edit_lenses`
- New actions:
  - `action_new_preset` — push `NewPresetModal`; on dismiss handle three
    cases:
    - **recipe request**: call `actions.create_user_preset_graph(...)`
      with the recipe-built mapping, refresh the gallery, select the new
      preset, show Overview.
    - **blank request**: hold an unsaved `PresetCreationDraft`, switch to
      Graph tab, render the empty-stage validation rail.
    - **create-and-activate**: write first via
      `create_user_preset_graph(..., activate=False)`, reload and
      revalidate, then call `actions.activate_preset(name)`. On
      activation failure: keep the new preset, show
      "Preset created, activation refused" with errors.
  - `action_add_stack` — push `GraphStackModal`; on dismiss apply via
    `state.draft_apply_graph_stack(...)` or
    `recipes.apply_graph_stack(...)` against the current draft.

Graph tab action strip above `PipelineLayerBoard`:

- Add Stack
- Add Module
- Add Agent Stage
- Add Fan-Out
- Add Provider
- Edit Dependencies
- Remove

### Fast-path UX contract

Starting on the Presets screen:

1. User presses `N`. `NewPresetModal` opens with `Implementation` selected.
2. Variant defaults to `Balanced default`.
3. Name is generated via `actions.suggest_user_preset_name("balanced")`.
4. Preview shows graph, routing, provider, budget, and validation status:
   - **Ready** — no errors → Create + Create & Activate enabled.
   - **Warning** — warnings only → Create remains enabled.
   - **Blocked** — errors → Create + Create & Activate disabled, one-line
     red status, first three errors visible, "show all" expands the rest.
5. `Enter` → `Create Preset`. `A` → `Create & Activate`.
6. The TUI writes a user preset with `pipeline_inline`, refreshes the
   gallery, selects the new preset, opens Overview. **No post-create
   activation prompt appears.**

Default balanced happy path keystrokes:

- Create only: `N`, `Enter`
- Create & activate: `N`, `A`

Typed names do not silently change. If the user edits the generated name to
an invalid or colliding value, show inline error and disable Create.

### Documentation references

- Modal pattern: `ConfirmModal` (line 952), `PresetValueModal` (line 972)
  — copy structure for dismiss/return semantics.
- Existing bindings format: see `BINDINGS` lists at lines 1271, 1617, 1711,
  1896, 2758, 3390.
- Graph tab host: `PipelineLayerBoard` (existing widget).

### Verification checklist

- [ ] Preset command palette includes "Create new preset".
- [ ] Live `PresetWorkbenchScreen` has binding `N → new_preset`.
- [ ] `NewPresetModal` defaults: intent = Implementation, variant =
      Balanced default.
- [ ] Creating balanced through the modal writes a user preset, selects it
      in the gallery, and shows valid preview state.
- [ ] `Create & Activate` calls
      `create_user_preset_graph(..., activate=False)` then
      `activate_preset(name)` — verified by patching both and asserting
      call order.
- [ ] Blank flow opens the Graph tab and shows the empty-stage validation
      message.

### Tests to author

Add to `py/swarm_do/tui/tests/test_app.py` (existing) using Textual
`run_test`.

### Anti-pattern guards

- ❌ Do not edit existing `action_add_module` or `action_edit_lenses`.
- ❌ Do not change the lowercase `n` and `m` bindings.
- ❌ Do not call `create_user_preset_graph` for blank drafts before the
  user explicitly saves.
- ❌ Do not show a post-create activation prompt — `Create & Activate` is
  the explicit path.

---

### Phase 5 — Documentation Updates

**Files to edit:**

- `tui/README.md` — document New Preset, recipe creation, blank builder,
  and activation behavior.
- `README.md` — mention user-created inline presets in the command/TUI
  overview.

This plan stays in `docs/new-preset-creation-flow-plan.md` and is linked
from the implementation PR.

### Verification checklist

- [ ] `tui/README.md` describes `N`, `M`, modal preview, fast path, blank
      builder, and Create & Activate.
- [ ] Top-level `README.md` notes that the TUI can now create presets with
      inline pipelines.

### Anti-pattern guards

- ❌ Do not document features that did not ship in Phases 1–4.
- ❌ Do not duplicate the recipe catalog tables — link to this plan.

---

### Phase 6 — Final Verification

### Test runs

```
pytest py/swarm_do/pipeline/tests/test_recipes.py
pytest py/swarm_do/pipeline/tests/test_pipeline_actions.py
pytest py/swarm_do/tui/tests/test_state.py
pytest py/swarm_do/tui/tests/test_app.py
pytest py/swarm_do/   # full suite to catch regressions
```

### Manual TUI smoke test

1. Launch the TUI. Open the Presets workbench.
2. Press `N`. Confirm modal defaults to Balanced default.
3. Press `Enter`. Confirm a new user preset appears in the gallery and
   Overview is selected.
4. Press `N`, then `A`. Confirm preset is created **and** active (status
   bar reflects active preset).
5. Press `N`, choose Blank graph, accept name. Confirm Graph tab shows the
   empty-stage validation rail.
6. Press `M`, choose Default implementation stack. Confirm stages are
   added with correct dependency defaults and Save becomes enabled.

### Anti-pattern grep guards

```
# No created preset should reference stock pipelines:
grep -rE 'pipeline\s*=\s*"(default|lightweight|hybrid-review|ultra-plan|repair-loop|smart-friend|competitive|research|brainstorm|design|review|review-strict|claude-only|codex-only)"' \
  py/swarm_do/pipeline/recipes.py && echo "FAIL"

# Recipes module must not load stock files at runtime:
grep -nE 'load_toml_file|open\(.*presets/|open\(.*pipelines/' \
  py/swarm_do/pipeline/recipes.py && echo "FAIL"

# Created presets must use inline:
grep -nE 'origin\s*=\s*"stock"' py/swarm_do/pipeline/recipes.py && echo "FAIL"
```

### Backwards-compatibility verification

- [ ] Existing stock presets remain read-only.
- [ ] Existing user presets continue to load, edit, detach, save, rename,
      delete, diff, and activate through current helpers.
- [ ] Existing `pipeline = "<stock-name>"` user presets are not migrated.
- [ ] `fork_preset_and_pipeline` still works for stock-edit flows.
- [ ] `save_user_preset_graph` still works for existing user-preset graph
      drafts.

---

## Per-Workstream Definition Of Done

### Recipe Catalog (Phase 1)
- `py/swarm_do/pipeline/recipes.py` defines all recipe, routing package,
  and graph stack specs in the catalog table.
- Every recipe builds a preset mapping with `origin = "user"` and
  `pipeline_inline`.
- Recipe unit tests validate all recipes and compare stock-equivalent
  recipes to stock fixtures.

### Persistence (Phase 2)
- `create_user_preset_graph` writes atomically through existing helpers.
- Collisions and invalid names rejected before writing.
- Create-and-activate behavior covered by unit tests.
- Existing fork/detach/save tests still pass.

### TUI State And Builder (Phase 3)
- Blank preset drafts can exist without being saved.
- Graph stacks can be applied with empty, append-missing, and replace
  semantics.
- Dependency defaults are deterministic and covered by tests.
- Invalid drafts keep Save/Create disabled and show validation errors.

### TUI Modal And Workbench Integration (Phase 4)
- `N` opens `NewPresetModal` from `PresetWorkbenchScreen`.
- Recipe creation takes `N`, `Enter` for the balanced default happy path.
- `N`, `A` creates and activates.
- Graph tab exposes the action strip.
- Modal, preview, gallery refresh, selection, and status behavior covered
  by Textual `run_test` tests.

### Documentation (Phase 5)
- `tui/README.md` documents New Preset, recipe creation, blank builder,
  and activation behavior.
- `README.md` mentions user-created inline presets.
- This plan remains linked from the implementation PR notes.

---

## Appendix — Recipe Catalog Reference

Use this appendix as the source of truth when implementing Phase 1
builders. Phase 1 must produce these graphs and policies exactly.

### Routing Packages

#### `balanced`
- `roles.agent-docs`: codex, `gpt-5.4-mini`, medium
- `roles.agent-spec-review`: codex, `gpt-5.4-mini`, medium
- `roles.agent-clarify`: codex, `gpt-5.4-mini`, medium
- `roles.agent-writer.simple`: codex, `gpt-5.4-mini`, medium

#### `claude-only`
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

#### `codex-only`
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

#### Recipe-Specific Packages

- **lightweight**: `roles.agent-clarify` and `roles.agent-writer.simple` to
  codex `gpt-5.4-mini` medium.
- **hybrid-review**: `roles.agent-codex-review` to codex `gpt-5.4` high.
- **ultra-plan**: `roles.agent-analysis.hard` to Claude Opus xhigh,
  `roles.agent-analysis-judge` to Claude Opus high, and
  `roles.agent-writer.hard` to Claude Opus high.
- **repair-loop**: balanced routes plus `roles.agent-clean-review` to codex
  `gpt-5.4` high.
- **smart-friend**: balanced routes plus named route `smart-advisor` to
  Claude Opus high.
- **competitive**: `roles.agent-analysis` to Claude Opus xhigh and
  `roles.agent-writer-judge` to codex `gpt-5.4` high.
- **research**: `roles.agent-research` to Claude Sonnet high and
  `roles.agent-research-merge` to Claude Opus high.
- **brainstorm**: `roles.agent-brainstorm` to Claude Sonnet high and
  `roles.agent-brainstorm-merge` to Claude Opus high.
- **design**: `roles.agent-research` to Claude Sonnet high,
  `roles.agent-analysis` to Claude Opus xhigh,
  `roles.agent-analysis-judge` to Claude Opus high, and
  `roles.agent-clarify` to Claude Sonnet medium.
- **review** and **review-strict**: `roles.agent-review` to Claude Opus high.

### Recipes — Graphs & Policies

#### Balanced Default
Intent: Implementation. Graph:
- `research`: agents `agent-research`
- `analysis`: depends on `research`, agents `agent-analysis`
- `clarify`: depends on `research`, agents `agent-clarify`
- `writer`: depends on `analysis`, `clarify`, agents `agent-writer`
- `spec-review`: depends on `writer`, agents `agent-spec-review`
- `provider-review`: depends on `writer`, provider `swarm-review`, command
  `review`, selection `auto`, output `findings`, memory false,
  `timeout_seconds 1800`, `max_parallel 4`, failure_tolerance best-effort
- `review`: depends on `spec-review`, `provider-review`, agents
  `agent-review`
- `docs`: depends on `spec-review`, agents `agent-docs`

Policy:
- routing package `balanced`
- review_providers: selection auto, min_success 1, max_parallel 4
- budget: 80 agents, $20, 14400 s, 60 writer tool calls, 60000 writer
  output bytes, 1 handoff
- decompose: off
- mem_prime: off, max_tokens 500, recency_days 90, min_relevance 0.6,
  adapter `dispatch_file`

#### Claude-Only Diagnostic
Balanced Default graph + `claude-only` routing. Budget estimated cost $30.

#### Codex-Only Fallback
Balanced Default graph + `codex-only` routing. Budget estimated cost $20.

#### Lightweight
Graph:
- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writer`: depends on `analysis`, `clarify`
- `provider-review`: depends on `writer`, same provider settings as
  balanced
- `review`: depends on `writer`, `provider-review`

Policy: lightweight routes; review_providers auto, min_success 1,
max_parallel 4; budget 40 agents, $10, 7200 s, 60 writer tool calls,
60000 bytes, 1 handoff; decompose off; mem_prime defaults off.

#### Hybrid Review
Balanced Default graph plus:
- `codex-review`: depends on `spec-review`, agents `agent-codex-review`
  with backend codex, model `gpt-5.4`, effort high, failure_tolerance
  best-effort
- final `review`: depends on `spec-review`, `provider-review`,
  `codex-review`

Policy: hybrid-review route; review_providers auto, min_success 1,
max_parallel 4; budget 100 agents, $25, 14400 s, 60 writer tool calls,
60000 bytes, 1 handoff.

#### Ultra Plan
Graph:
- `research`: agents `agent-research`
- `exploration`: depends on `research`, fan_out role `agent-analysis`,
  count 3, variant `prompt_variants`, variants `explorer-a`, `explorer-b`,
  `explorer-c`, merge synthesize by `agent-analysis-judge`,
  failure_tolerance quorum min_success 2
- `clarify`: depends on `research`, agents `agent-clarify`
- `writer`: depends on `exploration`, `clarify`, agents `agent-writer`
- `spec-review`: depends on `writer`
- `provider-review`: depends on `writer`, same provider settings as
  balanced
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy: ultra-plan routes; review_providers auto, min_success 1,
max_parallel 4; budget 120 agents, $35, 21600 s, 60 writer tool calls,
60000 bytes, 1 handoff.

#### Repair Loop
Graph:
- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writer`: depends on `analysis`, `clarify`
- `clean-review`: depends on `writer`, agents `agent-clean-review`
- `revise-writer`: depends on `writer`, `clean-review`, agents
  `agent-writer`, failure_tolerance best-effort
- `spec-review`: depends on `revise-writer`
- `provider-review`: depends on `revise-writer`, same provider settings
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy: repair-loop routes; review_providers auto, min_success 1,
max_parallel 4; budget 100 agents, $28, 18000 s, 60 writer tool calls,
60000 bytes, 1 handoff.

#### Smart Friend
Graph:
- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `advisor`: depends on `analysis`, `clarify`, agents
  `agent-implementation-advisor` routed through named route
  `smart-advisor`
- `writer`: depends on `analysis`, `clarify`, `advisor`
- `spec-review`: depends on `writer`
- `provider-review`: depends on `writer`, same provider settings
- `review`: depends on `spec-review`, `provider-review`
- `docs`: depends on `spec-review`

Policy: smart-friend routes; review_providers auto, min_success 1,
max_parallel 4; budget 100 agents, $25, 18000 s, 60 writer tool calls,
60000 bytes, 1 handoff.

#### Competitive Implementation
Graph:
- `research`
- `analysis`: depends on `research`
- `clarify`: depends on `research`
- `writers`: depends on `analysis`, `clarify`, fan_out role
  `agent-writer`, count 2, variant `models`
  - branch route 1: claude, `claude-opus-4-7`, xhigh
  - branch route 2: codex, `gpt-5.4`, xhigh
  - merge: synthesize by `agent-writer-judge`
  - failure_tolerance: strict
- `spec-review`: depends on `writers`
- `review`: depends on `spec-review`
- `docs`: depends on `spec-review`

Policy: competitive routes; no provider stage; no review_providers table
required; budget 120 agents, $40, 21600 s, 60 writer tool calls,
60000 bytes, 1 handoff.

#### Research Memo
Graph:
- `research`: fan_out role `agent-research`, count 3, variant
  `prompt_variants`, variants `codebase-map`, `prior-art-search`,
  `risk-discovery`, merge synthesize by `agent-research-merge`,
  failure_tolerance quorum min_success 2

Policy: research routes; budget 20 agents, $8, 7200 s; output-only.

#### Brainstorm
Graph:
- `brainstorm`: fan_out role `agent-brainstorm`, count 3, variant
  `prompt_variants`, variants `expand-options`,
  `constraints-and-failure-modes`, `analogies-and-transfers`, merge
  synthesize by `agent-brainstorm-merge`, failure_tolerance quorum
  min_success 2

Policy: brainstorm routes; budget 20 agents, $8, 7200 s; output-only.

#### Design Plan
Graph:
- `research`: agents `agent-research`
- `exploration`: depends on `research`, fan_out role `agent-analysis`,
  count 4, variant `prompt_variants`, variants `explorer-a`, `explorer-b`,
  `explorer-c`, `security-threat-model`, merge synthesize by
  `agent-analysis-judge`, failure_tolerance quorum min_success 3
- `clarify`: depends on `research`, agents `agent-clarify`
- `recommendation`: depends on `research`, `exploration`, `clarify`,
  agents `agent-analysis`

Policy: design routes; budget 60 agents, $20, 14400 s; output-only.

#### Review Evidence
Graph:
- `provider-review`: provider `swarm-review`, command `review`, selection
  `auto`, output `findings`, memory false, timeout_seconds 1800,
  max_parallel 4, failure_tolerance best-effort
- `review`: depends on `provider-review`, fan_out role `agent-review`,
  count 5, variant `prompt_variants`, variants `correctness-rubric`,
  `api-contract`, `security-threat-model`, `performance-review`,
  `edge-case-review`, merge synthesize by `agent-review`,
  failure_tolerance quorum min_success 3

Policy: review route; review_providers auto, min_success 1, max_parallel
4; budget 30 agents, $12, 7200 s; output-only.

#### Strict Review Evidence
Same graph as Review Evidence except provider-review failure_tolerance is
quorum min_success 2.

Policy: review route; review_providers auto, min_success 2, max_parallel
4; budget 35 agents, $16, 9000 s; output-only.

---

## Validation Checklist For This Plan

- [x] Bootstrap/file layout gaps resolved by Phase 0 + per-phase File
      anchors.
- [x] Phase 0 documentation discovery is mandatory and lists exact API
      anchors with line numbers.
- [x] `NewPresetModal` parent class, pattern, bindings, and tab
      integration are specified in Phase 4.
- [x] Recipe source is specified as hand-authored specs with stock
      fixture tests; runtime must not read stock files.
- [x] Routing packages and recipe-specific routes are catalogued in the
      appendix.
- [x] Name collision policy, Add Stack non-empty semantics, dependency
      defaults, validation preview, and Create & Activate behavior are
      specified per phase.
- [x] Test files, fixture patterns, and assertion granularity specified
      per phase.
- [x] Each implementation workstream has a Definition of Done.
- [x] Backwards compatibility is explicitly additive and requires no
      migration.
- [x] Anti-pattern guards live next to the phase they protect, plus a
      Phase 6 grep gate.
