# TUI Layer-Board Execution Plan

Date: 2026-04-27

## Purpose

Replace the current edge-dense Pipelines graph workbench with a native Textual
layer-board component that makes pipeline order, parallel work, joins, provider
stages, terminal outputs, and live/draft status readable at a glance.

This plan is the executable successor to the graph workbench portion of
`docs/tui-interface-improvement-plan.md`. The broader TUI shell/navigation work
belongs to that historical plan; this document is only for the remaining
layer-board implementation.

Implementation adjustment, 2026-04-27: after the first board pass, the default
board renders layers top-to-bottom, uses actor/provider names as card titles,
and keeps critical path as a card state/style rather than a loud `CRITICAL`
badge. The pure board model still preserves `PipelineGraphModel.layers` and
plain-text fallbacks still expose dependency stage ids.

Out-of-scope owner: Presets screen, Settings screen, AppChrome, global
`1-5/?/q` bindings, and `get_system_commands` entries are already shipped in
`py/swarm_do/tui/app.py`. No further shell work is planned in this iteration;
this plan owns only the Pipelines workbench center surface and Dashboard's
read-only reuse of the board view-model.

## User Problem

The current graph workbench technically contains the right information, but it
is hard to digest because box-drawing branches and join glyphs compete with the
pipeline itself. Operators need to answer these questions quickly:

- What runs first, next, and last?
- Which stages run in parallel?
- Which stages wait for multiple dependencies?
- Where does provider/evidence work happen?
- Which stage is selected, dirty, blocked, running, done, or failed?
- What can I safely do to the selected stage?

The workbench should behave like an operator console, not like raw graph art.

## Current State

Already available or expected from the current TUI pass:

- `PipelineGraphModel` and `PipelineGraphOverlay` in
  `py/swarm_do/tui/state.py:153-187`.
- `PipelineGraphNode` already exposes `lane`, `subtitle`, `outgoing`, and
  `tolerance` fields (`state.py:155-167`); the board view-model derives card
  fields from these without redefining the node.
- Topological layers from `topological_layers()`.
- Stage metadata: kind, lane, shape, dependencies, outgoing dependents,
  fan-out count, provider type, failure tolerance, warnings, dirty/live/critical
  overlays.
- `PipelinesScreen.selected_stage_id` as the single selection source of truth
  (`app.py:1106-1112` exposes `select_graph_stage(stage_id)`).
- `pipeline_live_stage_statuses()` (`state.py:589`) emits lowercase status
  strings (`"queued"`, `"running"`, `"done"`, `"failed"`, plus
  `event_type.replace("_","-")` for unmapped events). The board normalizes
  these to uppercase badges (see Badge Rules / `STATUS_TO_BADGE`).
- Existing edit/fork/route/provider/module/lens modals.
- Existing `PipelineGraphView(id="pipeline-graph")` mounted in
  `PipelinesScreen.compose()` at `app.py:919-923`. This is the widget the new
  board replaces (see Widget Replacement below).
- Existing plain-text graph output that can be retained as fallback/copy text.

This plan should not discard those pieces. It should reuse them and replace the
hard-to-read center rendering.

## Recommended Approach

Build a custom native Textual layer-board component:

- Columns represent topological layers.
- Stage cards represent stages.
- Multiple cards in one column represent parallel work.
- Join badges/chips represent dependency waits.
- Provider, fan-out, terminal, warning, dirty, critical, and live states are
  visible as badges/classes on cards.
- The selected card drives the inspector, validation rail, and edit actions.
- Compact and linear modes preserve readability in narrow panes.
- Plain-text output remains available for copy/yank, screen-reader-friendly
  fallback, Dashboard compact output, and tests.

Do not use Graphviz, terminal images, or canvas as the default UI for this
implementation. Those remain optional later preview/export paths.

## Non-Goals

- Do not build a full canvas graph editor.
- Do not make cards directly editable.
- Do not render every edge in the board by default.
- Do not add Graphviz, `textual-image`, `textual-canvas`, `networkx`, or
  `py-dagviz` as required dependencies.
- Do not remove the plain-text fallback.
- Do not redesign the whole TUI shell, presets screen, or settings screen in
  this pass.

## Files To Touch

Primary:

- `py/swarm_do/tui/state.py`
- `py/swarm_do/tui/app.py`
- `py/swarm_do/tui/app.tcss`
- `py/swarm_do/tui/tests/test_state.py`

