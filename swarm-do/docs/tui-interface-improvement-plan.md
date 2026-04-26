# TUI Interface Improvement Plan

Date: 2026-04-26

## Goal

Make `bin/swarm-tui` understandable as an operator console, not a set of
disconnected configuration rooms.

The redesigned interface must let an operator answer these questions quickly:

- Where am I in the app?
- What preset and pipeline are active?
- What is the selected pipeline actually going to do?
- Which agents or providers run in parallel, which stages join, and what
  happens next?
- How do I get back to the dashboard or another section?
- What action is safe from here, and what will it change?

The load-bearing change is a graph-first Pipelines workbench. If users cannot
see the agent flow as a graph, the rest of the interface will keep feeling like
raw configuration tables.

## Feasibility Check

This plan is valid for the current codebase and Textual setup.

Local facts verified on 2026-04-26:

- The managed TUI venv currently imports Textual `0.89.1`.
- `TabbedContent`, `TabPane`, `Tree`, `OptionList`, `Static`, `DataTable`,
  `Footer`, `Header`, and `SystemCommand` import successfully in that venv.
- `App.COMMAND_PALETTE_BINDING` is `ctrl+p`, and
  `App.ENABLE_COMMAND_PALETTE` is `True`.
- The current requirements range is `textual>=0.80,<1`, so these APIs are in
  the supported local range.
- The current app already uses `Screen`, `Header`, `Footer`, `DataTable`,
  `ListView`, `Static`, `ModalScreen`, and CSS in `py/swarm_do/tui/app.py`.
- The pipeline graph data already exists:
  `py/swarm_do/pipeline/engine.py` exposes `topological_layers()` and
  `graph_lines()`.
- `py/swarm_do/tui/state.py` already converts pipelines into `StageRow` rows
  and stage inspector text. This is the right place to add pure graph model and
  render helpers before wiring the app.

External dependency findings:

- Textual does not ship a first-party DAG widget.
- That is not a blocker. A graph-first workbench can be implemented with a
  custom `Static`/Rich-text renderable in v1.
- `py-dagviz`, `textual-canvas`, Graphviz image output, and terminal image
  protocols are plausible later options, but none should be required for the
  first implementation pass.

Important testing caveat:

- The managed TUI venv does not currently include `pytest`. Use the normal repo
  test environment for unit tests, or add a dev/test dependency path separately.

## UX Findings To Preserve

The current interface is technically navigable but not experientially
navigable.

The main pain points are:

- Section navigation is only exposed through the footer, so it disappears into
  local command noise.
- Global keys collide with screen-local keys. For example, top-level `d` means
  Dashboard, but Pipelines uses `d` for Doctor and Presets uses `d` for Diff.
- The Dashboard has too much empty space when no runs are active, even though
  active preset/pipeline orientation is what the user needs most.
- Pipelines shows a list of stages, but users need a mental model of the DAG:
  fan-out, dependency joins, provider-review evidence, final review, and docs.
- The Pipelines screen gives equal or greater visual weight to low-level
  editing controls than to understanding the workflow.
- Settings shows effective routes well, but it reads as a data dump because it
  lacks scoped explanation and progressive detail.
- The footer tries to carry navigation, action discovery, and app status at the
  same time. It cannot do all three clearly.

Good TUI patterns to emulate:

- Persistent app orientation, not only per-screen hotkeys.
- Command palette for global navigation and actions.
- Contextual help for the focused panel.
- Workspace panes where the largest pane is the primary user object.
- Data tables for dense values, but only after the user has a clear frame for
  what the data means.
- Graph or map first for workflow tools, details second.

Reference TUIs worth studying before implementation:

- Harlequin: app shell, tabbed details, command palette, and database-workbench
  density.
- Posting: panel synchronization, palette-first navigation, and Textual
  authoring conventions.
- k9s: persistent section/status/command bars across many rooms.
- lazygit: focused-pane semantics and footer hints that change with focus.
- gh dash: section-grouped scrollable lists for the Pipeline Gallery.
- dive: layered dependent-item explorer with synchronized details, the closest
  behavior model for revealing pipeline layer structure.
- Toolong / Textual `RichLog`: active event strip behavior for Dashboard.
- mitmproxy flow view: packed list selection driving an adjacent detail panel
  during live activity.

## Design Principles

