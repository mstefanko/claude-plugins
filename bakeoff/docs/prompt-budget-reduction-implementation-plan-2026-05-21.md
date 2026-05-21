# Prompt Budget Reduction Implementation Plan

Date: 2026-05-21

Status: proposed

Scope: Bakeoff plugin prompt surfaces, especially `skills/bakeoff/SKILL.md`
and `commands/run.md`

## Recommendation

Reduce prompt budget by removing duplicated live contract first, then applying
progressive disclosure to long examples, templates, and mode-specific rules.

The current problem is not just verbosity. `skills/bakeoff/SKILL.md` and
`commands/run.md` contain large overlapping copies of the same workflow
contracts. That doubles prompt cost, creates drift risk, and makes every new
approval mode, partial-failure rule, or summary-file rule harder for the model
to honor.

Use first-class skill routing immediately, but keep the routed surface small:

- `commands/run.md`: one-line or very thin `/bakeoff:run` shim that invokes the
  focused run skill.
- `skills/bakeoff/SKILL.md`: tiny shared router/core contract with global
  invariants, type taxonomy, and the skill routing map.
- `skills/bakeoff-run/SKILL.md`: `/bakeoff:run` lifecycle: preflight,
  argument/path routing, approval transitions, validation, execution, and handoff
  to helper skills.
- `skills/bakeoff-drafting/SKILL.md`: natural-language drafting, task-fit,
  required-field non-synthesis, fast path, and split proposal rules.
- `skills/bakeoff-review/SKILL.md`: review-shaped drafts, code-review facet
  rules, multi-lens review, lens execution, and partial multi-lens summaries.
- `skills/bakeoff-summary/SKILL.md`: artifact summary, continuation advice, and
  post-run permission reminders.
- `references/`: long tables, preview blocks, summary templates, failure
  matrices, and examples that should not be eagerly loaded.
- `scripts/` or tests: prompt-size, duplicate-section, and route-adherence
  guardrails.

Do not trim the safety invariants blindly. The approval gate, no-inline-answer
rule, non-synthesizable build fields, path routing, validation-before-run, and
final artifact summary contract are load-bearing.

## Research Summary

### Local Bloat Audit

Current line counts:

```text
1034 skills/bakeoff/SKILL.md
 999 commands/run.md
2033 total
```

Highest-value duplication:

- Drafting invariants:
  `skills/bakeoff/SKILL.md:422-672` duplicates `commands/run.md:109-357`.
- Task fit and clean splits:
  `skills/bakeoff/SKILL.md:48-218` overlaps `commands/run.md:358-514`.
- Multi-lens review:
  `skills/bakeoff/SKILL.md:219-421` mirrors `commands/run.md:515-738`.
- Fast path:
  `skills/bakeoff/SKILL.md:673-771` repeats `commands/run.md:739-836`.
- Artifact summary and continuation:
  `skills/bakeoff/SKILL.md:925-1005` overlaps `commands/run.md:918-999`.

Near-duplicate rules also appear across source-of-truth/no-inline-answer,
work-order classification, path-like input handling, approval wording,
no-write-before-approval, and patch handoff/permission semantics.

Content that should stay explicit somewhere:

- `commands/run.md` preflight and flag routing.
- Existing work-order path validation and build/research routing.
- Required-field non-synthesis rules for acceptance criteria, verifier, scope,
  protected paths, and refactor invariants.
- No-write-before-approval.
- Validation-before-run.
- Final summary requirements and artifact paths.

### External Pattern Review

The strongest external patterns are consistent:

- Superpowers uses thin command shims that invoke focused skills rather than
  repeating workflow bodies in every command:
  <https://raw.githubusercontent.com/pcvelz/superpowers/main/commands/execute-plan.md>
- ECC separates portable skill behavior from harness-specific command adapters:
  <https://raw.githubusercontent.com/affaan-m/ECC/main/AGENTS.md>
  and
  <https://raw.githubusercontent.com/affaan-m/ECC/main/docs/architecture/cross-harness.md>
