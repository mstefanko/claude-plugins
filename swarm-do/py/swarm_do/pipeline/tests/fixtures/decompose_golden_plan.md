# Decompose Golden Fixture Plan

This plan exercises every parser path in the decomposer.

### Phase 1 — Prepared Run Artifact Contract  *(complexity: moderate, kind: foundation)*

A short narrative paragraph referencing inline `py/swarm_do/pipeline/plan.py`
and a non-path token like `accept/reject` that must NOT be captured.

### Files to create / modify

- `schemas/prepared_plan.schema.json`
- `py/swarm_do/pipeline/prepare.py`
- `py/swarm_do/pipeline/run_state.py`

### Acceptance criteria

- AC1 schema file exists.
- AC2 prepared run shape persisted.
- AC3 idempotent prepare invocation.
- AC4 hash recorded in run.json.

### Verification commands

```
cd swarm-do && python3 -m unittest swarm_do.pipeline.tests.test_prepare_artifact -v
cd swarm-do && python3 -m unittest swarm_do.pipeline.tests.test_run_state -v
```

### Expected results

- Tests exit 0.

### Phase 2: Simple docs touch

### File Targets

- `docs/adr/0001-prepare-gate.md`

- Add ADR.
- Cross-link from README.

### Phase 3 — Narrative-only sweep  *(complexity: hard)*

This phase has NO File Targets section. It references `py/foo/bar.py` and
`py/baz/qux.py` inline along with non-path tokens such as `accept/reject`,
`read/write`, `inspect/decompose`, `and/or`, and `yes/no` that must be
rejected.

- Sweep imports.
- Wire the narrative pipeline.
- Land the inspect/decompose split.

### Phase 4 — Big table phase  *(complexity: moderate, kind: feature)*

### File Targets

| Path | Purpose |
| --- | --- |
| `py/swarm_do/pipeline/a.py` | one |
| `py/swarm_do/pipeline/b.py` | two |
| `py/swarm_do/pipeline/c.py` | three |
| `py/swarm_do/pipeline/d.py` | four |
| `py/swarm_do/pipeline/e.py` | five |
| `py/swarm_do/pipeline/f.py` | six |
| `py/swarm_do/pipeline/g.py` | seven |
| `py/swarm_do/pipeline/h.py` | eight |
| `py/swarm_do/pipeline/i.py` | nine |
| `py/swarm_do/pipeline/j.py` | ten |
| `py/swarm_do/pipeline/k.py` | eleven |

### Acceptance criteria

- AC1 every file gets a doctring.
- AC2 mypy clean.

### Verification commands

```
rg -n "TODO" docs/swarmdaddy-prepare-gate-plan.md || true
python3 -m mypy py/swarm_do/pipeline
```
