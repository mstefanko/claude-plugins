# Operator UX Dogfood Tightening - Implementation Plan

Date: 2026-05-15
Status: proposed
Scope: Bakeoff CLI operator experience, triage surfaces, report wording, and
runtime-budget prompt discipline

## Triggering Run

This plan follows the `dogfood-lens-operator-ux-high` dogfood run.

Run facts:

- Research run succeeded with workers at `high` and judge at `xhigh`.
- Claude worker completed successfully after about 665 seconds with zero stdout
  until completion.
- Codex worker completed successfully after about 227 seconds.
- Gather judge completed successfully after about 86 seconds.
- Triage ran with Claude Opus at `xhigh` and completed in about 166 seconds.
- Harness source selection improved from the previous operator-UX run's `3`
  selected findings to `31` selected findings, with zero skipped findings.

The source-selection fix worked. The remaining problems are now clearer:
operator guidance is inconsistent across commands, several state labels collapse
distinct states, stale triage can still be shown as current, and prompts do not
tell agents how to spend the configured wall-clock budget.

## Decision

Implement two related but separate improvements:

1. Add runtime-budget instructions to worker, judge, and triage prompts so
   provider calls preserve time for schema-valid final output and prefer partial
   cited results over missing or late `final_json`.
2. Tighten CLI/report/triage UX around next-step commands, state labels, stale
   artifacts, dry-run artifacts, and markdown fidelity.

Do not try to make provider CLIs stream semantic progress through stdout. The
last run showed that Claude can remain at zero stdout while still doing useful
work. Bakeoff should explain that liveness limitation through heartbeat output
and status messages, not by asking providers to emit progress chatter that could
pollute the structured output channel.

## Goals

- Reduce timeout and missing-`final_json` risk on high-effort runs.
- Keep broad dogfood lenses useful without forcing every provider to chase
  perfect coverage.
- Make every suggested follow-up command pasteable, including non-default
  `--out` ledgers.
- Prevent stale triage from being displayed without a warning.
- Make `bakeoff ls` a reliable scan surface for facet and triage state.
- Ensure `triage.md` faithfully renders every schema-valid triage item.
- Make dry-run and skipped-source artifacts discoverable from CLI output.
- Keep the implementation small enough to dogfood again immediately.

## Non-Goals

- No new provider topology.
- No separate triage model configuration yet.
- No live stdout progress protocol.
- No terminal dashboard.
- No automatic code edits from triage.
- No attempt to infer true model reasoning progress from quiet subprocesses.

## Runtime-Budget Prompt Pattern

Add a shared helper in `src/bakeoff/providers.py`, for example:

```python
def render_runtime_budget_block(budgets: dict[str, Any], *, role: str) -> str:
    ...
```

Insert the block into worker, judge, and triage prompts near the task and schema
rules, before the final output instruction.

Recommended wording:

```text
<runtime_budget>
The harness will stop this provider after {wall_clock_seconds} seconds.
Plan to finish investigation by about {work_seconds} seconds and reserve the
remaining time to emit a schema-valid <final_json>.

If full coverage is not possible before the cutoff:
- Prefer fewer well-cited findings over broad uncited coverage.
- Emit a partial but schema-valid result before the cutoff.
- Record unfinished or uncertain areas in the schema's unknowns, caveats,
  conflicts, recommended_next_checks, or rationale fields, as applicable.
- Do not wait for perfect coverage if that risks missing the final_json cutoff.

Do not emit progress updates or partial JSON outside the final <final_json>
block. stdout is the structured answer channel.
</runtime_budget>
```

Role-specific additions:

- Workers may use `status: "complete_with_concerns"` when coverage is partial.
- Gather judges should use `unknowns_union[]` for unresolved synthesis gaps.
- Compare judges should use the rationale and preservation arrays to explain
  incomplete confidence rather than inventing certainty.
- Analyze judges should put concrete unresolved risks in
  `actionable_followups[]` and keep ordinary uncertainty in rationale/verdicts.
