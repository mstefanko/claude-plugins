# Pre-Drafting Missing-Field Exploration Plan

Date: 2026-05-20

Status: proposed implementation plan

## Goal

Improve the `/bakeoff:run` pre-drafting UX when a build request is missing
fields that may be discoverable from the local repository.

The current contract correctly avoids silently inventing build verifier
commands, edit boundaries, acceptance criteria, and protected benchmark paths.
That protects run quality, but the user experience can overcorrect into a
stopping point: the agent says it needs exact fields, even when a read-only repo
pass could likely identify the right test package, file boundary, or existing
command convention.

The new behavior should preserve the anti-synthesis rule while adding a better
middle path:

```text
I will not guess, but I can inspect the repo once and bring back a concrete
proposal for you to approve.
```

## Recommendation

Replace the binary missing-field behavior with a three-way routing rule:

| Missing value is... | Drafting behavior |
| --- | --- |
| Explicit in the user's request | Draft normally. |
| Repo-discoverable with read-only context | Do one batched exploration pass, propose the value, then ask for approval before writing or running. |
| User-owned intent | Ask the user directly; do not explore as a substitute for the user's decision. |

This is a plugin-contract change first. Do not add a Go-side semantic linter or
a new CLI command in this pass. The existing enforced safety gates remain:

- no file write before approval;
- `bakeoff draft-build` for canonical build JSON when fields are known;
- on-disk `bakeoff validate` before provider execution.

## Problem

The screenshot flow exposed a UX gap:

1. The user asked for a build run that named a plausible target:
   `bakeoff ls ordering by finished_at descending`.
2. The agent spotted a prior duplicate run and asked for confirmation.
3. The user replied `draft anyway`, matching the existing task-fit continuation
   phrase.
4. The agent dismissed the duplicate warning, but then hard-stopped on missing
   required build fields:
   - exact verifier command;
   - edit boundary.

That is safe, but awkward. The user already gave permission to continue past the
duplicate warning. At that point the best next step is not to force the user to
remember package/test layout. It is to inspect the repo read-only, infer a
candidate from evidence, and ask the user to approve or edit that candidate.

## Product Contract

### 1. Keep Required Fields Required

This plan does not make verifier commands, edit boundaries, or acceptance
criteria optional.

A valid build draft still needs:

- implementation goal;
- observable acceptance criteria;
- at least one gate verifier command;
- explicit edit boundary;
- protected paths when an official metric verifier depends on repo fixtures,
  goldens, or benchmark harnesses;
- non-`HEAD` base ref when the user names one.

### 2. Distinguish Guessing From Evidence-Based Proposal

The contract should explicitly separate these cases:

- **Silent synthesis:** the agent fills a missing field and drafts as if the
  user supplied it. This remains discouraged.
- **Evidence-based proposal:** the agent performs one read-only, batched repo
  pass, names the evidence it found, proposes a field value, and waits for
  approval before writing or running. This is the desired new behavior.
- **User-owned decision:** the agent asks the user because repo inspection
  cannot decide the value.

The proposed verifier or scope may be passed to `bakeoff draft-build` to
generate a read-only preview after the proposal has been surfaced. The eventual
write/run still waits for the normal explicit approval.

### 3. `draft anyway` Only Clears The Warning

The phrase `draft anyway` should not waive required fields. It should only
acknowledge the task-fit or duplicate-work warning for the current turn. Do not
introduce a second continuation phrase in this plan.

After that acknowledgement, the agent should continue the normal drafting
state machine. If missing fields are discoverable, the next step is exploration.
If they are user-owned, the next step is a direct question.

### 4. Exploration Is Narrowly Targeted

One batched pass limits round trips, not output volume. The contract should say
that repo exploration must be narrowly targeted, read-only, and scoped to the
missing drafting facts. The agent should search for package/test layout,
existing work orders, relevant command code, Make targets, benchmark harnesses,
and nearby fixtures. It should not dump broad file contents, full diffs, large
logs, generated artifacts, or unrelated search results into the transcript.