Optional if `app.py` becomes too large:

- `py/swarm_do/tui/widgets.py`
- `py/swarm_do/tui/tests/test_widgets.py` if Textual pilot tests are practical

Docs:

- `tui/README.md`
- `docs/tui-interface-improvement-plan.md` only for cross-reference/status
  notes, not for detailed implementation steps

## Data Model

Keep `PipelineGraphModel` as the topology source of truth. Add a board view
model derived from it. This keeps the transformation unit-testable without
Textual.

Add to `py/swarm_do/tui/state.py`:

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
    mode: str
    fallback_lines: tuple[str, ...]
    warnings: tuple[str, ...]
```

Add helpers:

- `pipeline_board_model(model, overlay=None, width=None, height=None) -> PipelineBoardModel`
- `pipeline_board_mode(width, height, column_count) -> str`
- `pipeline_board_plain_text(board) -> list[str]`

Rules:

- `PipelineBoardModel.columns` must preserve `PipelineGraphModel.layers`.
- `PipelineBoardCard.badges` must be deterministic and short.
- Board labels may be semantic where obvious, otherwise use `Layer N`.
- The board view model must not perform file I/O or import Textual.
- `PipelineBoardCard.outgoing_label` is derived from
  `PipelineGraphNode.outgoing` (`state.py:161`); do not re-derive it from
  edges.
- `PipelineBoardCard.selected` is a snapshot of `overlay.selected_stage_id` at
  model build time. The widget re-renders only the affected cards on selection
  change; selection state changes do not require rebuilding the entire model.
  When the model is rebuilt for any other reason, `selected` reflects the
  current overlay snapshot.

### Lane Assignment Rules

Lane is read from `PipelineGraphNode.lane` (`state.py:155`). The board does not
re-classify stages. Each lane string maps 1:1 to a TCSS card modifier:

| `lane` value | TCSS class             | Notes                                |
|--------------|------------------------|--------------------------------------|
| `agents`     | `.stage-card--agents`  | default for agent-driven stages      |
| `provider`   | `.stage-card--provider`| co-applies with `PROVIDER` badge     |
| `tools`      | `.stage-card--agents`  | treated as agents lane visually      |
| `output`     | `.stage-card--terminal`| co-applies with `OUTPUT` badge       |
| _empty/None_ | `.stage-card--agents`  | safe default                         |

Fan-out and join state come from booleans, not lane:

- `.stage-card--fanout` applies when `fan_out_count is not None`.
- `JOIN`/`AND` badges apply when `len(depends_on) > 1`; they do not change the
  card's lane class.

If `state.py` introduces a new lane string before the board ships, fall back to
`.stage-card--agents` and add a row to this table in the same PR.

## Badge Rules

Initial badges:

- `JOIN`: `len(depends_on) > 1`
- `FAN xN`: `fan_out_count is not None`
- `PROVIDER`: `provider_type is not None`
- `OUTPUT`: terminal/docs/answer-producing stages
- `WARN`: stage warnings exist
- `DIRTY`: stage id is in `overlay.dirty_stage_ids`
- Critical path: stage id is in `overlay.critical_stage_ids`; expose this as
  `PipelineBoardCard.critical` / `.stage-card--critical`, not as a default
  badge.
- `QUEUED`, `RUN`, `DONE`, `FAILED`: derived from `overlay.stage_statuses` via
  `STATUS_TO_BADGE` (below).

### Status Normalization

`overlay.stage_statuses` carries lowercase strings produced by
`pipeline_live_stage_statuses()` (`state.py:589`). The board normalizes them
through a single mapping:

```python
STATUS_TO_BADGE = {
    "queued":  "QUEUED",
    "running": "RUN",
    "done":    "DONE",
    "failed":  "FAILED",
}
```

Mapping rules:

- Known lowercase status → uppercase badge per the table.
- Unknown status ending in `-start` (e.g. `"phase-start"`) → `RUN`.
- Any other unknown status → no status badge (the card still renders; only
  status overlay is dropped). Add the mapping to `STATUS_TO_BADGE` in the same
  PR if a new status appears upstream.
- `PipelineBoardCard.status` stores the raw lowercase string for tests; the
  TCSS modifier is applied from the normalized form (`.stage-card--running`
  for `RUN`, `.stage-card--failed` for `FAILED`).

Selected cards should show:

- `after: dep-a + dep-b` when dependencies exist
- `next: child-a, child-b` when outgoing dependents exist

The inspector remains the place for full route/provider/YAML detail.

## Render Modes

Threshold constants live in `py/swarm_do/tui/state.py` next to
`pipeline_board_mode()`:

```python
BOARD_MIN_WIDTH = 96
COMPACT_MIN_WIDTH = 72
MIN_BOARD_HEIGHT = 14
```

`pipeline_board_mode(width, height, column_count) -> str` returns:

- `"board"` when `width >= BOARD_MIN_WIDTH` and `height >= MIN_BOARD_HEIGHT`.
- `"compact"` when `COMPACT_MIN_WIDTH <= width < BOARD_MIN_WIDTH`, or when
  width qualifies for board but `height < MIN_BOARD_HEIGHT`.
- `"linear"` when `width < COMPACT_MIN_WIDTH`.

Tuning of these constants after real cmux testing is allowed (see Open
Questions); the writer must start with these values.

`board`

- Render one horizontal column per topological layer.
- Cards have stable dimensions.
- Horizontal scroll is acceptable when the pipeline is wider than the pane.

`compact`

- Render one row per layer. `pipeline_board_plain_text()` emits, for the
  default pipeline:
  ```
  L1 research
  L2 analysis  clarify
  L3 writer JOIN after: analysis + clarify
  L4 spec-review  provider-review PROVIDER
  L5 review JOIN
  L6 docs OUTPUT
  ```

`linear`

- Render numbered topological order with dependencies. Sample output:
  ```
  1. research [agents]
  2. analysis [agents] depends_on=research
  3. clarify  [agents] depends_on=research
  4. writer   [agents] depends_on=analysis,clarify  JOIN
  5. spec-review     [agents]   depends_on=writer
  6. provider-review [provider] depends_on=writer  PROVIDER
  7. review   [agents] depends_on=spec-review,provider-review  JOIN
  8. docs     [output] depends_on=review  OUTPUT
  ```

Dashboard always uses `compact` or `linear` mode regardless of available width
(operators expect the dashboard pane to stay summary-shaped). The Dashboard
caller passes a clamped `width` argument when calling
`pipeline_board_model()`.

Plain-text fallback (`pipeline_board_plain_text()`) is text-only and contains
no box-drawing edges. The pre-existing `pipeline_graph_lines()` plain-text
path in `state.py` is retained unchanged for the `y`/copy action and for the
graph view's legacy callers; the board does not regress that output.

## Textual Component Design

Recommended classes:

```python
class PipelineLayerBoard(Widget):
    can_focus = True