- Triage should classify every provided `source_findings[]` item it can, use
  `evidence_gap` or `needs_repro` when evidence is insufficient, and put checks
  it could not perform in `unknowns[]`.

Implementation details:

- Compute a reserve window from `wall_clock_seconds`, capped to keep the prompt
  simple. A reasonable first cut is `work_seconds = max(60,
  int(wall_clock_seconds * 0.8))`.
- Mention `max_output_bytes` only if needed. The more important instruction is
  to finish with valid JSON before the wall-clock cutoff.
- Keep the budget text deterministic so prompt tests can assert key phrases.
- Do not ask providers to emit progress updates; that belongs to heartbeat UX.

## CLI Tightening

### 1. Centralize Suggested Commands

Add a small helper in `src/bakeoff/cli.py`:

```python
def command_hint(base: str, run_id: str, *, out_dir: Path, flags: Sequence[str] = ()) -> str:
    ...
```

Behavior:

- Omit `--out runs` for the default ledger.
- Include `--out <path>` for non-default ledgers.
- Reuse this helper for every `next:`, `recommended:`, stale, missing triage,
  and force-retry message.

This addresses the repeated `--out` omission and prevents future drift.

### 2. Make `--no-triage` Wording Honest

When `no_triage=True`, suppress the `recommended: bakeoff triage ...` line or
change it to neutral acknowledgement:

```text
triage skipped by --no-triage; run bakeoff triage <id> if you want verification later
```

Prefer suppression for now. The flag is explicit, and dogfood showed the current
recommendation reads like a contradiction.

Update tests that currently assert the recommendation appears under
`--no-triage`.

### 3. Harden `show --triage`

Before printing `triage/triage.md`, call `triage_state(run_dir)`.

Behavior:

- `yes`: print triage markdown.
- `stale`: print a stale warning and recovery command before the markdown, or
  fail with a recovery command. Prefer warning plus markdown so operators can
  still inspect the old artifact knowingly.
- `no`: raise `ValidationError` that includes the full recovery command.

Add an end-to-end test for stale `show --triage`, not only plain `show`.

### 4. Represent Dry-Run Triage State

Extend `triage_state(run_dir)` to return `dry_run` when
`triage/status.json` exists with `status: "dry_run"` and no final triage report
exists.

Then:

- `bakeoff ls` prints `triage:dry_run`.
- `bakeoff show` can suggest `bakeoff triage <id> --force`.
- `bakeoff triage --dry-run` prints the prompt/status/filter artifact paths.

### 5. Improve `bakeoff ls`

Add a header and a facet column:

```text
run_id	type	facet	decision	triage	finished_at
```

Behavior:

- Print a one-line empty state when `--out` does not exist.
- Use `-` for missing facet.
- Keep output tab-separated for easy scripting.

This makes `ls` useful as a scan surface without forcing operators through
`show` for every run.

### 6. Print Triage Input Artifact Paths

After source selection, print:

```text
source findings: selected N; skipped M non-actionable; skipped K out-of-facet
source filter: runs/<id>/triage/source_finding_filter.json
```

For `--dry-run`, also print:

```text
triage prompt: runs/<id>/triage/prompt.txt
triage status: runs/<id>/triage/status.json
```

This directly addresses the dogfood finding that the harness writes the useful
audit artifact but hides the path.

### 7. Improve Triage Recovery Errors

Tighten `run_triage` errors:

- Existing triage dir without `--force` should include
  `bakeoff triage <run-id> --force`.
- Provider failure should print where `status.json`, `stdout.txt`, and
  `stderr.txt` were written, plus the force retry command.
- Dry-run follow-up should be explicit: inspect prompt/filter or rerun with
  `--force`.

## Report and Triage Markdown Tightening

### 1. Clarify Gather Corroboration

The operator-UX report flagged raw headings such as `### claude` and
`single-source` wording. Add a short legend near the gather Findings intro:

```text
Section headings name the provider set that surfaced each claim. `single-source`
means only one provider surfaced the claim; it is not independent verification.
`multi-source` means both providers surfaced materially similar claims; it is
still not proof of correctness.
```

