# ADR 0001: Telemetry Retention Policy

**Status:** Accepted  
**Date:** 2026-04-24  
**Supersedes:** None  
**Related:** ADR 0002, Phase 9g (Telemetry Close-Out)

## Context

Telemetry is stored in JSONL ledgers (runs.jsonl, findings.jsonl, outcomes.jsonl, adjudications.jsonl, finding_outcomes.jsonl) on the operator's filesystem. Each ledger grows unbounded over repeated swarm-do invocations. Cross-repository data accumulates without retention limits, creating:

1. **Storage burden:** multi-repository swarms produce thousands of rows per run.
2. **PII/secret exposure:** three ledger fields contain sensitive data that should not persist indefinitely:
   - `runs.repo` — Git remote origin URL, which may encode org slug, repository name, or personal access tokens in HTTPS credentials.
   - `findings.summary` and `findings.file_path` — Free-text finding descriptions and repository-relative file paths, exposing internal directory structure.
   - `adjudications.rationale` — Free-text rationale that may contain code snippets, diff excerpts, and reviewer notes.

Without a retention policy, stale telemetry carries PII/secret risk indefinitely and consumes local disk space across multiple machines and repositories.

## Decision

Implement a per-ledger retention window, enforced by an operator-invoked `swarm telemetry purge` subcommand. Rows older than the retention threshold are irrecoverably deleted via atomic file rewrite.

**Retention Windows:**

| Ledger | Window | Rationale |
|--------|--------|-----------|
| `runs` | 180 days | Operational metadata; minimal value after 6 months. |
| `findings` | 365 days | Training signal for findings classifiers and review models; high value for 1 year. |
| `outcomes` | 365 days | High-signal classification targets; retained for 1 year. |
| `adjudications` | 365 days | Adjudicator labels and metadata; high value for training and analysis. |
| `finding_outcomes` | 180 days | Derived join table; secondary utility after 6 months. |

**PII/Secret Classes:**

1. **`runs.repo`** (string | null) — Git remote origin URL. May contain org slug, repository slug, or PAT-in-HTTPS format (`https://token@github.com/org/repo`). Sensitivity: **High** within the operator's organization; **Medium** cross-org.
2. **`findings.summary` + `findings.file_path`** (string, string | null) — Free-text finding description and repo-relative path. Exposes internal directory structure and discovery logic. Sensitivity: **Medium** within org; **Low** cross-org.
3. **`adjudications.rationale`** (string | null) — Free-text adjudication rationale. May quote code fragments, diff snippets, and reviewer notes. Sensitivity: **Medium** within org; **Low** cross-org.

**Cross-Repo Sensitivity Tiers:**

- **Tier 1 (High):** runs.repo from proprietary code repositories. Delete aggressively (180d).
- **Tier 2 (Medium):** findings and adjudications within private organizations. Retain for 365d for classifier training; purge thereafter.
- **Tier 3 (Low):** findings and adjudications from public repositories. Acceptable to retain longer, but purge after 365d as hygiene.

## Consequences

- Operators must invoke `swarm telemetry purge --older-than Nd [--ledger <name>]` manually or via cron.
- Rows older than the specified retention window are permanently deleted. No recovery without backups.
- The purge operation is not part of swarm-run; it is operator-invoked only to avoid implicit data loss.
- A corresponding Python subcommand implementation (swarm-do/py/swarm_do/telemetry/subcommands/purge.py) holds retention windows as a module-level dict with a source-of-truth pointer to this ADR. Updates to retention values must be coordinated: ADR revision + dict update + tests.
- Timestamp field names vary per ledger (runs uses `timestamp_start`; others use `timestamp` or `observed_at`). The purge implementation encodes this mapping explicitly to prevent silent misses.
