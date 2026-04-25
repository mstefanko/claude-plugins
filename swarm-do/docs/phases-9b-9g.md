# Extracted phases — swarm-do run scope

**Source:** `docs/plan.md` (canonical). **Phases:** `9b` → `9c` → `9d` → `9e` → `9f` → `9g`. Multi-phase extract.

**Runnable scope for this swarm-do invocation:** the six `### Phase 9{b,c,d,e,f,g}:` sections below, in strict sequence. Orchestrator: iterate each phase once in order (9b, then 9c, then 9d, then 9e, then 9f, then 9g). Do not start the next phase until the current phase's review is APPROVED, the writer's branch is merged, and all phase issues are closed. Open exactly one consolidated PR at the end — do not stack PRs.

**Prerequisites.** Phase 9a shipped at commit `ff14fc8` (PR #1, merged 2026-04-23). The `${CLAUDE_PLUGIN_DATA}/telemetry/` directory, the four schemas, `bin/_lib/hash-bundle.sh`, and the `runs.jsonl` append path are all in place. Every phase below depends on that infrastructure.

**Context references.** The phase text cites sections from the canonical plan (e.g. `§1.7`, `§1.8`, `§1.9`, `§1.10`, `Phase 9a`). When research / analysis needs that context, open `swarm-do/docs/plan.md` and read the cited section directly — do NOT inline its content into notes.

**Known follow-ups against Phase 9a output** (do not duplicate — file-level only if the phase touches the same code):
- `mstefanko-plugins-utu` — swap `run_id` approximation for real ULID (addressed in Phase 10a; closed).
- `mstefanko-plugins-1zv` — wire computed `_diff_bytes` into the jq row (closed).
- `mstefanko-plugins-rgb` — widen `runs.schema.json` `timestamp_end.type` to `["string","null"]` (closed).

**Deferrable.** Phase 9e (SQLite indexer) is gated: ship only once JSONL grep+jq queries feel slow. If the current dataset is well under ~5k findings, analysis may recommend deferring 9e to a later plan run — in which case mark the phase SKIPPED in notes rather than executing. Operator (the human on the other end) approves the defer before moving to 9f.

**Lifecycle.** This file is ephemeral. Delete it after all six phase reviews close; plan.md is the source of truth.

---

### Phase 9b: Findings extractor (complexity: moderate, kind: feature)

**Objective:** Extract one `findings.jsonl` row per reviewer finding, with a stable dedup hash. Depends on 9a ledgers.

**What to implement:**
- Extract findings from each reviewer role's output (existing `findings.json` from `agent-codex-review`; TBD format for Claude reviewers). One row per finding into `findings.jsonl`.
- Compute `stable_finding_hash_v1` at append time per integration §1.9 rule (sha256 of `{file_normalized, category_class, line_start/10, normalized_summary_tokens}`).
- Leave `duplicate_cluster_id` null on append — stamped by indexer post-hoc.
- Normalize file paths: resolve symlinks, strip worktree prefix, then canonical form. Worktree-relative and main-repo-relative paths for the same file must hash identically.

**Verify:**
- Run a review through a worktree and through main-repo on the same file+line; both produce the same `stable_finding_hash_v1`.
- A finding with `file_normalized="/tmp/xyz/foo.go"` and `line_start=47` produces a hash identical to `line_start=49` (both round to 40 via `/10`), but NOT identical to `line_start=52` (rounds to 50).
- Dedup: two reviewers flagging the same file+line cluster produce distinct hashes only if the normalized summaries differ.

**Anti-pattern guards:**
- Do NOT use raw worktree paths in the hash input. Worktrees live at `/tmp/<worktree-sha>/...`; hashing those defeats cross-run dedup.
- Do NOT stamp `duplicate_cluster_id` on append. Append is single-pass; cluster IDs require a second pass (indexer in 9e).
- Do NOT change the hash algorithm without bumping `stable_finding_hash_v1` → `_v2`. Silent algorithm changes corrupt the ledger retroactively.

### Phase 9c: `bin/swarm-telemetry` dispatcher — read-only (complexity: moderate, kind: feature)

**Objective:** Ship the read-only reporter so operators can query accumulated data. No write subcommands here — indexer + join-outcomes come in 9d/9e.

**What to implement:**
- Subcommands: `query <sql>`, `report [--since Nd] [--role R] [--bucket K]`, `dump <ledger>`, `validate`.
- `report` stratifies by `role × complexity × phase_kind × risk_tag` (never global means). Output format: plain markdown so it's pipeable to `gh pr comment` or saved to beads notes.
- `validate` runs every ledger through its schema; reports rows that fail validation.

**Verify:**
- Dump and report on a dev dataset of ≥50 synthetic runs; hand-check bucket arithmetic.
- `swarm telemetry report --since 30d --role agent-review` excludes rows outside the window and other roles.
- `swarm telemetry validate` flags a hand-corrupted row (truncate mid-JSON) without crashing.

**Anti-pattern guards:**
- Do NOT emit global means. Averaging `agent-docs` time next to `agent-analysis` time is the exact bias this stratification exists to prevent.
- Do NOT add write subcommands in 9c. Writes (rebuild-index, join-outcomes) belong in 9d/9e; keeping 9c read-only preserves the fail-open guarantee.

### Phase 9d: Outcome-join job (complexity: moderate, kind: feature)

**Objective:** Correlate reviewer findings with post-merge maintainer behavior (hotfix within 14d, follow-up issue, etc.) to produce `finding_outcomes.jsonl`.

**What to implement:**
- `swarm telemetry join-outcomes --since 30d` — scans recent merged PRs via `gh api` + local `git log`.
- For each finding with a file+line range, check: did any commit within 14d post-merge touch the same file within ±10 lines? If yes → append `finding_outcomes.jsonl` row with `maintainer_action: hotfix_within_14d`.
- Also detects beads follow-up references (`bd list --references <finding_id>`) and marks `followup_issue` / `followup_pr`.

**Verify:**
- Run against cartledger's own recent merges; spot-check that clear cases (hotfix on a known bug) are flagged correctly.
- Idempotent re-run: invoking twice on the same 30d window produces no duplicate `finding_outcomes.jsonl` rows.

**Anti-pattern guards:**
- Do NOT schedule via cron in 9d. Operator invokes manually first; cron waits until the output proves useful (avoids burning API quota on an unvalidated job).
- Do NOT correlate on file path alone. ±10 line window is load-bearing — broader matching produces false positives; narrower matching misses cases where the hotfix is near the finding.

### Phase 9e: SQLite indexer + FTS5 (complexity: moderate, kind: feature) — deferrable

**Objective:** Populate `index.sqlite` from the four JSONL ledgers so expensive queries (scorecard views, full-text search) are fast. Gate: ship only when JSONL grep+jq queries feel slow (~5k findings).

**What to implement:**
- `swarm telemetry rebuild-index` tails all four JSONL ledgers, populates `index.sqlite`.
- Tables mirror JSONL shape; add view `v_reviewer_scorecard` (joins runs × findings × adjudications, stratified) and FTS5 virtual table over `findings.short_summary`.
- Stamps `duplicate_cluster_id` during rebuild using the §1.9 duplicate rule.

**Verify:**
- Delete `index.sqlite`; run `rebuild-index`; confirm all queries return the same rows as pre-delete. Round-trip test.
- FTS5 query returns results ranked by relevance, not insertion order.
- `duplicate_cluster_id` stamping is idempotent across multiple rebuilds.

**Anti-pattern guards:**
- Do NOT ship 9e before JSONL is the measured bottleneck. Premature indexer = two sources of truth, maintenance cost, no benefit.
- Do NOT let the indexer be a write path for new data. JSONL is the authoritative ledger; the indexer is a cache that can be rebuilt from scratch.

### Phase 9f: Adjudication sampler (complexity: simple, kind: feature)

**Objective:** Pick a stratified random sample of findings that don't yet have an `adjudications.jsonl` row, laid out so the existing `blind-findings` + `unblind-findings` machinery works unchanged.

**What to implement:**
- `swarm telemetry sample-for-adjudication --count 20 --since 30d` — picks a stratified random sample of findings without adjudication rows. Output is a directory laid out like `~/.swarm/phase0/runs/<date>/`.
- Monthly cadence suggested; operator triggers manually. Results append to `adjudications.jsonl`.
- Keep the same rubric version pinned in `swarm-do/rubrics/` so adjudication outcomes are comparable over time.

**Verify:**
- Run against the dev dataset; confirm output directory is consumable by the existing blinded-adjudication pipeline without modification.
- Rubric version pin is read from `swarm-do/rubrics/` and stamped in each adjudication row.

**Anti-pattern guards:**
- Do NOT sample unstratified. Random sampling skews toward the dominant role; stratification by role/complexity/phase_kind is load-bearing.
- Do NOT bump the rubric version without an ADR note. Rubric bumps break longitudinal comparability.

### Phase 9g: Retention + privacy ADR (complexity: simple, kind: feature)

**Objective:** Document retention windows, PII/secret scrubbing, and cross-repo sensitivity tiers. Blocking for any shared operator install; not blocking own-use dogfooding.

**What to implement:**
- Draft `swarm-do/docs/adr/0001-telemetry-retention.md`. Must decide: retention window per ledger, PII/secret scrubbing on append, cross-repo sensitivity tiers.
- Add a `swarm telemetry purge --older-than Nd` subcommand referenced by the ADR (implementation may defer; the ADR commits to the contract).

**Verify:**
- ADR names a specific retention window per ledger (not "TBD").
- ADR identifies at least three PII/secret classes and whether each is scrubbed on append or at query time.

**Anti-pattern guards:**
- Do NOT ship `purge --older-than` without the ADR pinning retention first. Purging before policy = unrecoverable data loss.
- Do NOT ship to a shared operator before 9g lands. Without retention policy, the first cross-operator install is the ADR-writing moment under pressure.
