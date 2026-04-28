# SwarmDaddy Prepare Gate — Execution Plan

> Companion to [`swarmdaddy-prepare-gate-plan.md`](swarmdaddy-prepare-gate-plan.md).
> That document is the design contract. This document is the runnable, phase-by-phase
> implementation plan with copy-from anchors verified against the current repo.
>
> Each phase is self-contained: it can be executed in a fresh chat context using only
> its own section plus Phase 0 doc-discovery anchors.

---

## Doc Discovery — Anchors and Anti-patterns (informational, not a phase)

These anchors were verified before plan authoring. Every later phase cites them
with the **`copy-from`** convention: copy the named pattern instead of inventing one.

### A. Plan inspect / parser

| Anchor | Location |
|---|---|
| CLI subparser dispatch (`plan` group) | `py/swarm_do/pipeline/cli.py:1095-1115` |
| `cmd_plan(args)` handler | `py/swarm_do/pipeline/cli.py:742-810` |
| Phase heading regex | `py/swarm_do/pipeline/plan.py:26` (`PHASE_HEADING_RE`) |
| `parse_plan(path) -> list[ParsedPhase]` | `py/swarm_do/pipeline/plan.py:85-112` |
| `inspect_phase`, `inspect_plan` | `py/swarm_do/pipeline/plan.py:114-150` |
| `write_inspect_run(...)` | `py/swarm_do/pipeline/plan.py:152-194` |
| `new_run_id()` | `py/swarm_do/pipeline/plan.py:196` |
| `DEFAULT_THRESHOLDS` | `py/swarm_do/pipeline/plan.py:18` |
| `ParsedPhase`, `InspectionReport` dataclasses | `py/swarm_do/pipeline/plan.py:52, 69` |

### B. Run artifact / artifact dir / atomic write

| Anchor | Location |
|---|---|
| `resolve_data_dir()` (`$CLAUDE_PLUGIN_DATA` or `REPO_ROOT/data`) | `py/swarm_do/pipeline/paths.py` |
| Run dir layout: `data_dir/runs/<run_id>/{inspect.v1.json, run.json, checkpoint.v1.json}` | `plan.py:152-194`, `run_state.py:26` |
| `_atomic_json_write(...)` | `py/swarm_do/pipeline/run_state.py:144` |
| `write_checkpoint_from_active(...)` | `py/swarm_do/pipeline/run_state.py:72-123` |
| `append_run_event(data_dir, row)` | `py/swarm_do/pipeline/run_state.py:57-72` |
| Index append pattern (`runs/index.jsonl` row, `status="prepared"`) | `plan.py:152-194` |

### C. agent-decompose + work_units schema

| Anchor | Location |
|---|---|
| Role spec | `role-specs/agent-decompose.md` |
| Generated agent | `agents/agent-decompose.md` (auto-generated; do not hand-edit) |
| Schema | `schemas/work_units.schema.json` (`$id` ends `#v2`) |
| `DecomposeResult`, `decompose_phase`, `decompose_plan_phase` | `py/swarm_do/pipeline/decompose.py:19, 27, 74` |
| `synthesize_work_units` (deterministic single-unit synth for simple phases) | `py/swarm_do/pipeline/decompose.py:94-118` |

### D. decompose.mode preset field

| Anchor | Location |
|---|---|
| Schema enum (`off`/`inspect`/`enforce`) | `schemas/preset.schema.json:71-78` |
| Per-preset `[decompose]` block | `presets/balanced.toml:25` (15 presets total under `presets/*.toml`) |
| CLI override flag | `commands/do.md` (`--decompose=...` argument-hint) |

### E. Role generator + permissions registry (CRITICAL — three places must stay in lockstep)

| Anchor | Location |
|---|---|
| Generator entry | `python3 -m swarm_do.roles gen [--write|--check]` → `py/swarm_do/roles/__main__.py` → `py/swarm_do/roles/cli.py:main` |
| Renderers | `py/swarm_do/roles/render.py: to_agents_md(spec)`, `to_shared_md(spec)` |
| Generation stamp prefix (in generated files) | `<!-- generated from role-specs/<name>.md ... -->` |
| Python role registry | `py/swarm_do/pipeline/permissions.py:15` (`ROLE_NAMES = {...}`) |
| Permissions JSON schema enum | `schemas/permissions.schema.json` (`role` enum) |
| Per-role permission fragments | `permissions/<role>.json` (e.g. `permissions/research.json`, `permissions/writer.json`) |
| `load_fragment(role)` | `py/swarm_do/pipeline/permissions.py:55` |
| Existing read-only role to copy | `role-specs/agent-research.md`, `role-specs/agent-clarify.md`, `permissions/research.json` |
| Existing narrow-write role to copy | `role-specs/agent-writer.md`, `permissions/writer.json` |

