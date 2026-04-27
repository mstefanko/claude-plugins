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
- Copy Pipeline Board
- Run Provider Doctor

## Graph-First Pipelines Workbench

This is the main redesign.

Implementation note: the remaining graph readability work is tracked as the
focused executable plan in `docs/tui-layer-board-execution-plan.md`. This
section remains useful as design background and rationale. As of
2026-04-27, the Pipelines center surface uses the native `PipelineLayerBoard`
with top-to-bottom layers, actor/provider card titles, compact/linear
plain-text fallbacks, and quieter critical-path styling; the legacy edge-dense
`PipelineGraphView` is no longer mounted. The Presets screen also reuses the
same board as a read-only profile preview: presets are not separate DAGs, but
they can overlay routes, budget, and provider policy onto their linked
pipeline.

### Long-Term Workbench Direction

The path that gives the best long-term result is a native Textual
**layer-board workbench**, not a denser box-drawing graph and not an immediate
image/canvas renderer.

The v3 text graph proved that the underlying graph semantics are useful, but
also exposed the main comprehension problem: edge syntax and box-drawing glyphs
compete with the workflow. Operators should not have to decode branch art before
they can answer "what runs next?" or "what waits for what?"

The next iteration should treat the graph as a board of topological layers:

- columns show execution order;
- cards show stages;
- cards stacked in the same column show parallel work;
- join badges show stages with multiple dependencies;
- provider, fan-out, terminal, dirty, warning, live, and critical-path states
  are card badges/classes;
- detailed dependencies move into the selected card and inspector instead of
  being encoded primarily as crossing edge lines.

Recommended renderer progression:

1. **V1: native layer-board component.**

   Use the pure graph model as the source of truth, then render topological
   layers as Textual columns and stages as focusable cards. Make joins explicit
   with badges/chips. Keep the visual grammar stable across themes by relying
   on shape, labels, and badges first, color second.

2. **V2: richer overlays and optional lightweight connectors.**

   Add selection, live status badges, dirty/diff overlays, provider/evidence
   styling, copy-to-clipboard, and critical-path highlighting. Add simple
   connector hints only where they improve comprehension. Do not recreate the
   dense edge-rendering problem inside the board.

3. **V3: navigation aids and optional image renderer.**

   Add mini-map/"you are here" support if graphs exceed the terminal width.
   If native Textual rendering proves insufficient for dense pipelines, render
   Graphviz/SVG/PNG as an optional visual preview through `textual-image` or
   terminal image protocols on capable terminals. Keep the layer board and
   plain-text output as the always-available path.

This keeps the first implementation testable while leaving a credible upgrade
path. `textual-canvas` is still a possible future choice if direct interactive
canvas gestures become necessary, but it should not be the first escalation.

Highest-leverage first-pass additions:

- Board columns from topological layers, so execution order is visible before
  edge details.
- Focusable stage cards, so mouse/keyboard selection can use Textual widgets
  instead of parsing x/y positions in a rendered text canvas.
- Explicit `JOIN`, `FAN-OUT`, `PROVIDER`, `OUTPUT`, `WARN`, `DIRTY`, `RUN`,
  `DONE`, and `CRITICAL` badges.
- Dependency chips such as `after: analysis + clarify` on selected or joined
  cards.
- Compact and linear fallbacks from the start, so Dashboard reuse, narrow cmux
  panes, and screen-reader-friendly views do not become special cases later.

### Target Layout

