# Operator UX Dogfood Tightening - Implementation Plan

Date: 2026-05-15
Status: revised
Scope: Bakeoff CLI operator experience, prompt budget discipline, heartbeat
wording, Codex final-output capture, triage surfacing, and docs/tests alignment

## Triggering Runs

This plan follows the `dogfood-lens-operator-ux-high` run and the follow-up
heartbeat/output dogfood review.

Observed facts:

- Research succeeded with workers at `high` and judge at `xhigh`.
- Claude completed successfully after about 665 seconds with zero stdout until
  completion.
- Codex completed successfully after about 227 seconds.
- Gather judge completed successfully after about 86 seconds.
- Triage completed successfully after about 166 seconds.
- Source selection improved from the previous operator-UX run's `3` selected
  findings to `31` selected findings, with zero skipped findings.
- Follow-up review showed Codex can emit high-volume stderr progress while its
  final stdout stays small. Existing status artifacts already record retained
  and observed byte counts.

The remaining problem is not one giant UX rewrite. It is a small set of operator
surfaces that should be tightened without duplicating behavior already present in
the code.

## Decision

Implement the remaining gaps in one dogfood-sized pass:

1. Add a deterministic runtime-budget block to worker, judge, and triage prompts.
2. Make heartbeat wording honest by splitting stdout and stderr in the live line.
3. Add Codex `--output-last-message` capture so final JSON does not depend on
   noisy progress streams.
4. Reuse the existing command helper functions everywhere follow-up commands are
   printed.
5. Preserve and test the already-implemented `ls`, stale triage, dry-run triage,
   report legend, and triage markdown behavior.
6. Update README and related docs to describe the actual CLI behavior.

This plan supersedes
`docs/heartbeat-observability-implementation-plan-2026-05-15.md` as the active
implementation plan. That file should remain only as a pointer here.

## Verified Current State

These items are already implemented and should not be re-planned as new feature
work:

- Suggested-command helpers already exist:
  `bakeoff_show_command()`, `bakeoff_triage_command()`, and `out_dir_suffix()`
  in `src/bakeoff/cli.py`.
- `bakeoff ls` already prints a header, facet column, triage state, and a
  missing-ledger empty state.
- `triage_state_detail()` already reports `dry_run` when `triage/status.json`
  has `status: "dry_run"` and no final triage report exists.
- Plain `bakeoff show` already reports stale triage and dry-run triage with a
  recovery command.
- `bakeoff show --triage` already fails stale, dry-run-only, and missing triage
  paths with `ValidationError`; the CLI exit code is `2`.
- `bakeoff triage --dry-run` already prints the source filter, prompt, status,
  and force-rerun command paths.
- Gather reports already include the provider-set/corroboration legend near
  `## Findings`.
- Out-of-facet claims already include the note that they are observability-only
  and excluded from triage source selection.
- `triage.md` already separates `Already Fixed` from `False Positives` and has
  an `Other Valid Items` fallback bucket.

## Non-Goals

- No new provider topology.
- No structural split of `max_output_bytes` into multiple budget fields in this
  pass.
- No raw stdout or stderr snippet streaming.
- No heartbeat deltas, ETA, percent complete, or observed-byte field in the live
  heartbeat line.
- No new `Ignored` triage markdown bucket in this pass.
- No broad prompt decomposition framework beyond the runtime-budget block.
- No attempt to infer true model reasoning progress from quiet subprocesses.

## Runtime-Budget Prompt Block

Add a shared helper in `src/bakeoff/providers.py`:

```python
RUNTIME_BUDGET_ROLES = ("worker", "judge", "triage")

def render_runtime_budget_block(budgets: dict[str, Any], *, role: str) -> str:
    ...
```

Contract:

- `role` must be one of `worker`, `judge`, or `triage`; raise `ValueError` for
  unsupported roles.
- `budgets["wall_clock_seconds"]` must be a positive integer; raise
  `ValueError` if it is missing or invalid. In normal CLI flow this is already
  validated by work-order loading, so this is a defensive contract.