1. Keep a persistent app shell.

   The app should always show section navigation and current context. The user
   should never have to remember whether `d` currently means Dashboard, Doctor,
   or Diff.

2. Make Pipelines a graph workbench.

   Pipeline selection, stage details, validation, and editing all orbit the
   graph. The graph is not a preview tucked below a list; it is the primary
   surface.

3. Separate global navigation from local actions.

   Use stable global keys such as `1` Dashboard, `2` Runs, `3` Pipelines,
   `4` Presets, `5` Settings, plus `ctrl+p` for the command palette. Let local
   screen actions use mnemonic letters without stealing app navigation.

4. Keep first-pass rendering dependency-free.

   Build the v1 graph with Textual/Rich primitives and pure state helpers.
   Bring in a canvas or DAG package only if the dependency-free graph cannot
   satisfy the actual operator workflow.

5. Prefer progressive disclosure.

   The default view answers "what happens?" Details answer "how is this stage
   configured?" Editing answers "what will change if I save?"

6. Preserve keyboard-first operation.

   Every click path should have a key path. The UI should also remain usable
   over SSH and inside cmux panes.

7. Shape first, color second.

   Node semantics must survive monochrome terminals, SSH, Solarized themes, and
   colorblind use. Color can reinforce meaning, but shape and text carry the
   primary signal.

8. Editing stays modal.

   The graph is for comprehension, selection, status, and navigation. Forking,
   route edits, provider edits, and YAML edits stay in explicit modals or
   secondary panes. Do not turn the graph into an inline editor.

## Proposed App Shell

Replace the current "each screen owns its whole chrome" feel with a consistent
shell.

Recommended chrome:

```text
SwarmDaddy   [1 Dashboard] [2 Runs] [3 Pipelines] [4 Presets] [5 Settings]   ^p Commands
preset=balanced  pipeline=default  draft=none  validation=OK
```

Implementation options:

- Low-risk option: keep separate Textual `Screen`s, but add a shared
  `AppChrome` widget at the top of each screen and reserve global navigation
  keys.
- Higher-refactor option: use a single screen with `TabbedContent` or a custom
  content switcher. This reduces duplicated chrome but touches more code.

Recommendation:

- Start with the low-risk shared `AppChrome` widget.
- Keep `Footer()` for contextual local actions, but do not depend on it for
  global orientation.
- Add command palette entries through `SwarmTui.get_system_commands()`.

Global navigation binding proposal:

| Key | Destination |
| --- | --- |
| `1` | Dashboard |
| `2` | Runs / active runs view |
| `3` | Pipelines |
| `4` | Presets |
| `5` | Settings |
| `ctrl+p` | Command palette |
| `q` | Quit |

Initial implementation can map `2` to the existing Dashboard run table until a
separate Runs screen exists.

Command palette entries:

- Go to Dashboard
- Go to Pipelines
- Go to Presets
- Go to Settings
- Show Help
- Validate Selected Pipeline
- Fork/Edit Selected Pipeline
- Save Pipeline Draft
- Discard Pipeline Draft
- Copy Pipeline Graph
- Run Provider Doctor

## Graph-First Pipelines Workbench

This is the main redesign.

### Long-Term Workbench Direction

The path that gives the best long-term result is a layered text workbench, not
an immediate canvas editor.

Recommended renderer progression:

1. **V1: semantic layered text renderer.**

   Build a pure graph model, then render it with a Sugiyama-style layered
   layout: topological layer assignment from the existing engine, deterministic
   barycentric reordering within layers to reduce crossings, box-drawing edges,
   pinned semantic node shapes, compact mode, and a numbered linear fallback.

2. **V2: focusable graph with overlays.**

   Make the graph navigable and reusable across Pipelines and Dashboard. Add
   selection, live status badges, dirty/diff overlays, provider/evidence
   styling, copy-to-clipboard, and critical-path highlighting.

3. **V3: navigation aids and optional image renderer.**

   Add mini-map/"you are here" support if graphs exceed the terminal width.
   If text rendering proves insufficient for dense pipelines, render Graphviz
   to PNG and display it through `textual-image` or terminal image protocols on
   capable terminals. Keep the text renderer as the always-available path.

This keeps the first implementation testable while leaving a credible upgrade
path. `textual-canvas` is still a possible future choice if direct interactive
canvas gestures become necessary, but it should not be the first escalation.