> **Drift guard:** the JSON enum currently lacks `clean-review` and `implementation-advisor`
> that exist in `ROLE_NAMES`. Phase 3 MUST add `plan-review`/`plan-normalizer` to all three
> places (Python set, JSON enum, fragment file) and add a permission test that fails when
> they drift.

### F. Telemetry

| Anchor | Location |
|---|---|
| Run events schema (`$id` ends `#v1`) | `schemas/telemetry/run_events.schema.json` |
| Existing `event_type` enum | `checkpoint_written, resume_started, resume_completed, drift_detected, handoff_triggered, handoff_reason, retry_started, retry_exhausted, worktree_merge_conflict` |
| Required fields | `run_id (ULID), timestamp, event_type, schema_ok` |
| Telemetry registry | `py/swarm_do/telemetry/registry.py: PLUGIN_ROOT, Ledger, resolve_telemetry_dir():111, resolve_ledger_path():124` |
| Existing emit API | `run_state.py:57 append_run_event(data_dir, row)` (caller-built dict; no typed helper today) |
| Example construction site | `run_state.py:191-208` (`checkpoint_written` row) |

### G. Command profile system

| Anchor | Location |
|---|---|
| Command files | `commands/{do, design, brainstorm, research, review, setup, configure, quickstart, init-beads, resume}.md` |
| Frontmatter shape | `commands/do.md` — `--- description, argument-hint ---` |
| Skill orchestration | `skills/swarmdaddy/SKILL.md` |
| Profile handlers (CLI) | `cli.py: cmd_brainstorm, cmd_design, cmd_research, cmd_review` |
| Profile tests (copy scaffold) | `py/swarm_do/pipeline/tests/test_command_profiles.py` (1-40, `_dry_run` helper) |

### H. Resume helper

| Anchor | Location |
|---|---|
| `ResumeReport` dataclass | `py/swarm_do/pipeline/resume.py:30` |
| `build_resume_report(bd_epic_id)` | `py/swarm_do/pipeline/resume.py:57-95` |
| `format_resume_report`, `resume_exit_code` | `py/swarm_do/pipeline/resume.py:96-133` |
| Status constants (note: `STATUS_PREPARED` already exists) | `py/swarm_do/pipeline/resume.py` (top) |

### I. Beads optionality

- `plan inspect` already runs without Beads (`--no-write` at `cli.py:1101`).
- All `pipeline/` helpers (`plan.py`, `run_state.py`, `paths.py`, `permissions.py`) are pure stdlib + JSON.
- **Rule for new prepare modules:** no `bd ...` invocations inside `py/swarm_do/pipeline/prepare.py`; surface Beads-aware behavior only in `commands/prepare.md` orchestration.

### J. Files / directories that DO NOT EXIST YET (net-new authorship)

- `py/swarm_do/pipeline/prepare.py`
- `schemas/prepared_plan.schema.json`
- `commands/prepare.md`
- `role-specs/agent-plan-review.md`, `role-specs/agent-plan-normalizer.md`
- `agents/agent-plan-review.md`, `agents/agent-plan-normalizer.md` (generated)
- `roles/agent-plan-review/shared.md`, `roles/agent-plan-normalizer/shared.md` (generated)
- `permissions/plan-review.json`, `permissions/plan-normalizer.json`
- `bin/swarm plan accept <run-id>`, `bin/swarm plan reject <run-id>` subcommands
- A reusable trust-boundary path validator (no `is_relative_to` / `..` rejection helper exists today)

### K. Anti-patterns surfaced by Phase 0 (do not do these)

- Do **not** invent a typed telemetry emit API; reuse `append_run_event` and add a constructor pattern next to it.
- Do **not** introduce a second `agents/agent-decompose.md` invocation inside `/swarmdaddy:do --prepared`. Decompose is owned by prepare.
- Do **not** hand-edit `agents/*.md` files — they are regenerated from `role-specs/`.
- Do **not** add a new role without updating `permissions.py:ROLE_NAMES`, `schemas/permissions.schema.json` enum, AND `permissions/<role>.json` together.
- Do **not** treat paths from validation-command fences, narrative backticks, or the plan file path itself as `allowed_files`. Only entries inside `**File Targets**` / `File Targets` blocks count (Phase 2 grammar).
- Do **not** call `Path.resolve()` ad hoc in new code — Phase 1 will create one canonical helper.

