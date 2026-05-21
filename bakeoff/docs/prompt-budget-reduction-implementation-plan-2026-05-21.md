# Prompt Budget Reduction Implementation Plan

Date: 2026-05-21

Status: proposed, tightened after clarity and value audits

Scope: Bakeoff plugin prompt surfaces, especially `commands/run.md` and
`skills/bakeoff/SKILL.md`

## Recommendation

Reduce prompt budget by removing duplicated live contract first. Do the first
implementation as one focused skill extraction, not a six-file prompt
architecture.

Target first pass:

- `commands/run.md`: thin `/bakeoff:run` shim that invokes `bakeoff-run`.
- `skills/bakeoff/SKILL.md`: compact core/router with global invariants, type
  taxonomy, permission semantics, and route map.
- `skills/bakeoff-run/SKILL.md`: the canonical `/bakeoff:run` workflow,
  including drafting, task fit, clean split, multi-lens review, approval,
  validation, execution, summary, and continuation advice.
- `references/run-appendix.md`: optional single appendix for bulky tables,
  preview blocks, summary templates, and long examples. Create it only if
  `bakeoff-run` would otherwise exceed the budget. Split this appendix only if
  it grows past roughly 200 lines.
- `scripts/prompt-budget.sh`: simple line-count budget check.

Defer `bakeoff-drafting`, `bakeoff-review`, and `bakeoff-summary` helper skills.
They are clean boundaries, but creating them now turns a two-file dedup into a
larger routing project. Add helper skills only after dogfood shows that
`bakeoff-run` remains too large or that routing by workflow phase improves
adherence.

## Accepted Audit Changes

- Keep the core insight: duplicate contract between `commands/run.md` and
  `skills/bakeoff/SKILL.md` is the load-bearing problem.
- Replace the previous five-skill split with one extracted skill:
  `skills/bakeoff-run/SKILL.md`.
- Replace the elaborate duplicate detector/frontmatter audit with a small
  `wc -l` budget script.
- Collapse `references/` to one optional `references/run-appendix.md`.
- Remove optional prompt-source code generation from this plan.
- Treat creation of `bakeoff-run`, command shim shrink, and core skill shrink as
  one migration, not independent phases that can land in a breaking order.
- Add explicit source-range move mapping, dogfood inputs/assertions, compatibility
  gate, and rollback plan.

## Research Summary

### Local Bloat Audit

Current live prompt size at the time of this tightened plan:

```text
1042 commands/run.md
1078 skills/bakeoff/SKILL.md
2120 total
```

Highest-value duplication:

- Drafting invariants:
  `commands/run.md:109-357` duplicates `skills/bakeoff/SKILL.md:466-716`.
- Task fit and clean splits:
  `commands/run.md:358-557` overlaps `skills/bakeoff/SKILL.md:48-262`.
- Multi-lens review:
  `commands/run.md:558-786` mirrors `skills/bakeoff/SKILL.md:263-465`.
- Fast path and general drafting:
  `commands/run.md:787-960` overlaps `skills/bakeoff/SKILL.md:717-947`.
- Artifact summary and continuation:
  `commands/run.md:961-1042` overlaps `skills/bakeoff/SKILL.md:969-1050`.

Content that must survive somewhere explicit:

- CLI preflight and existing work-order path routing.
- No inline answer and no direct provider CLI calls.
- Non-synthesizable fields: acceptance criteria, verifier, edit scope,
  protected benchmark paths, and refactor invariants.
- One batched context pass for drafting discovery.
- No write before approval.
- Validation before run.
- Split and multi-lens partial-failure behavior.
- Final artifact summary and permission semantics.

### External Pattern Review

External repo patterns support this shape:

- Superpowers uses thin command shims that invoke focused skills:
  <https://raw.githubusercontent.com/pcvelz/superpowers/main/commands/execute-plan.md>
- ECC separates portable skill behavior from harness-specific command adapters:
  <https://raw.githubusercontent.com/affaan-m/ECC/main/AGENTS.md>
- GSD treats prompt surface as budgeted and favors routing/modules over giant
  always-loaded prompts:
  <https://raw.githubusercontent.com/gsd-build/get-shit-done/main/docs/adr/0011-skill-surface-budget-module.md>
