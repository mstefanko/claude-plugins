# SwarmDaddy Prepare Gate Plan

Goal: make SwarmDaddy own the repetitive plan-prep loop before implementation:
review a concrete plan for gaps, safely fix mechanical issues, convert it into
canonical runnable phases, prepare bounded work units where useful, then let
`/swarmdaddy:do` continue from an accepted prepared artifact.

The operator experience should move from:

```text
write plan -> manual review -> manual fixes -> /made-plan -> /swarmdaddy:do
```

to:

```text
/swarmdaddy:prepare <plan.md> -> review prepared artifact -> accept artifact
/swarmdaddy:do --prepared <run-id>
```

After dogfood proves the gate is reliable, add the convenience path:

```text
/swarmdaddy:do <plan.md> --prepare --continue
```

## Recommendation

Build this as a first-class prepare gate, not silent behavior inside normal
`/swarmdaddy:do`.

The plan is the implementation contract. SwarmDaddy may help shape the
contract, but any material rewrite must stop for operator acceptance before
writer branches, worktrees, merges, or pull requests begin.

## Current State

- `/swarmdaddy:do` already has a plan-prepare section that runs
  `bin/swarm plan inspect <plan-path> --json`.
- `plan.inspect` can parse `### Phase` headings and falls back to one synthetic
  phase for older scratch plans.
- `decompose.mode` supports `off`, `inspect`, and `enforce`, but stock presets
  still default to `off`.
- `agent-decompose` already owns the schema-strict `work_units.v2` artifact for
  one inspected phase.
- The missing layer is the pre-inspect contract: reviewing an unphased or
  under-specified plan, deciding which gaps are safe to fix, producing canonical
  phase markdown, and tracking acceptance before execution.

## Design Principles

- Keep deterministic helpers responsible for parsing, schema validation,
  artifact loading, stale checks, hashes, and phase/work-unit lint.
- Keep model-backed agents responsible for judgment: feasibility,
  completeness, ambiguity, scope risk, and safe-fix recommendations.
- Auto-fix only mechanical issues: headings, phase ids, extracted validation
  commands, explicit complexity tags, duplicate labels, formatting, and
  canonical phase layout.
- Do not auto-invent requirements, API behavior, security policy, UX decisions,
  migration strategy, or acceptance criteria that were not present in the
  original plan or accepted by the operator.
- Store both the original plan hash and prepared plan hash, bind artifacts to
  the current repo and git base, and refuse execution when any sidecar, path,
  or hash is stale.
- Treat provider/model review evidence as advisory during prepare. It can block
  on severe gaps, but it must not directly approve implementation.
- `/swarmdaddy:prepare` never marks an artifact accepted by itself. Acceptance
  is a separate operator action after reviewing the normalized plan, findings,
  work-unit splits, file scopes, and validation commands.

## Architecture Decisions (Locked)

These decisions resolve ambiguity across phases and must be honored consistently
by every implementation step. They are derived from the MetaSwarm pattern
(Plan → Design Review Gate → Work Unit Decomposition → Execution), adapted to
SwarmDaddy's deterministic-helper-plus-bounded-agent split.

- **Decompose runs inside `/swarmdaddy:prepare`, not inside
  `/swarmdaddy:do --prepared`.** The prepared artifact's `work_unit_artifacts`
  field is populated during prepare. `/swarmdaddy:do --prepared` is pure
  consumption: load artifact, verify hashes, create Beads child issues, run
  executor. There is no second decompose round between acceptance and dispatch.
- **Plan review iterates at most 3 times before escalating to operator input.**
  Each iteration runs lint → review → normalize → re-lint. After the third
  iteration without convergence, status flips to `needs_input`. This bounds
  cost and matches MetaSwarm's design-review cap.
- **Decompose runs in parallel across moderate and hard phases.** Phases are
  independent in `inspect_phase` output; fan them out. Simple phases use the
  deterministic synthesizer (no agent call). Per-phase decompose failures are
  isolated — one bad phase does not poison the rest.
- **`phase_map` stores per-phase cache identity, not only raw content.**
  Re-running prepare after a partial rewrite reuses decomposition only when the
  phase content, whole prepared-plan hash, shared plan-context hash,
  schema/role versions, and prepare policy version all match. This caps
  incremental cost without reusing stale work-unit scopes after cross-phase
  contract changes.
- **Operator acceptance covers both `review_findings` and
  `work_unit_artifacts`.** One acceptance moment for the full prepared
  artifact, not separate accept-the-plan and accept-the-splits steps.