---

### Phase 1 — Prepared Run Artifact Contract  *(complexity: moderate, kind: foundation)*

**Goal:** persist the artifact that connects review → normalize → decompose → acceptance → execution.

#### Files to create / modify

| File | Action |
|---|---|
| `schemas/prepared_plan.schema.json` | CREATE |
| `py/swarm_do/pipeline/prepare.py` | CREATE |
| `py/swarm_do/pipeline/run_state.py` | EXTEND (add accept/reject transitions) |
| `py/swarm_do/pipeline/tests/test_prepare_artifact.py` | CREATE |
| `docs/adr/0006-prepare-gate-contract.md` | CREATE |

#### Implementation tasks (copy-from style)

1. **Schema** — write `schemas/prepared_plan.schema.json` matching the field list in
   the design plan §Phase 1 (lines 132-160 of `swarmdaddy-prepare-gate-plan.md`).
   Required keys (do not invent extras): `schema_version, run_id, repo_root,
   git_base_ref, git_base_sha, source_plan_path, source_plan_sha,
   prepared_plan_path, prepared_plan_sha, inspect_artifact{path,sha},
   phase_map[], review_findings, review_iteration_count (0..3), accepted_fixes,
   work_unit_artifacts, acceptance|null, status, created_at, ready_at,
   accepted_at`.
   - Status enum: `draft, ready_for_acceptance, needs_input, accepted, stale, rejected`.
   - `phase_map[]` item keys: `phase_id, title, complexity, kind, content_sha,
     plan_context_sha, cache_key, requires_decomposition`.
   - `cache_key` composition is documented in design plan lines 91-96; bake it
     into the schema description but compute it in `prepare.py`.

2. **Trust-boundary helper** — create `def canonicalize(path, *, repo_root) -> Path`
   in `prepare.py` that:
   - rejects absolute paths, `..` segments, and out-of-repo results;
   - calls `Path(repo_root).resolve()` and `.is_relative_to(...)`.
   - **copy-from:** there is no existing helper (Phase 0 §J). Pattern the API
     after `paths.py:resolve_data_dir()`.

3. **Artifact persistence** — implement `write_prepared_artifact(...)`,
   `load_prepared_artifact(run_id)`, `mark_ready_for_acceptance(run_id)`,
   `accept_prepared(run_id)`, `reject_prepared(run_id)`.
   - **copy-from:** `run_state.py:144 _atomic_json_write` for atomic writes;
     `plan.py:152-194 write_inspect_run` for the `runs/<run_id>/` layout and
     `runs/index.jsonl` append pattern.

4. **Stale detection** — `def check_stale(artifact) -> StaleReason | None`.
   Whole-plan sha, sidecar sha, git-base sha, per-phase `cache_key`.
   - **copy-from:** drift-key construction in `resume.py:57-95`.

5. **State transitions** — exposed via two new CLI subcommands:
   `bin/swarm plan accept <run-id>` and `bin/swarm plan reject <run-id>`.
   - **copy-from:** subparser registration at `cli.py:1095-1115`; handler
     wiring at `cli.py:742-810` (`cmd_plan`).
   - Accept transitions ONLY `ready_for_acceptance -> accepted` after
     re-running schema + trust-boundary + stale checks. Prepare cannot mark
     accepted directly.

6. **Independence from Beads** — no `bd` import in `prepare.py`. Tests must run
   without an initialized rig (Phase 0 §I).

#### Acceptance criteria (verbatim from design plan §Phase 1, with line refs)

- Prepared artifact can be written, loaded, schema-linted, marked
  `ready_for_acceptance`, accepted via `bin/swarm plan accept`, and rejected
  via `bin/swarm plan reject`.
- Stale detection catches whole-plan, sidecar, git-base, and per-phase
  cache-key drift.
- `review_iteration_count` constrained to `[0, 3]` at the schema level.
- `work_unit_artifacts` keys are valid phase ids that exist in `phase_map`.
- Invalid status, missing hashes, missing prepared files, absolute paths,
  `..` segments, out-of-repo paths, or sidecar hash mismatches all fail closed.
- Prepare cannot transition to `accepted`; only the accept helper can.
- Existing `plan inspect` behavior unchanged.

