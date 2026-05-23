# Agentic Code Review and Software-Writing Loops in 2026

Date: 2026-05-23

Status: research memo

## Executive Summary

The strongest 2026 pattern is not one coding agent writing code and approving
itself. It is a human-led loop with narrow scope, independent review, objective
verification, and explicit human merge judgment:

```text
human scopes -> planner researches -> writer implements -> writer self-checks
-> fresh reviewer audits -> specialist/cross-model escalation for risk
-> CI/verifiers run -> human merges
```

Multi-agent review is useful when the agents are genuinely independent or
scoped by concrete lenses. It is much less useful when several agents receive
the same broad prompt and produce overlapping prose. Self-review is useful as a
preflight, but it should not be treated as an independent quality gate.
Cross-model review is most worth the cost on high-risk changes, where different
model families may have different blind spots.

The practical recommendation for Bakeoff is to keep the default review path
small: two independent reviewers, one union/dedupe judge, and triage. Add
explicit escalation only when the run is high risk, surprising, incomplete, or
when a user asks to challenge the report.

## Evidence Summary

### AI Review Helps, But It Is Not Complete

The 2026 c-CRAB benchmark evaluates commercial and open-source code review
agents, including Claude Code and Codex. Its main implication for Bakeoff is
that automated reviewers find useful issues, but they do not replace human
review and they miss enough material that combining review with human judgment
remains necessary.