- **Legacy `/swarmdaddy:do <plan-path>` retains today's `decompose.mode`
  preset field** (off/inspect/enforce). The `--prepared` path ignores that
  field — decompose is unconditional inside prepare.
- **Prepare returns a runnable package, not just a rewritten plan.** The
  operator sees a prepared markdown path, review summary, work-unit summary, and
  `run_id`. `/swarmdaddy:do --prepared <run-id>` consumes the accepted package.

## Out Of Scope

- No recursive orchestration.
- No automatic PR shepherding.
- No default-on `--prepare --continue` until dogfood telemetry shows fewer
  operator interventions and no increase in spec mismatches or review churn.
- No replacement for `/swarmdaddy:design`; prepare starts from a concrete plan,
  not a vague design question.
- No broad rewrite of the pipeline DSL.

### Phase 1: Prepared Run Artifact Contract (complexity: moderate, kind: foundation)

Define and persist the artifact that connects plan review, normalization,
decomposition, acceptance, and later execution.

**File Targets**

- `schemas/prepared_plan.schema.json`
- `py/swarm_do/pipeline/prepare.py`
- `py/swarm_do/pipeline/run_state.py`
- `py/swarm_do/pipeline/tests/test_prepare_artifact.py`
- `docs/adr/0006-prepare-gate-contract.md`

**Implementation**

- Add a prepared-plan artifact schema with:
  - `schema_version`
  - `run_id`
  - `repo_root`
  - `git_base_ref`
  - `git_base_sha`
  - `source_plan_path`
  - `source_plan_sha`
  - `prepared_plan_path`
  - `prepared_plan_sha`
  - `inspect_artifact`: `{path, sha}`
  - `phase_map`: ordered list of `{phase_id, title, complexity, kind,
    content_sha, plan_context_sha, cache_key, requires_decomposition}`. The
    `cache_key` includes phase content, whole prepared-plan hash, shared
    plan-context hash, prepared-plan schema version, work-unit schema version,
    `agent-decompose` role version, and prepare policy version.
  - `review_findings`
  - `review_iteration_count`: integer in `[0, 3]`. Reaching 3 without
    convergence flips status to `needs_input`.
  - `accepted_fixes`
  - `work_unit_artifacts`: map keyed by `phase_id` to a `work_units.v2`
    sidecar descriptor `{path, sha, artifact}`, populated during prepare for
    every phase. Simple phases get deterministic single-unit artifacts; phases
    whose `requires_decomposition` is true get decomposed artifacts.
  - `acceptance`: `{accepted_by, accepted_at, accepted_source_sha,
    accepted_prepared_sha}` or `null`
  - `status`: `draft`, `ready_for_acceptance`, `needs_input`, `accepted`,
    `stale`, `rejected`
  - `created_at`, `ready_at`, and `accepted_at`
- Write artifacts under the existing run artifact directory.
- Add helpers to load, validate, mark accepted, and detect stale artifacts.
  Stale detection covers whole-plan hashes, sidecar hashes, git-base sha, and
  per-phase `cache_key`.
- Add artifact trust-boundary validation:
  - all persisted artifact sidecars live under the run artifact directory
  - source and prepared plan paths are canonicalized and must stay under the
    repo root
  - artifact sidecar paths are stored with hashes and re-read by hash before use
  - absolute paths and `..` segments are rejected from repo-relative plan,
    inspect, prepared-plan, and work-unit path fields
  - work-unit `allowed_files`, `blocked_files`, and `context_files` must be
    repo-relative, bounded, and non-overlapping according to the work-unit lint
    contract
  - validation commands are displayed for operator review and are never treated
    as file targets
  - accepted artifacts record the git base sha used at prepare time; dispatch
    refuses if the repo base changed unless the operator reruns prepare
- Add explicit state transitions:
  - prepare may write `draft`, `needs_input`, or `ready_for_acceptance`
  - `bin/swarm plan accept <run-id>` transitions only
    `ready_for_acceptance -> accepted` after rechecking hashes and trust-boundary
    validation
  - `bin/swarm plan reject <run-id>` transitions non-dispatched artifacts to
    `rejected`
  - no prepare path may directly create an `accepted` artifact
- Keep the artifact independent from Beads so deterministic helper tests can run
  without an initialized Beads rig.

**Acceptance Criteria**