#### Verification commands

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan inspect docs/swarmdaddy-prepare-gate-plan.md --no-write --json
```

#### Anti-pattern guards

- ❌ Do not skip the trust-boundary helper "for now". Every path field in the
  artifact must round-trip through `canonicalize()`.
- ❌ Do not add a `force_accept` shortcut. Acceptance is the only place state
  flips to `accepted`.
- ❌ Do not import `bd` from `prepare.py`.
- ❌ Do not allow validation-command paths (e.g. `bin/swarm`, `prepared.md`,
  the plan file itself) to leak into `allowed_files`.

---

### Phase 2 — Deterministic Plan Lint + Canonical Phase Writer  *(complexity: moderate, kind: feature)*

**Goal:** non-model layer that detects obvious gaps and converts a source plan
into canonical `### Phase` markdown.

#### Files to create / modify

| File | Action |
|---|---|
| `py/swarm_do/pipeline/plan.py` | EXTEND (lint rules + writer) |
| `py/swarm_do/pipeline/prepare.py` | EXTEND (orchestrate lint→write) |
| `py/swarm_do/pipeline/cli.py` | EXTEND (`plan prepare` subparser) |
| `py/swarm_do/pipeline/tests/test_plan_prepare_lint.py` | CREATE |
| `py/swarm_do/pipeline/tests/test_plan_prepare_write.py` | CREATE |

#### Implementation tasks

1. **Lint rules** in `plan.py`. Each rule returns a structured finding
   `{code, severity, phase_id|None, location, message}`. Required rules
   (verbatim list from design plan §Phase 2, lines 233-241):
   - `no_phase_headings`, `duplicate_phase_ids`, `missing_acceptance_criteria`,
     `missing_validation_commands`, `missing_file_targets_when_referenced`,
     `phase_too_broad` (bullet/file thresholds — extend `DEFAULT_THRESHOLDS`
     at `plan.py:18`), `ambiguous_verbs` ("maybe", "consider", "etc."),
     `untagged_hard_phase`.

2. **Section grammar** — extend `parse_plan` (`plan.py:85-112`) to recognize:
   - canonical headings: `**File Targets**` (source) ↔ `File Targets` (normalized).
   - **only entries inside `File Targets` blocks** count as `allowed_files`.
   - validation-command fences, narrative backticks, expected-results paths
     are reference-only.
   - design plan lines 245-251 enumerate the rules; encode each as a discrete
     parser branch with a unit test.

3. **Canonical phase writer** — `write_canonical_plan(parsed, dest)` emits per
   phase:

   ```
   ### Phase <id>: <title> (complexity: <value>, kind: <value>)

   File Targets
   ...
   Implementation
   ...
   Acceptance Criteria
   ...
   Validation Commands
   ...
   Expected Results
   ...
   Notes
   ...
   ```

   - Source plan is **never** mutated. Output goes to a prepared markdown path
     under the run artifact dir.
   - **copy-from:** `plan.py:152-194 write_inspect_run` for path/run-id wiring.

4. **CLI**: register `plan prepare` subparser in `cli.py:1095-1115`. Args:

   ```
   bin/swarm plan prepare <plan-path> [--dry-run] [--write] [--json]
   ```

   - **copy-from:** the existing `inspect` subparser literally above it.

#### Acceptance criteria

- Unphased plans produce a prepared markdown file with canonical phase headings.
- Already-phased plans round-trip without destructive rewrites.
- Deterministic lint findings are stable in JSON output.
- Source plan never modified by default.
- `File Targets` parsing supports current bold section headings; does NOT infer
  command paths (`bin/swarm`, the plan file itself, `prepared.md`, validation
  command paths) as `allowed_files`.
- Tests cover path containment, `..` rejection, absolute-path rejection, and
  the split between file targets, context references, and validation commands.

#### Verification commands

```bash
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_plan*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
```

#### Anti-pattern guards

- ❌ Do not auto-fix anything beyond mechanical normalization. Inferring
  acceptance criteria, requirements, or APIs is reserved for Phase 3 model agents.
- ❌ Do not let the writer silently drop unknown sections — preserve them under
  `Notes`.
- ❌ Do not modify the source plan file at any code path.

---

### Phase 3 — Plan Review Roles + Safe-Fix Policy  *(complexity: hard, kind: orchestration)*

**Goal:** model-backed plan review for judgment calls that lint cannot make.

#### Files to create / modify