Highest-leverage first-pass additions:

- Sugiyama-style layer reordering, so a 6+ stage DAG does not devolve into
  crossing list art.
- Box-drawing edges and joins, with ASCII fallback for `LANG=C`, dumb
  terminals, or explicit monochrome mode.
- Shape-based node semantics:
  - agents: square box, `┌─┐`
  - provider work: rounded box, `╭─╮`
  - evidence/answer-producing stages: double-line box, `╔═╗`
- Compact and linear modes from the start, so Dashboard reuse and narrow cmux
  panes do not become special cases later.

### Target Layout

```text
SwarmDaddy   [1 Dashboard] [2 Runs] [3 Pipelines] [4 Presets] [5 Settings]   ^p Commands
preset=balanced  pipeline=default  draft=none  validation=OK

+--------------------------+ +----------------------------------------------------------+ +--------------------------+
| Pipelines                | | Execution Graph: default                                 | | Stage Inspector          |
| implement                | |                                                          | | research                 |
|   default [stock]        | | ┌ research ┐                                             | | kind: agents             |
|   lightweight [stock]    | |      ├──▶ ┌ analysis ┐ ──┐                               | | role: agent-research     |
|   ultra-plan [stock]     | |      └──▶ ┌ clarify  ┐ ──┴──▶ ┌ writer ┐                 | | deps: none               |
| review                   | |                              │                           | | route: preset/hard       |
|   review [stock]         | |                              ├──▶ ┌ spec-review ┐        | |                          |
| design                   | |                              │        ├──▶ ┌ review ┐    | | actions                  |
|   design [stock]         | |                              │        └──▶ ┌ docs ┐      | | enter edit/fork          |
| custom                   | |                              └──▶ ╭ provider-review ╮    | | r route  o provider      |
+--------------------------+ +----------------------------------------------------------+ +--------------------------+

+--------------------------------------------------------------------------------------------------------------------+
| Validation / Budget / Provider Readiness                                                                           |
| OK structural validation  budget agents=8 cost=$1.4400 wall=1920s  provider doctor required for swarm-review       |
+--------------------------------------------------------------------------------------------------------------------+
```

The visual graph pane must be the largest object on the screen. The stage list
is not the center of gravity anymore.

### Required Graph Semantics

The graph must make these concepts visible:

- **Stage order:** left-to-right or top-to-bottom by topological layer.
- **Dependencies:** edges from each dependency to the dependent stage.
- **Parallel branches:** multiple stages in the same layer should read as
  parallel work.
- **Fan-out stages:** show branch count and variation mode inside the node.
  Example: `exploration x3 prompt_variants`.
- **Merge stages:** show synthesize merge agent inside the fan-out node.
  Example: `merge: agent-analysis-judge`.
- **Provider stages:** visually distinguish evidence/provider work from normal
  agent work by shape first and color second.
  Example: `provider-review (swarm-review, best-effort)`.
- **Join points:** when a stage has multiple dependencies, the incoming edges
  must make the join obvious.
- **Terminal outputs:** final review/docs stages should be visually findable.
- **Draft/validation status:** invalid stages or graph errors should be marked
  directly on the node when possible.
- **Selection:** selected graph node and inspector must stay synchronized.
- **Live run status:** the same renderer should be able to add `running`,
  `done`, `failed`, and `queued` badges when Dashboard shows active runs.
- **Route diff status:** draft route overrides should tint or mark affected
  nodes so edits feel concrete.
- **Critical path:** when budget/wall-clock estimates are available, the graph
  should be able to emphasize the longest estimated path through the DAG.
- **Swimlanes:** when width allows, stage kinds should align into stable lanes
  so provider/evidence work is structurally visible even without color.

### V1 Graph Rendering Strategy

Implement a deterministic dependency-free renderer first.

Add pure model helpers in `py/swarm_do/tui/state.py`:

```python
@dataclass(frozen=True)
class PipelineGraphNode:
    stage_id: str
    layer: int
    kind: str
    lane: str
    shape: str
    title: str
    subtitle: str
    depends_on: tuple[str, ...]
    outgoing: tuple[str, ...]
    fan_out_count: int | None
    fan_out_variant: str | None
    merge_agent: str | None
    provider_type: str | None
    tolerance: str | None
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class PipelineGraphEdge:
    source: str
    target: str

@dataclass(frozen=True)
class PipelineGraphModel:
    nodes: tuple[PipelineGraphNode, ...]
    edges: tuple[PipelineGraphEdge, ...]
    layers: tuple[tuple[str, ...], ...]

@dataclass(frozen=True)
class PipelineGraphOverlay:
    selected_stage_id: str | None
    stage_statuses: Mapping[str, str]
    dirty_stage_ids: frozenset[str]
    critical_stage_ids: frozenset[str]
    highlighted_stage_ids: frozenset[str]
```

Add these helpers:

- `pipeline_graph_model(pipeline) -> PipelineGraphModel`
- `pipeline_graph_overlay(...) -> PipelineGraphOverlay` for draft/live/status
  concerns that do not belong in the topology model.
- `pipeline_graph_lines(model, overlay=None, width=None, compact=False,
  linear=False, ascii_only=False) -> list[Text | str]`
- `pipeline_graph_legend_lines(model, ascii_only=False) -> list[str]`

Use the existing `topological_layers()` as the source of truth. Do not create a
new graph algorithm for execution order. Layer reordering is allowed only
within a topological layer and must remain deterministic.

Layered text layout algorithm:

1. Build layer columns from `topological_layers()`.
2. Assign each node a semantic lane and shape.
3. Apply barycentric reordering within layers to reduce edge crossings.
4. Route orthogonal box-drawing edges with explicit join markers.
5. Prefer wide layered mode when it fits.
6. Use `compact=True` for Dashboard and small panels.
7. Use numbered linear topological mode for very narrow panes and screen
   readers.

Initial renderer requirements:

- Render a compact DAG map that fits the current terminal width where possible.
- Use box-drawing edges and joins by default.
- Fall back to ASCII edges when terminal capabilities are unknown or explicitly
  plain.
- Fall back gracefully to a vertical tree/DAG projection on narrow terminals.
- Fall back to a numbered topological list when even the tree projection is too
  cramped.
- Mark repeated join nodes as joins rather than pretending the graph is a pure
  tree.
- Use shape and labels for agents, provider/evidence, fan-out, selected, dirty,
  warning, and error states. Use Textual/Rich styling as enhancement.
- Include live-status badges when an overlay provides status.
- Support critical-path and dirty-stage overlays without changing the graph
  topology model.
- Memoize rendered output by `(pipeline_id, draft_revision, overlay_fingerprint,
  width, compact, linear, ascii_only)`.
- Keep all graph rendering pure and unit-testable without Textual. If the
  normal repo test environment does not include Rich, return plain strings or
  style-span data from `state.py` and let the Textual widget convert that into
  Rich `Text`.

Acceptable v1 visual forms:

1. Wide terminal:

   ```text
   ┌ research ┐
        ├───────▶ ┌ analysis ┐ ──┐
        └───────▶ ┌ clarify  ┐ ──┴──▶ ┌ writer ┐
                                             ├──▶ ┌ spec-review ┐ ──┬──▶ ┌ review ┐
                                             │                       └──▶ ┌ docs   ┐
                                             └──▶ ╭ provider-review ╮ ───▶ ┌ review ┐ (join)
   ```

2. Narrow terminal:

   ```text
   ┌ research ┐
   ├── ┌ analysis ┐
   │   └── ┌ writer ┐
   │       ├── ┌ spec-review ┐
   │       │   ├── ┌ review ┐
   │       │   └── ┌ docs ┐
   │       └── ╭ provider-review ╮
   │           └── ┌ review ┐ (join)
   └── ┌ clarify ┐
       └── ┌ writer ┐ (join: analysis + clarify)
   ```

3. Linear fallback:

   ```text
   1. research [agents]
   2. analysis [agents] depends_on=research
   3. clarify [agents] depends_on=research
   4. writer [agents] depends_on=analysis,clarify
   5. spec-review [agents] depends_on=writer
   6. provider-review [provider] depends_on=writer
   7. review [agents] depends_on=spec-review,provider-review
   8. docs [agents] depends_on=spec-review
   ```

The narrow fallback is allowed to repeat join nodes only if it labels them as
joins. It must not hide the fact that `writer` waits for both `analysis` and
`clarify`, or that `review` waits for both `spec-review` and
`provider-review`.

### V2 Graph Interaction

After v1 proves useful, make the graph itself focusable.