```text
SwarmDaddy   [1 Dashboard] [2 Runs] [3 Pipelines] [4 Presets] [5 Settings]   ^p Commands
preset=balanced  pipeline=default  draft=none  validation=OK

+--------------------------+ +----------------------------------------------------------+ +--------------------------+
| Pipelines                | | Execution Board: default                                 | | Stage Inspector          |
| implement                | | [1 Research]   [2 Parallel]   [3 Build]   [4 Verify]     | | review                   |
|   default [stock]        | | ┌───────────┐ ┌───────────┐ ┌──────────┐ ┌────────────┐ | | kind: agents             |
|   lightweight [stock]    | | │ research  │ │ analysis  │ │ writer   │ │ spec-review│ | | deps: spec-review,       |
|   ultra-plan [stock]     | | │           │ │ clarify   │ │ JOIN     │ │ provider   │ | |       provider-review    |
| review                   | | └───────────┘ └───────────┘ └──────────┘ └────────────┘ | | route: preset/hard       |
|   review [stock]         | |                                      [5 Outputs]          | |                          |
| design                   | |                                      ┌────────────┐       | | actions                  |
|   design [stock]         | |                                      │ review JOIN│       | | enter edit/fork          |
| custom                   | |                                      │ docs OUTPUT│       | | r route  o provider      |
+--------------------------+ +----------------------------------------------------------+ +--------------------------+

+--------------------------------------------------------------------------------------------------------------------+
| Validation / Budget / Provider Readiness                                                                           |
| OK structural validation  budget agents=8 cost=$1.4400 wall=1920s  provider doctor required for swarm-review       |
+--------------------------------------------------------------------------------------------------------------------+
```

The visual board pane must be the largest object on the screen. The stage list
is not the center of gravity anymore.

### Required Graph Semantics

The graph must make these concepts visible:

- **Stage order:** left-to-right or top-to-bottom by topological layer.
- **Dependencies:** relationship from each dependency to the dependent stage,
  visible through layer order, selected-card chips, and inspector details; full
  edge drawing is optional.
- **Parallel branches:** multiple stages in the same layer should read as
  parallel work.
- **Fan-out stages:** show branch count and variation mode inside the node.
  Example: `exploration x3 prompt_variants`.
- **Merge stages:** show synthesize merge agent inside the fan-out node.
  Example: `merge: agent-analysis-judge`.
- **Provider stages:** visually distinguish evidence/provider work from normal
  agent work by badge/shape first and color second.
  Example: `provider-review (swarm-review, best-effort)`.
- **Join points:** when a stage has multiple dependencies, `JOIN`/`AND` badges
  and dependency chips must make the wait obvious.
- **Terminal outputs:** final review/docs stages should be visually findable.
- **Draft/validation status:** invalid stages or graph errors should be marked
  directly on the card when possible.
- **Selection:** selected stage card and inspector must stay synchronized.
- **Live run status:** the same renderer should be able to add `running`,
  `done`, `failed`, and `queued` badges when Dashboard shows active runs.
- **Route diff status:** draft route overrides should tint or mark affected
  nodes so edits feel concrete.
- **Critical path:** when budget/wall-clock estimates are available, the board
  should be able to emphasize the longest estimated path through the DAG.
- **Swimlanes:** when width allows, stage kinds should align into stable lanes
  so provider/evidence work is structurally visible even without color.

### Native Layer-Board Component Plan

The default Pipelines graph should be a custom Textual component composed from
normal Textual widgets. It should feel like a workbench, not an image embedded
in a terminal.

#### Component Structure

Keep topology and overlay computation pure in `py/swarm_do/tui/state.py`.
Textual widgets should receive a prepared model and render it; they should not
recompute pipeline semantics.

Recommended classes:

```python
class PipelineLayerBoard(Widget):
    """Focusable board that owns keyboard movement and board refresh."""

class PipelineLayerColumn(Vertical):
    """One topological layer rendered as a column."""

class PipelineStageCard(Static):
    """Focusable/clickable stage card with badges and selection state."""

class PipelineJoinBadge(Static):
    """Small semantic marker for multi-dependency stages."""
```

`PipelineLayerBoard` responsibilities:

- Accept `PipelineGraphModel` and `PipelineGraphOverlay`.
- Decide render mode from available size:
  - board mode for wide enough panes;
  - compact layer-list mode for medium panes;
  - linear topological fallback for narrow panes.
- Compose or refresh one `PipelineLayerColumn` per layer.
- Own graph-level bindings:
  - `left/right`: move to previous/next layer or connected dependency/dependent.
  - `up/down`: move within the current layer.
  - `home/end`: first/last stage in topological order.
  - `enter`: launch the existing edit/fork flow for the selected stage.
  - `y`: copy the plain-text fallback graph.
  - `t`: focus the inspector/details pane.
