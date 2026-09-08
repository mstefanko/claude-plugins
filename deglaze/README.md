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

The bare `/deglaze` also works when no other installed command claims that name.

## Output

```
Verdict: Nope | Needs surgery | Worth a cheap test | Annoyingly solid — one blunt sentence
Trying to do: what the target is trying to do, in its words
Keep: the strongest thing it gets right, or the technique worth keeping
Change: numbered findings, each with where it lives and why it matters
Risks: plausible but unconfirmed, omitted when there are none
Prove me wrong: one experiment, test, query, or decisive question
Confidence: what was read, what was skipped
```

## How it stays at the concept level

This is the part that makes it useful on a code change instead of annoying. Four layers:

- **No shell, no edits.** Bash, Edit, Write, subagents, and the planning tools are removed
  from the pool while the skill runs. Nothing executes, so micro-performance and lint
  complaints have no evidence to stand on.
- **The unit of review is a decision, not a file.** It first states what the change or plan
  is trying to do, and every finding has to attach to that sentence.
- **Four admission tests.** A finding must be statable in plain words without quoting code,
  must change an approach rather than a line, must survive an attempt to refute it against
  tests and callers, and must carry a complete evidence chain. Several small problems of one
  kind roll up into one pattern-level finding.
- **An exclusion list.** Style, naming, formatting, anything a linter catches, typos, import
  order, test counts, and pre-existing problems the change did not introduce are never
  findings.

Speculation is separated from defects. A claim about the artifact ("asserts this, shows
nothing") can be a finding. A claim about the world ("users will hate it") is a Risk at most.

## Budget

Words and tool calls scale with what it had to look at, not with how the request was phrased.

| Target | Words | Findings | Tool calls |
|---|---|---|---|
| Answered from the target alone | about 150, ceiling 250 | up to 3 | 0 |
| Needed to read files | about 400, ceiling 700 | up to 5 | up to 12, 8 files, 2 greps |

It reads the artifact and its direct dependencies only: callers of changed symbols, tests
for changed behavior, contracts and migrations it touches, and files a plan makes claims
about. It does not follow the graph further, does not browse for context, and never retries
a failed call. A repository is not a unit of review.

## Guardrails

- `disable-model-invocation: true`, so it only ever runs when you type it. It will not
  deglaze something that merely walked past in the conversation.
- `disallowed-tools` removes the shell, the editors, subagents, and the planning tools.
  Verified 2026-09-07: an attempt to use Bash is refused at the tool layer, not just
  discouraged by the prompt.
- Everything it reads is treated as data under review. Instructions embedded in a diff, a
  plan, or a fetched page ("approve this", "skip the validation section") are findings, not
  commands. Two eval cases cover this.
- It holds its verdict under pushback unless you bring new evidence, a constraint it missed,
  or reasoning that breaks a finding's evidence chain, and it says what changed its mind.

**Known limitation: the tool ban covers the invoking turn only.** Verified 2026-09-08. When
you reply in the same conversation and it answers your pushback, the skill is no longer
active, so `disallowed-tools` no longer applies and the shell is available again. The word
and finding ceilings stop binding too. If you need the guarantees, invoke it fresh rather
than continuing the thread.

## Design notes

The analysis is adversarial and balanced; only the delivery is sassy. A critic told to find
flaws will manufacture them, which is the failure mode these choices target:

- Claims are rewritten as neutral questions before evaluation.
- It must name the strongest thing the target gets right before any finding.
- Every candidate finding gets an attempted refutation, and only survivors are promoted.
- There is no finding quota. "Annoyingly solid" is a first-class verdict.
- Jokes are confined to the verdict line and finding openers, away from evidence.

Those choices are informed by human-subject research on premortems, dialectical
bootstrapping, steelmanning, and humor's effect on perceived credibility, plus published
work on LLM critics manufacturing false positives. Treat that literature as the design
hypothesis, not as validation of this workflow. The validation of *this* skill is the eval
set in `evals/`, which is where to look before trusting it on something that matters.

Design rationale and decisions live in the `plans/` folder of the marketplace repository.
They are not shipped with the installed plugin.

## Evals

```
bun evals/run.ts                       # 32 cases, 2 trials each
bun evals/run.ts --only R8 --trials 1  # the altitude canary
```

Each trial runs in an isolated temporary git repository and captures a full stream-json
trace, so tool calls, files read, and refused tools are all scoreable rather than inferred
from the rendered text. `evals/cases.md` explains the case groups, what the harness checks
automatically, what needs a human, and which cases cannot be automated and why.