- Return a deterministic string containing exactly one `<runtime_budget>` block,
  with no leading blank line and one trailing newline.
- Do not mention role-specific schema fields in v1. The block should instruct
  the provider to use existing uncertainty/rationale fields in the requested
  schema and never add fields outside the schema.

Compute the work cutoff so it is always less than the wall clock:

```python
reserve_seconds = min(max(30, wall_clock_seconds // 5), max(1, wall_clock_seconds - 1))
work_seconds = max(1, wall_clock_seconds - reserve_seconds)
```

Use this wording:

```text
<runtime_budget>
The harness will stop this provider after {wall_clock_seconds} seconds.
Plan to stop investigation by about {work_seconds} seconds and reserve the
remaining time to emit a schema-valid <final_json>.

If full coverage is not possible before the cutoff:
- Prefer fewer well-cited findings over broad uncited coverage.
- Emit a partial but schema-valid result before the cutoff.
- Use existing uncertainty or rationale fields in the requested schema to record
  unfinished areas.
- Do not add fields outside the requested schema.
- Do not wait for perfect coverage if that risks missing the final_json cutoff.

Do not emit progress updates or partial JSON outside the final <final_json>
block. stdout is the structured answer channel.
</runtime_budget>
```

Insertion points:

- Worker prompts: after `<rules>` and before `<worker_result_schema>`.
- Judge prompts: after `<rules>` and before `<process>`.
- Triage prompt: after `<rules>` and before `<triage_payload>`.

Implementation notes:

- Worker and judge builders can read `work_order["budgets"]`.
- `build_triage_prompt()` must receive budgets explicitly, or `run_triage()` must
  include budgets in the payload before rendering.
- Do not add the separate `<scope_management>` block in this pass.
- Do not add role-specific uncertainty-field templating in this pass.
- Do not introduce new prompt instructions around `complete_with_concerns` in
  this pass.

## Heartbeat Wording

Keep this v1 intentionally small. The live heartbeat should separate stdout from
stderr and keep the existing honest process telemetry.

Replace the ambiguous current shape:

```text
[provider=codex t=60s out=72.9KB quiet=14s]
```

with:

```text
[codex] running t=60s/900s out=13.5KB err=58.6KB last=14s
[claude] quiet t=600s/900s out=0.0KB err=0.0KB last=600s
```

Rules:

- `running` and `quiet` come from the existing tick `phase`.
- `t` is elapsed seconds over wall-clock budget seconds.
- `out` is retained stdout bytes only.
- `err` is retained stderr bytes only.
- `last` is seconds since the last stdout or stderr.
- Do not include byte deltas in this pass.
- Do not include `observed=` in the live heartbeat in this pass. Retained and
  observed byte counts remain available in status artifacts and report details.
- Do not print raw provider stdout or stderr snippets.

Implementation:

- Add or refactor a pure `format_heartbeat_line(label: str, tick: dict[str,
  Any]) -> str` helper in `src/bakeoff/cli.py`.
- Update `make_tick_printer()` to call the formatter and print to stderr.
- Preserve `quiet=True` returning `None`.
- Do not change `src/bakeoff/runner.py` unless the implementation discovers a
  missing field. The existing tick payload already carries phase, elapsed,
  wall budget, stdout bytes, stderr bytes, and last-output age.

## Codex Final-Message Capture

The real Codex-side hardening is to capture the final assistant message
out-of-band. OpenAI's Codex docs describe `--output-last-message` as writing the
assistant's final message to a file for downstream scripting, and `--json` as
newline-delimited JSON events.

Sources:

- https://developers.openai.com/codex/noninteractive
- https://developers.openai.com/codex/cli/reference/

Implementation:

- Detect whether the installed Codex CLI supports `--output-last-message` from
  `codex exec --help`, or add the flag only when support is known.
- Add optional final-message path support to `build_participant_argv()` or to the
  call sites that invoke Codex. The path should live beside the normal provider,
  judge, or triage artifacts:
  `providers/<id>/last-message.txt`, `judge/last-message[-label].txt`, or
  `triage/last-message.txt`.