- Emit stage selection through the existing `PipelinesScreen.select_graph_stage`
  flow rather than owning app state.
- Keep the board scrollable horizontally and vertically when it exceeds the
  available pane.

`PipelineLayerColumn` responsibilities:

- Render a short layer header: `1 Research`, `2 Parallel prep`, `3 Build`, or a
  neutral `Layer N` when no semantic label is available.
- Render all cards in the layer in deterministic order from the graph model.
- Group or visually separate provider/evidence cards when there is room, but do
  not require swimlanes for comprehension.
- Preserve stable spacing so focus rings and status badges do not move other
  columns around.

`PipelineStageCard` responsibilities:

- Render the stage title.
- Render one short subtitle, selected from:
  - first agent role;
  - fan-out role/count/variant;
  - provider type and tolerance;
  - terminal artifact role.
- Render badges:
  - `JOIN` when `len(depends_on) > 1`;
  - `FAN xN` when `fan_out_count` exists;
  - `PROVIDER` for provider/evidence work;
  - `OUTPUT` for terminal answer/docs;
  - `WARN` or `ERROR` when warnings are present;
  - `DIRTY` for draft changes;
  - `CRITICAL` for critical-path overlays;
  - live status badges such as `QUEUED`, `RUN`, `DONE`, `FAILED`.
- In selected state, render the dependency chip:
  `after: analysis + clarify`.
- In selected state, render outgoing summary when useful:
  `next: spec-review, provider-review`.
- On click or keyboard activation, call back to the screen with `stage_id`.

`PipelineJoinBadge` responsibilities:

- Make multi-dependency waits obvious without edge spaghetti.
- Render near the joined card or immediately above it:
  `AND analysis + clarify`.
- Collapse to a simple `JOIN` chip in narrow board mode.

#### Board View Model

Add a small pure view-model layer in `state.py` so tests do not need Textual:

```python
@dataclass(frozen=True)
class PipelineBoardCard:
    stage_id: str
    layer: int
    title: str
    subtitle: str
    badges: tuple[str, ...]
    dependency_label: str | None
    outgoing_label: str | None
    kind: str
    lane: str
    selected: bool
    dirty: bool
    critical: bool
    status: str | None
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class PipelineBoardColumn:
    index: int
    label: str
    cards: tuple[PipelineBoardCard, ...]

@dataclass(frozen=True)
class PipelineBoardModel:
    columns: tuple[PipelineBoardColumn, ...]
    fallback_lines: tuple[str, ...]
    warnings: tuple[str, ...]
```

Add:

- `pipeline_board_model(model, overlay=None, width=None) -> PipelineBoardModel`
- `pipeline_board_mode(width, height, columns) -> Literal["board",
  "compact", "linear"]`
- `pipeline_board_plain_text(board) -> list[str]`

The board model should be derived from `PipelineGraphModel`; it must not become
a second topology model.

#### Render Modes

Board mode:

- Use when the board pane is wide enough to show at least three readable
  columns, initially around `>= 96` columns.
- Columns scroll horizontally if the whole pipeline is wider than the pane.
- Cards have stable width, initially around 22-30 terminal columns.
- Multi-line cards are acceptable; overflowing long stage names should wrap or
  elide after preserving a usable stage id in the inspector.

Compact mode:

- Use when board mode would become cramped, initially around `72-95` columns.
- Render one line per layer:
  `L2  analysis  clarify`
- Preserve badges:
  `writer JOIN after: analysis + clarify`
- Keep selection and inspector synchronization.

Linear mode:

- Use below the compact threshold or when screen-reader/plain output is
  requested.
- Render numbered topological order with `depends_on=...`.
- This can reuse `pipeline_graph_lines(..., linear=True)`.

Dashboard mode:

- Reuse the same board model, but render compact-only by default.
- Show only active pipeline shape and live status; do not expose editing
  affordances on Dashboard.

#### Connector Policy

V1 should not try to draw every edge. The key UX signal is:

- layer order;
- parallel cards in the same layer;
- explicit join badges;
- selected-card dependency/outgoing chips;
- inspector dependency details.

Optional lightweight connector hints may be added later:

- short right-arrow glyph between adjacent columns;
- connector only for the selected card's incoming/outgoing edges;
- connector only for critical path.

Avoid full-board crossing edge lines in V1. That is the path that made the v3
workbench hard to read.

#### Textual Validity

This approach is valid for the current Textual dependency range because it uses
core primitives already present in the app:

- `Widget`/`Static` for board and cards;
- `Horizontal`/`Vertical` containers for columns and layout;
- focusable widgets and `Binding` for keyboard navigation;
- `on_click`/message callbacks for mouse selection;
- TCSS classes for selected/dirty/provider/warning/live styling;
- existing `Reactive[str | None] selected_stage_id` ownership on
  `PipelinesScreen`.

It avoids relying on optional terminal image protocols, browser rendering,
Graphviz binaries, or canvas packages.

#### Styling Rules

- Color is reinforcement, not the primary signal.
- Every semantic state must have a text/glyph badge.
- Card borders/focus styles must not change dimensions when selection changes.
- Use short labels inside cards; move long YAML/provider details to the
  inspector.
- Provider/evidence cards should have a distinct class and badge even in
  monochrome.
- Terminal/output stages should be findable through an `OUTPUT` badge and
  stable placement near the final layer.

Initial TCSS classes:

- `.stage-card`
- `.stage-card--selected`
- `.stage-card--agents`
- `.stage-card--provider`
- `.stage-card--fanout`
- `.stage-card--terminal`
- `.stage-card--dirty`
- `.stage-card--critical`
- `.stage-card--warning`
- `.stage-card--running`
- `.stage-card--failed`
- `.join-badge`
- `.layer-column`
- `.layer-column-title`

#### Interaction Contract

The board does not edit directly. It selects, explains, and launches explicit
workflows.

- Selection updates the inspector and validation rail.
- `Enter`/`f` opens fork/edit using the existing modal flow.
- `r`, `b`, `n`, `o`, `m`, `delete`, and route reset continue to operate on the
  selected stage.
- `y` copies a plain-text representation, not a widget dump.
- `?` explains board navigation and badge meanings.
- Pipeline changes preserve selection only when the stage id still exists.

#### Testing Strategy

Pure tests:

- Board model columns match graph model layers for default, design, review, and
  competitive pipelines.
- Join cards include dependency labels.
- Provider/fan-out/terminal stages emit the expected badges.
- Overlay states produce `DIRTY`, live status, and critical badges without
  changing topology.
- Compact and linear modes are selected at the expected width thresholds.

Textual/manual tests:

- Wide terminal: default pipeline shows five readable columns and selected card
  drives inspector.
- Narrow terminal: board falls back to compact or linear mode without
  unreadable wrapping.
- cmux pane: horizontal scroll works when columns exceed width.
- Keyboard-only walkthrough:
  focus board, move through layers, edit/fork selected stage, validate,
  discard.
- Monochrome/low-color check: badges still explain kind/status.

### Plain Text Fallback Rendering Strategy

Keep a deterministic dependency-free renderer as fallback and export format.

The plain-text renderer remains important, but it is no longer the primary
Pipelines workbench. It should serve:

- copy/yank output;
- Dashboard compact fallback when the board cannot fit;
- narrow/screen-reader-friendly linear mode;
- non-Textual tests of topology and overlay semantics;
- emergency fallback if widget rendering fails.

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

Fallback text layout algorithm:

1. Build layer columns from `topological_layers()`.
2. Assign each node a semantic lane and shape.
3. Apply barycentric reordering within layers to reduce edge crossings.
4. Route orthogonal box-drawing edges with explicit join markers for fallback
   wide text output.
5. Prefer wide layered mode when it fits.
6. Use `compact=True` for Dashboard and small panels.
7. Use numbered linear topological mode for very narrow panes and screen
   readers.

Fallback renderer requirements:

- Render a compact DAG map that fits the current terminal width where possible.
- Use box-drawing edges and joins in fallback wide mode.
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

Acceptable fallback visual forms:

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

### Post-V1 Board Interaction

After the first board lands, improve interaction only where it helps the
operator answer workflow questions faster.

Candidate additions:

- selected-edge hints for the selected card's incoming and outgoing
  dependencies;
