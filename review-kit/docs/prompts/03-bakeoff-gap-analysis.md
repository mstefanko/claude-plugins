# Bakeoff Code-Review: Gap Analysis & Plugin Recommendation

Compares the existing **bakeoff** plugin's code-review flow against the two synthesized prompts
(`01-single-agent-routine.md`, `02-swarm-multi-lens.md`) and the research in this directory.

Bakeoff lives at `~/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/`. Relevant files:
- `internal/workorder/templates/review.work-order.json` — review facet (include/exclude lists)
- `internal/prompt/fixtures/worker-gather-{claude,codex}.txt` — the two reviewer prompts
- `internal/prompt/fixtures/judge-gather.txt` — dedup/judge prompt
- `internal/prompt/fixtures/escalation-gather-union.txt` — escalation judge
- `docs/multi-lens-review-swarm-implementation-plan-2026-05-21.md` — opt-in multi-lens

---

## How bakeoff reviews today

1. Drafts a `gather` work order with facet `code-review` (include/exclude lists).
2. Two reviewers run independently and **cross-family by default — Claude Sonnet + Codex GPT-5.5**.
3. Each emits `claims[]` with mandatory `file:line` evidence and `high|medium|low` confidence;
   "breadth over depth" (5–15 findings); out-of-scope items go to `recommended_next_checks`;
   workers are told NOT to synthesize/rank.
4. A judge (Opus) dedups, surfaces conflicts, unions — and treats provider output as untrusted data.
5. Opt-in multi-lens: separate work orders per lens. Escalation modes: witness / dispute / independent.

---

## What bakeoff ALREADY does right (matches our prompts/research)

| Best practice | Bakeoff status |
|---|---|
| Mandatory `file:line` citation (citation-or-drop) | ✅ enforced per claim |
| Confidence calibration (high/med/low + decision rules) | ✅ |
| Include/exclude rubric to prevent scope creep | ✅ in the facet |
| Multi-agent + dedicated judge/dedup pass | ✅ |
| **Cross-family reviewers (Claude + Codex)** | ✅ — and this is exactly what §C2 of the web scan endorses to break correlated-error bias |
| Untrusted-data handling (anti-injection) | ✅ at the judge |
| Out-of-scope triage instead of scope creep | ✅ `recommended_next_checks` |
| Conflict surfacing rather than forced consensus | ✅ |
| Breadth-over-depth coverage | ✅ |

Bakeoff is **closer to the swarm prompt than expected** — and its default cross-family setup is
ahead of our "same strong model" default for the *critic* role specifically.

## Gaps to close (bakeoff is missing these)

1. **No explicit severity scale.** It has *confidence* but not *severity* (blocker/high/medium/low).
   These are different axes (a low-confidence finding can be a blocker). Add a `severity` field.
2. **No intent isolation.** Workers receive user-supplied acceptance criteria / known risks mixed in.
   Our prompts split an **intent-blind defect/security pass** from a **separate conformance pass**, and
   treat the PR description as untrusted *at the worker level* (bakeoff only does this at the judge).
   This is the highest-value gap — report 02 measured 16–93 pt detection drops from intent framing.
3. **No kill-mandate refutation step by default.** The judge dedups but doesn't adversarially *disprove*.
   Bakeoff's `dispute` escalation is adjacent but opt-in and not cold-start/context-asymmetric.
4. **Judge can promote on agreement.** "Union synthesis" risks the consensus≠correctness failure.
   Add the gate: HIGH/blocker only with a concrete scenario the critic couldn't refute.
5. **Context is best-effort whole-codebase, not curated.** Workers can read the full repo → context-rot
   risk (report 03). Prefer changed files + immediate deps + *only-relevant* conventions.
6. **No size routing or chunking.** No single-vs-swarm switch by diff size; no cohesive-slice chunking
   or cross-chunk integration pass for large diffs (report 05).
7. **No confidence-drop gate** post-run (web scan §B2 — the reliable noise lever).

---

## Should this be its own plugin?

**Recommendation: yes — a thin "code-review" plugin that owns CONTEXT ASSEMBLY + PROMPT BUILDING +
ROUTING, and (optionally) hands execution to bakeoff.** Rationale:

- Bakeoff's job is **competitive provider comparison / bakeoffs**. It already executes cross-family
  reviewers + judge well. It is *not* designed to curate context or build a review prompt — it makes
  the user supply the diff/context.
- The thing the user actually wants — *"Claude helps build the prompt, pulling in just enough context
  without context rot"* — is precisely a **context-assembly + routing layer**, which is the central
  finding of reports 03 + 04 + 05 and is the one piece neither bakeoff nor the raw prompts provide.

What the new plugin would own (the differentiated value):
- **Context assembler:** from a branch/PR, gather the diff with line numbers, full changed files,
  immediate dependencies (callers/callees), and *only the relevant* conventions. In this repo it can
  lean on the `enovis-context` CLI to pull just the touched models' fields / routes / feature flags —
  high-signal, low-token, avoiding a CLAUDE.md dump.
- **Router:** pick `01-single-agent-routine` for small/medium PRs vs `02-swarm-multi-lens` for large/
  high-stakes; chunk large diffs by cohesive slice; add the cross-chunk integration pass.
- **Intent fencing:** auto-separate the diff-only defect pass from the conformance pass.
- **Prompt builder:** emit the filled prompt / work order. For multi-agent execution, **delegate to
  bakeoff** (reuse its proven cross-family + judge machinery) rather than reimplementing it.

In short: **don't fork bakeoff's executor — build the context/orchestration layer on top of it, and
backfill bakeoff's prompt gaps (#1–#4 above) so the delegated run is itself best-practice.**

### Two viable paths
- **A — Extend bakeoff only:** add severity, intent isolation, a refutation critic, and the consensus
  gate to bakeoff's fixtures. Cheapest. Leaves context-assembly and routing as a manual step.
- **B — New plugin over bakeoff (recommended):** new plugin does context assembly + routing + intent
  fencing + prompt building; delegates multi-agent execution to a bakeoff that has had gaps #1–#4
  backfilled. Delivers the "Claude builds the prompt with just-enough context" goal directly.
