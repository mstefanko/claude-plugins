# SwarmDaddy TUI/CLI Clarity Plan

Goal: collapse first-run friction by unifying the preset and pipeline
concepts into a single user-facing **Preset** entity, then re-thread the
TUI, CLI defaults, and docs around that entity. A user who installed five
minutes ago should reach a successful `/swarmdaddy:do` run in two slash
commands. A user editing a custom preset should activate a draft in one
button.

This plan rolls up the ux-researcher audit (2026-04-27) and the validated
flow facts captured in that conversation. Every decision below is final;
there are no open questions.

## Status quo (validated against source)

- TUI top-level nav: `1` Dashboard, `2` Runs (sub-view), `3` Pipelines,
  `4` Presets, `5` Settings, `Ctrl+P` palette, `q` quit.
- Pipelines local: `r b n o m Delete f/Enter Ctrl+S Ctrl+Z Ctrl+Y a g t y
  Esc`, plus `Ctrl+D` provider doctor.
- Presets local: `l` load, `v` diff, `x` delete (user only).
- Dashboard local: `f` handoff, `o` open Beads issue, `c` cancel run.
- `AppChrome` and `StatusBar` already render on all four screens
  (`app.py:755, 894, 989, 1148` and `app.py:763, 900, 995, 1157`). The
  active-state footer added in this plan extends those existing widgets;
  no new widget class is required.
- `/swarmdaddy:setup` is a pure alias for `/swarmdaddy:configure`; it does
  NOT init Beads.
- `/swarmdaddy:init-beads` is the explicit Beads bootstrap.
- Default pipeline (research → analysis+clarify → writer →
  spec-review+provider-review → review+docs) runs implicitly when no
  preset is active. The fallback is silent — there is no banner today.
- Forking a stock pipeline today creates a user pipeline YAML +
  matching user preset TOML, and the preset must still be `l`-loaded on
  the Presets screen before `/swarmdaddy:do` uses it.
- Pipelines: 10 stock files under `swarm-do/pipelines/`. Presets: 12
  stock TOML files under `swarm-do/presets/`. Every preset references
  exactly one pipeline by name; the only N:1 case is the `default`
  pipeline, which has three presets pointing at it (`balanced`,
  `claude-only`, `codex-only`).
- `provider_doctor()` (`pipeline/providers.py`) has no on-disk cache;
  every call shells out to local provider CLIs. The persistent footer
  introduced here uses an in-memory session cache only — no new cache
  file is created.
- `select_source_preset_for_pipeline(name) -> str | None` exists at
  `tui/state.py:1681`; `suggested_fork_name(source_name, *, suffix)`
  exists at `tui/state.py:1702`. Both are reused by Phase 4.

## Compatibility boundaries

- `/swarmdaddy:setup` becomes a deprecated alias for
  `/swarmdaddy:configure` with a banner. Anyone scripting `setup` for
  its (current) pure TUI behavior keeps working with the banner. The
  new `/swarmdaddy:quickstart` is the explicit first-run command and
  carries all bootstrap side effects.
- `/swarmdaddy:configure` is unchanged: pure TUI launcher, no Beads
  init, no migrator, no stdin prompt.
- Pipelines stop being a user-facing concept on the TUI. The stock
  `swarm-do/pipelines/` directory stays on disk as the source of
  truth for stock-ref preset graphs; the user pipelines directory
  (`${CLAUDE_PLUGIN_DATA}/pipelines/`) is migrated and archived. User
  presets continue to support both stock-ref and inline-snapshot graph
  forms in storage.
- The preset schema gains an optional `pipeline_inline` and relaxes
  `required` to drop `pipeline`. Stock presets still REQUIRE
  `pipeline = "<name>"`. Existing stock presets validate unchanged.
- TUI key remap (`Ctrl+D` → `Ctrl+H`) breaks operator muscle memory.
  `Ctrl+D` is kept as a deprecated alias for one release with a
  StatusBar toast.
- CLI: `bin/swarm mode <name>` is deprecated in favor of
  `bin/swarm preset load <name>`. The alias keeps working with a
  deprecation notice for one release.
- README drift fix is doc-only; covered as part of Phase 7 to land
  alongside the final vocab.

## Out of scope

- No changes to provider-review or MCO contracts.
- No changes to stage execution, telemetry, or run-locking semantics.
- No new pipeline templates beyond what is shipped today.
- No general Beads-issue browser inside the Dashboard. The Dashboard
  remains a read-only operational view of in-flight runs.
- No graphical preset diff beyond the existing `v` action.

---

## The unified Preset model

The merger is a **frontend** decision. The TUI exposes one entity —
**Preset** — and never uses the word "pipeline" in user-facing surfaces.
The **backend** preserves the graph-source abstraction so route/budget
variants can share a graph and stock-following user presets remain
possible.

A **Preset** is the single user-facing entity that defines what runs
next. It carries:

- Identity: `name`, `description`, `origin`, `forked_from`,
  `forked_from_hash`.
- Routing: per-role `backend`, `model`, `effort`.
- Budget: agent count, cost, wall-clock, writer caps, handoffs.
- Policy: `decompose`, `mem_prime`, `review_providers`.
- **Graph source — exactly one of two forms:**
  - `pipeline = "<pipeline-name>"` — **stock-ref** form. References a
    pipeline YAML by name. Used by all stock presets and by user
    presets that opt into stock-graph follow-along. Graph upgrades to
    the referenced file flow through automatically.
  - `[pipeline_inline]` — **inline-snapshot** form. A TOML-encoded
    pipeline graph embedded directly in the preset. Used by user
    presets that have edited the graph. The embedded graph is the
    source of truth; no name-based lookup happens.
- Graph lineage metadata for inline snapshots:
  - `[pipeline_inline_source]` — optional metadata table recording the
    upstream stock graph when the inline snapshot came from a known
    stock-ref detach. It is not a graph source; it only powers UI
    lineage, config hashing, and the re-attach action.
  - Fields: `name = "<stock-pipeline-name>"` and
    `hash = "sha256:<canonical-graph-hash-at-detach>"`.
  - Detach from a stock-ref preset MUST write this table. Adopted
    orphan pipelines MAY omit it because no upstream stock graph is
    known.

