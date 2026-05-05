# SwarmDaddy Full-Pipeline Smoke Plan

Status: ready for prepare-gate smoke
Date: 2026-05-05

This is a small real change set for dogfooding the full SwarmDaddy
implementation pipeline after the fanout foundation fixes. It should be run
with the explicit two-step flow so both slash commands are exercised:

```bash
/swarmdaddy:prepare docs/swarmdaddy-full-pipeline-smoke-plan-2026-05-05.md
/swarmdaddy:prepare --accept <run-id>
/swarmdaddy:do --prepared <run-id> --phase-sessions fanout
```

CLI equivalent:

```bash
bin/swarm prepare docs/swarmdaddy-full-pipeline-smoke-plan-2026-05-05.md
bin/swarm prepare --accept <run-id>
bin/swarm do --prepared <run-id> --phase-sessions fanout
```

Expected prepare shape:

- Two phases.
- Phase 1 requires decomposition and should produce at least two work units.
- Phase 2 is simple and follows Phase 1 through the sequential phase map.
- Total prepared work is small enough for a smoke run while still touching the
  writer, spec-review, docs, review, result, handoff, adoption, and merge paths.

Success signal for the live run:

- Prepare reaches `READY_FOR_ACCEPTANCE`.
- The accepted run completes both phases.
- Phase 1 has multiple adopted work units.
- Stage ledger, phase result, and merge status agree.
- No writer launch prompt contains unsubstituted `${MAX_TOOL_CALLS}`,
  `${MAX_OUTPUT_BYTES}`, `${MAX_HANDOFFS}`, or `${WORK_UNIT_ID}` placeholders.

### Phase 1: Add A Checked Smoke Fixture (complexity: moderate, kind: test)

Goal: add a durable, repo-local fixture and focused regression test that keeps
the prepare/decompose smoke contract executable without live providers.

### Files to create / modify

| File | Action |
| --- | --- |
| `tests/fixtures/swarmdaddy-pipeline-smoke-plan.md` | CREATE |
| `py/swarm_do/pipeline/tests/test_smoke_plan_fixture.py` | CREATE |
| `docs/eval-recipes.md` | UPDATE |

### Implementation tasks

1. Create `tests/fixtures/swarmdaddy-pipeline-smoke-plan.md` as a minimal
   two-phase implementation plan fixture. The fixture must include canonical
   phase headings, per-phase file targets, acceptance criteria, and validation
   command sections.
2. Add `py/swarm_do/pipeline/tests/test_smoke_plan_fixture.py`. The test must
   load the fixture through `parse_plan`, `lint_plan`, `decompose_plan_phase`,
   and `prepare_plan_run` in dry-run mode with no artifact writes.
3. Update `docs/eval-recipes.md` with a short full-pipeline smoke recipe that
   names the fixture, the expected prepare shape, and the live-run success
   signals operators should record.

### Acceptance criteria

- The fixture parses as exactly two phases with stable ids `1` and `2`.
- `lint_plan` reports no blocking findings for the fixture.
- `decompose_plan_phase` reports at least two work units for fixture Phase 1
  and exactly one work unit for fixture Phase 2.
- `prepare_plan_run(..., dry_run=True, write=False)` reports
  `READY_FOR_ACCEPTANCE`, `phase_count == 2`, and `work_unit_count >= 3`.
- `docs/eval-recipes.md` has a "Full Pipeline Smoke" section that lists the
  fixture path and the success signals above.

### Verification commands

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_smoke_plan_fixture
bin/swarm prepare tests/fixtures/swarmdaddy-pipeline-smoke-plan.md --dry-run --json
rg -n "Full Pipeline Smoke|swarmdaddy-pipeline-smoke-plan" docs/eval-recipes.md
```

### Expected results

- The unittest command exits 0.
- The dry-run prepare JSON reports `status_label` as `READY_FOR_ACCEPTANCE`.
- The recipe search prints the new section and fixture path.

### Phase 2: Document The Operator Smoke Run (complexity: simple, kind: docs)

Goal: document the exact manual runbook for executing this plan through
`/swarmdaddy:prepare` and `/swarmdaddy:do` after Phase 1 lands. This phase
depends on Phase 1 because it references the fixture and test added there.

### Files to create / modify

| File | Action |
| --- | --- |
| `README.md` | UPDATE |
| `docs/testing-strategy.md` | UPDATE |

### Implementation tasks

1. Add a short "Full Pipeline Smoke" subsection to `README.md` near the
   two-step prepare gate documentation. Include the slash-command sequence,
   the CLI equivalent, and the expected prepare/run shape.
2. Update `docs/testing-strategy.md` to classify this smoke as a manual
   live-provider dogfood check, distinct from unit, TUI, and shell tests.
3. Include a compact checklist for recording the run id, phase count, work-unit
   count, ledger/result agreement, merge status, and placeholder scan result.

### Acceptance criteria

- `README.md` names this plan file and shows the two-step
  `/swarmdaddy:prepare` then `/swarmdaddy:do --prepared` flow.
- `docs/testing-strategy.md` explains when to run the smoke and why it is not a
  normal local unit-test gate.
- The operator checklist includes run id, prepared status, phase count,
  work-unit count, ledger/result agreement, merge status, and placeholder scan.
- Phase 1's smoke fixture test still passes after the docs updates.

### Verification commands

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_smoke_plan_fixture
rg -n "Full Pipeline Smoke|swarmdaddy-full-pipeline-smoke-plan-2026-05-05|--phase-sessions fanout" README.md docs/testing-strategy.md
```

### Expected results

- The unittest command exits 0.
- The search command prints the README and testing-strategy smoke references.
