# Review Kit

Review Kit is a thin, skill-driven code-review coordinator. It assembles curated context for a diff, fences user intent from defect review, chooses single-agent vs. swarm routing, writes a review-plan artifact, and delegates ledgered multi-agent execution to bakeoff when the route calls for it.

Primary command:

```bash
/review-kit:review [base-ref] [--mode auto|single|focused-swarm|swarm|chunked-swarm]
```

The command is read-only/output-only by default. It does not create branches, PRs, commits, GitHub comments, or implementation plans.

Provenance:

- Plan: `/Users/mstefanko/myorthomd-web/docs/code-review-research/07-plugin-implementation-plan.md`
- Single-agent prompt: `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/01-single-agent-routine.md`
- Swarm prompt: `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/02-swarm-multi-lens.md`
- Bakeoff recommendation: `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/03-bakeoff-gap-analysis.md`
