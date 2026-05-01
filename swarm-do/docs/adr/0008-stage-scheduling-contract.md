# ADR 0008: Stage Scheduling Contract

- Status: Accepted
- Date: 2026-05-01
- Deciders: SwarmDaddy maintainers
- Related: ADR 0002 (pipeline invariants), ADR 0006 (prepare gate contract), ADR 0007 (selftest and observability contracts)

## Context

SwarmDaddy has two graph forms: stock pipelines and preset-resolved graphs.
Dispatchers, provider checks, budget previews, and TUI surfaces must agree on
which graph is real. The old prose sometimes told operators to inspect a stock
pipeline with `bin/swarm pipeline show <name>`, which can miss preset routing,
inline snapshots, and lineage drift.

Scheduling also needs one clear rule. Stages already declare `depends_on`
edges, and the deterministic helper can compute topological layers. Implicit
ordering by file order or by role name would make provider-review and
spec-review evidence races easy to reintroduce.

## Decision

`depends_on` is the only stage scheduling contract. A dispatcher may run stages
in the same topological layer concurrently, and it must not start a stage until
all declared dependencies are terminal according to that pipeline's failure
tolerance.

All graph consumers must resolve presets first:

```bash
bin/swarm preset resolve <preset-name> --json
```

The resolved payload is the shared source for:

- stage graph and topological layers;
- concrete role route summaries, including fan-out model branches;
- synthesize merge-agent metadata;
- inline snapshot lineage warnings;
- validation and preflight surfaces.

`bin/swarm pipeline show <name>` remains useful for inspecting raw stock
pipelines, but it is not the dispatcher contract.

Synthesize merge stages are write-path reducers, so every
`merge.strategy == "synthesize"` merge agent must resolve to a Claude backend.
Codex-backed roles are still valid for normal agent stages and model fan-out
branches when the preset routes them explicitly.

## Stock Pipeline Edge Changes

Docs stages that need review evidence now declare those edges explicitly:

- `default`: `docs` depends on `spec-review` and `provider-review`.
- `hybrid-review`: `docs` depends on `spec-review`, `provider-review`, and
  `codex-review`.
- `mco-review-lab`: `docs` depends on `spec-review` and `mco-review`.
- `repair-loop`, `smart-friend`, and `ultra-plan`: `docs` depends on
  `spec-review` and `provider-review`.

## Consequences

- Preset inline snapshots can drift from their source stock pipeline without
  silently changing dispatch; `preset resolve --json` surfaces lineage
  warnings.
- Route validation catches bad normal, fan-out, and merge roles before run
  start.
- Provider-review and docs scheduling no longer depend on operator memory or
  stage ordering conventions.

## Rollback

Rolling back requires reverting the stock-pipeline edge changes and removing
the `preset resolve` dispatcher guidance. Runtime code should keep resolving
presets for validation even if this ADR is superseded.