class PipelineLayerColumn(Vertical):
    pass


class PipelineStageCard(Static):
    can_focus = True


class PipelineJoinBadge(Static):
    pass
```

`PipelineLayerBoard` owns:

- current `PipelineBoardModel`
- current `PipelineGraphModel`
- current `PipelineGraphOverlay`
- render mode
- board-level keyboard bindings
- callbacks into `PipelinesScreen`

`PipelineLayerColumn` owns:

- layer title
- deterministic card stack
- stable width

`PipelineStageCard` owns:

- stage id
- title/subtitle text
- badges
- selected/dirty/provider/fanout/terminal/status CSS classes
- click-to-select behavior

`PipelineJoinBadge` owns:

- short join marker, usually `AND` or `JOIN`
- collapsed dependency label in board mode only when it fits

## Keyboard And Mouse Behavior

Bindings:

- `g`: focus board
- `left/right`: move to connected dependency/dependent when possible; otherwise
  nearest card in previous/next layer
- `up/down`: move within current layer
- `home/end`: first/last stage in topological order
- `enter`: open existing edit/fork flow for selected stage
- `y`: copy plain-text board/graph fallback
- `t`: focus inspector/details

Mouse:

- Clicking a card selects that stage.
- Do not parse rendered text coordinates for hit detection.

Selection:

- `PipelinesScreen.selected_stage_id` remains the single source of truth.
- Pipeline changes preserve selection only if the same stage id still exists.
- Every panel re-renders from the selected stage id.

### Resize, Focus, and Modal Behavior

- On `on_resize`, the board calls `pipeline_board_mode(width, height,
  column_count)` and rebuilds only when the resulting mode differs from the
  current mode. Same-mode resizes use Textual's existing reflow without a
  model rebuild.
- Selection (`selected_stage_id`) is preserved across resizes.
- If the board had focus before the resize, focus is restored to the board
  after the rebuild; if a card was focused, focus is restored to that card
  when its id still exists, otherwise to the board container.
- While any modal screen is mounted (edit/fork/route/provider/help), the board
  does not rebuild on overlay or status-update events. Pending updates are
  coalesced and applied on `on_screen_resume`.
- The board does not own any persisted state. Mode is computed from current
  pane size on every render; selection lives only on
  `PipelinesScreen.selected_stage_id` for the lifetime of the session.

### Empty And Error States

The board renders a single-column placeholder, never an empty `Vertical`:

- **No pipeline selected** → one card reading `No pipeline selected.` with
  class `.stage-card--warning`. No badges.
- **Pipeline failed to load** → one card reading
  `Pipeline failed to load: {reason}` with class `.stage-card--failed`. The
  `{reason}` is the exception message, truncated to 120 characters.
- **Empty pipeline (zero stages)** → one card reading `Pipeline has no stages.`
  with class `.stage-card--warning`.

These strings are the source of truth; do not invent alternates.

## TCSS Requirements

Add stable classes:

- `.pipeline-board`
- `.layer-column`
- `.layer-column-title`
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
- `.stage-badge`
- `.join-badge`

Styling constraints:

- Focus and selected states must not change card dimensions.
- Semantic state must be visible without color.
- Card text must fit or wrap without overlapping badges.
- Provider/evidence work must remain visually distinct in monochrome.
- Avoid decorative-heavy styling; this is an operator tool.

## Widget Replacement

`PipelineGraphView(id="pipeline-graph")` (currently mounted at
`app.py:919-923` inside `Vertical(id="pipeline-content")`) is **replaced** by
`PipelineLayerBoard(id="pipeline-graph")` — not wrapped, not run side-by-side.
Sequencing:

1. **Phase 2** mounts `PipelineLayerBoard` under the same id `pipeline-graph`
   so existing TCSS rules `#pipeline-graph` continue to apply. The old
   `PipelineGraphView` class definition stays in `app.py` but is no longer
   instantiated. Selection wiring is verified.
