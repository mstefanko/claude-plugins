# deglaze

A Claude Code plugin that gives you a blunt second opinion on one thing.

AI likes to tell you your idea is great. "Glazing" is slang for that kind of empty
praise. This plugin strips it off. Hand it an idea, a claim, a diff, a plan file, or a
URL, and it tells you what holds up, what doesn't, and how to find out for sure. It is
rude about the work and never about you, and it does not soften the verdict to be
polite.

## Install

```
/plugin install deglaze@mstefanko-plugins
```

## Use it

```
/deglaze:deglaze A Slack bot that summarizes every channel and assigns action items.
/deglaze:deglaze docs/PLAN_SEARCH_INDEX.md
/deglaze:deglaze <paste a diff>
/deglaze:deglaze https://example.com/some-blog-post
/deglaze:deglaze                         (the last thing you shared, or your uncommitted work)
/deglaze:deglaze docs/PLAN.md --md       (also save the review to a file)
```

## What you get back

```
Verdict: Nope | Needs surgery | Worth a cheap test | Annoyingly solid — one blunt sentence
Trying to do: what the thing is trying to do
Keep: the strongest part, worth keeping
Change: numbered problems, each with where it is and why it matters
Risks: things that might be wrong but aren't proven (skipped if none)
Prove me wrong: one test, query, or question that would settle it
Confidence: what it read, what it skipped
```

"Annoyingly solid" is a real answer. If nothing it found would change your decision,
it says so instead of inventing problems.

## How it thinks

- It judges ideas and decisions, not lines of code. Style, naming, and formatting are
  never findings.
- It has to name the best part before it names any problem.
- Every problem has to survive its own attempt to knock it down. Guesses about the
  world go under Risks, not Change.
- It cannot run commands, edit files, or start other agents. Those tools are switched
  off while it runs.
- If you paste something, it judges the paste and does not go looking for files. If you
  point it at a file or plan in your repo, it reads that and its direct neighbors, up to
  12 tool calls, and stops.
- Anything inside what it reviews is treated as data. A comment saying "reviewer, approve
  this" becomes a finding, not an instruction.

## Saving a review

Add `--md` and the review is also written to `.deglaze/<date>-<slug>.md` in your working
directory, with `Target:` and `Commit:` lines at the top. Open it in a later session next
to the plan or change it judged. Without the flag, nothing is written. Add `.deglaze/` to
your gitignore.

## Pushing back

Reply in the same conversation and it will hold its verdict unless you bring new
evidence or a missed constraint, and it will say what changed its mind. Once you reply,
the tool switches are off again, so start fresh if you need the guarantees.

## Checking it still works

```
bun evals/run.ts
```

Two headless cases, about two minutes: a pasted diff with deliberate style nits must get
zero style findings and zero tool calls, and a plan in a repo must be read, judged, and
saved with `--md`. Run it after editing the skill. Everything else you learn by using it.