| File | Action |
|---|---|
| `role-specs/agent-plan-review.md` | CREATE |
| `role-specs/agent-plan-normalizer.md` | CREATE |
| `agents/agent-plan-review.md` | GENERATED via `roles gen --write` |
| `agents/agent-plan-normalizer.md` | GENERATED via `roles gen --write` |
| `roles/agent-plan-review/shared.md` | GENERATED |
| `roles/agent-plan-normalizer/shared.md` | GENERATED |
| `permissions/plan-review.json` | CREATE |
| `permissions/plan-normalizer.json` | CREATE |
| `py/swarm_do/pipeline/permissions.py` | EXTEND (`ROLE_NAMES`) |
| `schemas/permissions.schema.json` | EXTEND (role enum) |
| `py/swarm_do/pipeline/tests/test_permissions.py` | EXTEND (drift guard test) |
| `py/swarm_do/roles/tests/test_renderers.py` | EXTEND (cover new specs) |

#### Implementation tasks

1. **`agent-plan-review`** (read-only role).
   - **copy-from:** `role-specs/agent-research.md` for the read-only contract
     shape; `role-specs/agent-clarify.md` for finding-vocabulary structure.
   - Permission preset: `permissions/plan-review.json` —
     **copy-from:** `permissions/research.json` for read-only allow/deny lists.
   - Output finding shape: `{severity in [blocking, safe_fix, advisory],
     phase_id|None, location, reason, citation}`.

2. **`agent-plan-normalizer`** (narrow-write role).
   - **copy-from:** `role-specs/agent-writer.md` for narrow-write contract.
   - Permission preset: `permissions/plan-normalizer.json` —
     **copy-from:** `permissions/writer.json`. Restrict writes to the prepared
     plan path under the run artifact directory.

3. **3-iteration cap loop** in `prepare.py`:

   ```
   for i in range(3):
       lint_findings = run_lint(plan)
       review_findings = run_plan_review(plan, lint_findings)
       if no_blocking(lint_findings + review_findings):
           break
       plan = run_plan_normalizer(plan, lint_findings, accepted_safe_fixes)
   else:
       artifact.status = "needs_input"
   artifact.review_iteration_count = i + 1
   ```

4. **Three-place lockstep** for new roles:
   - Add `plan-review`, `plan-normalizer` to `ROLE_NAMES` in
     `permissions.py:15`.
   - Add both to the `role` enum in `schemas/permissions.schema.json`.
   - Add fragment files `permissions/plan-review.json`, `permissions/plan-normalizer.json`.
   - Add a regression test that fails when these three drift (Phase 0 §E
     showed `clean-review`/`implementation-advisor` are already drifted —
     do not propagate that bug).

5. **Regenerate role outputs**:

   ```
   python3 -m swarm_do.roles gen --write
   ```

#### Acceptance criteria

- Role specs render into generated agent files (stamp present in `agents/`).
- `load_fragment("plan-review")` and `load_fragment("plan-normalizer")` succeed.
- Plan-review output has structured finding shape consumable by `prepare.py`.
- Normalizer output passes `bin/swarm plan prepare` lint.
- Blocking findings stop prepare before execution.
- Loop never exceeds 3 iterations; the third blocking iteration → `needs_input`.
- Drift test fails if any of the three role-registry locations diverge.

#### Verification commands

```bash
python3 -m swarm_do.roles gen --check
python3 -m unittest discover -s py/swarm_do/roles/tests -p 'test_*.py'
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_plan_prepare*.py'
```

#### Anti-pattern guards

- ❌ Do not hand-edit `agents/agent-plan-{review,normalizer}.md`. Run the generator.
- ❌ Do not let the normalizer invent requirements or acceptance criteria. Its
  contract is canonical-form rewrite ONLY.
- ❌ Do not add the new roles to only one or two of the three registry
  locations.
- ❌ Do not auto-apply model-labeled `safe_fix` findings. They are summarized
  for operator review (Phase 4).

---

### Phase 4 — `/swarmdaddy:prepare` Command Profile  *(complexity: moderate, kind: feature)*

**Goal:** operator-facing wrapper. Two-step flow only.

#### Files to create / modify

| File | Action |
|---|---|
| `commands/prepare.md` | CREATE |
| `skills/swarmdaddy/SKILL.md` | EXTEND |
| `README.md` | EXTEND |
| `py/swarm_do/pipeline/cli.py` | EXTEND (`cmd_prepare`) |
| `py/swarm_do/pipeline/tests/test_command_profiles.py` | EXTEND |
| `docs/testing-strategy.md` | EXTEND |