- Anthropic's `frontend-design` plugin is a useful small-skill reference:
  <https://raw.githubusercontent.com/anthropics/claude-code/main/plugins/frontend-design/skills/frontend-design/SKILL.md>

The useful import is not "make many skills." It is "make the command surface a
shim and keep one canonical behavior body."

## Architecture

### File Layout

```text
commands/
  run.md                         # shim to bakeoff-run

skills/
  bakeoff/
    SKILL.md                     # core/router and global invariants
  bakeoff-run/
    SKILL.md                     # canonical /bakeoff:run workflow

references/
  run-appendix.md                # optional bulky tables/templates/examples

scripts/
  prompt-budget.sh               # simple line budget report/check
```

### Shim Invocation Mechanism

Use textual skill invocation in `commands/run.md`; do not invent a custom
runtime hook.

`commands/run.md` should keep the existing command frontmatter and tool
allowlist, then reduce the body to this shape:

```markdown
# /bakeoff:run

Use the `bakeoff-run` skill for the entire workflow. Treat this command's
arguments and the user's request as input to that skill.

Do not satisfy the requested research, review, comparison, analysis, or build
inline. Do not call provider CLIs directly; only the Bakeoff CLI may launch
providers. If the `bakeoff-run` skill is unavailable, stop and report that the
plugin install or routing is incomplete.
```

The command shim must not draft, write, validate, run, or summarize on its own.
Those transitions belong to `bakeoff-run`.

### Budget Rule

Use one enforced first-pass budget:

```text
commands/run.md + skills/bakeoff/SKILL.md + skills/bakeoff-run/SKILL.md <= 1100 lines
```

Additional design targets:

- `commands/run.md` should be under 60 lines.
- `skills/bakeoff/SKILL.md` should be under 180 lines.
- `references/run-appendix.md` should stay under 200 lines; split only after it
  exceeds that size.

The script should enforce the aggregate budget first. Per-file targets can warn,
not fail, during the first pass.

## Verbatim Invariants To Preserve

The project `CLAUDE.md` repeats two `/bakeoff:run` invariants because they are
load-bearing. Preserve them verbatim in `skills/bakeoff-run/SKILL.md`; if a
future `bakeoff-drafting` helper skill is created, preserve them there too.

```markdown
- **One batched context pass.** If `/bakeoff:run` drafting needs local
  context (file paths, verifier conventions, schema, available
  backends), use ONE `ctx_batch_execute` call covering all questions.
  Sequential `Bash` / `Read` / `Grep` probes during drafting are a
  contract violation. Available backends (`claude`, `codex`) and the
  canonical work-order skeletons are embedded in the skill — do **not**
  probe the CLI (`bakeoff providers list`, `bakeoff --help`,
  `bakeoff init`, `bakeoff doctor`) to discover them.
- **No `Write` before approval.** Drafting must show the compact
  preview, wait for affirmative reply (`yes` / `approve` / `run it` for
  single, `write and run` for split/multi-lens), and only then issue
  the file-mutating tool call.
```

Also preserve the current command/skill rules that proposal is not approval,
`draft-build` stdout is pre-approval safe, and all on-disk work orders must pass
`bakeoff validate` before provider execution.

## Source Range Move Map

Use current headings as the authority and verify ranges with
`rg -n '^#{1,4} ' commands/run.md skills/bakeoff/SKILL.md` before editing.

Move into `skills/bakeoff-run/SKILL.md`:

| Source | Target section |
| --- | --- |
| `commands/run.md:15-107` | Invocation, preflight, existing path mode |
| `commands/run.md:109-357` | Drafting invariants |
| `commands/run.md:358-557` | Natural-language drafting, task fit, clean split |
| `commands/run.md:558-786` | Multi-lens review |
| `commands/run.md:787-960` | Fast path and general drafting |
| `commands/run.md:961-1042` | Execution, summary, continuation |

Remove duplicates from `skills/bakeoff/SKILL.md` after the moved
`bakeoff-run` skill exists and is routed:

| Source | Action |
| --- | --- |
| `skills/bakeoff/SKILL.md:48-262` | Remove duplicated task fit / split body |
| `skills/bakeoff/SKILL.md:263-465` | Remove duplicated multi-lens body |
| `skills/bakeoff/SKILL.md:466-716` | Remove duplicated drafting invariants |
| `skills/bakeoff/SKILL.md:717-947` | Remove duplicated fast path / drafting rules |
| `skills/bakeoff/SKILL.md:969-1050` | Remove duplicated summary / continuation body |

Keep and compress in `skills/bakeoff/SKILL.md`:

- source-of-truth principle;
- no secrets in work orders/prompts/generated context;
- work-order classification taxonomy;
- route to `bakeoff-run` for `/bakeoff:run`;
- permission semantics;
- environment/auth ownership.

## Implementation Steps

### Step 1: Add Budget Script

Create `scripts/prompt-budget.sh` as a small shell script using `wc -l`.

It should:

- print line counts for `commands/run.md`, `skills/bakeoff/SKILL.md`,
  `skills/bakeoff-run/SKILL.md` when present, and `references/run-appendix.md`
  when present;
- compute the aggregate live `/bakeoff:run` line count;
- fail if the aggregate exceeds 1100 lines after migration;
- warn, not fail, on per-file design target misses.

Do not build a duplicate-block detector, Go test, or frontmatter analyzer in
this pass.

### Step 2: Extract `bakeoff-run`

Create `skills/bakeoff-run/SKILL.md` and move the command workflow into it.
Preserve behavior first; edit for brevity only after the migration passes
dogfood.

The skill should own:

- preflight;
- existing work-order path mode;
- natural-language drafting;
- required-field non-synthesis;
- task-fit warnings and deterministic-evidence repair menu;
- clean split;
- multi-lens review;
- approval phrases;
- filename collisions;
- validation before run;
- execution and exit-code interpretation;
- artifact summary;
- continuation advice;
- permission reminders.

If the multi-lens lens table, preview block, or summary template pushes
`bakeoff-run` past the aggregate budget, move those bulky pieces into
`references/run-appendix.md` and leave only the rule plus "load appendix when
needed" pointer in the skill.

### Step 3: Shrink Command And Core Skill In The Same PR

After `bakeoff-run` exists:

1. Shrink `commands/run.md` to the shim.
2. Shrink `skills/bakeoff/SKILL.md` to the core/router.
3. Run `scripts/prompt-budget.sh`.
4. Run the dogfood scenarios below.

Do not merge a PR where `commands/run.md` routes to `bakeoff-run` before the
skill exists. If this work must be split across PRs, use this order:

1. PR A: add `bakeoff-run`, keep old command/skill bodies intact.
2. PR B: switch the command shim and remove duplicated bodies after dogfood.

Prefer one PR to avoid a long-lived duplicated state.

### Step 4: Dogfood Scenarios

Add these to `docs/task-fit-test-scenarios.md` or a new
`docs/prompt-budget-dogfood-scenarios.md`.

| Scenario | Input | Required assertions |
| --- | --- | --- |
| Existing path mode | `/bakeoff:run ./examples/review.work-order.json --run-id prompt-budget-path-smoke --quiet` | Routes through `bakeoff-run`; preflights; validates existing file; does not run task fit or natural-language drafting. |
| Missing verifier | `/bakeoff:run build fix auth timeout handling in internal/auth` | Does not invent `go test`; classifies verifier/scope/AC as explicit, repo-discoverable, or user-owned; uses at most one batched context pass before proposing. |
| Refactor invariants | `/bakeoff:run build extract default resolution helper in internal/config; verifier go test ./internal/config -run TestDefaults -count=1; edit scope internal/config` | Does not accept "no behavior change" as AC; asks for concrete invariants or proposes repo-discoverable evidence without writing. |
| Clean split | `/bakeoff:run compare our CLI setup flow against README expectations, and review my local diff for security` | Offers separate work orders only if each part has independent evidence; requires `split`; then requires exact `write and run`; validates all files before running any. |
| Multi-lens | `/bakeoff:run review my local changes against main with security and tests as separate lenses --diff` | Uses multi-lens rules; does not treat normal "security and tests" review as multi-lens unless separate lenses are requested; requires exact `write and run`; uses `<base>.<lens>` naming. |
| Partial multi-lens stop | Simulate one lens command failure or interrupt after one completed lens | Shows completed lenses, stopped lens, remaining lenses, artifact paths, and whether a partial summary file was written; asks for `continue lenses`. |
| Final handoff | Any completed build run with candidate patches | Summarizes report/decision/patch paths; does not apply patches, commit, open PRs, or synthesize changes without a separate user request. |

