# Task-Fit Mechanical Prompt Repair Plan

Date: 2026-05-21

Status: tightened implementation plan with external-pattern review

## Recommendation

Tighten the task-fit improvement to one narrow behavior: when a request is
mostly deterministic evidence extraction plus thin interpretation, warn that
Bakeoff is probably low-value and show one or two labeled higher-value Bakeoff
rewrites.

Keep the existing generic task-fit warning for other weak-fit cases. The repair
menu is an alternate warning shape only for deterministic-evidence weak-fit
prompts, not a global replacement for every task-fit warning.

Do not add a new CLI flag, a Go-side classifier, or a second reserved phrase.
`draft anyway` remains the only literal phrase that clears the task-fit warning
for the current turn. That is a Bakeoff-local UX constraint, not an externally
validated plugin pattern.

## Validated Corrections From Review

- **Alternate deterministic-evidence warning only.** The prior draft conflicted
  with itself by saying to replace the current warning shape in one section and
  append to it in another. This plan adds a mirrored alternate warning shape for
  deterministic-evidence weak-fit prompts only; the existing generic warning
  remains for other weak-fit categories.
- **No `answer inline` magic string.** The current contract already allows an
  inline answer only when the user explicitly abandons Bakeoff. This plan does
  not introduce another reserved reply parallel to `draft anyway`.
- **Only one new weak-fit category.** Missing build selectors, vague review/RCA,
  and compare-without-criteria are already covered by the existing task-fit and
  required-field rules. The new category is mechanical evidence plus thin
  interpretation.
- **Mirror both contract files.** The same trigger and wording rules must land in
  `commands/run.md` and `skills/bakeoff/SKILL.md`; neither file should drift.
- **Multi-lens inherits task fit.** Multi-lens review already runs task fit
  before lens selection. If the request fails task fit, show the updated
  task-fit warning and do not ask for lenses yet.
- **No undefined narrowing phrase.** A user can pick a numbered rewrite, choose
  `draft anyway`, abandon Bakeoff in ordinary language, or provide any revised
  prompt. Do not require or document `narrow it to:` as a magic phrase.

## External Pattern Check

Do not rely on the failed `swarm-do` plugin as validation for this plan. A
follow-up search of external or non-`swarm-do` plugin material found enough
corroboration for the core principles:

- advisory warnings are preferable to blocking when fit is questionable;
- repair guidance should preserve user intent and avoid inventing requirements;
- if a grounded repair cannot be derived, ask a concrete clarification instead;
- deterministic lookups, exact searches, and small reads are weak fits for agent
  orchestration unless synthesis or decision value is added;
- suggested alternatives should be meaningfully distinct, with labels and
  tradeoffs, not cosmetic variants.

The exact `draft anyway` phrase, the one-or-two rewrite cap, selected-rewrite
follow-up handling, and mirrored contract wording remain Bakeoff-specific
contract choices.

## Problem

The current warning says the task may not need Bakeoff and asks the user to
continue or narrow. That is useful, but for deterministic comparison requests it
does not show the user what a stronger Bakeoff-shaped prompt would look like.

Example weak prompt:

```text
/bakeoff:run compare https://github.com/pcvelz/superpowers and https://github.com/obra/superpowers, how much has changed in the fork and what is the difference
```

The "how much changed" part is a mechanical fork diff: fetch both repos, pin
commit SHAs, find the divergence point, run `git log`, and run `git diff
--stat`. Two providers are likely to duplicate that evidence. Bakeoff becomes
useful only when the user adds an interpretive lens where independent readers
may disagree: behavior impact, upstreamability, risk, maintenance cost, or
regression exposure.

## Trigger

Add this weak-fit case to both task-fit weak-case lists:

```text
- deterministic evidence extraction plus thin interpretation, such as comparing
  two forks, counting changed files or commits, summarizing a diffstat, or
  asking "what changed" when one command pass can produce the evidence.
```