Add `PipelineGraphView(Static)` or a custom `Widget` with:

- `selected_stage_id` passed from `PipelinesScreen`; the screen owns a single
  `Reactive[str | None]` selected stage id and all panels watch it.
- Arrow-key movement between connected stages:
  - `left/right`: previous/next topological layer.
  - `up/down`: previous/next node within a layer.
  - `enter`: open the existing edit/fork modal for the selected stage.
- `g`: focus graph.
- `t`: focus stage table/details.
- `y`: copy/yank the current graph as plain text through
  `App.copy_to_clipboard`.
- Mouse click selection if Textual event handling is straightforward.
- Scroll support for large graphs.
- Optional corner mini-map when horizontal scroll is introduced.

The graph must never become the edit form itself. Route/provider edits, fork,
save, discard, and raw YAML stay modal or secondary-detail workflows.

If the graph becomes too awkward as text, first evaluate Graphviz-to-PNG through
`textual-image` on capable terminals while keeping the text renderer as
fallback. Evaluate `textual-canvas` only if the product needs direct
interactive canvas behavior that an image cannot provide.

### Workbench Panels

Left panel: Pipeline Gallery

- Group by intent.
- Show active pipeline and stock/user/custom origin.
- Keep labels short. Move long descriptions to preview/inspector.
- Add a filter/search later if the list grows.

Center panel: Execution Graph

- Default focus for Pipelines.
- Largest panel.
- Shows graph legend only when there is space; otherwise use help/command
  palette.

Right panel: Stage Inspector

- Shows selected stage:
  - stage id
  - kind
  - dependencies
  - outgoing dependents
  - role/provider/fan-out summary
  - effective route source
  - live status / dirty route / critical-path markers when present
  - edit availability
  - warnings/errors
- Avoid raw YAML formatting in the default inspector.
- Raw YAML belongs in a secondary details tab or modal.

Bottom rail: Validation / Budget / Readiness

- One or two lines by default.
- Use severity prefixes: `OK`, `WARN`, `ERROR`, `BLOCKED`.
- Full validation modal remains available.

Optional lower/secondary view: Details Tabs

Use `TabbedContent` if useful:

- `Graph` (default)
- `Stages`
- `Routes`
- `Validation`
- `Diff`
- `Raw YAML`

Do not make `Stages` the default tab.

## Dashboard Improvements

The Dashboard should orient the user even when no runs are active.

Recommended Dashboard layout:

```text
+-------------------------------------------+ +------------------------------------------------+
| Active Profile                            | | Active Runs / Event Log                        |
| preset=balanced  pipeline=default         | | no in-flight runs                              |
| validation=OK     provider=needs doctor   | | 12:41 writer queued                            |
| budget estimate: agents=8 cost=$1.44      | | 12:42 provider-review waiting on doctor        |
+-------------------------------------------+ +------------------------------------------------+

+------------------------------------------------------------------------------------------------+
| Active Pipeline Graph                                                                          |
| ┌ research ┐ ├▶ ┌ analysis ┐ ┐                                                                 |
|              └▶ ┌ clarify  ┐ ┴▶ ┌ writer ┐ ...                                                 |
+------------------------------------------------------------------------------------------------+

+------------------------------------------------------------------------------------------------+
| In-Flight Runs                                                                                 |
| issue  role  backend  model  effort  pid  status                                               |
+------------------------------------------------------------------------------------------------+
```

Implementation notes:

- Reuse `pipeline_graph_model()` and `pipeline_graph_lines()` from the
  Pipelines workbench.
- Dashboard graph is read-only and always rendered with `compact=True`.
- Add a small `RichLog` event strip for the last N run/checkpoint/observation
  events. It should be filterable by selected stage once graph selection exists.
- Use live-status graph badges when active-run state can be mapped to stage ids.
- If no active preset/pipeline exists, show a clear empty state with the command
  to open Presets/Pipelines.

## Settings Improvements

Settings can stay table-first because it is inherently tabular, but it needs
stronger framing.

Changes:

- Title the table "Effective Role Routes".
- Add context line:
  `active preset=balanced origin=stock editing=read-only fork required`.
- Freeze headers and role column with `DataTable.fixed_rows = 1` and
  `fixed_columns = 1` if compatible with the current table behavior.
- Add command palette entries for "Edit selected route" and "Fork active
  preset".