## Compatibility Gate

Before deleting the old command body, manually verify in the target Claude
plugin runtime that a command shim can route to `skills/bakeoff-run/SKILL.md`.

Expected behavior:

- `/bakeoff:run ...` causes the model to use the `bakeoff-run` skill body before
  drafting or running.
- If the skill is unavailable, the model stops with the shim error instead of
  falling back to inline answering.

If this fails, do not ship the shim. Fall back to keeping `commands/run.md`
self-contained for Claude and use `bakeoff-run` only on the Codex skill side
until the runtime behavior is understood.

## Rollback Plan

This migration is prompt/docs only. Rollback is straightforward:

1. Restore the previous full `commands/run.md` body.
2. Restore the previous full `skills/bakeoff/SKILL.md` body.
3. Leave `skills/bakeoff-run/SKILL.md` in place but unreferenced, or remove it in
   the rollback commit.
4. Re-run the dogfood scenario that failed and confirm the old behavior returns.

Do not partially roll back only the command shim; a shim pointing to a missing or
stale skill is worse than the current duplicated prompt.

## Resolved Questions

- **Shim mechanism:** textual skill invocation from `commands/run.md`, with the
  existing command frontmatter/tool allowlist retained. No new runtime hook.
- **Same-context loading:** assume the command, core skill, and routed run skill
  may all enter context for `/bakeoff:run`; enforce the aggregate 1100-line
  budget across those files.
- **Skill count:** one new focused skill in the first pass: `bakeoff-run`.
- **Helper skill visibility:** `bakeoff-drafting`, `bakeoff-review`, and
  `bakeoff-summary` are not created in this pass. If created later, treat them
  as internal helper skills routed from `bakeoff-run`, not user-facing commands.
- **Budget tool:** shell script at `scripts/prompt-budget.sh`, using `wc -l`.
  No Go test in this pass.
- **Approval contract placement:** global no-write and one-batched-context-pass
  invariants stay verbatim in `bakeoff-run`; mode-specific approval rules stay
  in the state transition they control.
- **Install profiles:** defer. `/bakeoff:run` prompt bloat is the urgent issue;
  profiles are a later plugin-wide budget project.
- **References:** one optional appendix file, not a directory of four files, in
  the first pass.

## Acceptance Criteria

- `commands/run.md` is a thin shim under 60 lines.
- `skills/bakeoff/SKILL.md` is a compact core/router under 180 lines.
- The aggregate live `/bakeoff:run` prompt surface is at or below 1100 lines.
- `skills/bakeoff-run/SKILL.md` contains the full current behavior with no known
  safety rule removed.
- The two `CLAUDE.md` invariants are preserved verbatim in `bakeoff-run`.
- No large workflow section is hand-maintained in both `commands/run.md` and
  `skills/bakeoff/SKILL.md`.
- `scripts/prompt-budget.sh` reports the line budget and fails on aggregate
  budget violation.
- Dogfood scenarios pass for existing path, missing verifier, refactor
  invariants, clean split, multi-lens, partial stop, final handoff, and
  permission semantics.

## Remaining Concerns

- Textual skill invocation must be verified in the Claude plugin runtime before
  removing the old command body.
- The current long prose likely exists because shorter contracts previously
  failed in dogfood. The scenario suite is the guardrail against reintroducing
  silent synthesis, approval bypass, or inline answers.
- Moving examples into an appendix can increase schema drift unless
  `bakeoff draft-build`, `bakeoff validate`, and `examples/*.work-order.json`
  remain explicit in `bakeoff-run`.
- If `bakeoff-run` remains too large after deduplication, split helper skills as
  a second pass based on observed dogfood failures, not ahead of evidence.