User presets MAY use either form. The TUI defaults to the stock-ref
form when forking (preserves stock follow-along) and prompts the user
to **detach** to inline-snapshot the first time they try to edit the
Graph tab.

### Schema delta

Update `swarm-do/schemas/preset.schema.json`:

- `required` becomes `["name", "budget"]` (drop `pipeline` from
  `required` so either graph-source form is allowed).
- Add `pipeline_inline` as an optional object whose subschema mirrors
  the pipeline schema fields (`pipeline_version`, `name`,
  `description`, `parallelism`, `stages`).
- Add `pipeline_inline_source` as an optional object with
  `name` and `hash`. It is only valid when `pipeline_inline` is present.
  `hash` uses the same `sha256:<hex>` prefix format as
  `forked_from_hash`.
- Add a JSON Schema `oneOf` constraint: a preset must have exactly one
  of `pipeline` (string, non-empty) or `pipeline_inline` (object). Not
  both, and not neither.
- For `pipeline = "<name>"`, the validator additionally enforces that
  the referenced name resolves to a known pipeline (stock pipelines
  directory only — see "Stock vs user behavior" below).

### Loader semantics

A new module `swarm-do/py/swarm_do/pipeline/graph_source.py` owns
graph resolution. Every site that loads a pipeline graph from a preset
calls into this module — `BackendResolver` does not (it only handles
role routing).

```
def resolve_preset_graph(preset: Mapping[str, Any]) -> ResolvedGraph
```

Returns a `ResolvedGraph` dataclass with:

- `graph: dict` — the pipeline graph dict (same shape as a parsed
  pipeline YAML).
- `source: Literal["stock-ref", "inline-snapshot"]`.
- `source_name: str | None` — the stock pipeline name when
  `source == "stock-ref"`, else `None`.
- `source_hash: str` — sha256 of the resolved graph contents in a
  canonical JSON form. Used by `config_hash` and lineage tracking.
- `lineage_name: str | None` — for inline snapshots, the upstream
  stock pipeline name from `[pipeline_inline_source]` when known.
- `lineage_hash: str | None` — for inline snapshots, the upstream
  stock graph hash captured at detach time when known.

Behavior:

- If `pipeline_inline` is present, return it with
  `source = "inline-snapshot"`. The hash is computed from
  `json.dumps(graph, sort_keys=True)`. If `[pipeline_inline_source]`
  is present, validate that its `name` resolves to a stock pipeline and
  expose its `name`/`hash` as `lineage_name`/`lineage_hash`. If the
  source name no longer resolves, keep the inline graph usable but
  return a validation warning so the re-attach action can be hidden
  with an explanation.
- Else look up `preset["pipeline"]` via `find_pipeline(name)`. If the
  result has `origin in {"stock", "path"}`, parse and return it with
  `source = "stock-ref"`. If the result is missing or has any other
  origin (user, experiment), raise `PresetGraphError` with a clear
  message.
- If neither form is present, raise `PresetGraphError` (defense in
  depth — the schema should catch this earlier).

### All call sites that load a pipeline graph from a preset

P1 must update every one of these to go through
`resolve_preset_graph`. Each is verified during implementation by a
post-edit `grep -nE 'load_pipeline\(|find_pipeline\(' swarm-do/py`
that returns no preset-graph-loading hits outside the new module:

- `swarm-do/py/swarm_do/pipeline/validation.py` — extend
  `schema_lint_pipeline` and any preset-mapping validator to accept a
  `ResolvedGraph` and validate its `graph` field. Add a new helper
  `validate_preset_mapping(preset)` that calls
  `resolve_preset_graph` and runs the existing pipeline validator on
  the result.
- `swarm-do/py/swarm_do/pipeline/providers.py` — `provider_doctor`
  and any helper that inspects pipeline stages for provider gating.
  Replace direct pipeline lookups with `resolve_preset_graph(preset)
  .graph`.
- `swarm-do/py/swarm_do/pipeline/context.py` and
  `swarm-do/py/swarm_do/pipeline/config_hash.py` — `current_context`
  must read the resolved graph and include `graph_source`,
  `graph_source_name`, `graph_lineage_name`, `graph_lineage_hash`, and
  `source_hash` in the config-hash inputs so a stock-ref and an inline
  snapshot of identical graph contents do not collapse to the same
  active config hash.
  Existing telemetry fields remain compatible:
  - `pipeline_name = <stock-pipeline-name>` for stock-ref presets.
  - `pipeline_name = inline:<preset-name>` for inline-snapshot presets.
  - `pipeline_hash = source_hash` for both forms.
- `swarm-do/py/swarm_do/tui/state.py` — `pipeline_board_model`,
  `pipeline_stage_rows`, `pipeline_validation_report`,
  `pipeline_has_provider_stage`, `pipeline_critical_stage_ids`,
  `pipeline_activation_blocker`, `pipeline_profile_preset`,
  `pipeline_live_stage_statuses`, `pipeline_graph_model`,
  `pipeline_graph_overlay`, `pipeline_graph_move`,
  `start_pipeline_draft`, `validate_pipeline_draft`. All move to the
  new module's resolver as their input source. Public names rename in
  Phase 3; this phase only changes the data source.
- `swarm-do/py/swarm_do/pipeline/actions.py` — profile activation,
  preset write, and `render_toml` paths (lines 317, 342, 358, 395,
  415, 490) read and write `pipeline_inline` and
  `pipeline_inline_source` faithfully.
- `swarm-do/py/swarm_do/cli/` — any CLI subcommand that prints or
  validates a preset graph (e.g. `swarm preset show`, lint commands).
- `swarm-do/py/swarm_do/run/` and `swarm-do/bin/swarm-run` — wherever
  the run dispatcher reads the active preset's graph to schedule
  stages. Verify exact site via `grep -rn 'load_pipeline\|stages\b'
  swarm-do/bin/swarm-run` during implementation.
- All test fixtures under
  `swarm-do/py/swarm_do/pipeline/tests/test_pipeline_validation.py`
  and `tui/tests/` — switch to `resolve_preset_graph` in fixture
  setup so they cover both source forms.