- Add `final_message_path: Path | None` to `run_provider()` and
  `run_provider_with_format_retry()`.
- When `final_message_path` exists and is non-empty, prefer extracting
  `<final_json>` from that file instead of captured stdout.
- Continue writing captured stdout and stderr artifacts for audit.
- Add `final_json_source` to the returned provider result and to
  `status_without_payload()` output. Values: `stdout`, `last_message`.
- Do not enable Codex `--json` in this pass. JSONL event parsing can be a later
  feature; the current `<final_json>` extractor must not parse JSONL progress as
  the final answer.
- If final-message capture is unsupported or the file is absent/empty, fall back
  to current stdout extraction and record `final_json_source: "stdout"` on
  success.

Short-term dogfood guidance:

- While final-message capture is being implemented, high-effort dogfood work
  orders may raise `max_output_bytes` and `max_output_overrun_bytes` to `262144`
  or `524288` to reduce false early output-cap pressure.
- Do not redesign the output-cap budget model in this pass.

## CLI Tightening

### Suggested Commands

Do not add a new generic `command_hint()` helper. Reuse the existing helpers:

- `bakeoff_show_command(run_id, out_dir, flag=None)`
- `bakeoff_triage_command(run_id, out_dir, force=False)`
- `out_dir_suffix(out_dir)`

Audit every `next:`, `recommended:`, stale, dry-run, missing-triage,
already-exists, provider-failure, and force-retry message. Replace any remaining
hand-built command strings with the existing helpers.

### `--no-triage`

When `no_triage=True`, do not print an unsolicited `recommended: bakeoff triage
...` line. The flag is explicit, and recommending the skipped action reads like
a contradiction.

### `show --triage`

Preserve the current stricter behavior:

- `yes`: print triage markdown and exit `0`.
- `stale`: raise `ValidationError` with the stale inputs and a force recovery
  command; CLI exits `2`.
- `dry_run`: raise `ValidationError` with a force recovery command; CLI exits
  `2`.
- `no`: raise `ValidationError` with a triage command; CLI exits `2`.

### Triage Artifact Paths

Preserve the current dry-run and source-filter path output. Add tests only if a
path is not covered:

```text
source findings: selected N; skipped M non-actionable; skipped K out-of-facet
source filter: runs/<id>/triage/source_finding_filter.json
triage dry run: runs/<id>/triage/prompt.txt
triage status:  runs/<id>/triage/status.json
next:           bakeoff triage <id> --force [--out <path>]
```

### `bakeoff ls`

Preserve the current header/facet/empty-state behavior. Do not reimplement it:

```text
run_id	type	facet	decision	triage	finished_at
```

## Report And Triage Markdown

### Gather Corroboration Legend

The gather report already explains provider-set headings and `single-source` /
`multi-source` wording near `## Findings`. Preserve that wording and keep test
coverage around it.

### Out-of-Facet Note

The report already marks out-of-facet claims as observability-only and excluded
from triage source selection. Preserve that wording and keep test coverage
around it.

### Triage Buckets

Do not rename buckets in this pass. Keep the current public markdown headings to
avoid needless golden-output churn:

- `Fix Now`
- `False Positives`
- `Already Fixed`
- `Needs Reproduction`
- `Defer / Product Decision`
- `Other Valid Items`

Bucket rules:

- `recommended_action: fix_now` renders under `Fix Now`.
- `classification: false_positive` renders under `False Positives`.
- `classification: already_fixed` renders under `Already Fixed`.
- `recommended_action: reproduce`, `classification: needs_repro`, and
  `classification: evidence_gap` render under `Needs Reproduction`.
- `recommended_action: document`, `recommended_action: defer`,
  `classification: plan_doc_drift`, and `classification: product_decision`
  render under `Defer / Product Decision`.
- Any schema-valid item not matched by those rules renders under
  `Other Valid Items`.
- There is no `Ignored` bucket in this pass. `recommended_action: ignore` only
  influences the bucket when paired with a classification rule above; otherwise
  it falls through to `Other Valid Items`.

