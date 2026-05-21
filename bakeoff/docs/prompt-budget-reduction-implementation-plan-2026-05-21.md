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

Use this target shape:

- `skills/bakeoff/SKILL.md`: compact shared contract, trigger rules, safety
  invariants, type taxonomy, and a "load when needed" map.
- `commands/run.md`: thin `/bakeoff:run` command adapter with invocation,
  preflight, argument/path routing, and pointers to focused run references.
- `references/run/`: focused workflow references for natural-language drafting,
  split runs, multi-lens review, execution summaries, continuation advice, and
  templates.
- `examples/`: canonical JSON shapes remain outside the live prompt.
- `scripts/` or tests: prompt-size and duplicate-section guardrails.

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

### Canonical Source Strategy

Do not keep two hand-maintained canonical copies. Use one of these approaches:

1. Preferred: create focused `references/run/*.md` files as canonical workflow
   modules. `commands/run.md` and `skills/bakeoff/SKILL.md` become adapters that
   load the same modules when needed.
2. Acceptable fallback: make `commands/run.md` canonical for `/bakeoff:run` and
   reduce `SKILL.md` to shared overview plus command-specific pointers.
3. Avoid: keeping the same multi-lens, task-fit, fast-path, approval, and
   summary prose in both live files with "keep in sync" comments.

The preferred approach is closer to the Superpowers, ECC, and GSD patterns:
small routing surfaces, focused durable workflow modules, and fewer duplicated
contracts.

### Suggested File Layout

```text
references/
  run/
    README.md                  # load map and phase overview
    drafting.md                # task-fit, type routing, required-field rules
    approval.md                # shared approval and no-write rules
    split-runs.md              # clean split preview, approval, partial failure
    multi-lens-review.md       # lens selection, run sequence, partial summary
    execution-summary.md       # artifact summary, continuation advisor
    templates.md               # preview blocks, summary layout, lens table
```

The live prompt should retain only the route map and the mandatory state
transition reminders. Long examples and reusable templates move out.

### Live Prompt Targets

Target budgets:

- `skills/bakeoff/SKILL.md`: 100-180 lines.
- `commands/run.md`: 120-250 lines.
- No duplicated section body longer than roughly 15 consecutive lines across
  the two live files.

These are working limits, not sacred numbers. The real goal is to keep the
always-loaded contract compact while still making the model load the right
reference before acting.

## Implementation Plan

### Phase 1: Baseline and Guardrails

Add a small prompt-budget report command or test that prints:

- line counts for `skills/bakeoff/SKILL.md`, `commands/*.md`, and
  `references/run/*.md`;
- approximate token or word counts;
- duplicated heading names across `SKILL.md` and `commands/run.md`;
- optionally, repeated exact blocks above a small line threshold.

Acceptance criteria:

- The report is easy to run during prompt-contract edits.
- It fails or warns when live prompt files exceed agreed budgets.
- It does not inspect secrets, run providers, or depend on network access.

### Phase 2: Extract Without Behavior Change

Create the `references/run/` files and move the long bodies there first, keeping
the wording as close to current as possible.

Initial extraction map:

- `drafting.md`: required-field synthesis guidance, mechanical pre-flight
  checklist, anti-synthesis examples, backend/schema drift rules, fast path.
- `split-runs.md`: task-fit clean split handling and split partial-failure
  behavior.
- `multi-lens-review.md`: trigger rules, lens table, preview wording, approval,
  sequential execution, partial summary, optional synthesis.
- `execution-summary.md`: existing path summary, run result summary,
  continuation advisor, permission semantics.
- `templates.md`: long preview blocks, summary layout, and examples that do not
  need to be always loaded.

Acceptance criteria:

- Extracted files preserve current behavior.
- `commands/run.md` and `SKILL.md` still contain enough inline guidance to route
  to the correct reference.
- No approval or partial-failure rule exists only in a template file. State
  transition rules stay in the relevant workflow reference.

### Phase 3: Shrink `commands/run.md`

Keep command-local operational behavior:

- invocation contract;
- preflight with `bakeoff-ensure-cli --check`;
- flag parsing and path detection;
- existing work-order validate-and-route flow;
- hard stop rules before a run starts;
- pointer map for natural-language drafting, split, multi-lens, and summary.

Remove or replace repeated long sections:

- replace drafting invariants with "load `references/run/drafting.md` before
  drafting from natural language";
- replace multi-lens body with "load `references/run/multi-lens-review.md`
  when the request explicitly asks for separate review lenses";