### Stock vs user behavior

- **Stock presets** (under `swarm-do/presets/`) MUST use
  `pipeline = "<name>"` (stock-ref form). Validation enforces this.
  Stock graph upgrades in `swarm-do/pipelines/` flow through to every
  stock preset that references them.
- **User presets** (under `${CLAUDE_PLUGIN_DATA}/presets/`) MAY use
  either form. They reference only stock pipelines by name; user
  pipelines disappear as a user-facing concept after migration.
- **Forking a stock preset** (Phase 4 Activate / "New from template")
  defaults to producing a stock-ref user preset — same `pipeline =
  "<name>"`, copied routing and budget. The user inherits future stock
  graph upgrades automatically.
- **Editing the Graph tab on a stock-ref user preset** triggers an
  explicit "Detach from upstream <name>?" confirmation modal. On
  confirm, the preset is converted to `pipeline_inline` by snapshotting
  the resolved graph at the current commit, writing
  `[pipeline_inline_source]` with the upstream stock pipeline `name`
  and canonical graph `hash`, then the edit proceeds.
  The Overview tab thereafter shows
  `Graph: inline snapshot (forked from <name> at <hash-prefix>)`.
- **Re-attaching a snapshot to upstream** is exposed as a power-user
  action under the command palette only:
  `Re-attach graph to upstream <name>`. The upstream name comes from
  `[pipeline_inline_source].name`, not from preset `forked_from`
  lineage. It discards local graph edits after a diff confirmation
  modal. Routing/budget are preserved.

### Migration (one-time, idempotent)

A new script `bin/swarm preset migrate` runs at most once per
`${CLAUDE_PLUGIN_DATA}` directory, gated by the sentinel file
`${CLAUDE_PLUGIN_DATA}/.preset-migrate-v1.done`. Behavior:

1. **Paired user pipelines (have a matching user preset).** For each
   `*.yaml` under `${CLAUDE_PLUGIN_DATA}/pipelines/` whose stem is the
   `pipeline` value of some user preset:
   - Read the YAML, convert to a TOML-compatible dict, write it as
     `[pipeline_inline]` into the user preset.
   - Remove the `pipeline = "..."` line from that preset (graph source
     becomes inline-snapshot).
   - Move the YAML to
     `${CLAUDE_PLUGIN_DATA}/pipelines/.archived/<name>.yaml.<timestamp>`.
2. **Orphan user pipelines (no matching user preset).** For each YAML
   that does not match any user preset's `pipeline` field:
   - Move the YAML to
     `${CLAUDE_PLUGIN_DATA}/pipelines/.archived/<name>.yaml.<timestamp>`.
   - Do **not** synthesize a preset. Migrating an orphan would require
     guessing routing/budget defaults, which silently changes cost
     and behavior.
3. Print a structured summary to stdout:
   `migrated: <n>, archived-orphans: <m>, sentinel: <path>`.
   For each orphan, also print:
   `orphan: <name>; to adopt run: swarm preset adopt
   <archived-path> --template <stock-preset-name>`.
4. Write the sentinel and exit 0.
5. On a fresh `${CLAUDE_PLUGIN_DATA}` (no `pipelines/` dir), the
   migrator writes the sentinel and exits 0 immediately.

A companion subcommand `bin/swarm preset adopt <archived-yaml>
--template <stock-preset-name> [--name <new-name>]` is added in Phase
1 alongside the migrator. It:

- Reads the archived YAML.
- Reads the named stock preset for routing, budget, decompose,
  mem_prime, and review_providers defaults.
- Writes a new user preset combining those policy fields with
  `pipeline_inline = <yaml-contents>`.
- Validates the result and exits 0 on success.

The migrator never invokes `adopt` automatically. Adoption is always
explicit.

## Phase graph

```
P1 (unified Preset model + migrator + adopt + detach/reattach + render_toml)
   │
   ├─► P2 (quickstart + configure + setup deprecation + run-banner)
   │       │
   │       └─► P6 (Getting Started panel)
   │
   ├─► P3 (single-screen Preset workbench, dual-form aware)
   │       │
   │       └─► P4 (single Activate action + persistent footer)
   │               │
   │               └─► P5 (TUI structure cleanup: Ctrl+D→Ctrl+H, binding trim)
   │                       │
   │                       └─► P7 (docs sync — final vocab)
   │
   └─► P8 (CLI verb deprecation: swarm mode → swarm preset load)
                                                — independent, anytime
```

Critical path: P1 → P3 → P4 → P5 → P7.
P2 lands in parallel with P3 once P1 ships.
P6 lands after P2 + P4.
P8 lands anytime after P1.

---

## Phase 1 — Unified Preset model

**Files**

- `swarm-do/schemas/preset.schema.json`
- New: `swarm-do/py/swarm_do/pipeline/graph_source.py` (owns
  `resolve_preset_graph` and `ResolvedGraph`).
- `swarm-do/py/swarm_do/pipeline/registry.py` — `find_pipeline` keeps
  its current shape; new code paths use `graph_source` instead of
  calling the registry directly.
- `swarm-do/py/swarm_do/pipeline/validation.py` — add
  `validate_preset_mapping(preset)`; extend `schema_lint_pipeline` to
  accept either a YAML-loaded dict or a `ResolvedGraph.graph` dict.
- `swarm-do/py/swarm_do/pipeline/providers.py` — replace direct
  pipeline lookups with `resolve_preset_graph(preset).graph`.
- `swarm-do/py/swarm_do/pipeline/context.py` and
  `swarm-do/py/swarm_do/pipeline/config_hash.py` — incorporate
  `ResolvedGraph.source`, `source_name`, `lineage_name`,
  `lineage_hash`, and `source_hash` into the context/config-hash
  inputs so graph-source identity survives even when the resolved graph
  contents match.
- `swarm-do/py/swarm_do/pipeline/actions.py` — extend `render_toml`
  (line 196) to faithfully serialize nested arrays-of-tables with
  array-of-string `depends_on`, nested mappings (`provider`,
  `failure_tolerance`, `fan_out`, `merge`), and stable key ordering.
  Update preset write paths (lines 317, 342, 358, 395, 415, 490) to
  preserve `pipeline_inline` and `pipeline_inline_source` on
  round-trip.