- A prepared artifact can be written, loaded, schema-linted, marked
  `ready_for_acceptance`, accepted through `bin/swarm plan accept <run-id>`, and
  rejected through `bin/swarm plan reject <run-id>`.
- Stale source-plan and prepared-plan hashes are detected at the whole-plan
  level, sidecar level, git-base level, and per-phase cache-key level.
- `review_iteration_count` is bounded by `[0, 3]`; out-of-range values fail
  schema validation.
- `work_unit_artifacts` keys are valid phase ids that exist in `phase_map`.
- Invalid statuses, missing hashes, missing prepared files, absolute paths,
  `..` path segments, out-of-repo paths, or sidecar hash mismatches fail closed.
- Prepare cannot mark artifacts accepted; only the accept helper can transition
  `ready_for_acceptance -> accepted`.
- Existing `plan inspect` behavior remains unchanged.

**Validation Commands**

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan inspect docs/swarmdaddy-prepare-gate-plan.md --no-write --json
```

**Expected Results**

- The unittest suite passes.
- Inspect emits phase reports for this plan without writing a run artifact.

### Phase 2: Deterministic Plan Lint And Canonical Phase Writer (complexity: moderate, kind: feature)

Add the non-model layer that can identify obvious plan issues and convert a
source plan into canonical `### Phase` markdown.

**File Targets**

- `py/swarm_do/pipeline/plan.py`
- `py/swarm_do/pipeline/prepare.py`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/tests/test_plan_prepare_lint.py`
- `py/swarm_do/pipeline/tests/test_plan_prepare_write.py`

**Implementation**

- Add deterministic lint rules for:
  - no runnable `### Phase` headings
  - duplicate phase ids
  - missing acceptance criteria
  - missing validation commands
  - missing file targets when file paths are otherwise referenced
  - overly broad phase size by bullet/file thresholds
  - ambiguous implementation verbs such as "maybe", "consider", and "etc."
  - untagged hard-looking phases
- Define plan section grammar explicitly:
  - canonical section headings may be either `**File Targets**` style in source
    plans or `File Targets` style in normalized prepared plans
  - only entries inside `File Targets` contribute to explicit file scope
  - paths in fenced command blocks, inline command examples, `Validation
    Commands`, `Expected Results`, and narrative backticks are references only;
    they must not become `allowed_files`
  - source plans with both canonical and legacy section labels normalize to the
    canonical writer output before inspect/decompose
- Add a canonical phase writer that emits:
  - `### Phase <id>: <title> (complexity: <value>, kind: <value>)`
  - `File Targets`
  - `Implementation`
  - `Acceptance Criteria`
  - `Validation Commands`
  - `Expected Results`
  - `Notes`
- Preserve original text in the prepared artifact rather than overwriting the
  source plan.
- Add a CLI entrypoint:

```bash
bin/swarm plan prepare <plan-path> --dry-run --json
bin/swarm plan prepare <plan-path> --write --json
```

**Acceptance Criteria**

- Unphased plans produce a prepared markdown file with canonical phase headings.
- Already phased plans round-trip without destructive rewrites.
- Deterministic lint findings are stable in JSON output.
- The source plan is never modified by default.
- `File Targets` parsing supports the current bold section headings and does
  not infer command paths such as `bin/swarm`, the plan file itself, generated
  `prepared.md`, or paths from validation command fences as work-unit
  `allowed_files`.
- Tests cover path containment, `..` rejection, absolute-path rejection, and the
  split between file targets, context references, and validation commands.

**Validation Commands**

```bash
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_plan*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
```

**Expected Results**

- Plan parser and prepare tests pass.
- Dry run reports lint results and the prepared output path without mutating the
  source file.

### Phase 3: Plan Review Roles And Safe-Fix Policy (complexity: hard, kind: orchestration)

Add model-backed plan review for gaps that deterministic lint cannot judge.

**File Targets**

- `role-specs/agent-plan-review.md`
- `role-specs/agent-plan-normalizer.md`
- `agents/agent-plan-review.md`
- `agents/agent-plan-normalizer.md`
- `roles/agent-plan-review/shared.md`
- `roles/agent-plan-normalizer/shared.md`
- `permissions/plan-review.json`
- `permissions/plan-normalizer.json`
- `py/swarm_do/pipeline/permissions.py`
- `schemas/permissions.schema.json`
- `py/swarm_do/pipeline/tests/test_permissions.py`
- `py/swarm_do/roles/tests/test_renderers.py`