#### Implementation tasks

1. **`commands/prepare.md`** — argument-hint:
   `<plan-path> [--dry-run] [--auto-mechanical-fixes] | --accept <run-id> | --reject <run-id>`.
   - **copy-from:** `commands/design.md` for output-only command boundaries
     and `commands/do.md` for frontmatter shape.

2. **Pipeline ordering** (verbatim from design plan §Phase 4 lines 388-403):

   1. deterministic lint (Phase 2)
   2. canonical phase writer (Phase 2) → `prepared.md`
   3. plan-review/normalize loop, capped at 3 iterations (Phase 3)
   4. apply mechanical fixes only; model `safe_fix` proposals are summarized,
      NOT auto-applied
   5. inspect each phase to populate `phase_map` with `content_sha`
   6. parallel decompose for every phase whose `requires_decomposition` is
      true; simple phases use deterministic synth (`synthesize_work_units`,
      `decompose.py:94-118`); cache by `phase_map.cache_key`
   7. write `prepared.md` + prepared artifact + `work_unit_artifacts`
   8. exit with `Status: READY_FOR_ACCEPTANCE | NEEDS_INPUT | REJECTED`

3. **Accept mode** (`--accept <run-id>`):
   - re-run schema + trust-boundary + stale checks
   - print: prepared plan path, finding counts, proposed safe-fix summary,
     work-unit count, allowed-file summary, validation-command summary,
     hash + git-base summary
   - transition `ready_for_acceptance -> accepted` only after explicit operator confirmation

4. **CLI handler** `cmd_prepare(args)` in `cli.py`.
   - **copy-from:** `cmd_design`/`cmd_research` profile handler shape.
   - **copy-from test scaffold:** `py/swarm_do/pipeline/tests/test_command_profiles.py:1-40`
     (`_dry_run` helper).

#### Acceptance criteria

- `commands/prepare.md` exists with explicit boundaries.
- README documents the two-step flow.
- Command-profile tests cover dry-run validation and profile activation rules.
- Prepare cannot create writer issues, worktrees, merges, or PRs.
- Decompose runs in parallel across moderate/hard phases inside prepare;
  cache-key hits skip redundant agent calls on iteration.
- Accepted artifacts always carry `work_unit_artifacts` for every phase.
- `/swarmdaddy:prepare` never marks artifacts accepted without a separate accept action.
- Model-labeled `safe_fix` proposals shown as summary, not auto-applied.

#### Verification commands

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
```

#### Anti-pattern guards

- ❌ Do not allow `cmd_prepare` to call writer/spec-review/review/docs lanes.
- ❌ Do not run a second `agent-decompose` outside this phase's pipeline.
- ❌ Do not auto-apply model `safe_fix`s under any flag.
- ❌ Do not initialize Beads inside `cmd_prepare` deterministic paths.

---

### Phase 5 — `/swarmdaddy:do --prepared` Execution Gate  *(complexity: hard, kind: feature)*

**Goal:** consume an accepted prepared artifact; pure dispatch with no second decompose.

#### Files to create / modify

| File | Action |
|---|---|
| `commands/do.md` | EXTEND (add `--prepared` flag, `<prepared-artifact-path> --prepared` form) |
| `skills/swarmdaddy/SKILL.md` | EXTEND |
| `py/swarm_do/pipeline/prepare.py` | EXTEND (artifact-load helpers reused by `do`) |
| `py/swarm_do/pipeline/resume.py` | EXTEND (recognize prepared-but-not-dispatched) |
| `py/swarm_do/pipeline/run_state.py` | EXTEND if needed |
| `py/swarm_do/pipeline/tests/test_resume.py` | EXTEND |
| `py/swarm_do/pipeline/tests/test_inspect.py` | EXTEND |
| `py/swarm_do/pipeline/tests/test_command_profiles.py` | EXTEND |

#### Implementation tasks

1. **Pre-dispatch verification** (in `cmd_do` when `--prepared` is set):
   - `load_prepared_artifact(run_id)` (Phase 1)
   - assert `status == "accepted"`
   - re-check whole-plan + per-phase `cache_key` staleness
   - re-run trust-boundary on `repo_root`, `git_base_sha`, sidecar hashes,
     prepared markdown path, inspect output, work-unit artifacts
   - reject absolute paths, `..` segments, out-of-repo plan paths,
     out-of-run-dir sidecars, work-unit scopes that fail lint
   - attach `phase_map` and `review_findings` to the run state

2. **Skip-list when `--prepared`**:
   - skip the legacy plan-prepare stage in `cmd_do`
   - skip ALL `agent-decompose` calls (assert via test)
   - ignore active preset's `decompose.mode` field

3. **Refusal states**: `draft`, `ready_for_acceptance`, `needs_input`,
   `rejected`, `stale` → exit non-zero before any Beads child issue is created.

4. **Resume awareness**:
   - **copy-from:** `resume.py:30 ResumeReport`, `resume.py:57-95
     build_resume_report`. Add a branch that returns `STATUS_PREPARED`
     when the artifact is accepted but no checkpoint/dispatch event exists yet.

#### Acceptance criteria

- Accepted prepared artifacts can start normal execution.
- Stale or unaccepted prepared artifacts fail before any Beads child is created.
- Trust-boundary failures fail before Beads child creation.
- `--prepared` path NEVER invokes `agent-decompose`; tests assert this.
- Resume surfaces prepared-but-not-dispatched state without merging or mutating branches.
- Legacy `/swarmdaddy:do <plan-path>` behavior still works, including its
  existing `decompose.mode` preset field.

#### Verification commands

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
bin/swarm plan inspect docs/swarmdaddy-prepare-gate-plan.md --no-write --json
```