- When a stock preset is active, show a persistent warning rail rather than
  only a modal after edit attempt.

## Presets Improvements

Presets should answer "which profile should I use?" before "what raw routing
keys exist?"

Changes:

- Group presets by intent/profile.
- Mark active preset.
- In preview, show:
  - pipeline
  - origin
  - budget summary
  - route override count
  - validation summary
  - diff/drift summary for user presets
- Move raw routing dump into a details tab or modal.
- Rename `d Diff` to avoid collision with Dashboard. Use `v View diff` or make
  it command-palette-first.

## Keybinding Policy

Reserved global keys:

- `1` Dashboard
- `2` Runs
- `3` Pipelines
- `4` Presets
- `5` Settings
- `ctrl+p` Commands
- `q` Quit
- `?` Help

Screen-local keys should avoid global keys. If a mnemonic conflicts, prefer the
screen-local action in the command palette or use a modified key.

Suggested local remaps:

| Current | Screen | Current Action | Suggested |
| --- | --- | --- | --- |
| `d` | Pipelines | Doctor | `o` Provider settings, `v` Validate with doctor, or command palette |
| `s` | Pipelines | Set | `a` Activate |
| `d` | Presets | Diff | `v` View diff |
| `s` | Settings | top-level nav conflict | use `5` globally; keep route save as `ctrl+s` |

Footer rule:

- Footer shows local actions for the focused screen.
- AppChrome shows global navigation.
- Command palette shows both.

## Implementation Phases

### Phase 1: Navigation And Chrome

Goal: stop users getting lost before changing the graph.

Tasks:

- Add shared `AppChrome` widget.
- Add global `1-5` navigation bindings in `SwarmTui`.
- Keep old `d/s/p/i` temporarily if desired, but remove them from the footer or
  mark them deprecated in docs. Prefer removing conflicting single-letter
  globals after the new keys land.
- Resolve local key collisions in Pipelines and Presets.
- Add `get_system_commands()` with global navigation commands.
- Add a first-pass `?` contextual help modal that lists global navigation,
  current screen actions, and the command palette binding.
- Update README TUI key map.

Tests:

- Unit or smoke test that `SwarmTui` exposes command palette system commands.
- Manual help check: `?` opens from each main screen and names the focused
  screen's useful keys.
- Manual launch: confirm every screen shows the same app chrome.
- Manual navigation: confirm Dashboard is reachable from Pipelines without
  depending on a hidden/conflicting `d` key.

### Phase 2: Pure Pipeline Graph Model

Goal: create a tested graph model without touching visual layout yet.

Tasks:

- Add `PipelineGraphNode`, `PipelineGraphEdge`, and `PipelineGraphModel` to
  `py/swarm_do/tui/state.py`.
- Add `PipelineGraphOverlay` or an equivalent immutable overlay structure for
  selection, live status, dirty route edits, critical path, and highlights.
- Implement `pipeline_graph_model(pipeline)`.
- Include stage kind, lane, shape, fan-out count, fan-out variant, merge agent,
  provider type, failure tolerance, dependencies, warnings, and outgoing
  dependents.
- Add graph model tests for:
  - default pipeline
  - design fan-out pipeline
  - competitive models fan-out
  - provider-review stage
  - invalid/cyclic graph fallback behavior
  - semantic shapes for agents/provider/evidence stages

Tests:

- `py/swarm_do/tui/tests/test_state.py` graph model assertions.
- Existing pipeline validation tests continue to pass.

### Phase 3: Text Graph Renderer

Goal: render a useful DAG map as text/Rich content.

Tasks:

- Implement `pipeline_graph_lines(model, overlay=None, width=None,
  compact=False, linear=False, ascii_only=False)`.
- Implement deterministic Sugiyama-style layered rendering:
  - topological layers from the existing engine
  - barycentric reordering within each layer
  - orthogonal box-drawing edges
  - explicit join markers
- Implement wide, narrow tree, compact, and numbered linear rendering modes.
- Add ASCII fallback for plain terminals.
- Mark selected node.
- Mark joins explicitly in narrow mode.
- Render node shape distinctions for normal agents, fan-out, provider/evidence,
  selected, dirty, live status, warning, and error states.
- Add optional swimlane ordering by stage kind when width allows.
- Add optional critical-path emphasis when the overlay provides
  `critical_stage_ids`.