Keep the existing facet caveat, but define the labels where the operator sees
them.

### 2. Mark Out-of-Facet Claims As Triage-Skipped

When rendering `Out-of-Facet Claims`, add an explicit note:

```text
These claims are observability-only and are excluded from triage source
selection.
```

The triage source filter already tracks `skipped_out_of_facet`; the report
should set the same expectation before the operator acts on the section.

### 3. Make `triage.md` Lossless

Update bucket rendering so every schema-valid item appears exactly once.

Recommended buckets:

- `Fix Now`
- `Needs Reproduction`
- `Document / Defer`
- `Already Fixed`
- `False Positives`
- `Ignored`
- `Other Triage Items`

Rules:

- `already_fixed` should not appear under `False Positives`.
- `recommended_action: ignore` should render under `Ignored`.
- Any item not matched by known rules should render under `Other Triage Items`.
- Add a test that constructs one item for every allowed classification/action
  combination likely to be bucketed.

## Documentation Tightening

Update README command surface:

- Include `--out runs` for `bakeoff show`.
- Explain that citation checks are anchored to the original `cwd` recorded in
  `meta.json`, falling back to the current directory with a caveat.
- Document `triage:dry_run` if implemented.
- Mention `source_finding_filter.json`.
- Keep effort defaults documented as quality-first dogfood defaults.

Update the faceted research plan if it still contains command examples or effort
defaults that no longer match the CLI.

Do not treat `gpt-5.5` in examples as a placeholder unless a separate provider
compatibility check proves it is invalid. The dogfood run used `gpt-5.5`
successfully.

## Heartbeat and Quiet-Provider Messaging

The prompt budget block should improve completion discipline, but it will not
make Claude stream stdout. Pair this plan with the existing heartbeat
observability plan.

Add a quiet-provider hint after repeated zero-output ticks:

```text
[claude] quiet 10:00/15:00 out=0.0KB last=600s; some provider CLIs buffer until final output
```

This is an operator reassurance, not proof of progress. Keep the wording honest.

## Tests

Add or update tests for:

- prompt budget block appears in worker, judge, and triage prompts
- worker prompt mentions partial schema-valid output and
  `complete_with_concerns`
- judge/triage prompts mention valid final JSON before cutoff without inventing
  new schema fields
- `--no-triage` does not print an unsolicited recommendation
- command hints include non-default `--out`
- `show --triage` warns or errors on stale/missing triage with recovery command
- `triage:dry_run` state
- `bakeoff ls` header, facet column, missing-ledger empty state
- triage dry-run prints prompt/status/source-filter paths
- triage already-exists and provider-failure paths include recovery commands
- gather corroboration legend text
- Out-of-Facet Claims note
- triage markdown renders every item exactly once, including `already_fixed`,
  `ignore`, and unmatched combinations
- README command surface matches argparse for `show --out`

## Suggested Implementation Order

1. Add runtime-budget prompt helper and prompt tests.
2. Add centralized command hint helper and update all next-step/recovery prints.
3. Harden `show --triage`, triage existing-dir errors, and provider-failure
   recovery output.
4. Add `triage:dry_run`, dry-run artifact path prints, and `ls` header/facet
   column.
5. Make report and triage markdown wording/bucketing lossless.
6. Update README and implementation-plan docs.
7. Rerun focused tests and then dogfood `dogfood-lens-operator-ux` once more.

## Acceptance Criteria

- The operator-UX dogfood run selects all faceted Findings into triage unless
  they are explicitly out-of-facet.
- High-effort runs receive budget instructions and still produce schema-valid
  results when partial.
- No generated next-step command points at the wrong ledger when `--out` is
  non-default.
- `show --triage` cannot silently present stale triage as current.
- `ls` shows enough state to choose the next command.
- Dry-run triage is visible as dry-run, not collapsed into not-run.
- `triage.md` renders every triage item from `final.json`.
- README describes actual CLI behavior.