Do not warn solely because a task is small or straightforward. Warn only when
the likely answer is stable fact listing, counting, or diffstat-style evidence
from one obvious evidence path and the user has not provided a decision lens.
If the prompt includes criteria where independent readers may reasonably
disagree, such as behavior impact, compatibility risk, maintainability, or
upstreamability, draft normally.

## Wording Shape

For deterministic-evidence weak-fit prompts only, use this compact alternate
warning shape:

```text
This may not need Bakeoff because <reason>. A direct one-pass answer would
<direct evidence path>; do that outside Bakeoff if that is all you need.

If you still want Bakeoff, reply `draft anyway`.

Better Bakeoff shapes:
1. <label> - fixes <missing lens or decision>. Goal: <goal>. Output: <evidence/output shape>.
2. <label> - fixes <missing lens or decision>. Goal: <goal>. Output: <evidence/output shape>.
```

Rules:

- Show one or two rewrites by default. A third rewrite is allowed only when it is
  clearly distinct and still keeps the warning compact.
- Each rewrite must state what it fixes, the revised goal, and the expected
  evidence or output shape.
- Rewrites may reshape the task for Bakeoff, but they must preserve the user's
  intent and must not invent missing requirements, repositories, criteria, or
  success measures.
- If the prompt is too thin to seed a concrete rewrite, do not invent options.
  Ask one targeted narrowing question instead.
- Do not perform the direct one-pass answer from inside `/bakeoff:run` unless
  the user explicitly abandons Bakeoff in ordinary language.
- Do not emit a second repair menu for the immediate follow-up. If the user picks
  a rewrite by number/label or supplies a revised prompt, re-run task fit on that
  revised prompt and proceed normally if it passes. If it still fails task fit or
  required fields, ask one targeted clarification rather than showing another
  repair menu.
- Number and label replies are local selections from the displayed menu, not new
  reserved phrases.

## Real Use Case

Recommended response for the fork-diff prompt:

```text
This may not need Bakeoff because "how much changed" is a deterministic fork
diff: fetch both repos, pin commit SHAs, find the divergence point, run git log,
and run git diff --stat. Two providers would likely duplicate that evidence. A
direct one-pass answer would report commit counts, changed file groups, and a
short summary; do that outside Bakeoff if that is all you need.

If you still want Bakeoff, reply `draft anyway`.

Better Bakeoff shapes:
1. Behavior impact - fixes the vague "what is different" lens. Goal: Analyze
   behavioral changes in the fork's prompt or loop logic versus upstream.
   Output: cited commit/file summary plus behavior and regression notes.
2. Upstreamability - fixes the missing decision. Goal: Assess whether the fork's
   changes are safe to upstream and how to chunk them. Output: cited change
   groups, blockers, and suggested PR slices.
```

This keeps the warning short, preserves the existing `draft anyway` escape hatch,
and gives the user concrete higher-value prompts without creating a second magic
reply.

## Contract Changes

### `commands/run.md`

In `## Natural Language Drafting`:

- add the deterministic-evidence weak-fit bullet to the weak-case list;
- keep the current generic weak-fit wording for existing weak-fit categories;
- add the compact alternate wording shape above for deterministic-evidence
  weak-fit prompts only;
- add the wording rules above, including the one-turn repair-menu cap;
- keep the existing `draft anyway` semantics and inline-answer prohibition;
- state that mechanical repair guidance does not waive required build fields.

### `skills/bakeoff/SKILL.md`

Mirror the same trigger, compact alternate wording shape, and rules under
`## Task Fit And Clean Splits`. The skill file should not summarize or reinterpret
the command file differently, and it should preserve the generic warning for
other weak-fit cases.

### `docs/task-fit-test-scenarios.md`

Add three manual scenarios and leave existing scenarios intact:

1. **Remote fork diff gets mechanical prompt repair.**
   Prompt:
   `/bakeoff:run compare https://github.com/pcvelz/superpowers and https://github.com/obra/superpowers, how much has changed in the fork and what is the difference`

   Expect:
   task-fit warning; reason names deterministic fork diff evidence; no work order
   is drafted; `draft anyway` is preserved; one or two labeled rewrites identify
   what they fix plus goal and output shape.