- Add a small legend.
- Add renderer memoization keyed by pipeline id/revision, overlay fingerprint,
  width, compact/linear/ascii flags.
- Replace or supplement `graph_lines()` usage in TUI previews with the new
  renderer.

Tests:

- Snapshot-like unit tests on renderer output for default and design pipelines.
- Tests should assert semantics, not exact whitespace everywhere:
  - fan-out count appears
  - provider-review appears
  - joins are labeled
  - selected stage is marked
  - shape markers survive monochrome/plain-string assertions
  - narrow fallback repeats join nodes with `(join)`
  - linear fallback preserves complete topological order
  - compact mode stays under a small line budget suitable for Dashboard

### Phase 4: Pipelines Workbench Layout

Goal: make graph the primary Pipelines surface.

Tasks:

- Replace the current three-column `pipeline-gallery`, `stage-rows`,
  `stage-inspector` layout with:
  - left pipeline gallery
  - center execution graph
  - right stage inspector
  - bottom validation rail
- Keep stage rows available in a secondary tab or modal.
- Add `selected_stage_id: Reactive[str | None]` on `PipelinesScreen`.
- Synchronize selection:
  - Graph, stage table, inspector, and validation rail render from
    `selected_stage_id`.
  - Selecting a graph node updates `selected_stage_id`.
  - Selecting a stage row updates `selected_stage_id`.
  - Selecting a pipeline resets or preserves `selected_stage_id` only when the
    stage still exists, then refreshes graph, stage table, inspector, and
    validation rail.
- Move long raw stage details out of the default inspector.
- Keep edit/fork/route/provider/YAML changes in modals or secondary details;
  the graph selection can launch those flows but must not become the edit
  surface.
- Add focused empty states:
  - no pipeline selected
  - unreadable pipeline
  - graph validation error
  - stock pipeline selected, fork required to edit
- Add `y` or command-palette action to copy/yank the current graph as plain
  text.

Tests:

- Textual pilot/smoke test if available in the repo test environment.
- Manual cmux launch on a wide terminal and a narrow terminal.
- Verify text does not overflow badly in the screenshots' approximate width.

### Phase 5: Dashboard Orientation

Goal: make Dashboard useful even with no active runs.

Tasks:

- Add active profile summary.
- Add compact active pipeline graph.
- Keep in-flight runs table.
- Add a `RichLog` event strip for the last N checkpoint/observation/run events.
- Add latest checkpoint/observation summary from existing status state as the
  event strip's empty/minimal state.
- Map active-run stage state into graph badges when stage ids are available.
- Use empty states instead of huge blank areas.

Tests:

- State tests for active pipeline graph summary when active preset exists.
- State tests for compact graph line budget.
- Manual no-runs view.
- Manual one-run view.

### Phase 6: Graph Polish And Operator Loops

Goal: make the graph workbench feel like an operator console rather than a
static diagram.

Tasks:

- Add command palette actions for screen-specific commands.
- Refine `?` help content after the new graph interactions exist.
- Add visible validation severity styling.
- Add a default palette and monochrome fallback that survive SSH, cmux,
  Solarized, and low-contrast themes.
- Add route-diff mode: changed nodes marked green/changed, dirty nodes marked
  amber/dirty, with non-color glyphs as the primary signal.
- Add critical-path overlay using budget/wall-clock estimates once those
  estimates are stable enough at stage level.
- Add mini-map/"you are here" only if real stock/user pipelines exceed the
  graph pane width often enough to justify horizontal navigation.
- Polish borders and focus styles in `app.tcss`.
- Update README and any TUI docs.

Tests:

- Manual keyboard-only walkthrough:
  - open TUI
  - go to Pipelines
  - inspect default graph
  - fork stock pipeline
  - edit one route
  - validate
  - discard
  - return to Dashboard

## Rejected Alternatives

### Build A Full Canvas Graph Editor First

Why it loses:

- More dependencies and interaction complexity.
- Harder to test.
- More likely to stall before fixing the actual navigation/orientation problem.

Use only if the text/Rich graph proves insufficient after real use.

### Use Graphviz ASCII As The Main Renderer

Why it loses:

- Adds an external binary/build dependency.
- ASCII output availability depends on Graphviz build features.
- Styling and selection synchronization would be awkward.

### Use Graphviz PNG / `textual-image` As V1