## Discoverability Matrix

| Field | Explore first? | Rationale |
| --- | --- | --- |
| Build gate verifier command | Yes, when target package/file/test area is named or strongly implied. | The repo can reveal package layout, existing tests, Make targets, or prior work orders. Exploration may propose a command, but approval still finalizes it. |
| Edit boundary | Yes, when the goal names a command, package, route, file, or feature area. | File/package ownership is often discoverable from names and nearby tests. |
| Acceptance criteria | Usually no. | AC describes desired behavior and product intent. Repo context can refine wording, but should not replace user intent unless the request already states observable behavior. |
| Refactor invariants | No by default. | The user knows which behavior must remain byte-identical, API-compatible, or exit-code-compatible. Existing tests can be examples, not the whole contract. |
| Metric protected paths | Yes, when a benchmark/harness/fixture path is named or findable from an explicit metric request. | The measuring stick is often a concrete file set. If the benchmark itself is vague, ask. |
| Non-`HEAD` base ref | Ask. | Repo inspection cannot know which base the user intends when it is ambiguous. |
| Scope involving secrets, auth, or external web | Ask or reject per existing rules. | Exploration must not gather secrets or depend on provider auth material. |

## User-Visible Flow

### Duplicate Plus Discoverable Missing Fields

When a duplicate warning was acknowledged and the remaining missing fields look
repo-discoverable:

```text
Got it - continuing with Bakeoff.

I still need a valid build contract before drafting. I can do one read-only repo
pass to propose the verifier and edit boundary, then you can approve or edit
them before anything is written.

I'll inspect package/test layout now.
```

Then run one batched context pass. After exploration:

```text
I found `internal/commands/lscmd` and focused ls command tests nearby.

Proposed build fields:
- Verifier: `go test ./internal/commands/lscmd/... -run TestLs -count=1`
- Edit boundary: `internal/commands/lscmd` and its tests

Proposal is not approval: I'll use these only in the preview, then wait for
your explicit write/run approval before creating the work-order file.
```

Then show the normal compact preview and approval prompt.

### Discoverable But Ambiguous

If exploration finds multiple plausible commands or scopes:

```text
I found two plausible verifier scopes:
- `go test ./internal/commands/lscmd/... -run TestLs -count=1`
- `go test ./internal/commands/... -run TestLs -count=1`

Which verifier should this work order use?
```

Do not draft until the user chooses.

### User-Owned Missing Intent

When the missing value is acceptance criteria or refactor invariants:

```text
I can inspect the repo for relevant tests, but I still need the behavior you
want preserved. What observable invariant should the providers optimize for?
Examples: output order, exit-code mapping, JSON field stability, byte-identical
formatting, or a named test file.
```

## Contract Edits

Update these files together:

- `commands/run.md`
- `skills/bakeoff/SKILL.md`
- `docs/task-fit-test-scenarios.md`

Optional follow-up if the wording becomes load-bearing enough:

- `CLAUDE.md`

### `commands/run.md` And `skills/bakeoff/SKILL.md`

Use this literal replacement paragraph inside
`Required-Field Synthesis Guidance (Advisory)`, replacing the current sentence
"If a field is missing, ask rather than filling in a plausible default.":

```text
If a required field is missing, first classify it as explicit,
repo-discoverable, or user-owned. Do not silently fill a plausible default.
For repo-discoverable fields, perform one narrowly targeted, read-only batched
context pass, propose the value with evidence, and wait for normal preview
approval before writing or running. For user-owned fields, ask directly.
```

Add this paragraph immediately after the non-synthesizable field list:

```text
Repo-discoverable means the user's request names or strongly implies a target
whose verifier, edit boundary, or protected measuring files can be found by
read-only repository inspection. Exploration may inspect package/test layout,
existing work orders, relevant command code, Make targets, benchmark harnesses,
and nearby fixtures. It must not dump broad file contents, full diffs, large
logs, generated artifacts, or unrelated search results into the transcript.
User-owned means the value depends on product intent or desired behavior, such
as acceptance criteria, refactor invariants, ambiguous base refs, or secret/auth
material.
```