#### Anti-pattern guards

- ❌ Do not invoke `agent-decompose` when `--prepared` is set.
- ❌ Do not honor `decompose.mode` from the preset when `--prepared` is set.
- ❌ Do not skip stale checks "because we already validated at prepare time".
  The artifact may have been accepted hours/days ago.

---

### Phase 6 — Dogfood Telemetry + Promotion Scorecard  *(complexity: moderate, kind: observability)*

**Goal:** measurement to decide whether `--prepare --continue` (Phase 7) is safe to enable.

#### Files to create / modify

| File | Action |
|---|---|
| `schemas/telemetry/run_events.schema.json` | EXTEND (event_type enum) |
| `py/swarm_do/telemetry/registry.py` | EXTEND if a typed helper is needed |
| `py/swarm_do/pipeline/prepare.py` | EXTEND (emit events) |
| `py/swarm_do/pipeline/tests/test_prepare_artifact.py` | EXTEND |
| `docs/eval-recipes.md` | EXTEND |
| `docs/adr/0006-prepare-gate-contract.md` | EXTEND |

#### Implementation tasks

1. **New `event_type` values** to add to enum at
   `schemas/telemetry/run_events.schema.json`:

   ```
   prepare_started
   prepare_lint_findings
   prepare_review_findings
   prepare_safe_fixes_accepted
   prepare_safe_fixes_proposed_unaccepted
   prepare_ready_for_acceptance
   prepare_blocking_findings
   prepare_accepted
   prepare_stale_rejected
   prepare_dispatch_started
   ```

2. **Emit pattern**: reuse `run_state.py:57 append_run_event` (Phase 0 §F).
   **copy-from:** `run_state.py:191-208` for row construction.

3. **Scorecard** (in `docs/eval-recipes.md`):
   - operator interventions per run trend ↓
   - manual plan-review time trend ↓
   - spec-mismatch retry rate not ↑
   - final review churn not ↑
   - decomposition rejections not ↑
   - wall-clock within budget

4. **ADR `0006-prepare-gate-contract.md`** — document architecture decisions
   already locked in design plan lines 78-105.

#### Acceptance criteria

- Prepare events validate against `run_events.schema.json`.
- Existing telemetry tests still pass.
- Eval docs document promote/hold/rollback criteria for `--prepare --continue`.

#### Verification commands

```bash
python3 -m unittest discover -s py/swarm_do/telemetry/tests -p 'test_*.py'
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_prepare*.py'
```

#### Anti-pattern guards

- ❌ Do not invent a typed emit API ahead of need; keep using `append_run_event`.
- ❌ Do not bypass `schema_ok` validation when emitting.

---

### Phase 7 — `--prepare --continue` Convenience Flag  *(complexity: moderate, kind: ux)*

**Gating:** only proceed if Phase 6 scorecard shows green for ≥ N dogfood runs (operator decision).

#### Files to create / modify

| File | Action |
|---|---|
| `commands/do.md` | EXTEND (`--prepare --continue` flag) |
| `skills/swarmdaddy/SKILL.md` | EXTEND |
| `README.md` | EXTEND |
| `py/swarm_do/pipeline/cli.py` | EXTEND |
| `py/swarm_do/pipeline/tests/test_command_profiles.py` | EXTEND |
| `docs/eval-recipes.md` | EXTEND |

