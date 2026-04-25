# Performance Review - review lens overlay

Apply the normal `agent-review` contract. Do not change the verdict vocabulary, section names, or no-edit rule.

Bias your review toward performance defects: N+1 behavior, unbounded loops, hot paths in new code, allocation in tight loops, blocking IO inside async paths, lock contention, cache invalidation, and unbounded data growth.

- For each item in `### Issues Found`, tag it `[N+1]`, `[O-N2]`, `[ALLOC]`, `[BLOCKING-IO]`, or `[CONTENTION]`.
- Name the input size, call frequency, or load pattern that triggers the concern.
- In `### Production Risk`, distinguish load-tested observable risk from asymptotic concern only.

Do not flag speculative performance issues without both file:line evidence and a concrete trigger.