- `swarm-do/py/swarm_do/tui/state.py` — every helper that reads a
  pipeline graph (`pipeline_board_model`, `pipeline_stage_rows`,
  `pipeline_validation_report`, `pipeline_has_provider_stage`,
  `pipeline_critical_stage_ids`, `pipeline_activation_blocker`,
  `pipeline_profile_preset`, `pipeline_live_stage_statuses`,
  `pipeline_graph_model`, `pipeline_graph_overlay`,
  `pipeline_graph_move`, `start_pipeline_draft`,
  `validate_pipeline_draft`) sources its graph through
  `resolve_preset_graph`. Internal names stay; renames land in P3.
- `swarm-do/py/swarm_do/run/` (or wherever the active-preset run
  dispatcher reads stages — site identified during implementation
  via `grep -rn 'load_pipeline\|stages\b' swarm-do/bin/swarm-run
  swarm-do/py/swarm_do/run`).
- `swarm-do/py/swarm_do/cli/` — add `swarm preset migrate` and
  `swarm preset adopt` subcommands; existing `swarm preset show`
  switched to `resolve_preset_graph`.
- New: `swarm-do/py/swarm_do/pipeline/migrate_inline.py` (migrator
  implementation).
- New tests:
  `swarm-do/py/swarm_do/pipeline/tests/test_graph_source.py`,
  `test_migrate_inline.py`,
  `test_render_toml_pipeline_inline.py`,
  `test_validate_preset_mapping.py`.

**Changes**

- Implement schema delta exactly as specified above.
- Implement `graph_source.resolve_preset_graph` and
  `ResolvedGraph` per the loader-semantics spec.
- Migrate every call site listed in "All call sites that load a
  pipeline graph from a preset" to go through `resolve_preset_graph`.
  `BackendResolver` is **not** modified — it owns role routing only.
- Extend `render_toml` to handle nested arrays-of-tables.
  Acceptance pins below cover round-trip and ordering.
- Implement `swarm preset migrate` and `swarm preset adopt` per the
  migration spec.
- Wire migration into `/swarmdaddy:quickstart` (Phase 2). The
  `/swarmdaddy:configure` and `/swarmdaddy:setup` paths do **not**
  invoke the migrator.
- Add validators:
  - Stock preset must use `pipeline = "<name>"` (stock-ref form).
  - User preset must use exactly one of the two forms.
  - `pipeline = "<name>"` must resolve to a stock pipeline; it cannot
    point at a user pipeline (user pipelines no longer exist
    post-migration).
  - `pipeline_inline_source` is allowed only with `pipeline_inline`.
    When present, `pipeline_inline_source.name` must be a string and
    `pipeline_inline_source.hash` must be a `sha256:<hex>` string.
    Missing upstream stock files are warnings, not hard errors, because
    the inline graph remains runnable.
- Add the **detach** primitive in `actions.py` so P3 can call it:
  `detach_preset_graph(name) -> None` snapshots the resolved graph
  into `pipeline_inline`, writes `[pipeline_inline_source]`, and
  removes the `pipeline = ...` line. Reverse primitive
  `reattach_preset_graph(name, stock_name) -> None` drops
  `pipeline_inline` and `pipeline_inline_source`, then writes
  `pipeline = "<stock_name>"`. Both write via `render_toml` and the
  existing atomic-write path.

**Acceptance**

- Schema validates against all 12 stock presets unchanged. Schema
  rejects: a stock preset with `pipeline_inline`; a user preset with
  both forms or neither form; a `pipeline = "<name>"` whose target is
  a user pipeline.
- `resolve_preset_graph(stock_preset)` returns a `ResolvedGraph` whose
  `graph` field is byte-identical to the old
  `load_pipeline(find_pipeline(name).path)` output (golden file test
  on all 12 stock presets).
- `resolve_preset_graph` for a `pipeline_inline` preset returns the
  embedded graph and `source = "inline-snapshot"`. The
  `source_hash` is stable across re-renders of the same preset. If
  `[pipeline_inline_source]` is present, its `name` and `hash` are
  surfaced as `lineage_name` and `lineage_hash`.
- `render_toml` round-trip on a preset with `pipeline_inline`
  containing every shape we ship (stages with agents, fan_out, merge,
  provider, failure_tolerance, prompt lenses, `depends_on` arrays)
  plus `[pipeline_inline_source]` yields a TOML string that re-parses
  to the original dict (golden file test). Key ordering is
  deterministic across saves.
- `validate_preset_mapping` on a user preset whose stock-ref target
  was deleted from `swarm-do/pipelines/` raises `PresetGraphError`
  with the missing name.
- `provider_doctor` on a `pipeline_inline` preset detects provider
  stages identically to the equivalent stock-ref preset (parametrized
  test over both forms).
- `active_config_hash()` differs between two presets that share the
  same routing/budget but have different graph sources (one stock-ref,
  one inline-snapshot), even when their resolved graph contents are
  identical. The hash payload includes at least `graph_source`,
  `graph_source_name`, `graph_lineage_name`, `graph_lineage_hash`, and
  `source_hash`.
- `swarm preset migrate` on a fresh `${CLAUDE_PLUGIN_DATA}` is a no-op
  and writes the sentinel.
- `swarm preset migrate` on a fixture with one paired user pipeline
  embeds the YAML into the matching preset, archives the YAML, writes
  the sentinel. Re-run is a no-op.
- `swarm preset migrate` on a fixture with one orphan user pipeline
  archives the YAML, prints the `to adopt run: ...` line on stdout,
  does **not** create any new preset, writes the sentinel.
- `swarm preset adopt <archived-yaml> --template balanced --name foo`
  produces a new user preset `foo` with routing/budget copied from
  `balanced` and `pipeline_inline` = the archived YAML contents.
  Validation passes.
- `detach_preset_graph` on a stock-ref user preset writes a TOML file
  with `pipeline_inline`, `[pipeline_inline_source]`, and no
  `pipeline = ...` line, preserving routing and budget byte-for-byte.
  `pipeline_inline_source.name` is the original stock pipeline name,
  and `pipeline_inline_source.hash` is the original canonical graph
  hash. `reattach_preset_graph` uses that metadata by default,
  reverses the graph source, and discards local graph edits.