- GSD treats prompt surface as a budgeted module, with profiles, namespace
  routers, workflows, templates, and references:
  <https://raw.githubusercontent.com/gsd-build/get-shit-done/main/docs/adr/0011-skill-surface-budget-module.md>
  and
  <https://raw.githubusercontent.com/gsd-build/get-shit-done/main/docs/ARCHITECTURE.md>
- Anthropic's `frontend-design` plugin is a useful small-skill reference: short
  dense live instructions without large inline appendices:
  <https://raw.githubusercontent.com/anthropics/claude-code/main/plugins/frontend-design/skills/frontend-design/SKILL.md>
- OpenWolf uses generated maps and token-awareness to reduce repeated reading:
  <https://raw.githubusercontent.com/cytostack/openwolf/main/README.md>
- Metaswarm keeps phase transitions, retry policy, and human escalation close
  to the execution loop:
  <https://raw.githubusercontent.com/dsifry/metaswarm/main/skills/orchestrated-execution/SKILL.md>

Patterns to avoid:

- One giant always-loaded skill containing every command, template, example,
  failure policy, and appendix.
- Duplicating workflow text across Claude commands, Codex skills, and docs.
- Flat catalogs with verbose descriptions instead of routers or profiles.
- Advisory gates buried in long prose rather than state-transition rules.
- Relying on the model to remember state that could be persisted or summarized.

## Proposed Architecture

### First-Class Routing Strategy

Do not keep two hand-maintained canonical copies. Use a small set of focused
skills as the canonical workflow modules:

1. Preferred: `commands/run.md` is a shim to `bakeoff-run`; `bakeoff-run` routes
   to `bakeoff-drafting`, `bakeoff-review`, and `bakeoff-summary` as needed.
2. `skills/bakeoff/SKILL.md` remains the core/router skill with only global
   invariants and skill-selection guidance.
3. `references/` stores appendices, templates, examples, and long lookup tables,
   not the primary workflow contract.
4. Avoid: keeping the same multi-lens, task-fit, fast-path, approval, and
   summary prose in both live files with "keep in sync" comments.

The preferred approach is closest to the Superpowers command-shim pattern while
retaining the ECC/GSD discipline of one canonical behavior surface and small
routing adapters.

### Suggested File Layout

```text
commands/
  run.md                       # shim: invoke bakeoff-run

skills/
  bakeoff/
    SKILL.md                   # core/router and global invariants
  bakeoff-run/
    SKILL.md                   # /bakeoff:run lifecycle and transitions
  bakeoff-drafting/
    SKILL.md                   # NL drafting, task-fit, split, fast path
  bakeoff-review/
    SKILL.md                   # review drafts and multi-lens review
  bakeoff-summary/
    SKILL.md                   # artifact summaries and continuation advice

references/
  run-templates.md             # preview blocks and summary layouts
  lens-presets.md              # lens synonym/focus table
  anti-synthesis-examples.md   # examples, not core rule text
  failure-matrix.md            # approval/partial-failure tables if too long
```

The skill bodies own behavior. References are loaded only for bulky examples,
tables, and templates.

### Live Prompt Targets

Target budgets:

- `commands/run.md`: 15-60 lines.
- `skills/bakeoff/SKILL.md`: 60-120 lines.
- `skills/bakeoff-run/SKILL.md`: 120-250 lines.
- `skills/bakeoff-drafting/SKILL.md`: 120-250 lines.
- `skills/bakeoff-review/SKILL.md`: 120-250 lines.
- `skills/bakeoff-summary/SKILL.md`: 80-180 lines.
- No duplicated section body longer than roughly 15 consecutive lines across
  any two live skill or command files.

These are working limits, not sacred numbers. The real goal is to keep the
always-loaded contract compact while still making the model route to the right
skill before acting.

## Implementation Plan

### Phase 1: Baseline and Guardrails

Add a small prompt-budget report command or test that prints:

- line counts for `commands/*.md`, `skills/*/SKILL.md`, and `references/*.md`;
- approximate token or word counts;
- duplicated heading names across live command and skill files;
- skill catalog count and frontmatter description lengths;
- optionally, repeated exact blocks above a small line threshold.