2. **Phase 3** removes the now-unused `PipelineGraphView` class and its
   helpers from `app.py`. Any test that imports `PipelineGraphView` is
   updated. Tests that target plain-text output continue to import
   `pipeline_graph_lines` from `state.py` (kept).

The id `pipeline-graph` is reused to keep cmux pane recordings, focus styles,
and `select_graph_stage()` callers stable. Do not introduce a parallel id.

## Implementation Phases

### Phase 1: Pure Board Model

Goal: produce board-ready columns/cards from the existing graph model.

Tasks:

- Add board dataclasses.
- Implement `pipeline_board_model()`.
- Implement badge derivation.
- Implement dependency and outgoing labels.
- Implement semantic layer labels.
- Implement mode selection thresholds.
- Implement `pipeline_board_plain_text()`.

Tests:

Add to `py/swarm_do/tui/tests/test_state.py` under a new
`class TestPipelineBoardModel(unittest.TestCase)`. Reuse the
`find_pipeline()` / `load_pipeline()` fixture pattern from
`test_pipeline_graph_model_captures_default_dag_semantics` (existing in the
same file) — do not invent new fixtures.

Required test methods:

- `test_default_pipeline_layers_match_topology` — columns count and per-column
  stage ids match `PipelineGraphModel.layers`.
- `test_writer_and_review_have_join_badge` — `JOIN` present on `writer` and
  `review`.
- `test_provider_review_has_provider_badge` — `PROVIDER` present on
  `provider-review`.
- `test_docs_has_output_badge` — `OUTPUT` present on `docs`.
- `test_fan_out_pipeline_shows_fan_count` — `FAN x{N}` appears for fan-out
  stages on a fan-out fixture.
- `test_overlay_dirty_live_critical_add_badges_without_changing_columns` —
  column shape is invariant under overlay changes; only badges differ.
- `test_status_normalization_known_and_unknown` — verifies `STATUS_TO_BADGE`
  mapping plus the `-start → RUN` rule plus drop-on-unknown rule.
- `test_pipeline_board_mode_thresholds` — exact constants
  `BOARD_MIN_WIDTH`/`COMPACT_MIN_WIDTH`/`MIN_BOARD_HEIGHT` produce the
  expected mode at boundary widths/heights.