- All existing tests pass: `PYTHONPATH=py python3 -m unittest discover
  -s py -p 'test_*.py'`.
- Post-edit gate: `grep -rnE 'load_pipeline\(|find_pipeline\(' swarm-do/py
  | grep -v graph_source.py | grep -v tests/` returns no matches in
  preset-resolution code paths.

---

## Phase 2 — CLI surface that explains itself

Depends on P1 for the migrator and adopt subcommands. Otherwise
independent.

**Files**

- New: `swarm-do/commands/quickstart.md`
- `swarm-do/commands/setup.md` (rewritten to deprecate)
- `swarm-do/commands/configure.md`
- `swarm-do/commands/do.md`
- `swarm-do/bin/swarm-tui` (quit-time print)
- Run-start banner site under `swarm-do/py/swarm_do/run/` or
  `swarm-do/bin/swarm-run` — exact site identified by `grep -rn
  "active preset" swarm-do/py swarm-do/bin` during implementation.

**Changes**

- **New command `/swarmdaddy:quickstart`** — opinionated first-run
  bootstrap. Its body, in order:
  1. Print, before doing anything: `quickstart will initialize Beads
     in this repo (if missing) and migrate any user pipelines into
     unified presets. Continue? [Y/n]`. Read one line from stdin;
     non-`y`/empty input aborts with no side effects. The prompt is
     skipped only when `SWARMDADDY_QUICKSTART_YES=1` is set in the
     environment (for non-interactive shells; documented in
     `quickstart.md`).
  2. If no `.beads/` rig is detected, run `bd init --stealth`.
     Idempotent — no-op when `.beads/` already exists.
  3. Run `swarm preset migrate` if its sentinel file is missing.
  4. Print one status line:
     `rig: ok | active: <preset|default-fallback> | providers: ok|warn|error|unchecked`.
  5. Open the TUI by delegating to the same launcher as `configure`.
     The TUI lands on the Dashboard with the Getting Started panel
     visible (Phase 6 implements the panel; this phase only ensures
     `quickstart` triggers its visibility predicate by leaving the
     active-preset state unchanged).
- **`/swarmdaddy:configure`** stays a pure TUI launcher with no
  Beads, migration, or stdin-prompt side effects. Documented
  explicitly: "Opens the configuration TUI. Does not initialize Beads;
  does not migrate presets. Use `/swarmdaddy:quickstart` for first-run
  bootstrap."
- **`/swarmdaddy:setup`** is deprecated. The slash command body
  prints to stdout exactly once:
  `setup is deprecated. Use /swarmdaddy:quickstart for first-run
  bootstrap, or /swarmdaddy:configure to open the TUI without side
  effects.` It then delegates to `/swarmdaddy:configure`. The
  deprecation message is removed in a later release; this plan does
  not schedule the removal.
- **TUI quit hook** prints, on exit:
  - `Active: <preset-name>` (or `Active: default fallback (no preset
    chosen — that's fine)` when none is active).
  - `Next: /swarmdaddy:do <plan-path>`.
  Implemented via a Textual `on_unmount` on the App class that writes
  to stdout immediately before process exit. Triggered for every
  TUI launcher (`quickstart`, `configure`, deprecated `setup`).
- **`/swarmdaddy:do` halt-on-missing-rig** prints exactly:
  `No Beads rig detected in this repo. Run /swarmdaddy:init-beads
  (or /swarmdaddy:quickstart for guided first-run setup) first.`
- **`/swarmdaddy:do` run-start banner** prints to stderr exactly once
  when no preset is active:
  `swarmdaddy: no active preset; using default pipeline (research →
  analysis+clarify → writer → spec-review+provider-review → review+docs)`.

**Acceptance**

- Fresh repo, interactive shell: `/swarmdaddy:quickstart` prompts;
  responding `y` initializes Beads, runs migrator, prints status,
  opens TUI. A second invocation prompts again, then no-ops on Beads
  init and migrator (sentinel is present), prints status, opens TUI.
- Fresh repo, `SWARMDADDY_QUICKSTART_YES=1`: same effect, no prompt.
- Fresh repo, interactive shell, user types `n`: command exits 0 with
  no `.beads/` directory created and no sentinel written.
- `/swarmdaddy:configure` invoked in any repo: no `.beads/` is
  created, no sentinel is written, no stdin prompt appears.
- `/swarmdaddy:setup` invoked: deprecation banner prints, then the
  TUI opens with the same behavior as `configure` (no side effects).
- `commands/do.md` halt message contains both
  `/swarmdaddy:init-beads` and `/swarmdaddy:quickstart` by name.
- TUI quit prints `Active:` and `Next:` lines on stdout regardless of
  which launcher invoked it.
- A `/swarmdaddy:do` run with no preset prints the fallback notice to
  stderr exactly once at run start.

---

## Phase 3 — Single-screen Preset workbench

Depends on P1 (graph lookup uses `resolve_preset_graph`).

**Files**

- `swarm-do/py/swarm_do/tui/app.py`
  - Remove `PipelineScreen` class registration.
  - Replace `PresetsScreen` with a tabbed workbench called
    `PresetWorkbenchScreen`.
- `swarm-do/py/swarm_do/tui/app.tcss` (tab styling).
- `swarm-do/py/swarm_do/tui/state.py`:
  - Extend `PipelineEditDraft` to operate on a preset's
    `pipeline_inline` (or, for stock presets opened read-only, on the
    referenced stock pipeline). Rename helpers from `pipeline_*` to
    `preset_*` only at module boundary; keep internal names stable to
    minimize churn. Specifically rename:
    `pipeline_gallery_rows` → `preset_gallery_rows`,
    `pipeline_board_model` → `preset_graph_board_model`,
    `pipeline_stage_rows` → `preset_graph_stage_rows`,
    `pipeline_validation_report` → `preset_validation_report`,
    `start_pipeline_draft` → `start_preset_draft`,
    `validate_pipeline_draft` → `validate_preset_draft`. Other
    `pipeline_*` helpers stay private to the module.