Acceptance criteria:

- The report is easy to run during prompt-contract edits.
- It fails or warns when live prompt files exceed agreed budgets.
- It does not inspect secrets, run providers, or depend on network access.

### Phase 2: Create First-Class Skills Without Behavior Change

Create the new skill directories and move the long bodies there first, keeping
the wording as close to current as possible.

Initial extraction map:

- `skills/bakeoff-run/SKILL.md`: invocation contract, preflight, existing path
  mode, approval transitions, file writing, validation, execution, and route
  calls to the helper skills.
- `skills/bakeoff-drafting/SKILL.md`: required-field synthesis guidance,
  mechanical pre-flight checklist, anti-synthesis examples, backend/schema drift
  rules, fast path, task-fit, and clean split proposal rules.
- `skills/bakeoff-review/SKILL.md`: review classification, code-review facet
  rules, multi-lens trigger rules, lens execution, partial-progress handling,
  partial summary file rules, and optional synthesis.
- `skills/bakeoff-summary/SKILL.md`: run result summary, artifact path
  preservation, continuation advisor, and post-run permission reminders.
- `references/*.md`: long preview blocks, lens table, summary layout, failure
  tables, and examples that do not need to be loaded for every turn.

Acceptance criteria:

- Extracted files preserve current behavior.
- `commands/run.md` and `skills/bakeoff/SKILL.md` route to the correct focused
  skill with minimal prose.
- No approval or partial-failure rule exists only in a template file. State
  transition rules stay in the relevant workflow skill.

### Phase 3: Shrink `commands/run.md` To A Shim

Keep only command-local adapter behavior:

- invoke `bakeoff-run`;
- pass through the user's arguments/request;
- state that `/bakeoff:run` must not answer inline or call provider CLIs
  directly;
- state that `bakeoff-run` owns preflight, approval, validation, execution, and
  summary.

Remove every long workflow body from the command file.

Acceptance criteria:

- `commands/run.md` is short enough that command budget is no longer a material
  concern.
- The command always routes into `bakeoff-run` before drafting, writing,
  validating, running, or summarizing.
- The shim still prevents inline answers and direct provider CLI calls.

### Phase 4: Shrink `skills/bakeoff/SKILL.md` To Core Router

Keep shared cross-command and cross-harness guidance:

- Bakeoff is source of truth; the CLI owns validation, provider execution,
  judging, patch capture, reports, ledgers, triage, and exit codes.
- Do not place secrets in work orders, prompts, generated context, summaries, or
  plugin-written files.
- Work-order classification taxonomy.
- Permission semantics: Bakeoff artifacts are not permission to apply patches,
  commit, open PRs, merge, or synthesize changes.
- Environment variable/auth ownership.
- Skill route map.

Remove command-specific long bodies that now live in the focused skills.

Acceptance criteria:

- `SKILL.md` is usable as a compact Bakeoff overview for Codex.
- It does not duplicate command-specific `run` workflow bodies.
- It clearly tells the model which focused skill to use before drafting, running,
  summarizing, or advising continuation.

### Phase 5: Add Prompt-Contract Scenarios

Add or update manual dogfood scenarios that verify adherence after the trim:

- Existing work-order path validates and routes to `build` or `research`.
- Natural-language build with missing verifier asks or performs targeted
  read-only discovery; it does not synthesize a fake verifier.
- Refactor request with "no behavior change" still asks for concrete
  invariants.
- Multi-lens request loads lens rules, requires exact `write and run`, and
  writes a partial summary on stopped sequences.
- Split request validates all files before running any part.
- Final handoff summarizes artifact paths and does not apply patches.

Acceptance criteria:

- The scenarios cover the rules most likely to regress when prose is moved out
  of live prompts.
- The scenarios mention which focused skill should have been routed to.

### Phase 6: Optional Generation

If drift remains a concern, generate the live files from smaller source
fragments during release prep:

- source fragments live under `prompt-src/` or the focused skill directories;
- generated files include a "generated from" header;
- CI checks that generated live files are current.

This should be a second pass. Manual extraction and budget guards are enough for
the first reduction.