**Implementation**

- Add `agent-plan-review` with a read-only contract:
  - review one concrete plan
  - classify findings as `blocking`, `safe_fix`, or `advisory`
  - cite the plan section and the reason the issue matters
  - avoid implementation code changes
- Add `agent-plan-normalizer` with a narrow contract:
  - consume source plan, deterministic lint findings, and operator-accepted
    safe fixes
  - output canonical phase markdown only
  - do not invent new requirements
- Bound the review/normalize loop with an iteration cap of 3:
  - iteration `n` runs lint → review → normalize → re-lint
  - if iteration 3 still produces blocking findings, stop and flip status to
    `needs_input` rather than continuing
  - record `review_iteration_count` on the prepared artifact
- Add permission presets that allow read-only inspection for review and
  controlled artifact writes only for normalization.
- Add `plan-review` and `plan-normalizer` to the permission role registry and
  permission schema enum.
- Regenerate role outputs through the existing role generator.

**Acceptance Criteria**

- Role specs render into generated agent files.
- Plan review output has a structured finding shape that the prepare helper can
  store in `review_findings`.
- Normalizer output can be linted by `bin/swarm plan prepare`.
- Blocking findings stop prepare before execution.
- Plan-review loop never exceeds 3 iterations; the third blocking iteration
  flips the artifact to `needs_input` and surfaces all collected findings.
- `load_fragment("plan-review")`, `load_fragment("plan-normalizer")`, and
  `bin/swarm permissions check --role plan-review --role plan-normalizer`
  succeed against valid fragments.
- Permission schema tests include the new roles so future role additions cannot
  drift between JSON schema and Python registry.

**Validation Commands**

```bash
python3 -m swarm_do.roles gen --check
python3 -m unittest discover -s py/swarm_do/roles/tests -p 'test_*.py'
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_plan_prepare*.py'
```

**Expected Results**

- Generated role files are current.
- Role and prepare tests pass.

### Phase 4: `/swarmdaddy:prepare` Command Profile (complexity: moderate, kind: feature)

Expose the prepare gate as an explicit operator command before changing
`/swarmdaddy:do`.

**File Targets**

- `commands/prepare.md`
- `skills/swarmdaddy/SKILL.md`
- `README.md`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`
- `docs/testing-strategy.md`

**Implementation**

- Add `/swarmdaddy:prepare <plan-path> [--dry-run] [--auto-mechanical-fixes]`
  and `/swarmdaddy:prepare --accept <run-id>` / `/swarmdaddy:prepare --reject
  <run-id>` as operator-facing wrappers over the deterministic accept/reject
  helpers.
- In dry-run mode:
  - run deterministic lint
  - run budget/profile validation if possible
  - do not write prepared artifacts unless explicitly requested
- In normal mode, run this exact ordered pipeline:
  1. deterministic lint (Phase 2 helpers)
  2. canonical phase writer (Phase 2 helpers) → produces `prepared.md`
  3. plan-review/normalize loop, capped at 3 iterations (Phase 3 agents)
  4. apply deterministic mechanical fixes only; model-labeled `safe_fix`
     changes are summarized as proposed fixes and require operator acceptance
     before they can be applied
  5. inspect each phase to populate `phase_map` with per-phase `content_sha`
  6. decompose every phase whose `requires_decomposition` is true, in
     parallel, one `agent-decompose` call per moderate/hard phase
     (simple phases use the deterministic synthesizer); cache by
     `phase_map.cache_key` so unchanged and policy-compatible phases skip
     re-decomposition on later iterations
  7. write prepared markdown, prepared-plan artifact, and per-phase
     `work_unit_artifacts`
  8. stop with `Status: READY_FOR_ACCEPTANCE | NEEDS_INPUT | REJECTED`
- In accept mode:
  - re-run prepared artifact schema validation, trust-boundary validation, and
    stale checks
  - show the operator the prepared plan path, review finding counts, proposed
    model safe fixes, work-unit count, allowed-file summary, validation command
    summary, and hash/base-sha summary
  - transition `ready_for_acceptance -> accepted` only after the operator
    explicitly accepts the full package
- Operator acceptance covers the full prepared artifact: review findings,
  normalized plan, and work-unit splits in one decision.
- Keep writer/spec-review/review/docs lanes out of scope for this command.
- Document that `bin/swarm plan prepare` is the scriptable deterministic helper,
  while `/swarmdaddy:prepare` is the model-assisted command profile.

**Acceptance Criteria**

- `/swarmdaddy:prepare` has a command file with explicit boundaries.
- The README documents the new two-step flow.
- Command-profile tests cover dry-run validation and profile activation rules.
- Prepare cannot create writer issues, worktrees, merges, or PRs.
- Decompose runs in parallel across moderate/hard phases inside prepare;
  per-phase cache-key hits skip redundant agent calls on iteration.
- Accepted prepared artifacts always carry `work_unit_artifacts` for every
  phase, with deterministic single-unit artifacts for simple phases and
  decomposed artifacts for phases whose `requires_decomposition` is true.
- `/swarmdaddy:prepare` never marks artifacts accepted without a separate
  accept action.
- Model-labeled `safe_fix` proposals are shown as a diff/summary and are not
  auto-applied by `--auto-mechanical-fixes`.

**Validation Commands**

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
```