- Tests at `swarm-do/py/swarm_do/tui/tests/test_app.py` and a new
  `test_preset_workbench.py`.
- `swarm-do/tui/README.md` and `swarm-do/README.md` (vocab updates;
  full README sync lands in Phase 6).

**Changes**

- TUI top-level nav becomes:
  - `1` Dashboard
  - `2` Runs (focuses runs table on Dashboard, no separate screen)
  - `3` Presets (the new workbench)
  - `4` Settings
  - `Ctrl+P` palette
  - `q` quit
  The previous `3 Pipelines` and `4 Presets` are gone; `3` is now the
  unified workbench.
- `PresetWorkbenchScreen` layout:
  - Left rail (35% width): preset gallery, grouped by intent
    (Implementation / Output-only / Experimental). Selected row shows
    an "Active" badge when applicable.
  - Right pane: tabbed inspector with four tabs:
    1. **Overview** — description, origin, lineage (`forked_from`),
       graph-source line (`Graph: stock-ref to <name>` or
       `Graph: inline snapshot (forked from <name> at <hash-prefix>)`),
       validation status.
    2. **Graph** — the existing layer-board composer, sourced from the
       preset's resolved graph (`resolve_preset_graph`). Read-only for
       stock presets. For user presets:
       - If the graph source is **stock-ref**, the Graph tab is also
         read-only by default. The first edit-attempt key (`r`, `b`,
         `n`, `o`, `m`, `Delete`) opens a confirmation modal:
         `This preset follows the <name> stock graph. Detach to a
         local snapshot so you can edit?` On confirm, the action calls
         `actions.detach_preset_graph(name)` (Phase 1 primitive),
         which converts the preset to `pipeline_inline`. The original
         keystroke is then applied to the new editable draft.
       - If the graph source is **inline-snapshot**, the Graph tab is
         immediately editable. All existing graph composer bindings
         (`r b n o m Delete Ctrl+R Ctrl+S Esc`) stay scoped to the
         Graph tab.
    3. **Routing** — the existing per-role route table from the
       Settings screen, scoped to the selected preset. Editable for
       all user presets regardless of graph-source form (routing edits
       never trigger detach).
    4. **Budget & policy** — caps, decompose, mem_prime,
       review_providers. Editable for all user presets regardless of
       graph-source form.
  - Tab switch keys: `o` Overview, `g` Graph, `t` Routing, `p` Policy.
    (`r` is reserved as the in-Graph route override binding — using
    `t` for the Routing tab avoids the shadow.)
  - Re-attach action exposed in the command palette only:
    `Re-attach graph to upstream <name>` (calls
    `actions.reattach_preset_graph`). Visible only when the selected
    preset's graph source is `inline-snapshot` AND
    `[pipeline_inline_source].name` resolves to a known stock pipeline.
    Preset `forked_from` is not used for graph re-attach because it
    tracks preset lineage, not graph lineage. The action shows a diff
    modal before committing the discard of local graph edits.
- Provider stage editor (`o` provider on a stage) and provider doctor
  binding (changed to `Ctrl+H` in Phase 5) remain available in the
  Graph tab.
- Settings screen's role-route view is preserved as the **Settings**
  screen (`4`), but now framed as "Global route defaults (apply when
  no preset overrides them)" rather than the primary editing surface.
  Per-preset routing edits move to the Routing tab.

**Acceptance**

- A fresh TUI launch lands on Dashboard. Pressing `3` opens the
  workbench. Pressing `4` opens Settings. There is no Pipelines screen
  anywhere.
- Selecting a stock preset and switching tabs shows graph, routing,
  and policy for that preset. All edits are blocked with a clear
  "Stock preset — fork to edit" toast on each edit-attempt key.
- Selecting a stock-ref user preset and pressing a Graph-tab edit key
  shows the detach confirmation modal. Confirming runs
  `detach_preset_graph` and the keystroke applies to the new draft.
  The Overview tab now reads
  `Graph: inline snapshot (forked from <name> at <hash-prefix>)`.
- Selecting an inline-snapshot user preset and pressing a Graph-tab
  edit key applies the edit immediately, no modal.
- Editing routing or budget on a stock-ref user preset never triggers
  a detach modal; the resulting save preserves `pipeline = "<name>"`.
- Re-attach action is visible in the command palette only for
  inline-snapshot user presets with a resolvable upstream name.
  Confirming the diff modal restores `pipeline = "<name>"` and
  removes `pipeline_inline`. Routing/budget are preserved
  byte-for-byte.
- Round-trip test: load a stock preset, fork it (stock-ref user
  preset), edit only routing, save, reload — graph source remains
  stock-ref, resolved graph byte-identical to the stock parent.
- Round-trip test: load a stock preset, fork it, detach, edit a
  stage, save, reload — graph source is inline-snapshot, the edit is
  preserved, `source_hash` is stable across reloads.
- All existing TUI unit tests pass after rename. New tests cover tab
  switching, stock-edit blocking, detach modal, re-attach palette
  action, and both round-trip scenarios.

---

## Phase 4 — Single Activate action + persistent footer

Depends on P3.

**Files**

- `swarm-do/py/swarm_do/tui/app.py` (workbench bindings + AppChrome
  + StatusBar updates).
- `swarm-do/py/swarm_do/tui/state.py` (helper that creates a user
  preset from a stock template and marks it active in one call).
- `swarm-do/py/swarm_do/pipeline/actions.py` (idempotent activate
  helper if not already present).

**Changes**

- Add a new global binding `A` (capital A) on the Preset workbench
  labeled `Use this for next /swarmdaddy:do`. Behavior:
  1. If the selected preset is `origin = stock`, materialize a
     **stock-ref** user fork via `suggested_fork_name(stock_name,
     suffix="active")`. The fork copies routing and budget from the
     stock parent and writes `pipeline = "<stock_name>"` (no detach;
     no `pipeline_inline`). This preserves stock graph follow-along
     by default.
  2. Validate the (possibly newly-forked) preset via
     `validate_preset_mapping` (Phase 1). Block activation on hard
     errors with a modal listing them.
  3. Write the active-preset state via the existing active-preset
     helper used by `active_preset_name()` (`resolver.py:76`). No new
     state file.
  4. Pop a confirmation modal showing:
     - `Active: <preset-name>`.
     - `Graph: stock-ref to <name>` or
       `Graph: inline snapshot (forked from <name> at <hash-prefix>)`.
     - `Next: /swarmdaddy:do <plan-path>` — with the literal slash
       command on a single line so the user can copy it.