Add or keep a test that proves every schema-valid item appears exactly once.
Broaden coverage only as needed to cover `already_fixed`, `ignore`, and the
fallback bucket.

## Documentation

Update README and related docs to match behavior after implementation:

- Include `--out runs` for `bakeoff show`.
- Explain that citation checks are anchored to the original `cwd` recorded in
  `meta.json`, falling back to the current directory with a caveat.
- Document `triage:dry_run`.
- Mention `source_finding_filter.json`.
- Document the heartbeat line fields: `running`/`quiet`, `t`, `out`, `err`,
  `last`, `--quiet`, and `budgets.heartbeat_seconds`.
- Explain that heartbeat progress is subprocess telemetry, not semantic model
  progress.
- Document Codex `last-message.txt` capture and `final_json_source` when
  implemented.
- Keep effort defaults documented as quality-first dogfood defaults.
- Update the faceted research plan if it still contains command examples or
  effort defaults that no longer match the CLI.
- Do not treat `gpt-5.5` in examples as a placeholder unless a separate provider
  compatibility check proves it is invalid. The dogfood run used `gpt-5.5`
  successfully.

## Tests

Add or update focused tests for:

- runtime-budget helper role validation
- runtime-budget helper missing/invalid budget behavior
- runtime-budget reserve calculation always producing `work_seconds <
  wall_clock_seconds`
- runtime-budget block appearing in worker, judge, and triage prompts
- partial schema-valid output language without adding schema-specific fields
- heartbeat formatter splitting `out` and `err`
- heartbeat formatter using stdout bytes for `out`, stderr bytes for `err`, and
  not combined total bytes
- heartbeat formatter showing `running`/`quiet`, `t`, and `last`
- `quiet=True` still returning `None`
- heartbeat output still writing to stderr without contaminating provider stdout
- Codex final-message extraction from `last-message.txt`
- Codex fallback to stdout when final-message capture is unsupported, absent, or
  empty
- `final_json_source` appearing in result/status metadata
- command outputs continuing to use `bakeoff_show_command()` and
  `bakeoff_triage_command()` for non-default `--out`
- `--no-triage` suppressing unsolicited triage recommendation
- `show --triage` stale, dry-run, and missing paths returning exit code `2` with
  recovery commands
- `triage:dry_run` state in `ls` and `show`
- triage dry-run path output
- triage provider-failure retry output
- gather corroboration legend and out-of-facet note remaining present
- triage markdown rendering each item exactly once, including `already_fixed`,
  `ignore`, and fallback cases
- README command, heartbeat, triage, and Codex capture docs matching actual
  behavior

## Suggested Implementation Order

1. Keep the superseded heartbeat plan as a pointer to this plan.
2. Add the runtime-budget helper and prompt insertion tests.
3. Add the minimal heartbeat formatter and tests.
4. Add Codex `--output-last-message` capture, extraction, fallback, and
   `final_json_source` metadata.
5. Audit command strings for reuse of existing show/triage helpers.
6. Tighten any remaining `--no-triage`, stale triage, dry-run, and provider
   failure tests.
7. Preserve/report triage markdown bucket behavior and broaden lossless tests.
8. Update README and related docs.
9. Rerun focused tests and dogfood the operator-UX lens again.

## Acceptance Criteria

- High-effort runs receive runtime-budget instructions and still produce
  schema-valid results when partial.
- Heartbeats split retained stdout and retained stderr into `out` and `err`.
- Heartbeats remain honest subprocess telemetry and never include raw provider
  content.
- Codex final output can be captured from `last-message.txt` when available.
- `final_json_source` explains whether structured output came from stdout or a
  final-message artifact.
- No generated next-step command points at the wrong ledger when `--out` is
  non-default.
- `show --triage` cannot silently present stale, dry-run-only, or missing triage
  as current.
- `ls`, dry-run triage, report legends, and triage bucket headings remain aligned
  with current behavior.
- `triage.md` renders every triage item from `final.json` exactly once.
- README describes actual CLI behavior.