Replace the first mechanical-checklist item with this literal text:

```text
[ ] User named the verifier command verbatim?
    (Not "the conventional test command for X", not "the auth tests",
    not "the build". A real verifier is exact argv the user typed:
    `go test ./internal/foo/... -run . -count=1`, `make test`,
    `bundle exec rspec spec/auth_spec.rb`. If the answer is NO, the fast
    path does not apply. In the careful flow, if the request names or strongly
    implies a repo target, perform one narrowly targeted read-only batched
    context pass to propose a verifier with evidence; otherwise ask the user
    for the exact verifier.)
```

Add this paragraph after the checklist:

```text
Proposal is not approval. A verifier, edit boundary, or protected path found
during repo exploration may be used to generate a read-only preview, but it is
not a user-supplied field and does not authorize writing or running. Show the
proposal with evidence and wait for the normal approval phrase before creating
the work-order file.
```

Replace the fast-path fallback lead-in with this literal text:

```text
**Fast-path fallback rules.** Do not fast-path when any of these are true.
Take the careful drafting flow instead: explore once for repo-discoverable
missing fields, ask one targeted question for user-owned missing fields, and
stop when the missing value cannot be determined safely. Sequential repo probes
remain a failure of exploration discipline.
```

Add this sentence to the task-fit confirmation paragraph that currently says
task-fit confirmation does not waive required work-order fields:

```text
The phrase `draft anyway` only clears the task-fit or duplicate-work warning
for the current turn; it does not waive required build fields.
```

### `docs/task-fit-test-scenarios.md`

Add regression scenarios for:

1. Duplicate acknowledged, verifier/scope missing but discoverable.
   - Expect: after `draft anyway`, one narrowly targeted read-only exploration
     pass proposes verifier/scope; normal approval prompt follows; no write
     before approval.
2. Verifier target ambiguous after exploration.
   - Expect: ask the user to choose among plausible verifier/scope options; no
     draft.
3. Refactor missing behavioral invariants.
   - Expect: ask for invariants; repo exploration may offer examples but does
     not replace the ask.
4. Metric benchmark names harness but omits protected paths.
   - Expect: explore for protected paths, propose them, then preview.
5. Missing acceptance criteria with a named package.
   - Expect: ask for observable behavior; do not treat existing tests as AC.

## Implementation Steps

1. Edit `commands/run.md` to introduce the explicit/discoverable/user-owned
   routing model.
2. Mirror the same section structure and wording in `skills/bakeoff/SKILL.md`.
3. Add scenario rows to `docs/task-fit-test-scenarios.md`.
4. Run the source-vs-skill consistency check below for the changed sections.
5. Dogfood with fresh plugin cache after commit/push/reload, following the
   cache-pinning protocol from the drafting speed plan.
6. Record dogfood outcomes in either the drafting experiment log or a short
   follow-up note in this plan.

Definition of done for step 4:

```bash
mkdir -p /tmp/bakeoff-drafting-section-check
sed -n '/### Required-Field Synthesis Guidance (Advisory)/,/### No Write Before Approval/p' commands/run.md > /tmp/bakeoff-drafting-section-check/run.required-field.md
sed -n '/### Required-Field Synthesis Guidance (Advisory)/,/### No Write Before Approval/p' skills/bakeoff/SKILL.md > /tmp/bakeoff-drafting-section-check/skill.required-field.md
sed -n '/### Obvious One-Work-Order Fast Path/,/Full JSON remains available with `show` at any point./p' commands/run.md > /tmp/bakeoff-drafting-section-check/run.fast-path.md
sed -n '/### Obvious One-Work-Order Fast Path/,/Full JSON remains available with `show` at any point./p' skills/bakeoff/SKILL.md > /tmp/bakeoff-drafting-section-check/skill.fast-path.md
diff -u /tmp/bakeoff-drafting-section-check/run.required-field.md /tmp/bakeoff-drafting-section-check/skill.required-field.md
diff -u /tmp/bakeoff-drafting-section-check/run.fast-path.md /tmp/bakeoff-drafting-section-check/skill.fast-path.md
```

