# deglaze

Claude Code plugin that gives a blunt, sassy, evidence-grounded second opinion on
one thing. An idea, a decision, a claim, a pasted diff, a screen, a paper abstract,
a URL, or up to three named files.

Single pass. Under 250 words. At most three findings. No subagents, no research,
no repo sweeps, no edits. It runs only when you type it.

The name: "glazing" is slang for laying on the praise. This strips it off.

## Install

```
/plugin install deglaze@mstefanko-plugins
```

## Usage

```
/deglaze A Slack bot that summarizes every channel daily and auto-assigns action items.
/deglaze src/billing/invoice.ts src/billing/invoice.test.ts
/deglaze https://example.com/blog/why-we-rewrote-everything-in-rust
/deglaze <paste a diff>
/deglaze            (deglazes the last thing you shared in the conversation)
```

If `/deglaze` collides with another command, use `/deglaze:deglaze`.

## Output

```
Verdict: [Nope | Needs surgery | Worth a cheap test | Annoyingly solid] — one blunt sentence
Not wrong about: the strongest thing it gets right
What's wobbling: 1–3 real issues, each pointing at where it lives in the input
Cut first: one thing to remove
Prove me wrong: one cheap experiment or decisive question
Confidence: low | medium | high — what evidence is missing
```

## Why it is built this way

The analysis is adversarial and balanced. Only the delivery is sassy. A critic told to
"find flaws" manufactures them (Huang et al. 2023; OpenAI CriticGPT 2024), so:

- The pitch is first rewritten as neutral questions, which cuts sycophancy more than
  telling the model not to be sycophantic (Dubois et al., UK AISI, 2026).
- It must name one genuine strength before any finding (steelmanning).
- It runs a pre-mortem ("six months later it failed, why?"), which raises correct
  cause-finding by roughly 30% (Mitchell, Russo & Pennington 1989).
- It drafts a verdict, argues against it, then revises (Herzog & Hertwig 2009).
- Every defect must point to a location in the input or be labeled an assumption.
- "Annoyingly solid" is a first-class verdict. There is no finding quota.
- Jokes live in the verdict line and finding headers only, because humor lowers
  perceived credibility when it sits where evidence should (Nabi et al. 2007).
- It holds its verdict under pushback unless you bring new evidence (Sharma et al. 2023).

Full rationale, citations, and decisions: `../plans/deglaze-skill-plan.md`.

## Guardrails

- `disable-model-invocation: true` so Claude never deglazes something that merely walked
  past the conversation.
- `disallowed-tools` removes Agent, Bash, Edit, Write, Grep, Glob, and planning tools
  from the pool while the skill is active. Read and URL fetch stay, rationed by
  instruction to 4 calls, 2 sources, no retries.
- `effort: medium`. Speed comes from the word cap and tool ban, not from thinking less.

## Evals

`evals/cases.md` holds 15 balanced cases plus 3 confident-vs-neutral framing pairs.
`evals/run-cases.sh` runs them headless with `--plugin-dir` and writes results to
`evals/results-<date>/`. Score by hand against the pass criteria in `cases.md`.

Claude Code-only frontmatter fields are used, so this skill is not uploadable to
claude.ai as-is. A spec-only variant is a possible follow-up.
