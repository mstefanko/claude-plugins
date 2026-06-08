# Experiment-metadata feature — hardening plan

Status: investigation + hardening backlog (no code written yet)
Date: 2026-06-08
Owner: TBD

## Why this plan exists

The experiment-metadata block (the `experiment` object on a work order:
`id`, `task_id`, `condition_id`, `run_kind`, `repetition_index`, `slot_id`,
`slot_attempt`) was recently added to Bakeoff core to support **external
repetition harnesses** (see `examples/repetition-loop.sh`). We ran a live
pairwise gather to exercise the contract and surfaced a set of robustness and
ergonomics gaps. This plan records the findings, the evidence, and concrete
investigation/fix steps so a fresh agent can verify each claim independently
before changing code.

**Scope discipline:** this is core-Bakeoff work under `bakeoff/`. Do not refactor
across plugin boundaries. Evidence-only investigation first; implement only after
each claim is confirmed.

## Run info (reproduce / investigate from here)

Two live runs exist. The `-2` run is the canonical one for this plan; the first
collided on run-id and is kept for reference.

| Run id | Path | Result | Exit |
|--------|------|--------|------|
| `live-v2-experiment-contract-2` | `runs/live-v2-experiment-contract-2/` | `structured_union`, judge ok | 0 |
| `live-v2-experiment-contract`   | `runs/live-v2-experiment-contract/`   | prior run (collision source) | — |

Work order: `live-v2-experiment-contract.work-order.json` (repo root of `bakeoff/`).
Experiment labels used: `id=bakeoff-live-experiment-v2`, `task_id=experiment-contract-gather`,
`condition_id=pairwise.gather`, `run_kind=pairwise`, `repetition_index=1`,
`slot_id=gather`, `slot_attempt=1`.

Key artifacts for investigation:
- `runs/live-v2-experiment-contract-2/manifest.json` — experiment fields hoisted top-level
- `runs/live-v2-experiment-contract-2/meta.json` — runtime-written; current manifest projection source
- `runs/live-v2-experiment-contract-2/work-order.json` — archived authoritative experiment block
- `runs/live-v2-experiment-contract-2/report.md` — provider findings F-001..F-025 (UNVERIFIED by triage; gather was not triaged)
- `runs/live-v2-experiment-contract-2/decision.json` — `decision_kind: structured_union`, `canonical_winner: null`

Commands used to gather evidence (re-runnable):
```
bakeoff runs verify live-v2-experiment-contract-2 --json
bakeoff ls --experiment bakeoff-live-experiment-v2 --json
cat runs/live-v2-experiment-contract-2/manifest.json
```

Caveat: report findings cite `file:line` but were NOT triage-verified (generic
gather is not auto-triaged). Treat every `file:line` below as a lead to confirm,
not a fact. Line numbers reflect the tree as of 2026-06-08 and may drift.

## Confirmed working (verified directly on the `-2` run — do not "fix")

- **Manifest projection.** All seven experiment fields are hoisted to top-level
  in `manifest.json`. Verified by reading the file.
- **`ls --json` filtering.** `bakeoff ls --experiment bakeoff-live-experiment-v2
  --json` returned matching runs with every experiment column populated.
- **Run-id collision safety.** A duplicate `--run-id` refused to clobber and
  required `--force`. `examples/repetition-loop.sh` depends on this (mints fresh
  attempt ids; never uses `--force`).

## Findings to investigate and harden (ranked)

### 1. `runs verify --json` carries no experiment identity  (CONFIRMED gap)
- **Observed:** `runs verify --json` output contains `run_id` but none of the
  experiment fields. The reference harness uses `runs verify --json` as its
  post-run completeness gate (`verify_if_present` in
  `examples/repetition-loop.sh`), so it cannot attribute a verified run to its
  experiment/condition/repetition without a second `ls`/manifest read.
- **Investigate:** `internal/verify/verify.go` (+ `verify_test.go`). Find the
  JSON result struct; confirm it has no experiment fields.
- **Harden:** add the experiment block (at minimum `experiment_id`,
  `condition_id`, `repetition_index`, `slot_id`, `slot_attempt`) to the verify
  JSON result, sourced the same way manifest projection sources it. Add a test
  asserting verify JSON surfaces experiment fields for an experiment run and
  omits them cleanly for a non-experiment run.

### 2. Manifest experiment data sourced from `meta.json`, not `work-order.json`  (fragile coupling)
- **Claim (report F-004/F-010):** `addExperimentManifestFields` reads
  `meta["experiment"]`, not the archived `work-order.json`. If finalize writes
  the manifest but `meta.json`'s experiment block is missing/empty, experiment
  labels drop even though `work-order.json` (a required artifact) still has them.
- **Investigate:** `internal/manifest/manifest.go:384-410`
  (`addExperimentManifestFields`), `:98-128` (`BuildRunManifest`); confirm the
  source map. Check `internal/artifact/artifact.go:552,582` for the
  work-order -> meta experiment copy. Determine whether `manifest.json` and
  `meta.json` are written atomically together (if so, severity is lower).
- **Harden:** fall back to `work-order.json`'s experiment block when
  `meta["experiment"]` is absent. Add a test for the meta-missing path.

### 3. `rerun` is not attempt-aware  (attribution correctness)
- **Claim (report F-019/F-020):** `bakeoff rerun` copies the work order verbatim,
  so `run_kind` stays as authored (e.g. `pairwise`) and `slot_attempt` is
  unchanged — a rerun is indistinguishable from the original along the experiment
  axes, despite `rerun` being a valid `run_kind`.
