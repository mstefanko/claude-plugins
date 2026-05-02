# Runtime Foundations Implementation Roadmap

Date: 2026-05-02
Status: active implementation roadmap
Source plan: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md`

Use this directory as the implementation entry point. The source plan remains
the long-form evidence and strategy record; these files are the smaller plans
an implementation agent should actually pick up.

## Senior Implementation Read

The recommendation holds, but only if "phase" means bounded delivery scope, not
a request to build every abstraction in the source plan.

The real first risk is not that SwarmDaddy lacks a richer runtime framework.
The real first risk is that state changes, recovery decisions, and traceable
behavior are hard to verify without a live run. That is why the build order
starts with the state seam and trace/eval instead of typed contracts, hooks, or
canonical SQLite.

The second risk is implementation drag. A plan that asks one agent to touch
state ownership, domain contracts, policy, trace, SQL, decisions, events,
hooks, reducers, and migration will either stall or land abstractions before
their call sites exist. The split below keeps each plan small enough to review
and dogfood.

## Build Order

0. Coordinate with `docs/phase-session-live-stage-marker-streaming-plan.md`.
   That plan should land first or be reviewed as an immediate dependency
   because it adds the `stage_controller.py` and `claude_stream.py` consumers
   that Phase 1 must keep out of the direct-writer whitelist.
1. Finish Phase 1 state ownership boundary.
2. Build Phase 4 run trace / replay / eval. It can begin against existing JSON
   readers while Phase 1 finishes, then move behind the seam.
3. Land Phase 3 policy consolidation. This is intentionally before the
   read-only projector in implementation order, even though the projector has
   higher strategic value, because it removes an existing retry-policy fork
   before status, doctor, and TUI surfaces start displaying resolved policy.
4. Land Phase 4.5 read-only SQLite projector after the Phase 1 seam and Phase 4
   behavioral test net exist.
5. Land Phase 2 typed domain contracts incrementally, starting with records
   that status, doctor, recovery, and the projector already expose.
6. Land Phase 7 operator decisions for mutating recovery commands only.
7. Keep Phase 9 canonical SQLite gated until the trigger conditions in the
   source plan are met.

## Active Plans

- `phase-1-state-ownership-boundary-plan.md`
- `phase-4-run-trace-eval-plan.md`
- `phase-3-policy-consolidation-plan.md`
- `phase-4-5-readonly-sqlite-projector-plan.md`
- `phase-2-domain-contracts-plan.md`
- `phase-7-operator-decisions-plan.md`

## Dormant Work

Do not create implementation tickets yet for these:

- Phase 5 event envelope: deferred until at least two new consumers need a
  typed event shape, or Phase 9 starts.
- Phase 6 internal hooks: cut. Revive only with a concrete injection/testing
  need that ordinary function composition cannot satisfy.
- Phase 8 reducers: deferred until a second real merge site exists or provider
  review is already being refactored.
- Phase 9 canonical SQLite: ADR and per-family implementation only after all
  objective trigger conditions are met.

## Cross-Plan Rules

- Preserve existing JSON artifacts and CLI JSON output unless a child plan
  explicitly includes a schema/version compatibility step.
- Add no live Claude/Codex calls to unit tests.
- Treat `run_events.jsonl`, phase-session state, prepared artifacts, stage
  sessions, worktree manifests, and evidence manifests as owned state files.
  New consumers call owner modules; they do not write those files directly.
- Re-pin upstream ADK, smolagents, and LangGraph references at implementation
  time if a child plan uses an upstream pattern.
- Prefer small compatibility shims over file moves when a module is already in
  use. Make the next backend possible; do not perform the backend migration
  early.

## Review Gate

Each child plan should close with:

- changed files;
- tests added and tests run;
- compatibility risks;
- dogfood recipe, when operator-visible behavior changes;
- explicit statement that no dormant phase was accidentally implemented.