**Expected Results**

- Full Python suite passes.
- Dry-run helper output remains deterministic.

### Phase 5: `/swarmdaddy:do --prepared` Execution Gate (complexity: hard, kind: feature)

Teach implementation runs to start from an accepted prepared artifact.

**File Targets**

- `commands/do.md`
- `skills/swarmdaddy/SKILL.md`
- `py/swarm_do/pipeline/prepare.py`
- `py/swarm_do/pipeline/resume.py`
- `py/swarm_do/pipeline/run_state.py`
- `py/swarm_do/pipeline/tests/test_resume.py`
- `py/swarm_do/pipeline/tests/test_inspect.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`

**Implementation**

- Add `/swarmdaddy:do --prepared <run-id>` or
  `/swarmdaddy:do <prepared-artifact-path> --prepared`.
- Before dispatch:
  - load the prepared artifact
  - verify `status == accepted`
  - verify source and prepared hashes are not stale at both whole-plan and
    per-phase cache-key levels
  - verify `repo_root`, `git_base_sha`, canonical path containment, and sidecar
    hashes before reading prepared markdown, inspect output, or work-unit
    artifacts
  - reject absolute paths, `..` segments, out-of-repo plan paths, out-of-run-dir
    sidecars, and work-unit file scopes that fail lint
  - use the prepared plan path and the embedded `work_unit_artifacts` directly
  - attach the phase map and review findings to the run state
- Dispatch is pure consumption. When `--prepared` is set:
  - skip the legacy plan-prepare stage inside `/swarmdaddy:do`
  - skip any second `agent-decompose` call — work units already exist on the
    artifact
  - ignore the active preset's `decompose.mode` field
- Refuse execution for `draft`, `ready_for_acceptance`, `needs_input`,
  `rejected`, or `stale` artifacts.
- Make resume aware of prepared runs so it can return to the prepare acceptance
  gate when dispatch has not started.

**Acceptance Criteria**

- Accepted prepared artifacts can start normal `/swarmdaddy:do` execution.
- Stale or unaccepted prepared artifacts fail before Beads child issue creation.
- Trust-boundary failures fail before Beads child issue creation, including
  stale sidecar sha, changed git base, absolute path, `..`, out-of-repo path,
  out-of-run-dir sidecar, and invalid work-unit file scope.
- The `--prepared` path never invokes `agent-decompose`; tests assert no
  decompose calls happen during dispatch when work-unit artifacts are present.
- Resume surfaces prepared-but-not-dispatched state without merging or mutating
  branches.
- Legacy `/swarmdaddy:do <plan-path>` behavior still works, including its
  existing `decompose.mode` preset field.