- **Investigate:** `internal/commands/reruncmd/rerun.go:68,72,81,109,112` and
  `internal/commands/researchcmd/run.go:240,257,263,311-314` (judge-only path
  records `source_run_id`, `rerun_mode=judge_only`).
- **Decide + act:** either bump `run_kind=rerun` / increment `slot_attempt` on
  rerun, OR explicitly document that rerun is not attempt-aware and studies must
  manage repetition/attempt via fresh work orders (which
  `repetition-loop.sh` already does). Pick one; add a test or a doc note.

### 4. `ls` experiment-filter coverage is asymmetric  (ergonomics, low priority)
- **Claim (report F-012):** only `--experiment` and `--condition` filter flags
  exist; `task_id`, `run_kind`, `repetition_index`, `slot_id`, `slot_attempt`
  require `--json` + post-filter. All columns ARE emitted, so post-filtering works.
- **Investigate:** `internal/commands/lscmd/ls.go:30-31,87-88,130-136`;
  `docs/cli-reference.md:444-451` (flags table).
- **Optional harden:** add filter flags for the remaining experiment fields, or
  document the `--json` + post-filter pattern as the intended path.

### 5. Docs gaps  (low priority)
- **Claim (report F-005):** `docs/work-orders.md:195-229` documents the
  experiment block but does not state (a) manifest projection sources from
  `meta.json`, or (b) `verify --json` omits experiment fields.
- **Act:** add both notes once #1/#2 are resolved (so docs match final behavior).

### 6. Gemini evaluator reads are blocked by `runs/` being gitignored  (CONFIRMED; convention, not code)
- **Observed (live run `bakeoff-live-agent-eval.r001.evaluator`):** a single-provider
  `analyze` worker on `gemini/pro`, tasked to read the six prior r001 run dirs
  under `runs/`, could only read the repo-root `*.multi-lens-summary.md`. It
  reported `status: complete_with_concerns`: it could not compute single/pairwise
  scores, precision, union coverage, or any lift metric. Root cause: gemini's file
  tools honor `.gitignore`, and `runs/` is gitignored (`bakeoff/.gitignore:5`).
- **Scope of impact (verified against source):**
  - `claude` and `codex` workers are **unaffected** — their read tool / sandbox do
    not filter on `.gitignore`.
  - The **judge phase is unaffected** for all providers, including gemini-as-judge:
    judge inputs are built inline from worker outputs
    (`runSingleJudge` → `prompt.BuildJudgePrompt`, `internal/commands/researchcmd/run.go`)
    and passed as the prompt, never read from `runs/`. Triage is likewise fed
    inline (`internal/triage/citation.go`).
  - So this bites exactly one case: a **gemini worker whose task input lives under a
    gitignored path** (i.e. meta-evaluation of prior runs).
- **Rejected fix (option 3 — disabling gitignore in the gemini adapter):** not
  surgical and carries risk. Gemini CLI 0.43.0 has no gitignore flag (only
  `--include-directories`, which still honors `.gitignore`); the only lever is the
  settings file `fileFiltering.respectGitIgnore`, which would require writing
  `./.gemini/settings.json` into the workspace CWD (collision/concurrency risk
  under shared-CWD pairwise/parallel runs; `.gemini/` is already a protected path
  at `internal/commands/buildcmd/scope.go:222`) and would broaden gemini's reads to
  secrets/`*.pem`/run noise in **every** codebase run — the opposite of scope's
  purpose.
- **Resolution (option 1 — convention, no code change):** the harness already
  parameterizes the output dir (`OUT_DIR="${OUT_DIR:-runs}"` in
  `examples/repetition-loop.sh`). When a batch will be meta-evaluated by a gemini
  worker, run it with `OUT_DIR` set to a **non-gitignored** dir (e.g.
  `OUT_DIR=experiments`); `<out>/<run-id>/` stays `show`/`ls`/`history`-compatible
  via `--out`, and the evaluator's `runs/`-relative reads become `experiments/`
  reads that gemini can see. Alternatively, run the evaluator on `claude`/`codex`.
  Do **not** rely on a gemini worker reading `runs/` directly.
- **Tracked by:** beads `mstefanko-plugins-a7xw`.

## Explicit non-issues (do not act)
- **Empty-vs-absent `slot_id` (report F-003/F-011):** moot — `slot_id` validates
  as a non-empty slug (`^[A-Za-z0-9][A-Za-z0-9._-]*$`), so it cannot be set to an
  explicit empty string. Verify the regex at `internal/workorder/workorder.go`
  (~`:773-807`) before closing.
- **Codex 487KB stderr truncated to 60000 (`output_truncation_count: 1`):**
  generic provider noise, unrelated to the experiment feature.

## Open questions a new agent should close
- F-024 is now confirmed (verify omits experiment) — see finding #1.
- F-022: how/when `meta.json` gets the experiment block at runtime
  (`internal/artifact/artifact.go:552,582` is the lead).
- F-025: whether `rerun` preserves experiment into the NEW run's `meta.json`
  (tied to finding #3).

## Definition of done
- Findings #1 and #2 implemented with tests (the two real robustness items).
- Finding #3 resolved by code or an explicit doc decision.
- Findings #4/#5 either done or consciously deferred with a one-line rationale.
- Each report `file:line` claim cited above confirmed against the current tree
  before the corresponding change lands.
- `bin/swarm test` (or `go test ./...`) green for touched packages.

## Suggested next Bakeoff move
Either a focused **code-review** bakeoff over the experiment-metadata diff, or a
**build** work order targeting findings #1 + #2. Draft + preview before writing.