- The previous `l` (Presets `load`) and `a` (Pipelines `activate`)
  bindings collapse: `l` is removed, `a` (lowercase) becomes a synonym
  for `A` and works identically. Existing telemetry/keystroke users
  see no behavior change.
- Vocabulary lock applied across the workbench, footer, modals, and
  HELP strings:
  - "Activate" — the action that makes a preset active.
  - "New from template" — replaces "Fork" everywhere.
  - "Active preset" — the only state name.
  - "Pipeline" disappears from user-facing TUI copy. It remains in
    file paths and developer docs.
- Persistent footer extends `AppChrome` (already on all four screens
  per `app.py:755, 894, 989, 1148`). The chrome refresh path
  (`refresh_chrome` at `app.py:446`) already runs on screen activation;
  extend it to also write a single line:
  `Active: <preset> | Beads: ok|missing | Providers: ok|warn|error|unchecked`.
  Provider state is read from a session-only in-memory cache held on
  the App instance; the cache starts as `unchecked` and updates only
  when the user runs `Ctrl+H` provider doctor (Phase 5). Beads state
  is read from a cheap `actions.has_beads_rig()` check called on
  screen mount.

**Acceptance**

- From a clean repo with no user presets: select the `balanced` stock
  preset, press `A`, dismiss the modal. The next `/swarmdaddy:do` uses
  a freshly-materialized user fork named `balanced-active` whose graph
  source is **stock-ref to default** (the same pipeline `balanced`
  references). No `pipeline_inline` is written. Resolved graph is
  byte-identical to `balanced`'s.
- Press `A` again on the freshly-active stock-ref user preset:
  validation passes, the same preset stays active, modal shows
  `Graph: stock-ref to default`.
- Detach the user preset's graph via the Graph tab, then press `A`:
  the modal shows `Graph: inline snapshot (forked from default at
  <hash-prefix>)`.
- Modal shows the next command verbatim with the `<plan-path>`
  placeholder.
- Footer renders the same active-state line on Dashboard, Preset
  workbench, and Settings.
- New unit tests cover: stock-fork-then-activate, activate-existing-
  user-preset, activate-when-validation-fails (modal blocks), footer
  rendering across all three screens, footer provider-state
  transitions (unchecked → ok after Ctrl+H).

---

## Phase 5 — TUI structure cleanup

Depends on P3, P4. Independent of P2 and P6.

**Files**

- `swarm-do/py/swarm_do/tui/app.py`
- `swarm-do/py/swarm_do/tui/app.tcss`

**Changes**

- Move provider doctor `Ctrl+D` → `Ctrl+H`. `Ctrl+D` stays registered
  as a deprecated alias that fires the same action and writes
  `Ctrl+D is deprecated; use Ctrl+H` to the StatusBar.
- Promote provider doctor to a Dashboard-level action labeled
  `Ctrl+H Health` when the active preset's resolved graph contains
  a provider stage (use `pipeline_has_provider_stage` from `state.py`).
- Trim Preset workbench Graph-tab visible bindings to: `r b n o m
  Delete f/Enter Ctrl+S Esc Ctrl+H A`. Move `g`, `t`, `y`, `Ctrl+R`,
  `Ctrl+Z`, `Ctrl+Y` into the command palette only — they remain
  callable but are not shown in the Footer.
- Update HELP strings on Dashboard, Preset workbench, and Settings to
  match the new bindings.

**Acceptance**

- `grep -nE 'ctrl\+d|ctrl\+h' swarm-do/py/swarm_do/tui/app.py` shows
  the deprecated `Ctrl+D` alias plus the canonical `Ctrl+H` binding.
- Pressing `Ctrl+D` in the TUI runs provider doctor and shows the
  deprecation toast in the StatusBar.
- Pressing `Ctrl+H` runs provider doctor with no toast.
- The Graph-tab Footer shows ≤11 visible bindings.
- Dashboard exposes `Ctrl+H Health` only when the active preset's
  resolved graph contains a provider stage (verified by switching the
  active preset between `default` and `lightweight`).
- All existing tests pass; new tests cover the alias toast and the
  Dashboard provider-doctor visibility predicate.

---

## Phase 6 — Getting Started panel

Depends on P2 (`/swarmdaddy:quickstart` runs init-beads + migrator)
and P4 (Activate + footer).

**Files**

- `swarm-do/py/swarm_do/tui/app.py` (DashboardScreen.compose +
  refresh_dashboard).
- `swarm-do/py/swarm_do/tui/state.py` (extend `status_summary` to
  return a `getting_started_visible: bool` field).

**Changes**

- The Getting Started panel renders on Dashboard above the runs table
  when ALL of the following are true:
  - No active user preset is set (`active_preset_name()` returns
    `None`).
  - No in-flight runs exist.
  - `${CLAUDE_PLUGIN_DATA}/telemetry/runs.jsonl` is missing or empty.
- The panel contains, in order:
  1. Three traffic-light rows: Beads rig, active preset, providers.
     Each row shows `ok` (green), `warn` (yellow), or `missing/error`
     (red). Beads is green if `actions.has_beads_rig()` returns True;
     active preset is green if any user preset is active, yellow if
     none (the silent-default state), red if a referenced preset file
     is missing; providers reflect the in-memory cache from Phase 4.
  2. A single line: `Plan path?` with an `Input` widget below it.
  3. On submit, write the literal `/swarmdaddy:do <typed-path>` to
     the StatusBar AND copy it to the system clipboard via the
     existing `y` board-copy hook. Then dismiss the panel.
- Once the panel has been dismissed by submission once, persist a
  sentinel `${CLAUDE_PLUGIN_DATA}/.getting-started-dismissed` so it
  does not re-render on subsequent launches even if telemetry is
  cleared.

