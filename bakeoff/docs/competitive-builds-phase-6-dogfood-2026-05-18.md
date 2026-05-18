# Competitive Builds Phase 6 Dogfood

Date: 2026-05-18
Status: Phase 6 dogfood complete
Plan: `docs/competitive-builds-implementation-plan-2026-05-18.md`

## Commands

Deterministic harness dogfood:

```bash
scripts/dogfood-build-phase6.py --ledger-rows 600
```

Live environment readiness dogfood:

```bash
go run ./cmd/bakeoff doctor --build --skip-auth-probe --json --quiet
```

The live readiness command failed inside the default surrounding sandbox, then
passed when rerun outside the sandbox. That is the intended classification:
host readiness failure, not a provider patch failure.

## Deterministic Dogfood Results

Workspace:
`/private/tmp/bakeoff-phase6-dogfood-lu00iiml`

Runs directory:
`/private/tmp/bakeoff-phase6-dogfood-lu00iiml/runs`

All five concrete cases passed with `runs verify`:

| Case | Selection | Winner | Judge | Notes |
| --- | --- | --- | --- | --- |
| `phase6-worktree-patch-capture` | `metric` | `claude` | no | Source checkout stayed unmodified after provider worktree edits. |
| `phase6-verifier-runner` | `metric` | `claude` | no | Metric artifacts were written for baseline and both providers. |
| `phase6-manifest-runs-verify` | `judge` | `claude` | yes | Manifest includes `build-context.json`; `ls`, `show`, and `runs verify` worked. |
| `phase6-provider-permissions` | `gate` | `claude` | no | Fake `doctor --build` passed; missing Codex workspace-write became `scope_error`. |
| `phase6-large-ledger-metric` | `judge` | `claude` | yes | Metric verifier scanned 600 manifest rows; observed `elapsed_ms` was about 19.3 ms. |

Negative dogfood also passed: `phase6-no-gate-negative` exited with validation
code 2 and reported that `build.verify` must include at least one gate verifier.

## Prompt And Artifact Audit

The sampled build judge prompt was 17,678 bytes. It included both position-swap
guidance and the explicit rule:

```text
Do not let style, verbosity, or patch size alone override failing verifier evidence.
```

The prompt does include patch excerpts. That is useful for judge fallback, but
the current excerpt caps still matter. No Phase 6 evidence showed the judge
overweighting patch size or verbosity.

The five deterministic run ledgers totalled 359,719 bytes, about 351.3 KiB.
The large-ledger scratch data was rooted under the dogfood workspace and
totalled 390,600 bytes, about 381.4 KiB. Manifest verification performance was
acceptable in this sample; the large-ledger metric scanned 600 manifest rows
quickly enough that a SQLite or indexing surface is still not justified for v1.

## Environment Dogfood

Inside the default sandbox, `doctor --build` failed before any build patch run:

- Claude probe: provider live edit failed with `Not logged in`.
- Codex probe: provider live edit failed because Codex could not access
  `/Users/mstefanko/.codex/sessions`.

Rerunning the same command outside the sandbox passed:

- Claude edited the temporary workspace in about 9.1 seconds.
- Codex edited the temporary workspace in about 9.4 seconds.
- `temporary_workspace_removed` was `true`.
- Codex advertised `--sandbox workspace-write`.

This supports keeping `doctor --build` as the readiness boundary before live
competitive build dogfood.

## Follow-Up Decision

No `bakeoff apply` helper was added. Current reports hand off the exact
selected provider patch artifact and intentionally do not emit apply commands.
The desired competitive-build output is the report plus the selected patch
artifact. Applying, editing, combining, synthesizing, or reimplementing after
the report is intentionally a separate implementation step outside the bakeoff
decision and must be verified again before it is treated as ready.

One harness issue was found and fixed: the fake provider detected any prompt
containing the words "build judge" as a judge prompt. A worker background used
that phrase and crashed the fake provider. The fake now detects judge prompts by
their actual opening line.

## Scratch Probe Hygiene

One-off dogfood metric probes should stay in scratch space unless they become a
durable maintainer check. The run ledger is the evidence record for the command
output and parsed metric; it is not a promise that scratch scripts are stable
product surface. Promote a probe into `scripts/` only when it has stable inputs,
does not inject temporary source files, and is expected to be rerun by
maintainers.
