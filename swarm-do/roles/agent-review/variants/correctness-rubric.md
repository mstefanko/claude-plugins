# Correctness Rubric - review lens overlay

Apply the normal `agent-review` contract. Do not change the verdict vocabulary, section names, or no-edit rule.

Bias your review toward behavioral correctness: logic errors, invariants, state machines, contracts, and regression risks that tests may not cover.

- For each item in `### Issues Found`, prefix the file:line claim with `[LOGIC]`, `[CONTRACT]`, `[INVARIANT]`, or `[STATE-MACHINE]`.
- Prefer findings that name the violated invariant and the execution path that reaches it.
- In `### Production Risk`, call out the most likely production failure mode if the issue ships.

Drop any concern that cannot be grounded in a specific file:line and runtime path.