Pass condition: no semantic diff. Expected differences are limited to relative
link targets or neighboring headings that differ because `commands/run.md` and
`skills/bakeoff/SKILL.md` have different surrounding document structure.

## Dogfood Prompts

Use fresh sessions and verify the active plugin cache SHA before each batch.

### DME1: `draft anyway` With Discoverable Fields

Prompt:

```text
/bakeoff:run Implement bakeoff ls ordering by finished_at descending, with
stable fallback for legacy/malformed runs, and add focused tests.
```

Reply to the task-fit or duplicate warning:

```text
draft anyway
```

Expect:

- The warning is dismissed for the current turn only.
- Missing verifier/scope does not hard-stop immediately.
- Exactly one narrowly targeted read-only batched pass inspects `ls` command
  code, tests, and existing work-order history.
- The response proposes a verifier and edit boundary with evidence.
- The response includes "Proposal is not approval" or equivalent wording.
- No file write occurs before explicit approval.

### DME2: Refactor Invariants Still Ask

Prompt:

```text
/bakeoff:run Refactor default-value resolution in the build command. Keep the
existing verifier command if you can find it.
```

Expect:

- The agent may perform one narrowly targeted read-only batched pass to find a
  plausible verifier.
- The agent still asks for behavioral invariants before drafting.
- No AC is synthesized as "no behavior change" or "tests pass".
- No file write occurs before explicit approval.

### DME3: Ambiguous Verifier

Prompt:

```text
/bakeoff:run Fix the auth tests flaking in CI.
```

Expect:

- If multiple auth test packages or commands are plausible, the agent asks the
  user to choose.
- The agent does not draft with a broad invented verifier such as
  `go test ./...`.
- No file write occurs before explicit approval.

### DME4: Metric Protected Paths

Prompt:

```text
/bakeoff:run Optimize ledger import performance using the existing benchmark.
```

Expect:

- If a benchmark harness is discoverable, the agent proposes the metric command
  and protected harness/fixture paths.
- If no clear harness exists, the agent asks for the benchmark command and
  measuring-stick files.
- The agent does not draft a metric verifier without protected measuring files
  unless the user explicitly removes the metric requirement.
- No file write occurs before explicit approval.

## Acceptance Criteria

- The `draft anyway` acknowledgement no longer leads directly to a required-field
  dead end when missing fields are plausibly repo-discoverable.
- Repo-discoverable missing verifier/scope cases use at most one batched
  read/search pass before proposing values, and that pass is narrowly targeted
  to drafting facts.
- Proposed verifier/scope values are visibly tied to evidence and still require
  preview approval before write/run.
- User-owned fields, especially acceptance criteria and refactor invariants,
  are still asked directly.
- No scenario writes a work-order file before explicit approval.
- No scenario probes the Bakeoff CLI for schema/backend discovery.

## Risks

- The agent may treat exploration as permission to silently draft. Mitigation:
  repeat "proposal is not approval" in the contract and scenarios.
- The agent may explore too broadly or flood the transcript. Mitigation:
  preserve the single batched context pass rule, require the pass to be narrowly
  targeted and read-only, and forbid broad dumps of full files, full diffs, large
  logs, generated artifacts, or unrelated search results.
- The proposed verifier may be plausible but wrong. Mitigation: show evidence
  and ask approval; ask the user to choose when multiple plausible commands
  exist.
- More branching language could increase contract length. Mitigation: replace
  binary ask-only wording rather than adding another large mandatory marker.

## Non-Goals

- Do not make required build fields optional.
- Do not build a Go-side verifier/scope inference engine.
- Do not add a new work-order schema field for "proposed" values.
- Do not weaken no-write-before-approval.
- Do not let `draft anyway`, `yes`, or any duplicate-warning acknowledgement
  silently override missing user-owned acceptance criteria.