- `test_pipeline_board_plain_text_compact_and_linear_samples` — golden output
  matches the samples in the Render Modes section for the default pipeline.
- `test_outgoing_label_derived_from_node_outgoing` — `outgoing_label` on a
  card with multiple dependents matches the order in
  `PipelineGraphNode.outgoing`.
- `test_selected_card_carries_after_and_next_chips` — when an overlay sets
  `selected_stage_id="writer"`, the writer card exposes the dependency and
  outgoing chip strings used by the inspector.

### Phase 2: Board Widget Skeleton

Goal: mount `PipelineLayerBoard(id="pipeline-graph")` in place of
`PipelineGraphView` and render columns/cards. Selection callbacks still flow
through the existing `select_graph_stage()` so nothing else has to change yet.

Tasks:

- Add `PipelineLayerBoard`, `PipelineLayerColumn`, `PipelineStageCard`, and
  `PipelineJoinBadge`.
- Add TCSS classes.
- Render columns/cards from `PipelineBoardModel`.
- Render empty/error states using the strings in "Empty And Error States".
- Keep existing inspector and validation rail unchanged.
- Initially keep copy output using the existing `pipeline_graph_lines()`
  fallback text. Board-emitted plain text from
  `pipeline_board_plain_text()` becomes the copy source in Phase 4.
- Replace the `PipelineGraphView(id="pipeline-graph")` mount in
  `PipelinesScreen.compose()` (`app.py:919-923`) with
  `PipelineLayerBoard(id="pipeline-graph")`. Keep the id stable.

Validation:

- Manual wide-terminal launch shows readable columns.
- The board can be focused.
- Cards do not shift when selected styling applies.
- Inspector and validation rail still update on selection.

### Phase 3: Selection And Navigation

Goal: make the board the interactive selection surface and remove the legacy
graph view.

Tasks:

- Wire card clicks to `select_graph_stage(stage_id)`.
- Wire arrow/home/end bindings.
- Preserve `enter`, `f`, `r`, `b`, `n`, `o`, `m`, `delete`, route reset,
  save, discard, undo, and redo behavior against selected stage.
- Ensure inspector updates on selection change.
- Ensure validation rail remains stable.
- Delete the `PipelineGraphView` class and its private helpers from `app.py`
  once selection wiring is verified. Keep `pipeline_graph_lines()` in
  `state.py` (still used by copy and by tests).
- Update or remove any test in `tests/test_widgets.py` (if it exists) that
  imports `PipelineGraphView`. Tests against `pipeline_graph_lines()` stay.

Validation:

- Keyboard-only walkthrough works on default pipeline.
- Mouse click selection works.
- Switching pipelines resets/preserves selection correctly per the rule in
  "Selection".
- `grep -R "PipelineGraphView" py/` returns no matches after Phase 3.

### Phase 4: Responsive Fallbacks

Goal: make the workbench readable in narrow panes and cmux.

Tasks:

- Render compact mode when board mode is cramped.
- Render linear mode below compact threshold.
- Ensure horizontal/vertical scroll works in board mode.
- Ensure `y` copies plain text that includes full dependencies.
- Update help text to explain board, compact, and linear behavior.

Validation:

- Wide pane uses board mode.
- Medium pane uses compact mode.
- Narrow pane uses linear mode.
- Copied text preserves topological order and joins.

### Phase 5: Dashboard Reuse

Goal: reuse board semantics for Dashboard orientation without adding editing
surface there.

Tasks:

- Add compact active pipeline board/fallback output to Dashboard.
- Map live run statuses into badges when stage ids can be resolved.
- Keep Dashboard board read-only.
- Avoid showing edit/fork controls on Dashboard.

Validation:

- Dashboard remains useful with no active runs.
- Dashboard compact output fits the current panel height.

### Phase 6: Polish And Documentation

Goal: make the board feel production-ready.

Tasks:

- Tune TCSS for selected, warning, provider, dirty, critical, and failed states.
- Add monochrome-friendly badge text.
- Add optional selected-edge hints only if dependency chips are insufficient.
- Update `tui/README.md`.
- Add a short cross-reference in `docs/tui-interface-improvement-plan.md`.
- Re-run relevant unit tests and manual TUI checks.

Validation:

- No visual overlap in wide/medium/narrow panes.
- Badge meanings are discoverable through `?`.
- Docs match the implemented controls.

## Acceptance Criteria

- Pipelines opens with the layer board as the primary center surface.
- The default pipeline visibly shows:
  - `research` before `analysis` and `clarify`
  - `analysis` and `clarify` as parallel work
  - `writer` as a join
  - `spec-review` and `provider-review` after `writer`
  - `review` as a join
  - `docs` as an output
- Provider stages are visually distinct without relying only on color.
- Fan-out stages visibly show branch count.
- Dirty, warning, and live states are visible as badges; critical path is
  visible as a quieter card state/style.
- Selecting a card updates the inspector.
- Edit/fork/route/provider actions operate on the selected stage.
- Narrow panes fall back to compact or linear output.
- Plain-text copy preserves full topological order and dependencies.
- No new required graph/image/canvas dependencies are introduced.

## Definition Of Done

The effort is shipped when **all** of the following hold:

- All Phase 1–6 task lists are complete.
- `PYTHONPATH=swarm-do/py python -m pytest swarm-do/py/swarm_do/tui/tests`
  is green, including the new `TestPipelineBoardModel` class and any Pilot
  tests that the env supports.
- The Manual Verification matrix below has been executed and signed off in
  the PR description for the cmux pane (`swarm-do/data/tui/cmux-pane.surface`)
  plus at least 120×40, 96×30, 80×30, and 60×24 terminal sizes.
- `tui/README.md` is regenerated to describe board / compact / linear modes,
  bindings, and badge meanings.
- `docs/tui-interface-improvement-plan.md` carries a one-paragraph
  cross-reference noting that the layer-board work is owned by this plan and
  is complete.
- `grep -R "PipelineGraphView" py/` returns no matches.
- No new runtime dependencies in `pyproject.toml`/`requirements*.txt`.

## Manual Verification

Pilot-driven Textual tests are conditional on the runtime env (`from
textual.pilot import Pilot`); when unavailable, this matrix is the only
visual-verification path. Run each row before requesting review:

| Terminal       | Pipeline              | Expected mode | Spot-check                                           |
|----------------|-----------------------|---------------|------------------------------------------------------|
| 120×40         | default               | board         | 6 columns; `writer` shows JOIN + `after:` chip       |
| 120×40         | fan-out fixture       | board         | fan stage shows `FAN x{N}`                           |
| 96×30          | default               | board         | columns wrap card text without overlapping badges    |
| 95×30          | default               | compact       | rows match Render Modes compact sample               |
| 80×30          | default               | compact       | `provider-review` row carries `PROVIDER`             |
| 72×30          | default               | compact       | last column of Render Modes sample renders          |
| 71×30          | default               | linear        | linear sample matches numbered output                |
| 60×24          | default               | linear        | no horizontal overflow; copy via `y` works           |
| 120×12         | default               | compact       | height fallback engages despite wide terminal        |
| any            | _no pipeline loaded_  | board/compact | empty-state card renders with literal copy           |
| any            | invalid YAML fixture  | board/compact | error-state card shows truncated reason              |
| cmux pane      | default               | as recorded   | `cmux-pane.surface` snapshot matches post-board run  |

For each row, capture: (a) the rendered top-left corner via screenshot or
copy/paste, (b) confirmation that `enter`, `y`, and arrow nav still work.

## Risks And Mitigations

Risk: board mode becomes too wide.

Mitigation: compact and linear thresholds, horizontal scroll, stable card width.

Risk: dependencies are too implicit without edges.

Mitigation: `JOIN`/`AND` badges, selected-card `after:`/`next:` chips,
inspector dependency details, optional selected-edge hints later.

Risk: widget code makes `app.py` too large.

Mitigation: move board widgets to `py/swarm_do/tui/widgets.py` once the shape is
clear.

Risk: status updates cause noisy reflows.

Mitigation: keep card dimensions stable and update badge content in place.

Risk: color themes obscure semantics.

Mitigation: every state has a text badge; color only reinforces meaning.

## Open Questions

- Should `left/right` prefer graph-connected movement or strict adjacent-layer
  movement when both are possible?
- What exact width threshold should trigger compact mode after real cmux
  testing?
- Should semantic layer labels be derived heuristically or stay as neutral
  `Layer N` labels in v1?
- Should selected-edge hints ship in v1 or wait for user feedback after the
  board lands?