2. **Selecting a repair option becomes the narrowed prompt.**
   Prompt:
   same warning, then user replies `1` or `Behavior impact`.

   Expect:
   plugin treats the selected rewrite as the revised natural-language request,
   re-runs task fit once, and proceeds to normal preview approval if it passes.
   It does not show another repair menu for the immediate follow-up.

3. **Interpretive compare with criteria drafts normally.**
   Prompt:
   `/bakeoff:run compare https://github.com/pcvelz/superpowers and https://github.com/obra/superpowers for behavior impact, regression risk, and upstreamability`

   Expect:
   plugin treats the request as a Bakeoff-shaped compare because the user
   provided decision criteria where independent readers may disagree. It drafts a
   normal preview rather than showing the deterministic-evidence repair menu.

Do not add a separate scenario for `draft anyway` preserving missing build fields;
that behavior is already covered by the existing checklist.

## Acceptance Criteria

- The implemented change touches only prompt/docs surfaces: `commands/run.md`,
  `skills/bakeoff/SKILL.md`, and `docs/task-fit-test-scenarios.md`.
- The deterministic-evidence alternate warning wording is added consistently in
  both contract files; the generic weak-fit warning remains in place for other
  weak-fit categories.
- `draft anyway` remains the only reserved task-fit opt-out phrase.
- The implementation does not introduce `answer inline` or any other new magic
  reply.
- The deterministic fork-diff prompt above warns instead of drafting.
- The warning contains no more than two default rewrites, unless a third is
  clearly distinct and compact.
- Each rewrite is labeled and includes what it fixes, a revised goal, and an
  output or evidence shape.
- Each rewrite preserves the user's stated intent and does not invent missing
  requirements, repositories, criteria, or success measures.
- When the prompt is too vague to ground a rewrite, the plugin asks one targeted
  narrowing question instead of inventing options.
- A selected rewrite is treated as a narrowed prompt and does not trigger a
  second repair menu in the immediate next turn.
- An interpretive compare with explicit criteria drafts normally and does not
  trigger the deterministic-evidence repair menu.
- Multi-lens review continues to run task fit before lens selection and inherits
  the updated warning when task fit fails.
- Existing task-fit, required-field, split, and multi-lens checklist rows remain
  present; the new scenarios are additive.
- No Go CLI tests are required for this prompt-only change.

## Non-Goals

- No Go-side classifier or validation rule.
- No `--skip-fit-check` flag.
- No persistent "never warn me again" preference.
- No new reserved reply phrase beyond `draft anyway`.
- No broad prompt-repair framework for every weak-fit category.
- No automatic direct answer from a task-fit warning.

## Risks

- **Warning fatigue:** long repair menus can make users reflexively type
  `draft anyway`. Mitigation: cap default rewrites at two and drop the repeated
  rubric paragraph.
- **Over-warning legitimate compare tasks:** "what changed" can be mechanical,
  but compare prompts with behavior, risk, maintainability, or upstreamability
  criteria are valid Bakeoff work. Mitigation: bias toward drafting when the user
  supplies a decision lens.
- **Scope creep into direct work:** direct one-pass answers may require cloning or
  diffing remote repos. Mitigation: recommend that path only as outside-Bakeoff
  work, and do not perform it until the user explicitly abandons Bakeoff.
- **Contract drift:** prompt-only behavior can diverge between command and skill
  files. Mitigation: require mirrored wording and additive manual scenarios.
- **Invented rewrites:** a thin prompt may not support useful alternatives.
  Mitigation: ask one targeted narrowing question instead of filling two slots.

## Implementation Order

1. Update `commands/run.md`.
2. Mirror the same wording in `skills/bakeoff/SKILL.md`.
3. Add the three manual scenarios to `docs/task-fit-test-scenarios.md`.
4. Dogfood the fork-diff prompt and the interpretive-compare prompt, then trim
   the wording if the repair warning exceeds the compact shape above.