Source: [c-CRAB: A Challenging Code Review Agent Benchmark](https://arxiv.org/abs/2603.23448)

The 2026 Human-AI Synergy study of GitHub review conversations found that human
review comments still contribute substantially to understanding, testing, and
knowledge transfer, and that AI suggestions are not uniformly adopted. This
supports a workflow where AI review produces candidate findings and humans own
the final product and risk judgment.

Source: [Human-AI Synergy in Agentic Code Review](https://arxiv.org/abs/2603.15911)

### Context-Aware Industrial Review Can Reduce Cycle Time

Atlassian's RovoDev Code Reviewer report found meaningful operational wins from
a context-aware AI review system: 38.70% of AI comments led to code resolution,
PR cycle time dropped 30.8%, and human-written comments dropped 35.6%. The
important design lesson is that the system was not a raw single prompt. It used
context, review guidance, and quality controls.

Source: [RovoDev Code Reviewer](https://arxiv.org/abs/2601.01129)

### Multi-Agent and Multi-Lens Review Can Improve Coverage

Anthropic's Claude Code Review uses multiple agents over the diff and
surrounding code, then verifies, deduplicates, ranks severity, and posts inline
comments. That is a useful reference architecture: parallel review is paired
with verification and synthesis.

Source: [Claude Code Review docs](https://code.claude.com/docs/en/code-review)

Hydra-Reviewer, an FSE 2026 journal-first system, argues that automatic review
systems miss issues when they review from a single perspective. Its
multi-agent design is evidence for scoped perspectives improving review
coverage, especially when the perspectives map to review dimensions rather than
role-play personas.

Source: [Hydra-Reviewer](https://conf.researchr.org/details/fse-2026/fse-2026-journal-first/40/Hydra-Reviewer-A-holistic-multi-agent-system-for-automatic-code-review-comment-gener)

### Self-Review Is A Cheap Preflight, Not A Gate

A May 2026 paper on LLM code modernization found that producing models silently
endorsed a meaningful share of their own semantic-drift failures. The takeaway
is not that self-checking is useless. It is that self-review shares too many
blind spots with generation to serve as the final reviewer.

Source: [Articulate but Wrong](https://arxiv.org/abs/2605.21537)

### Fresh Context Matters

Anthropic's Claude Code best practices recommend separate writer and reviewer
sessions, and recommend subagents for post-implementation review and
verification. Fresh context is a practical bias-reduction mechanism: the
reviewer did not just author the code and does not have the same conversational
commitment to the path taken.

Source: [Claude Code best practices](https://code.claude.com/docs/en/best-practices)

### Explicit Instructions Improve Review Quality

GitHub Copilot Code Review emphasizes project context and custom instructions,
while still requiring human validation. Claude Code Review similarly supports
repository guidance through `CLAUDE.md` and review-specific `REVIEW.md`.

Sources:

- [GitHub Copilot Code Review](https://docs.github.com/en/copilot/concepts/agents/code-review)
- [Claude Code Review docs](https://code.claude.com/docs/en/code-review)

## Answers To The Original Questions

### Do Reviewer Swarms Help?

Yes, if "swarm" means separate, scoped reviewers whose findings are verified,
deduplicated, and ranked. No, if it means sending the same broad review prompt
to five agents and concatenating the output. The evidence supports
complementary perspectives and independent attempts. It does not support
unbounded fanout as a default product shape.

For Bakeoff, the right default remains small: two providers plus one judge. A
third provider should be an explicit escalation, not a normal work-order shape.

### Should The Builder Review Its Own Work?

Yes, as preflight:

- run tests, lint, typecheck, and any task-specific gates;
- summarize changed behavior;
- list assumptions and known gaps;
- identify risky areas for the next reviewer.

No, as the independent quality gate. The same model/session that created a bug
is often weak at falsifying the path that produced it.

### Does Cross-Model Review Help?

The strongest direct evidence is still thinner than the practice case. The
case for cross-model review is an inference from failure diversity, model
family differences, and self-review weakness. It is worth the cost for
security, auth, billing, migrations, concurrency, data loss, public APIs, and
large refactors.

For Bakeoff, cross-model review already appears in the default generated
review pair when Claude and Codex are used as the two providers. The stronger
high-risk form is post-run escalation with a third provider that did not
participate in the source run.

### Does Same-Model Review With Different Lenses Help?

Yes, when the lens is concrete and the context is fresh. "Act as a senior
reviewer" is weaker than a bounded facet such as:

- "authz bypass in admin routes";
- "migration reversibility and data-loss risk";
- "race conditions and idempotency";
- "public API compatibility";
- "test oracle strength."

The useful unit is a narrow review contract, not a persona.

### Can Models Choose The Right Scope?

They can suggest likely scopes, but humans should define important scopes for
high-risk work. Domain-specific risk is often invisible from the diff alone.
The most reliable setup is to encode recurring review concerns in persistent
instructions and let humans add one-off risk lenses when the task demands it.

For Bakeoff, the `facet` object is the right primitive: `focus`, `include`,
`exclude`, and optional notes.

## Recommended 2026 Software-Writing Loop

1. Human writes an issue-quality task: goal, non-goals, acceptance criteria,
   changed areas, risk areas, and expected verification.
2. Planner agent investigates the repo and proposes a plan without editing.
3. Human approves or edits the plan.
4. Writer agent implements in a branch or worktree.
5. Writer self-checks with tests, lint, typecheck, and a risk summary.
6. Fresh-context reviewer checks correctness, edge cases, repository fit, and
   test quality.
7. Specialist review runs only for justified risks: security, data, migrations,
   performance, accessibility, observability, release/rollback.
8. Cross-model or third-provider escalation runs for high-risk or surprising
   reviews.
9. CI and verifiers provide objective evidence.
10. Human reviews final diff, AI findings, residual risk, and merge readiness.

OpenAI's public Codex material describes this as a model-tool-observation loop:
the agent plans, acts, observes tool output, and iterates under constraints.
GitHub's cloud agent model follows a similar operational shape: research, plan,
branch, edit, test, and open a PR for human review.

Sources:

- [Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [GitHub Copilot cloud agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)

## Claude And Review Tooling Worth Considering

### Claude Code Review

Worth considering for managed PR review when cost is acceptable. It is
multi-agent, repository-context-aware, and designed around verification,
deduplication, and severity ranking. It is most useful on important PRs rather
than every small local diff.

Source: [Claude Code Review docs](https://code.claude.com/docs/en/code-review)

### Claude Subagents

Useful for project-specific review lenses such as security, migration safety,
performance, frontend accessibility, and test quality. The main value is fresh
context plus a persistent narrow prompt.

Source: [Claude subagents](https://docs.anthropic.com/en/docs/claude-code/sub-agents)

### Claude Plugins And PR Review Toolkits

The Claude plugin ecosystem can bundle commands, agents, skills, hooks, and
MCP servers. It is worth checking existing review plugins before building a
large local orchestration loop, because the commodity review surface is now
well covered.

Source: [Claude plugin discovery](https://code.claude.com/docs/en/discover-plugins)

### OpenAI Codex Plugin For Claude Code

Useful for cross-model review inside a Claude workflow. It exposes Codex review
and adversarial-review commands without forcing users to leave the Claude
environment.

Source: [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)

### GitHub Copilot Code Review

Useful when the team lives in GitHub and wants review directly in the PR
workflow. It should still be treated as candidate feedback that humans validate.

Source: [GitHub Copilot Code Review](https://docs.github.com/en/copilot/concepts/agents/code-review)

## Implications For Bakeoff

Bakeoff's current review model is well aligned with the evidence:

```text
same scope -> two independent reviews -> one combined finding list -> triage
```

The next improvement should not be a larger default swarm. It should be a small
post-run escalation path for high-risk or disputed reviews:

- `independent`: fresh third review to improve recall;
- `witness`: adversarial audit of the report and triage;
- `dispute`: narrow investigation of contested points.

The most useful product change is to make `witness` explicitly mean "fight the
report" for code-review runs, while keeping it advisory until triaged.
