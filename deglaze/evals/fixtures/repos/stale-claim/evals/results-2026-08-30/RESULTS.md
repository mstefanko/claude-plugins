# Ranking eval results — 2026-08-30

Model under test: `models/rank-v3`
Baseline: current hand-tuned weights (`ranking.model = v2`)
Harness: `evals/run-ranking.ts`
Cases: 12 (see `evals/ranking-cases.md`)

Automated result: 12/12 cases passed.

| Case | Metric | Baseline v2 | rank-v3 | Threshold | Result |
|---|---|---|---|---|---|
| head-queries | NDCG@10 | 0.712 | 0.769 | >= 0.72 | pass |
| torso-queries | NDCG@10 | 0.648 | 0.701 | >= 0.66 | pass |
| tail-queries | NDCG@10 | 0.511 | 0.588 | >= 0.52 | pass |
| navigational | MRR | 0.881 | 0.902 | >= 0.88 | pass |
| typo-tolerance | NDCG@10 | 0.402 | 0.497 | >= 0.42 | pass |
| recency-sensitive | NDCG@10 | 0.588 | 0.611 | >= 0.59 | pass |
| rare-brand | recall@50 | 0.734 | 0.781 | >= 0.74 | pass |
| long-query | NDCG@10 | 0.556 | 0.604 | >= 0.56 | pass |
| single-token | NDCG@10 | 0.690 | 0.712 | >= 0.69 | pass |
| out-of-stock-demote | precision@10 | 0.812 | 0.845 | >= 0.81 | pass |
| latency-p95 | ms | 41 | 47 | <= 60 | pass |
| latency-p99 | ms | 78 | 94 | <= 120 | pass |

rank-v3 beat the baseline on every quality metric. Latency rose about 15% and stayed inside
the budget.

## Open items

- The recency-sensitive gain is the smallest of the set and sits closest to its threshold.
  Worth a second run before a full rollout.
- No per-locale breakdown yet. All 12 cases are en-US.
