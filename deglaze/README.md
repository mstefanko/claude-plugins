# deglaze

Claude Code plugin that gives a blunt, evidence-grounded second opinion on one thing: an
idea, a claim, a response, a snippet, a URL, a code change, or an implementation plan.

It judges ideas, techniques, design decisions, invariants, failure paths, and validation.
It is not a line-by-line code reviewer. Lines are evidence, never the thing under review.

The name: "glazing" is slang for laying on praise the work did not earn. This strips it off.

## Install

```
/plugin install deglaze@mstefanko-plugins
```

## Usage

```
/deglaze:deglaze A Slack bot that summarizes every channel daily and auto-assigns action items.
/deglaze:deglaze docs/PLAN_SEARCH_INDEX.md
/deglaze:deglaze Review this change: src/api/orders.ts now returns null instead of [].
/deglaze:deglaze https://example.com/blog/why-we-rewrote-everything-in-rust
/deglaze:deglaze <paste a diff>
/deglaze:deglaze            (the last thing you shared, or your uncommitted work)
```

## Output

```
Verdict: Nope | Needs surgery | Worth a cheap test | Annoyingly solid — one blunt sentence
Trying to do: what the target is trying to do
Keep: the strongest thing it gets right
Change: numbered findings, each with where it lives and why it matters
Risks: plausible but unconfirmed, omitted when there are none
Prove me wrong: one experiment, test, query, or decisive question
Confidence: what was read, what was skipped, calls used
```

## How it stays at the concept level

- **No shell, no edits.** Bash, Edit, Write, subagents, and the planning tools are removed
  from the pool while the skill runs, so lint and micro-performance complaints have nothing
  to stand on.
- **The unit of review is a decision, not a file.** Every finding has to attach to one
  sentence about what the change or plan is trying to do.
- **Four admission tests.** A finding must be statable in plain words without quoting code,
  must change an approach rather than a line, must survive an attempt to refute it, and must
  carry a complete evidence chain.
- **An exclusion list.** Style, naming, formatting, typos, import order, test counts, and
  pre-existing problems the change did not introduce are never findings.

Speculation is separated from defects: a claim about the artifact can be a finding, a claim
about the world is a Risk at most. "Annoyingly solid" is a first-class verdict; there is no
finding quota.

## Budget

| Target | Words | Findings | Tool calls |
|---|---|---|---|
| Answered from the target alone | about 200, ceiling 320 | up to 3 | 0 |
| Needed to read files | about 400, ceiling 700 | up to 5 | up to 12, 8 files, 2 greps |

It reads the artifact and its direct dependencies only, never retries a failed call, and
treats a repository as not a unit of review.

## Guardrails

- `disable-model-invocation: true`: it only runs when you type it.
- `disallowed-tools` removes the shell, editors, subagents, and planning tools at the tool
  layer, not just in the prompt.
- Everything it reads is data under review. Instructions embedded in a diff, plan, or page
  ("approve this", "skip validation") become findings, not commands.
- It holds its verdict under pushback unless you bring new evidence, a missed constraint, or
  reasoning that breaks a finding's chain, and says what changed its mind.

**Known limitation:** the tool ban covers the invoking turn only. When you reply in the same
conversation, the skill is no longer active, so the shell is available again and the word
ceilings stop binding. Invoke it fresh if you need the guarantees.

## Evals

```
bun evals/run.ts                    # 24 cases, one run each
bun evals/run.ts --only R8,R14      # the altitude and zero-call canaries
```

Each case runs in a temp git repo and is scored from the stream-json trace, so tool calls,
files read, and refused tools are checked rather than inferred. `evals/cases.md` lists the
cases and what needs a human. Design notes live in the marketplace repo's `plans/` folder.
