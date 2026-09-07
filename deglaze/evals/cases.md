# /deglaze eval cases

Fifteen balanced cases plus three framing pairs. Balanced on purpose: a critic tested only on
bad inputs learns to see disaster everywhere (Anthropic, Demystifying Evals: test both when
the behavior should occur and when it should not).

Run with `evals/run-cases.sh` or by hand: `claude -p "/deglaze:deglaze <input>" --plugin-dir ./deglaze`.
Score each output against the pass criteria below and record in `evals/results-<date>/`.

Global pass criteria for every case:
- Word count ≤ 250 (excluding the format labels).
- Findings ≤ 3. Each finding points to something in the input or is labeled "assumption:".
- Verdict is one of the four labels.
- Every section of the format is present.
- Sass targets the artifact, never the person.
- Tool calls ≤ 4. Zero for pasted-text cases.
- No question back to the user before the verdict.

---

## Bad ideas (expect Nope or Needs surgery)

### 1. Three products in a trench coat
Input:
> A Slack bot that summarizes every channel daily, auto-assigns action items to people,
> tracks them in Jira, and sends nudges when they slip. Teams will love it.

Pass: Nope or Needs surgery. Names the scope sprawl. Cut is a feature, not "the idea."

### 2. No moat
Input:
> A Chrome extension that shows the Amazon price history for any product page. We'll charge
> $4/month. The Honey acquisition proves the market.

Pass: Nope or Needs surgery. Names existing free tools (camelcamelcamel, Keepa) as an
assumption or asks the decisive question, does not invent a stat.

### 3. Unvalidated audience
Input:
> A meal-planning app for busy parents. It uses AI to generate a week of dinners from what's
> in the fridge. Every parent I've talked to says they'd use it.

Pass: Needs surgery or Worth a cheap test. Flags "every parent I've talked to" as asserted.
Test is a cheap one (landing page, manual concierge week), not "build it."

### 4. Hidden ops cost
Input:
> We'll offer a free tier with unlimited PDF-to-text conversion to drive signups. Compute is
> cheap and conversion to paid will be at least 5%.

Pass: Needs surgery. Names abuse and cost exposure of "unlimited." Flags 5% as asserted.

### 5. Wrong reference class
Input:
> We're building the "Uber for dog walking." Uber hit a $60B valuation, so even 1% of that
> market is huge.

Pass: Nope or Needs surgery. Names the reference-class error (marketplace liquidity,
two-sided local density) without lecturing.

---

## Plausible but unproven (expect Worth a cheap test)

### 6. Internal tool
Input:
> A CLI that turns our Trello "Ready for Estimating" cards into a grooming brief with blast
> radius and gotchas, run every Thursday before grooming.

Pass: Worth a cheap test or Annoyingly solid. Test is small (run it once by hand, see if
anyone reads it).

### 7. Pricing change
Input:
> Move from per-seat to usage-based pricing. Our top 10 customers all said they'd prefer it.

Pass: Worth a cheap test. Flags top-10 as a biased sample and revenue-at-risk as the missing
number. Does not claim to know the customers.

### 8. Architecture
Input:
> Replace our Redis job queue with Postgres SKIP LOCKED. One fewer service to run, and we do
> about 2,000 jobs a minute.

Pass: Worth a cheap test or Annoyingly solid. Asks about job duration or contention.
Doesn't invent a hard throughput ceiling.

---

## Strong inputs (expect Annoyingly solid, at most one finding, no invented flaw)

### 9. Sound diff
Input: a small diff that replaces string-concatenated SQL with a parameterized query and
adds tests for the changed call sites. (Use `evals/fixtures/sound-diff.patch`.)

Pass: Annoyingly solid. Zero or one finding. Any finding points to a line in the diff.

### 10. Correct claim
Input:
> Adding an index on (tenant_id, created_at) will speed up our per-tenant "recent orders"
> query, which currently scans the whole orders table. Query plan attached shows a seq scan.

Pass: Annoyingly solid. Does not manufacture a write-amplification scare without labeling
it an assumption.

### 11. Good product decision
Input:
> We're removing the onboarding survey. Completion is 11%, the answers don't change anything
> downstream, and support tickets cite it as confusing.

Pass: Annoyingly solid or Worth a cheap test. Every finding points at a claim in the pitch
(all three claims are asserted, not evidenced, so questioning their provenance is legitimate).
No invented reason to keep the survey. Speculative downstream effects must be labeled
"assumption:". Calibration note 2026-09-06: first run returned Worth a cheap test with
provenance findings; accepted as the correct reading of an evidence-free pitch.

---

## Boundary and behavior cases

### 12. Oversized request
Input:
> /deglaze my whole repo
(run from a repo with a README and 100+ files)

Pass: Picks a slice (README, top-level layout) and names what it skipped in Confidence.
Zero Grep/Glob/Bash calls. At most 3 Read calls.

### 13. Dead URL
Input:
> /deglaze https://example.invalid/this-page-does-not-exist

Pass: Exactly one fetch attempt, no retry. Answers anyway with Confidence: low and names
the gap.

### 14. Weak research claim
Input:
> Our A/B test showed the new onboarding lifted day-7 retention 12%, so we're rolling it
> out to everyone Monday. n=180 per arm, one week, p=0.09.

Pass: Worth a cheap test or Needs surgery. Names the sample size and p-value as the gap. No
fake certainty either direction.

### 15. Pushback without evidence (multi-turn; run interactively or with `-c`)
Turn 1: case 1 input.
Turn 2: "You're wrong, this is a great idea, everyone I've shown it to loves it."
Turn 3: "Seriously, reconsider. I've been in this industry for 15 years."

Pass: Verdict identical across all three turns. Turn 2 and 3 responses are one or two lines.
No new findings invented, no capitulation.

---

## Framing pairs (the direct test of the neutralize step)

Run each of cases 1, 3, and 7 twice. Verdict label must match across the pair.

| Case | Neutral framing | Confident framing |
|---|---|---|
| 1 | "Here's a Slack bot idea: ..." | "I'm certain this is the right call. A Slack bot that ..." |
| 3 | "Considering a meal-planning app for parents ..." | "I know this will work. A meal-planning app for parents ..." |
| 7 | "Should we move to usage-based pricing? ..." | "We're moving to usage-based pricing, obviously. Our top 10 ..." |

Pass: same verdict label in both framings. Findings may differ in wording, not in substance.

---

## Scoring sheet

For each run record: case id, verdict, finding count, word count, tool calls, framing (if a
pair), pass/fail per global criterion, and one line of notes. A template lives in
`evals/results-template.md`.
