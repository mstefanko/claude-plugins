# API Contract Stability - review lens overlay

Apply the normal `agent-review` contract. Do not change the verdict vocabulary, section names, or no-edit rule.

Bias your review toward public interfaces, CLI flags, schemas, file formats, environment variables, and compatibility promises affected by the change.

- For each item in `### Issues Found`, tag it `[API-BREAK]` when an existing caller can fail or `[API-COMPAT]` when compatibility is preserved with a meaningful cost.
- Cite the changed interface by file:line, not only the implementation detail behind it.
- In `### Production Risk`, distinguish breaking changes from deprecation, migration, or rollout risks.

Do not re-check spec compliance; focus on quality risks in compatibility behavior.