**Validation Commands**

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
bin/swarm plan inspect docs/swarmdaddy-prepare-gate-plan.md --no-write --json
```

**Expected Results**

- Full Python suite passes.
- Both helper commands succeed against this plan file.

### Phase 6: Dogfood Telemetry And Promotion Scorecard (complexity: moderate, kind: observability)

Measure whether the prepare gate actually reduces the manual loop without
increasing downstream churn.

**File Targets**

- `schemas/telemetry/run_events.schema.json`
- `py/swarm_do/telemetry/registry.py`
- `py/swarm_do/pipeline/prepare.py`
- `py/swarm_do/pipeline/tests/test_prepare_artifact.py`
- `docs/eval-recipes.md`
- `docs/adr/0006-prepare-gate-contract.md`

**Implementation**

- Emit run events for:
  - prepare started
  - deterministic lint findings count
  - model review findings by severity
  - safe fixes accepted
  - model safe fixes proposed but not accepted
  - prepared artifact ready for acceptance
  - blocking findings
  - prepared artifact accepted
  - stale artifact rejected
  - execution from prepared artifact
- Add a dogfood scorecard:
  - operator interventions per run decrease
  - manual plan-review time decreases
  - spec mismatch retry rate does not increase
  - final review churn does not increase
  - decomposition rejections do not increase
  - wall clock stays within an accepted budget
- Document how to compare prepared and non-prepared runs.

**Acceptance Criteria**

- Prepare events validate against telemetry schemas.
- Existing telemetry tests pass.
- Eval docs explain how to decide whether `--prepare --continue` is ready.

**Validation Commands**

```bash
python3 -m unittest discover -s py/swarm_do/telemetry/tests -p 'test_*.py'
python3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_prepare*.py'
```

**Expected Results**

- Telemetry and prepare tests pass.
- Scorecard docs describe clear promote/hold/rollback criteria.

### Phase 7: Convenience Auto-Continue Flag (complexity: moderate, kind: ux)

After dogfood proves the two-step gate, add the optional one-command path.

**File Targets**

- `commands/do.md`
- `skills/swarmdaddy/SKILL.md`
- `README.md`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/tests/test_command_profiles.py`
- `docs/eval-recipes.md`

**Implementation**

- Add `/swarmdaddy:do <plan-path> --prepare --continue`.
- The flag must:
  - run the same prepare pipeline
  - auto-accept only deterministic clean plans or deterministic
    mechanical-fix-only plans when policy allows it
  - stop for operator input on blocking findings, advisory findings above the
    configured risk threshold, any model-labeled `safe_fix`, inferred hard
    phases, or any material rewrite
  - continue into normal execution only after the prepared artifact is accepted
- Keep the default `/swarmdaddy:do <plan-path>` behavior unchanged.
- Add docs that recommend the two-step flow for high-risk work.

**Acceptance Criteria**

- `--prepare --continue` is opt-in only.
- Blocking or stale prepare output prevents dispatch.
- The command records the same prepared artifact as the two-step flow.
- README explains when to use two-step prepare versus auto-continue.
- `--prepare --continue` cannot auto-accept model-labeled safe fixes, changed
  validation commands, changed allowed-file scopes, or any prepared artifact
  that fails trust-boundary validation.

**Validation Commands**

```bash
python3 -m unittest discover -s py -p 'test_*.py'
bin/swarm plan prepare docs/swarmdaddy-prepare-gate-plan.md --dry-run --json
bin/swarm preset dry-run balanced docs/swarmdaddy-prepare-gate-plan.md
```

**Expected Results**

- Full suite passes.
- Preset dry-run succeeds against this phased plan.

## Rollback Plan

- Keep `/swarmdaddy:do <plan-path>` legacy behavior available throughout.
  This is the natural rollback for any prepare-side regression — operators
  stop passing `--prepared`.
- If prepare artifacts create downstream churn, disable only
  `--prepare --continue` and keep `/swarmdaddy:prepare` as an advisory command.
- If plan normalization proves too aggressive, keep deterministic lint and
  prepared artifact state but require manual acceptance for every proposed
  rewrite and disable `--auto-mechanical-fixes`.
- If model-backed plan review is noisy, keep deterministic `bin/swarm plan
  prepare` and move `agent-plan-review` behind an experimental preset.
- If parallel decompose-in-prepare causes resource contention or cost
  spikes, fall back to serial decompose inside prepare before considering
  a move back to `/swarmdaddy:do --prepared`. Moving decompose out of
  prepare entirely would invalidate the single-acceptance-moment invariant
  and is a last resort.

## Open Questions

- Should `/swarmdaddy:prepare` require Beads for model-assisted review, or allow
  a helper-only mode by default and use Beads only when dispatching agents?
- Should accepted prepared plans live only under run artifacts, or also be
  copied into a repo-visible `docs/prepared/` directory when the operator asks?
- Should plan-review findings use the existing provider-findings vocabulary or
  a smaller prepare-specific schema?
- What is the right `agent-decompose` parallelism cap inside prepare? The
  current sequential default is 1; lifting to N=phase-count is straightforward
  but may need a per-run upper bound (4? 6?) to stay within Claude Code's
  Agent dispatch budget.
- Should accepted prepared plans be signed or only hash-bound? Hash-bound is
  enough for local dogfood, but signing could help if artifacts are shared
  across machines.
