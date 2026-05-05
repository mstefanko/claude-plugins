# SwarmDaddy Full-Pipeline Smoke Plan

Status: ready for prepare-gate smoke
Date: 2026-05-05

A trivial change set whose only job is to dogfood the full SwarmDaddy
fanout pipeline end-to-end. The plan deliberately stays small: prepare
does the work of validating, decomposing, and lining the run up; the
controller does the work of enforcing that every planned stage is
adopted before a phase is marked complete. We just need a phase that
naturally splits into a few work units so per-unit writer fanout
actually fires.

Run the explicit two-step flow so both slash commands are exercised:

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

## What we are relying on prepare to do

Don't pre-compute these by hand — the smoke is partly a test of
`/swarmdaddy:prepare`. After dry-run, prepare should report:

- `status_label: READY_FOR_ACCEPTANCE`
- `phase_count: 2`
- `work_unit_count: 4` (Phase 1 splits 3 ways across distinct decomposer
  categories; Phase 2 stays one unit)
- `lint_findings: []`

If prepare returns anything else, that's a finding — record it and stop
before accepting.

## What we are relying on the controller to do

The controller (`stage_controller.py:151`) already requires every
planned stage to reach `adopted` before a phase is marked
`complete`. The default preset plans `writer` (per unit),
`provider-review`, `spec-review`, `review`, and `docs`, so a phase that
ends in `complete` is by definition a phase where all of those ran.
The smoke does **not** need to grep for individual stage results — a
single "both phases complete" assertion covers it.

If a phase ends in `partial_success` or `failed`, that *is* the wiring
regression. Pull the run's stage ledger and dispatcher transcript and
file a bug; do not paper over it with manual checks here.

## Success signals (record per run)

After `/swarmdaddy:do` exits:

1. `bin/swarm phases list <run-id>` shows `status=complete` for both
   phases. (This is the load-bearing assertion — it implies every
   default-preset stage was adopted.)
2. Phase 1 exposed per-unit fanout: `bin/swarm stages list <run-id> 1`
   shows three `writer:fanout-N` stages, each `status=adopted` with a
   distinct `work_unit_id`.
3. No writer launch prompt contains unsubstituted `${MAX_TOOL_CALLS}`,
   `${MAX_OUTPUT_BYTES}`, `${MAX_HANDOFFS}`, or `${WORK_UNIT_ID}`
   placeholders. Verify with
   `grep -rn '\${MAX_\|\${WORK_UNIT_ID}' <data-dir>/runs/<run-id>/phases/`.

After a successful run, delete the smoke artifacts:
`rm -f docs/samples/smoke-alpha.md tests/fixtures/smoke-bravo.txt schemas/smoke-charlie.json docs/samples/README.md`.

### Phase 1: Add Three Smoke Artifacts (complexity: moderate, kind: test)

Goal: drop three independent one-line files into three distinct
decomposer categories so Phase 1 naturally decomposes into three work
units. The actual content does not matter; only the per-unit shape
does.

#### Files to create

| File | Action |
| --- | --- |
| `docs/samples/smoke-alpha.md` | CREATE |
| `tests/fixtures/smoke-bravo.txt` | CREATE |
| `schemas/smoke-charlie.json` | CREATE |

#### Implementation tasks

1. Create `docs/samples/smoke-alpha.md` containing a `# Smoke alpha` heading and one short sentence describing it as a smoke artifact.
2. Create `tests/fixtures/smoke-bravo.txt` containing exactly the line `smoke bravo fixture` and a trailing newline.
3. Create `schemas/smoke-charlie.json` containing exactly the JSON object `{}` and a trailing newline.

The three files must not import, link, or reference each other.

#### Acceptance criteria

- All three files exist at the listed paths.
- `docs/samples/smoke-alpha.md` is between 2 and 4 lines and starts with `# Smoke alpha`.
- `tests/fixtures/smoke-bravo.txt` contains exactly one non-empty line: `smoke bravo fixture`.
- `schemas/smoke-charlie.json` parses as JSON and equals `{}`.

#### Verification commands

```bash
ls docs/samples/smoke-alpha.md tests/fixtures/smoke-bravo.txt schemas/smoke-charlie.json
head -n 1 docs/samples/smoke-alpha.md
cat tests/fixtures/smoke-bravo.txt
python3 -c "import json; assert json.load(open('schemas/smoke-charlie.json')) == {}; print('ok')"
```

#### Expected results

- All three files exist.
- `docs/samples/smoke-alpha.md` first line is `# Smoke alpha`.
- `tests/fixtures/smoke-bravo.txt` prints `smoke bravo fixture`.
- The Python check prints `ok`.

### Phase 2: Index The Smoke Artifacts (complexity: simple, kind: docs)

Goal: add a single index file that lists the three Phase-1 artifacts.
Depends on Phase 1.

#### Files to create

| File | Action |
| --- | --- |
| `docs/samples/README.md` | CREATE |

#### Implementation tasks

1. Create `docs/samples/README.md` with the heading `# Smoke samples` and a markdown list naming the three Phase-1 file paths in alphabetical order.

#### Acceptance criteria

- `docs/samples/README.md` exists.
- It contains the heading `# Smoke samples`.
- It lists the three Phase-1 paths, in alphabetical order.

#### Verification commands

```bash
rg -n "^# Smoke samples$|smoke-alpha\.md|smoke-bravo\.txt|smoke-charlie\.json" docs/samples/README.md
```

#### Expected results

- The search prints the heading line and the three path references in alphabetical order.