#### Implementation tasks

1. Auto-accept ONLY if **all** of:
   - lint clean OR mechanical-fix-only AND policy allows
   - no blocking findings
   - no advisory finding above configured risk threshold
   - no model-labeled `safe_fix` (those still require operator)
   - no inferred hard-phase additions
   - no material rewrite

2. Otherwise stop with `Status: NEEDS_INPUT`. Operator runs
   `/swarmdaddy:prepare --accept <run-id>` to continue.

3. The flag MUST record the same prepared artifact as the two-step flow.

#### Acceptance criteria

- `--prepare --continue` is opt-in only.
- Blocking or stale prepare output prevents dispatch.
- Same prepared artifact recorded as the two-step flow.
- README explains when to use two-step vs. auto-continue.
- `--prepare --continue` cannot auto-accept model-labeled safe fixes,
  changed validation commands, changed allowed-file scopes, or any artifact
  that fails trust-boundary validation.

#### Verification commands

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
bin/swarm preset dry-run balanced docs/swarmdaddy-prepare-gate-plan.md
```

#### Anti-pattern guards

- ❌ Do not auto-accept any model-labeled `safe_fix`.
- ❌ Do not allow `--prepare --continue` to bypass trust-boundary validation.
- ❌ Do not enable `--prepare --continue` by default until Phase 6 scorecard greenlights.

---

### Phase 8 — Final Verification  *(no new files)*

#### Tasks

1. Run full Python suite:

   ```bash
   python3 -m unittest discover -s py -p 'test_*.py'
   ```

2. Anti-pattern grep audit:

   ```bash
   # No bd imports inside prepare.py
   rg -n '^\s*(import|from)\s+bd' py/swarm_do/pipeline/prepare.py && echo BAD || echo OK

   # No agent-decompose invocations under --prepared dispatch
   rg -n 'agent-decompose|decompose_phase' py/swarm_do/pipeline/cli.py | rg -v 'cmd_prepare\b'

   # ROLE_NAMES / permissions schema lockstep
   python3 -c "
   import json, re
   from py.swarm_do.pipeline.permissions import ROLE_NAMES
   schema = json.load(open('schemas/permissions.schema.json'))
   enum = set(schema['properties']['role']['enum'])
   missing = ROLE_NAMES - enum
   assert not missing, f'role drift: {missing}'
   print('OK')
   "
   ```

3. End-to-end manual smoke:

   ```bash
   # Two-step flow
   bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --write --json
   # → note the run_id
   bin/swarm plan accept <run-id>
   bin/swarm do --prepared <run-id>   # should refuse if dispatch dependencies missing, but accept the artifact
   ```

4. Telemetry sanity:

   ```bash
   tail -n 20 "$CLAUDE_PLUGIN_DATA/telemetry/run_events.jsonl" 2>/dev/null \
     || tail -n 20 "$(python3 -c 'from swarm_do.pipeline.paths import resolve_data_dir; print(resolve_data_dir())')/telemetry/run_events.jsonl"
   ```

   Confirm new `prepare_*` events appear and validate against the schema.

#### Promotion gate

- All tests green.
- All anti-pattern greps return 0 hits.
- Scorecard (Phase 6) trends are non-regressive across ≥ N dogfood runs.
- ADR `0006` published.

---

## Open questions deferred from design plan

These are tracked but NOT blockers for Phases 1–6. Resolve before / during Phase 7
based on dogfood evidence:

1. Beads requirement for model-assisted prepare — helper-only mode default? (lines 638-639)
2. Repo-visible `docs/prepared/` mirror? (lines 640-641)
3. Plan-review finding vocabulary: reuse provider-findings schema or new prepare-specific schema? (lines 642-643)
4. `agent-decompose` parallelism cap inside prepare (4? 6?). (lines 644-647)
5. Sign accepted artifacts vs. hash-bind only? (lines 648-650)

## Rollback ladder (from design plan §Rollback Plan)

1. Stop using `--prepared` → revert to legacy `/swarmdaddy:do <plan-path>`.
2. Disable `--prepare --continue`; keep `/swarmdaddy:prepare` as advisory.
3. Disable `--auto-mechanical-fixes`; require manual acceptance for every rewrite.
4. Move `agent-plan-review` behind an experimental preset.
5. Fall back from parallel to serial decompose inside prepare (last resort).