## Approval, Partial Failure, and Summary File Placement

These rules should stay close to the state transition they control:

- Global no-write-before-approval: keep inline in both live surfaces or in a
  tiny shared rule in `skills/bakeoff/SKILL.md` and `skills/bakeoff-run/SKILL.md`.
- Single work-order approval: keep in `skills/bakeoff-run/SKILL.md` because it
  owns the transition from preview to file write.
- Natural-language preview and split approval details: keep in
  `skills/bakeoff-drafting/SKILL.md`.
- Multi-lens approval, partial-progress block, and summary-file writing: keep in
  `skills/bakeoff-review/SKILL.md`.
- Final artifact summary and continuation advisor: keep in
  `skills/bakeoff-summary/SKILL.md`.

Avoid a global "approval doctrine" that repeats every mode. A compact shared
rule plus mode-specific transition tables should be easier for the model to
follow.

## Acceptance Criteria

- `skills/bakeoff/SKILL.md` drops below 180 lines.
- `commands/run.md` drops below 60 lines unless a measured harness constraint
  proves the command must be self-contained.
- `skills/bakeoff-run/SKILL.md`, `skills/bakeoff-drafting/SKILL.md`,
  `skills/bakeoff-review/SKILL.md`, and `skills/bakeoff-summary/SKILL.md` each
  stay under the target budgets unless dogfood proves a specific exception.
- The extracted focused skills contain the full current behavior with no known
  safety rule removed.
- No large workflow section is hand-maintained in both live files.
- Prompt-budget guardrails report line/token counts and duplicate sections.
- Existing examples remain valid and continue to be referenced for JSON shape.
- Dogfood scenarios pass for approval, missing-field, multi-lens, split,
  existing-path, summary, and permission semantics.

## Open Questions

- Does the Claude command runtime reliably allow `commands/run.md` to invoke a
  plugin-local skill before acting, or must the command prompt remain more
  self-contained?
- Are `commands/run.md` and `skills/bakeoff/SKILL.md` ever loaded into the same
  model context for the same turn? The target budgets should be stricter if yes.
- How many focused skills can the plugin expose before skill-catalog routing
  overhead becomes its own prompt-budget problem?
- Should helper workflows such as `bakeoff-drafting` be user-invocable skills,
  or internal skills that only `bakeoff-run` routes to?
- What exact line or token budget should be enforced in CI?
- Should prompt-budget reporting live in shell scripts, Go tests, or both?
- How much of the approval contract must remain inline to preserve adherence
  after progressive disclosure?
- Should optional command families eventually ship as install profiles, or is
  `/bakeoff:run` the only urgent budget problem?

## Concerns

- The current long prose likely exists because prior shorter contracts failed in
  dogfood. Trimming without targeted scenarios could reintroduce silent
  synthesis, approval bypass, or inline answers.
- First-class routing saves prompt budget only if the model reliably invokes the
  focused skill before acting.
- Moving examples out of live prompt can increase schema drift unless the model
  is forced to use `bakeoff draft-build`, `bakeoff validate`, and the existing
  JSON examples.
- Two harnesses can drift if command and skill adapters are edited separately.
  A generated or tested source-of-truth approach may be needed.
- Partial-failure rules and summary-file rules are easy to bury. They need
  compact transition tables, not long narrative paragraphs.
- Too many focused skills can recreate the prompt-budget problem in the skill
  catalog. Keep the first split small and based on workflow boundaries.

## Assumptions

- The Go CLI remains the source of truth for schema validation, provider
  execution, judging, triage, reports, ledgers, and exit codes.
- Prompt reduction should not require changing Bakeoff runtime behavior.
- The existing `examples/*.work-order.json` files remain the canonical non-build
  JSON examples.
- Plugin-local skills can be invoked by command shims and can route to each
  other reliably enough for dogfood.
- A plugin-shipped `references/` directory can still be read for appendices,
  templates, and long examples when a focused skill asks for it.
- The first implementation should prefer a small first-class skill split,
  line-count reduction, and guardrails over a larger harness/profile redesign.