- replace split details with "load `references/run/split-runs.md` after task
  fit passes and before proposing multiple work orders";
- replace final summary/continuation details with "load
  `references/run/execution-summary.md` after any run completes or partially
  stops".

Acceptance criteria:

- `commands/run.md` remains sufficient to avoid inline answering, direct
  provider CLI calls, and preflight bypass.
- The command cannot write a work order unless approval rules have been loaded
  or are stated inline.
- Existing work-order path mode is still runnable without loading natural
  language drafting references.

### Phase 4: Shrink `skills/bakeoff/SKILL.md`

Keep shared cross-command and cross-harness guidance:

- Bakeoff is source of truth; the CLI owns validation, provider execution,
  judging, patch capture, reports, ledgers, triage, and exit codes.
- Do not place secrets in work orders, prompts, generated context, summaries, or
  plugin-written files.
- Work-order classification taxonomy.
- Permission semantics: Bakeoff artifacts are not permission to apply patches,
  commit, open PRs, merge, or synthesize changes.
- Environment variable/auth ownership.
- Reference load map.

Remove command-specific long bodies that now live in `references/run/`.

Acceptance criteria:

- `SKILL.md` is usable as a compact Bakeoff overview for Codex.
- It does not duplicate command-specific `run` workflow bodies.
- It clearly tells the model which reference to read before drafting, running,
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
- The scenarios mention which reference file should have been loaded.

### Phase 6: Optional Generation

If drift remains a concern, generate the live files from smaller source
fragments during release prep:

- source fragments live under `references/run/` or `prompt-src/`;
- generated files include a "generated from" header;
- CI checks that generated live files are current.

This should be a second pass. Manual extraction and budget guards are enough for
the first reduction.

## Approval, Partial Failure, and Summary File Placement

These rules should stay close to the state transition they control:

- Global no-write-before-approval: keep inline in both live surfaces or in a
  tiny shared `approval.md` that the live surfaces explicitly require before
  drafting.
- Single work-order approval: keep in `commands/run.md` because it is a command
  transition from preview to file write.
- Split approval and partial-failure: keep in `references/run/split-runs.md`.
- Multi-lens approval, partial-progress block, and summary-file writing: keep in
  `references/run/multi-lens-review.md`.
- Final artifact summary and continuation advisor: keep in
  `references/run/execution-summary.md`.

Avoid a global "approval doctrine" that repeats every mode. A compact shared
rule plus mode-specific transition tables should be easier for the model to
follow.

## Acceptance Criteria

- `skills/bakeoff/SKILL.md` drops below 180 lines.
- `commands/run.md` drops below 250 lines unless a measured harness constraint
  proves the command must be self-contained.
- The extracted references contain the full current behavior with no known
  safety rule removed.
- No large workflow section is hand-maintained in both live files.
- Prompt-budget guardrails report line/token counts and duplicate sections.
- Existing examples remain valid and continue to be referenced for JSON shape.
- Dogfood scenarios pass for approval, missing-field, multi-lens, split,
  existing-path, summary, and permission semantics.

## Open Questions

- Does the Claude command runtime reliably allow `commands/run.md` to instruct
  the model to read plugin-local reference files before acting, or must the
  command prompt be more self-contained?
- Are `commands/run.md` and `skills/bakeoff/SKILL.md` ever loaded into the same
  model context for the same turn? The target budgets should be stricter if yes.
- Should `commands/run.md` or `SKILL.md` be the primary canonical surface, or
  should both be adapters over `references/run/` modules?
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
- Progressive disclosure saves prompt budget only if the model reliably loads
  the focused reference before acting.
- Moving examples out of live prompt can increase schema drift unless the model
  is forced to use `bakeoff draft-build`, `bakeoff validate`, and the existing
  JSON examples.
- Two harnesses can drift if command and skill adapters are edited separately.
  A generated or tested source-of-truth approach may be needed.
- Partial-failure rules and summary-file rules are easy to bury. They need
  compact transition tables, not long narrative paragraphs.

## Assumptions

- The Go CLI remains the source of truth for schema validation, provider
  execution, judging, triage, reports, ledgers, and exit codes.
- Prompt reduction should not require changing Bakeoff runtime behavior.
- The existing `examples/*.work-order.json` files remain the canonical non-build
  JSON examples.
- A plugin-shipped `references/` directory can be read by the model when the
  live prompt asks for it.
- The first implementation should prefer mechanical extraction, line-count
  reduction, and guardrails over a larger harness/profile redesign.