**Acceptance**

- Fresh repo with no telemetry and no active preset: open TUI →
  Dashboard renders the panel. Three traffic lights match actual
  state. Submitting a path prints the next command to StatusBar and
  copies to clipboard, then the panel collapses.
- Existing repo with prior runs: panel is suppressed; current
  Dashboard renders unchanged.
- After dismissal sentinel exists: panel does not re-render even if
  `runs.jsonl` is later truncated.
- New unit test covers panel visibility predicate combinations and
  sentinel behavior.

---

## Phase 7 — Docs sync

Depends on final vocab from P3 + P4 + P5.

**Files**

- `swarm-do/README.md`
- `swarm-do/tui/README.md`
- `swarm-do/role-specs/README.md` (only the parts that mention
  pipeline vs preset).

**Changes**

- Replace every `d`/`s`/`p`/`i` top-level key with `1`/`4`/`3` (note:
  no `5` — Settings moved to `4` after Pipelines was removed). Update
  the navigation table and the prose sentence at the bottom of the
  TUI Configuration Console section.
- Replace every "press d for provider doctor" with "press `Ctrl+H`
  (formerly `Ctrl+D`) for provider doctor".
- Reorder Quick Start: surface the zero-config path
  (`/swarmdaddy:quickstart` then `/swarmdaddy:do <plan>`) as the
  primary flow, with preset customization as the optional second
  flow. Document that `/swarmdaddy:configure` is the inspect-only
  TUI launcher and `/swarmdaddy:setup` is deprecated.
- Replace "open a Beads issue" in the Dashboard description with
  "open the run's Beads issue".
- Remove every reference to "Pipelines screen" from user-facing docs
  (developer docs under `docs/` keep their existing references).
- Replace "preset" + "pipeline" pair with "preset" alone wherever the
  pair appeared in user-facing prose. The "Presets, Pipelines, And
  Prompt Lenses" section is renamed "Presets And Prompt Lenses" and
  its body rewritten to describe the unified model.
- Update the README's preset/pipeline example snippets to show a
  `[pipeline_inline]` user preset and a `pipeline = "default"` stock
  preset side-by-side.

**Acceptance**

- `grep -nE '\b(d|s|p|i)\b dashboard|provider doctor.*\bd\b|press d'
  swarm-do/README.md swarm-do/tui/README.md` returns no stale
  references.
- README and `tui/README.md` agree on every key shown.
- The phrase "Pipelines screen" appears nowhere in user-facing docs.
- Generated-section markers (`<!-- BEGIN/END: generated-by ... -->`)
  are not edited by hand. Run-and-check pass after the doc edits:
  `PYTHONPATH=py python3 -m swarm_do.roles gen readme-section
  --check` and `PYTHONPATH=py python3 -m swarm_do.telemetry.gen
  readme-section --check`.

---

## Phase 8 — CLI verb deprecation

Independent of all other phases.

**Files**

- `swarm-do/bin/swarm`
- `swarm-do/py/swarm_do/cli/__init__.py` (or wherever the `mode` and
  `preset load` handlers live; exact site identified during
  implementation via `grep -rn 'def cmd_mode\|preset.load\|cmd_preset'
  swarm-do/py swarm-do/bin`).
- `swarm-do/README.md` "CLI Reference" section.

**Changes**

- `swarm preset load <name>` is the canonical verb.
- `swarm mode <name>` continues to work but writes to stderr exactly
  once per invocation: `swarm mode is deprecated; use 'swarm preset
  load <name>'`.
- README CLI Reference shows only `swarm preset load <name>` in the
  primary table, with a footnote: `swarm mode <name> is a deprecated
  alias of swarm preset load <name>`.

**Acceptance**

- `swarm mode <name>` exits 0 and emits the deprecation notice
  exactly once.
- `swarm preset load <name>` is documented as the primary verb.
- README's CLI Reference no longer lists `mode` as a primary verb.

---

## Definition of done

- All eight phases shipped, each behind its own Beads issue and PR.
- A user who runs `/swarmdaddy:quickstart` in a fresh repo, confirms
  the prompt, and pastes the next-command line printed by the TUI
  reaches a green `/swarmdaddy:do` run without ever opening the Preset
  workbench manually.
- A user who selects a stock preset and presses `A` (or the lowercase
  `a` synonym) materializes a stock-ref user fork, marks it active,
  and sees the next command in a confirmation modal — all in one
  keystroke. Editing only routing/budget on that fork preserves the
  stock-ref graph source. Editing the Graph tab triggers an explicit
  detach modal.
- Persistent footer shows `Active: <preset> | Beads: ok | Providers:
  ok|warn|error|unchecked` on Dashboard, Preset workbench, and
  Settings.
- No user-facing TUI surface mentions "pipeline" as a separate
  entity. The word survives only in stock file paths, developer
  docs, and the schema's `pipeline = "<name>"` field name.
- The backend graph-source abstraction is preserved: stock-ref and
  inline-snapshot forms both round-trip through `render_toml`,
  validate, doctor, hash, and run dispatch identically.
- `/swarmdaddy:configure` has zero side effects (no `.beads/` write,
  no migrator invocation, no stdin prompt).
- `/swarmdaddy:setup` prints a deprecation banner and delegates to
  `configure` with no other side effects.
- The migrator never silently synthesizes presets. Orphan user
  pipelines are archived and reported with explicit `swarm preset
  adopt` instructions.
- All existing unit tests pass; new tests cover graph-source
  resolution (both forms), nested-array TOML round-trip,
  migrator pair + orphan paths, `swarm preset adopt`, detach and
  re-attach primitives, Activate flow with both source forms,
  footer rendering, Getting Started panel, `Ctrl+D` deprecation
  toast, and `swarm mode` deprecation notice.
- Generator-backed docs pass:
  - `PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'`
  - `PYTHONPATH=py python3 -m swarm_do.roles gen readme-section --check`
  - `PYTHONPATH=py python3 -m swarm_do.telemetry.gen readme-section --check`
  - `PYTHONPATH=py python3 -m swarm_do.telemetry.gen docs --check`
