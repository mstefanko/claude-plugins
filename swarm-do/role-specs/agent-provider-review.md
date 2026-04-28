---
name: agent-provider-review
description: Provider-review coordinator helper. Owns the bin/swarm-provider-review and bin/swarm-stage-mco invocation surface. Consumed by the provider-review CLI path, not by Claude Code's native subagent loader.
consumers:
  - permissions
tools:
  - Bash(bin/swarm providers doctor:*)
  - Bash(bin/swarm providers evidence:*)
  - Bash(bin/swarm-provider-review:*)
  - Bash(claude --help:*)
  - Bash(claude --version:*)
  - Bash(claude -p:*)
  - Bash(claude auth status:*)
  - Bash(codex --version:*)
  - Bash(codex exec:*)
  - Bash(codex login status:*)
  - Bash(git diff:*)
  - Bash(git show:*)
  - Bash(rg:*)
  - Read
---

# Role: agent-provider-review

This role is consumed by the `bin/swarm-provider-review` and `bin/swarm-stage-mco`
helpers; it is **not** dispatched as a Claude Code subagent. The role-spec exists
so the deterministic permissions JSON stays in lockstep with all other roles
under the `python3 -m swarm_do.roles gen --write` generator.

For the actual provider-review prompt and orchestration contract, see
`py/swarm_do/pipeline/provider_review.py` and `bin/swarm-provider-review`.
