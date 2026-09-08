# R13 — one-screen question asked inside a dirty repo

Removed by the harness before the model runs.

The working tree has an uncommitted change (quote.ts gains tax, new tax.ts), so the skill's
injected git diff --stat is non-empty and tempting.

The input is a different question entirely: should quotes be cached per customer for 5
minutes. Expected: zero tool calls, at most 250 words, answers the caching question.
Reading the repo or reviewing the uncommitted diff instead fails the case.