Why it loses:

- Excellent escape hatch, but the first renderer still needs to work in plain
  SSH/cmux panes.
- Image output makes selection, diff overlays, and copy-as-text harder unless a
  text renderer already exists.
- It shifts testing toward visual snapshots before the semantic model is
  proven.

Use later as a capability upgrade when terminals support kitty/sixel/iTerm
images or when dense pipelines outgrow box-drawing.

### Use `py-dagviz` Immediately

Why it loses for v1:

- Adds `networkx` and a new graph library before proving the UX.
- The repo already has topological layer logic and small pipeline DAGs.

Potential later use:

- Compare renderer output if pipelines grow complex enough that local text
  layout becomes expensive to maintain.

### Use Braille / Drawille As The Primary Graph

Why it loses:

- It looks dense and impressive, but it is usually harder to read for the small
  and medium DAGs this app has today.
- It weakens copy/paste and screen-reader behavior.

Keep it parked unless pipelines become so dense that box-drawing plus
Sugiyama-style ordering cannot stay readable.

### Put Editing Directly In The Graph

Why it loses:

- It overloads the comprehension surface with form state.
- It makes keyboard interaction ambiguous: selection, navigation, and editing
  fight for the same keys.
- It creates more failure modes for stock-vs-user fork safety.

Graph selection may launch edit/fork modals, but editing itself stays explicit.

### Keep The Stage List As The Primary Workbench

Why it loses:

- It preserves the current mental-model problem.
- Lists hide dependency joins and parallel work.
- The operator still has to reconstruct the swarm flow manually.

## Risks And Mitigations

Risk: text graph rendering becomes too hard to read for complex DAGs.

Mitigation: start with known stock pipelines, use Sugiyama-style layer
reordering and box-drawing joins, add compact and linear fallbacks, and keep
stage table/details available. Escalate to Graphviz image output first, then
`textual-canvas` only if direct canvas interaction is truly needed.

Risk: graph and stage selection drift out of sync.

Mitigation: store one `Reactive[str | None] selected_stage_id` in
`PipelinesScreen`; every panel renders from that state.

Risk: graph redraws become noticeable as focus changes or run events stream in.

Mitigation: keep the graph model immutable, separate fast-changing overlays
from topology, and memoize render output by pipeline/revision/overlay/width.

Risk: color-heavy styling fails over SSH, cmux, monochrome, or colorblind use.

Mitigation: make node shape, labels, and glyphs the primary signal; treat color
as enhancement only.

Risk: command palette duplicates footer actions without improving discovery.

Mitigation: make the palette useful for global navigation first, then add only
high-value local actions.

Risk: keybinding changes break operator muscle memory.

Mitigation: document new `1-5` navigation, optionally keep old global letters
for one release only where they do not conflict, and prioritize removing
collisions in Pipelines/Presets.

Risk: visual polish expands scope.

Mitigation: phase the work. Navigation and graph semantics ship before color or
layout polish.

## Acceptance Criteria

The work is successful when:

- A user can always see how to get to Dashboard, Pipelines, Presets, and
  Settings.
- `?` opens contextual help from each main screen.
- Pipelines opens to a graph-first view.
- The default pipeline graph visibly shows:
  - research splitting to analysis and clarify
  - writer waiting for both
  - spec-review and provider-review running after writer
  - review waiting for both spec-review and provider-review
  - docs following spec-review
- Fan-out pipelines visibly show branch count and merge agent.
- Provider stages are visually distinct from normal agent stages by shape, not
  only color.
- Selecting any graph node updates the inspector.
- Validation/budget/provider readiness is visible without opening a modal.
- Narrow terminals can switch to a numbered linear topological view.
- The Dashboard is informative even when there are no in-flight runs.
- The Dashboard includes a compact graph and a small recent-event strip.
- Global navigation no longer collides with Doctor/Diff/Set actions.
- Editing/forking is launched from the graph when useful but remains modal.

## Implementation Entry Point

Start with **Phase 1: Navigation And Chrome**, then implement **Phase 2: Pure
Pipeline Graph Model** before touching the Pipelines layout.

Do not begin a canvas or external graph dependency spike until the dependency-
free `pipeline_graph_model()` and layered box-drawing `pipeline_graph_lines()`
path has been tried against the stock pipelines in wide, compact, narrow, and
linear modes.