- a small "you are here" indicator when horizontal scrolling hides columns;
- optional provider/evidence lane grouping when wide terminals have room;
- command palette actions that operate on the selected stage;
- richer live status badges when active-run events map cleanly to stage ids.

The board must never become the edit form itself. Route/provider edits, fork,
save, discard, and raw YAML stay modal or secondary-detail workflows.

If the native board proves insufficient for dense pipelines, first evaluate
Graphviz/SVG/PNG as an optional preview/export path through `textual-image` on
capable terminals while keeping the board and text fallback available. Evaluate
`textual-canvas` only if the product needs direct canvas interaction that
normal Textual widgets cannot provide.

### Workbench Panels

Left panel: Pipeline Gallery

- Group by intent.
- Show active pipeline and stock/user/custom origin.
- Keep labels short. Move long descriptions to preview/inspector.
- Add a filter/search later if the list grows.

Center panel: Execution Board

- Default focus for Pipelines.
- Largest panel.
- Shows badge legend only when there is space; otherwise use help/command
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
| Active Pipeline                                                                                 |
| L1 research  ->  L2 analysis | clarify  ->  L3 writer JOIN  ->  L4 spec | provider  -> review   |
+------------------------------------------------------------------------------------------------+

+------------------------------------------------------------------------------------------------+
| In-Flight Runs                                                                                 |
| issue  role  backend  model  effort  pid  status                                               |
+------------------------------------------------------------------------------------------------+
```

Implementation notes:

- Reuse `pipeline_graph_model()` and `pipeline_board_model()` from the
  Pipelines workbench.
- Dashboard board is read-only and always rendered in compact/fallback mode.
- Add a small `RichLog` event strip for the last N run/checkpoint/observation
  events. It should be filterable by selected stage once board selection exists.
- Use live-status board badges when active-run state can be mapped to stage ids.
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

### Phase 3: Layer-Board View Model And Text Fallback

Goal: prepare board-ready data without touching Textual layout yet, and keep a
plain-text fallback for copy, narrow panes, and tests.

Tasks:

- Add `PipelineBoardCard`, `PipelineBoardColumn`, and `PipelineBoardModel` to
  `py/swarm_do/tui/state.py`.
- Implement `pipeline_board_model(model, overlay=None, width=None)`.
- Derive columns directly from `PipelineGraphModel.layers`.
- Derive card badges from `PipelineGraphNode` and `PipelineGraphOverlay`:
  - `JOIN`
  - `FAN xN`
  - `PROVIDER`
  - `OUTPUT`
  - `WARN` / `ERROR`
  - `DIRTY`
  - `CRITICAL`
  - live status
- Add selected-card dependency and outgoing labels:
  - `after: analysis + clarify`
  - `next: spec-review, provider-review`
- Add deterministic layer labels:
  - semantic labels when obvious, such as `Research`, `Parallel prep`,
    `Build`, `Verification`, `Outputs`;
  - `Layer N` fallback otherwise.
- Implement `pipeline_board_mode(width, height, columns)` with initial
  thresholds:
  - board mode at roughly `>= 96` columns;
  - compact mode at roughly `72-95` columns;
  - linear mode below that.
- Keep or implement `pipeline_graph_lines(..., compact=True, linear=True)` as
  the plain-text fallback. It does not need to be the primary workbench
  renderer.
- Implement `pipeline_board_plain_text(board)` for copy/yank and tests.
- Replace old preview-only `graph_lines()` usage with either the board fallback
  text or the existing graph fallback where appropriate.

Tests:

- Unit tests on `pipeline_board_model()` for default, design, review, and
  competitive pipelines.
- Tests should assert semantics, not TCSS or exact visual spacing:
  - layers are preserved
  - fan-out count appears as a badge
  - provider-review appears as provider/evidence work
  - joins include dependency labels
  - selected stage has dependency/outgoing labels
  - dirty/live/critical overlays produce badges
  - compact and linear thresholds choose the expected mode
  - plain-text fallback preserves complete topological order

### Phase 4: Native Textual Layer-Board Workbench

Goal: replace the hard-to-read graph text pane with a Textual component that
uses columns, cards, badges, and synchronized inspector state.

Tasks:

- Add `PipelineLayerBoard`, `PipelineLayerColumn`, `PipelineStageCard`, and
  `PipelineJoinBadge` classes in `py/swarm_do/tui/app.py` or a new
  `py/swarm_do/tui/widgets.py` module if the app file becomes too large.
- Add TCSS classes for board, columns, cards, selected state, semantic kinds,
  warning/error, dirty, critical, and live status.
- Replace the current `PipelineGraphView(Static)` pane with
  `PipelineLayerBoard`.
- Keep the graph-first workbench layout:
  - left pipeline gallery
  - center layer board
  - right stage inspector
  - bottom validation rail
- Keep stage rows or raw YAML available in a secondary tab/modal, not as the
  default workbench center.
- Continue using `selected_stage_id: Reactive[str | None]` on
  `PipelinesScreen`.
- Synchronize selection:
  - Board, fallback text, inspector, and validation rail render from
    `selected_stage_id`.
  - Selecting a card updates `selected_stage_id`.
  - Selecting a stage row updates `selected_stage_id`.
  - Selecting a pipeline resets or preserves `selected_stage_id` only when the
    stage still exists, then refreshes board, inspector, and validation rail.
- Implement board keyboard movement:
  - `left/right` moves by dependency/dependent when available, otherwise by
    nearest card in adjacent layer;
  - `up/down` moves within the current layer;
  - `home/end` moves to first/last topological stage;
  - `enter` launches the existing edit/fork flow.
- Implement card click selection without parsing rendered text coordinates.
- Implement render-mode fallback inside the board:
  - board mode;
  - compact layer-list mode;
  - linear topological mode.
- Preserve `y`/command-palette copy as plain text.
- Move long raw stage details out of the default inspector.
- Keep edit/fork/route/provider/YAML changes in modals or secondary details;
  board selection can launch those flows but must not become the edit
  surface.
- Add focused empty states:
  - no pipeline selected
  - unreadable pipeline
  - board/model validation error
  - stock pipeline selected, fork required to edit

Tests:

- Textual pilot/smoke test if available in the repo test environment.
- Manual cmux launch on a wide terminal and a narrow terminal.
- Verify cards and badges do not resize the layout during focus/status changes.
- Verify compact/linear fallback is readable in narrow panes.

### Phase 5: Dashboard Orientation

Goal: make Dashboard useful even with no active runs.

Tasks:

- Add active profile summary.
- Add compact active pipeline board or compact layer-list fallback.
- Keep in-flight runs table.
- Add a `RichLog` event strip for the last N checkpoint/observation/run events.
- Add latest checkpoint/observation summary from existing status state as the
  event strip's empty/minimal state.
- Map active-run stage state into board badges when stage ids are available.
- Use empty states instead of huge blank areas.

Tests:

- State tests for active pipeline board summary when active preset exists.
- State tests for compact board/fallback line budget.
- Manual no-runs view.
- Manual one-run view.

### Phase 6: Board Polish And Operator Loops

Goal: make the board workbench feel like an operator console rather than a
static diagram.

Tasks:

- Add command palette actions for screen-specific commands.
- Refine `?` help content after the new board interactions exist.
- Add visible validation severity styling.
- Add a default palette and monochrome fallback that survive SSH, cmux,
  Solarized, and low-contrast themes.
- Add route-diff mode: changed nodes marked green/changed, dirty nodes marked
  amber/dirty, with non-color glyphs as the primary signal.
- Add critical-path overlay using budget/wall-clock estimates once those
  estimates are stable enough at stage level.
- Add optional selected-edge hints only if users still miss dependency
  relationships after the board lands.
- Add mini-map/"you are here" only if real stock/user pipelines exceed the
  board pane width often enough to justify horizontal navigation.
- Polish borders and focus styles in `app.tcss`.
- Update README and any TUI docs.

Tests:

- Manual keyboard-only walkthrough:
  - open TUI
  - go to Pipelines
  - inspect default board
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

Use only if the native board and optional image preview both prove insufficient
after real use.

### Use Graphviz ASCII As The Main Renderer

Why it loses:

- Adds an external binary/build dependency.
- ASCII output availability depends on Graphviz build features.
- Styling and selection synchronization would be awkward.

### Use Graphviz PNG / `textual-image` As V1

Why it loses:

- Excellent escape hatch, but the first workbench still needs to work in plain
  SSH/cmux panes.
- Image output makes selection, diff overlays, and copy-as-text harder unless a
  native board/text renderer already exists.
- It shifts testing toward visual snapshots before the semantic model is
  proven.

Use later as a capability upgrade when terminals support kitty/sixel/iTerm
images or when dense pipelines outgrow the native board.

### Continue Edge-Dense Box-Drawing As The Primary Graph

Why it loses:

- The v3 screenshot shows that the operator has to parse glyphs before seeing
  the workflow.
- Joins and parallelism are technically represented but not visually obvious.
- Click hit detection depends on rendered string positions instead of stable
  widgets.
- Adding more edge detail would likely increase noise faster than
  comprehension.

Keep plain-text graph output for copy, compact, linear, and emergency fallback.
Do not make it the default Pipelines workbench.

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

Keep it parked unless pipelines become so dense that the native board plus
selected-edge hints cannot stay readable.

### Put Editing Directly In The Graph

Why it loses:

- It overloads the comprehension surface with form state.
- It makes keyboard interaction ambiguous: selection, navigation, and editing
  fight for the same keys.
- It creates more failure modes for stock-vs-user fork safety.

Board selection may launch edit/fork modals, but editing itself stays explicit.

### Keep The Stage List As The Primary Workbench

Why it loses:

- It preserves the current mental-model problem.
- Lists hide dependency joins and parallel work.
- The operator still has to reconstruct the swarm flow manually.

## Risks And Mitigations

Risk: board columns become too wide for small panes.

Mitigation: set explicit board/compact/linear thresholds, make the center board
scroll horizontally, keep selected-card dependency chips, and preserve the
linear fallback.

Risk: dependency relationships become too implicit without full edge lines.

Mitigation: show `JOIN`/`AND` badges, selected-card `after:` and `next:` chips,
and inspector dependency details. Add selected-edge hints only if user testing
shows the badges are insufficient.

Risk: board and stage selection drift out of sync.

Mitigation: store one `Reactive[str | None] selected_stage_id` in
`PipelinesScreen`; every panel renders from that state.

Risk: board redraws become noticeable as focus changes or run events stream in.

Mitigation: keep the graph model immutable, separate fast-changing overlays
from topology, keep the board view model pure, and memoize expensive topology
mapping by pipeline/revision/overlay/width.

Risk: color-heavy styling fails over SSH, cmux, monochrome, or colorblind use.

Mitigation: make card badges, labels, and glyphs the primary signal; treat color
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
- Pipelines opens to a board-first graph view.
- The default pipeline board visibly shows:
  - research splitting to analysis and clarify
  - writer waiting for both
  - spec-review and provider-review running after writer
  - review waiting for both spec-review and provider-review
  - docs following spec-review
- Fan-out pipelines visibly show branch count and merge agent.
- Provider stages are visually distinct from normal agent stages by badge,
  placement/class, and color enhancement.
- Selecting any stage card updates the inspector.
- Validation/budget/provider readiness is visible without opening a modal.
- Narrow terminals can switch to a numbered linear topological view.
- The Dashboard is informative even when there are no in-flight runs.
- The Dashboard includes a compact board/fallback text view and a small
  recent-event strip.
- Global navigation no longer collides with Doctor/Diff/Set actions.
- Editing/forking is launched from board selection when useful but remains
  modal.

## Implementation Entry Point

Start with **Phase 1: Navigation And Chrome**, then implement **Phase 2: Pure
Pipeline Graph Model**, then **Phase 3: Layer-Board View Model And Text
Fallback** before touching the Pipelines layout.

Do not begin a canvas or external graph dependency spike until the dependency-
free `pipeline_graph_model()`, `pipeline_board_model()`, native
`PipelineLayerBoard`, and plain-text fallback path have been tried against the
stock pipelines in wide, compact, narrow, and linear modes.
