# Plan: roll out the new ranking model

Owner: search. Target: next week.

## 1. Goal

Replace the hand-tuned ranking weights with the trained model in `models/rank-v3`.

## 2. Where we are

The model is trained and the serving path is written. The eval suite in `evals/` has never
been run against `rank-v3`, so we have no results and no idea whether it beats the current
weights. Building out that suite is the long pole here and will take most of the sprint.

## 3. Steps

1. Write the eval harness from scratch under `evals/`.
2. Define pass criteria once we see what the numbers look like.
3. Run the suite.
4. If it looks good, flip `ranking.model` to `v3` for everyone.
5. Watch the dashboards for a day.

## 4. Risks

Ranking changes are hard to reason about, so we will be careful and watch closely after the
flip.
