# Review Kit

Review Kit is a thin, skill-driven review coordinator. It assembles curated
context for a code diff, implementation plan, or implementation-vs-plan drift
pass; fences user intent from defect review; chooses single-agent vs. swarm
routing; writes a review-plan artifact; and delegates ledgered multi-agent
execution to bakeoff when the route calls for it.

Primary command:

```bash
/review-kit:review [base-ref|plan-path] [--mode auto|single|focused-swarm|swarm|chunked-swarm] [--approved-plan path]
```

The command is read-only/output-only by default. It does not create branches,
PRs, commits, GitHub comments, implementation plans, or code changes. It writes
`approved-plan.md` only after the user explicitly approves or selects a
reviewed plan as the implementation baseline.

Provenance (bundled under `docs/`):

- Plan: `docs/07-plugin-implementation-plan.md`
- Single-agent prompt: `docs/prompts/01-single-agent-routine.md`
- Swarm prompt: `docs/prompts/02-swarm-multi-lens.md`
- Bakeoff recommendation: `docs/prompts/03-bakeoff-gap-analysis.md`

These were synthesized in the `myorthomd-web` code-review research directory and copied here so the plugin is self-contained.
